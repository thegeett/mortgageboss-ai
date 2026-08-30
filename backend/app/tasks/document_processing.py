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
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.classification import classify_document
from app.ai.client import INFRA_RATE_LIMITED
from app.ai.cost import estimate_cost
from app.ai.extraction import EXTRACTORS, Extractor
from app.ai.extraction.consistency import run_consistency_checks
from app.ai.extraction.parsing import document_confidence_provenance, failure_detail
from app.ai.generic_analyzer import analyze_document
from app.core.config import resolve_model, settings
from app.documents.catalog import get_category, get_tier
from app.models.activity_log import ActivityType
from app.models.document import Document, DocumentStatus, Tier
from app.models.document_finding import DocumentFindingType
from app.models.extraction import ConfidenceSource, ExtractionStatus
from app.models.helpers import only_active
from app.services.activity_log import log_activity
from app.services.document_borrower_links import assign_document_borrower_links
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
    """The core pipeline for one document. Always reaches a terminal status.

    Raises ONLY ``SoftTimeLimitExceeded`` (LP-625) — the worker's out-of-time signal, which the task
    wrapper classifies as terminal and never retries; its ``on_exhausted`` still marks the document
    FAILED, so the terminal-status guarantee holds. Every other exception is absorbed into FAILED here.

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
        # LP-636: keep the model's OWN name for the document. LP-463 emits it before the
        # constrained pick and calls it "a more reliable signal than the constrained pick";
        # until now it was used for the type_matches_document self-check and discarded, so a
        # confident `unknown` the model had already named correctly left no trace. Stored, not
        # acted on: routing is unchanged by this line.
        #
        # NOT logged and NOT put in the activity detail. It is model prose over the document and
        # can carry a borrower name, which the C7 scrub cannot catch (it matches identifier
        # shapes, and a name is not digit-shaped) — activity detail is readable through the
        # readonly query path, so a name there would reach a terminal and a transcript.
        document.document_name = classification.document_name
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
        rerunnable_infra = await _route_by_tier(db, document, content)

        # A re-runnable infrastructure outcome (a THROTTLED Tier-1 extraction) must NOT
        # advance needs (LP-464 review): the classification is valid and the document
        # will be re-run, but a needs update would drive the matching OPEN need
        # RECEIVED→REJECTED — and REJECTED is not re-matched, so the successful re-run
        # could never advance it. Skip it here; the re-run enqueues it on success.
        if rerunnable_infra:
            return

        # --- Update the needs list (LP-68) — SERIALIZED per loan file -------- #
        # The document is now terminal + committed; advance any matching need in a
        # separate per-file-serialized task (concurrent arrivals never race).
        _enqueue_needs_update(document.loan_file_id, document.id)
    except SoftTimeLimitExceeded:
        # LP-625 (corrected) — OUT OF TIME IS NOT A PROCESSING ERROR, so it must not be handled as one
        # here. The handler below marks the document FAILED and returns normally, which means nothing
        # propagates out of `_run` — and `terminal_on=(SoftTimeLimitExceeded,)` on the task therefore
        # never saw the exception it was added to catch.
        #
        # Deliberately BEFORE `_mark_failed`: the task wrapper's `on_exhausted` marks the document
        # failed on its own, so re-raising loses nothing and gains the terminal (never-retried)
        # classification. Retrying a timeout re-runs identical work against the same wall.
        raise
    except Exception as exc:
        # UNEXPECTED (storage/DB/etc.) — never crash the worker or the batch.
        logger.warning(
            "process_document_failed",
            document_id=document_id,
            error_type=type(exc).__name__,
        )  # metadata only — no PII
        await _mark_failed(db, document, document_id)


async def _route_by_tier(db: AsyncSession, document: Document, content: bytes) -> bool:
    """Dispatch a classified document to its tier's handling path (LP-58).

    The tier was set from the catalog during classification. Exactly one branch
    runs and every branch reaches a terminal status:

      * **Tier 1 with a registered extractor** → the EXTRACTORS registry (deep
        typed extraction).
      * **Everything else** — a Tier-2 type, a Tier-1 type whose extractor isn't
        wired yet (LP-441), or a Tier-3 uncataloged/``unknown`` type — → scoped
        FREE EXTRACTION (:func:`_tier3_analyze`, LP-463). LP-471 routed the
        no-typed-extractor cases here (they used to get the LP-65 lightweight
        summary), so a correctly-classified document is never left with only a
        thin summary or nothing — its facts land in the untyped snapshot section.

    Reached only for a document whose label is TRUSTED (self-consistent + not
    low-confidence) — the LP-463 review gate routes a flagged/declined document
    straight to :func:`_tier3_analyze` before this point. A confident ``unknown``
    still lands in the Tier 3 branch here and COMPLETES.

    Returns ``True`` only when a Tier-1 extraction was THROTTLED (re-runnable infra whose need must not be
    advanced — :func:`_extract_branch`); ``False`` for every other path.
    """
    if document.tier == Tier.TIER_1:
        extractor = EXTRACTORS.get(document.document_type or "")
        if extractor is not None:
            return await _extract_branch(db, document, content, extractor)
    # No typed extractor for this document — a Tier-2 type (no extractor by design), a Tier-1 type
    # promoted before its extractor is wired (LP-441), or an uncataloged/``unknown`` Tier-3 type. ALL of
    # them now get Tier-3 scoped FREE EXTRACTION (LP-471), so a correctly-classified document is never left
    # with only a thin summary (the old LP-65 Tier-2 path) or nothing. The output lands in the marked-UNTYPED
    # snapshot section — read by a processor + AI cross-source reasoning, NEVER a deterministic rule (LP-463).
    await _tier3_analyze(db, document, content)
    return False  # only a throttled Tier-1 extraction (above) defers the needs update


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
        # Preserve the human-reference gist in ``document.summary`` too (the DocumentResponse field the UI
        # shows) — LP-471 routed the old Tier-2 summarize path here, so this keeps that quick-view gist for
        # every long-tail document (additive; the untyped extraction / findings / status are unchanged).
        document.summary = analysis.summary
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
) -> bool:
    """Run the registered extractor, persist a versioned extraction (+ cost), set terminal status.

    Type-agnostic (LP-39c): any extractor result is stored uniformly via
    ``create_extraction_version`` (its ``data.model_dump`` JSON), and the
    typed-core/transactions/catch-all shape just rides in that JSON.

    Returns ``True`` when the extraction was a re-runnable infrastructure outcome (a THROTTLE) whose need
    must NOT be advanced — the caller skips the needs update so a transient blip cannot drive the matching
    OPEN need to REJECTED (unrecoverable on re-run). ``False`` for a completed or content-failed extraction.
    """
    document.status = DocumentStatus.EXTRACTING
    await db.commit()

    # The FULL, uncapped document — deliberately, unlike classification (15 pages, LP-462) and Tier-3 free
    # extraction (50 pages, LP-463). A >100-page file therefore hits the provider's document-block limit here
    # (INFRA_OVERSIZED → a graceful FAILED that LP-471 falls back to Tier-3). Do NOT add a naive page cap: a
    # 069-style multi-document PACKAGE keeps its 1003 liabilities/REO deep in the file, so a cap trades an
    # honest crash for SILENT wrong data. The real fix is the splitter (its own ticket) — LP-473 ADR.
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
        return True  # re-runnable infra — the caller must NOT advance needs (see docstring)

    # The model that ACTUALLY ran (B1): under AI_PROVIDER=bedrock this is the
    # inference-profile id, not the tier value. Recording the tier value instead would
    # both mislabel `model_used` and price the call against the wrong key.
    invoked_model = resolve_model(settings.anthropic_model_extraction)

    tokens_used: int | None = None
    cost_estimate: float | None = None
    if result.input_tokens is not None and result.output_tokens is not None:
        # LP-628 review — THE CACHED HALVES COUNT. `input_tokens` is the UNCACHED REMAINDER once a call
        # uses prompt caching, so on the chunked path it excludes the document itself: chunk 1 bills
        # its bytes as a cache write and every later chunk as a read. Counting only the remainder
        # stored a cost roughly an order of magnitude below what the run actually cost, for exactly
        # the documents chunking exists to handle.
        #
        # `getattr` because caching is used by ONE extractor today, and widening the shared
        # `ExtractionResult` Protocol would force 118 others to declare a field they can never set.
        # See the note on `BankStatementExtractionResult`.
        cache_read = getattr(result, "cache_read_tokens", 0)
        cache_write = getattr(result, "cache_write_tokens", 0)
        tokens_used = result.input_tokens + result.output_tokens + cache_read + cache_write
        cost_estimate = estimate_cost(
            model=invoked_model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
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
        error_detail=failure_detail(result.status, result.reasoning),
        confidence=reported_confidence,
        confidence_source=confidence_source,
    )

    # LP-567 — attribute the document to its borrower(s) HERE, while the extraction that asserts
    # the name is the current one. The snapshot's ``belongs_to`` reads ``document_borrower_links``,
    # and until this call the producer had no caller outside a dev script: staging ran with 0 of 16
    # documents attributed, so every per-borrower rule saw a file whose documents belonged to
    # nobody. Placed before the branches below so a type override re-linking through
    # ``reprocess_document_extraction`` gets it for free.
    #
    # LP-569 — SKIPPED ON A FAILED EXTRACTION, and the savepoint is not what protects this. The
    # linker opens with an unconditional DELETE and only then looks for names, so a call that
    # SUCCEEDS while finding nothing commits the wipe — only an exception rolls it back. A FAILED
    # extraction is exactly that path: all-null data, `asserted_names_for` returns [], and a pay
    # stub correctly linked to a borrower loses that link on a retry or a type override.
    #
    # A FAILED extraction is an ABSENCE OF DATA, not a determination that the document names nobody
    # (§8). The service's "a re-match is authoritative" is right for a genuine re-match — a document
    # retyped to something with no name field SHOULD lose its links — so the guard belongs here, at
    # the call site that knows nothing was read, not in the service.
    if result.status is ExtractionStatus.FAILED:
        logger.info(
            "document_borrower_link_skipped",
            document_id=str(document.id),
            reason="extraction_failed",
        )
    else:
        # SAVEPOINT, as the snapshot builder does: matching is deterministic and additive, and a DB
        # error inside it must never cost the document the extraction that just succeeded.
        try:
            async with db.begin_nested():
                links = await assign_document_borrower_links(db, document)
        except SoftTimeLimitExceeded:
            # LP-625 (corrected) — the last swallow point on this path. Deterministic DB work, so a
            # soft limit landing here is unlikely; included anyway because ONE remaining broad handler
            # is all it takes for the task's terminal classification to go quiet again.
            raise
        except Exception as exc:
            logger.warning(
                "document_borrower_link_failed",
                document_id=str(document.id),
                error_type=type(exc).__name__,
            )
        else:
            # Zero links is a legitimate outcome, not a failure: the type asserts no name
            # (closing_disclosure, form_1098), or the asserted name matches nobody above
            # threshold. Logged with the count so the two are distinguishable in CloudWatch.
            logger.info(
                "document_borrower_linked",
                document_id=str(document.id),
                document_type=document.document_type,
                link_count=len(links),
            )

    if result.status == ExtractionStatus.FAILED:
        # Genuinely EMPTY (derive_status: nothing read → FAILED; PARTIAL keeps its fields and never lands
        # here). The FAILED extraction version above already records WHY (error_detail = result.reasoning —
        # oversized / parse / "AI call failed"; rate_limited was carved out by the throttle gate). LP-471:
        # fall back to Tier-3 free extraction so the document is not left with zero data. ``review_reason``
        # keeps it NEEDS_REVIEW (the typed extraction still errored — a human should see it) and the FAILED
        # version is NOT hidden. If the fallback ALSO fails (069's oversized payload defeats it too),
        # _tier3_analyze is graceful (analysis None) and the document ends NEEDS_REVIEW with no untyped data —
        # that one needs the LP-464 page cap, and the fallback cannot save it.
        # ``processing_error`` is UI-shown and MUST stay PII-safe (the module invariant above), and the log
        # carries no extracted content — so DON'T interpolate ``result.reasoning`` here: for an all-null-parse
        # FAILED it is the model's free-text reasoning and can quote document details. The raw reason is
        # already persisted in the FAILED extraction version's ``error_detail`` above, the access-controlled
        # place for it (LP-471 review).
        document.processing_error = "extraction failed — fell back to Tier 3 free extraction"
        await _tier3_analyze(db, document, content, review_reason="extraction_error")
        logger.info(
            "document_extraction_fell_back_to_tier3",
            document_id=str(document.id),
        )
        # A CONTENT failure (not a throttle) — the need is correctly advanced to REJECTED below.
        return False
    # LP-636 defect 3 — gate on the HONEST pair, not the coerced float.
    #
    # This used to read ``result.confidence < _CONFIDENCE_THRESHOLD``. ``coerce_confidence``
    # collapses a model that OMITTED confidence to 0.0, so "the model did not say" was read as
    # "the model said zero" and the document was flagged "extraction low confidence" — a reason
    # that was not true. LP-201 keeps the distinction two lines up (NULL / ``not_provided``,
    # "absence is a legitimate state") and this gate immediately re-conflated it. Measured on
    # staging: 15 of 115 successful extractions (13%) carried no confidence, every one flagged.
    #
    # ABSENCE IS NOT TREATED AS LOW CONFIDENCE, deliberately. An extraction that captured nothing
    # is already handled above — FAILED → Tier 3 fallback — so by this line the extraction HAS
    # typed fields and the only missing thing is the model's self-report. That is not evidence of
    # unsureness, and a 13% false-flag rate is how a review queue stops being read.
    #
    # A CONSEQUENCE TO BE HONEST ABOUT: a model that reports exactly 0.0 is indistinguishable from
    # one that reported nothing, because ``document_confidence_provenance`` maps 0.0 → (None,
    # not_provided). Such a document is no longer flagged, where before it was. That follows
    # LP-201's own position — a defaulted 0.0 carries no information and must not be dressed as a
    # self-report — but it is a behaviour change on that input, not an oversight.
    #
    # The population stays measurable: ``confidence_source`` is persisted on the extraction
    # version and is exposed by ``readonly.extractions``, so this decision can be revisited with
    # data rather than reopened by argument.
    if confidence_source is ConfidenceSource.NOT_PROVIDED:
        logger.info(
            "extraction_confidence_not_reported",
            document_id=str(document.id),
            document_type=document.document_type,
        )
    elif reported_confidence is not None and reported_confidence < _CONFIDENCE_THRESHOLD:
        # LOW confidence but NOT empty — the extraction captured typed fields (LP-471 A6: do NOT fall back;
        # mixing typed + untyped data for one document would let a reader conflate them). Keep the typed
        # fields; a human reviews. No Tier-3 fallback.
        document.status = DocumentStatus.NEEDS_REVIEW
        document.processing_error = "extraction low confidence"
        await db.commit()
        logger.info(
            "document_needs_review",
            document_id=str(document.id),
            reason="low_confidence",
            confidence=reported_confidence,
        )
        return False

    document.status = DocumentStatus.COMPLETED
    # The needs update (satisfaction-matching) is enqueued once, per-file-serialized,
    # at the end of _process_document (LP-68) — not inline here (which would race
    # under concurrent same-file arrivals). Record any findings the extraction
    # surfaced (LP-66) — e.g. a divorce decree's obligations → findings (LP-63 loop).
    findings_count = await record_findings_from_extraction(db, document, result.data)
    # LP-474 — deterministic self-consistency checks: two extracted values that must DIFFER came out
    # equal (e.g. state tax == federal tax withheld). FLAG a distinct CONSISTENCY finding — never
    # rewrite the value, never fail. The coverage status is left untouched, so an accuracy flag is
    # distinguishable from a coverage PARTIAL. No model call (deterministic).
    for violation in run_consistency_checks(document.document_type, result.data):
        await create_document_finding(
            db,
            document=document,
            finding_type=DocumentFindingType.CONSISTENCY,
            description=f"Possible extraction error — {violation.check.label}",
            details={"check": violation.check.label, "detail": violation.detail},
        )
    await db.commit()
    logger.info(
        "document_completed",
        document_id=str(document.id),
        extraction_status=result.status,
        tokens_used=tokens_used,
        cost_estimate=cost_estimate,
        findings_count=findings_count,
    )
    return False  # completed normally — advance needs as usual


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
    double-satisfied) and resilient (unexpected error → FAILED).

    Raises ONLY ``SoftTimeLimitExceeded`` (LP-625): the worker's out-of-time signal is not an
    extraction failure and must reach the task, which classifies it as terminal rather than retrying
    identical work against the same deadline. Every other exception is still absorbed into FAILED.

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
    except SoftTimeLimitExceeded:
        # LP-625 (corrected) — same reasoning as `_process_document`: the worker's out-of-time signal
        # is not an extraction failure. Swallowing it here made line 690's `terminal_on` unconditionally
        # dead, since this function documents "Never raises" and delivered on that too literally.
        # `on_exhausted` still marks the document failed, so the visible outcome is unchanged.
        raise
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


# The document pipeline's OWN time limits (LP-625). The global default is 120s
# (``celery_app.py``, "Generous for V1; tune once real task latencies are known") and a bank statement
# does not fit inside it — measured on LF-AWBB, staging, 2026-08-23:
#
#     classification                       ~8s
#     extraction @ max_tokens=16384        65s   -> `extraction_truncated`
#     retry      @ max_tokens=32768        longer again (roughly 2x the output)
#
# The truncation retry is what makes a long statement extractable at all, and it is exactly what pushes
# the task past 120s. The soft limit fired mid-retry, Celery restarted the task from classification,
# and it truncated again: a clean 2-minute sawtooth, 8 classifications and 7 kills across 4 documents,
# ending in FAILED once MAX_RETRIES ran out. Every re-attempt re-paid for the classification call too.
#
# Sized the way RULE_ENGINE_SOFT_LIMIT_SECONDS is: generously above the worst measured path (~220s),
# because the ceiling only has to be high enough that a legitimate document finishes — a task that
# genuinely hangs is caught by the hard limit, not by a tight soft one.
DOCUMENT_SOFT_LIMIT_SECONDS = 600  # 10 min — a truncate-and-retry statement finishes with headroom
DOCUMENT_HARD_LIMIT_SECONDS = 660  # the SIGKILL ceiling, above the soft limit's graceful mark


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="documents.process_document",
    max_retries=MAX_RETRIES,
    soft_time_limit=DOCUMENT_SOFT_LIMIT_SECONDS,
    time_limit=DOCUMENT_HARD_LIMIT_SECONDS,
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
        # LP-625 — A TIME LIMIT IS TERMINAL, NOT TRANSIENT, and this is the half of the bug that the
        # raised ceiling above does not fix. `retry_or_terminal`'s own docstring says a task time
        # limit belongs here, and `verification.run_rule_engine` has passed it since LP-377-C; the
        # document tasks never did. So a SoftTimeLimitExceeded fell into the generic transient branch
        # and Celery re-ran the task FROM THE TOP — re-classifying, re-extracting, truncating again,
        # and being killed again on a two-minute cycle until MAX_RETRIES ran out.
        #
        # Retrying a timeout cannot work: nothing about the document changed, so the same work takes
        # the same time and hits the same wall. It only multiplies the cost. And raising the ceiling
        # WITHOUT this would have made it worse — four attempts at 600s is forty minutes of a serial
        # worker instead of eight, with every other document on the file queued behind it.
        terminal_on=(SoftTimeLimitExceeded,),
    )


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="documents.reprocess_document",
    max_retries=MAX_RETRIES,
    # Re-extraction runs the same extractor, so it meets the same truncation retry and needs the same
    # ceiling. It skips classification, which only makes it cheaper, never longer.
    soft_time_limit=DOCUMENT_SOFT_LIMIT_SECONDS,
    time_limit=DOCUMENT_HARD_LIMIT_SECONDS,
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
        # Same reasoning as `process_document`: re-running the same extraction after a timeout takes
        # the same time and meets the same wall.
        terminal_on=(SoftTimeLimitExceeded,),
    )
