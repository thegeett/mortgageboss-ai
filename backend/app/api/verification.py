"""Verification endpoints (LP-78) — the manual trigger + the status/staleness read.

``POST .../verification/run`` triggers the cross-source AI pass (creates a RUNNING
run and enqueues the worker task — the pass is an AI call, so it runs in the
background); ``GET .../verification`` returns the staleness flag, the latest run,
and the findings (the uniform shape). Tenant-scoped (cross-company → 404). The
rich findings UI + resolution flow is LP-81.
"""

from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import CurrentUser
from app.core.database import DbSession
from app.models.finding import Finding, FindingOrigin
from app.models.helpers import only_active
from app.models.verification import Verification, VerificationTrigger
from app.schemas.verification import (
    FindingPublic,
    VerificationRunPublic,
    VerificationStatusPublic,
)
from app.services.loan_files import get_loan_file
from app.services.verifications import create_verification_run

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/loan-files", tags=["verification"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan file not found")


def _enqueue_cross_source(loan_file_id: UUID, run_id: UUID) -> None:
    """Fire-and-forget enqueue of the cross-source pass (the worker runs it)."""
    try:
        from app.tasks.cross_source import run_cross_source_pass

        run_cross_source_pass.delay(str(loan_file_id), str(run_id))
    except Exception:  # pragma: no cover - enqueue failure must not 500 the request
        log.warning("cross_source_enqueue_failed", loan_file_id=str(loan_file_id))


@router.post("/{identifier}/verification/run", response_model=VerificationRunPublic)
async def run_verification(
    identifier: str, db: DbSession, current_user: CurrentUser
) -> VerificationRunPublic:
    """Trigger the cross-source verification pass for one of the caller's files.

    Creates a RUNNING run and enqueues the AI pass (the worker assembles the two
    sides, runs the pass, and emits findings). Returns the run immediately; the
    client polls the status endpoint for completion.
    """
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    run = await create_verification_run(
        db, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
    )
    await db.commit()
    _enqueue_cross_source(loan_file.id, run.id)
    return VerificationRunPublic.from_model(run)


@router.get("/{identifier}/verification", response_model=VerificationStatusPublic)
async def get_verification(
    identifier: str, db: DbSession, current_user: CurrentUser
) -> VerificationStatusPublic:
    """The file's verification status — staleness, the latest run, and the findings."""
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND

    latest_stmt = (
        only_active(
            select(Verification).where(Verification.loan_file_id == loan_file.id), Verification
        )
        .order_by(Verification.created_at.desc())
        .limit(1)
    )
    latest = (await db.execute(latest_stmt)).scalars().first()

    findings_stmt = only_active(
        select(Finding).where(
            Finding.loan_file_id == loan_file.id,
            Finding.origin == FindingOrigin.AI_CROSS_SOURCE,
        ),
        Finding,
    ).order_by(Finding.created_at.desc())
    findings = (await db.execute(findings_stmt)).scalars().all()

    return VerificationStatusPublic(
        stale=loan_file.verification_stale,
        latest_run=VerificationRunPublic.from_model(latest) if latest else None,
        findings=[FindingPublic.from_model(f) for f in findings],
    )
