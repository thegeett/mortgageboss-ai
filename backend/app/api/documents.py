"""Document endpoints — upload/list (nested) and get/download/delete (flat) (LP-36).

The first real consumer of the LP-35 storage layer. Two routers:

  * **Nested** under a loan file — ``/loan-files/{file_identifier}/documents`` —
    for upload and list. Each route declares :data:`ScopedLoanFile`, so the
    parent file is company-scope-checked **first** (``404`` if not the caller's).
  * **Flat** — ``/documents/{document_id}`` — for get-one, download, and delete.
    A document has no ``company_id``, so every flat route resolves it via
    :func:`get_document_for_company` (join through the loan file) and ``404``s
    unless the file belongs to the caller's company. This is the cross-tenant
    gate: a Company A user can never get/download/delete a Company B document.

Uploaded bytes are validated (size + content-type + magic bytes), stored via the
storage backend, and recorded as ``PENDING`` documents (the pipeline, LP-42,
picks them up). The stored ``storage_path`` is internal — never in a response;
bytes are returned only through the auth'd ``/download`` route.
"""

from typing import Annotated
from urllib.parse import quote
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status

from app.api.dependencies import CurrentUser, ScopedLoanFile
from app.core.database import DbSession
from app.documents.catalog import get_category, get_tier
from app.models.activity_log import ActivityType
from app.models.document import (
    PIPELINE_IN_FLIGHT_STATUSES,
    Document,
    DocumentStatus,
    is_pipeline_in_flight,
)
from app.models.loan_file import LoanFile
from app.schemas.document import (
    BulkReprocessRequest,
    BulkReprocessResponse,
    DocumentDetailResponse,
    DocumentReprocessRequest,
    DocumentResponse,
    DocumentTypeOverrideRequest,
    StalenessResolveRequest,
)
from app.services.activity_log import log_activity
from app.services.document_versioning import supersede_document
from app.services.documents import (
    MAX_FILE_SIZE_BYTES,
    DocumentValidationError,
    build_document_detail,
    build_document_response,
    build_document_responses,
    create_document,
    get_document_for_company,
    get_version_group_documents,
    list_documents,
    resolve_staleness,
    soft_delete_document,
    validate_upload,
)
from app.services.verifications import mark_verification_stale
from app.storage import get_storage_backend
from app.tasks.document_processing import (
    process_document,
    reprocess_document,
)

log = structlog.get_logger(__name__)

# Read uploads in 1 MB chunks so an over-limit file is rejected without buffering
# far past the cap (see ``_read_capped``).
_CHUNK_SIZE = 1024 * 1024

nested_router = APIRouter(prefix="/loan-files/{file_identifier}/documents", tags=["documents"])
flat_router = APIRouter(prefix="/documents", tags=["documents"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

#: What the type-override endpoint writes to mean "a person chose this type" (LP-44). Named rather
#: than spelled 1.0 inline, because it is a PROXY and readers need to see that it is one — the model
#: can reach the same value through `coerce_confidence`'s clamp.
_HUMAN_CLASSIFIED_CONFIDENCE = 1.0


#: The bodies used when a request sends none. Module-level singletons rather than calls in the
#: argument defaults (ruff B008): they are only ever READ, so one shared instance each is safe.
_DEFAULT_REPROCESS_REQUEST = DocumentReprocessRequest()
_DEFAULT_BULK_REQUEST = BulkReprocessRequest()

#: Why a document was passed over by a bulk reprocess. Reported back per document, so a processor
#: can tell "I skipped this and here is why" from "the queue is slow".
_SKIP_SUPERSEDED = "superseded_version"
_SKIP_IN_FLIGHT = "already_processing"
_SKIP_HUMAN_TYPE = "type_set_by_a_person"
_SKIP_ALREADY_CLASSIFIED = "already_classified"
#: Already queued by an earlier press and not yet picked up. `all_documents` overrides it.
_SKIP_ALREADY_QUEUED = "already_queued"
#: The broker refused the task, so the document was put back the way it was found.
_SKIP_ENQUEUE_FAILED = "enqueue_failed"

#: Most documents a single bulk press may queue.
#:
#: A foot-gun guard, not a capacity limit. `all_documents` on a large file enqueues one task per
#: document, each with a 600s soft limit, onto a worker that runs them serially — one press can
#: occupy the document worker for hours and put every other file's uploads behind it. The largest
#: real file we have is 44 documents (LF-ZE9N), so this is comfortably above the motivating case
#: and well below a pathological one.
_MAX_BULK_REPROCESS = 100

#: What the classifier writes when it cannot name a document (`app/ai/classification.py`): a literal
#: type rather than a null, so it reaches the catalog lookup and takes the Tier 3 path. LP-636 defect
#: 5 is the shape that makes this worth re-reading — a CONFIDENT `unknown` completes cleanly, raises
#: no flag, and produces no typed data.
_UNKNOWN_DOCUMENT_TYPE = "unknown"


def _would_benefit(document: Document) -> bool:
    """Is this a document a re-classification could plausibly improve? (LP-637)

    The bounded default for bulk. A document is worth re-reading when nothing knows what it is
    (no type, or the literal ``unknown`` that LP-636 defect 5 produces), or when the pipeline
    already flagged it — NEEDS_REVIEW and FAILED are the two states that say "this did not go
    well". Everything else has a type the classifier was content with, and re-deriving it costs a
    model call to reach the same answer.

    Deliberately not "reprocess anything not COMPLETED", which would sweep in PENDING and every
    other transient state.

    THIS FUNCTION DOES NOT STOP A SECOND PRESS RE-QUEUEING THE FIRST'S WORK, and an earlier version
    of this docstring claimed it did. Nothing here looks at status except to include NEEDS_REVIEW
    and FAILED — an untyped or `unknown` document is STILL untyped while it sits at PENDING, so it
    stayed eligible, and that is the exact cohort the feature exists for. The bulk endpoint carries
    its own PENDING skip for that; see `_SKIP_ALREADY_QUEUED`.
    """
    return (
        document.document_type is None
        or document.document_type == _UNKNOWN_DOCUMENT_TYPE
        or document.status in (DocumentStatus.NEEDS_REVIEW, DocumentStatus.FAILED)
        # An in-flight status that reached this far is an ABANDONED one — the caller checks
        # `is_pipeline_in_flight` first, and that is time-aware. Without this line a document
        # stranded mid-pipeline WITH a type fell through to "the classifier was content with it"
        # and was reported to the processor as `already_classified`: the default bulk press still
        # could not recover it, and said so in words that described a different situation.
        or document.status in PIPELINE_IN_FLIGHT_STATUSES
    )


def _enqueue_processing(document_id: UUID) -> None:
    """Fire-and-forget enqueue of the LP-42 processing task for a stored document.

    The document is already stored + committed (``PENDING``), so an enqueue
    hiccup (broker down) must NOT fail the upload — the bytes and record are
    safe and the document can be reprocessed. We log and move on.
    """
    try:
        process_document.delay(str(document_id))
    except Exception:
        log.warning("document_enqueue_failed", document_id=str(document_id))


def _enqueue_full_reprocess(document_id: UUID) -> bool:
    """Enqueue the FULL pipeline — classify then extract (LP-637). ``True`` if it landed.

    Deliberately a separate helper from :func:`_enqueue_reprocess`, which enqueues the
    extraction-only task. The two differ by exactly the step this ticket exists to provide, and one
    helper taking a flag would make the call sites read the same.

    Never raises, for the reason the other one does not: a broker hiccup should leave a document
    that can be reprocessed again rather than a 500 on a request whose durable half succeeded.

    IT REPORTS THE OUTCOME rather than only logging it (LP-637 review), because both callers write
    the document to PENDING and clear its ``processing_error`` before this runs, and a swallowed
    failure made that permanent: a FAILED document became a PENDING one with a type and no error,
    which reads as healthy, is invisible in the UI, and — for the bulk path — falls outside
    `_would_benefit`, so the default bulk reprocess skips it as `already_classified` forever. The
    callers use this to put such a document back the way they found it.
    """
    try:
        from app.tasks.document_processing import process_document

        process_document.delay(str(document_id))
    except Exception:
        log.warning("full_reprocess_enqueue_failed", document_id=str(document_id))
        return False
    return True


def _enqueue_reprocess(document_id: UUID) -> None:
    """Fire-and-forget enqueue of the LP-39c re-extraction task after a type override.

    The type change is already committed, so an enqueue hiccup (broker down) must
    NOT lose the override — the document is updated and can be reprocessed.
    """
    try:
        reprocess_document.delay(str(document_id))
    except Exception:
        log.warning("reprocess_enqueue_failed", document_id=str(document_id))


async def _read_capped(upload: UploadFile, *, max_bytes: int) -> bytes:
    """Read an upload into memory, aborting once it exceeds ``max_bytes``.

    Reads in chunks and raises a size :class:`DocumentValidationError` as soon as
    the running total passes the cap, so a malicious 10 GB upload is never fully
    buffered — at most ``max_bytes`` + one chunk is held before rejection.
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(_CHUNK_SIZE):
        total += len(chunk)
        if total > max_bytes:
            raise DocumentValidationError(
                "File exceeds the 50MB limit",
                http_status=status.HTTP_413_CONTENT_TOO_LARGE,
            )
        chunks.append(chunk)
    return b"".join(chunks)


@nested_router.post("", response_model=list[DocumentResponse], status_code=status.HTTP_201_CREATED)
async def upload(
    loan_file: ScopedLoanFile,
    current_user: CurrentUser,
    db: DbSession,
    files: Annotated[list[UploadFile], File(description="One or more files to upload")],
) -> list[DocumentResponse]:
    """Upload one or more files to the loan file (validated, stored, ``PENDING``).

    All files are validated **before any are stored**, so an invalid file in the
    batch rejects the whole request and leaves nothing persisted. Each valid file
    is stored via the LP-35 backend (tenant-prefixed UUID path) and recorded as a
    ``PENDING`` document; a single ``DOCUMENT_UPLOADED`` activity is logged.
    """
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files provided")

    # Stage 1 — read + validate every file first (all-or-nothing).
    staged: list[tuple[UUID, UploadFile, bytes, str]] = []
    for upload_file in files:
        try:
            content = await _read_capped(upload_file, max_bytes=MAX_FILE_SIZE_BYTES)
            mime_type = validate_upload(
                content=content, declared_content_type=upload_file.content_type or ""
            )
        except DocumentValidationError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc
        staged.append((uuid4(), upload_file, content, mime_type))

    # Stage 2 — store bytes + create records (the request already passed validation).
    storage = get_storage_backend()
    created: list[Document] = []
    for document_id, upload_file, content, mime_type in staged:
        filename = upload_file.filename or "upload"
        storage_path = await storage.save(
            company_id=current_user.company_id,
            file_id=loan_file.id,
            document_id=document_id,
            filename=filename,
            content=content,
        )
        document = await create_document(
            db,
            loan_file=loan_file,
            document_id=document_id,
            filename=filename,
            mime_type=mime_type,
            size=len(content),
            storage_path=storage_path,
            uploaded_by_user_id=current_user.id,
        )
        created.append(document)

    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.DOCUMENT_UPLOADED,
        summary=(f"Uploaded {len(created)} document{'s' if len(created) != 1 else ''}"),
        actor_user_id=current_user.id,
        detail={"document_count": len(created)},
    )
    await db.commit()

    # Enqueue background processing per document AFTER commit (fire-and-forget) —
    # the upload returns immediately; processing advances each Document's status
    # (LP-42). An enqueue failure doesn't fail the upload (the doc is safe/PENDING).
    for document in created:
        _enqueue_processing(document.id)

    return [await build_document_response(db, document=d) for d in created]


@nested_router.get("", response_model=list[DocumentResponse])
async def list_(loan_file: ScopedLoanFile, db: DbSession) -> list[DocumentResponse]:
    """List the file's active documents, newest first (+ versioning/staleness/fitness)."""
    documents = await list_documents(db, loan_file_id=loan_file.id)
    return await build_document_responses(db, documents)


@nested_router.post("/reprocess", response_model=BulkReprocessResponse)
async def reprocess_documents(
    loan_file: ScopedLoanFile,
    current_user: CurrentUser,
    db: DbSession,
    body: BulkReprocessRequest = _DEFAULT_BULK_REQUEST,
) -> BulkReprocessResponse:
    """Reprocess a file's documents in one call — classification included (LP-637).

    THE PER-DOCUMENT ENDPOINT'S REFUSALS BECOME FILTERS HERE, and that difference is the design. A
    single reprocess is a processor pointing at one document, so telling them "no, and why" is the
    right answer. A bulk reprocess is a processor pointing at a file: failing all ten because one
    is mid-pipeline would make the button useless exactly when a file is busy, which is when it is
    most likely to be pressed. Each document is judged on its own and the skips are REPORTED, so
    doing less than asked is visible rather than silent.

    LF-ZE9N is why this exists rather than ten clicks: ten unidentifiable documents, and every
    future improvement to the classifier will leave its own cohort behind in the same way.

    The default set is bounded — see :func:`_would_benefit`. ``all_documents`` widens it to every
    current document on the file.
    """
    documents = await list_documents(db, loan_file_id=loan_file.id)
    skipped: dict[str, int] = {}
    queued: list[Document] = []

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for document in documents:
        if not document.is_current:
            skip(_SKIP_SUPERSEDED)
        elif is_pipeline_in_flight(document):
            skip(_SKIP_IN_FLIGHT)
        elif not body.all_documents and document.status is DocumentStatus.PENDING:
            # ALREADY QUEUED. This is the skip that stops a second press re-queueing the first
            # press's work, and `_would_benefit` never did: an untyped or `unknown` document is
            # still untyped while it sits at PENDING, so it stayed eligible — and that is exactly
            # the cohort this feature exists for. A processor who sees nothing change for a minute
            # (the worker is serial, the soft limit is 600s) and presses again would otherwise send
            # every document a second time, and two overlapping pipelines end with one of them
            # absorbing an IntegrityError into FAILED while the other's extraction is the current
            # one.
            #
            # `all_documents` overrides it, which is what keeps a genuinely stranded PENDING
            # document reachable in bulk. The per-document endpoint takes PENDING unconditionally,
            # and that asymmetry is deliberate: there a processor is naming one document, so
            # "queue this again" is exactly what they asked for.
            skip(_SKIP_ALREADY_QUEUED)
        elif document.classification_confidence == _HUMAN_CLASSIFIED_CONFIDENCE and not body.force:
            skip(_SKIP_HUMAN_TYPE)
        elif not body.all_documents and not _would_benefit(document):
            skip(_SKIP_ALREADY_CLASSIFIED)
        else:
            queued.append(document)

    if len(queued) > _MAX_BULK_REPROCESS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{len(queued)} documents selected, more than the {_MAX_BULK_REPROCESS} a single "
                "reprocess may queue. Narrow the request, or reprocess documents individually."
            ),
        )

    # Remembered before anything is written, so a refused enqueue can be undone.
    previous = {d.id: (d.status, d.processing_error) for d in queued}

    if queued:
        # ONE activity entry for the batch, not one per document. Ten entries saying the same thing
        # at the same second buries the file's actual history, which is what the feed is for.
        await log_activity(
            db,
            loan_file_id=loan_file.id,
            activity_type=ActivityType.DOCUMENT_REPROCESSED,
            summary=(
                f"{len(queued)} document{'s' if len(queued) != 1 else ''} sent for reprocessing"
            ),
            actor_user_id=current_user.id,
            detail={
                "document_ids": [str(d.id) for d in queued],
                "forced": body.force,
                "all_documents": body.all_documents,
            },
        )
        # Once for the file, for the same reason the per-document endpoint does it per document.
        await mark_verification_stale(db, loan_file_id=loan_file.id)
        # Without the rollback below, a broker outage turned a FAILED document into a PENDING one
        # with a type and no error — which reads as healthy, shows nothing wrong in the UI, and
        # falls outside `_would_benefit`, so the DEFAULT bulk path then skips it as
        # `already_classified` for good. At batch scale that is a whole file's diagnostics, gone
        # silently.
        for document in queued:
            document.status = DocumentStatus.PENDING
            document.processing_error = None
    await db.commit()

    # After the commit, so a broker failure cannot leave the database claiming work that was never
    # reported. Anything the broker refuses is put back the way it was found, in a second commit,
    # and reported as a skip rather than counted as queued.
    enqueued: list[Document] = []
    for document in queued:
        if _enqueue_full_reprocess(document.id):
            enqueued.append(document)
        else:
            document.status, document.processing_error = previous[document.id]
            skip(_SKIP_ENQUEUE_FAILED)
    if len(enqueued) != len(queued):
        await db.commit()

    return BulkReprocessResponse(
        queued=len(enqueued),
        queued_document_ids=[d.id for d in enqueued],
        skipped=skipped,
    )


@flat_router.get("/{document_id}", response_model=DocumentDetailResponse)
async def retrieve(
    document_id: UUID, current_user: CurrentUser, db: DbSession
) -> DocumentDetailResponse:
    """Get one document + its current extraction (+ versioning/staleness); ``404`` if not the caller's."""
    document = await get_document_for_company(
        db, document_id=document_id, company_id=current_user.company_id
    )
    if document is None:
        raise _NOT_FOUND
    return await build_document_detail(db, document=document)


@flat_router.get("/{document_id}/versions", response_model=list[DocumentResponse])
async def versions(
    document_id: UUID, current_user: CurrentUser, db: DbSession
) -> list[DocumentResponse]:
    """The document's version group, oldest→newest (LP-71). A standalone doc → just itself."""
    document = await get_document_for_company(
        db, document_id=document_id, company_id=current_user.company_id
    )
    if document is None:
        raise _NOT_FOUND
    group = await get_version_group_documents(db, document=document)
    return await build_document_responses(db, group)


@flat_router.patch("/{document_id}", response_model=DocumentResponse)
async def override_document_type(
    document_id: UUID,
    body: DocumentTypeOverrideRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> DocumentResponse:
    """Manually override a document's type, then re-extract for the corrected type (LP-44).

    The human-correction half of the loop: LP-43 surfaces a misclassified /
    ``NEEDS_REVIEW`` document; this PATCH sets the authoritative type. It
    re-derives the category, marks the classification **human-overridden**
    (``classification_confidence = 1.0`` — so re-extraction isn't re-flagged
    NEEDS_REVIEW for low confidence), clears any stale ``processing_error``, audits
    the change, and **enqueues the existing LP-39c re-extraction** (which skips
    classification and uses this type via the EXTRACTORS registry; an unmapped type
    relabels classified-only). Tenant-scoped (``404`` for another company's
    document); re-extraction runs in the background and shows live in the UI.
    """
    document = await get_document_for_company(
        db, document_id=document_id, company_id=current_user.company_id
    )
    if document is None:
        raise _NOT_FOUND

    if is_pipeline_in_flight(document):
        # THE CLAIM IS ONLY EXCLUSIVE AGAINST ITSELF unless every path that writes an extraction
        # respects it (LP-637 review). This endpoint enqueues `reprocess_document`, which now takes
        # the claim in its own task — so a type override during a live pipeline would simply be
        # dropped by that claim, silently, and the processor would see their correction do nothing.
        # Refusing here says so instead.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document is already being processed. Wait for it to finish, then retry.",
        )

    new_type = body.document_type.strip()
    document.document_type = new_type
    # Catalog-driven (LP-58): re-derive both tier and category from the new type.
    document.tier = get_tier(new_type)
    document.category = get_category(new_type)
    document.classification_confidence = 1.0  # human-set type is authoritative
    document.processing_error = None

    await log_activity(
        db,
        loan_file_id=document.loan_file_id,
        activity_type=ActivityType.DOCUMENT_TYPE_OVERRIDDEN,
        summary=f"Type changed to {new_type}",
        actor_user_id=current_user.id,
        detail={"document_id": str(document.id), "document_type": new_type},
    )
    # The document's type changed → the cross-source verification is out of date.
    await mark_verification_stale(db, loan_file_id=document.loan_file_id)
    await db.commit()

    # Re-extract in the background (fire-and-forget; the override is already saved).
    _enqueue_reprocess(document.id)

    return await build_document_response(db, document=document)


@flat_router.post("/{document_id}/reprocess", response_model=DocumentResponse)
async def reprocess_document_from_scratch(
    document_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    # Defaulted so a body-less POST works. FastAPI makes a Pydantic body parameter REQUIRED
    # regardless of every field on it having a default, so without this the natural call — a
    # button that posts nothing — is a 422.
    body: DocumentReprocessRequest = _DEFAULT_REPROCESS_REQUEST,
) -> DocumentResponse:
    """Read a stored document again from scratch — CLASSIFICATION INCLUDED (LP-637).

    THE GAP THIS FILLS. Classification runs once, at upload, and nothing re-runs it. So every
    improvement to the classifier is invisible to every document already in the system, and the only
    route to a corrected type is a processor typing it by hand — which cannot help a document that
    classified as ``unknown``, because nobody knows what it is.

    LF-ZE9N is the worked example: ten documents classified nineteen hours before the LP-636 fixes
    that would have classified them correctly, still untyped, generating 220 of that file's 256
    `couldnt_check` findings. The fixes were deployed and could not reach them.

    NOT :func:`app.tasks.document_processing.reprocess_document`, which the type-override endpoint
    uses and which SKIPS classification by design — correctly, because there a human has already
    supplied the type. This enqueues the full ``process_document`` pipeline against the stored file.

    A HUMAN-CLASSIFIED DOCUMENT IS REFUSED unless ``force``; see
    :class:`~app.schemas.document.DocumentReprocessRequest` for why that signal is imperfect and why
    refusing is the cheaper error. Tenant-scoped (404 for another company's document). Refused
    (409) for a superseded version and for a document the pipeline is already running on. The
    document returns to PENDING and moves through its statuses as the background pipeline runs.
    """
    document = await get_document_for_company(
        db, document_id=document_id, company_id=current_user.company_id
    )
    if document is None:
        raise _NOT_FOUND

    if not document.is_current:
        # A superseded version is kept for AUDIT, and it cannot affect an answer: the verification
        # snapshot selects `Document.is_current.is_(True)`, so no finding on this file reads it.
        # Reprocessing one would re-classify a historical record, spend a full classify+extract on
        # work that provably changes nothing, and mark the whole file's verification stale — a
        # "needs re-verification" for a document that is not part of the file's current state. The
        # replace endpoint below refuses the same thing for the same reason.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only the current version of a document can be reprocessed.",
        )

    if is_pipeline_in_flight(document):
        # The pipeline is already running on this document — a status in the in-flight set AND a
        # row written recently enough that a worker can still be behind it. The time half is not
        # decoration: on status alone, a worker killed mid-run left the document refused here
        # forever, with no route back through the product at all.
        #
        # Two overlapping `_process_document`
        # runs both write a current extraction, and `UNIQUE (document_id) WHERE is_current` lets
        # only one of them: the loser absorbs the IntegrityError into FAILED, so the document ends
        # up reading FAILED while carrying the winner's perfectly good extraction.
        #
        # WHAT THIS DOES NOT DO IS STOP A DOUBLE-CLICK, and an earlier draft of this comment said
        # it did. No status guard can: the status only moves when a WORKER starts, so two clicks
        # two seconds apart both read whatever the row said before either was picked up, and both
        # enqueue. Closing that needs task-level deduplication or a lock — neither is this
        # endpoint's to add, and the frontend action in feature 3 should disable on submit.
        #
        # What it does stop is a reprocess landing on a pipeline that is visibly running, which is
        # the longer and likelier window. The residual is a confusing status, recoverable by
        # reprocessing again — not a corrupt one.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document is already being processed. Wait for it to finish, then retry.",
        )

    if document.classification_confidence == _HUMAN_CLASSIFIED_CONFIDENCE and not body.force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This document's type looks as though a person set it. Reprocessing would "
                "replace it with the classifier's answer — re-send with force to do that anyway."
            ),
        )

    await log_activity(
        db,
        loan_file_id=document.loan_file_id,
        activity_type=ActivityType.DOCUMENT_REPROCESSED,
        summary="Document sent for reprocessing",
        actor_user_id=current_user.id,
        detail={"document_id": str(document.id), "forced": body.force},
    )
    # The type may change, so findings computed from the old one are out of date. The override
    # endpoint marks the run stale for exactly this reason; a re-classification that left a green
    # verification standing would be a false green.
    await mark_verification_stale(db, loan_file_id=document.loan_file_id)
    # Back to PENDING, so the response says what is actually true. Returning the document's OLD
    # status meant a processor reprocessing a COMPLETED document got `completed` back and saw
    # nothing change until a worker happened to pick the task up.
    #
    # It is NOT free, and an earlier draft claimed it was. `_enqueue_full_reprocess` swallows every
    # exception, so with the broker down a COMPLETED document is left at PENDING with no task
    # behind it, having lost a terminal status it had legitimately earned. That is recoverable the
    # same way any other stranded PENDING is — by reprocessing again — and the alternative is
    # answering `completed` to a request that changed the document's future.
    previous_state = (document.status, document.processing_error)
    document.status = DocumentStatus.PENDING
    # And clear the previous run's error, as the override endpoint does. `_process_document` only
    # ever WRITES this column — no path through it clears one — so a document that failed, was
    # reprocessed and then succeeded reached COMPLETED still carrying "extraction incomplete
    # (connection) — re-runnable" from the run that no longer exists. That is the common case here,
    # not an edge: the documents this endpoint was built for are the ones sitting in NEEDS_REVIEW
    # with an error on them. `readonly.documents` selects the column unscrubbed, so the stale text
    # is what someone querying staging reads. (The comment at document_processing.py:460 also calls
    # it UI-shown; no response schema exposes it today, so that half looks stale.)
    document.processing_error = None
    await db.commit()

    if not _enqueue_full_reprocess(document.id):
        # Put it back. The same defect the bulk path had (LP-637 review): with the broker down,
        # clearing the status and the error before a fire-and-forget enqueue made a FAILED document
        # look like a healthy PENDING one, and threw away the reason it failed. Nothing durable
        # changed for the document now — the activity entry and the stale marker stand, which is
        # the conservative direction — so the response below truthfully shows it unchanged.
        document.status, document.processing_error = previous_state
        await db.commit()

    return await build_document_response(db, document=document)


@flat_router.post(
    "/{document_id}/replace",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def replace(
    document_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File(description="The new version of the document")],
) -> DocumentResponse:
    """Explicitly replace a document with a new upload (Model C, LP-71).

    A **deliberate** supersession (NOT triggered by a same-type upload — multiples are
    normal): the target (which must be the current version) becomes HISTORICAL, the new
    upload becomes CURRENT in the same version group, BOTH are kept for audit, and the
    need the old satisfied re-evaluates against the new current version (via the new
    document's pipeline, LP-68 serialized). Tenant-scoped (``404``); audited.
    """
    old = await get_document_for_company(
        db, document_id=document_id, company_id=current_user.company_id
    )
    if old is None:
        raise _NOT_FOUND
    if not old.is_current:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only the current version of a document can be replaced.",
        )

    try:
        content = await _read_capped(file, max_bytes=MAX_FILE_SIZE_BYTES)
        mime_type = validate_upload(content=content, declared_content_type=file.content_type or "")
    except DocumentValidationError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc

    loan_file = await db.get(LoanFile, old.loan_file_id)
    if loan_file is None:  # pragma: no cover - the scoped doc guarantees its file exists
        raise _NOT_FOUND

    new_id = uuid4()
    filename = file.filename or "upload"
    storage_path = await get_storage_backend().save(
        company_id=current_user.company_id,
        file_id=old.loan_file_id,
        document_id=new_id,
        filename=filename,
        content=content,
    )
    new_document = await create_document(
        db,
        loan_file=loan_file,
        document_id=new_id,
        filename=filename,
        mime_type=mime_type,
        size=len(content),
        storage_path=storage_path,
        uploaded_by_user_id=current_user.id,
    )
    await supersede_document(db, old_document=old, new_document=new_document)

    await log_activity(
        db,
        loan_file_id=old.loan_file_id,
        activity_type=ActivityType.DOCUMENT_REPLACED,
        summary=f"Replaced {old.original_filename}",
        actor_user_id=current_user.id,
        detail={"old_document_id": str(old.id), "new_document_id": str(new_document.id)},
    )
    await db.commit()

    # Process the new version (fire-and-forget); on completion it re-satisfies the need.
    _enqueue_processing(new_document.id)
    return await build_document_response(db, document=new_document)


@flat_router.post("/{document_id}/resolve-staleness", response_model=DocumentResponse)
async def resolve_staleness_endpoint(
    document_id: UUID,
    body: StalenessResolveRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> DocumentResponse:
    """Resolve a flagged-stale document (LP-71): ``waive`` or ``accept`` (replace is its
    own flow). Clears the staleness flag; the processor decides. Tenant-scoped; audited."""
    document = await get_document_for_company(
        db, document_id=document_id, company_id=current_user.company_id
    )
    if document is None:
        raise _NOT_FOUND
    action = "waive" if body.action == "waive" else "accept"
    await resolve_staleness(db, document=document, action=action)
    await log_activity(
        db,
        loan_file_id=document.loan_file_id,
        activity_type=ActivityType.DOCUMENT_STALENESS_RESOLVED,
        summary=f"Staleness {action}d for {document.original_filename}",
        actor_user_id=current_user.id,
        detail={"document_id": str(document.id), "action": action},
    )
    await db.commit()
    return await build_document_response(db, document=document)


@flat_router.get("/{document_id}/download")
async def download(document_id: UUID, current_user: CurrentUser, db: DbSession) -> Response:
    """Stream the original bytes (auth'd). The only way to fetch a document's bytes.

    Scoped via :func:`get_document_for_company` (``404`` for another company's
    document). Returns the bytes with the stored content type and a
    ``Content-Disposition: attachment`` carrying the original filename.
    """
    document = await get_document_for_company(
        db, document_id=document_id, company_id=current_user.company_id
    )
    if document is None:
        raise _NOT_FOUND
    storage = get_storage_backend()
    content = await storage.read(document.storage_path)
    return Response(
        content=content,
        media_type=document.mime_type,
        headers={"Content-Disposition": _attachment_header(document.original_filename)},
    )


@flat_router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(document_id: UUID, current_user: CurrentUser, db: DbSession) -> None:
    """Soft-delete a document (preserves the stored bytes); ``404`` if not the caller's."""
    document = await get_document_for_company(
        db, document_id=document_id, company_id=current_user.company_id
    )
    if document is None:
        raise _NOT_FOUND
    await soft_delete_document(db, document=document)
    await db.commit()


def _attachment_header(filename: str) -> str:
    """Build a safe ``Content-Disposition`` value for ``filename``.

    Provides an ASCII-sanitized ``filename=`` plus an RFC 5987 ``filename*`` with
    the percent-encoded UTF-8 name, and strips quotes/control characters so the
    (user-controlled) filename cannot break out of the header.
    """
    ascii_name = filename.encode("ascii", "ignore").decode("ascii")
    ascii_name = ascii_name.replace('"', "").replace("\\", "").replace("\r", "").replace("\n", "")
    ascii_name = ascii_name or "download"
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"
