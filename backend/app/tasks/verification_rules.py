"""Snapshot/rules verification task (LP-365) — the governed rule-engine pass.

The Run button enqueues TWO tasks against one verification run: the AI cross-source sweep (LP-78,
:mod:`app.tasks.cross_source`) and — from this ticket on — this governed pass. It builds the frozen
snapshot from the loan file, materializes the declared tags a LIVE rule reads, evaluates the ACTIVE
rules, reconciles the findings across runs (LP-322), and persists the snapshot (`snapshot_records`).

The two systems stay SEPARATE: this writes findings with ``origin=DETERMINISTIC_RULE`` +
``evaluation_outcome`` + provenance; the sweep writes ungoverned ``ai_cross_source`` observations. Their
counts are never summed (their trust properties differ — a gated, provenance-carrying rule verdict is not
the same kind of thing as a 75%-confidence AI guess).

FAIL-CLOSED RUN STATUS (LP-377-C): the RULE PASS is the run's COMPLETION AUTHORITY. The governed pass needs
~282s on a 30-document file (LP-365) — far more than the 65s sweep — so the sweep NO LONGER marks a run
COMPLETED (it cannot know this half finished). A run reads COMPLETED ONLY when THIS pass reaches the end and
sets it. The two failure paths:
  * a SOFT time-limit (or a transient error that exhausts retries) raises INTO the task → ``on_exhausted``
    marks the run FAILED immediately. A soft time-limit is ``terminal_on`` (NOT retried) — retrying re-runs
    the same ~282s+ work, times out again, and stacked retries (up to 3x the hard limit) would outlast the
    watchdog and let it fail a run mid-retry. Fail closed once.
  * a HARD kill (SIGKILL at the hard limit) cannot commit its own marker → the run stays RUNNING and the
    watchdog (``_reconcile_stuck_run``, timeout sized ABOVE this pass's hard limit) fails it — detection that
    does NOT depend on the dying task. Because soft time-limits no longer retry, the watchdog only ever
    bounds a single un-retried attempt, so its "above one hard limit" sizing is correct.

The governed pass gets its OWN, generous time limits (below): the 65s sweep keeps the short global limits
(``celery_app.py``), but a ~282s pass must not be killed at the global 120s soft limit — the fourth
fail-open (LP-377-C: nobody put 282 next to 120). These cover the current realistic file sizes with margin;
a file large enough to exceed even these needs the engine-level fix (parallelize / gate the per-document AI
groups — LP-368 rec 4), which is out of scope here.
"""

from uuid import UUID

import structlog
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.finding import Finding, FindingStatus
from app.models.loan_file import LoanFile
from app.models.verification import Verification, VerificationStatus
from app.services.verification_run import run_verification
from app.tasks.base import run_async, task_session
from app.tasks.celery_app import celery_app
from app.tasks.retry import MAX_RETRIES, retry_or_terminal

logger = structlog.get_logger(__name__)

# The governed pass's OWN time limits (LP-377-C, Fix 1). LP-365 measured ~282s on a 30-document file; the
# runtime is dominated by SEQUENTIAL AI calls (6 materialization groups, each over per-document batches,
# plus Stage A/B), so it grows with document count. Sized generously above 282s so a realistic file
# completes; the soft limit raises inside the task for a graceful mark, the hard limit is the SIGKILL
# ceiling. The stuck-run watchdog (``verification.py``) is sized ABOVE the hard limit so a hard-kill (which
# cannot commit its own FAILED marker) is still caught.
RULE_ENGINE_SOFT_LIMIT_SECONDS = 900  # 15 min — a 30-doc run (~282s) finishes with wide headroom
RULE_ENGINE_HARD_LIMIT_SECONDS = 1200  # 20 min — the SIGKILL ceiling


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="verification.run_rule_engine",
    max_retries=MAX_RETRIES,
    soft_time_limit=RULE_ENGINE_SOFT_LIMIT_SECONDS,
    time_limit=RULE_ENGINE_HARD_LIMIT_SECONDS,
)
def run_rule_engine_pass(self: Task, loan_file_id: str, run_id: str) -> None:
    """Build the snapshot, evaluate the ACTIVE rules, persist the findings + snapshot, and — on success —
    mark the run COMPLETED (the completion authority, LP-377-C); mark FAILED on exhaustion (fail-closed —
    never a silent permanent RUNNING or a false COMPLETED via the sweep alone)."""
    retry_or_terminal(
        self,
        lambda: run_async(_run(loan_file_id, run_id)),
        on_exhausted=lambda: run_async(_mark_failed(run_id)),
        event="rule_engine_pass_exhausted",
        # LP-377-C: a SOFT time-limit is terminal, NOT transient — retrying re-runs the same ~282s+ work
        # and will time out again, and stacked retries (up to 3x the hard limit) would outlast the 1500s
        # stuck-run watchdog and let it fail a run mid-retry. Fail closed once, immediately.
        terminal_on=(SoftTimeLimitExceeded,),
    )


async def _run(loan_file_id: str, run_id: str) -> None:
    async with task_session() as db:
        loan_file = await db.get(LoanFile, UUID(loan_file_id))
        run = await db.get(Verification, UUID(run_id))
        if loan_file is None or run is None:
            logger.warning("rule_engine_pass_missing_target", run_id=run_id)
            return
        # reasoners omitted → run_verification uses the REAL model (a real run must never use a stub).
        await run_verification(
            db,
            run_id=run.id,
            loan_file_id=loan_file.id,
            company_id=loan_file.company_id,
            verification_id=run.id,
        )
        # LP-377-C Fix 2: the governed pass is the completion authority. Re-read status under a ROW LOCK
        # (the LP-377 BUG-1 pattern, moved here from the sweep) and mark COMPLETED only if a concurrent
        # FAILED (a sweep failure) has not been committed — the lock is held to commit, so a FAILED that
        # arrives later serializes AFTER and stays sticky (FAILED always wins). Reaching this line at all is
        # the proof the governed engine finished; a timed-out pass never gets here.
        locked_status = await db.scalar(
            select(Verification.status).where(Verification.id == run.id).with_for_update()
        )
        if locked_status is not VerificationStatus.FAILED:
            run.status = VerificationStatus.COMPLETED
            run.completed_at = utcnow()
            await _stamp_triage_counts(db, run)
        await db.commit()


async def _stamp_triage_counts(db: AsyncSession, run: Verification) -> None:
    """Fill the run's red / yellow / green counts from the findings it left (bug-005).

    These columns have existed since the first verification and were never written: EVERY completed run
    on staging back to 2026-08-23 reads 0/0/0, including one carrying 130 findings and 21 reds. A
    default of zero is the worst possible wrong answer here — anything reading these to summarise a run
    reports a clean file, which is the one direction this codebase refuses everywhere else.

    Counted over the file's ACTIVE findings rather than the ones this run restamped: `verification_id`
    marks what a run CHANGED, so counting by it would report 20 findings on a run that touched 20 and
    left 110 standing. The number a processor wants is what the file says now.
    """
    # BEST-EFFORT, AND CONTAINED IN A SAVEPOINT. This is a summary: a run whose verdicts are correct
    # and persisted must not fail because a count did not come back. And the containment is not
    # optional — a bare `except` around a DB read is best-effort only for non-DB errors, since a
    # SQLAlchemy error poisons the session and the caller's `commit` two lines down would then take
    # the COMPLETED status with it. bug-002 shipped exactly that mistake in `flag_covered_needs`.
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(
                    select(Finding.status, func.count())
                    .where(Finding.loan_file_id == run.loan_file_id, Finding.deleted_at.is_(None))
                    .group_by(Finding.status)
                )
            ).all()
    except Exception:
        logger.warning("verification_triage_counts_failed", run_id=str(run.id), exc_info=True)
        return
    counts: dict[FindingStatus, int] = dict(rows)  # type: ignore[arg-type]
    run.red_count = counts.get(FindingStatus.RED, 0)
    run.yellow_count = counts.get(FindingStatus.YELLOW, 0)
    run.green_count = counts.get(FindingStatus.GREEN, 0)


async def _mark_failed(run_id: str) -> None:
    async with task_session() as db:
        run = await db.get(Verification, UUID(run_id))
        if run is None:
            return
        # FAILED is sticky and fail-closed — a governed-engine failure must be VISIBLE on the run.
        run.status = VerificationStatus.FAILED
        run.completed_at = utcnow()
        run.error_detail = "Rule-engine pass failed after retries"
        await db.commit()


__all__ = ["run_rule_engine_pass"]
