"""Document service — upload validation, CRUD, and flat-route scoping (LP-36).

Documents are **owned children** of a loan file with no ``company_id`` of their
own (ADR-052/053): they are company-scoped **transitively** through the file.
Two scoping shapes are served here:

  * **Nested** operations (create/list) take an already scope-checked
    ``loan_file`` / ``loan_file_id`` — the endpoint resolves the parent file with
    the caller's company first (the LP-29 file gate).
  * **Flat** operations (get/download/delete by document id) have no file in the
    path, so :func:`get_document_for_company` resolves the document's company by
    **joining through its loan file** and returns ``None`` unless that file
    belongs to the caller's company. A flat route must NEVER load a document by
    id alone — that is the cross-tenant leak this guards against.

Upload bytes are validated (size + type via content-type allowlist *and*
magic-byte signature) before they reach the storage layer (LP-35); the
extension is sanitized there too (defense in depth). Services ``flush``; the
endpoint commits. Soft-delete preserves the stored bytes (audit).
"""

from uuid import UUID

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.documents.naming import standard_name
from app.documents.staleness import evaluate_staleness, package_fitness, package_qualification
from app.models.base import utcnow
from app.models.document import Document, DocumentStatus, StalenessResolution, UploadSource
from app.models.extraction import Extraction
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.schemas.document import DocumentDetailResponse, DocumentResponse, ExtractionPublic
from app.services.document_versioning import version_count, version_counts_for_group_ids
from app.services.verifications import mark_verification_stale

# --------------------------------------------------------------------------- #
# Upload validation
# --------------------------------------------------------------------------- #

#: Hard cap on a single uploaded file (50 MB).
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024

#: Content types we accept. Mortgage documents are PDFs and scans (images).
ALLOWED_CONTENT_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png"})

#: Magic-byte signatures → the content type they prove. A file's real type is
#: detected from its leading bytes and must match the declared content type,
#: which resists content-type spoofing (declaring ``application/pdf`` for a PNG).
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)


class DocumentValidationError(Exception):
    """An uploaded file failed size/type validation.

    Carries the HTTP status the endpoint should map to: ``413`` for an
    over-limit file, ``415`` for an unsupported/mismatched type.
    """

    def __init__(self, message: str, *, http_status: int) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status


def _detect_content_type(content: bytes) -> str | None:
    """The content type proven by the leading magic bytes, or ``None``."""
    for signature, content_type in _MAGIC:
        if content.startswith(signature):
            return content_type
    return None


def validate_upload(*, content: bytes, declared_content_type: str) -> str:
    """Validate an uploaded file's size and type; return the verified content type.

    Enforces the 50 MB cap, the content-type allowlist, AND that the bytes'
    magic-byte signature matches the declared type (so a renamed/relabelled file
    can't slip past the allowlist). Raises :class:`DocumentValidationError` —
    ``413`` for size, ``415`` for type — on the first failure.
    """
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise DocumentValidationError(
            "File exceeds the 50MB limit",
            http_status=status.HTTP_413_CONTENT_TOO_LARGE,
        )
    declared = (declared_content_type or "").split(";", 1)[0].strip().lower()
    if declared not in ALLOWED_CONTENT_TYPES:
        raise DocumentValidationError(
            f"Unsupported file type: {declared_content_type!r}. Allowed: PDF, JPEG, PNG.",
            http_status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )
    detected = _detect_content_type(content)
    if detected is None or detected != declared:
        raise DocumentValidationError(
            "File content does not match its declared type (PDF, JPEG, or PNG).",
            http_status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )
    return declared


# --------------------------------------------------------------------------- #
# Service functions
# --------------------------------------------------------------------------- #


async def create_document(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    document_id: UUID,
    filename: str,
    mime_type: str,
    size: int,
    storage_path: str,
    uploaded_by_user_id: UUID | None,
    upload_source: UploadSource = UploadSource.USER_UPLOAD,
) -> Document:
    """Create a ``PENDING`` document record for ``loan_file``.

    ``document_id`` is the UUID already used to build the storage path (LP-35),
    so the record and the stored bytes share one id. The processing pipeline
    (LP-42) later advances the status. Uses ``flush``; the endpoint commits.
    """
    document = Document(
        id=document_id,
        loan_file_id=loan_file.id,
        original_filename=filename,
        mime_type=mime_type,
        file_size_bytes=size,
        storage_path=storage_path,
        status=DocumentStatus.PENDING,
        upload_source=upload_source,
        uploaded_by_user_id=uploaded_by_user_id,
    )
    db.add(document)
    await db.flush()
    # A document changed → the cross-source verification is out of date (LP-78).
    # Covers upload and replace (replace creates its new document through here).
    await mark_verification_stale(db, loan_file_id=loan_file.id)
    return document


async def list_documents(db: AsyncSession, *, loan_file_id: UUID) -> list[Document]:
    """The file's active documents, newest first. (File gate done by the caller.)

    Eager-loads ``extractions`` so the response builder can compute staleness from the
    current extraction's dates without an N+1 (LP-71).
    """
    stmt = select(Document).where(Document.loan_file_id == loan_file_id)
    stmt = only_active(stmt, Document)
    stmt = stmt.options(selectinload(Document.extractions))
    stmt = stmt.order_by(Document.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_version_group_documents(db: AsyncSession, *, document: Document) -> list[Document]:
    """All active documents in this document's version group, oldest→newest (LP-71).

    A standalone document (no group) returns just itself. Used by the version-history view.
    """
    if document.version_group_id is None:
        return [document]
    stmt = (
        select(Document)
        .where(Document.version_group_id == document.version_group_id)
        .options(selectinload(Document.extractions))
        .order_by(Document.version)
    )
    return list((await db.scalars(only_active(stmt, Document))).all())


async def resolve_staleness(db: AsyncSession, *, document: Document, action: str) -> Document:
    """Record the processor's staleness resolution (LP-71): ``waive`` or ``accept``.

    Clears the active staleness flag (the assessment respects the stored resolution).
    *Replace* is the versioning flow, not a value here. Uses ``flush``.
    """
    document.staleness_resolution = (
        StalenessResolution.WAIVED if action == "waive" else StalenessResolution.ACCEPTED
    )
    await db.flush()
    return document


async def get_document_for_company(
    db: AsyncSession, *, document_id: UUID, company_id: UUID
) -> Document | None:
    """Fetch an active document **only if** its loan file is the company's.

    The flat-route tenant gate: documents have no ``company_id``, so this joins
    ``Document -> LoanFile`` and filters on the file's company. Returns ``None``
    if the document doesn't exist, is soft-deleted, lives under a soft-deleted
    file, or belongs to another company — the endpoint turns that into ``404``,
    so a cross-tenant id is indistinguishable from a missing one.
    """
    stmt = (
        select(Document)
        .join(LoanFile, Document.loan_file_id == LoanFile.id)
        .where(Document.id == document_id, LoanFile.company_id == company_id)
    )
    stmt = only_active(stmt, Document)
    stmt = only_active(stmt, LoanFile)
    document: Document | None = await db.scalar(stmt)
    return document


async def soft_delete_document(db: AsyncSession, *, document: Document) -> None:
    """Soft-delete a document (set ``deleted_at``).

    Never a hard delete, and the **stored bytes are preserved** (audit) — only
    the record is hidden from active reads. Uses ``flush``; the endpoint commits.
    """
    document.deleted_at = utcnow()
    await db.flush()


async def get_current_extraction(db: AsyncSession, *, document: Document) -> Extraction | None:
    """The document's current extraction (LP-16), or ``None`` if none yet.

    Queried directly (rather than via the ``current_extraction`` property) so the
    flat detail route need not eager-load the whole ``extractions`` collection.
    """
    stmt = select(Extraction).where(
        Extraction.document_id == document.id,
        Extraction.is_current.is_(True),
    )
    stmt = only_active(stmt, Extraction)
    extraction: Extraction | None = await db.scalar(stmt)
    return extraction


# --------------------------------------------------------------------------- #
# Response building — enrich with versioning + staleness + naming + qualification
# (LP-71 + LP-72)
# --------------------------------------------------------------------------- #


def _enrich(
    document: Document, extraction: Extraction | None, *, version_count: int
) -> DocumentResponse:
    """Assemble the enriched response from a document + its current extraction.

    Computes the LP-71 staleness/fitness + the LP-72 standard name + package
    qualification. Pure (no DB) so list/single builders share one place.
    """
    staleness = evaluate_staleness(document, extraction)
    return DocumentResponse.from_model(
        document,
        version_count=version_count,
        staleness=staleness,
        package_fit=package_fitness(document, staleness),
        standard_name=standard_name(document, extraction),
        package_qualification=package_qualification(document, staleness),
    )


async def build_document_response(db: AsyncSession, *, document: Document) -> DocumentResponse:
    """Build one enriched response (fetches the current extraction + version count).

    For single-document endpoints (detail / override / replace / resolve / upload).
    """
    extraction = await get_current_extraction(db, document=document)
    count = await version_count(db, document=document)
    return _enrich(document, extraction, version_count=count)


async def build_document_detail(db: AsyncSession, *, document: Document) -> DocumentDetailResponse:
    """Build the enriched detail response (base + current extraction + generic analysis)."""
    extraction = await get_current_extraction(db, document=document)
    count = await version_count(db, document=document)
    base = _enrich(document, extraction, version_count=count)
    return DocumentDetailResponse(
        **base.model_dump(),
        current_extraction=(
            ExtractionPublic.model_validate(extraction) if extraction is not None else None
        ),
        generic_analysis=document.generic_analysis,
    )


async def build_document_responses(
    db: AsyncSession, documents: list[Document]
) -> list[DocumentResponse]:
    """Build the enriched list response — version counts batched, staleness/naming from
    the eager-loaded current extraction (no N+1). ``documents`` must have ``extractions``
    loaded (``list_documents`` does)."""
    group_ids = {d.version_group_id for d in documents if d.version_group_id is not None}
    counts = await version_counts_for_group_ids(db, group_ids=group_ids)
    responses: list[DocumentResponse] = []
    for d in documents:
        count = counts.get(d.version_group_id, 1) if d.version_group_id is not None else 1
        responses.append(_enrich(d, d.current_extraction, version_count=count))
    return responses
