"""Verification endpoints (LP-78) — the manual trigger + the status/staleness read.

``POST .../verification/run`` triggers the cross-source AI pass (creates a RUNNING
run and enqueues the worker task — the pass is an AI call, so it runs in the
background); ``GET .../verification`` returns the staleness flag, the latest run,
and the findings (the uniform shape). Tenant-scoped (cross-company → 404). The
rich findings UI + resolution flow is LP-81.
"""

from datetime import timedelta
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.dependencies import CurrentUser
from app.core.database import DbSession
from app.models.base import utcnow
from app.models.borrower import Borrower
from app.models.document import Document
from app.models.finding import Finding, FindingOrigin, FindingStatus
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.user import User
from app.models.verification import Verification, VerificationStatus, VerificationTrigger
from app.schemas.finding_impact import FindingImpactPreview
from app.schemas.verification import (
    AcceptRiskRequest,
    AggressionPublic,
    AggressionUpdate,
    FindingPublic,
    NoteRequest,
    OverrideRequest,
    RequestDocsRequest,
    RuleFindingPublic,
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
from app.services.finding_impact import has_apply_spec, preview_finding_apply
from app.services.finding_resolution import (
    CannotUndoError,
    accept_risk_finding,
    add_finding_note,
    apply_finding,
    override_finding,
    request_docs_for_finding,
    undo_finding,
)
from app.services.loan_files import get_loan_file
from app.services.rule_subject_label import resolve_subject_label
from app.services.verifications import create_verification_run, mark_verification_current
from app.verification.confidence import CONFIDENCE_CUTOFFS
from app.verification.snapshot.content_id import DOC_PREFIX
from app.verification.snapshot.documents_section import document_filenames_by_content_id

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/loan-files", tags=["verification"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan file not found")
_FINDING_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found"
)

# Findings surfaced in the tab: cross-source (AI) + deterministic-rule, handled
# uniformly (the origin distinguishes provenance). Green passes are not findings.
_SHOWN_ORIGINS = (FindingOrigin.AI_CROSS_SOURCE, FindingOrigin.DETERMINISTIC_RULE)

# The stuck-RUNNING watchdog (LP-89): a run RUNNING longer than this is treated as dead (the worker died
# mid-run / the broker dropped the task / a pass was hard-killed and could not commit its own FAILED) and
# reconciled to FAILED on read, so the UI never spins forever with no recovery.
#
# LP-377-C: this is the BACKSTOP for the fourth fail-open. The governed rule pass is now the run's completion
# authority (it needs ~282s; the sweep leaves the run RUNNING), and a pass killed at its hard limit (1200s,
# ``RULE_ENGINE_HARD_LIMIT_SECONDS``) cannot commit its own FAILED marker — so detection must NOT depend on
# the dying task. This timeout is sized ABOVE that hard limit (+ queue/start slack) so a healthy long run is
# never raced, but a run whose governed pass never finished is reliably failed here.
_STUCK_RUN_TIMEOUT_SECONDS = 1500


async def _reconcile_stuck_run(db: DbSession, loan_file: LoanFile) -> None:
    """Mark a RUNNING run that has exceeded the watchdog timeout as FAILED (LP-89).

    A worker crash / dropped task would otherwise leave the run RUNNING forever with no
    recovery. On read, if the latest run has been RUNNING past the timeout, fail it (with a
    legible error) + commit, so ``get_verification`` returns a FAILED run the UI can re-run.
    """
    stmt = (
        only_active(
            select(Verification).where(Verification.loan_file_id == loan_file.id), Verification
        )
        .order_by(Verification.created_at.desc())
        .limit(1)
    )
    latest = (await db.execute(stmt)).scalars().first()
    if latest is None or latest.status is not VerificationStatus.RUNNING:
        return
    started = latest.started_at or latest.created_at
    if started is None or (utcnow() - started) <= timedelta(seconds=_STUCK_RUN_TIMEOUT_SECONDS):
        return
    latest.status = VerificationStatus.FAILED
    latest.completed_at = utcnow()
    latest.error_detail = "Verification timed out — the worker did not finish. Re-run it."
    await db.commit()
    log.warning("verification_run_watchdog_failed", run_id=str(latest.id))


async def _borrower_names(db: DbSession, loan_file_id: UUID) -> dict[str, str]:
    """The file's active borrowers as ``str(id) → "First Last"`` (LP-377-B), so a per-borrower finding's
    subject resolves to a name a processor recognises rather than the borrower's UUID."""
    rows = (
        await db.execute(
            only_active(
                select(Borrower.id, Borrower.first_name, Borrower.last_name).where(
                    Borrower.loan_file_id == loan_file_id
                ),
                Borrower,
            )
        )
    ).all()
    return {str(r.id): f"{r.first_name} {r.last_name}".strip() for r in rows}


async def _get_finding(db: DbSession, *, loan_file: LoanFile, finding_id: UUID) -> Finding | None:
    """Resolve a finding by id within a (already company-scoped) file — tenant-safe."""
    stmt = only_active(
        select(Finding).where(Finding.id == finding_id, Finding.loan_file_id == loan_file.id),
        Finding,
    )
    return (await db.execute(stmt)).scalars().first()


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


def _enqueue_rule_engine(loan_file_id: UUID, run_id: UUID) -> bool:
    """Enqueue the governed snapshot/rules pass (LP-365) ALONGSIDE the sweep, on the same run. Returns
    False on an enqueue failure (broker/worker unavailable) so the caller can mark the run FAILED — the
    task's own fail-closed FAILED only fires if the task RUNS, so an UN-enqueued pass must fail the run
    here, else the sweep would mark it COMPLETED with the governed pass never having run (a false-green).
    Never raises."""
    try:
        from app.tasks.verification_rules import run_rule_engine_pass

        run_rule_engine_pass.delay(str(loan_file_id), str(run_id))
        return True
    except Exception:
        log.warning("rule_engine_enqueue_failed", loan_file_id=str(loan_file_id))
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

    # LP-365: the governed snapshot/rules pass runs ALONGSIDE the sweep on the same run. Enqueued on the
    # cache-MISS path only (a new run). A failed enqueue marks the run FAILED (fail-closed: the governed
    # pass must run, or the run must NOT read COMPLETED). NOTE (reported, not fixed): the LP-78.1
    # fingerprint above is keyed on the CROSS-SOURCE inputs; the rule engine reads a SUPERSET (all
    # documents), so a cache-hit could skip a rule run a rule-relevant-only change should have triggered —
    # the cache needs a rule-aware key (its own ticket). Here it simply rides the same trigger as the sweep.
    if not _enqueue_rule_engine(loan_file.id, run.id):
        run.status = VerificationStatus.FAILED
        run.completed_at = utcnow()
        run.error_detail = (
            "Could not enqueue the governed rule-engine pass (worker/broker unavailable)."
        )
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

    # LP-375 — the two finding systems are split STRUCTURALLY by ``evaluation_outcome`` (the discriminator;
    # ``origin`` does NOT work — ``deterministic_rule`` spans BOTH the governed rule engine AND retired
    # ``xsrc`` findings). ``findings`` is the LEGACY quarantine (evaluation_outcome null: the AI sweep +
    # the retired xsrc deterministic findings) — RED/YELLOW, unchanged, so the sweep behaves identically.
    findings_stmt = (
        only_active(
            select(Finding).where(
                Finding.loan_file_id == loan_file.id,
                Finding.origin.in_(_SHOWN_ORIGINS),
                Finding.status.in_((FindingStatus.RED, FindingStatus.YELLOW)),
                Finding.evaluation_outcome.is_(
                    None
                ),  # legacy only — governed findings go to rule_findings
            ),
            Finding,
        )
        .options(selectinload(Finding.source_document))  # LP-114: name the source doc (no N+1)
        .order_by(Finding.created_at.desc())
    )
    findings = (await db.execute(findings_stmt)).scalars().all()

    # The GOVERNED rule-engine findings (evaluation_outcome present) — ALL outcomes, NO status filter, so
    # ``satisfied`` (Tab 2, previously dropped by the RED/YELLOW filter) and ``no_longer_applies`` (Tab 3)
    # are reachable. A SEPARATE list of a SEPARATE type → the two systems' counts can never be summed.
    rule_findings_stmt = only_active(
        select(Finding).where(
            Finding.loan_file_id == loan_file.id,
            Finding.evaluation_outcome.is_not(None),
            # Parity with the legacy query's exposure gate: a finding of a non-shown origin is not
            # surfaced by EITHER system. Governed findings are DETERMINISTIC_RULE (in _SHOWN_ORIGINS),
            # so this is a no-op today and a guard against a future non-shown-origin governed finding.
            Finding.origin.in_(_SHOWN_ORIGINS),
        ),
        Finding,
    ).order_by(Finding.created_at.desc())
    rule_findings = (await db.execute(rule_findings_stmt)).scalars().all()

    # LP-114.1: the file's document names, loaded ONCE, to name every finding's source-document set
    # (no N+1). Keyed by id → readable filename.
    doc_rows = (
        await db.execute(
            only_active(
                select(Document.id, Document.original_filename, Document.document_type).where(
                    Document.loan_file_id == loan_file.id
                ),
                Document,
            )
        )
    ).all()
    document_names: dict[UUID, str] = {row.id: row.original_filename for row in doc_rows}
    # LP-541 — the document TYPES the file actually holds, off the SAME query (no extra round trip), so
    # a couldnt_check can be sorted into "request this document" vs "read the one that is already here".
    documents_on_file: set[str] = {row.document_type for row in doc_rows if row.document_type}

    # LP-377-B — the processor-facing SUBJECT LABEL for each governed finding (a filename / amount /
    # borrower / "Loan-level"), resolved read-time per subject TYPE so a row names its subject, never a
    # content-id hash. The borrower map is cheap; the document content-id → filename map is built ONLY
    # when a governed finding actually has a document subject (it rebuilds the documents section — the
    # single honest way to recover a content-id → filename, LP-312 ids being content hashes).
    borrower_names = await _borrower_names(db, loan_file.id) if rule_findings else {}
    document_filenames = (
        await document_filenames_by_content_id(db, loan_file)
        if any((f.subject_key or "").startswith(DOC_PREFIX) for f in rule_findings)
        else {}
    )

    level = resolve_aggression_level(loan_file, user)
    cutoff = active_cutoff(loan_file, user)
    in_scope = await open_in_scope_findings(db, loan_file_id=loan_file.id, confidence_cutoff=cutoff)

    return VerificationStatusPublic(
        stale=loan_file.verification_stale,
        program=loan_file.loan_program.value if loan_file.loan_program else None,
        latest_run=VerificationRunPublic.from_model(latest) if latest else None,
        findings=[FindingPublic.from_model(f, document_names=document_names) for f in findings],
        rule_findings=[
            RuleFindingPublic.from_model(
                f,
                subject_label=resolve_subject_label(
                    f.subject_key,
                    f.load_bearing_tags or [],
                    borrower_names=borrower_names,
                    document_filenames=document_filenames,
                ),
                documents_on_file=documents_on_file,
            )
            for f in rule_findings
        ],
        # LP-377-C Fix 3: the latest run did not complete (still RUNNING, or FAILED / killed) yet governed
        # findings exist — so they MAY be carried forward from an earlier run (LP-322). Keyed on RUN status,
        # not "the rule engine failed" (a run can fail on the SWEEP while the rule pass succeeded, so the
        # findings can even be fresh) — the surface just flags possible staleness, never claims which half failed.
        rule_findings_stale=(
            latest is not None
            and latest.status is not VerificationStatus.COMPLETED
            and len(rule_findings) > 0
        ),
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
    await _reconcile_stuck_run(db, loan_file)  # the stuck-RUNNING watchdog (LP-89)
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


# --- Per-finding resolution (LP-81) — Apply / Override / Add note -------------
# Each returns the re-filtered status so the client gets the updated findings +
# blocking (and the recompute-coupled calculators refresh) in one round-trip.


@router.get(
    "/{identifier}/findings/{finding_id}/apply-preview", response_model=FindingImpactPreview
)
async def preview_finding_apply_endpoint(
    identifier: str, finding_id: UUID, db: DbSession, current_user: CurrentUser
) -> FindingImpactPreview:
    """The "View fix" DRY-RUN (LP-97) — the itemized before/after impact of applying a finding.

    Reuses the REAL apply→recompute in a rolled-back savepoint, so the preview MATCHES what Apply
    does but persists NOTHING (this endpoint never commits). Only for findings with an apply-spec
    (a 400 otherwise). Tenant-scoped.
    """
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    finding = await _get_finding(db, loan_file=loan_file, finding_id=finding_id)
    if finding is None:
        raise _FINDING_NOT_FOUND
    if not has_apply_spec(finding):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This finding declares no structured change to preview.",
        )
    # No commit — the dry-run's savepoint is rolled back inside; nothing persists.
    return await preview_finding_apply(
        db, finding=finding, loan_file=loan_file, actor_user_id=current_user.id
    )


@router.post("/{identifier}/findings/{finding_id}/apply", response_model=VerificationStatusPublic)
async def apply_finding_endpoint(
    identifier: str, finding_id: UUID, db: DbSession, current_user: CurrentUser
) -> VerificationStatusPublic:
    """Resolve a finding as APPLIED — incorporate it into the structured data (LP-75).

    Fires the APPLY→recompute interlock (the DTI/LTV calculators recompute from the
    changed data; verification is marked stale to prompt a re-run). Tenant-scoped.
    """
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    finding = await _get_finding(db, loan_file=loan_file, finding_id=finding_id)
    if finding is None:
        raise _FINDING_NOT_FOUND

    await apply_finding(db, finding=finding, loan_file=loan_file, actor_user_id=current_user.id)
    await db.commit()
    await db.refresh(loan_file)
    return await _build_status(db, loan_file=loan_file, user=current_user)


@router.post("/{identifier}/findings/{finding_id}/undo", response_model=VerificationStatusPublic)
async def undo_finding_endpoint(
    identifier: str, finding_id: UUID, db: DbSession, current_user: CurrentUser
) -> VerificationStatusPublic:
    """Undo a finding's resolution (LP-98) — reverse Apply / Accept-risk / Override → OPEN.

    Undo-Applied REVERSES the data change (restores the recorded pre-apply state) + recomputes;
    Undo-Accept/Override just reopens. Audited; tenant-scoped. 400 if the finding isn't resolved.
    """
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    finding = await _get_finding(db, loan_file=loan_file, finding_id=finding_id)
    if finding is None:
        raise _FINDING_NOT_FOUND

    try:
        await undo_finding(db, finding=finding, loan_file=loan_file, actor_user_id=current_user.id)
    except CannotUndoError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(loan_file)
    return await _build_status(db, loan_file=loan_file, user=current_user)


@router.post(
    "/{identifier}/findings/{finding_id}/override", response_model=VerificationStatusPublic
)
async def override_finding_endpoint(
    identifier: str,
    finding_id: UUID,
    payload: OverrideRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> VerificationStatusPublic:
    """Resolve a finding as OVERRIDDEN — dismissed with a **required** recorded reason."""
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    finding = await _get_finding(db, loan_file=loan_file, finding_id=finding_id)
    if finding is None:
        raise _FINDING_NOT_FOUND

    try:
        await override_finding(
            db, finding=finding, actor_user_id=current_user.id, reason=payload.reason
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(loan_file)
    return await _build_status(db, loan_file=loan_file, user=current_user)


@router.post("/{identifier}/findings/{finding_id}/note", response_model=VerificationStatusPublic)
async def add_finding_note_endpoint(
    identifier: str,
    finding_id: UUID,
    payload: NoteRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> VerificationStatusPublic:
    """Add a free-text note to a finding (informational — does not resolve it)."""
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    finding = await _get_finding(db, loan_file=loan_file, finding_id=finding_id)
    if finding is None:
        raise _FINDING_NOT_FOUND

    try:
        await add_finding_note(
            db, finding=finding, actor_user_id=current_user.id, note=payload.note
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(loan_file)
    return await _build_status(db, loan_file=loan_file, user=current_user)


# --- The full action set (LP-88) — Accept-risk + Request-docs -----------------


@router.post(
    "/{identifier}/findings/{finding_id}/accept-risk", response_model=VerificationStatusPublic
)
async def accept_risk_endpoint(
    identifier: str,
    finding_id: UUID,
    payload: AcceptRiskRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> VerificationStatusPublic:
    """Resolve a finding as ACCEPTED_RISK — acknowledged, proceed with it (LP-88).

    DISTINCT from override: this acknowledges a REAL finding the processor accepts (the
    FHA compensating-factors / subject-to-repair conditional model). An optional reason
    (the compensating factor) is recorded. Tenant-scoped.
    """
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    finding = await _get_finding(db, loan_file=loan_file, finding_id=finding_id)
    if finding is None:
        raise _FINDING_NOT_FOUND

    await accept_risk_finding(
        db, finding=finding, actor_user_id=current_user.id, reason=payload.reason
    )
    await db.commit()
    await db.refresh(loan_file)
    return await _build_status(db, loan_file=loan_file, user=current_user)


@router.post(
    "/{identifier}/findings/{finding_id}/request-docs", response_model=VerificationStatusPublic
)
async def request_docs_endpoint(
    identifier: str,
    finding_id: UUID,
    payload: RequestDocsRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> VerificationStatusPublic:
    """Request documents from a finding (LP-88) — create a needs item; the finding stays open.

    Generates a FINDING-origin needs item (priority by severity) the borrower must satisfy,
    and marks the finding (``details.docs_requested``) so the tab shows the linkage. The
    finding is not resolved. Tenant-scoped.
    """
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    finding = await _get_finding(db, loan_file=loan_file, finding_id=finding_id)
    if finding is None:
        raise _FINDING_NOT_FOUND

    await request_docs_for_finding(
        db, finding=finding, actor_user_id=current_user.id, note=payload.note
    )
    await db.commit()
    await db.refresh(loan_file)
    return await _build_status(db, loan_file=loan_file, user=current_user)


@router.get("/{identifier}/verification/runs", response_model=list[VerificationRunPublic])
async def list_verification_runs(
    identifier: str, db: DbSession, current_user: CurrentUser, limit: int = 20
) -> list[VerificationRunPublic]:
    """The file's verification run history (newest first) — the version selector (LP-88).

    Runs are already versioned (each row is a run); this exposes the history so the tab can
    show prior runs + their summary counts (and how the file's verification evolved across
    re-runs / applied findings / new docs). Tenant-scoped.
    """
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    stmt = (
        only_active(
            select(Verification).where(Verification.loan_file_id == loan_file.id), Verification
        )
        .order_by(Verification.created_at.desc())
        .limit(max(1, min(limit, 100)))
    )
    runs = (await db.execute(stmt)).scalars().all()
    return [VerificationRunPublic.from_model(r) for r in runs]
