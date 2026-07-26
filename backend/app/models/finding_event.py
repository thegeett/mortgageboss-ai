"""Per-finding append-only event log (LP-316) — the finding lifecycle history.

Findings had no per-finding history: the general :class:`~app.models.activity_log.ActivityLog` is
keyed to the loan FILE, not to a finding, and the current reconcile mutates-in-place / soft-deletes
(LP-94). This table records each state transition of ONE finding — created, its outcome changed,
resolved, retired — as an immutable, insert-only row. It is the substrate for the four-tab
lifecycle + no-longer-needed retirement + the immortality guarantee (§3D), which LP-322 builds on.

This ticket is SINGLE-RUN: only the ``created`` event (with the initial outcome) is emitted here;
cross-run transitions (outcome_changed / resolved / retired) are wired in LP-322.

Append-only: insert-only, no ``updated_at`` and no soft-delete (a ``TimestampMixin`` would add
``updated_at``; a ``SoftDeleteMixin`` would allow a mutating delete). ``occurred_at`` is the
event's own timestamp. Owned by the finding (CASCADE): a hard-deleted finding takes its events.
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
from app.models.finding import EvaluationOutcome

if TYPE_CHECKING:
    from app.models.finding import Finding


class FindingEventType(StrEnum):
    """What happened to a finding. ``CREATED`` is emitted single-run (LP-316); the rest are the
    cross-run reconciliation transitions (LP-322)."""

    CREATED = "created"  # the finding was first persisted / minted (with its initial outcome)
    CARRIED_FORWARD = "carried_forward"  # a re-run re-detected it, unchanged (LP-322)
    OUTCOME_CHANGED = "outcome_changed"  # a re-run changed its evaluation outcome (LP-322)
    RESOLVED = "resolved"  # open → satisfied: the rule now PASSES for the subject (LP-322)
    RETIRED = "retired"  # the SUBJECT is no longer detected → no_longer_applies (LP-322)
    REVIVED = "revived"  # a retired finding's subject reappeared → back on the surface (LP-322)


class FindingEvent(Base, UUIDMixin):
    """One immutable state-transition of a finding — the append-only lifecycle history."""

    __tablename__ = "finding_events"
    __table_args__ = (
        # One finding's events, in time order — the shape a lifecycle-history read wants (LP-322).
        # A composite (finding_id, occurred_at) also serves plain finding_id lookups (prefix), so no
        # separate single-column index is needed.
        Index("ix_finding_events_finding_occurred", "finding_id", "occurred_at"),
    )

    # The finding this event belongs to (CASCADE — events die with a hard-deleted finding).
    finding_id: Mapped[UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[FindingEventType] = mapped_column(str_enum(FindingEventType), nullable=False)
    # The outcome transition this event records (both null for a non-outcome event). Distinct
    # constraint names because one enum backs two columns on the same table.
    from_outcome: Mapped[EvaluationOutcome | None] = mapped_column(
        str_enum(EvaluationOutcome, name="finding_event_from_outcome"), nullable=True
    )
    to_outcome: Mapped[EvaluationOutcome | None] = mapped_column(
        str_enum(EvaluationOutcome, name="finding_event_to_outcome"), nullable=True
    )
    # PII-safe structured context (e.g. the actor, a reason) — never raw borrower data.
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    finding: Mapped["Finding"] = relationship()

    def __repr__(self) -> str:
        return f"<FindingEvent {self.event_type} finding_id={self.finding_id} to={self.to_outcome}>"
