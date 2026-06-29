"""Activity log service — recording events on a loan file (LP-20).

:func:`log_activity` is the single standard way to append an entry to a loan
file's audit trail. Operations call it to record what happened; wiring it into
every operation is incremental (ADR-071), not done all at once.
"""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog, ActivityType
from app.models.helpers import only_active


def audit_value(value: Any) -> Any:
    """A JSON-safe scalar for the activity_log ``detail`` (exact, no lossy types).

    Decimals → str (exact precision), enums → their value, dates/datetimes → ISO
    8601, UUID → str; primitives pass through; ``None`` stays ``None``. So ``detail``
    can carry real from→to **values** (LP-80.5) without emitting a non-JSON type or
    losing decimal precision.
    """
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date | datetime):
        return value.isoformat()
    return str(value)


def field_changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[dict[str, Any]]:
    """``[{field, from, to}]`` for every key in ``after`` whose value changed.

    Values are :func:`audit_value`-encoded. This is the field-level change history
    behind the LP-80.5 audit — a deliberate change that **supersedes the LP-56
    value-free posture** for stated/loan/property edits. Because ``detail`` now holds
    financial/PII-adjacent values, it inherits the stated data's PII posture wherever
    the activity log is displayed (auth + tenant scoped, same as the stated data).
    """
    changes: list[dict[str, Any]] = []
    for field, new in after.items():
        old = before.get(field)
        if old != new:
            changes.append({"field": field, "from": audit_value(old), "to": audit_value(new)})
    return changes


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
