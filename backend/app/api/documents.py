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
from app.models.document import Document
from app.models.loan_file import LoanFile
from app.schemas.document import (
    DocumentDetailResponse,
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
    await db.commit()

    # Re-extract in the background (fire-and-forget; the override is already saved).
    _enqueue_reprocess(document.id)

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
