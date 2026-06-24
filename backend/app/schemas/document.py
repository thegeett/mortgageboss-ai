"""Document response schemas (LP-36).

Public views of an uploaded :class:`~app.models.document.Document`. The
``storage_path`` is **internal** and never appears in any response (bytes are
served only through the auth'd download endpoint, not a direct URL). Documents
carry no SSN/inbox_token, so there is nothing else to mask here.

:class:`DocumentDetailResponse` additionally carries the document's *current*
extraction (LP-16) — ``None`` until the processing pipeline (LP-42) runs.
"""

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.documents.staleness import PackageFitness, PackageQualification, StalenessInfo
from app.models.document import Document, DocumentCategory, DocumentStatus, Tier, UploadSource
from app.models.extraction import ExtractionStatus


class DocumentTypeOverrideRequest(BaseModel):
    """A manual document-type correction (LP-44). The human-set type is authoritative."""

    document_type: str = Field(min_length=1, max_length=64)


class StalenessResolveRequest(BaseModel):
    """Resolve a flagged-stale document (LP-71): waive or accept (replace is its own flow)."""

    action: str = Field(pattern="^(waive|accept)$")
    reason: str | None = Field(default=None, max_length=2000)


def _empty_staleness() -> StalenessInfo:
    return StalenessInfo(is_stale=False, kind=None, reason=None, resolution=None, as_of_date=None)


class DocumentResponse(BaseModel):
    """An uploaded document's metadata (no ``storage_path``) + versioning/staleness."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    loan_file_id: UUID
    original_filename: str
    mime_type: str
    file_size_bytes: int
    document_type: str | None
    category: DocumentCategory | None
    # The level-of-investment tier the document was handled as (LP-58, catalog-driven).
    tier: Tier | None
    # A short human-readable gist for Tier 2 (recognized) documents (LP-65); null
    # for Tier 1 (which carries structured extraction instead) and on summary failure.
    summary: str | None
    classification_confidence: float | None
    status: DocumentStatus
    upload_source: UploadSource
    uploaded_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime

    # --- Versioning (Model C, LP-71) — current/historical + the version group ----
    version: int = 1
    is_current: bool = True
    version_group_id: UUID | None = None
    supersedes_document_id: UUID | None = None
    # How many versions are in this document's group (1 = standalone). Computed.
    version_count: int = 1
    # The email-ingest "possible duplicate" flag (surfaced gently). Default False.
    possible_duplicate: bool = False

    # --- Staleness + package fitness (LP-71) — computed, deterministic -----------
    staleness: StalenessInfo = Field(default_factory=_empty_staleness)
    package_fit: PackageFitness = Field(
        default_factory=lambda: PackageFitness(fit=True, reason=None)
    )

    # --- LP-72: a derived display name + the package-qualification flag ----------
    # A consistent ``{Type}_{Identifier}_{Date}`` name derived from the extracted data
    # (a display name — the stored file is untouched). Defaults to the raw filename.
    standard_name: str = ""
    # Package-ready = current + fresh + typed + extracted (consumes LP-71 + extraction).
    package_qualification: PackageQualification = Field(
        default_factory=lambda: PackageQualification(qualified=False, reason="not_extracted")
    )

    @classmethod
    def from_model(
        cls,
        document: Document,
        *,
        version_count: int,
        staleness: StalenessInfo,
        package_fit: PackageFitness,
        standard_name: str,
        package_qualification: PackageQualification,
    ) -> Self:
        """Build the response, attaching the computed versioning/staleness/naming/fitness."""
        return cls.model_validate(document).model_copy(
            update={
                "version_count": version_count,
                "staleness": staleness,
                "package_fit": package_fit,
                "standard_name": standard_name,
                "package_qualification": package_qualification,
            }
        )


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
    # The Tier 3 generic-analyzer output (LP-66), if any — for the LP-72 detail view.
    generic_analysis: dict[str, Any] | None = None
