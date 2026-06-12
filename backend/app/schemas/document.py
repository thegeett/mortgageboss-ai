"""Document response schemas (LP-36).

Public views of an uploaded :class:`~app.models.document.Document`. The
``storage_path`` is **internal** and never appears in any response (bytes are
served only through the auth'd download endpoint, not a direct URL). Documents
carry no SSN/inbox_token, so there is nothing else to mask here.

:class:`DocumentDetailResponse` additionally carries the document's *current*
extraction (LP-16) — ``None`` until the processing pipeline (LP-42) runs.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import DocumentCategory, DocumentStatus, UploadSource
from app.models.extraction import ExtractionStatus


class DocumentTypeOverrideRequest(BaseModel):
    """A manual document-type correction (LP-44). The human-set type is authoritative."""

    document_type: str = Field(min_length=1, max_length=64)


class DocumentResponse(BaseModel):
    """An uploaded document's metadata (no ``storage_path``)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    loan_file_id: UUID
    original_filename: str
    mime_type: str
    file_size_bytes: int
    document_type: str | None
    category: DocumentCategory | None
    classification_confidence: float | None
    status: DocumentStatus
    upload_source: UploadSource
    uploaded_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime


class ExtractionPublic(BaseModel):
    """A read-only view of a document's current extraction (LP-16)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    extracted_data: dict[str, Any]
    extraction_status: ExtractionStatus
    model_used: str | None
    created_at: datetime


class DocumentDetailResponse(DocumentResponse):
    """A document plus its current extraction (``None`` until extraction runs)."""

    current_extraction: ExtractionPublic | None
