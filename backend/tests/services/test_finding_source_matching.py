"""Tests for finding source-document SET matching (LP-114.1).

A cross-source finding names ALL the documents it derived from (an employer on a pay stub AND a
W-2), by value-matching its distinctive cited value(s) to every document that contains them —
honest by construction (a common token that only coincides does NOT over-include a document).
"""

from uuid import uuid4

from app.core.security import hash_password
from app.models import Company, User, UserRole
from app.models.document import Document, DocumentStatus
from app.models.extraction import ExtractionStatus
from app.models.finding import Finding, FindingCategory, FindingOrigin, FindingStatus
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.schemas.verification import FindingPublic
from app.services.extractions import create_extraction_version
from app.services.finding_source_matching import (
    distinctive_values,
    populate_finding_source_documents,
)
from app.services.loan_files import create_loan_file
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


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


async def _doc(db: AsyncSession, lf: LoanFile, *, name: str, doc_type: str, data: dict) -> Document:
    doc = Document(
        id=uuid4(),
        loan_file_id=lf.id,
        original_filename=name,
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path=f"{lf.company_id}/{lf.id}/{name}",
        document_type=doc_type,
        status=DocumentStatus.COMPLETED,
        upload_source="user_upload",
    )
    db.add(doc)
    await db.flush()
    await create_extraction_version(
        db, document_id=doc.id, extracted_data=data, extraction_status=ExtractionStatus.SUCCEEDED
    )
    return doc


def _finding(
    lf: LoanFile, *, document_value=None, snippet=None, category=FindingCategory.CROSS_SOURCE
) -> Finding:
    # Default category is CROSS_SOURCE (unconstrained — matches any document category).
    return Finding(
        loan_file_id=lf.id,
        rule_id="xsrc.income.employer_name_consistency",
        origin=FindingOrigin.DETERMINISTIC_RULE,
        status=FindingStatus.YELLOW,
        category=category,
        message="m",
        confidence=1.0,
        details={"document_value": document_value} if document_value else {},
        source_snippet=snippet,
    )


# --------------------------------------------------------------------------- #
# distinctive_values — precision (keys on the specific value, not common tokens)
# --------------------------------------------------------------------------- #


def test_distinctive_values_keeps_specific_drops_common(db_session) -> None:
    lf = LoanFile(company_id=uuid4())
    # A multi-word employer name is distinctive; a lone common word is not.
    assert "novant health" in distinctive_values(_finding(lf, document_value="Novant Health"))
    assert distinctive_values(_finding(lf, document_value="Bank")) == []  # lone stopword → dropped
    # amounts + addresses + account fragments come off the snippet.
    vals = distinctive_values(
        _finding(
            lf, snippet="Ending balance $2,512.79; 4415 OVERLOOK COVE RD CHARLOTTE NC; ...6684"
        )
    )
    assert "2512.79" in vals
    assert any("overlook cove" in v for v in vals)
    assert "6684" in vals


# --------------------------------------------------------------------------- #
# populate — the multi-document SET (the LP-114.1 headline)
# --------------------------------------------------------------------------- #


async def test_employer_finding_names_all_containing_documents(db_session: AsyncSession) -> None:
    # "Novant Health" is on BOTH a pay stub and a W-2 → the finding's source is the SET (not one,
    # not null — the exact case LP-114's single-FK nulled out).
    lf = await _loan_file(db_session)
    paystub = await _doc(
        db_session,
        lf,
        name="paystub.pdf",
        doc_type="pay_stub",
        data={"employer_name": {"value": "Novant Health"}},
    )
    w2 = await _doc(
        db_session,
        lf,
        name="w2.pdf",
        doc_type="w2",
        data={"employer_name": {"value": "Novant Health"}},
    )
    # An unrelated document must NOT be included.
    await _doc(
        db_session,
        lf,
        name="bank.pdf",
        doc_type="bank_statement",
        data={"bank_name": {"value": "Wells Fargo"}},
    )
    finding = _finding(lf, document_value="Novant Health", category=FindingCategory.INCOME)
    db_session.add(finding)
    await db_session.flush()

    await populate_finding_source_documents(db_session, loan_file_id=lf.id)
    assert set(finding.source_document_ids or []) == {str(paystub.id), str(w2.id)}
    assert finding.source_document_id in (paystub.id, w2.id)  # a primary is promoted (back-compat)


async def test_category_guard_excludes_off_category_documents(db_session: AsyncSession) -> None:
    # The precision case you flagged: an employer (INCOME) finding's value "Bank of America" appears
    # on a pay stub (employer) AND a savings statement (bank name) — but only the INCOME document is a
    # source; the ASSETS document is a coincidental name, not over-included.
    lf = await _loan_file(db_session)
    paystub = await _doc(
        db_session,
        lf,
        name="paystub.pdf",
        doc_type="pay_stub",
        data={"employer_name": {"value": "Bank of America"}},
    )
    await _doc(
        db_session,
        lf,
        name="savings.pdf",
        doc_type="bank_statement",
        data={"bank_name": {"value": "Bank of America"}},  # same name, wrong role
    )
    finding = _finding(lf, document_value="Bank of America", category=FindingCategory.INCOME)
    db_session.add(finding)
    await db_session.flush()

    await populate_finding_source_documents(db_session, loan_file_id=lf.id)
    assert finding.source_document_ids == [str(paystub.id)]  # the savings statement is NOT included


async def test_unique_value_names_one_document(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session)
    lic = await _doc(
        db_session,
        lf,
        name="DL Bansari.pdf",
        doc_type="drivers_license",
        data={"address": {"value": "4415 OVERLOOK COVE RD CHARLOTTE, NC 28216-7769"}},
    )
    await _doc(db_session, lf, name="other.pdf", doc_type="w2", data={"employer": {"value": "X"}})
    finding = _finding(
        lf, snippet="lists the address 4415 OVERLOOK COVE RD CHARLOTTE, NC 28216-7769"
    )
    db_session.add(finding)
    await db_session.flush()

    await populate_finding_source_documents(db_session, loan_file_id=lf.id)
    assert finding.source_document_ids == [str(lic.id)]


async def test_no_cited_value_is_empty_and_graceful(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session)
    await _doc(db_session, lf, name="x.pdf", doc_type="w2", data={"a": {"value": "b"}})
    finding = _finding(lf)  # no document_value, no snippet
    db_session.add(finding)
    await db_session.flush()
    await populate_finding_source_documents(db_session, loan_file_id=lf.id)
    assert finding.source_document_ids is None  # graceful — no broken/guessed source


async def test_common_token_does_not_over_include(db_session: AsyncSession) -> None:
    # The precision discipline: matching keys on the DISTINCTIVE value, so a document that merely
    # contains a common word ("bank") is not wrongly attributed.
    lf = await _loan_file(db_session)
    await _doc(
        db_session,
        lf,
        name="unrelated.pdf",
        doc_type="bank_statement",
        data={"note": {"value": "your bank account statement"}},
    )
    finding = _finding(lf, document_value="Bank")  # lone stopword → no distinctive value
    db_session.add(finding)
    await db_session.flush()
    await populate_finding_source_documents(db_session, loan_file_id=lf.id)
    assert finding.source_document_ids is None  # not over-included on a coincidental common token


# --------------------------------------------------------------------------- #
# Expose — FindingPublic names the whole set
# --------------------------------------------------------------------------- #


async def test_finding_public_exposes_source_documents_set(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session)
    a = await _doc(
        db_session,
        lf,
        name="paystub.pdf",
        doc_type="pay_stub",
        data={"employer_name": {"value": "Novant Health"}},
    )
    b = await _doc(
        db_session,
        lf,
        name="w2.pdf",
        doc_type="w2",
        data={"employer_name": {"value": "Novant Health"}},
    )
    finding = _finding(lf, document_value="Novant Health")
    db_session.add(finding)
    await db_session.flush()
    await populate_finding_source_documents(db_session, loan_file_id=lf.id)

    loaded = await db_session.scalar(
        only_active(select(Finding).where(Finding.id == finding.id), Finding)
    )
    names = {a.id: a.original_filename, b.id: b.original_filename}
    public = FindingPublic.from_model(loaded, document_names=names)
    assert {d.filename for d in public.source_documents} == {"paystub.pdf", "w2.pdf"}
