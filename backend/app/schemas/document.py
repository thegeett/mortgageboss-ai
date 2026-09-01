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


class DocumentReprocessRequest(BaseModel):
    """Re-run the full pipeline on a stored document, classification included (LP-637)."""

    #: Reprocess even when the document looks HUMAN-CLASSIFIED.
    #:
    #: The signal is ``classification_confidence == 1.0``, which the type-override endpoint sets and
    #: means "a person chose this". It is an IMPERFECT proxy and that is stated rather than hidden:
    #: `coerce_confidence` clamps the model's own answer into [0, 1], so a very confident
    #: classification can land on 1.0 too. Refusing by default therefore costs a processor one extra
    #: click on a rare confidently-classified document, while the alternative — replacing someone's
    #: decision with a model's guess and telling nobody — is the more expensive mistake.
    force: bool = False


class BulkReprocessRequest(BaseModel):
    """Reprocess a loan file's documents in one call (LP-637)."""

    #: Reprocess EVERY current document, not only the ones that look like they would benefit.
    #:
    #: The default is bounded on purpose. A 44-document file is 44 classifications and 44
    #: re-extractions, and the documents this feature exists for are a minority of any file — the
    #: untyped, the `unknown`, and the ones sitting in review. Spending the whole file's model
    #: budget to re-derive answers that are already correct is the easy way to make a useful tool
    #: something nobody is allowed to press.
    all_documents: bool = False

    #: Include documents whose type a person set. Same meaning, and same imperfect signal, as the
    #: per-document endpoint's ``force`` — see :class:`DocumentReprocessRequest`.
    force: bool = False


class BulkReprocessResponse(BaseModel):
    """What a bulk reprocess actually did (LP-637).

    REPORTS THE SKIPS, and that is most of the point. A bulk action that silently does less than it
    was asked leaves a processor waiting for ten documents to change when only seven were sent —
    with no way to tell that from a slow queue. Each skip carries the reason it was skipped.
    """

    queued: int
    queued_document_ids: list[UUID]
    #: reason -> how many, e.g. ``{"already_processing": 2, "type_set_by_a_person": 1}``.
    skipped: dict[str, int]


class DocumentTypeOption(BaseModel):
    """One selectable document type for the manual-correction control (LP-638).

    Served from the catalog rather than hardcoded in the frontend. The list it replaces was eight
    entries written when there were three document types; the catalog now has 164, so a processor
    could not correct a document to `closing_disclosure`, `purchase_agreement` or `mortgage_statement`
    at all — and two of the eight (`tax_return_1040`, `other`) were not catalog types, so choosing
    them set a document to a string nothing recognises.
    """

    value: str
    label: str
    category: str
    #: Does choosing this type re-run structured extraction, or only relabel the document?
    #:
    #: Served rather than inferred, because the frontend's own answer was a three-item set
    #: (`pay_stub`, `w2`, `bank_statement`) written in Phase 1 while the registry grew to 121. So
    #: correcting a document to `closing_disclosure` told a processor "recorded only — no data is
    #: extracted" while the pipeline extracted it. The registry is the only thing that knows.
    extracts: bool


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
    #: Why the last run could not finish, in words meant for a processor (LP-637 review).
    #:
    #: EXPOSED BECAUSE OTHERWISE IT REACHES NOBODY. The pipeline writes this column and the whole
    #: point of writing it is that "it is the only place a processor looks" — which was not true:
    #: no response schema carried it, so the two carefully-worded failure voices were dead text and
    #: LF-ZE9N's oversized document would still have shown "Processing / uncategorized" with no
    #: explanation after the fix.
    #:
    #: Safe to expose, and that is a property the writers maintain rather than an assumption here:
    #: `document_processing.py` treats this column as UI-shown and PII-safe by module invariant,
    #: and refuses to interpolate model free-text into it for exactly that reason.
    processing_error: str | None
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


class DocumentDetailResponse(DocumentResponse):
    """A document plus its current extraction (``None`` until extraction runs)."""

    current_extraction: ExtractionPublic | None
    # The Tier 3 generic-analyzer output (LP-66), if any — for the LP-72 detail view.
    generic_analysis: dict[str, Any] | None = None
