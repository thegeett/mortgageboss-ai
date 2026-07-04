"""Tests for finding source-document capture + exposure (LP-114).

A finding NAMES which document grounds it: deterministic findings FORWARD the document_id already
in their fact's source_location (previously dropped); AI cross-source findings RESOLVE their type
string to a unique document or stay NULL (never a wrong guess); FindingPublic exposes the id +
filename.
"""

from uuid import uuid4

from app.ai.cross_source import CrossSourceRawFinding
from app.core.security import hash_password
from app.models import Company, User, UserRole
from app.models.document import Document, DocumentStatus
from app.models.finding import Finding, FindingCategory, FindingOrigin, FindingStatus
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.schemas.verification import FindingPublic
from app.services.cross_source import (
    _normalize_doc_type,
    _to_finding,
    _unique_type_document_map,
)
from app.services.loan_files import create_loan_file
from app.services.verification_engine import _source_location_fields
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def _loan_file(db: AsyncSession, *, slug: str = "acme") -> LoanFile:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    db.add(
        User(
            company_id=company.id,
            email=f"u@{slug}.com",
            hashed_password=hash_password("x"),
            first_name="T",
            last_name="U",
            role=UserRole.PROCESSOR,
            is_active=True,
        )
    )
    await db.flush()
    return await create_loan_file(db, company_id=company.id)


async def _document(db: AsyncSession, lf: LoanFile, *, document_type: str, name: str) -> Document:
    doc = Document(
        id=uuid4(),
        loan_file_id=lf.id,
        original_filename=name,
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path=f"{lf.company_id}/{lf.id}/{name}",
        document_type=document_type,
        status=DocumentStatus.COMPLETED,
        upload_source="user_upload",
    )
    db.add(doc)
    await db.flush()
    return doc


def _raw(**kw: object) -> CrossSourceRawFinding:
    base: dict = {
        "type": "income_variance",
        "description": "A discrepancy",
        "stated_value": None,
        "document_value": None,
        "source_document": None,
        "page": None,
        "snippet": None,
        "confidence": 0.8,
        "reasoning": "because",
    }
    base.update(kw)
    return CrossSourceRawFinding(**base)


# --------------------------------------------------------------------------- #
# Deterministic — forward the document_id source_location already carries
# --------------------------------------------------------------------------- #


def test_source_location_forwards_document_id() -> None:
    doc_id = uuid4()
    document_id, page, snippet = _source_location_fields(
        {"document_id": str(doc_id), "page": 2, "snippet": "Gross pay 3,775.00"}
    )
    assert document_id == doc_id  # previously DROPPED — now forwarded
    assert page == 2 and snippet == "Gross pay 3,775.00"


def test_source_location_null_and_malformed_are_graceful() -> None:
    assert _source_location_fields(None) == (None, None, None)
    assert _source_location_fields({"page": 3}) == (None, 3, None)  # no document_id → None
    # A malformed id → None (never a wrong link), page/snippet still forwarded.
    assert _source_location_fields({"document_id": "not-a-uuid", "page": 1}) == (None, 1, None)


# --------------------------------------------------------------------------- #
# AI cross-source — resolve type→unique document, else NULL (no guess)
# --------------------------------------------------------------------------- #


def test_normalize_doc_type() -> None:
    assert _normalize_doc_type("W2") == "w2"
    assert _normalize_doc_type("Bank Statement") == "bank_statement"
    assert _normalize_doc_type("  pay-stub ") == "pay_stub"


async def test_unique_type_document_map_only_unambiguous(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session)
    payslip = await _document(db_session, lf, document_type="pay_stub", name="April paystub.pdf")
    await _document(db_session, lf, document_type="bank_statement", name="BofA 1.pdf")
    await _document(
        db_session, lf, document_type="bank_statement", name="BofA 2.pdf"
    )  # 2 → ambiguous

    mapping = await _unique_type_document_map(db_session, lf.id)
    assert mapping["pay_stub"] == payslip.id  # exactly one → resolvable
    assert "bank_statement" not in mapping  # two of a type → omitted (won't guess)


def test_ai_finding_resolves_unique_type_else_null() -> None:
    lf_id, run_id, doc_id = uuid4(), uuid4(), uuid4()
    mapping = {"pay_stub": doc_id}

    resolved = _to_finding(
        _raw(source_document="Pay-Stub"),  # normalizes to pay_stub → unique
        loan_file_id=lf_id,
        run_id=run_id,
        income_target=None,
        source_doc_by_type=mapping,
    )
    assert resolved.source_document_id == doc_id

    # An unmapped / ambiguous / absent type → NULL (honest, no wrong link).
    for raw in (_raw(source_document="bank_statement"), _raw(source_document=None)):
        finding = _to_finding(
            raw, loan_file_id=lf_id, run_id=run_id, income_target=None, source_doc_by_type=mapping
        )
        assert finding.source_document_id is None


# --------------------------------------------------------------------------- #
# Expose — FindingPublic names the source document
# --------------------------------------------------------------------------- #


async def test_finding_public_exposes_source_document(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session)
    doc = await _document(db_session, lf, document_type="bank_statement", name="KASHS BANK.pdf")
    finding = Finding(
        loan_file_id=lf.id,
        rule_id="cross_source.income_variance",
        origin=FindingOrigin.AI_CROSS_SOURCE,
        status=FindingStatus.YELLOW,
        category=FindingCategory.CROSS_SOURCE,
        message="m",
        confidence=0.8,
        details={},
        source_document_id=doc.id,
        source_page=1,
    )
    db_session.add(finding)
    await db_session.flush()

    loaded = await db_session.scalar(
        only_active(
            select(Finding)
            .where(Finding.id == finding.id)
            .options(selectinload(Finding.source_document)),
            Finding,
        )
    )
    assert loaded is not None
    public = FindingPublic.from_model(loaded)
    assert public.source_document_id == doc.id
    assert public.source_document_filename == "KASHS BANK.pdf"  # the readable name


async def test_finding_public_graceful_when_no_source_document(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session)
    finding = Finding(
        loan_file_id=lf.id,
        rule_id="conv.dti.max",
        origin=FindingOrigin.DETERMINISTIC_RULE,
        status=FindingStatus.RED,
        category=FindingCategory.CROSS_SOURCE,
        message="m",
        confidence=1.0,
        details={},
        source_page=None,
    )
    db_session.add(finding)
    await db_session.flush()
    loaded = await db_session.scalar(
        only_active(
            select(Finding)
            .where(Finding.id == finding.id)
            .options(selectinload(Finding.source_document)),
            Finding,
        )
    )
    assert loaded is not None
    public = FindingPublic.from_model(loaded)
    assert public.source_document_id is None
    assert public.source_document_filename is None  # graceful — no broken "Source:"
