"""Document processing pipeline tasks (LP-42).

On upload, :func:`process_document` chains, for one document, independently:

    read bytes → classify (Haiku) → look up the type's tier in the catalog →
    route by tier → (Tier 1) extract via the registry (Opus) → persist a
    versioned Extraction (+ cost) → set a TERMINAL status → enqueue the per-file
    needs update (LP-68, serialized) → log activity.

Classification + the catalog **route** handling (LP-58, tier-aware): the
classified type's tier (from :mod:`app.documents.catalog`) selects the path —
**Tier 1** runs the registered extractor (a Tier-1 type whose extractor isn't
built yet is classified-only); **Tier 2** is the shared recognize/summarize path
(LP-65 — one lightweight summary for any Tier-2 type); **Tier 3** is scoped FREE
EXTRACTION (LP-463; was the LP-66 generic analyzer) — one flexible, mortgage-scoped
read for any document with no fitting catalog type. Catalog types are tried FIRST;
free extraction is the fallback. A document whose LABEL cannot be trusted — a
model-admitted type↔document mismatch (LP-463 ``type_matches_document``) or a
low-confidence pick — is routed to Tier 3 (READ), not left unread, and lands in
NEEDS_REVIEW. The ``Document.status`` field is the source of truth the UI polls
(LP-43), so the status is transitioned and committed at each stage.

**Resilience.** Each document is processed on its own; one document's failure
never crashes the worker or affects others. Graceful classify/extract outcomes
(``unknown`` / ``failed``) are *expected* → ``NEEDS_REVIEW``. Any *unexpected*
exception → ``FAILED`` with a **safe** ``processing_error`` (never raw PII).
Every handled path reaches a terminal status (COMPLETED / NEEDS_REVIEW / FAILED)
— never left stuck in CLASSIFYING / EXTRACTING.

**Retry-safe.** Re-running is safe: extraction uses ``create_extraction_version``
(a new version, not a duplicate current), and the needs update (LP-68, a separate
per-file-serialized task) only advances an OPEN need (a satisfied one is left alone).

**Async bridge (LP-41).** The Celery task is sync; the real work (DB, storage,
classify, extract) is async, run via ``run_async`` inside one coroutine using a
worker async session (``task_session``).

**Privacy.** Never logs document bytes/text or extracted values — only metadata
(ids, status, classified type, confidence, tokens/cost).
"""

from uuid import UUID

import structlog
from celery import Task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.classification import classify_document
from app.ai.client import INFRA_RATE_LIMITED
from app.ai.cost import estimate_cost
from app.ai.extraction import EXTRACTORS, Extractor
from app.ai.extraction.parsing import document_confidence_provenance
from app.ai.generic_analyzer import analyze_document
from app.ai.summarization import summarize_document
from app.core.config import resolve_model, settings
from app.documents.catalog import get_category, get_tier
from app.models.activity_log import ActivityType
from app.models.document import Document, DocumentStatus, Tier
from app.models.extraction import ExtractionStatus
from app.models.helpers import only_active
from app.services.activity_log import log_activity
from app.services.document_findings import (
    coerce_finding_type,
    create_document_finding,
    record_findings_from_extraction,
)
from app.services.extractions import create_extraction_version
from app.storage import get_storage_backend
from app.tasks.base import run_async, task_session
from app.tasks.celery_app import celery_app
from app.tasks.needs import update_needs_for_document
from app.tasks.retry import MAX_RETRIES, retry_or_terminal

logger = structlog.get_logger(__name__)

# Below this classification/extraction confidence (or an "unknown" type) the
# document is routed to human review rather than trusted. Tune with real data.
_CONFIDENCE_THRESHOLD = 0.5


async def _load_document(db: AsyncSession, document_id: str) -> Document | None:
    """Load an active document by id (string from the task message)."""
    try:
        pk = UUID(document_id)
    except ValueError:
        return None
    stmt = only_active(select(Document).where(Document.id == pk), Document)
    document: Document | None = await db.scalar(stmt)
    return document


def _enqueue_needs_update(loan_file_id: UUID, document_id: UUID) -> None:
    """Fire-and-forget enqueue of the LP-68 per-file-serialized needs update.

    The document already reached a terminal status (committed); the needs update is
    a separate, serialized task (:mod:`app.tasks.needs`). An enqueue hiccup (broker
    down) must NOT fail processing — the document is safe and the update can re-run.
    """
    try:
        update_needs_for_document.delay(str(loan_file_id), str(document_id))
    except Exception:
        logger.warning("needs_update_enqueue_failed", document_id=str(document_id))


async def _process_document(db: AsyncSession, document_id: str) -> None:
    """The core pipeline for one document. Never raises; always reaches a terminal status.

    Takes the session explicitly so it is unit-testable with the test session;
    the Celery task wraps it with a worker session (:func:`task_session`).
    """
    document = await _load_document(db, document_id)
    if document is None:
        # Soft-deleted or gone between enqueue and run — nothing to do.
        logger.info("process_document_missing", document_id=document_id)
        return

    try:
        content = await get_storage_backend().read(document.storage_path)

        # --- Classify -------------------------------------------------------- #
        document.status = DocumentStatus.CLASSIFYING
        await db.commit()
        classification = await classify_document(content, document.mime_type)

        # --- Infrastructure-failure gate (LP-462) → NEEDS_REVIEW, but DISTINCT - #
        # A classification that never COMPLETED (throttled, or a payload over the
        # document-block limit) must be recorded as INFRASTRUCTURE, not a JUDGMENT:
        # a throttle is not a coverage gap, and framing it as one corrupts every
        # downstream audit. Gate BEFORE the classification-success block so we never
        # stamp document_type="unknown" or persist a "Classified as unknown"
        # activity for a call that never ran — the audit trail instead records the
        # infrastructure cause (rate_limited / oversized / failed) and the document
        # stays re-runnable. (Same terminal status; a different, honest cause.)
        if classification.infra_failure is not None:
            document.status = DocumentStatus.NEEDS_REVIEW
            await log_activity(
                db,
                loan_file_id=document.loan_file_id,
                activity_type=ActivityType.STATUS_CHANGED,
                summary=f"Classification incomplete ({classification.infra_failure}) — needs review",
                detail={
                    "document_id": str(document.id),
                    "infra_failure": classification.infra_failure,
                },
            )
            await db.commit()
            logger.info(
                "document_needs_review",
                document_id=str(document.id),
                reason=classification.infra_failure,
                infra_failure=True,
            )
            return

        # --- LP-463: do NOT apply a label the model flagged as wrong -------- #
        # ``type_matches_document`` False means the model chose a type but told us
        # it does NOT describe the document it named (the T4→w2 harm — a wrong
        # schema applied to a confidently-mislabelled form, invisible downstream).
        # Honour "do not apply the label": store the type as ``unknown`` (the
        # document is still READ via Tier 3 free extraction below), and keep the
        # model's rejected pick + its own name for the human in the activity detail.
        type_mismatch = not classification.type_matches_document
        effective_type = "unknown" if type_mismatch else classification.document_type

        document.document_type = effective_type
        # Catalog-driven (LP-58): the type's tier (for routing) + category (for
        # filing) both come from the single source of truth, so they never drift.
        document.tier = get_tier(effective_type)
        document.category = get_category(effective_type)
        document.classification_confidence = classification.confidence
        document.status = DocumentStatus.CLASSIFIED
        await db.commit()
        await log_activity(
            db,
            loan_file_id=document.loan_file_id,
            activity_type=ActivityType.DOCUMENT_PROCESSED,
            summary=(
                f"Classified as {effective_type}"
                + (
                    f" — model picked {classification.document_type!r} but flagged it as not matching"
                    if type_mismatch
                    else ""
                )
            ),
            detail={
                "document_id": str(document.id),
                "document_type": effective_type,
                "confidence": classification.confidence,
                **(
                    {"rejected_type": classification.document_type, "type_mismatch": True}
                    if type_mismatch
                    else {}
                ),
            },
        )

        # --- Review gate: flag, but STILL READ (LP-59 low-conf + LP-463 mismatch) - #
        # A document whose LABEL we cannot trust — the model's confidence is low, OR
        # the model itself flagged a type-vs-document mismatch — is flagged for human
        # review. Unlike before (a bare NEEDS_REVIEW that left the document unread),
        # a flagged document now routes to Tier 3 FREE EXTRACTION so its
        # mortgage-relevant facts are still captured, then reaches a NEEDS_REVIEW
        # terminal status. Catalog types are tried first (below); free extraction is
        # the fallback for the flagged / declined tail, never the default.
        review_reason: str | None = None
        if type_mismatch:
            review_reason = "type_mismatch"
        elif classification.confidence < _CONFIDENCE_THRESHOLD:
            review_reason = "low_confidence"

        if review_reason is not None:
            logger.info("document_needs_review", document_id=str(document.id), reason=review_reason)
            await _tier3_analyze(db, document, content, review_reason=review_reason)
            # A flagged document's LABEL is not trusted, so it must NOT auto-advance a need (the pre-LP-463
            # low-confidence gate returned here too). Its untrusted document_type would drive a matching OPEN
            # need RECEIVED→REJECTED, and REJECTED is not in the matcher's OPEN set — so the genuine document
            # could never advance that need later. The LP-44 human override advances it once the type is
            # confirmed. type_mismatch stores "unknown" (matches no need) so this only bites low_confidence.
            return

        # --- Route by tier (catalog-driven, LP-58) -------------------------- #
        # A confidently-classified, self-consistent type. Each tier has one handling
        # path, every path terminal. A confident "unknown" routes here to Tier 3 free
        # extraction (the catalog default) and COMPLETES.
        await _route_by_tier(db, document, content)

        # --- Update the needs list (LP-68) — SERIALIZED per loan file -------- #
        # The document is now terminal + committed; advance any matching need in a
        # separate per-file-serialized task (concurrent arrivals never race).
        _enqueue_needs_update(document.loan_file_id, document.id)
    except Exception as exc:
        # UNEXPECTED (storage/DB/etc.) — never crash the worker or the batch.
        logger.warning(
            "process_document_failed",
            document_id=document_id,
            error_type=type(exc).__name__,
        )  # metadata only — no PII
        await _mark_failed(db, document, document_id)


async def _route_by_tier(db: AsyncSession, document: Document, content: bytes) -> None:
    """Dispatch a classified document to its tier's handling path (LP-58).

    The tier was set from the catalog during classification. Exactly one branch
    runs and every branch reaches a terminal status:

      * **Tier 1** → the existing EXTRACTORS registry (deep extraction). A Tier-1
        type whose extractor isn't registered yet (LP-441 promoted 18 spec'd types
        to Tier-1 before step 7 wires their extractors) falls back to the SAME
        interim treatment a Tier-2 type gets — a lightweight summary — so a
        promoted type keeps its human-reference gist until deep extraction lands,
        rather than silently losing it (LP-441 review). NOT a crash.
      * **Tier 2** → the shared recognize/summarize path (LP-65) — one mechanism
        for every Tier-2 type: a lightweight summary, then a terminal status.
      * **Tier 3** → scoped free extraction (LP-463) — one flexible read for any
        unrecognized document (+ recorded findings, the untyped snapshot section).

    Reached only for a document whose label is TRUSTED (self-consistent + not
    low-confidence) — the LP-463 review gate routes a flagged/declined document
    straight to :func:`_tier3_analyze` before this point. A confident ``unknown``
    still lands in the Tier 3 branch here and COMPLETES.
    """
    if document.tier == Tier.TIER_1:
        extractor = EXTRACTORS.get(document.document_type or "")
        if extractor is not None:
            await _extract_branch(db, document, content, extractor)
        else:
            # A Tier-1 type whose extractor isn't registered yet (LP-441 — promoted before its
            # extractor is wired). Give it the Tier-2 interim summary (not classified-only): a
            # promoted type keeps its gist until deep extraction lands (LP-441 review).
            await _summarize_document(db, document, content)
    elif document.tier == Tier.TIER_2:
        await _summarize_document(db, document, content)
    else:  # Tier.TIER_3 (the catalog default for uncataloged long-tail types)
        await _tier3_analyze(db, document, content)


async def _summarize_document(db: AsyncSession, document: Document, content: bytes) -> None:
    """The shared recognize/summarize path (LP-65) — the interim treatment for a document that
    reaches a terminal status WITHOUT deep extraction: every Tier-2 type, and a Tier-1 type whose
    extractor isn't wired yet (LP-441 review — a promoted-but-unwired type keeps its gist).

    No per-type logic: the document (already classified + categorized, LP-59) gets a single
    lightweight 1-2 sentence AI **summary** (a human-reference gist, not extraction —
    :func:`app.ai.summarization.summarize_document`, a cheap Haiku call) and reaches a terminal
    status. The document is a normal, package-eligible file document filed under its category.

    **Graceful** (resilience): ``summarize_document`` never raises and returns ``None`` on failure;
    a failed summary still finalizes the document (recognized + categorized, ``summary`` null) —
    never stuck, never a crash. Metadata-only log (the summary text itself is never logged — it can
    quote document PII).
    """
    document.summary = await summarize_document(content, document.mime_type)
    document.status = DocumentStatus.COMPLETED
    await db.commit()
    logger.info(
        "document_summarized",
        document_id=str(document.id),
        document_type=document.document_type,
        tier=document.tier,
        category=document.category,
        has_summary=document.summary is not None,
    )


async def _tier3_analyze(
    db: AsyncSession, document: Document, content: bytes, *, review_reason: str | None = None
) -> None:
    """Tier 3 (long-tail) handling — scoped FREE EXTRACTION (LP-463; was generic analysis, LP-66).

    No per-type logic: a document with no fitting catalog type — a confident ``unknown``, or one FLAGGED
    for review (low confidence, or a model-admitted type-vs-document mismatch) — is read by the flexible
    free extractor (:func:`app.ai.generic_analyzer.analyze_document`), now SCOPED to mortgage-relevant
    facts (parties, amounts, dates, identifiers, obligations, terms) and told to skip boilerplate (LP-463
    A4). The output is stored on the document (``generic_analysis``) — surfaced into the snapshot's
    marked-UNTYPED section for a processor + AI cross-source reasoning, NEVER a deterministic rule
    (LP-463) — and each ``key_finding`` is recorded as a :class:`DocumentFinding` (uniform across tiers).

    ``review_reason`` (LP-463): when set (``type_mismatch`` / ``low_confidence``), the document is READ but
    reaches a **NEEDS_REVIEW** terminal status — a flagged document is no longer left unread. When None (a
    confident ``unknown`` / uncataloged type), it COMPLETES normally.

    **Graceful** (resilience): ``analyze_document`` never raises and returns ``None`` on failure; a failed
    analysis still finalizes the document (analysis null, no findings) — never stuck, never a crash.
    Metadata-only log (no extracted values).
    """
    analysis = await analyze_document(content, document.mime_type)
    findings_count = 0
    if analysis is not None:
        # Store the structured free extraction (the full text lives in its own column).
        document.generic_analysis = analysis.model_dump(mode="json", exclude={"full_text"})
        document.full_text = analysis.full_text
        for f in analysis.key_findings:
            await create_document_finding(
                db,
                document=document,
                finding_type=coerce_finding_type(f.finding_type),
                description=f.description or "(no description)",
                amount=f.amount,
                frequency=f.frequency,
                details=f.details,
            )
            findings_count += 1

    # A flagged document is READ (above) but still needs a human; a clean unknown completes.
    document.status = (
        DocumentStatus.NEEDS_REVIEW if review_reason is not None else DocumentStatus.COMPLETED
    )
    await db.commit()
    logger.info(
        "document_tier3_analyzed",
        document_id=str(document.id),
        document_type=document.document_type,
        has_analysis=analysis is not None,
        findings_count=findings_count,
        review_reason=review_reason,
    )


async def _extract_branch(
    db: AsyncSession, document: Document, content: bytes, extractor: Extractor
) -> None:
    """Run the registered extractor, persist a versioned extraction (+ cost), set terminal status.

    Type-agnostic (LP-39c): any extractor result is stored uniformly via
    ``create_extraction_version`` (its ``data.model_dump`` JSON), and the
    typed-core/transactions/catch-all shape just rides in that JSON.
    """
    document.status = DocumentStatus.EXTRACTING
    await db.commit()

    result = await extractor(content, document.mime_type)

    # --- LP-464: a THROTTLED extraction is infrastructure, not a content failure - #
    # The extraction call never completed — it was rate-limited (the LP-462 retry is
    # shared, so this only survives a sustained burst). Recording it as a FAILED
    # extraction would read as a coverage gap and corrupt every downstream audit —
    # the exact corrosion LP-462 fixed for classification, now on the extraction
    # path. Gate BEFORE persisting an extraction version: no content was produced,
    # so nothing is recorded as content; the document is flagged re-runnable.
    # (109 extractors surface the call's ``failure_reason`` as ``reasoning``, so the
    # throttle marker rides that channel — no per-extractor change.)
    if result.status == ExtractionStatus.FAILED and result.reasoning == INFRA_RATE_LIMITED:
        document.status = DocumentStatus.NEEDS_REVIEW
        document.processing_error = "extraction throttled (rate_limited) — re-runnable"
        await db.commit()
        logger.info(
            "document_needs_review",
            document_id=str(document.id),
            reason="rate_limited",
            infra_failure=True,
        )
        return

    # The model that ACTUALLY ran (B1): under AI_PROVIDER=bedrock this is the
    # inference-profile id, not the tier value. Recording the tier value instead would
    # both mislabel `model_used` and price the call against the wrong key.
    invoked_model = resolve_model(settings.anthropic_model_extraction)

    tokens_used: int | None = None
    cost_estimate: float | None = None
    if result.input_tokens is not None and result.output_tokens is not None:
        tokens_used = result.input_tokens + result.output_tokens
        cost_estimate = estimate_cost(
            model=invoked_model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )

    # LP-201: persist the document-level confidence honestly — a failed/defaulted
    # 0.0 is stored as NULL / not_provided, never mislabelled model_self_reported.
    reported_confidence, confidence_source = document_confidence_provenance(result.confidence)
    await create_extraction_version(
        db,
        document_id=document.id,
        extracted_data=result.data.model_dump(mode="json"),
        extraction_status=result.status,
        model_used=invoked_model,
        tokens_used=tokens_used,
        cost_estimate=cost_estimate,
        error_detail=result.reasoning if result.status == ExtractionStatus.FAILED else None,
        confidence=reported_confidence,
        confidence_source=confidence_source,
    )

    if result.status == ExtractionStatus.FAILED or result.confidence < _CONFIDENCE_THRESHOLD:
        document.status = DocumentStatus.NEEDS_REVIEW
        document.processing_error = "extraction failed or low confidence"
        await db.commit()
        logger.info("document_needs_review", document_id=str(document.id), reason="extraction")
        return

    document.status = DocumentStatus.COMPLETED
    # The needs update (satisfaction-matching) is enqueued once, per-file-serialized,
    # at the end of _process_document (LP-68) — not inline here (which would race
    # under concurrent same-file arrivals). Record any findings the extraction
    # surfaced (LP-66) — e.g. a divorce decree's obligations → findings (LP-63 loop).
    findings_count = await record_findings_from_extraction(db, document, result.data)
    await db.commit()
    logger.info(
        "document_completed",
        document_id=str(document.id),
        extraction_status=result.status,
        tokens_used=tokens_used,
        cost_estimate=cost_estimate,
        findings_count=findings_count,
    )


async def _mark_failed(db: AsyncSession, document: Document, document_id: str) -> None:
    """Set a document FAILED with a safe message. Never raises.

    The common case (a storage/AI error, no failed DB flush) just sets the status
    on the already-loaded document and commits — no rollback needed. Only if that
    fails (the session is in a failed-transaction state from a DB error
    mid-pipeline) do we rollback, re-load, and retry once. If even that can't
    complete, it is logged and the task ends — the worker is never crashed.
    """
    try:
        document.status = DocumentStatus.FAILED
        document.processing_error = "processing error"  # safe message, no raw PII
        await db.commit()
        return
    except Exception:
        logger.warning("process_document_mark_failed_retry", document_id=document_id)

    try:
        await db.rollback()
        reloaded = await _load_document(db, document_id)
        if reloaded is not None:
            reloaded.status = DocumentStatus.FAILED
            reloaded.processing_error = "processing error"
            await db.commit()
    except Exception:
        logger.error("process_document_mark_failed_error", document_id=document_id)


async def reprocess_document_extraction(db: AsyncSession, document: Document) -> None:
    """Re-run extraction for an already-classified document via the SAME registry.

    The reusable core a type-override / reprocess flow (LP-44) calls after changing
    a document's ``document_type``: it re-reads the bytes and runs the registered
    extractor for the (new) type through the same ``_extract_branch`` — so a manual
    correction to any of the three types re-extracts correctly, and an unregistered
    type falls back to classified-only. Retry-safe (versioned extraction; needs not
    double-satisfied) and resilient (unexpected error → FAILED). Never raises.

    The LP-44 override **endpoint/UI** is not built here — this is the core it uses.
    """
    extractor = EXTRACTORS.get(document.document_type or "")
    if extractor is None:
        document.status = DocumentStatus.COMPLETED  # classified-only
        await db.commit()
        return
    try:
        content = await get_storage_backend().read(document.storage_path)
        await _extract_branch(db, document, content, extractor)
    except Exception as exc:
        logger.warning(
            "reprocess_document_failed",
            document_id=str(document.id),
            error_type=type(exc).__name__,
        )
        await _mark_failed(db, document, str(document.id))


async def _run(document_id: str) -> None:
    """Open a worker session and run the pipeline (the async entrypoint)."""
    async with task_session() as db:
        await _process_document(db, document_id)


async def _run_reprocess(document_id: str) -> None:
    """Open a worker session, load the document, and re-extract it (entrypoint)."""
    async with task_session() as db:
        document = await _load_document(db, document_id)
        if document is None:
            logger.info("reprocess_document_missing", document_id=document_id)
            return
        await reprocess_document_extraction(db, document)


async def _mark_document_failed(document_id: str) -> None:
    """Terminal-failed (LP-73): set the document FAILED if a transient infra error
    (e.g. a DB/Redis blip outside the pipeline's own handling) exhausted retries —
    so it is never left silently stranded in a non-terminal status."""
    async with task_session() as db:
        document = await _load_document(db, document_id)
        if document is not None:
            await _mark_failed(db, document, document_id)


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True, name="documents.process_document", max_retries=MAX_RETRIES
)
def process_document(self: Task, document_id: str) -> None:
    """Celery task: process one uploaded document end-to-end (sync→async bridge).

    The pipeline itself never raises (it sets its own terminal status); this bounded
    retry (LP-73) covers a transient infra error *around* it, and on exhaustion marks
    the document FAILED rather than leaving it stranded.
    """
    retry_or_terminal(
        self,
        lambda: run_async(_run(document_id)),
        on_exhausted=lambda: run_async(_mark_document_failed(document_id)),
        event="process_document_exhausted",
    )


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True, name="documents.reprocess_document", max_retries=MAX_RETRIES
)
def reprocess_document(self: Task, document_id: str) -> None:
    """Celery task: re-extract a document after a manual type override (LP-44).

    A thin wrapper over the existing :func:`reprocess_document_extraction` core
    (LP-39c, registry-based, skips classification, new version, resilient) — the
    PATCH override endpoint enqueues this. Bounded-retry on a transient blip (LP-73).
    """
    retry_or_terminal(
        self,
        lambda: run_async(_run_reprocess(document_id)),
        on_exhausted=lambda: run_async(_mark_document_failed(document_id)),
        event="reprocess_document_exhausted",
    )
