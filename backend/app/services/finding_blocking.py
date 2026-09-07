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

from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import Finding, FindingOrigin, FindingResolutionStatus, FindingStatus
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


class FindingBreakdown(BaseModel):
    """The in-scope findings split by the system that produced them (LP-UI-021).

    A single total merges three generators into one number. LP-375 keeps the
    governed rule engine and the legacy AI sweep structurally separate, and a
    banner reading "91 unresolved findings" is that separation collapsed into a
    figure a processor cannot reconcile with anything on screen — on LF-96SV the
    tabs show 75 governed and 13 legacy, and the missing 3 appear nowhere at all.

    Counted PER SYSTEM, never as a remainder. `other` exists so a generator this
    split does not know about gets its own visible number rather than being
    absorbed into whichever bucket happens to be computed last: a labelled count
    derived by subtraction cannot be wrong about its label, so nothing looks like
    a claim (LP-UI-020 review).
    """

    #: The governed rule engine — findings that carry an `evaluation_outcome`.
    governed: int = 0
    #: Deterministic cross-source rules (`xsrc.*`), which carry no outcome.
    cross_source: int = 0
    #: The legacy AI sweep (LP-375's quarantine).
    legacy: int = 0
    #: Any generator the three above do not describe. Never silently folded in.
    other: int = 0

    @property
    def total(self) -> int:
        return self.governed + self.cross_source + self.legacy + self.other


def breakdown_by_system(findings: Sequence[Finding]) -> FindingBreakdown:
    """Split findings by the generator that produced them. See `FindingBreakdown`."""
    counts = FindingBreakdown()
    for finding in findings:
        if finding.evaluation_outcome is not None:
            counts.governed += 1
        elif finding.origin is FindingOrigin.DETERMINISTIC_RULE:
            counts.cross_source += 1
        elif finding.origin is FindingOrigin.AI_CROSS_SOURCE:
            counts.legacy += 1
        else:
            counts.other += 1
    return counts


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
