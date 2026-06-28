"""Finding blocking computation (LP-75) — open in-scope findings block submission.

A loan file is **blocked** from "ready to submit" while it has any **open
in-scope** finding. *In-scope* = an actionable (red/yellow) **open** finding
whose **confidence is at or above the active cutoff** — so a low-confidence
hunch below the cutoff does not block. This is the locked "findings are blocking
— nothing silently ignored" principle made computational.

LP-75 owns the **computation** and runs it against a cutoff; **LP-79's aggression
dial** chooses the cutoff per file (a user default + a per-file override). Until
then the computation works standalone with :data:`DEFAULT_CONFIDENCE_CUTOFF`
(Balanced). Green findings are passes — they never block.

Tenant-scoped: callers pass a ``loan_file_id`` already resolved within the
company (the endpoint resolves the parent file with the caller's company first),
and findings are reachable only via that file.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import Finding, FindingResolutionStatus, FindingStatus
from app.models.helpers import only_active
from app.verification.confidence import DEFAULT_CONFIDENCE_CUTOFF

# Only actionable findings block; green is a passed check.
_BLOCKING_SEVERITIES = (FindingStatus.RED, FindingStatus.YELLOW)


async def open_in_scope_findings(
    db: AsyncSession,
    *,
    loan_file_id: UUID,
    confidence_cutoff: float = DEFAULT_CONFIDENCE_CUTOFF,
) -> list[Finding]:
    """The file's open, actionable findings at or above the cutoff (in-scope)."""
    stmt = only_active(
        select(Finding).where(
            Finding.loan_file_id == loan_file_id,
            Finding.resolution_status == FindingResolutionStatus.OPEN,
            Finding.status.in_(_BLOCKING_SEVERITIES),
            Finding.confidence >= confidence_cutoff,
        ),
        Finding,
    )
    return list((await db.execute(stmt)).scalars().all())


async def is_file_blocked(
    db: AsyncSession,
    *,
    loan_file_id: UUID,
    confidence_cutoff: float = DEFAULT_CONFIDENCE_CUTOFF,
) -> bool:
    """True if the file has any open in-scope finding (so it cannot submit).

    Resolving every in-scope finding (apply or override) unblocks the file;
    findings below the cutoff do not block (LP-79's dial sets the cutoff).
    """
    findings = await open_in_scope_findings(
        db, loan_file_id=loan_file_id, confidence_cutoff=confidence_cutoff
    )
    return len(findings) > 0
