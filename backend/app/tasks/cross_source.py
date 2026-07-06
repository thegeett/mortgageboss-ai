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
from app.services.cross_source import run_cross_source
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
        on_exhausted=lambda: run_async(_mark_failed(run_id)),
        event="cross_source_pass_exhausted",
    )


async def _run(loan_file_id: str, run_id: str) -> None:
    async with task_session() as db:
        loan_file = await db.get(LoanFile, UUID(loan_file_id))
        run = await db.get(Verification, UUID(run_id))
        if loan_file is None or run is None:
            logger.warning("cross_source_pass_missing_target", run_id=run_id)
            return
        await run_cross_source(db, loan_file=loan_file, run=run)
        await db.commit()


async def _mark_failed(run_id: str) -> None:
    async with task_session() as db:
        run = await db.get(Verification, UUID(run_id))
        if run is None:
            return
        run.status = VerificationStatus.FAILED
        run.completed_at = utcnow()
        run.error_detail = "Cross-source pass failed after retries"
        await db.commit()
