"""Tests for the Extraction model (LP-16).

Covers the extraction record against a real table: field round-tripping, the
JSON ``extracted_data`` storing nested structured data (a mock pay stub and a
bank statement with a transactions list), the ``extraction_status`` CHECK
constraint, soft delete, and tenant isolation (extractions reachable only through
the owning company's documents -> loan files, since they have no company_id).

The versioning behaviour (the version flip and the one-current invariant) is
exercised in ``tests/services/test_extractions.py`` alongside the helper.

Uses the transaction-rollback ``db_session`` fixture from LP-10.
"""

from typing import Any

import pytest
from app.models import (
    Company,
    Document,
    Extraction,
    ExtractionStatus,
    LoanFile,
    UploadSource,
    only_active,
    scope_to_company,
    utcnow,
)
from app.services.loan_files import create_loan_file
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_company(db_session: AsyncSession, slug: str) -> Company:
    company = Company(name=slug.title(), slug=slug)
    db_session.add(company)
    await db_session.flush()
    return company


async def _make_loan_file(db_session: AsyncSession, company: Company) -> LoanFile:
    return await create_loan_file(db_session, company_id=company.id)


async def _make_document(db_session: AsyncSession, loan_file: LoanFile) -> Document:
    document = Document(
        loan_file_id=loan_file.id,
        original_filename="paystub.pdf",
        mime_type="application/pdf",
        file_size_bytes=1024,
        storage_path="acme/lf/paystub.pdf",
        upload_source=UploadSource.USER_UPLOAD,
    )
    db_session.add(document)
    await db_session.flush()
    return document


async def _add_extraction(
    db_session: AsyncSession,
    document: Document,
    *,
    version: int = 1,
    is_current: bool = True,
    extracted_data: dict[str, Any] | None = None,
    extraction_status: ExtractionStatus = ExtractionStatus.SUCCEEDED,
) -> Extraction:
    extraction = Extraction(
        document_id=document.id,
        version=version,
        is_current=is_current,
        extracted_data=extracted_data if extracted_data is not None else {},
        extraction_status=extraction_status,
    )
    db_session.add(extraction)
    await db_session.flush()
    return extraction


async def test_create_extraction_with_fields(db_session: AsyncSession) -> None:
    """A first extraction persists its fields: version 1, current, succeeded."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    document = await _make_document(db_session, loan_file)
    extraction = Extraction(
        document_id=document.id,
        version=1,
        is_current=True,
        extracted_data={"gross_pay": "5000.00"},
        extraction_status=ExtractionStatus.SUCCEEDED,
        model_used="claude-sonnet-4-5",
        tokens_used=1234,
        cost_estimate=0.0023,
    )
    db_session.add(extraction)
    await db_session.flush()

    await db_session.refresh(extraction)
    assert extraction.version == 1
    assert extraction.is_current is True
    assert extraction.extraction_status is ExtractionStatus.SUCCEEDED
    assert extraction.model_used == "claude-sonnet-4-5"
    assert extraction.tokens_used == 1234
    assert extraction.cost_estimate == pytest.approx(0.0023)
    assert extraction.error_detail is None


async def test_extracted_data_round_trips_nested_json(db_session: AsyncSession) -> None:
    """extracted_data stores and retrieves a nested dict + list structure.

    Mirrors a bank statement: account-level fields plus a transactions list —
    transactions live inside the JSON in V1, not a separate table (ADR-059).
    """
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    document = await _make_document(db_session, loan_file)
    data = {
        "account_holder": "Jane Doe",
        "account_number_last4": "6789",
        "ending_balance": "12500.34",
        "transactions": [
            {"date": "2026-05-01", "description": "Payroll", "amount": "5000.00"},
            {"date": "2026-05-03", "description": "Rent", "amount": "-2200.00"},
            {"date": "2026-05-10", "description": "Large deposit", "amount": "9000.00"},
        ],
    }
    extraction = await _add_extraction(db_session, document, extracted_data=data)

    await db_session.refresh(extraction)
    assert extraction.extracted_data == data
    assert extraction.extracted_data["transactions"][2]["description"] == "Large deposit"
    assert len(extraction.extracted_data["transactions"]) == 3


async def test_extraction_status_check_constraint_rejects_invalid_value(
    db_session: AsyncSession,
) -> None:
    """The DB CHECK constraint rejects an out-of-range extraction_status."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    document = await _make_document(db_session, loan_file)
    extraction = await _add_extraction(db_session, document)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE extractions SET extraction_status = :bad WHERE id = :id"),
                {"bad": "in_progress", "id": extraction.id},
            )


async def test_extraction_status_accepts_all_valid(db_session: AsyncSession) -> None:
    """SUCCEEDED, FAILED, and PARTIAL are all valid statuses."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    document = await _make_document(db_session, loan_file)
    for i, status in enumerate(ExtractionStatus, start=1):
        # Only one may be current (partial unique index), so mark these historical.
        extraction = await _add_extraction(
            db_session, document, version=i, is_current=False, extraction_status=status
        )
        await db_session.refresh(extraction)
        assert extraction.extraction_status is status


async def test_soft_delete_and_only_active(db_session: AsyncSession) -> None:
    """Soft delete sets deleted_at; only_active() filters the extraction out."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    document = await _make_document(db_session, loan_file)
    live = await _add_extraction(db_session, document, version=1, is_current=False)
    gone = await _add_extraction(db_session, document, version=2, is_current=False)

    gone.deleted_at = utcnow()
    await db_session.flush()
    assert gone.is_deleted is True

    stmt = only_active(select(Extraction), Extraction)
    ids = {e.id for e in (await db_session.scalars(stmt)).all()}
    assert live.id in ids
    assert gone.id not in ids


async def test_extractions_are_isolated_by_company_through_document_and_loan_file(
    db_session: AsyncSession,
) -> None:
    """Extractions carry no company_id; isolation is transitive (ADR-052).

    A query scoped to company A's loan files (joined extraction -> document ->
    loan_file) must never surface company B's extractions.
    """
    company_a = await _make_company(db_session, "company-a")
    company_b = await _make_company(db_session, "company-b")
    doc_a = await _make_document(db_session, await _make_loan_file(db_session, company_a))
    doc_b = await _make_document(db_session, await _make_loan_file(db_session, company_b))

    ext_a = await _add_extraction(db_session, doc_a)
    ext_b = await _add_extraction(db_session, doc_b)

    stmt_a = scope_to_company(
        select(Extraction)
        .join(Document, Extraction.document_id == Document.id)
        .join(LoanFile, Document.loan_file_id == LoanFile.id),
        LoanFile,
        company_a.id,
    )
    ids_a = {e.id for e in (await db_session.scalars(stmt_a)).all()}
    assert ids_a == {ext_a.id}
    assert ext_b.id not in ids_a

    stmt_b = scope_to_company(
        select(Extraction)
        .join(Document, Extraction.document_id == Document.id)
        .join(LoanFile, Document.loan_file_id == LoanFile.id),
        LoanFile,
        company_b.id,
    )
    ids_b = {e.id for e in (await db_session.scalars(stmt_b)).all()}
    assert ids_b == {ext_b.id}
    assert ids_a.isdisjoint(ids_b)
