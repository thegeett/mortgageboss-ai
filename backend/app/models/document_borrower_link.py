"""Document→borrower link model (LP-202, ADR-239).

A deterministic, recomputable link saying *"this document is about this
borrower"*, produced by name matching (:mod:`app.services.borrower_name_matching`).
Two deliberate shape choices:

* **One-to-many.** A document links to *zero, one, or many* borrowers — a joint
  bank statement is about both spouses — so this is a link *table*, not a
  ``Document.borrower_id`` column. A ``UNIQUE (document_id, borrower_id)`` keeps
  one row per pair.
* **The resolved link lives ONLY here.** The raw asserted name stays on the
  document's extraction; this table holds the *correlation* (with its
  ``confidence`` + ``method`` provenance), keeping the document facts raw and
  uncorrelated. A no-match document has **zero** rows — never a null-borrower row.

Owned child of the document (``ondelete=CASCADE``); company-scoped transitively
via the document → loan file (ADR-052). No soft-delete: links are derived and
replaced wholesale when a document is re-matched.
"""

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import SHORT_STRING

if TYPE_CHECKING:
    from app.models.borrower import Borrower
    from app.models.document import Document


class MatchMethod(StrEnum):
    """How the deterministic matcher resolved a document→borrower link (LP-202).

    Lives next to the model that owns the ``method`` column so one CHECK-constrained
    vocabulary governs both storage and the matcher's :class:`MatchResult.method`.
    LP-206 branches on this, so a typo'd/drifted literal must fail at write time,
    not surface downstream.
    """

    EXACT = "exact"  # every borrower token present verbatim on the document
    NORMALIZED = "normalized"  # matched after normalization / nickname resolution
    FUZZY = "fuzzy"  # matched via edit-distance similarity (a typo)


class DocumentBorrowerLink(Base, UUIDMixin, TimestampMixin):
    """A resolved link between a document and a borrower it is about."""

    __tablename__ = "document_borrower_links"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "borrower_id", name="uq_document_borrower_links_document_borrower"
        ),
        # Confidence is a similarity in [0, 1] — guarded at the DB (cf. findings).
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_document_borrower_links_confidence_range",
        ),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    borrower_id: Mapped[UUID] = mapped_column(
        ForeignKey("borrowers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The matcher's similarity score in [0, 1] for this pair.
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # How the match was made — CHECK-constrained to the MatchMethod vocabulary so a
    # drifted/typo'd value can't persist (LP-206 branches on it).
    method: Mapped[MatchMethod] = mapped_column(
        str_enum(MatchMethod, length=SHORT_STRING), nullable=False
    )

    document: Mapped["Document"] = relationship()
    borrower: Mapped["Borrower"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<DocumentBorrowerLink document_id={self.document_id} "
            f"borrower_id={self.borrower_id} method={self.method} confidence={self.confidence}>"
        )
