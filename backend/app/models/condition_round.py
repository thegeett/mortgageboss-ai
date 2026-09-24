"""One condition sheet received for a loan file (LP-904, ADR-403).

A **round** is the sheet, not the underwriting cycle that produced it — the glossary keeps that
distinction: "the cycle is the event, the round is the sheet it produced". Round 1 is the first
approval; later rounds are re-issues after the processor submits documents.

NOTHING HERE IS SAVED AS CONDITIONS UNTIL A PROCESSOR IMPORTS. A round arrives `PARSING`, becomes
`DRAFT` with its parsed rows in `draft_rows`, and only `import` (LP-909) turns those rows into
`conditions`. That is why `draft_rows` exists as a column rather than as rows in `conditions`: an
unreviewed parse must not be indistinguishable from the lender's confirmed list.

`round_number` IS ASSIGNED ON IMPORT, NOT ON ARRIVAL. Two drafts can exist at once (an upload and a
paste), and numbering them on arrival would either renumber on import or leave gaps where a draft was
discarded. Null until imported, unique per file among imported rows.

`sources` IS A LIST BECAUSE A ROUND CAN BE ENRICHED. A pasted round whose PDF arrives later MERGES
into that round (LP-907) rather than creating a second one, so the round carries every way it arrived
rather than one.

NPI (ADR-405): `raw_text`, `header`, `draft_rows`, and `parse_report.unassigned_lines`. All are
dropped from `readonly.condition_rounds`. `expiry_dates` is NOT NPI — it is a table of dates the
lender publishes about the loan, naming nobody.
"""

from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum

if TYPE_CHECKING:
    from app.models.lender import Lender
    from app.models.loan_file import LoanFile


class ConditionRoundStatus(StrEnum):
    """Where a round is between arriving and being imported."""

    PARSING = "parsing"  # the task is reading it
    DRAFT = "draft"  # read, awaiting the processor's review — NOTHING is saved as conditions yet
    PARSE_FAILED = "parse_failed"  # the reason is in `parse_report`, typed
    IMPORTED = "imported"  # its rows became conditions; `round_number` assigned
    DISCARDED = "discarded"  # the processor threw the draft away


class ConditionRoundCompleteness(StrEnum):
    """Whether this round is the lender's WHOLE list or only part of it (ADR-404).

    The distinction is load-bearing rather than descriptive: absence is evidence only when the thing
    absent was in a list claiming to be complete. A `PARTIAL` source may add and update; it may never
    remove or clear.
    """

    FULL = "full"
    PARTIAL = "partial"


class ConditionSheetFormat(StrEnum):
    """Which layout the reader recognised (LP-906)."""

    UWM_APPROVAL_LETTER = "uwm_approval_letter"
    CHAMPIONS_CERTIFICATE = "champions_certificate"
    GENERIC = "generic"
    PASTED_TEXT = "pasted_text"


class ConditionSourceKind(StrEnum):
    """How one arrival of a round reached us. Recorded per entry in `sources`."""

    PDF_UPLOAD = "pdf_upload"
    EMAIL = "email"
    PASTE = "paste"
    MANUAL = "manual"


class ConditionRound(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One condition sheet received for a loan file."""

    __tablename__ = "condition_rounds"
    __table_args__ = (
        Index("ix_condition_rounds_loan_file_id", "loan_file_id"),
        Index("ix_condition_rounds_company_id", "company_id"),
        # The round strip reads a file's rounds newest-first; the status half serves the poll that
        # waits for PARSING to become DRAFT.
        Index("ix_condition_rounds_file_status", "loan_file_id", "status"),
        # ⚠️ DECLARED HERE **AND** CREATED BY RAW SQL IN LP-904's MIGRATION (`d1f4b8c25e93`), AND
        # BOTH HALVES ARE LOAD-BEARING. The migration half is what a deployed database has; this
        # half is what `Base.metadata.create_all` builds, and the suite builds from `create_all`
        # rather than from migrations. Until this was added the index existed in production and in
        # NO TEST DATABASE — measured, not inferred: two rounds numbered 2 on one file inserted
        # cleanly.
        #
        # That is the mirror of the trap LP-904 documented and then fell into. Its own ticket says
        # `str_enum`'s CHECK "only materialises through `Base.metadata.create_all` — which is what
        # the suite builds from, and precisely why an enum/database mismatch is invisible to it".
        # Same blind spot, opposite direction: an index that lives only in a migration is invisible
        # the same way. `lender_contacts` does both halves (`uq_lender_contacts_lender_email`) and
        # is the pattern followed here.
        #
        # It matters beyond tidiness because this index IS the rule. `loan_file_needs_lock` is
        # advisory — it yields `bool(acquired)`, every caller binds nothing, and its 30s timeout
        # auto-expires a HELD lock — so nothing else stops two concurrent imports computing the
        # same `max + 1`. LP-909's import catches the violation and recomputes; without this
        # declaration that retry is code no test could ever provoke.
        #
        # The predicate mirrors the migration exactly. Partial because drafts have no number at all
        # (it is assigned on import) and several NULLs must not collide; `deleted_at IS NULL` stays
        # so a soft delete releases the number as the visible consequence of a deliberate act.
        # DISCARDED is deliberately NOT in the predicate: a discarded round keeps its number,
        # because `condition_events` is append-only and its ROUND_IMPORTED event survives forever.
        Index(
            "uq_condition_rounds_file_number",
            "loan_file_id",
            "round_number",
            unique=True,
            postgresql_where=text("round_number IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    #: Carried rather than inherited through the loan file. A round is reached directly by id from
    #: `/api/condition-rounds/{id}`, so the scoping filter needs a column on this row — unlike a
    #: `Document`, which is only ever reached through its file (ADR-052).
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), nullable=False
    )
    #: The lender whose sheet this is. Nullable because a file may have no lender set when the first
    #: sheet arrives, and refusing the sheet would be the wrong way to learn that.
    lender_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("lenders.id", ondelete="RESTRICT"), nullable=True
    )

    #: Assigned on IMPORT. Null on a draft — see the module docstring.
    round_number: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[ConditionRoundStatus] = mapped_column(
        str_enum(ConditionRoundStatus), default=ConditionRoundStatus.PARSING, nullable=False
    )
    #: `[{kind, at, document_id?, inbound_attachment_id?, user_id?}]` — a LIST, because a pasted
    #: round enriched by its PDF keeps both arrivals rather than forgetting the first.
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    completeness: Mapped[ConditionRoundCompleteness] = mapped_column(
        str_enum(ConditionRoundCompleteness),
        default=ConditionRoundCompleteness.FULL,
        nullable=False,
    )
    sheet_format: Mapped[ConditionSheetFormat] = mapped_column(
        str_enum(ConditionSheetFormat), default=ConditionSheetFormat.GENERIC, nullable=False
    )

    #: The date the lender printed on the sheet. Null for a paste, which has none — and the review
    #: screen shows no "Date printed" chip in that case rather than inventing one.
    date_printed: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: `date_printed` when known, else the date received. Editable by the processor.
    round_date: Mapped[date] = mapped_column(Date, nullable=False)

    #: ⚠️ NPI — the sheet's full text. Dropped from `readonly.condition_rounds`.
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ⚠️ NPI — `{loan_facts, lender_team, dates, mortgagee_clause?}`. Names borrowers and the
    #: property, so it is dropped whole rather than scrubbed: a scrub matches identifier SHAPES, and
    #: a name is not digit-shaped.
    header: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: NOT NPI. Dates the lender publishes about the loan — close_by, appraisal, asset, credit … —
    #: naming nobody, and the one part of the letter an analyst has a real reason to ask about.
    expiry_dates: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: ⚠️ NPI — parsed rows awaiting review, each holding the lender's verbatim wording. Cleared on
    #: import, when the rows become `conditions`.
    draft_rows: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    #: `{reader, reader_version, warnings, unassigned_lines, duplicates_dropped, ai_used}`.
    #:
    #: ⚠️ NPI AS A WHOLE, because `unassigned_lines` holds lines lifted from the sheet verbatim. The
    #: readonly view therefore exposes derived scalars rather than the column: `reader`,
    #: `reader_version`, `ai_used`, `duplicates_dropped`, `warning_count`, `unassigned_count`.
    #:
    #: ⚠️ THE TYPED FAILURE REASON IS NOT AMONG THEM, and an earlier version of this comment said it
    #: was ("the reader name, the counts, the typed failure reason — is exactly what a staging query
    #: needs"). `failure_kind` and `failure_detail` are not projected by migration `d1f4b8c25e93`, so
    #: they are dropped with the column and never reach a staging query at all.
    #:
    #: That matters for what may be written INTO them: nothing here is ever scrubbed, because
    #: nothing here is ever exposed. A borrower's name quoted into `failure_detail` does not escape
    #: — it sits at rest in a column excluded precisely because it already carries sheet text, where
    #: nobody can inspect it to find it. Compose those strings; never quote the sheet (spec §9.5).
    parse_report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    loan_file: Mapped["LoanFile"] = relationship()
    lender: Mapped["Lender | None"] = relationship()

    def __repr__(self) -> str:
        return f"<ConditionRound {self.status} round={self.round_number} file={self.loan_file_id}>"
