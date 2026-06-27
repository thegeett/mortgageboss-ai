"""Tests for the document-findings service (LP-66) — the shared recording + query.

Covers the Finding model + the shared ``create_document_finding`` (source-linked,
flexible details), the divorce-decree → findings wiring (closing the LP-63 loop;
uniform with the analyzer's findings), and the tenant-scoped query (a finding is
reachable only via its company's loan file).
"""

from decimal import Decimal
from uuid import uuid4

from app.ai.extraction.divorce_decree import DivorceDecreeExtraction, SupportObligation
from app.core.security import hash_password
from app.models import Company, User, UserRole
from app.models.document import Document, DocumentStatus
from app.models.document_finding import DocumentFindingStatus, DocumentFindingType
from app.services.document_findings import (
    create_document_finding,
    list_findings_for_loan_file,
    record_findings_from_extraction,
)
from app.services.loan_files import create_loan_file
from sqlalchemy.ext.asyncio import AsyncSession

PDF = b"%PDF-1.7 dummy"


async def _make_document(db: AsyncSession, *, slug: str) -> Document:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u@{slug}.com",
        hashed_password=hash_password("x"),
        first_name="T",
        last_name="U",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    loan_file = await create_loan_file(db, company_id=company.id)
    doc = Document(
        id=uuid4(),
        loan_file_id=loan_file.id,
        original_filename="x.pdf",
        mime_type="application/pdf",
        file_size_bytes=len(PDF),
        storage_path=f"{company.id}/{loan_file.id}/x.pdf",
        status=DocumentStatus.PENDING,
        upload_source="user_upload",
        uploaded_by_user_id=user.id,
    )
    db.add(doc)
    await db.flush()
    return doc


async def test_create_finding_source_linked_with_typed_fields(db_session: AsyncSession) -> None:
    doc = await _make_document(db_session, slug="acme")
    finding = await create_document_finding(
        db_session,
        document=doc,
        finding_type=DocumentFindingType.OBLIGATION,
        description="child support obligation (monthly)",
        amount=Decimal("1200.00"),
        frequency="monthly",
        details={"payer": "John Doe"},
    )
    assert finding.document_id == doc.id  # source-linked to the document
    assert finding.finding_type is DocumentFindingType.OBLIGATION
    assert finding.amount == Decimal("1200.00")
    assert finding.frequency == "monthly"
    assert finding.status is DocumentFindingStatus.OPEN  # default
    assert finding.details["payer"] == "John Doe"


async def test_flexible_details_for_a_non_obligation_finding(db_session: AsyncSession) -> None:
    """A finding with a different shape (a property interest with an address) works."""
    doc = await _make_document(db_session, slug="acme")
    finding = await create_document_finding(
        db_session,
        document=doc,
        finding_type=DocumentFindingType.PROPERTY_INTEREST,
        description="Interest in 123 Main St awarded by the decree",
        details={"address": "123 Main St", "awarded_to": "the borrower"},
    )
    assert finding.amount is None and finding.frequency is None  # not all findings have these
    assert finding.details["address"] == "123 Main St"


async def test_divorce_decree_wiring_records_uniform_findings(db_session: AsyncSession) -> None:
    """LP-63 loop closed: a divorce decree's obligations → findings via the SAME path."""
    doc = await _make_document(db_session, slug="acme")
    doc.document_type = "divorce_decree"
    data = DivorceDecreeExtraction(
        support_obligations=[
            SupportObligation(
                obligation_type="child_support",
                amount=Decimal("1200.00"),
                frequency="monthly",
                payer="John Doe",
            ),
            SupportObligation(
                obligation_type="alimony", amount=Decimal("800.00"), frequency="monthly"
            ),
        ]
    )

    count = await record_findings_from_extraction(db_session, doc, data)
    assert count == 2

    findings = await list_findings_for_loan_file(db_session, loan_file_id=doc.loan_file_id)
    assert len(findings) == 2
    # Uniform DocumentFinding shape — same as the Tier 3 analyzer would produce.
    types = {f.finding_type for f in findings}
    assert types == {DocumentFindingType.OBLIGATION}
    cs = next(f for f in findings if f.details.get("obligation_type") == "child_support")
    assert cs.amount == Decimal("1200.00") and cs.frequency == "monthly"
    assert cs.details["payer"] == "John Doe" and cs.details["source"] == "divorce_decree"


async def test_non_finding_extraction_records_nothing(db_session: AsyncSession) -> None:
    """An extraction type with no findings mapping records nothing (no crash)."""
    doc = await _make_document(db_session, slug="acme")
    doc.document_type = "pay_stub"
    from app.ai.extraction.pay_stub import PayStubExtraction

    count = await record_findings_from_extraction(db_session, doc, PayStubExtraction())
    assert count == 0


async def test_findings_are_tenant_scoped_via_loan_file(db_session: AsyncSession) -> None:
    """A finding is reachable only via its OWN company's loan file (isolation)."""
    doc_a = await _make_document(db_session, slug="acme")
    doc_b = await _make_document(db_session, slug="globex")
    await create_document_finding(
        db_session,
        document=doc_a,
        finding_type=DocumentFindingType.OTHER,
        description="A-only finding",
    )

    a_findings = await list_findings_for_loan_file(db_session, loan_file_id=doc_a.loan_file_id)
    b_findings = await list_findings_for_loan_file(db_session, loan_file_id=doc_b.loan_file_id)
    assert len(a_findings) == 1 and a_findings[0].description == "A-only finding"
    assert b_findings == []  # company B's loan file sees none of A's findings
