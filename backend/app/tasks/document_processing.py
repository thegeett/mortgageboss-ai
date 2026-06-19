"""Document processing pipeline tasks (LP-42).

On upload, :func:`process_document` chains, for one document, independently:

    read bytes → classify (Haiku) → look up the type's tier in the catalog →
    route by tier → (Tier 1) extract via the registry (Sonnet) → persist a
    versioned Extraction (+ cost) → satisfy a matching need → log activity →
    set a TERMINAL status.

Classification + the catalog **route** handling (LP-58, tier-aware): the
classified type's tier (from :mod:`app.documents.catalog`) selects the path —
**Tier 1** runs the registered extractor (a Tier-1 type whose extractor isn't
built yet is classified-only); **Tier 2** is the recognized/summarize path (an
LP-65 stub); **Tier 3** is the generic-analyzer path (an LP-66 stub). The
``Document.status`` field is the source of truth the UI polls (LP-43), so the
status is transitioned and committed at each stage.

**Resilience.** Each document is processed on its own; one document's failure
never crashes the worker or affects others. Graceful classify/extract outcomes
(``unknown`` / ``failed``) are *expected* → ``NEEDS_REVIEW``. Any *unexpected*
exception → ``FAILED`` with a **safe** ``processing_error`` (never raw PII).
Every handled path reaches a terminal status (COMPLETED / NEEDS_REVIEW / FAILED)
— never left stuck in CLASSIFYING / EXTRACTING.

**Retry-safe.** Re-running is safe: extraction uses ``create_extraction_version``
(a new version, not a duplicate current), and needs-matching only acts on an
``OUTSTANDING`` need (a ``RECEIVED`` one is left alone).

**Async bridge (LP-41).** The Celery task is sync; the real work (DB, storage,
classify, extract) is async, run via ``run_async`` inside one coroutine using a
worker async session (``task_session``).

**Privacy.** Never logs document bytes/text or extracted values — only metadata
(ids, status, classified type, confidence, tokens/cost).
"""

from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.classification import classify_document
from app.ai.cost import estimate_cost
from app.ai.extraction import EXTRACTORS, Extractor
from app.core.config import settings
from app.documents.catalog import get_category, get_tier
from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.document import Document, DocumentStatus, Tier
from app.models.extraction import ExtractionStatus
from app.models.helpers import only_active
from app.models.needs_item import NeedsItem, NeedsItemStatus
from app.services.activity_log import log_activity
from app.services.extractions import create_extraction_version
from app.storage import get_storage_backend
from app.tasks.base import run_async, task_session
from app.tasks.celery_app import celery_app

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


async def _satisfy_needs_for_document(db: AsyncSession, document: Document) -> None:
    """Mark one OUTSTANDING need in the document's category RECEIVED (PROVISIONAL rule).

    **PROVISIONAL — refine with Priya / Phase 2.** V1 rule: a successfully-extracted
    document satisfies the first OUTSTANDING needs item on the same loan file whose
    category matches the document's (e.g. a pay stub / W-2 → an income need; a bank
    statement → an assets need). Only ``OUTSTANDING`` needs are touched, so
    re-processing never double-satisfies (a ``RECEIVED`` need is left alone). No
    category or no match → no-op.
    """
    if document.category is None:
        return
    stmt = (
        select(NeedsItem)
        .where(
            NeedsItem.loan_file_id == document.loan_file_id,
            NeedsItem.status == NeedsItemStatus.OUTSTANDING,
            NeedsItem.category == document.category,
        )
        .order_by(NeedsItem.created_at)
        .limit(1)
    )
    stmt = only_active(stmt, NeedsItem)
    need = await db.scalar(stmt)
    if need is None:
        return
    need.status = NeedsItemStatus.RECEIVED
    need.satisfied_by_document_id = document.id
    need.satisfied_at = utcnow()
    await log_activity(
        db,
        loan_file_id=document.loan_file_id,
        activity_type=ActivityType.NEEDS_ITEM_SATISFIED,
        summary="A document satisfied an outstanding need",
        detail={"need_id": str(need.id), "document_id": str(document.id)},
    )


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
        document.document_type = classification.document_type
        # Catalog-driven (LP-58): the type's tier (for routing) + category (for
        # filing) both come from the single source of truth, so they never drift.
        document.tier = get_tier(classification.document_type)
        document.category = get_category(classification.document_type)
        document.classification_confidence = classification.confidence
        document.status = DocumentStatus.CLASSIFIED
        await db.commit()
        await log_activity(
            db,
            loan_file_id=document.loan_file_id,
            activity_type=ActivityType.DOCUMENT_PROCESSED,
            summary=f"Classified as {classification.document_type}",
            detail={
                "document_id": str(document.id),
                "document_type": classification.document_type,
                "confidence": classification.confidence,
            },
        )

        # --- Low-confidence / unknown gate → human review -------------------- #
        if (
            classification.document_type == "unknown"
            or classification.confidence < _CONFIDENCE_THRESHOLD
        ):
            document.status = DocumentStatus.NEEDS_REVIEW
            await db.commit()
            logger.info(
                "document_needs_review",
                document_id=str(document.id),
                reason="low_confidence_or_unknown",
            )
            return

        # --- Route by tier (catalog-driven, LP-58) -------------------------- #
        # The catalog gave the document its tier above; each tier has one
        # handling path, and every path reaches a terminal status (resilience).
        await _route_by_tier(db, document, content)
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

      * **Tier 1** → the existing EXTRACTORS registry (unchanged for the 3 built
        types). A Tier-1 type whose extractor isn't built yet (LP-60..64) has no
        registry entry → handled gracefully as *classified-only* (a terminal
        status), NOT a crash; its extractor arrives in a later ticket.
      * **Tier 2** → the recognized/summarize path — a clean stub for LP-65.
      * **Tier 3** → the generic-analyzer path — a clean stub for LP-66.

    The low-confidence / ``unknown`` gate already routed those to NEEDS_REVIEW
    before this point, so here the document is a confidently-classified type.
    """
    if document.tier == Tier.TIER_1:
        extractor = EXTRACTORS.get(document.document_type or "")
        if extractor is not None:
            await _extract_branch(db, document, content, extractor)
        else:
            # A Tier-1 type whose extractor isn't registered yet (LP-60..64).
            # Classified-only — the same terminal handling the pipeline has always
            # used for a type with no extractor; deep extraction arrives later.
            await _complete_classified_only(db, document, reason="tier1_extractor_pending")
    elif document.tier == Tier.TIER_2:
        await _tier2_summarize_stub(db, document)
    else:  # Tier.TIER_3 (the catalog default for uncataloged long-tail types)
        await _tier3_analyze_stub(db, document)


async def _complete_classified_only(db: AsyncSession, document: Document, *, reason: str) -> None:
    """Mark a correctly-classified document COMPLETED with no extraction (terminal).

    Used when no extractor runs: a Tier-1 type whose extractor isn't built yet
    (LP-60..64). The document is classified + categorized; it simply has no deep
    extraction. Metadata-only log (no PII).
    """
    document.status = DocumentStatus.COMPLETED
    await db.commit()
    logger.info(
        "document_classified_only",
        document_id=str(document.id),
        document_type=document.document_type,
        reason=reason,
    )


async def _tier2_summarize_stub(db: AsyncSession, document: Document) -> None:
    """Tier 2 (recognized) handling — a CLEAN STUB for LP-65 (terminal status).

    A Tier-2 document is correctly classified + categorized but gets no deep
    extraction; LP-65 will add a short AI summary for processor reference *here*,
    without restructuring the routing. For now we record it as handled at its
    tier and reach a terminal status. Metadata-only log (no PII).
    """
    document.status = DocumentStatus.COMPLETED
    await db.commit()
    logger.info(
        "document_tier2_recognized",
        document_id=str(document.id),
        document_type=document.document_type,
        category=document.category,
        summary="pending_lp65",
    )


async def _tier3_analyze_stub(db: AsyncSession, document: Document) -> None:
    """Tier 3 (long-tail) handling — a CLEAN STUB for LP-66 (terminal status).

    A Tier-3 document is a confidently-classified type the catalog doesn't know
    (the long-tail). LP-66 will run a generic analyzer to produce a structured
    summary *here*, without restructuring the routing. For now we record it as
    handled at its tier and reach a terminal status. Metadata-only log (no PII).
    """
    document.status = DocumentStatus.COMPLETED
    await db.commit()
    logger.info(
        "document_tier3_long_tail",
        document_id=str(document.id),
        document_type=document.document_type,
        category=document.category,
        analysis="pending_lp66",
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

    tokens_used: int | None = None
    cost_estimate: float | None = None
    if result.input_tokens is not None and result.output_tokens is not None:
        tokens_used = result.input_tokens + result.output_tokens
        cost_estimate = estimate_cost(
            model=settings.anthropic_model_extraction,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )

    await create_extraction_version(
        db,
        document_id=document.id,
        extracted_data=result.data.model_dump(mode="json"),
        extraction_status=result.status,
        model_used=settings.anthropic_model_extraction,
        tokens_used=tokens_used,
        cost_estimate=cost_estimate,
        error_detail=result.reasoning if result.status == ExtractionStatus.FAILED else None,
    )

    if result.status == ExtractionStatus.FAILED or result.confidence < _CONFIDENCE_THRESHOLD:
        document.status = DocumentStatus.NEEDS_REVIEW
        document.processing_error = "extraction failed or low confidence"
        await db.commit()
        logger.info("document_needs_review", document_id=str(document.id), reason="extraction")
        return

    document.status = DocumentStatus.COMPLETED
    await _satisfy_needs_for_document(db, document)
    await db.commit()
    logger.info(
        "document_completed",
        document_id=str(document.id),
        extraction_status=result.status,
        tokens_used=tokens_used,
        cost_estimate=cost_estimate,
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


@celery_app.task(name="documents.process_document")  # type: ignore[untyped-decorator]
def process_document(document_id: str) -> None:
    """Celery task: process one uploaded document end-to-end (sync→async bridge)."""
    run_async(_run(document_id))


@celery_app.task(name="documents.reprocess_document")  # type: ignore[untyped-decorator]
def reprocess_document(document_id: str) -> None:
    """Celery task: re-extract a document after a manual type override (LP-44).

    A thin wrapper over the existing :func:`reprocess_document_extraction` core
    (LP-39c, registry-based, skips classification, new version, resilient) — the
    PATCH override endpoint enqueues this.
    """
    run_async(_run_reprocess(document_id))
