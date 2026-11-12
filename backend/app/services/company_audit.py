"""Company audit log service — recording admin actions (LP-MB-Admin-01, ADR-441).

:func:`log_company_action` is the one way to append to ``company_audit_log``, the company-level
counterpart of :func:`app.services.activity_log.log_activity`. ``detail`` carries
``{"changes": field_changes(before, after)}`` plus action-specific keys, built by the caller with
the same :func:`~app.services.activity_log.field_changes` the activity log uses.
"""

from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company_audit_log import CompanyAuditLog


class AuditAction(StrEnum):
    """What an admin did. The only writer of ``company_audit_log.action``.

    The column has no CHECK (ADR-441), so adding a member here needs no migration.
    """

    #: `scripts/transfer_owner` moved `companies.owner_user_id`.
    OWNER_TRANSFERRED = "owner_transferred"
    #: The LP-MB-Admin-01 migration copied `users.role` into `user_roles` and set the owner.
    ROLE_BACKFILLED = "role_backfilled"


async def log_company_action(
    db: AsyncSession,
    *,
    company_id: UUID,
    actor_user_id: UUID | None,
    action: AuditAction,
    target_type: str,
    target_id: UUID | None,
    summary: str,
    detail: dict[str, Any] | None = None,
) -> CompanyAuditLog:
    """Record an admin action in a company (append-only).

    ``actor_user_id`` is ``None`` for the system. Uses ``flush`` rather than ``commit`` so the
    caller controls the transaction.
    """
    entry = CompanyAuditLog(
        company_id=company_id,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        summary=summary,
        detail=detail or {},
    )
    db.add(entry)
    await db.flush()
    return entry
