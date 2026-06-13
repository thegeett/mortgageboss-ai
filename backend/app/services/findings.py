"""Finding service — resolution operations (LP-17).

Resolution state on a finding (status + who/when/why) is an audit trail, so it
should always be written together. :func:`resolve_finding` centralizes that:
callers set a finding's resolution through it rather than mutating the fields
directly, guaranteeing the trail is consistent.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.finding import Finding, FindingResolutionStatus


async def resolve_finding(
    db: AsyncSession,
    *,
    finding: Finding,
    resolution_status: FindingResolutionStatus,
    user_id: UUID,
    note: str | None = None,
) -> Finding:
    """Set a finding's resolution state with an audit trail.

    For a resolution (``RESOLVED`` / ``ACCEPTED_RISK`` / ``WAIVED``): records the
    ``resolution_status``, the ``note``, the acting ``user_id`` (``resolved_by``),
    and ``resolved_at`` = now (timezone-aware).

    For **re-opening** (``resolution_status=OPEN``): the finding returns to OPEN
    and the resolution trail is cleared (``resolution_note``,
    ``resolved_by_user_id``, ``resolved_at`` set to ``None``) — a re-opened
    finding is, by definition, no longer resolved. The ``user_id``/``note`` args
    are ignored in this case (the activity log, a later ticket, is where "who
    re-opened" is recorded).

    Uses ``flush`` rather than ``commit`` so the caller controls the transaction.
    """
    if resolution_status is FindingResolutionStatus.OPEN:
        finding.resolution_status = FindingResolutionStatus.OPEN
        finding.resolution_note = None
        finding.resolved_by_user_id = None
        finding.resolved_at = None
    else:
        finding.resolution_status = resolution_status
        finding.resolution_note = note
        finding.resolved_by_user_id = user_id
        finding.resolved_at = utcnow()

    await db.flush()
    return finding
