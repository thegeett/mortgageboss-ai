"""Extraction model — structured data extracted from a document by AI (LP-16).

An :class:`Extraction` holds the document-type-specific fields read out of a
document (e.g. gross pay from a pay stub, the transaction list from a bank
statement). The data lives in a single ``extracted_data`` JSON column; its
*structure* is governed by document-type-specific Pydantic schemas at the
**application layer** (Phase 2), NOT by the database and NOT as a generic
field-bag. This is the deliberate difference from the POC's generic
``ExtractedField`` rows: V1 stores typed, document-type-specific structured data
that merely happens to be persisted as JSON (ADR-057).

Extractions are **versioned** (ADR-058): a document can be extracted many times
(re-classification, prompt improvements). Each run is a new ``version``; exactly
one row per document is ``is_current`` (enforced by a *partial unique index* —
``UNIQUE (document_id) WHERE is_current``); prior versions are kept for audit and
comparison. New versions are created through
:func:`app.services.extractions.create_extraction_version`, which demotes the old
current before inserting the new one so the index is never violated.

Bank-statement transactions live *inside* ``extracted_data`` as a nested list in
V1 — there is no separate transactions table (ADR-059).

Like documents, an extraction is an **owned child** (FK ``ondelete=CASCADE``) and
has no ``company_id`` — it is company-scoped transitively through
``document -> loan_file`` (ADR-052).
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import SHORT_STRING

if TYPE_CHECKING:
    from app.models.document import Document


class ExtractionStatus(StrEnum):
    """Outcome of an extraction run.

    ``PARTIAL`` is for a run that produced some fields but not all (e.g. a few
    fields were unreadable); ``FAILED`` produced nothing usable (reason in
    ``error_detail``).
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"


class Extraction(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A versioned set of structured data extracted from a document."""

    __tablename__ = "extractions"
    __table_args__ = (
        # Exactly one current extraction per document. A PARTIAL unique index:
        # the uniqueness applies only to rows where is_current is true, so any
        # number of historical (is_current=false) versions can coexist. The
        # WHERE clause is Postgres-specific (postgresql_where).
        Index(
            "uq_extractions_document_id_current",
            "document_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    # --- Ownership (owned child of the document, ADR-052) ------------------
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # --- Versioning (ADR-058) ----------------------------------------------
    # Sequential per document, starting at 1. is_current marks the active
    # version; the partial unique index above guarantees one per document.
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- Extracted data (typed at the app layer, ADR-057) ------------------
    # Document-type-specific structure, validated by Pydantic schemas in Phase 2.
    # Defaults to an empty dict (e.g. a FAILED run with no data).
    extracted_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # --- Outcome + AI provenance (for cost tracking and debugging) ---------
    extraction_status: Mapped[ExtractionStatus] = mapped_column(
        str_enum(ExtractionStatus), nullable=False
    )
    model_used: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Float, not Money/Numeric(14,2): per-extraction costs are sub-cent estimates
    # (e.g. $0.0023) that the 2-decimal Money type can't represent. This is an
    # estimate for tracking, not a ledger amount, so float precision is fine.
    cost_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Relationships -----------------------------------------------------
    document: Mapped["Document"] = relationship(back_populates="extractions")

    def __repr__(self) -> str:
        state = "current" if self.is_current else "historical"
        return f"<Extraction v{self.version} {state} document_id={self.document_id}>"
