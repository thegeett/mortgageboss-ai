"""Cross-source verification task (LP-78) — the manual-triggered AI pass.

The cross-source pass is a real AI call (cost + latency), so it runs on the
worker: the endpoint creates the run record and enqueues this task; the task
assembles the two sides, runs the AI pass, and emits the findings. Retry-safe via
``retry_or_terminal`` (a transient AI/transport failure retries with backoff; on
exhaustion the run is marked FAILED — never a silent permanent RUNNING).

The worker must be running for the pass to execute (the Phase-2 storage/loop
fixes apply). PII in the assembled context is never logged.
"""

from uuid import UUID

import structlog
from celery import Task

from app.models.base import utcnow
from app.models.loan_file import LoanFile
from app.models.verification import Verification, VerificationStatus
from app.tasks.base import run_async, task_session
from app.tasks.celery_app import celery_app
from app.tasks.retry import MAX_RETRIES, retry_or_terminal

logger = structlog.get_logger(__name__)


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True, name="verification.run_cross_source", max_retries=MAX_RETRIES
)
def run_cross_source_pass(self: Task, loan_file_id: str, run_id: str) -> None:
    """Run the cross-source pass for a file's run; mark the run FAILED on exhaustion."""
    retry_or_terminal(
        self,
        lambda: run_async(_run(loan_file_id, run_id)),
        on_exhausted=lambda _exc: run_async(_mark_failed(run_id)),
        event="cross_source_pass_exhausted",
    )


async def _run(loan_file_id: str, run_id: str) -> None:
    async with task_session() as db:
        loan_file = await db.get(LoanFile, UUID(loan_file_id))
        run = await db.get(Verification, UUID(run_id))
        if loan_file is None or run is None:
            logger.warning("cross_source_pass_missing_target", run_id=run_id)
            return
        # LP-614 — THE LEGACY CROSS-SOURCE PASS NO LONGER RUNS. Neither half of it.
        #
        # The endpoint no longer enqueues this task; this body stays as the guard for any task already
        # sitting in the queue at deploy time.
        #
        # IT TOUCHES NOTHING — deliberately. The obvious "disabled" body marks the run COMPLETED and
        # returns, and that is a FALSE-GREEN: this task and the governed rule pass are enqueued on the
        # SAME run, and the rule pass is the completion authority (LP-377-C). Completing the run here
        # would report a finished verification while the rules were still running, which is exactly the
        # failure `_enqueue_rule_engine` warns about in `app/api/verification.py`. So: log, and leave the
        # run's status to the pass that owns it.
        #
        # THE AI HALF cost a model call per run and spent this month being confidently wrong in ways its
        # own text disproved: a $6,028 biweekly gross "conflicting" with $13,166.67 a month (the same
        # money), a stated Bank of America balance "conflicting" with a documented WELLS FARGO one (two
        # different accounts), an employer mismatch over one trailing letter. Each was patched in turn —
        # LP-607 taught it to annualise, LP-611 gave it a threshold and a same-object rule — and the next
        # run found a new way. The snapshot cross-check (LP-586 onward) is the supported replacement and
        # is NOT affected by this.
        #
        # THE DETERMINISTIC HALF is off on evidence, not by association. Sixteen rules; across the two
        # real files on staging exactly TWO ever fired — `xsrc.identity.name_consistency` and
        # `xsrc.income.employer_name_consistency` — and both were retired (LP-606, LP-611) for
        # contradicting the governed rules that answer the same question with the tolerance they lack.
        # The other fourteen have produced nothing on real data, and eleven map to an ACTIVE governed
        # rule (ID-2, ID-3, ID-4, IN-1, CR-1, RE-1, AS-1, OC-1, PC-2, PC-3).
        #
        # NOTHING IS DELETED. Reconcile never runs, so findings already stored stay exactly as they are —
        # the Old findings tab keeps its history instead of emptying itself on the next run. It simply
        # stops growing.
        logger.info("cross_source_pass_skipped", loan_file_id=loan_file_id, run_id=run_id)
        return


async def _mark_failed(run_id: str) -> None:
    async with task_session() as db:
        run = await db.get(Verification, UUID(run_id))
        if run is None:
            return
        run.status = VerificationStatus.FAILED
        run.completed_at = utcnow()
        run.error_detail = "Cross-source pass failed after retries"
        await db.commit()
