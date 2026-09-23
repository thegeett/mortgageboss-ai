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

from sqlalchemy import Date, ForeignKey, Index, Text
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
    #: rest of it — the reader name, the counts, the typed failure reason — is exactly what a
    #: staging query needs, so the readonly view exposes those as separate scalars rather than
    #: exposing the column.
    parse_report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    loan_file: Mapped["LoanFile"] = relationship()
    lender: Mapped["Lender | None"] = relationship()

    def __repr__(self) -> str:
        return f"<ConditionRound {self.status} round={self.round_number} file={self.loan_file_id}>"
