"""Verification service — minimal run creation (the engine is Phase 3, LP-18)."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.verification import (
    Verification,
    VerificationStatus,
    VerificationTrigger,
)


async def create_verification_run(
    db: AsyncSession,
    *,
    loan_file_id: UUID,
    trigger: VerificationTrigger,
) -> Verification:
    """Create a new verification run in ``RUNNING`` status.

    Records ``started_at = now`` (timezone-aware) with the summary counts at 0.
    The engine that evaluates rules, produces findings, and sets the counts and
    completion status is Phase 3 — this helper only creates the run record.

    Uses ``flush`` rather than ``commit`` so the caller controls the transaction.
    """
    run = Verification(
        loan_file_id=loan_file_id,
        status=VerificationStatus.RUNNING,
        trigger=trigger,
        started_at=utcnow(),
    )
    db.add(run)
    await db.flush()
    return run
