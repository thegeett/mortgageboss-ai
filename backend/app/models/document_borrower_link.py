"""DocumentBorrowerLink (LP-118.8) — the borrower↔document association ("whose document is this").

Documents attach to the loan FILE (`Document.loan_file_id`); a document can also belong to a
specific borrower — "this is *Bansari's* W-2". Correct identity checking (ID-1 name, ID-2 SSN,
ID-3 DOB, IN-5 employer) is PER-BORROWER, so the rules need to know whose document each one is.

A **link table** (not a single `Document.borrower_id`) because a JOINT document (a joint bank
statement carrying both borrowers' names) legitimately belongs to MULTIPLE borrowers — one row per
(document, borrower) match. A document with no confident match has NO rows (unassigned/file-level);
its reason is recorded on ``Document.borrower_match_note``.

**Confidence + method are provenance** (like the canonicalization / DET-FUZZY discipline): a
reviewer or the eval set can see WHY a document was assigned. The links are recomputed (replaced) by
:func:`app.services.document_borrower_matching.assign_documents_to_borrowers`; nothing here executes
a verification rule.
"""

from uuid import UUID

from sqlalchemy import Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.types import SHORT_STRING


class DocumentBorrowerLink(Base, UUIDMixin, TimestampMixin):
    """One confident (document → borrower) association, with match provenance."""

    __tablename__ = "document_borrower_links"
    # One link per (document, borrower); re-matching replaces the file's links.
    __table_args__ = (
        UniqueConstraint(
            "document_id", "borrower_id", name="uq_document_borrower_links_document_borrower"
        ),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    borrower_id: Mapped[UUID] = mapped_column(
        ForeignKey("borrowers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The match score [0,1] — high only on a confident, unambiguous name match.
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # How it matched: "exact" | "name" (first+last) | "initial" (first-initial + last).
    method: Mapped[str] = mapped_column(String(SHORT_STRING), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<DocumentBorrowerLink doc={self.document_id} borrower={self.borrower_id} "
            f"conf={self.confidence} via={self.method}>"
        )
