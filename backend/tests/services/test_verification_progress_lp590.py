"""LP-590 — live progress for a run that takes six and a half minutes.

A spinner with no signal is indistinguishable from a hung worker, which has mattered twice.

THE WHOLE DIFFICULTY IS THE TRANSACTION. `run_rule_engine_pass` opens one session and commits once
at the end, so anything the run writes on that session is invisible to a poller until it is over.
Progress is therefore written from a SEPARATE short-lived session that commits immediately — which
is also why the session factory is injectable: `task_session()` builds its engine from the DEV
database URL, so a test exercising this would write into dev rather than the test database, and do
it silently because every error here is swallowed.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

from app.models import Company, LoanProgram, Verification, VerificationProgress
from app.models.verification import VerificationStatus, VerificationTrigger
from app.services.loan_files import create_loan_file
from app.services.verification_progress import PHASES, clear_progress, report_phase
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _factory(db: AsyncSession):
    """Point the reporter at the TEST session instead of a fresh dev-database engine."""

    @asynccontextmanager
    async def factory():
        yield db

    return factory


async def _run(db: AsyncSession, slug: str) -> Verification:
    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    run = Verification(
        loan_file_id=loan_file.id,
        status=VerificationStatus.RUNNING,
        trigger=VerificationTrigger.MANUAL,
    )
    db.add(run)
    await db.flush()
    return run


async def _progress(db: AsyncSession, run_id) -> VerificationProgress | None:
    return await db.scalar(
        select(VerificationProgress).where(VerificationProgress.verification_id == run_id)
    )


async def test_a_phase_is_recorded_with_its_position(db_session: AsyncSession) -> None:
    """ "Applying rules (4 of 5)" — a position, not a percentage. A bar would have to lie: stage A
    scales with the file's transaction count, so the phases are not evenly sized and a bar would
    visibly stall."""
    run = await _run(db_session, "phase")

    await report_phase(run.id, "rules", session_factory=_factory(db_session))

    row = await _progress(db_session, run.id)
    assert row is not None
    assert row.phase == "rules"
    assert (row.phase_index, row.phase_total) == (PHASES.index("rules") + 1, len(PHASES))


async def test_advancing_replaces_the_row_rather_than_adding_one(
    db_session: AsyncSession,
) -> None:
    """One row per run, upserted. A plain insert would collide on the second phase, and a
    select-then-update would race two workers on a retried task."""
    run = await _run(db_session, "advance")
    factory = _factory(db_session)

    for phase in ("build", "stage_a", "stage_b"):
        await report_phase(run.id, phase, session_factory=factory)

    rows = (
        (
            await db_session.execute(
                select(VerificationProgress).where(VerificationProgress.verification_id == run.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].phase == "stage_b"


async def test_progress_is_cleared_when_the_run_ends(db_session: AsyncSession) -> None:
    """Left on the last phase, "Cross-source review" would still be on screen after the run
    finished — which is exactly what a hung run looks like."""
    run = await _run(db_session, "cleared")
    factory = _factory(db_session)
    await report_phase(run.id, "cross_source", session_factory=factory)

    await clear_progress(run.id, session_factory=factory)

    assert await _progress(db_session, run.id) is None


async def test_a_reporting_failure_never_reaches_the_caller(db_session: AsyncSession) -> None:
    """THE PROPERTY THAT MAKES THIS SAFE TO CALL MID-RUN. Failing a six-minute verification in order
    to describe it would be a grotesque trade, so every error is swallowed with a log."""

    @asynccontextmanager
    async def broken():
        raise RuntimeError("database is on fire")
        yield  # pragma: no cover

    # Neither raises.
    await report_phase(uuid4(), "rules", session_factory=broken)
    await clear_progress(uuid4(), session_factory=broken)


async def test_an_unknown_phase_does_not_crash_or_misreport(db_session: AsyncSession) -> None:
    """A phase name that is not in the list lands at the end rather than raising ValueError from
    `PHASES.index` — a new stage added to the run must not break the run that added it."""
    run = await _run(db_session, "unknown")

    await report_phase(run.id, "some_new_stage", session_factory=_factory(db_session))

    row = await _progress(db_session, run.id)
    assert row is not None
    assert row.phase_index == len(PHASES)
