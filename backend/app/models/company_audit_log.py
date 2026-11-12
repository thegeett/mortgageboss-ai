"""CompanyAuditLog model — what admins did in a company (LP-MB-Admin-01, ADR-441).

The activity log is a loan file's timeline: every row belongs to a file and goes with it (ADR-052,
ADR-071). Inviting a user, changing a role or moving the owner has no file, so those land here,
keyed by company.

Append-only: no ``updated_at``, no ``deleted_at``, and no code path that updates or deletes a row.
:func:`app.services.company_audit.log_company_action` is the one writer.

``action`` is a plain VARCHAR with **no CHECK** (ADR-441, a stated exception to ADR-037): each
admin ticket adds values, and the CHECK-swap pattern has caused two incidents on ``ActivityType``.
:class:`app.services.company_audit.AuditAction` is the only thing that writes it.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, utcnow
from app.models.types import MediumStr


class CompanyAuditLog(Base, UUIDMixin):
    """One admin action in a company."""

    __tablename__ = "company_audit_log"
    # Newest first within a company: how the log is read.
    __table_args__ = (
        Index("ix_company_audit_log_company_id_created_at", "company_id", text("created_at DESC")),
    )

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    #: NULL = the system (a migration or a platform script with no acting user).
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    #: `user`, `invite`, `company` or `loan_file`.
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[UUID | None] = mapped_column(nullable=True)
    summary: Mapped[MediumStr] = mapped_column(nullable=False)
    #: `{"changes": field_changes(before, after)}` plus action-specific keys.
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
