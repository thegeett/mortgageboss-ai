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
from app.models.activity_log import ActivityType
from app.models.document import Document
from app.schemas.document import (
    DocumentDetailResponse,
    DocumentResponse,
    ExtractionPublic,
)
from app.services.activity_log import log_activity
from app.services.documents import (
    MAX_FILE_SIZE_BYTES,
    DocumentValidationError,
    create_document,
    get_current_extraction,
    get_document_for_company,
    list_documents,
    soft_delete_document,
    validate_upload,
)
from app.storage import get_storage_backend
from app.tasks.document_processing import process_document

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

    return [DocumentResponse.model_validate(d) for d in created]


@nested_router.get("", response_model=list[DocumentResponse])
async def list_(loan_file: ScopedLoanFile, db: DbSession) -> list[DocumentResponse]:
    """List the file's active documents, newest first. (File gate via dependency.)"""
    documents = await list_documents(db, loan_file_id=loan_file.id)
    return [DocumentResponse.model_validate(d) for d in documents]


@flat_router.get("/{document_id}", response_model=DocumentDetailResponse)
async def retrieve(
    document_id: UUID, current_user: CurrentUser, db: DbSession
) -> DocumentDetailResponse:
    """Get one document + its current extraction; ``404`` if not the caller's."""
    document = await get_document_for_company(
        db, document_id=document_id, company_id=current_user.company_id
    )
    if document is None:
        raise _NOT_FOUND
    extraction = await get_current_extraction(db, document=document)
    return DocumentDetailResponse(
        **DocumentResponse.model_validate(document).model_dump(),
        current_extraction=(
            ExtractionPublic.model_validate(extraction) if extraction is not None else None
        ),
    )


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
