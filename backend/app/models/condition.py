"""One lender condition, living across rounds (LP-904, ADR-403/404/407).

A condition is **the lender's demand, in the lender's words**. It is not a need — a need is our ask
for a document, in our words, which we may rewrite and close. ADR-403 is the argument; this table is
the consequence.

IT LIVES ACROSS ROUNDS. `first_round_id` is where it was first seen and `last_seen_round_id` is the
most recent sheet carrying it. A condition absent from a later sheet is **not touched** in Stage 1 —
not cleared, not removed, not flagged. Stage 2 compares rounds and proposes; only the lender clears
(ADR-404).

THE TWO STATUS FIELDS ARE WRITTEN ONCE AND NEVER MOVED IN STAGE 1. `prep_status` is our preparation
and `lender_status` is the lender's answer. They exist here because LP-904 is where the schema is
designed, and leaving them for later would mean a second migration over a table that by then has
rows. Nothing in Stage 1 changes either.

`verbatim_text` vs `text_fingerprint` — the distinction the matching depends on. The text keeps the
underwriter's dated notes (they are part of what the lender wrote); the fingerprint is taken with
those note spans REMOVED, so a condition that comes back with a new note is still recognised as the
same condition rather than as a new one.

NPI (ADR-405): `verbatim_text` and `underwriter_notes`. `text_fingerprint` is not — it is a sha256,
and it is the column that lets the readonly layer answer "did this condition recur?" without
reproducing a word of it.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import MEDIUM_STRING, SHORT_STRING

if TYPE_CHECKING:
    from app.models.condition_round import ConditionRound
    from app.models.lender import Lender
    from app.models.loan_file import LoanFile


class BucketKind(StrEnum):
    """WHEN a condition must be satisfied, normalised from the lender's own heading.

    The heading itself is kept verbatim in `bucket_heading`; this is the reading of it. The kind
    follows the parenthetical rather than the words — UWM's "Prior To Final Approval (PTD)" is
    PRIOR_TO_DOCS, and reading the words instead would file it under approval.
    """

    MASTER = "master"
    PRIOR_TO_APPROVAL = "prior_to_approval"
    PRIOR_TO_DOCS = "prior_to_docs"
    PRIOR_TO_CLOSING = "prior_to_closing"
    PRIOR_TO_FUNDING = "prior_to_funding"
    LENDER_TO_CLEAR = "lender_to_clear"  # the lender is doing it; no ask goes out
    TRAILING = "trailing"
    UNKNOWN = "unknown"  # recognised as a heading, not as one of the above — always with a warning


class OwnerHint(StrEnum):
    """Who probably has to act. A HINT, never a decision — Stage 3 decides."""

    BORROWER = "borrower"
    TITLE = "title"
    INSURANCE = "insurance"
    LENDER = "lender"
    BROKER = "broker"
    PROCESSOR = "processor"
    UNKNOWN = "unknown"


class OwnerHintSource(StrEnum):
    """Where the hint came from, so a processor can weigh it.

    Carried because the hints are not equally good: a `TC:` prefix the lender typed is far stronger
    evidence than a default looked up from the code map, and a UI that showed them identically would
    invite trusting the weak one.
    """

    PREFIX = "prefix"  # the lender's own marker — "TC:", "(PA)"
    BUCKET = "bucket"  # the heading says so — "Underwriter To Obtain And Clear"
    CODE_MAP = "code_map"  # the (lender, code) default
    NONE = "none"


class ConditionPrepStatus(StrEnum):
    """OUR preparation track (ADR-404). Not moved in Stage 1."""

    TO_DO = "to_do"
    WAITING = "waiting"
    REVIEW = "review"
    READY = "ready"
    WITH_UNDERWRITER = "with_underwriter"


class ConditionLenderStatus(StrEnum):
    """THE LENDER'S answer (ADR-404). Nothing but a recorded verdict moves this."""

    OPEN = "open"
    PENDING_REVIEW = "pending_review"
    CLEARED = "cleared"
    NOT_CLEARED = "not_cleared"
    WAIVED = "waived"
    SUPERSEDED = "superseded"


class ConditionOrigin(StrEnum):
    """Whether the condition came off a sheet or was typed by a processor."""

    SHEET = "sheet"
    MANUAL = "manual"


class Condition(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One lender condition on one loan file."""

    __tablename__ = "conditions"
    __table_args__ = (
        Index("ix_conditions_loan_file_id", "loan_file_id"),
        Index("ix_conditions_company_id", "company_id"),
        # The two lookups import does, in the order it does them: (code, fingerprint) then
        # fingerprint alone. Both are per file, and the code one is per lender because a code means
        # nothing across lenders (ADR-407).
        Index("ix_conditions_file_lender_code", "loan_file_id", "lender_id", "lender_code"),
        Index("ix_conditions_file_fingerprint", "loan_file_id", "text_fingerprint"),
    )

    #: On the row, not inherited — a condition is reached directly by id, so the scoping filter
    #: needs a column here (same reasoning as `ConditionRound.company_id`).
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), nullable=False
    )
    lender_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("lenders.id", ondelete="RESTRICT"), nullable=True
    )

    first_round_id: Mapped[UUID] = mapped_column(
        ForeignKey("condition_rounds.id", ondelete="RESTRICT"), nullable=False
    )
    last_seen_round_id: Mapped[UUID] = mapped_column(
        ForeignKey("condition_rounds.id", ondelete="RESTRICT"), nullable=False
    )
    #: Its order on the latest sheet it appeared on — so the list can read in sheet order, which is
    #: the order the processor sees in the lender's portal.
    sequence: Mapped[int] = mapped_column(nullable=False, default=0)

    #: EXACTLY AS PRINTED, leading zeros kept (ADR-407). `String`, never an int: "0006" is an
    #: identifier printed on a document, and normalising it to 6 is a silent loss that surfaces
    #: months later as a failed match.
    lender_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: The lender's own category column ("Assets", "Invoice", "HOI"), or a Champions section
    #: category. Kept as printed; it is the lender's vocabulary, not ours.
    lender_category: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    #: The heading exactly as printed, soft hyphens normalised and nothing else changed.
    bucket_heading: Mapped[str] = mapped_column(String(MEDIUM_STRING), nullable=False)
    bucket_kind: Mapped[BucketKind] = mapped_column(
        str_enum(BucketKind), default=BucketKind.UNKNOWN, nullable=False
    )

    #: ⚠️ NPI — the lender's words. Soft hyphen → "-", non-breaking space → space, whitespace
    #: collapsed, and NOTHING else. Never paraphrased.
    verbatim_text: Mapped[str] = mapped_column(Text, nullable=False)
    #: sha256 of the normalised text WITH UNDERWRITER NOTES REMOVED. Not NPI, and it is what the
    #: matching runs on — which is why the text itself never has to be compared in SQL.
    text_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    #: ⚠️ NPI — `[{date, text, first_seen_round_id}]`. A dated note the underwriter appended inside
    #: the condition's text, meaning it came back. Kept as structure AND left inside `verbatim_text`:
    #: the lender wrote one string, and a UI that showed the note as ours would misattribute it.
    underwriter_notes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )

    owner_hint: Mapped[OwnerHint] = mapped_column(
        str_enum(OwnerHint), default=OwnerHint.UNKNOWN, nullable=False
    )
    owner_hint_source: Mapped[OwnerHintSource] = mapped_column(
        str_enum(OwnerHintSource), default=OwnerHintSource.NONE, nullable=False
    )
    #: From the code map — a line that tells the processor something rather than asking for anything.
    info_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: The canonical condition type, from the code map. Stage 3 fills the rest of the taxonomy.
    canonical_type_id: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)

    #: ⚠️ Both created here and NOT MOVED IN STAGE 1 (ADR-404).
    prep_status: Mapped[ConditionPrepStatus] = mapped_column(
        str_enum(ConditionPrepStatus), default=ConditionPrepStatus.TO_DO, nullable=False
    )
    lender_status: Mapped[ConditionLenderStatus] = mapped_column(
        str_enum(ConditionLenderStatus), default=ConditionLenderStatus.OPEN, nullable=False
    )
    origin: Mapped[ConditionOrigin] = mapped_column(
        str_enum(ConditionOrigin), default=ConditionOrigin.SHEET, nullable=False
    )

    loan_file: Mapped["LoanFile"] = relationship()
    lender: Mapped["Lender | None"] = relationship()
    first_round: Mapped["ConditionRound"] = relationship(foreign_keys=[first_round_id])
    last_seen_round: Mapped["ConditionRound"] = relationship(foreign_keys=[last_seen_round_id])

    def __repr__(self) -> str:
        return f"<Condition {self.lender_code or '—'} {self.bucket_kind} file={self.loan_file_id}>"
