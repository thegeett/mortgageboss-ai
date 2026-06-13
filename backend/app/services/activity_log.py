"""Activity log service — recording events on a loan file (LP-20).

:func:`log_activity` is the single standard way to append an entry to a loan
file's audit trail. Operations call it to record what happened; wiring it into
every operation is incremental (ADR-071), not done all at once.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog, ActivityType
from app.models.helpers import only_active


async def log_activity(
    db: AsyncSession,
    *,
    loan_file_id: UUID,
    activity_type: ActivityType,
    summary: str,
    actor_user_id: UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> ActivityLog:
    """Record an activity on a loan file (append-only audit trail).

    ``actor_user_id`` is ``None`` for system-generated events. ``detail`` holds
    type-specific structured data (defaults to ``{}``). Uses ``flush`` rather than
    ``commit`` so the caller controls the transaction.
    """
    entry = ActivityLog(
        loan_file_id=loan_file_id,
        activity_type=activity_type,
        summary=summary,
        actor_user_id=actor_user_id,
        detail=detail or {},
    )
    db.add(entry)
    await db.flush()
    return entry


async def list_recent_activity(
    db: AsyncSession, *, loan_file_id: UUID, limit: int = 20
) -> list[ActivityLog]:
    """The file's recent activity (LP-34), most-recent-first, capped at ``limit``.

    Takes an already scope-checked ``loan_file_id`` (the endpoint resolves the
    parent file with the caller's company first). Excludes soft-deleted rows.
    """
    stmt = select(ActivityLog).where(ActivityLog.loan_file_id == loan_file_id)
    stmt = only_active(stmt, ActivityLog)
    stmt = stmt.order_by(ActivityLog.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())
