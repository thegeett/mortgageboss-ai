"""Company audit log service — recording admin actions (LP-MB-Admin-01, ADR-441).

:func:`log_company_action` is the one way to append to ``company_audit_log``, the company-level
counterpart of :func:`app.services.activity_log.log_activity`. ``detail`` carries
``{"changes": field_changes(before, after)}`` plus action-specific keys, built by the caller with
the same :func:`~app.services.activity_log.field_changes` the activity log uses.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, Select, Uuid, func, literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.models.company import Company
from app.models.company_audit_log import CompanyAuditLog
from app.schemas.audit import AuditActor, AuditEntry, AuditPage
from app.services.authorization import ensure
from app.services.override_attribution import resolve_user_names

if TYPE_CHECKING:
    from app.api.dependencies import Actor


class AuditAction(StrEnum):
    """What an admin did. The only writer of ``company_audit_log.action``.

    The column has no CHECK (ADR-441), so adding a member here needs no migration.
    """

    #: `scripts/transfer_owner` moved `companies.owner_user_id`.
    OWNER_TRANSFERRED = "owner_transferred"
    #: The LP-MB-Admin-01 migration copied `users.role` into `user_roles` and set the owner.
    ROLE_BACKFILLED = "role_backfilled"
    #: An admin changed `companies.settings` (`PATCH /company/settings`, LP-MB-Admin-02).
    COMPANY_SETTINGS_CHANGED = "company_settings_changed"
    #: People (LP-MB-Admin-03): an admin changed a person's details, roles or access.
    USER_DETAILS_CHANGED = "user_details_changed"
    USER_ROLES_CHANGED = "user_roles_changed"
    USER_DEACTIVATED = "user_deactivated"
    USER_REACTIVATED = "user_reactivated"
    #: Invitations (LP-MB-Admin-04). Never the token, raw or hashed.
    INVITE_SENT = "invite_sent"
    INVITE_RESENT = "invite_resent"
    INVITE_REVOKED = "invite_revoked"
    INVITE_ACCEPTED = "invite_accepted"
    #: An admin tried to invite an address that is a user of another company (ADR-444).
    INVITE_REFUSED_FOREIGN_EMAIL = "invite_refused_foreign_email"
    #: A departing person's file places moved to someone else (LP-MB-Admin-05).
    LOANS_REASSIGNED = "loans_reassigned"


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


def encode_cursor(created_at: datetime, entry_id: UUID) -> str:
    """The position after a row, as an opaque string: ``<iso time>_<id>``."""
    return f"{created_at.isoformat()}_{entry_id}"


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    """Inverse of :func:`encode_cursor`. Raises ``ValueError`` on anything else."""
    at, _, entry_id = cursor.rpartition("_")
    return datetime.fromisoformat(at), UUID(entry_id)


async def list_audit_log(
    db: AsyncSession,
    actor: "Actor",
    *,
    target_type: str | None = None,
    target_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    since: datetime | None = None,
    before: tuple[datetime, UUID] | None = None,
    limit: int = 50,
) -> AuditPage:
    """The actor's company's audit rows, newest first (``audit.view``).

    Paged by cursor, ``(created_at, id)`` of the last row returned, so a row written while someone
    is paging neither repeats nor skips. Actor and target names are resolved here, in one query.
    """
    ensure(actor, Permission.AUDIT_VIEW)
    filtered: Select[Any] = select(CompanyAuditLog).where(
        CompanyAuditLog.company_id == actor.company_id
    )
    if target_type is not None:
        filtered = filtered.where(CompanyAuditLog.target_type == target_type)
    if target_id is not None:
        filtered = filtered.where(CompanyAuditLog.target_id == target_id)
    if actor_user_id is not None:
        filtered = filtered.where(CompanyAuditLog.actor_user_id == actor_user_id)
    if since is not None:
        filtered = filtered.where(CompanyAuditLog.created_at >= since)
    # Counted on the first page only: the page shows the first page's count, and every "Load more"
    # recounting the whole filtered log would cost more as the log grows.
    total = (
        (await db.scalar(select(func.count()).select_from(filtered.subquery())) or 0)
        if before is None
        else None
    )

    page = filtered
    if before is not None:
        at, entry_id = before
        page = page.where(
            tuple_(CompanyAuditLog.created_at, CompanyAuditLog.id)
            < tuple_(literal(at, DateTime(timezone=True)), literal(entry_id, Uuid()))
        )
    page = page.order_by(CompanyAuditLog.created_at.desc(), CompanyAuditLog.id.desc())
    # One extra row says whether another page exists without a second count.
    rows = list(await db.scalars(page.limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]

    people = {row.actor_user_id for row in rows if row.actor_user_id is not None}
    people |= {row.target_id for row in rows if row.target_type == "user" and row.target_id}
    names = await resolve_user_names(db, people)
    # The effective company (ADR-443), not the actor's own row's company.
    company_name = await db.scalar(select(Company.name).where(Company.id == actor.company_id))

    def target_name(row: CompanyAuditLog) -> str | None:
        if row.target_type == "company":
            return company_name
        if row.target_type == "user" and row.target_id is not None:
            return names.get(row.target_id)
        return None

    items = [
        AuditEntry(
            id=row.id,
            created_at=row.created_at,
            actor=(
                AuditActor(id=row.actor_user_id, name=names.get(row.actor_user_id, "A former user"))
                if row.actor_user_id is not None
                else None
            ),
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            target_name=target_name(row),
            summary=row.summary,
            detail=row.detail,
        )
        for row in rows
    ]
    last = rows[-1] if rows and more else None
    return AuditPage(
        items=items,
        next_cursor=encode_cursor(last.created_at, last.id) if last is not None else None,
        total=total,
    )
