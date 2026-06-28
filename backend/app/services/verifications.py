"""Verification service — run creation + the cross-source staleness flag (LP-78).

The staleness flag (``LoanFile.verification_stale``) is the V1 model for "the
documents changed — re-run verification": it is set on any document change and
when a finding is applied (the structured data changed), and cleared when the
cross-source pass re-runs. Auto-re-run is deferred (the dial re-filters
already-computed findings without re-running — LP-79).
"""

from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.loan_file import LoanFile
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


async def mark_verification_stale(db: AsyncSession, *, loan_file_id: UUID) -> None:
    """Mark a file's cross-source verification out of date (a document/data change).

    A lightweight UPDATE (no need to load the file). Idempotent. ``flush`` only.
    """
    await db.execute(
        update(LoanFile).where(LoanFile.id == loan_file_id).values(verification_stale=True)
    )
    await db.flush()


async def mark_verification_current(db: AsyncSession, *, loan_file_id: UUID) -> None:
    """Clear the staleness flag — the cross-source pass has (re-)run."""
    await db.execute(
        update(LoanFile).where(LoanFile.id == loan_file_id).values(verification_stale=False)
    )
    await db.flush()
