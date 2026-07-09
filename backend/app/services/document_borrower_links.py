"""Document→borrower link persistence (LP-202, ADR-239).

The DB-facing side of the deterministic matcher: read a document's asserted
name(s) from its current extraction, match against the loan file's borrowers
(:mod:`app.services.borrower_name_matching` — pure, no AI), and record the links.

* **Idempotent.** A re-match replaces the document's existing links wholesale.
* **Honest no-match.** A document that asserts no borrower name, or whose name
  matches nobody above the threshold, produces **zero** rows — never an error,
  never a null-borrower row.
* Nothing consumes the links yet (LP-206 will); this is the producer + reader.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.borrower import Borrower
from app.models.document import Document
from app.models.document_borrower_link import DocumentBorrowerLink, MatchMethod
from app.models.extraction import Extraction
from app.models.helpers import only_active
from app.services.borrower_name_matching import (
    BorrowerName,
    asserted_names_for,
    match_document,
)


async def _current_extracted_data(db: AsyncSession, document_id: UUID) -> dict[str, Any]:
    """The document's current extraction payload, or ``{}`` if none."""
    extraction = await db.scalar(
        select(Extraction).where(
            Extraction.document_id == document_id,
            Extraction.is_current.is_(True),
        )
    )
    return extraction.extracted_data if extraction and extraction.extracted_data else {}


async def _loan_file_borrowers(db: AsyncSession, loan_file_id: UUID) -> list[BorrowerName]:
    borrowers = (
        (
            await db.execute(
                only_active(
                    select(Borrower).where(Borrower.loan_file_id == loan_file_id), Borrower
                ).order_by(Borrower.borrower_position)
            )
        )
        .scalars()
        .all()
    )
    return [
        BorrowerName(
            borrower_id=b.id,
            first_name=b.first_name,
            middle_name=b.middle_name,
            last_name=b.last_name,
        )
        for b in borrowers
    ]


async def assign_document_borrower_links(
    db: AsyncSession, document: Document
) -> list[DocumentBorrowerLink]:
    """(Re)compute and persist a document's borrower links. Flush-only.

    Replaces any existing links for the document. Returns the persisted rows
    (empty when the document names no borrower or matches none above threshold).
    """
    # Wipe any prior links for this document — a re-match is authoritative.
    await db.execute(
        delete(DocumentBorrowerLink).where(DocumentBorrowerLink.document_id == document.id)
    )

    extracted = await _current_extracted_data(db, document.id)
    names = asserted_names_for(extracted, document.document_type)
    if not names:
        await db.flush()
        return []

    borrowers = await _loan_file_borrowers(db, document.loan_file_id)
    matches = match_document(names, borrowers)

    rows = [
        DocumentBorrowerLink(
            document_id=document.id,
            borrower_id=m.borrower_id,
            confidence=m.confidence,
            method=MatchMethod(m.method),
        )
        for m in matches
    ]
    db.add_all(rows)
    await db.flush()
    return rows


async def get_document_borrower_links(
    db: AsyncSession, document_id: UUID
) -> list[DocumentBorrowerLink]:
    """Fetch a document's borrower links (empty when there are none).

    Excludes links whose document OR borrower has been soft-deleted: the link table
    has no soft-delete of its own and its ``ondelete=CASCADE`` FKs never fire on a
    soft delete (deleted_at is set, the row survives), so a borrower removed from
    the file after matching would otherwise leak back a link to a borrower the file
    no longer has. Joining the (soft-delete-aware) parents keeps reads honest.
    """
    stmt = (
        select(DocumentBorrowerLink)
        .join(Document, Document.id == DocumentBorrowerLink.document_id)
        .join(Borrower, Borrower.id == DocumentBorrowerLink.borrower_id)
        .where(DocumentBorrowerLink.document_id == document_id)
        .order_by(DocumentBorrowerLink.confidence.desc())
    )
    stmt = only_active(stmt, Document)
    stmt = only_active(stmt, Borrower)
    result = await db.execute(stmt)
    return list(result.scalars().all())
