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
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import SHORT_STRING, LongStr, MediumStr

if TYPE_CHECKING:
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
    # Classifier confidence in [0.0, 1.0]; bounds are an app-layer concern.
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Processing lifecycle (ADR-054) ------------------------------------
    status: Mapped[DocumentStatus] = mapped_column(
        str_enum(DocumentStatus),
        default=DocumentStatus.PENDING,
        nullable=False,
        index=True,
    )
    # Failure reason, populated when status is FAILED.
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    def __repr__(self) -> str:
        return (
            f"<Document {self.original_filename!r} status={self.status} "
            f"loan_file_id={self.loan_file_id}>"
        )
