"""Snapshot builder / orchestrator (LP-208) — DB-backed.

Happy path (all three sections), present-empty documents, resilient+honest section
failure (assembler raises → absent-with-reason, others intact), statelessness,
run_id received-not-minted, frozen, and LoanFileNotFound.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from app.models import Borrower, Company, Document, ExtractionStatus, UploadSource
from app.models.document_borrower_link import DocumentBorrowerLink, MatchMethod
from app.models.lender import LoanProgram
from app.models.loan_file import LoanFile, LoanPurpose
from app.models.property import Property
from app.models.stated_financials import StatedAsset, StatedIncomeItem, StatedLiability
from app.services.extractions import create_extraction_version
from app.services.loan_files import create_loan_file
from app.verification.snapshot import builder as bld
from app.verification.snapshot.builder import LoanFileNotFound, build_snapshot
from app.verification.snapshot.model import SNAPSHOT_VERSION, Snapshot
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession


async def _complete_loan_file(db: AsyncSession, *, with_documents: bool = True) -> LoanFile:
    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    lf = await create_loan_file(db, company_id=company.id)
    lf.loan_program = LoanProgram.CONVENTIONAL
    lf.loan_purpose = LoanPurpose.PURCHASE
    lf.loan_amount = Decimal("400000.00")
    lf.note_amount = Decimal("400000.00")
    lf.note_rate_percent = Decimal("6.5000")
    lf.amortization_months = 360
    borrower = Borrower(
        loan_file_id=lf.id,
        first_name="Akash",
        last_name="Patel",
        is_primary=True,
        borrower_position=1,
    )
    db.add(borrower)
    await db.flush()
    db.add(
        StatedIncomeItem(
            borrower_id=borrower.id, monthly_amount=Decimal("9000.00"), income_type="Base"
        )
    )
    db.add(
        StatedLiability(
            loan_file_id=lf.id, liability_type="Installment", monthly_payment=Decimal("500.00")
        )
    )
    db.add(StatedAsset(loan_file_id=lf.id, asset_type="CheckingAccount", value=Decimal("60000.00")))
    db.add(
        Property(
            loan_file_id=lf.id,
            purchase_price=Decimal("500000.00"),
            estimated_value=Decimal("500000.00"),
        )
    )
    if with_documents:
        doc = Document(
            loan_file_id=lf.id,
            original_filename="pay_stub.pdf",
            mime_type="application/pdf",
            file_size_bytes=1,
            storage_path="lf/pay_stub.pdf",
            upload_source=UploadSource.USER_UPLOAD,
            document_type="pay_stub",
        )
        db.add(doc)
        await db.flush()
        await create_extraction_version(
            db,
            document_id=doc.id,
            extracted_data={
                "employee_name": {"value": "Akash Patel", "source": None, "confidence": 0.98}
            },
            extraction_status=ExtractionStatus.SUCCEEDED,
        )
        db.add(
            DocumentBorrowerLink(
                document_id=doc.id,
                borrower_id=borrower.id,
                confidence=1.0,
                method=MatchMethod.EXACT,
            )
        )
    await db.flush()
    return lf


async def test_happy_path_all_sections_present_and_metadata(db_session: AsyncSession) -> None:
    lf = await _complete_loan_file(db_session)
    run_id = uuid4()
    snap = await build_snapshot(
        db_session, loan_file_id=lf.id, run_id=run_id, company_id=lf.company_id
    )

    assert isinstance(snap, Snapshot)
    assert snap.loan_file_id == lf.id
    assert snap.run_id == run_id
    assert snap.snapshot_version == SNAPSHOT_VERSION
    assert snap.created_at.tzinfo is not None  # tz-aware

    assert snap.mismo.is_present and snap.mismo.facts  # populated
    assert snap.documents.is_present and len(snap.documents.entries) == 1
    assert snap.documents.entries[0].belongs_to is not None  # link resolved
    assert snap.calculations.is_present
    assert snap.calculations.dti is not None and snap.calculations.ltv is not None


async def test_empty_documents_is_present_not_absent(db_session: AsyncSession) -> None:
    lf = await _complete_loan_file(db_session, with_documents=False)
    snap = await build_snapshot(
        db_session, loan_file_id=lf.id, run_id=uuid4(), company_id=lf.company_id
    )
    # No documents → a present, empty documents section (NOT absent, NOT an error).
    assert snap.documents.is_present
    assert snap.documents.entries == []
    assert snap.documents.reason is None
    # Other sections still built.
    assert snap.mismo.is_present and snap.mismo.facts
    assert snap.calculations.is_present


async def test_section_failure_is_absent_with_reason_others_intact(
    db_session: AsyncSession,
) -> None:
    lf = await _complete_loan_file(db_session)
    # Force the MISMO assembler to raise; the snapshot must still build.
    with patch.object(bld, "load_mismo_section", AsyncMock(side_effect=RuntimeError("boom"))):
        snap = await build_snapshot(
            db_session, loan_file_id=lf.id, run_id=uuid4(), company_id=lf.company_id
        )

    assert snap.mismo.absent is True
    assert snap.mismo.reason == "mismo assembler raised RuntimeError"  # PII-safe, class only
    assert "boom" not in (snap.mismo.reason or "")  # the message is NOT leaked
    # The other sections are unaffected.
    assert snap.documents.is_present and len(snap.documents.entries) == 1
    assert snap.calculations.is_present


async def test_build_is_stateless_and_deterministic(db_session: AsyncSession) -> None:
    lf = await _complete_loan_file(db_session)
    run_id = uuid4()
    a = await build_snapshot(
        db_session, loan_file_id=lf.id, run_id=run_id, company_id=lf.company_id
    )
    b = await build_snapshot(
        db_session, loan_file_id=lf.id, run_id=run_id, company_id=lf.company_id
    )
    # Equivalent modulo created_at — sections rebuild identically (no caching, no mutation).
    assert a.mismo == b.mismo
    assert a.documents == b.documents
    assert a.calculations == b.calculations
    assert a.run_id == b.run_id == run_id


async def test_run_id_is_received_not_minted(db_session: AsyncSession) -> None:
    lf = await _complete_loan_file(db_session, with_documents=False)
    run_id = uuid4()
    snap = await build_snapshot(
        db_session, loan_file_id=lf.id, run_id=run_id, company_id=lf.company_id
    )
    assert snap.run_id == run_id  # stamped exactly as received


async def test_snapshot_is_frozen(db_session: AsyncSession) -> None:
    lf = await _complete_loan_file(db_session, with_documents=False)
    snap = await build_snapshot(
        db_session, loan_file_id=lf.id, run_id=uuid4(), company_id=lf.company_id
    )
    with pytest.raises(ValidationError):
        snap.run_id = uuid4()


async def test_unknown_loan_file_raises(db_session: AsyncSession) -> None:
    with pytest.raises(LoanFileNotFound):
        await build_snapshot(db_session, loan_file_id=uuid4(), run_id=uuid4(), company_id=uuid4())


async def test_loan_file_of_another_company_is_not_found(db_session: AsyncSession) -> None:
    """The builder is company-scoped: a file from another tenant does not resolve."""
    lf = await _complete_loan_file(db_session, with_documents=False)
    with pytest.raises(LoanFileNotFound):
        await build_snapshot(
            db_session,
            loan_file_id=lf.id,
            run_id=uuid4(),
            company_id=uuid4(),  # wrong company
        )


async def test_nil_run_id_is_rejected(db_session: AsyncSession) -> None:
    """A nil UUID run_id (the 'forgot to set it' sentinel) is a caller error."""
    from uuid import UUID

    lf = await _complete_loan_file(db_session, with_documents=False)
    with pytest.raises(ValueError, match="run_id"):
        await build_snapshot(
            db_session, loan_file_id=lf.id, run_id=UUID(int=0), company_id=lf.company_id
        )


async def test_content_ids_are_stable_across_rebuilds(db_session: AsyncSession) -> None:
    """LP-312: building the SAME file twice (different runs) yields identical content_ids —
    they are content-derived and run-independent, not fresh per build."""
    lf = await _complete_loan_file(db_session)
    first = await build_snapshot(
        db_session, loan_file_id=lf.id, run_id=uuid4(), company_id=lf.company_id
    )
    second = await build_snapshot(
        db_session, loan_file_id=lf.id, run_id=uuid4(), company_id=lf.company_id
    )
    first_ids = [e.content_id for e in first.documents.entries]
    second_ids = [e.content_id for e in second.documents.entries]
    assert first_ids and first_ids == second_ids
    assert all(cid.startswith("doc") for cid in first_ids)


async def test_document_content_id_is_independent_of_other_documents(
    db_session: AsyncSession,
) -> None:
    """LP-312: adding another document must NOT change an existing document's content_id
    (position-independence through the real DB build path)."""
    lf = await _complete_loan_file(db_session)
    before = await build_snapshot(
        db_session, loan_file_id=lf.id, run_id=uuid4(), company_id=lf.company_id
    )
    original_id = before.documents.entries[0].content_id

    # Add a second, different document, then rebuild.
    doc = Document(
        loan_file_id=lf.id,
        original_filename="w2.pdf",
        mime_type="application/pdf",
        file_size_bytes=1,
        storage_path="lf/w2.pdf",
        upload_source=UploadSource.USER_UPLOAD,
        document_type="w2",
    )
    db_session.add(doc)
    await db_session.flush()
    await create_extraction_version(
        db_session,
        document_id=doc.id,
        extracted_data={"employer_name": {"value": "Acme", "source": None, "confidence": 0.9}},
        extraction_status=ExtractionStatus.SUCCEEDED,
    )
    await db_session.flush()

    after = await build_snapshot(
        db_session, loan_file_id=lf.id, run_id=uuid4(), company_id=lf.company_id
    )
    surviving = {e.content_id for e in after.documents.entries}
    assert original_id in surviving  # the original document's id is unchanged
    assert len(after.documents.entries) == 2
