"""LP-523 — `./scripts/deploy staging verify <LF-ID>`, the terminal-triggered run.

WHY IT EXISTS. The rule-engine loop is deploy → run verification → read the findings, and the middle
step was only reachable by clicking in the UI. Worse, the UI cannot re-run while a previous run is
stuck RUNNING — which is precisely when you most want to.

What is under test here is the STUCK-RUN rule, because it is the only part that decides anything. The
threshold is imported from the API rather than restated: two definitions of "stuck" would eventually
disagree, and the one that matters is whatever the UI already acts on.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from app.api.verification import _STUCK_RUN_TIMEOUT_SECONDS
from app.models.base import utcnow
from app.models.company import Company
from app.models.loan_file import LoanFile
from app.models.verification import Verification, VerificationStatus, VerificationTrigger
from app.scripts.run_verification import _supersede_stuck_run, _truthy
from sqlalchemy.ext.asyncio import AsyncSession


async def _loan_file(db: AsyncSession) -> LoanFile:
    company = Company(name="LP-523", slug=f"lp523-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    loan_file = LoanFile(
        company_id=company.id,
        display_id=f"LF-{uuid4().hex[:4].upper()}",
        inbox_token=uuid4().hex,
    )
    db.add(loan_file)
    await db.flush()
    return loan_file


async def _run(db: AsyncSession, loan_file: LoanFile, *, age_seconds: int, status) -> Verification:
    verification = Verification(
        loan_file_id=loan_file.id,
        status=status,
        trigger=VerificationTrigger.MANUAL,
        started_at=utcnow() - timedelta(seconds=age_seconds),
    )
    db.add(verification)
    await db.flush()
    return verification


async def test_a_young_running_run_is_never_superseded(db_session: AsyncSession) -> None:
    """⚠️ THE SAFETY PROPERTY. A run inside the threshold may still be working — six minutes of AI
    calls look identical to a wedge from the outside. Killing it would destroy real work and real
    spend, so this refuses and says how long is left."""
    loan_file = await _loan_file(db_session)
    live = await _run(db_session, loan_file, age_seconds=60, status=VerificationStatus.RUNNING)

    refusal = await _supersede_stuck_run(db_session, loan_file.id)

    assert refusal is not None
    assert "still RUNNING" in refusal
    await db_session.refresh(live)
    assert live.status is VerificationStatus.RUNNING


async def test_a_run_past_the_api_threshold_is_superseded(db_session: AsyncSession) -> None:
    """The case this whole stage exists for: the UI refuses to re-run because a dead run still says
    RUNNING, and waiting out the watchdog costs minutes for a task that is already gone."""
    loan_file = await _loan_file(db_session)
    stuck = await _run(
        db_session,
        loan_file,
        age_seconds=_STUCK_RUN_TIMEOUT_SECONDS + 60,
        status=VerificationStatus.RUNNING,
    )

    refusal = await _supersede_stuck_run(db_session, loan_file.id)

    assert refusal is None
    await db_session.refresh(stuck)
    assert stuck.status is VerificationStatus.FAILED
    assert stuck.completed_at is not None
    assert "Superseded" in (stuck.error_detail or "")


async def test_just_inside_the_threshold_still_belongs_to_the_running_run(
    db_session: AsyncSession,
) -> None:
    """A run a few seconds short of the threshold is still protected.

    ⚠️ Deliberately NOT asserted at exactly `_STUCK_RUN_TIMEOUT_SECONDS`. The clock advances between
    stamping `started_at` and comparing, so an "exactly at the boundary" fixture is really a
    fraction-of-a-second past it — a first version of this test asserted equality and failed for that
    reason. The `<=` that matches the API watchdog is a property of the source, not something a live
    clock can demonstrate; what IS worth pinning is that the protected side of the line is protected.
    """
    loan_file = await _loan_file(db_session)
    await _run(
        db_session,
        loan_file,
        age_seconds=_STUCK_RUN_TIMEOUT_SECONDS - 30,
        status=VerificationStatus.RUNNING,
    )

    assert await _supersede_stuck_run(db_session, loan_file.id) is not None


async def test_a_completed_prior_run_is_left_alone(db_session: AsyncSession) -> None:
    """Only a RUNNING run blocks a re-run. A completed one is history and must not be rewritten."""
    loan_file = await _loan_file(db_session)
    done = await _run(
        db_session, loan_file, age_seconds=99_999, status=VerificationStatus.COMPLETED
    )

    assert await _supersede_stuck_run(db_session, loan_file.id) is None
    await db_session.refresh(done)
    assert done.status is VerificationStatus.COMPLETED


async def test_a_file_with_no_prior_run_proceeds(db_session: AsyncSession) -> None:
    loan_file = await _loan_file(db_session)

    assert await _supersede_stuck_run(db_session, loan_file.id) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, True), ("", True), ("0", False), ("false", False), ("no", False), ("1", True)],
)
def test_force_defaults_to_on(raw: str | None, expected: bool) -> None:
    """⚠️ FORCING IS THE DEFAULT, and that is the design. The API caches on an INPUT fingerprint —
    correct for a user, wrong here, because this loop changes CODE, not inputs. With the cache honoured
    a deploy would hand back the previous run's findings and look like it did nothing."""
    assert _truthy(raw, default=True) is expected
