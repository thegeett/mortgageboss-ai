"""LP-591 — how long this file's verification usually takes.

Measured before building, on 29 completed runs of one real file: mean 384s, fastest 336s, slowest
454s, standard deviation 28s. That ~7% coefficient of variation is what makes an estimate honest —
good to roughly half a minute over a six-and-a-half-minute wait. Without that measurement this would
have been a guess dressed as a feature.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.models import Company, LoanProgram, Verification
from app.models.verification import VerificationStatus, VerificationTrigger
from app.services.loan_files import create_loan_file
from app.services.verification_eta import estimated_seconds
from sqlalchemy.ext.asyncio import AsyncSession


async def _file(db: AsyncSession, slug: str):
    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    return await create_loan_file(db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL)


async def _run(db: AsyncSession, loan_file, seconds: int | None, *, minutes_ago: int = 10) -> None:
    started = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    db.add(
        Verification(
            loan_file_id=loan_file.id,
            trigger=VerificationTrigger.MANUAL,
            status=(
                VerificationStatus.COMPLETED if seconds is not None else VerificationStatus.RUNNING
            ),
            started_at=started,
            completed_at=started + timedelta(seconds=seconds) if seconds is not None else None,
        )
    )
    await db.flush()


async def test_the_median_of_recent_runs_is_the_estimate(db_session: AsyncSession) -> None:
    loan_file = await _file(db_session, "eta")
    for seconds in (300, 380, 400, 420):
        await _run(db_session, loan_file, seconds)

    assert await estimated_seconds(db_session, loan_file_id=loan_file.id) == 390


async def test_a_single_slow_run_does_not_drag_every_future_estimate_up(
    db_session: AsyncSession,
) -> None:
    """Median, not mean. The slowest observed run was 70 seconds above the mean; one outlier like
    that should not raise the number a processor is shown on every subsequent run."""
    loan_file = await _file(db_session, "outlier")
    for seconds in (380, 380, 380, 380, 900):
        await _run(db_session, loan_file, seconds)

    estimate = await estimated_seconds(db_session, loan_file_id=loan_file.id)
    assert estimate == 380


async def test_too_little_history_yields_no_estimate(db_session: AsyncSession) -> None:
    """Below three runs, one unlucky run IS the median. Showing nothing beats showing a number built
    on a sample of one — a wrong ETA teaches a processor to distrust the panel."""
    loan_file = await _file(db_session, "new")
    await _run(db_session, loan_file, 380)
    await _run(db_session, loan_file, 400)

    assert await estimated_seconds(db_session, loan_file_id=loan_file.id) is None


async def test_a_running_run_is_not_counted(db_session: AsyncSession) -> None:
    """An in-flight run has no duration. Counting it would let a null completed_at poison the
    median, or worse, make the estimate depend on the run it is estimating."""
    loan_file = await _file(db_session, "inflight")
    for seconds in (380, 380, 380):
        await _run(db_session, loan_file, seconds)
    await _run(db_session, loan_file, None)

    assert await estimated_seconds(db_session, loan_file_id=loan_file.id) == 380


async def test_another_files_history_is_not_borrowed(db_session: AsyncSession) -> None:
    """PER FILE. A file's own history encodes its size, document count and transaction volume — the
    things that actually drive duration — so borrowing another file's would estimate the wrong
    thing while looking authoritative."""
    mine = await _file(db_session, "mine")
    theirs = await _file(db_session, "theirs")
    for seconds in (380, 380, 380, 380):
        await _run(db_session, theirs, seconds)

    assert await estimated_seconds(db_session, loan_file_id=mine.id) is None
