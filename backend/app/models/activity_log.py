"""ActivityLog model — the audit trail / timeline of events on a loan file (LP-20).

Each entry records one notable event (file created, status changed, document
uploaded, finding resolved, verification run, needs item satisfied, communication
sent, …) with an optional acting user (null = system-generated), a human-readable
``summary``, and type-specific ``detail`` JSON. Together the entries are the file's
audit trail and UI timeline.

**Append-only in spirit (ADR-071):** entries are written, never edited or deleted
in normal operation — the history must stay trustworthy. (The soft-delete columns
come from the shared mixin for consistency, but activity entries are not deleted
in normal flow.) The :func:`app.services.activity_log.log_activity` helper is the
single standard way to record an event; wiring it into every operation happens
**incrementally** as operations are built, not all at once here.

A separate model from :class:`~app.models.communication.Communication` (ADR-070):
the activity log covers *all* events (including non-message ones like status
changes), while a communication carries message fields. Like other file-owned
children it has no ``company_id`` — scoped transitively through its loan file
(ADR-052).
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import MediumStr

if TYPE_CHECKING:
    from app.models.loan_file import LoanFile
    from app.models.user import User


class ActivityType(StrEnum):
    """Types of activities recorded on a loan file.

    A reasonable initial set; it grows over time as more operations are
    instrumented — adding a value is a trivial VARCHAR + CHECK change.
    """

    FILE_CREATED = "file_created"
    FILE_UPDATED = "file_updated"
    FILE_DELETED = "file_deleted"
    STATUS_CHANGED = "status_changed"
    DOCUMENT_UPLOADED = "document_uploaded"
    DOCUMENT_PROCESSED = "document_processed"
    FINDING_RESOLVED = "finding_resolved"
    VERIFICATION_RUN = "verification_run"
    NEEDS_ITEM_CREATED = "needs_item_created"
    NEEDS_ITEM_SATISFIED = "needs_item_satisfied"
    COMMUNICATION_SENT = "communication_sent"
    COMMUNICATION_RECEIVED = "communication_received"
    NOTE_ADDED = "note_added"


class ActivityLog(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One recorded event on a loan file (audit trail / timeline)."""

    __tablename__ = "activity_logs"

    # --- Ownership (owned child of the loan file, ADR-052) -----------------
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    activity_type: Mapped[ActivityType] = mapped_column(
        str_enum(ActivityType), index=True, nullable=False
    )
    # The user who performed the action; null = system-generated. SET NULL: the
    # log entry survives if the user is removed (the summary still records it).
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    summary: Mapped[MediumStr] = mapped_column(nullable=False)
    # Type-specific structured data, e.g. {"from": "in_processing", "to":
    # "submitted"}. Defaults to an empty dict.
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # --- Relationships -----------------------------------------------------
    loan_file: Mapped["LoanFile"] = relationship(back_populates="activity_logs")
    actor: Mapped["User | None"] = relationship()

    def __repr__(self) -> str:
        return f"<ActivityLog {self.activity_type} loan_file_id={self.loan_file_id}>"
