"""Document→borrower link persistence (LP-202) — DB round-trip tests.

Covers: a single-borrower document links the right borrower; a joint document
links BOTH; a document that asserts no borrower name produces zero rows; links
read back; and re-matching replaces prior links.

Read-back uses :func:`_stored_links` — a plain select in this file — rather than a
production read helper. The former helper (``get_document_borrower_links``) was
removed as dead code: nothing outside these tests called it, and it filtered on
``document_id`` alone with no join back to the loan file. Reading the rows directly
keeps these tests about what ``assign_document_borrower_links`` *persists*, which is
the live behaviour they exist to protect.
"""

from uuid import UUID

from app.models import (
    Borrower,
    Company,
    Document,
    DocumentBorrowerLink,
    ExtractionStatus,
    UploadSource,
)
from app.services.document_borrower_links import assign_document_borrower_links
from app.services.extractions import create_extraction_version
from app.services.loan_files import create_loan_file
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _borrowers_stmt(loan_file_id: UUID):
    return select(Borrower).where(Borrower.loan_file_id == loan_file_id)


async def _stored_links(db: AsyncSession, document_id: UUID) -> list[DocumentBorrowerLink]:
    """The link rows as stored, highest confidence first. No soft-delete filtering.

    Deliberately unfiltered: these tests assert what was WRITTEN. Excluding links to
    soft-deleted parents is the reader's job, and the live reader
    (``_links_by_document`` in the snapshot's documents section) is tested where it
    lives, by ``test_link_to_soft_deleted_borrower_excluded``.
    """
    rows = await db.scalars(
        select(DocumentBorrowerLink)
        .where(DocumentBorrowerLink.document_id == document_id)
        .order_by(DocumentBorrowerLink.confidence.desc())
    )
    return list(rows.all())


async def _loan_file_with_borrowers(
    db: AsyncSession, slug: str, borrowers: list[tuple[str, str]]
) -> UUID:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    loan_file = await create_loan_file(db, company_id=company.id)
    for i, (first, last) in enumerate(borrowers, start=1):
        db.add(
            Borrower(
                loan_file_id=loan_file.id,
                first_name=first,
                last_name=last,
                is_primary=(i == 1),
                borrower_position=i,
            )
        )
    await db.flush()
    return loan_file.id


async def _document(
    db: AsyncSession, loan_file_id: UUID, doc_type: str, extracted: dict
) -> Document:
    document = Document(
        loan_file_id=loan_file_id,
        original_filename=f"{doc_type}.pdf",
        mime_type="application/pdf",
        file_size_bytes=1024,
        storage_path=f"lf/{doc_type}.pdf",
        upload_source=UploadSource.USER_UPLOAD,
        document_type=doc_type,
    )
    db.add(document)
    await db.flush()
    await create_extraction_version(
        db,
        document_id=document.id,
        extracted_data=extracted,
        extraction_status=ExtractionStatus.SUCCEEDED,
    )
    return document


def _name_field(value: str) -> dict:
    return {"value": value, "source": None, "confidence": None}


async def test_single_borrower_document_links_correct_borrower(db_session: AsyncSession) -> None:
    lf = await _loan_file_with_borrowers(
        db_session, "single", [("Akash", "Patel"), ("Priya", "Patel")]
    )
    borrowers = {
        (b.first_name, b.last_name): b.id
        for b in (await db_session.scalars(_borrowers_stmt(lf))).all()
    }
    doc = await _document(db_session, lf, "pay_stub", {"employee_name": _name_field("Akash Patel")})

    links = await assign_document_borrower_links(db_session, doc)
    assert len(links) == 1
    assert links[0].borrower_id == borrowers[("Akash", "Patel")]
    assert links[0].method == "exact"


async def test_joint_document_links_both_borrowers(db_session: AsyncSession) -> None:
    lf = await _loan_file_with_borrowers(
        db_session, "joint", [("Akash", "Patel"), ("Priya", "Patel")]
    )
    doc = await _document(
        db_session,
        lf,
        "bank_statement",
        {"account_holder_name": _name_field("Akash Patel and Priya Patel")},
    )
    links = await assign_document_borrower_links(db_session, doc)
    assert len(links) == 2
    assert {lk.borrower_id for lk in links} == {
        b.id for b in (await db_session.scalars(_borrowers_stmt(lf))).all()
    }


async def test_no_name_document_produces_zero_links(db_session: AsyncSession) -> None:
    lf = await _loan_file_with_borrowers(db_session, "noname", [("Akash", "Patel")])
    # An appraisal asserts no borrower name (no registered field).
    doc = await _document(db_session, lf, "appraisal", {"appraised_value": _name_field("500000")})
    links = await assign_document_borrower_links(db_session, doc)
    assert links == []
    assert await _stored_links(db_session, doc.id) == []


async def test_unmatched_name_produces_zero_links(db_session: AsyncSession) -> None:
    lf = await _loan_file_with_borrowers(db_session, "unmatched", [("Akash", "Patel")])
    doc = await _document(
        db_session, lf, "pay_stub", {"employee_name": _name_field("John Williams")}
    )
    assert await assign_document_borrower_links(db_session, doc) == []


async def test_links_persist_and_read_back_and_rematch_replaces(db_session: AsyncSession) -> None:
    lf = await _loan_file_with_borrowers(db_session, "roundtrip", [("Akash", "Patel")])
    doc = await _document(db_session, lf, "pay_stub", {"employee_name": _name_field("Akash Patel")})

    await assign_document_borrower_links(db_session, doc)
    read = await _stored_links(db_session, doc.id)
    assert len(read) == 1 and read[0].confidence == 1.0

    # Re-matching is idempotent — still exactly one link, not duplicated.
    await assign_document_borrower_links(db_session, doc)
    assert len(await _stored_links(db_session, doc.id)) == 1


# NOTE: `test_soft_deleted_borrower_link_is_not_returned` was removed with the read
# helper it exercised. It asserted that a READER excludes a link whose borrower was
# soft-deleted after matching — real behaviour, but it now belongs entirely to the
# live reader, and is covered there by
# `tests/verification/snapshot/test_documents_section.py::test_link_to_soft_deleted_borrower_excluded`.
# The write path tested in this file is unchanged: the link row is deliberately left
# in place on a soft delete (ondelete=CASCADE never fires on one), which is exactly
# why the reader, not the writer, has to do the filtering.
