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

from app.documents.period import DocumentPeriod
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
    # LP-105 — a consolidated, type-aware period line (range / tax year / single labeled date /
    # verbatim), derived from the already-extracted fields. ``None`` when the type has no period
    # concept or the date isn't extracted yet (the card/drawer then show no period line).
    period: DocumentPeriod | None = None
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
        period: DocumentPeriod | None = None,
    ) -> Self:
        """Build the response, attaching the computed versioning/staleness/naming/fitness."""
        return cls.model_validate(document).model_copy(
            update={
                "version_count": version_count,
                "staleness": staleness,
                "package_fit": package_fit,
                "standard_name": standard_name,
                "package_qualification": package_qualification,
                "period": period,
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


class FieldScrutiny(BaseModel):
    """How much scrutiny one extracted field deserves, independent of the model's confidence (LP-UI-032).

    Both signals are BACKEND knowledge — the critical list lives beside the schema
    specs and the distrust list beside the rule engine — so they are resolved here
    rather than reimplemented on a screen where they would drift from the specs.
    """

    #: Checked whatever the confidence says: money, a rate, or an identity.
    critical: bool = False
    #: Why this (document type, field) has a confirmed wrong value in the corpus, or
    #: ``None``. A REASON rather than a flag, because a screen that says "distrusted"
    #: without saying why is asking the processor to distrust it on faith.
    distrusted_reason: str | None = None
    #: An identifier — an SSN or ITIN. A screen must not render it in the clear.
    #: Answered here because the identity list already lives beside the schema specs;
    #: the frontend keeps its own masking set as a floor rather than relying on this.
    sensitive: bool = False


class DocumentDetailResponse(DocumentResponse):
    """A document plus its current extraction (``None`` until extraction runs)."""

    current_extraction: ExtractionPublic | None
    #: ``{field: scrutiny}``, for the fields this document's extraction actually
    #: carries. Only fields with something to say appear — an ordinary field is
    #: absent rather than present-and-false, so the payload does not grow with the
    #: 1,603-key spec vocabulary.
    field_scrutiny: dict[str, FieldScrutiny] = {}
    # The Tier 3 generic-analyzer output (LP-66), if any — for the LP-72 detail view.
    generic_analysis: dict[str, Any] | None = None
