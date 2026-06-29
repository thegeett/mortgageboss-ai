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
from app.models.base import utcnow
from app.models.finding import Finding, FindingOrigin
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.user import User
from app.models.verification import Verification, VerificationStatus, VerificationTrigger
from app.schemas.verification import (
    AggressionPublic,
    AggressionUpdate,
    FindingPublic,
    VerificationRunPublic,
    VerificationStatusPublic,
)
from app.services.aggression import active_cutoff, resolve_aggression_level
from app.services.cross_source import (
    assemble_cross_source_context,
    compute_input_fingerprint,
    latest_completed_run,
)
from app.services.finding_blocking import open_in_scope_findings
from app.services.loan_files import get_loan_file
from app.services.verifications import create_verification_run, mark_verification_current
from app.verification.confidence import CONFIDENCE_CUTOFFS

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/loan-files", tags=["verification"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan file not found")


def _enqueue_cross_source(loan_file_id: UUID, run_id: UUID) -> bool:
    """Enqueue the cross-source pass (the worker runs it). Returns success.

    Never raises (an enqueue failure must not 500 the request), but the caller
    must surface a failure on the run — a swallowed enqueue would otherwise strand
    the run RUNNING forever (the Phase-2 "surface, don't swallow" principle).
    """
    try:
        from app.tasks.cross_source import run_cross_source_pass

        run_cross_source_pass.delay(str(loan_file_id), str(run_id))
        return True
    except Exception:
        log.warning("cross_source_enqueue_failed", loan_file_id=str(loan_file_id))
        return False


@router.post("/{identifier}/verification/run", response_model=VerificationRunPublic)
async def run_verification(
    identifier: str, db: DbSession, current_user: CurrentUser, force: bool = False
) -> VerificationRunPublic:
    """Trigger the cross-source verification pass for one of the caller's files.

    **Caching (LP-78.1):** if the verification inputs (the stated + verified data the
    pass compares) hash to the same fingerprint as the last completed run, this
    returns that run's **cached** findings WITHOUT re-calling the AI — instant, free,
    and identical (the cross-source pass is non-deterministic, so re-asking the AI on
    unchanged inputs would only show the same discrepancies described differently).
    Pass ``force=true`` to re-run anyway (the escape hatch).

    When the inputs HAVE changed (or ``force``), it creates a RUNNING run and enqueues
    the AI pass on the worker; the client polls the status endpoint for completion. A
    failed enqueue marks the run FAILED rather than leaving it RUNNING.
    """
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND

    # Compare the CURRENT inputs to the last completed run's fingerprint.
    fingerprint = compute_input_fingerprint(await assemble_cross_source_context(db, loan_file))
    last = await latest_completed_run(db, loan_file.id)
    if not force and last is not None and last.input_fingerprint == fingerprint:
        # Inputs unchanged → return the cached run; do NOT call the AI.
        if loan_file.verification_stale:
            # Reconcile: matching inputs means it is not actually stale.
            await mark_verification_current(db, loan_file_id=loan_file.id)
            await db.commit()
        return VerificationRunPublic.from_model(last)

    run = await create_verification_run(
        db, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
    )
    await db.commit()

    if not _enqueue_cross_source(loan_file.id, run.id):
        run.status = VerificationStatus.FAILED
        run.completed_at = utcnow()
        run.error_detail = "Could not enqueue the verification pass (worker/broker unavailable)."
        await db.commit()

    return VerificationRunPublic.from_model(run)


async def _build_status(
    db: DbSession, *, loan_file: LoanFile, user: User
) -> VerificationStatusPublic:
    """Assemble the file's verification status at the user's active aggression cutoff.

    The dial is a **read-time view filter** over LP-78's already-stored findings — this
    only reads + filters, it never re-runs the AI. ``findings`` returns the full stored
    cross-source set (the client hides those below the active cutoff for display);
    ``blocked`` / ``in_scope_open_count`` are the authoritative blocking computation
    (LP-75) at the active cutoff over ALL findings (deterministic + AI).
    """
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

    level = resolve_aggression_level(loan_file, user)
    cutoff = active_cutoff(loan_file, user)
    in_scope = await open_in_scope_findings(db, loan_file_id=loan_file.id, confidence_cutoff=cutoff)

    return VerificationStatusPublic(
        stale=loan_file.verification_stale,
        latest_run=VerificationRunPublic.from_model(latest) if latest else None,
        findings=[FindingPublic.from_model(f) for f in findings],
        aggression=AggressionPublic(
            level=level.value,
            default=user.default_aggression_level.value,
            override=(
                loan_file.aggression_level_override.value
                if loan_file.aggression_level_override is not None
                else None
            ),
            cutoff=cutoff,
            cutoffs={lvl.value: c for lvl, c in CONFIDENCE_CUTOFFS.items()},
        ),
        blocked=len(in_scope) > 0,
        in_scope_open_count=len(in_scope),
    )


@router.get("/{identifier}/verification", response_model=VerificationStatusPublic)
async def get_verification(
    identifier: str, db: DbSession, current_user: CurrentUser
) -> VerificationStatusPublic:
    """The file's verification status — staleness, the latest run, the findings + the dial."""
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    return await _build_status(db, loan_file=loan_file, user=current_user)


@router.put("/{identifier}/verification/aggression", response_model=VerificationStatusPublic)
async def set_aggression(
    identifier: str, payload: AggressionUpdate, db: DbSession, current_user: CurrentUser
) -> VerificationStatusPublic:
    """Set (or clear) this file's aggression override and return the re-filtered status.

    A pure read-time re-filter over the **stored** findings (LP-78): it changes which
    findings are in-scope (shown + blocking) at the new cutoff — it NEVER re-runs the AI
    and NEVER recolors a finding (confidence ≠ severity). ``level = null`` clears the
    override (revert to the user default). Tenant-scoped (cross-company → 404).
    """
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND

    loan_file.aggression_level_override = payload.level
    await db.commit()
    await db.refresh(loan_file)
    return await _build_status(db, loan_file=loan_file, user=current_user)
