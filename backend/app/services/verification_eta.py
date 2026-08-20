"""How long this file's verification usually takes (LP-591).

Measured before building, on 29 completed runs of one real file: mean 384s, fastest 336s, slowest
454s, standard deviation 28s. A ~7% coefficient of variation is what makes an estimate honest here —
it is good to roughly half a minute over a six-and-a-half-minute wait.

WHY HISTORY AND NOT ARITHMETIC ON THE PHASE. The obvious estimate is
`elapsed / phase_index * phase_total`, and it would be wrong for the same reason a progress BAR is
wrong: stage A scales with the file's transaction count, so the phases are nowhere near evenly
sized, and that formula would swing wildly as each boundary is crossed.

PER FILE FIRST. A file's own history already encodes its size, its document count and its
transaction volume — the things that actually drive the duration — so it beats any global average
without modelling any of them.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.verification import Verification, VerificationStatus

# Enough runs to have a median worth trusting, few enough to follow a file that got bigger.
_WINDOW = 10
# Below this, one unlucky run IS the median. Better to show nothing than a number built on a sample
# of one — a wrong ETA is worse than no ETA, because it teaches a processor to distrust the panel.
_MIN_RUNS = 3

_DURATION = func.extract("epoch", Verification.completed_at - Verification.started_at).cast(Float)


async def estimated_seconds(db: AsyncSession, *, loan_file_id: UUID) -> int | None:
    """The MEDIAN duration of this file's recent completed runs, or None when there is no basis.

    Median rather than mean: the slowest observed run was 70 seconds above the mean, and a single
    outlier like that should not push every future estimate up.
    """
    recent = (
        select(_DURATION.label("seconds"))
        .where(
            Verification.loan_file_id == loan_file_id,
            Verification.status == VerificationStatus.COMPLETED,
            Verification.completed_at.is_not(None),
            Verification.started_at.is_not(None),
        )
        .order_by(Verification.started_at.desc())
        .limit(_WINDOW)
        .subquery()
    )
    row = (
        await db.execute(
            select(
                func.percentile_cont(0.5).within_group(recent.c.seconds),
                func.count(recent.c.seconds),
            )
        )
    ).one()
    median, count = row
    if median is None or count < _MIN_RUNS:
        return None
    return int(median)
