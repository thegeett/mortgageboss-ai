"""Append-only history for rounds and conditions (LP-904, spec §9.7).

Copies `finding_event.py`'s pattern, which enforces append-only **by shape**: `Base, UUIDMixin` and
nothing else. A `TimestampMixin` would add an `updated_at` that can only ever lie on a row nothing
updates; a `SoftDeleteMixin` would permit a mutating delete. `occurred_at` is the event's own time.

TWO DIFFERENCES FROM `FindingEvent`, both deliberate:

1. **It carries `company_id`.** A finding event is reached only through its finding, so it scopes
   transitively (ADR-052). A condition event is read directly — the round-details sheet builds its
   history from these rows by round id — so the scoping filter needs a column on the row.
2. **`detail` is NPI.** `FindingEvent.detail` is documented as "PII-safe structured context … never
   raw borrower data". This one holds what CHANGED: an edited wording, a note that was appended, the
   bucket a condition moved between. That is the lender's text, so the column is dropped from
   `readonly.condition_events` rather than scrubbed.

⚠️ THERE WAS NO TEST TO COPY. `finding_event.py`'s immutability is asserted nowhere in the suite —
every test that touches it only READS event rows to check a lifecycle sequence. LP-904 writes that
guard for this table from scratch (`tests/models/test_condition_events_append_only.py`).
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin, utcnow
from app.models.enums import str_enum

if TYPE_CHECKING:
    from app.models.loan_file import LoanFile


class ConditionEventKind(StrEnum):
    """What happened. Stage 1 emits all of these and nothing else.

    Note what is ABSENT and stays absent until Stage 2: there is no `CONDITION_CLEARED`, no
    `CONDITION_REMOVED` and no `ROUND_COMPARED`. Stage 1 cannot produce them, and an enum member
    nothing writes is an invitation (ADR-404).
    """

    ROUND_RECEIVED = "round_received"
    ROUND_PARSED = "round_parsed"
    ROUND_PARSE_FAILED = "round_parse_failed"
    ROUND_IMPORTED = "round_imported"
    ROUND_DISCARDED = "round_discarded"
    #: A round gained a later source — the PDF for a round that was pasted (LP-907).
    ROUND_ENRICHED = "round_enriched"
    CONDITION_CREATED = "condition_created"
    CONDITION_SEEN_AGAIN = "condition_seen_again"
    CONDITION_NOTE_ADDED = "condition_note_added"
    CONDITION_EDITED = "condition_edited"


class ConditionEvent(Base, UUIDMixin):
    """One immutable record of something that happened to a round or a condition."""

    __tablename__ = "condition_events"
    __table_args__ = (
        # One round's history in time order — the shape the round-details sheet reads (S1-09). A
        # composite also serves a plain round_id lookup by prefix, so no second index is needed.
        Index("ix_condition_events_round_occurred", "round_id", "occurred_at"),
        Index("ix_condition_events_condition_occurred", "condition_id", "occurred_at"),
        Index("ix_condition_events_loan_file_id", "loan_file_id"),
    )

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), nullable=False
    )
    #: Both nullable and at least one is set in practice: a round event has no condition, a
    #: condition event names the round it was seen on. Not enforced as a CHECK because
    #: `CONDITION_EDITED` outside an import legitimately has no round.
    round_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("condition_rounds.id", ondelete="CASCADE"), nullable=True
    )
    condition_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conditions.id", ondelete="CASCADE"), nullable=True
    )

    kind: Mapped[ConditionEventKind] = mapped_column(str_enum(ConditionEventKind), nullable=False)
    #: Null for a system event — a parse task has no actor, and naming the processor who uploaded
    #: the sheet as the actor of the parse would make the trail say something untrue.
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: ⚠️ NPI — what changed, which is the lender's text. Dropped from the readonly view.
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    loan_file: Mapped["LoanFile"] = relationship()

    def __repr__(self) -> str:
        return f"<ConditionEvent {self.kind} file={self.loan_file_id}>"
