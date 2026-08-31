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

The governed pass gets its OWN, generous time limits (``app.core.run_limits``): the 65s sweep keeps the short global limits
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

from app.core.run_limits import (
    RULE_ENGINE_HARD_LIMIT_SECONDS,
    RULE_ENGINE_SOFT_LIMIT_SECONDS,
)
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


# The pass's time limits live in `app.core.run_limits` (LP-635 review) — the LP-377-C rationale that
# used to sit here moved with them, rather than being left behind describing values this module no
# longer defines. The API watchdog and the
# deploy CLI both need them, and importing THIS module to reach them pulled Celery and the whole rule
# engine into the request path — 263 `app.*` modules, which is exactly what the function-local
# `import run_rule_engine_pass` in `api/verification.py` was arranged to avoid.
#
# NOT re-exported from here. A re-export would be an unused import that every `ruff --fix` deletes;
# it did, and the callers importing it from this module broke. Importers name the leaf module.
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
        on_exhausted=lambda exc: run_async(_mark_failed(run_id, exc)),
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


#: What a processor is told when a run fails, by cause (LP-635).
#:
#: This is `error_detail` — the one string from this ticket that a human actually reads, and it was
#: wrong twice over. It said "after retries" for `terminal_on` failures that are never retried,
#: because `on_exhausted` fires from both branches of `retry_or_terminal`. And it was generic where
#: the cause was specific: the breaker composes a sentence naming what happened and what to do, and
#: nothing could carry it here, because `on_exhausted` took no arguments.
#:
#: Both halves mattered. A timed-out run and an unreachable backend need DIFFERENT actions from a
#: processor — one is "this file is too big for the window", the other is "try again shortly" — and
#: telling them the same thing makes the message worth ignoring.
_FAILURE_DETAIL: dict[type[BaseException], str] = {
    # LP-635 review — NAMES NO CAUSE, because a timeout cannot tell them apart.
    #
    # It used to say "this usually means the file has more documents than one run can process". A
    # small file hitting the LF-ZE9N outage reaches here and is told exactly that: the breaker
    # counts BATCHES of up to fifteen subjects, so a pass of fewer than five batches can never trip
    # it, grinds to the soft limit, and the processor reads "too many documents" about a transport
    # outage. That is the misdiagnosis this ticket was opened to end, written into the field they
    # read.
    #
    # "Re-run it" was the other half: `rule_engine_limits` is deterministic from document count, so
    # a genuinely oversized file gets the identical budget on the re-run and burns another slot to
    # fail the same way.
    SoftTimeLimitExceeded: (
        "Verification ran out of time before it finished. That can mean the file is larger than "
        "one run's budget, or that the AI backend was slow or unreachable. Re-running is worth one "
        "attempt; if it times out again, raise it with support rather than repeating it."
    ),
}


def _failure_detail(exc: BaseException | None) -> str:
    """The user-visible reason a run failed.

    An exception that can explain itself is ASKED, via a ``user_detail`` attribute, before any type
    matching happens — so a future self-describing failure is not silently flattened into the
    generic line.

    LP-635 review: this docstring previously claimed exactly that while the code did
    ``isinstance(exc, AiBackendUnavailable)`` — a type match against one hardcoded class. The next
    self-describing exception would have been flattened, and the next reader would have trusted the
    sentence and not wired it. The protocol is now real, so the claim is true.

    ``user_detail`` must be safe to show: it is written verbatim into ``error_detail``, which
    ``readonly.verifications`` scrubs for identifier SHAPES ONLY. A digit run is redacted; a
    borrower's name or address is not — so this protocol still requires what it writes to be
    composed rather than quoted, and scrubbing is the second line, not the first.
    """
    detail = getattr(exc, "user_detail", None)
    if isinstance(detail, str) and detail:
        return detail
    for kind, detail in _FAILURE_DETAIL.items():
        if isinstance(exc, kind):
            return detail
    return "Rule-engine pass failed — re-run the verification."


async def _mark_failed(run_id: str, exc: BaseException | None = None) -> None:
    async with task_session() as db:
        run = await db.get(Verification, UUID(run_id))
        if run is None:
            return
        # FAILED is sticky and fail-closed — a governed-engine failure must be VISIBLE on the run.
        run.status = VerificationStatus.FAILED
        run.completed_at = utcnow()
        run.error_detail = _failure_detail(exc)
        await db.commit()


__all__ = ["run_rule_engine_pass"]
