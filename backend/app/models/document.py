"""Document model — uploaded files attached to a loan file (LP-15).

A :class:`Document` records **metadata** about an uploaded file (pay stub, bank
statement, W-2, …) plus a ``storage_path`` pointing at where the bytes live in
the storage backend (local in dev, S3 in prod — LP-35). The binary content is
**never** stored in the database (ADR-055): Postgres holds the record, the
storage backend holds the file.

A document carries two orthogonal classification facets, both set later by the
classifier (Epic 5 / Phase 2):

  * **category** — one of eight stable organizational buckets
    (:class:`DocumentCategory`), stored as a VARCHAR + CHECK enum.
  * **document_type** — a *flexible string* (``"pay_stub"``, ``"w2"``, a custom
    type, …). The full ~100-type set is finalized in Phase 2, so it is
    deliberately **not** an enum — that would mean a migration every time a type
    is added or refined (ADR-053). It is indexed for filtering.

It also moves through a processing **lifecycle** (:class:`DocumentStatus`,
ADR-054), updated by async tasks built in Epic 5; this ticket creates the record,
not the processing. Provenance (:class:`UploadSource` + nullable
``uploaded_by_user_id``, ADR-056) records how the file entered the system.

Like borrowers and properties, a document is an **owned child** of its loan file
(FK ``ondelete=CASCADE``) and has no ``company_id`` of its own — it is
company-scoped **transitively** through the loan file (ADR-052).
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import SHORT_STRING, LongStr, MediumStr

if TYPE_CHECKING:
    from app.models.extraction import Extraction
    from app.models.loan_file import LoanFile
    from app.models.user import User


class DocumentCategory(StrEnum):
    """The eight document categories from the processor's existing library.

    A small, stable organizational set — a good fit for a DB-enforced enum
    (ADR-053). ``CUSTOM`` is the escape hatch for a processor's own bucket.
    """

    ASSETS = "assets"
    BORROWER_INFO = "borrower_info"
    CREDIT = "credit"
    DISCLOSURES = "disclosures"
    INCOME_EMPLOYMENT = "income_employment"
    PROPERTY = "property"
    MISC = "misc"
    CUSTOM = "custom"


class Tier(StrEnum):
    """The level-of-investment tier a document type is handled at (LP-58, ADR-167).

    The three-tier model scales the pipeline from a handful of types to ~80-100
    without giving every type full structured extraction:

      * ``TIER_1`` — first-class: full structured extraction via the EXTRACTORS
        registry. High-value docs whose exact data drives Phase 3 verification.
      * ``TIER_2`` — recognized: classified + categorized + a short AI summary,
        stored/viewable, no deep extraction.
      * ``TIER_3`` — long-tail: didn't match a known type → a generic analyzer
        produces a structured summary.

    A small, stable set — a good fit for a DB-enforced enum (VARCHAR + CHECK,
    ADR-037). The document_type → tier mapping is **not** in the DB: it lives in
    the catalog (:mod:`app.documents.catalog`, the single source of truth), so a
    type's tier can be added/refined without a migration.
    """

    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"


class DocumentStatus(StrEnum):
    """Processing lifecycle status for a document (ADR-054).

    Async tasks (Epic 5) transition a document PENDING -> CLASSIFYING ->
    CLASSIFIED -> EXTRACTING -> COMPLETED. FAILED captures a processing error
    (see ``processing_error``); NEEDS_REVIEW surfaces a low-confidence
    classification for processor correction. Transitions are not enforced by a
    state machine in V1 — tasks set the status directly.
    """

    PENDING = "pending"
    CLASSIFYING = "classifying"
    CLASSIFIED = "classified"
    EXTRACTING = "extracting"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class UploadSource(StrEnum):
    """How a document entered the system (ADR-056).

    ``USER_UPLOAD`` has a user actor (``uploaded_by_user_id`` set); the other
    two do not (the borrower emails the inbox, or a MISMO import creates it), so
    ``uploaded_by_user_id`` is null for them.
    """

    USER_UPLOAD = "user_upload"
    BORROWER_INBOX = "borrower_inbox"
    MISMO_IMPORT = "mismo_import"


class StalenessResolution(StrEnum):
    """The processor's decision on a flagged-stale document (LP-71).

    Staleness is computed deterministically (the extracted date vs. a recency window,
    or a newer version exists). When a CURRENT document is flagged stale, the processor
    RESOLVES it: ``WAIVED`` (not required to be fresher for this file) or ``ACCEPTED``
    (acknowledged, used as-is). The third resolution — *replace* — is the versioning
    flow (the doc becomes historical), so it isn't a value here. Auto-resolution is V2.
    A ``None`` resolution means the staleness flag (if any) is unresolved/active.
    """

    WAIVED = "waived"
    ACCEPTED = "accepted"


class Document(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """An uploaded file attached to a loan file (metadata + storage path)."""

    __tablename__ = "documents"

    # --- Ownership (owned child of the loan file, ADR-052) -----------------
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # --- Storage metadata (the bytes live in the storage backend, ADR-055) --
    original_filename: Mapped[MediumStr] = mapped_column(nullable=False)
    mime_type: Mapped[MediumStr] = mapped_column(nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Path/key in the storage backend, not the bytes. LongStr (1024) because S3
    # keys and nested local paths can exceed the 256 of MediumStr.
    storage_path: Mapped[LongStr] = mapped_column(nullable=False)

    # --- Classification (set by the classifier, Epic 5 / Phase 2) ----------
    # Flexible string slug, NOT an enum: the ~100-type set is finalized in
    # Phase 2 and evolves, so it is governed at the app layer, not by a DB
    # CHECK (ADR-053). Indexed for filtering by type.
    document_type: Mapped[str | None] = mapped_column(
        String(SHORT_STRING), index=True, nullable=True
    )
    category: Mapped[DocumentCategory | None] = mapped_column(
        str_enum(DocumentCategory), nullable=True
    )
    # The level-of-investment tier the document was HANDLED as, looked up from the
    # document-type catalog during classification (LP-58). Nullable until
    # classified. Catalog-driven (:mod:`app.documents.catalog`), never a DB rule.
    tier: Mapped[Tier | None] = mapped_column(str_enum(Tier), nullable=True)
    # Classifier confidence in [0.0, 1.0]; bounds are an app-layer concern.
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # A short 1-2 sentence human-readable gist (LP-65), set by the Tier 2 shared
    # summary path for *recognized* documents — what the document is, for quick
    # processor reference. NOT structured data (that is the Tier 1 extraction). Null
    # for Tier 1 docs and when summarization fails (forgiving — low stakes).
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The Tier 3 generic-analyzer output (LP-66) — a structured-but-flexible JSON
    # blob (type guess, parties, dates, amounts, findings, summary) for an
    # *unrecognized* document. Null for Tier 1/2 and on analyzer failure.
    generic_analysis: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # The document's full text (LP-66), indexed for search — set for Tier 3 docs
    # (which can't be found by type). A GIN full-text index lives in the migration.
    full_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Processing lifecycle (ADR-054) ------------------------------------
    status: Mapped[DocumentStatus] = mapped_column(
        str_enum(DocumentStatus),
        default=DocumentStatus.PENDING,
        nullable=False,
        index=True,
    )
    # Failure reason, populated when status is FAILED.
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Versioning (Model C, LP-71) ---------------------------------------
    # New uploads are CURRENT + standalone (NO replacement assumption — multiples are
    # normal: a set of pay stubs / months of statements are NOT replacements). An
    # EXPLICIT replace supersedes a specific document: the old → historical
    # (is_current False), the new → current, BOTH kept for audit, sharing a
    # version_group. ``version_group_id`` is NULL for a standalone (single-version)
    # document and the originating document's id once a group forms. ``version`` is
    # the 1-based ordinal within the group. ``supersedes_document_id`` is the
    # immediate predecessor (the audit chain; SET NULL so the chain degrades, not breaks).
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    version_group_id: Mapped[UUID | None] = mapped_column(index=True, nullable=True)
    supersedes_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    # --- Staleness (LP-71) — the processor's resolution of a flagged-stale doc ----
    # Staleness itself is COMPUTED (the extracted date vs. a recency window, or a newer
    # version exists) — not stored. This records the processor's RESOLUTION (waive /
    # accept) so a resolved flag clears; NULL = unresolved. Replace is the versioning
    # flow (the doc goes historical), so it's not a value here. Auto-resolution is V2.
    staleness_resolution: Mapped[StalenessResolution | None] = mapped_column(
        str_enum(StalenessResolution), nullable=True
    )

    # An auto-ingested document (e.g. emailed by the borrower) can't be explicitly
    # "replaced" by a click, so it arrives flagged as a possible duplicate/replacement
    # for the processor to resolve. Set by ingestion (a later feature); the mechanism
    # + the gentle surfacing live here now. Default False (a normal user upload).
    possible_duplicate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- Provenance (ADR-056) ----------------------------------------------
    upload_source: Mapped[UploadSource] = mapped_column(str_enum(UploadSource), nullable=False)
    # Null for BORROWER_INBOX and MISMO_IMPORT (no user actor). ondelete=RESTRICT
    # for consistency with the soft-delete approach to users (ADR-044): a user
    # who uploaded documents cannot be hard-deleted out from under them.
    uploaded_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=True,
    )

    # --- Relationships -----------------------------------------------------
    loan_file: Mapped["LoanFile"] = relationship(back_populates="documents")
    # One-directional: User has no documents collection (not needed in V1).
    uploaded_by: Mapped["User | None"] = relationship()
    # Extraction versions (one-to-many, LP-16) — owned child of the document,
    # ordered by version so the collection reads oldest-to-newest.
    extractions: Mapped[list["Extraction"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Extraction.version",
    )

    @property
    def current_extraction(self) -> "Extraction | None":
        """The current extraction version, or None if there are none.

        A simple Python property over the loaded ``extractions`` collection
        (ADR-058) rather than a second filtered relationship — clearer for V1 and
        no extra query when ``extractions`` is already loaded. The caller must
        have loaded ``extractions`` (e.g. ``selectinload(Document.extractions)``);
        accessing it unloaded in async code raises, by design. The partial unique
        index guarantees at most one ``is_current`` row, so the first match is
        the answer.
        """
        return next((e for e in self.extractions if e.is_current), None)

    def __repr__(self) -> str:
        return (
            f"<Document {self.original_filename!r} status={self.status} "
            f"loan_file_id={self.loan_file_id}>"
        )
