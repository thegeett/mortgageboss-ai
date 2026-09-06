"""Verification endpoints (LP-78) — the manual trigger + the status/staleness read.

``POST .../verification/run`` triggers the cross-source AI pass (creates a RUNNING
run and enqueues the worker task — the pass is an AI call, so it runs in the
background); ``GET .../verification`` returns the staleness flag, the latest run,
and the findings (the uniform shape). Tenant-scoped (cross-company → 404). The
rich findings UI + resolution flow is LP-81.
"""

from collections.abc import Mapping
from datetime import timedelta
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.dependencies import CurrentUser
from app.core.database import DbSession
from app.core.run_limits import rule_engine_limits
from app.models.base import utcnow
from app.models.document import Document
from app.models.finding import EvaluationOutcome, Finding, FindingOrigin, FindingStatus
from app.models.finding_event import FindingEvent
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.snapshot_finding import SnapshotFinding
from app.models.user import User
from app.models.verification import Verification, VerificationStatus, VerificationTrigger
from app.models.verification_progress import VerificationProgress
from app.schemas.finding_impact import ApplyRequest, FindingImpactPreview
from app.schemas.snapshot_findings import (
    SnapshotFindingDisposition,
    SnapshotFindingPublic,
    SnapshotFindingSource,
)
from app.schemas.verification import (
    AcceptRiskRequest,
    AggressionPublic,
    AggressionUpdate,
    BulkRequestDocsRequest,
    FindingPublic,
    NoteRequest,
    OverrideRequest,
    RatifyRequest,
    RequestDocsRequest,
    RuleFindingPublic,
    VerificationRunPublic,
    VerificationStatusPublic,
    # helpers the row renders with, so the button and the card can never disagree about what is
    # still outstanding.
    _missing_documents,
    _requested_documents,
    _rule_spec,
)
from app.services.aggression import active_cutoff, resolve_aggression_level
from app.services.borrowers import borrower_display_names
from app.services.cross_source import (
    assemble_cross_source_context,
    compute_input_fingerprint,
    latest_completed_run,
)
from app.services.dti import build_dti_calculation
from app.services.finding_blocking import open_in_scope_findings
from app.services.finding_impact import (
    apply_fingerprint,
    has_apply_spec,
    preview_finding_apply,
)
from app.services.finding_resolution import (
    CannotApplyError,
    CannotRatifyError,
    CannotUndoError,
    accept_risk_finding,
    add_finding_note,
    apply_finding,
    override_finding,
    ratify_finding,
    request_docs_for_finding,
    request_documents_in_bulk,
    undo_finding,
)
from app.services.loan_files import get_loan_file
from app.services.ltv import build_ltv_calculation
from app.services.rule_subject_label import resolve_subject_label
from app.services.snapshot_findings import list_snapshot_findings
from app.services.verification_eta import estimated_seconds
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
#: Slack ABOVE the pass's hard limit: queue wait, worker start, and the moment a SIGKILLed task
#: needs before anyone could have written its FAILED marker. LP-635 turned the timeout itself into a
#: function of the file (`rule_engine_limits`); this is the constant part that survived, and it is
#: the same 300s the old fixed 1500s encoded over a 1200s hard limit.
_WATCHDOG_SLACK_SECONDS = 300


async def _latest_run(db: DbSession, loan_file_id: UUID) -> Verification | None:
    """The file's most recent active run, or ``None``.

    Extracted in LP-629 so the watchdog and the new in-flight guard read the SAME row by the
    same ordering. Two copies of this query that drifted would let the guard refuse a run the
    watchdog had just failed, or the reverse.
    """
    stmt = (
        only_active(
            select(Verification).where(Verification.loan_file_id == loan_file_id), Verification
        )
        .order_by(Verification.created_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


async def _watchdog_hard_limit(db: DbSession, run: Verification, loan_file_id: UUID) -> int:
    """The hard limit THIS run was given, in seconds (LP-635 review).

    STORED FIRST, derived only as a fallback. The watchdog runs on READ — potentially hours after the
    run started — and re-deriving from the file's current document count asks the wrong question. The
    count is taken through `only_active`, so soft-deleting documents during a long run SHRINKS the
    derived bound below the one the running task is actually holding: a healthy 44-document run gets
    failed, and the processor is told it "timed out" while the work was still in flight.

    The fallback covers runs enqueued before this column existed, and any path that enqueues without
    setting it. Those behave exactly as they did before — which is the behaviour above, wrong in the
    same narrow way, and strictly better than refusing to reconcile them at all.
    """
    if run.time_limit_seconds is not None:
        return run.time_limit_seconds
    _soft, hard = rule_engine_limits(await _document_count(db, loan_file_id))
    return hard


async def _reconcile_stuck_run(db: DbSession, loan_file: LoanFile) -> None:
    """Mark a RUNNING run that has exceeded the watchdog timeout as FAILED (LP-89).

    A worker crash / dropped task would otherwise leave the run RUNNING forever with no
    recovery. On read, if the latest run has been RUNNING past the timeout, fail it (with a
    legible error) + commit, so ``get_verification`` returns a FAILED run the UI can re-run.
    """
    latest = await _latest_run(db, loan_file.id)
    if latest is None or latest.status is not VerificationStatus.RUNNING:
        return
    started = latest.started_at or latest.created_at
    if started is None:
        return
    # LP-635 — the watchdog scales with the file, because the pass now does.
    #
    # A FIXED 1500s here would have been the new bug: a 44-document run is legitimately given ~49
    # minutes, and a watchdog that failed it at 25 would kill healthy runs on exactly the files this
    # ticket exists to make work — while telling the processor they "timed out". Derived from the same
    # `rule_engine_limits` the enqueue uses, so the two cannot disagree.
    #
    # Small files are unchanged: the floor puts them back at 1200s hard + 300s slack = 1500s, the
    # value this constant held. Nothing detects a stuck small run more slowly than before.
    hard = await _watchdog_hard_limit(db, latest, loan_file.id)
    if (utcnow() - started) <= timedelta(seconds=hard + _WATCHDOG_SLACK_SECONDS):
        return
    latest.status = VerificationStatus.FAILED
    latest.completed_at = utcnow()
    latest.error_detail = "Verification timed out — the worker did not finish. Re-run it."
    await db.commit()
    log.warning("verification_run_watchdog_failed", run_id=str(latest.id))


async def _borrower_names(db: DbSession, loan_file_id: UUID) -> dict[str, str]:
    """The file's active borrowers as ``str(id) → name`` (LP-377-B), so a per-borrower finding's
    subject resolves to a name a processor recognises rather than the borrower's UUID.

    Delegates to the shared builder (LP-613): this path and the prose composer disagreed on whether a
    middle name is part of the name, so one finding could read two ways in one panel."""
    return await borrower_display_names(db, loan_file_id)


async def _get_finding(db: DbSession, *, loan_file: LoanFile, finding_id: UUID) -> Finding | None:
    """Resolve a finding by id within a (already company-scoped) file — tenant-safe."""
    stmt = only_active(
        select(Finding).where(Finding.id == finding_id, Finding.loan_file_id == loan_file.id),
        Finding,
    )
    return (await db.execute(stmt)).scalars().first()


async def _document_count(db: DbSession, loan_file_id: UUID) -> int:
    """Active documents on the file — the input to this run's time limits (LP-635).

    Counted at ENQUEUE, so a run's budget reflects the file as it was when the run started. A
    document arriving mid-run does not extend the window it is already inside; it is picked up by the
    next run, which is also the run that would need the extra time.
    """
    return (
        await db.scalar(
            only_active(
                select(func.count())
                .select_from(Document)
                .where(Document.loan_file_id == loan_file_id),
                Document,
            )
        )
    ) or 0


def _enqueue_rule_engine(loan_file_id: UUID, run_id: UUID, *, document_count: int) -> bool:
    """Enqueue the governed snapshot/rules pass (LP-365) ALONGSIDE the sweep, on the same run. Returns
    False on an enqueue failure (broker/worker unavailable) so the caller can mark the run FAILED — the
    task's own fail-closed FAILED only fires if the task RUNS, so an UN-enqueued pass must fail the run
    here, else the sweep would mark it COMPLETED with the governed pass never having run (a false-green).
    Never raises."""
    try:
        from app.tasks.verification_rules import run_rule_engine_pass

        soft, hard = rule_engine_limits(document_count)
        # apply_async, not delay: the limits are PER RUN (LP-635). The decorator's values are only
        # the floor a task gets when something enqueues it without them.
        run_rule_engine_pass.apply_async(
            args=(str(loan_file_id), str(run_id)),
            soft_time_limit=soft,
            time_limit=hard,
        )
        log.info(
            "rule_engine_enqueued",
            loan_file_id=str(loan_file_id),
            documents=document_count,
            soft_time_limit=soft,
        )
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

    # LP-629 — REFUSE A SECOND CONCURRENT RUN ON THIS FILE, and return the one already
    # in flight instead.
    #
    # Two clicks on Run created two runs. That was harmless only because the worker had a
    # single slot and serialised them; with `worker_concurrency > 1` they execute TOGETHER
    # and collide on the findings partial-unique index over
    # ``(loan_file_id, rule_id, subject_key)`` — and a finding-persistence collision is one
    # of the two failures ``run_verification`` deliberately PROPAGATES rather than degrades
    # (services/verification_run.py). So enabling parallelism without this turns a benign
    # double-click into a failed run.
    #
    # Different files are unaffected: the check is scoped to this loan file, which is the
    # whole point — parallelism ACROSS files is what LP-629 exists to deliver.
    #
    # The stale case is handled first and by the SAME watchdog the read path uses, so
    # "stuck" has one definition: a run past ``_STUCK_RUN_TIMEOUT_SECONDS`` is failed here
    # and a fresh one may proceed. A run six minutes into its AI calls looks identical to a
    # wedged one from the outside, and superseding it would destroy real work and real spend.
    #
    # Returning the in-flight run (rather than a 409) keeps the client's contract unchanged:
    # it already polls the returned run to completion, so a double-click simply lands on the
    # run that is genuinely happening. ``force`` deliberately does NOT override this — it
    # bypasses the input-fingerprint CACHE, not the one-run-per-file invariant.
    await _reconcile_stuck_run(db, loan_file)
    in_flight = await _latest_run(db, loan_file.id)
    if in_flight is not None and in_flight.status is VerificationStatus.RUNNING:
        log.info(
            "verification_run_already_in_flight",
            loan_file_id=str(loan_file.id),
            run_id=str(in_flight.id),
        )
        return VerificationRunPublic.from_model(in_flight)

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

    # LP-635 review — the document count and the limit are settled BEFORE the run is committed, so
    # the row is never visible without the limit it was enqueued under. Two commits left a window,
    # however brief, in which the watchdog would read `time_limit_seconds IS NULL` and fall back to
    # re-deriving from the file — the exact question this column exists to stop it asking.
    documents = await _document_count(db, loan_file.id)
    run = await create_verification_run(
        db, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
    )
    run.time_limit_seconds = rule_engine_limits(documents)[1]
    await db.commit()

    # LP-365: the governed snapshot/rules pass runs ALONGSIDE the sweep on the same run. Enqueued on the
    # cache-MISS path only (a new run). A failed enqueue marks the run FAILED (fail-closed: the governed
    # pass must run, or the run must NOT read COMPLETED). NOTE (reported, not fixed): the LP-78.1
    # fingerprint above is keyed on the CROSS-SOURCE inputs; the rule engine reads a SUPERSET (all
    # documents), so a cache-hit could skip a rule run a rule-relevant-only change should have triggered —
    # the cache needs a rule-aware key (its own ticket). Here it simply rides the same trigger as the sweep.
    if not _enqueue_rule_engine(loan_file.id, run.id, document_count=documents):
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
    # LP-590 — the live phase, read only while a run is actually in flight. The row is deleted when
    # the run ends, so this is None for a finished run without a second query to prove it.
    progress = (
        await db.get(VerificationProgress, latest.id)
        if latest is not None and latest.status is VerificationStatus.RUNNING
        else None
    )
    # LP-591 — only while RUNNING, and only when this file has enough history for a median worth
    # trusting. Elapsed is computed here so the browser's clock never enters the arithmetic.
    eta_total = eta_elapsed = None
    if latest is not None and latest.status is VerificationStatus.RUNNING:
        eta_total = await estimated_seconds(db, loan_file_id=loan_file.id)
        if latest.started_at is not None:
            eta_elapsed = int((utcnow() - latest.started_at).total_seconds())

    # LP-375 — the two finding systems are split STRUCTURALLY by ``evaluation_outcome`` (the discriminator;
    # ``origin`` does NOT work for the GOVERNED side — ``deterministic_rule`` spans BOTH the governed rule
    # engine AND retired ``xsrc`` findings). ``findings`` is the LEGACY quarantine — RED/YELLOW.
    #
    # LP-614 — the legacy tab is now AI-TYPED ONLY. It used to carry a second population: the retired
    # ``xsrc.*`` deterministic rules, which also land here (origin ``deterministic_rule``, NO
    # evaluation_outcome). Seven such rows exist on staging, from the two xsrc rules that ever fired —
    # `xsrc.identity.name_consistency` and `xsrc.income.employer_name_consistency` — both retired for
    # contradicting ID-1 and IN-5 with a `_norm` that folds case and whitespace and nothing else. A
    # processor reading "Borrower name differs across sources" next to ID-1's "consistent across all
    # documents" cannot act on the file, which is why they were retired; leaving their output rendering
    # in a tab keeps that contradiction on screen. The rows are NOT deleted — they stop being displayed,
    # and with the pass off (app/tasks/cross_source.py) no more are written.
    findings_stmt = (
        only_active(
            select(Finding).where(
                Finding.loan_file_id == loan_file.id,
                Finding.origin == FindingOrigin.AI_CROSS_SOURCE,
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
        latest_run=(
            VerificationRunPublic.from_model(
                latest,
                progress=progress,
                estimated_total_seconds=eta_total,
                elapsed_seconds=eta_elapsed,
            )
            if latest
            else None
        ),
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
                loan_purpose=loan_file.loan_purpose.value if loan_file.loan_purpose else None,
                document_names=document_names,  # LP-617 — same map FindingPublic already uses
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
    try:
        return await preview_finding_apply(
            db, finding=finding, loan_file=loan_file, actor_user_id=current_user.id
        )
    except CannotApplyError as exc:
        # LP-577 — the dry-run runs the REAL `apply_finding`, so it raises on exactly what the write
        # path raises on: an ambiguous target (two liabilities from the same servicer), a target that
        # is gone, a finding already resolved. Unhandled, the PREVIEW 500'd — so the one flow whose
        # job is to tell a processor "this cannot be applied, and why" was the flow that crashed on
        # it. A 409 carries the reason to the dialog.
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "/{identifier}/snapshot-findings",
    response_model=list[SnapshotFindingPublic],
)
async def list_snapshot_findings_endpoint(
    identifier: str, db: DbSession, current_user: CurrentUser
) -> list[SnapshotFindingPublic]:
    """The snapshot-based AI cross-source findings for this file (LP-586).

    Read-only, and refreshed by the verification run rather than here: asking the model on a page
    load would make the tab move whenever someone looked at it, which is the drift this pass exists
    to remove.
    """
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    rows = await list_snapshot_findings(db, loan_file_id=loan_file.id)
    return [
        SnapshotFindingPublic(
            id=row.id,
            kind=row.kind,
            title=row.title,
            detail=row.detail,
            sources=[SnapshotFindingSource(**s) for s in row.sources],
            disposition=row.disposition,
            disposition_note=row.disposition_note,
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
        )
        for row in rows
    ]


@router.post(
    "/{identifier}/snapshot-findings/{finding_id}/disposition",
    response_model=SnapshotFindingPublic,
)
async def set_snapshot_finding_disposition_endpoint(
    identifier: str,
    finding_id: UUID,
    body: SnapshotFindingDisposition,
    db: DbSession,
    current_user: CurrentUser,
) -> SnapshotFindingPublic:
    """Record what a processor decided about one observation.

    THIS NEVER TOUCHES THE LOAN. There is no apply here — no rule spec, no calibrated threshold,
    no guideline — so the only thing written is the disposition and who set it. The finding itself
    is the model's; the decision is theirs; the loan is neither's to change from this tab.

    Tenant-scoped through the loan file, and the finding must belong to it — a bare id lookup would
    be the cross-tenant read shape `document_borrower_links` records a removal for.
    """
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    row = await db.scalar(
        select(SnapshotFinding).where(
            SnapshotFinding.id == finding_id,
            SnapshotFinding.loan_file_id == loan_file.id,
        )
    )
    if row is None:
        raise _FINDING_NOT_FOUND
    row.disposition = body.disposition
    # LP-589 — ABSENT IS NOT "CLEAR IT". `note` defaults to None, and Reopen sends no note at all, so
    # assigning unconditionally erased the explanation someone wrote when they signed off — silently
    # and unrecoverably. Only an explicitly-supplied note replaces the stored one.
    if body.note is not None:
        row.disposition_note = body.note
    row.disposition_by_user_id = current_user.id
    await db.commit()
    await db.refresh(row)
    return SnapshotFindingPublic(
        id=row.id,
        kind=row.kind,
        title=row.title,
        detail=row.detail,
        sources=[SnapshotFindingSource(**s) for s in row.sources],
        disposition=row.disposition,
        disposition_note=row.disposition_note,
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
    )


@router.post("/{identifier}/findings/{finding_id}/apply", response_model=VerificationStatusPublic)
async def apply_finding_endpoint(
    identifier: str,
    finding_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
    body: ApplyRequest | None = None,
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

    # LP-578 — THE STALENESS GUARD. The preview was computed at T and confirmed at T+30s; in between
    # another processor can edit the target liability, add a second one from the same servicer
    # (turning a clean target into an ambiguous one), soft-delete it, or change an override. Applying
    # anyway would write something other than the before/after this processor approved — and Apply
    # moves an underwriting number, so it refuses and asks them to look again.
    #
    # Optional, deliberately: a caller that sends no fingerprint gets today's behaviour rather than a
    # hard failure. The trade is real — no fingerprint means no protection — and the UI always sends
    # one, so the gap is a non-preview caller (a script, a test) rather than the product path.
    if body is not None and body.expected_fingerprint is not None:
        current = apply_fingerprint(
            finding,
            await build_dti_calculation(db, loan_file=loan_file),
            await build_ltv_calculation(db, loan_file=loan_file),
        )
        if current != body.expected_fingerprint:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=(
                    "This loan file changed since the preview was computed, so applying now would "
                    "not produce the before/after you reviewed. Reopen the preview and confirm again."
                ),
            )

    try:
        await apply_finding(db, finding=finding, loan_file=loan_file, actor_user_id=current_user.id)
    except CannotApplyError as exc:
        # LP-558 — the change did not happen, so the finding stays OPEN and the caller is told. The
        # alternative shipped for a while: a finding marked APPLIED over a loan file nothing was
        # written to, and a DTI the processor trusted that had not moved.
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(loan_file)
    return await _build_status(db, loan_file=loan_file, user=current_user)


@router.post("/{identifier}/findings/request-docs", response_model=VerificationStatusPublic)
async def bulk_request_docs_endpoint(
    identifier: str,
    payload: BulkRequestDocsRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> VerificationStatusPublic:
    """Request every document a set of findings is waiting on — ONE needs item per DOCUMENT (LP-562).

    A COLLECTION route, deliberately: it acts on many findings, so there is no single `finding_id` to
    key it on. LP-562 shipped the service, the schema and the button but not this, and the button
    404'd — the whole path had no API test, only service tests.

    The grouping is computed here because this is where the file's documents are already known, and it
    uses the SAME `_missing_documents` the row renders, so the button and the card can never disagree
    about what is still outstanding.
    """
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND

    doc_rows = (
        await db.execute(
            only_active(
                select(Document.document_type).where(Document.loan_file_id == loan_file.id),
                Document,
            )
        )
    ).all()
    on_file = {row.document_type for row in doc_rows if row.document_type}
    purpose = loan_file.loan_purpose.value if loan_file.loan_purpose else None

    by_document: dict[str, list[Finding]] = {}
    for finding_id in payload.finding_ids:
        finding = await _get_finding(db, loan_file=loan_file, finding_id=finding_id)
        if finding is None:
            continue
        # LP-624 — THE SAME ANSWER THE CARD RENDERED. `RuleFindingPublic.from_model` prefers the
        # evaluator's own `requested_documents` over the spec-derived list; this recomputed only the
        # spec-derived one, so for ID-2/ID-3's single-source abstention — where the spec yields [] —
        # the card showed a request and put the finding in the "request these" bucket, the processor
        # clicked "Request all N", and nothing was created and nothing marked `docs_requested`. This
        # endpoint's own docstring promises the button and the card can never disagree; it does now.
        details = finding.details if isinstance(finding.details, Mapping) else {}
        documents = _requested_documents(details) or _missing_documents(
            _rule_spec(finding.rule_id), on_file, loan_purpose=purpose
        )
        for document in documents:
            by_document.setdefault(document, []).append(finding)

    await request_documents_in_bulk(
        db,
        loan_file=loan_file,
        by_document=by_document,
        actor_user_id=current_user.id,
        note=payload.note,
    )
    await db.commit()
    await db.refresh(loan_file)
    return await _build_status(db, loan_file=loan_file, user=current_user)


@router.post("/{identifier}/findings/{finding_id}/ratify", response_model=VerificationStatusPublic)
async def ratify_finding_endpoint(
    identifier: str,
    finding_id: UUID,
    payload: RatifyRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> VerificationStatusPublic:
    """Record that a human reviewed an AI judgment and AGREED with it (LP-560).

    Changes no structured data. What changes is that the verdict now carries a person's name — the
    thing `ratification_pending` promises and that, until now, nothing could perform. The note is
    optional; Override's reason is required because it contradicts the system, where this agrees with
    what the finding already says.
    """
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    finding = await _get_finding(db, loan_file=loan_file, finding_id=finding_id)
    if finding is None:
        raise _FINDING_NOT_FOUND
    try:
        await ratify_finding(db, finding=finding, actor_user_id=current_user.id, note=payload.note)
    except CannotRatifyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
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


# LP-592 — what "needs attention" means, matching the tab that bears the name: everything that is
# not a pass and not out of scope. `no_longer_applies` is excluded because it is history, not work.
_ATTENTION_OUTCOMES = frozenset(
    {
        EvaluationOutcome.OPEN,
        EvaluationOutcome.COULDNT_CHECK,
        EvaluationOutcome.NEEDS_REVIEW,
        EvaluationOutcome.PENDING_AUTOMATION,
    }
)


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
    # LP-600 — the governed outcome counts, per run, FROM THE EVENT LOG.
    #
    # ⚠️ NOT FROM `Finding.verification_id`, which is what LP-592 did and what made every historical
    # run render as "produced no findings". That column is REASSIGNED on every run: `_update_finding`
    # sets it for each re-detected finding and the retire loop does the same, so after run 2 almost
    # all of run 1's findings point at run 2. Grouping by it returns rows for the latest run only.
    # LP-592's own comment claimed the answer "cannot drift from the findings themselves" — the exact
    # opposite of what reconcile does two files away.
    #
    # `finding_events` is APPEND-ONLY and genuinely per-run: each detected finding gets exactly one
    # event per run carrying `to_outcome`, and `detail->>'run_id'` is the verification id (the task
    # passes `run_id=run.id, verification_id=run.id`). So this is exact for every run, including the
    # ones already in the database — no migration, no denormalised column to keep in step.
    #
    # The two filters are the PANEL's (`rule_findings_stmt`), so a history badge counts exactly what
    # its tab shows: a soft-deleted finding, or one of a non-shown origin, is in neither.
    counts: dict[UUID, dict[str, int]] = {}
    if runs:
        run_id_expr = FindingEvent.detail["run_id"].astext
        outcome_rows = await db.execute(
            select(
                run_id_expr,
                FindingEvent.to_outcome,
                func.count(),
            )
            .join(Finding, Finding.id == FindingEvent.finding_id)
            .where(
                run_id_expr.in_([str(r.id) for r in runs]),
                Finding.deleted_at.is_(None),
                Finding.origin.in_(_SHOWN_ORIGINS),
            )
            .group_by(run_id_expr, FindingEvent.to_outcome)
        )
        for run_id_raw, outcome, total in outcome_rows:
            run_id_ = UUID(run_id_raw)
            bucket = counts.setdefault(run_id_, {"attention": 0, "satisfied": 0})
            if outcome is EvaluationOutcome.SATISFIED:
                bucket["satisfied"] += total
            elif outcome in _ATTENTION_OUTCOMES:
                bucket["attention"] += total
    return [
        VerificationRunPublic.from_model(
            r,
            attention_count=counts.get(r.id, {}).get("attention", 0),
            satisfied_count=counts.get(r.id, {}).get("satisfied", 0),
        )
        for r in runs
    ]
