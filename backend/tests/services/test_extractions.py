"""Tests for the extraction versioning service (LP-16).

The heart of this ticket: ``create_extraction_version`` must produce monotonic
per-document versions, flip ``is_current`` so exactly one version is current, and
never trip the partial unique index ``UNIQUE (document_id) WHERE is_current``.
These tests exercise the version flip, the one-current invariant (including a
direct attempt to force two current rows, which must fail), per-document version
independence, and the ``document.current_extraction`` convenience.

Uses the transaction-rollback ``db_session`` fixture from LP-10.
"""

from uuid import UUID

import pytest
from app.models import (
    Company,
    Document,
    Extraction,
    ExtractionStatus,
    UploadSource,
)
from app.services.extractions import create_extraction_version
from app.services.loan_files import create_loan_file
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def _make_document(db_session: AsyncSession, slug: str) -> Document:
    company = Company(name=slug.title(), slug=slug)
    db_session.add(company)
    await db_session.flush()
    loan_file = await create_loan_file(db_session, company_id=company.id)
    document = Document(
        loan_file_id=loan_file.id,
        original_filename="paystub.pdf",
        mime_type="application/pdf",
        file_size_bytes=1024,
        storage_path=f"{slug}/lf/paystub.pdf",
        upload_source=UploadSource.USER_UPLOAD,
    )
    db_session.add(document)
    await db_session.flush()
    return document


async def _versions_for(db_session: AsyncSession, document_id: UUID) -> list[Extraction]:
    stmt = (
        select(Extraction).where(Extraction.document_id == document_id).order_by(Extraction.version)
    )
    return list((await db_session.scalars(stmt)).all())


async def test_first_version_is_one_and_current(db_session: AsyncSession) -> None:
    """The first extraction for a document is version 1 and current."""
    document = await _make_document(db_session, "acme")
    extraction = await create_extraction_version(
        db_session,
        document_id=document.id,
        extracted_data={"gross_pay": "5000.00"},
        extraction_status=ExtractionStatus.SUCCEEDED,
    )
    assert extraction.version == 1
    assert extraction.is_current is True
    assert extraction.extracted_data == {"gross_pay": "5000.00"}


async def test_second_version_demotes_the_first(db_session: AsyncSession) -> None:
    """A second version is v2/current; the first becomes historical."""
    document = await _make_document(db_session, "acme")
    first = await create_extraction_version(
        db_session,
        document_id=document.id,
        extracted_data={"gross_pay": "5000.00"},
        extraction_status=ExtractionStatus.SUCCEEDED,
    )
    second = await create_extraction_version(
        db_session,
        document_id=document.id,
        extracted_data={"gross_pay": "5200.00"},
        extraction_status=ExtractionStatus.SUCCEEDED,
    )

    await db_session.refresh(first)
    assert second.version == 2
    assert second.is_current is True
    assert first.is_current is False


async def test_exactly_one_current_after_several_versions(db_session: AsyncSession) -> None:
    """After several versions, exactly one (the latest) is current."""
    document = await _make_document(db_session, "acme")
    for i in range(1, 5):
        await create_extraction_version(
            db_session,
            document_id=document.id,
            extracted_data={"run": i},
            extraction_status=ExtractionStatus.SUCCEEDED,
        )

    versions = await _versions_for(db_session, document.id)
    assert [e.version for e in versions] == [1, 2, 3, 4]
    current = [e for e in versions if e.is_current]
    assert len(current) == 1
    assert current[0].version == 4


async def test_partial_unique_index_forbids_two_current(db_session: AsyncSession) -> None:
    """Forcing a second current row for the same document fails at the DB."""
    document = await _make_document(db_session, "acme")
    await create_extraction_version(
        db_session,
        document_id=document.id,
        extracted_data={},
        extraction_status=ExtractionStatus.SUCCEEDED,
    )

    # Insert a second row directly with is_current=True, bypassing the service.
    # The partial unique index must reject it.
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                Extraction(
                    document_id=document.id,
                    version=2,
                    is_current=True,
                    extracted_data={},
                    extraction_status=ExtractionStatus.SUCCEEDED,
                )
            )
            await db_session.flush()


async def test_document_extractions_and_current_convenience(db_session: AsyncSession) -> None:
    """document.extractions returns all versions; current_extraction is the latest."""
    document = await _make_document(db_session, "acme")
    for i in range(1, 4):
        await create_extraction_version(
            db_session,
            document_id=document.id,
            extracted_data={"run": i},
            extraction_status=ExtractionStatus.SUCCEEDED,
        )

    stmt = (
        select(Document)
        .where(Document.id == document.id)
        .options(selectinload(Document.extractions))
    )
    loaded = (await db_session.scalars(stmt)).one()
    assert [e.version for e in loaded.extractions] == [1, 2, 3]
    assert loaded.current_extraction is not None
    assert loaded.current_extraction.version == 3
    assert loaded.current_extraction.is_current is True


async def test_versioning_is_per_document(db_session: AsyncSession) -> None:
    """Two documents each have their own independent version sequence."""
    doc_a = await _make_document(db_session, "company-a")
    doc_b = await _make_document(db_session, "company-b")

    a1 = await create_extraction_version(
        db_session,
        document_id=doc_a.id,
        extracted_data={},
        extraction_status=ExtractionStatus.SUCCEEDED,
    )
    b1 = await create_extraction_version(
        db_session,
        document_id=doc_b.id,
        extracted_data={},
        extraction_status=ExtractionStatus.SUCCEEDED,
    )
    a2 = await create_extraction_version(
        db_session,
        document_id=doc_a.id,
        extracted_data={},
        extraction_status=ExtractionStatus.SUCCEEDED,
    )

    # Each document starts its own sequence at 1.
    assert a1.version == 1
    assert b1.version == 1
    assert a2.version == 2
    # doc_b still has a single current v1; doc_a's current is v2.
    assert b1.is_current is True
    assert a2.is_current is True
    await db_session.refresh(a1)
    assert a1.is_current is False


async def test_failed_extraction_records_error_detail(db_session: AsyncSession) -> None:
    """A FAILED run can carry an error_detail and empty data, still versioned."""
    document = await _make_document(db_session, "acme")
    extraction = await create_extraction_version(
        db_session,
        document_id=document.id,
        extracted_data={},
        extraction_status=ExtractionStatus.FAILED,
        error_detail="model returned unparseable output",
    )
    assert extraction.version == 1
    assert extraction.is_current is True
    assert extraction.extraction_status is ExtractionStatus.FAILED
    assert extraction.error_detail == "model returned unparseable output"
