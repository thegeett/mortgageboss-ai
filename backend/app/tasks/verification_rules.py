"""Snapshot/rules verification task (LP-365) — the governed rule-engine pass.

The Run button enqueues TWO tasks against one verification run: the AI cross-source sweep (LP-78,
:mod:`app.tasks.cross_source`) and — from this ticket on — this governed pass. It builds the frozen
snapshot from the loan file, materializes the declared tags a LIVE rule reads, evaluates the ACTIVE
rules, reconciles the findings across runs (LP-322), and persists the snapshot (`snapshot_records`).

The two systems stay SEPARATE: this writes findings with ``origin=DETERMINISTIC_RULE`` +
``evaluation_outcome`` + provenance; the sweep writes ungoverned ``ai_cross_source`` observations. Their
counts are never summed (their trust properties differ — a gated, provenance-carrying rule verdict is not
the same kind of thing as a 75%-confidence AI guess).

FAIL-CLOSED RUN STATUS: on exhaustion this marks the run FAILED. A run must NOT read COMPLETED when the
governed engine silently failed — that is a run-level false-green, the exact class this architecture exists
to prevent. The sweep's COMPLETED set is guarded to never overwrite a FAILED (``run_cross_source``), so a
run is COMPLETED only if BOTH passes completed; if EITHER failed, the run reads FAILED.
"""

from uuid import UUID

import structlog
from celery import Task

from app.models.base import utcnow
from app.models.loan_file import LoanFile
from app.models.verification import Verification, VerificationStatus
from app.services.verification_run import run_verification
from app.tasks.base import run_async, task_session
from app.tasks.celery_app import celery_app
from app.tasks.retry import MAX_RETRIES, retry_or_terminal

logger = structlog.get_logger(__name__)


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True, name="verification.run_rule_engine", max_retries=MAX_RETRIES
)
def run_rule_engine_pass(self: Task, loan_file_id: str, run_id: str) -> None:
    """Build the snapshot, evaluate the ACTIVE rules, persist the findings + snapshot for a file's run;
    mark the run FAILED on exhaustion (fail-closed — never a silent permanent RUNNING or a false COMPLETED)."""
    retry_or_terminal(
        self,
        lambda: run_async(_run(loan_file_id, run_id)),
        on_exhausted=lambda: run_async(_mark_failed(run_id)),
        event="rule_engine_pass_exhausted",
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
        await db.commit()


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
