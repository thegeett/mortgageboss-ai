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
from app.models.finding import (
    EvaluationOutcome,
    Finding,
    FindingResolutionStatus,
    FindingStatus,
)
from app.models.loan_file import LoanFile
from app.models.verification import Verification, VerificationStatus
from app.services.verification_run import run_verification
from app.tasks.base import run_async, task_session
from app.tasks.celery_app import celery_app
from app.tasks.retry import MAX_RETRIES, retry_or_terminal
from app.verification.tag_materialization.breaker import AiBackendUnavailable

logger = structlog.get_logger(__name__)

# The governed pass's OWN time limits (LP-377-C, Fix 1). LP-365 measured ~282s on a 30-document file; the
# runtime is dominated by SEQUENTIAL AI calls (6 materialization groups, each over per-document batches,
# plus Stage A/B), so it grows with document count. Sized generously above 282s so a realistic file
# completes; the soft limit raises inside the task for a graceful mark, the hard limit is the SIGKILL
# ceiling. The stuck-run watchdog (``verification.py``) is sized ABOVE the hard limit so a hard-kill (which
# cannot commit its own FAILED marker) is still caught.
# ---------------------------------------------------------------------------
# The pass's time limits — LP-635
# ---------------------------------------------------------------------------
# THESE SCALE WITH THE FILE, and that is the fix. A fixed limit was never wrong about the clock; it
# was wrong about the assumption underneath it, and it could not notice. Its own comment read:
#
#     RULE_ENGINE_SOFT_LIMIT_SECONDS = 900  # 15 min — a 30-doc run (~282s) finishes with wide headroom
#
# That is 9.4 seconds per document. LF-AWBB's COMPLETED run is 747 seconds over 21 documents —
# 35.6 s/doc, nearly four times the assumption — so by the time LF-ZE9N (44 documents) arrived, the
# "wide headroom" was a deficit. The constant never drifted; the cost per document grew underneath
# it, and a constant cannot report that. Making the limit a function of the thing that drives the
# runtime is what stops the next silent divergence: if the cost per document grows again, files get
# slower rather than suddenly unverifiable, and the measurement below is what needs revisiting.
#
# THIS IS NOT THE WHOLE FIX and should not be mistaken for one. LP-635 ranks "raise the limit" LAST,
# behind understanding why a 44-document file needs 591 model calls at all. This buys those files the
# ability to finish; it does not make finishing cheap.

#: Measured, not chosen: LF-AWBB's completed run, 747s over 21 documents, on 2026-08-30.
#: Re-measure before trusting it — this is exactly the number whose staleness caused the incident.
MEASURED_SECONDS_PER_DOCUMENT = 35.6

#: Headroom over the measurement. A soft limit must be loose enough that a healthy run never trips it
#: (tripping is terminal — see ``terminal_on`` below) and tight enough to catch a genuinely stuck
#: one. 1.7x covers the run-to-run variance seen between LF-AWBB's ~10-minute and 12m27s runs.
LIMIT_HEADROOM = 1.7

#: The floor keeps today's behaviour for ordinary files: a small file gets the same 15 minutes it
#: always had, so this change cannot make anything detect a stuck run more slowly than before.
RULE_ENGINE_MIN_SOFT_SECONDS = 900

#: The ceiling is a REFUSAL, not a budget. Past this, a file needs the resumable pass LP-635 asks for
#: (item 3), not a longer lease on a worker slot — one task holding a prefork slot for an hour
#: starves everything queued behind it. A file that exceeds this will still fail; it will fail having
#: been given an hour, which is the signal that the pass itself has to change.
RULE_ENGINE_MAX_SOFT_SECONDS = 3600

#: Soft -> hard -> watchdog, each with the same 300s gap the original constants used. The ordering is
#: load-bearing: the soft limit lets the task mark its own run FAILED, the hard limit SIGKILLs a task
#: that ignored it, and the watchdog catches a hard-killed task that could not write its own marker.
LIMIT_STEP_SECONDS = 300

#: Backwards-compatible defaults — the decorator needs values at import time, and they are the bounds
#: a task gets when it is enqueued without per-file limits.
RULE_ENGINE_SOFT_LIMIT_SECONDS = RULE_ENGINE_MIN_SOFT_SECONDS
RULE_ENGINE_HARD_LIMIT_SECONDS = RULE_ENGINE_MIN_SOFT_SECONDS + LIMIT_STEP_SECONDS

#: The widest bound any run can be given — what the stuck-run watchdog must sit above.
RULE_ENGINE_MAX_HARD_SECONDS = RULE_ENGINE_MAX_SOFT_SECONDS + LIMIT_STEP_SECONDS


def rule_engine_limits(document_count: int) -> tuple[int, int]:
    """``(soft, hard)`` seconds for a file with ``document_count`` documents.

    One function so the enqueue path and the stuck-run watchdog cannot disagree about how long a run
    is allowed to take — a watchdog that fails a run its own task was still legitimately working on
    is a worse failure than the one this ticket is about.
    """
    budget = document_count * MEASURED_SECONDS_PER_DOCUMENT * LIMIT_HEADROOM
    soft = int(min(max(budget, RULE_ENGINE_MIN_SOFT_SECONDS), RULE_ENGINE_MAX_SOFT_SECONDS))
    return soft, soft + LIMIT_STEP_SECONDS


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
        #
        # LP-635 REVIEW — `AiBackendUnavailable` joins it, for the SAME reason and two more. It was
        # left transient so Celery would retry it, on the reasoning that the backend might be back;
        # measured, it is not:
        #
        #   * THE WATCHDOG. `started_at` is set once at run creation and never reset per attempt,
        #     while `_reconcile_stuck_run` measures against a SINGLE-attempt bound (`hard + 300`).
        #     The comment above says that sizing only holds "because soft time-limits no longer
        #     retry". A retried run keeps the original clock, so a 44-doc file that works 2200s,
        #     trips, and retries is failed by the watchdog at 3262s while the retry is still working
        #     — and `_run`'s FAILED-wins lock then suppresses COMPLETED while the findings commit
        #     anyway. A FAILED run carrying a full set of fresh findings is worse than either.
        #   * THE COST. `TagCaches` is `field(default_factory=dict)` — in-memory, rebuilt per
        #     invocation. A retry re-issues every Stage A / Stage B / materialization call already
        #     paid for, so an outage near the end of a 591-call pass costs up to 4x a normal run.
        #   * THE WINDOW. `retry_countdown` is 5s/10s/20s over MAX_RETRIES=3 — about 35 seconds. An
        #     outage long enough to trip the breaker (5 consecutive failures) is essentially never
        #     over inside 35 seconds, so all three attempts fail and the run ends FAILED regardless.
        #
        # The benefit the breaker actually delivers is unchanged by this: the slot is released in
        # under a minute instead of grinding for the file's whole budget, and the run is visibly
        # FAILED and re-runnable by hand. That was always the win; the retry was not.
        terminal_on=(SoftTimeLimitExceeded, AiBackendUnavailable),
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
        # bug-006 — THE COUNTS ARE READ BEFORE THE STATUS IS SET, and that ordering is the whole point.
        # A savepoint rollback expires every DIRTY object in the session (`_restore_snapshot`), so
        # taking one AFTER `run.status = COMPLETED` put the pending status inside what the rollback
        # would discard: a failed count query would leave a run whose findings all persisted sitting
        # non-COMPLETED until the stuck-run watchdog failed it. The savepoint added to protect the
        # commit was the one thing that could destroy it.
        #
        # The flush is the other half: it settles anything `run_verification` left dirty, so the
        # savepoint below has no unflushed state to expire either.
        await db.flush()
        counts = await _triage_counts(db, run.loan_file_id)
        if locked_status is not VerificationStatus.FAILED:
            run.status = VerificationStatus.COMPLETED
            run.completed_at = utcnow()
            if counts is not None:
                run.red_count, run.yellow_count, run.green_count = counts
        await db.commit()


async def _triage_counts(db: AsyncSession, loan_file_id: UUID) -> tuple[int, int, int] | None:
    """The file's red / yellow / green counts, or ``None`` if they could not be read (bug-005).

    These columns have existed since the first verification and were never written: EVERY completed run
    on staging back to 2026-08-23 read 0/0/0, including one carrying 130 findings and 21 reds. A default
    of zero is the worst possible wrong answer — anything reading them to summarise a run reports a
    clean file, the one direction this codebase refuses everywhere else.

    Counted over the file rather than over what this run RESTAMPED: `verification_id` marks what a run
    CHANGED, so counting by it would report 20 on a run that touched 20 and left 110 standing.

    bug-006 — AND "ACTIVE" HAD TO MEAN WHAT THIS SAID. The first cut filtered on `deleted_at` alone,
    which is neither of the things that make a finding count:

      * a RETIRED finding is not soft-deleted — reconciliation sets `NO_LONGER_APPLIES` and a green
        status and leaves the row live — so LF-AWBB's retired CR-1 rows would have landed in
        `green_count`, inflating it with rows the engine had already decided were not concerns;
      * a RESOLVED finding keeps its severity, because `_update_finding` deliberately never touches
        `resolution_status` — so a file whose reds a processor had APPLIED or OVERRIDDEN would still
        report them, which is the number they worked to clear.

    Both are excluded. What is left is what is still open and still applies.

    BEST-EFFORT, AND CONTAINED IN A SAVEPOINT. A summary must not fail a run whose verdicts are correct
    and persisted, and a bare `except` around a DB read is best-effort only for non-DB errors: a
    SQLAlchemy error poisons the session and the caller's `commit` would take the COMPLETED status with
    it. bug-002 shipped exactly that mistake in `flag_covered_needs`.
    """
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(
                    select(Finding.status, func.count())
                    .where(
                        Finding.loan_file_id == loan_file_id,
                        Finding.deleted_at.is_(None),
                        # bug-007 — `is_distinct_from`, NOT `!=`. `evaluation_outcome` is nullable BY
                        # DESIGN ("only tag-rule findings carry it; existing cross-source/document
                        # findings leave it null"), and in SQL `null != 'no_longer_applies'` is NULL,
                        # which WHERE drops. On staging that silently excluded 18 live, open, yellow
                        # findings from `yellow_count` — a cleaner file than the file is, which is the
                        # one direction the docstring above says this refuses.
                        Finding.evaluation_outcome.is_distinct_from(
                            EvaluationOutcome.NO_LONGER_APPLIES
                        ),
                        Finding.resolution_status == FindingResolutionStatus.OPEN,
                    )
                    .group_by(Finding.status)
                )
            ).all()
    except Exception:
        logger.warning(
            "verification_triage_counts_failed", loan_file_id=str(loan_file_id), exc_info=True
        )
        return None
    counts: dict[FindingStatus, int] = dict(rows)  # type: ignore[arg-type]
    return (
        counts.get(FindingStatus.RED, 0),
        counts.get(FindingStatus.YELLOW, 0),
        counts.get(FindingStatus.GREEN, 0),
    )


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
