"""Tests for the Finding model (LP-17).

Covers the verification-result record against a real table: field round-tripping,
the resolution_status default (OPEN), the three enum CHECK constraints
(status/category/resolution_status), rule_id as a flexible dotted string, the
details JSON, the nullable source_document linkage, relationships, multiple
findings per file, soft delete, and tenant isolation (findings reachable only
through the owning company's loan files, since they have no company_id).

The resolution helper is exercised in ``tests/services/test_findings.py``.

Uses the transaction-rollback ``db_session`` fixture from LP-10.
"""

from typing import Any

import pytest
from app.models import (
    Company,
    Document,
    Finding,
    FindingCategory,
    FindingResolutionStatus,
    FindingStatus,
    LoanFile,
    UploadSource,
    User,
    UserRole,
    only_active,
    scope_to_company,
    utcnow,
)
from app.services.loan_files import create_loan_file
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def _make_company(db_session: AsyncSession, slug: str) -> Company:
    company = Company(name=slug.title(), slug=slug)
    db_session.add(company)
    await db_session.flush()
    return company


async def _make_user(db_session: AsyncSession, company: Company, email: str) -> User:
    user = User(
        company_id=company.id,
        email=email,
        hashed_password="h",
        first_name="Re",
        last_name="Solver",
        role=UserRole.PROCESSOR,
    )
    db_session.add(user)
    await db_session.flush()
    return user


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


async def _add_finding(
    db_session: AsyncSession,
    loan_file: LoanFile,
    *,
    rule_id: str = "income.paystub_recency",
    status: FindingStatus = FindingStatus.YELLOW,
    category: FindingCategory = FindingCategory.INCOME,
    message: str = "Pay stub is older than 30 days.",
    details: dict[str, Any] | None = None,
    source_document_id: object = None,
) -> Finding:
    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id=rule_id,
        status=status,
        category=category,
        message=message,
        details=details if details is not None else {},
        source_document_id=source_document_id,
    )
    db_session.add(finding)
    await db_session.flush()
    return finding


async def test_create_finding_with_fields(db_session: AsyncSession) -> None:
    """A finding persists its rule, status, category, message, and details."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    document = await _make_document(db_session, loan_file)
    finding = await _add_finding(
        db_session,
        loan_file,
        rule_id="cross_source.income_consistency",
        status=FindingStatus.RED,
        category=FindingCategory.CROSS_SOURCE,
        message="Stated income differs from documents by 15%.",
        details={"stated": 16400, "verified": 14200, "variance_pct": 0.15},
        source_document_id=document.id,
    )

    await db_session.refresh(finding)
    assert finding.rule_id == "cross_source.income_consistency"
    assert finding.status is FindingStatus.RED
    assert finding.category is FindingCategory.CROSS_SOURCE
    assert finding.message == "Stated income differs from documents by 15%."
    assert finding.source_document_id == document.id


async def test_resolution_status_defaults_to_open(db_session: AsyncSession) -> None:
    """A new finding is OPEN with an empty resolution trail."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    finding = await _add_finding(db_session, loan_file)

    await db_session.refresh(finding)
    assert finding.resolution_status is FindingResolutionStatus.OPEN
    assert finding.resolution_note is None
    assert finding.resolved_by_user_id is None
    assert finding.resolved_at is None
    # verification_id is unset until a verification run populates it (LP-18).
    assert finding.verification_id is None


async def test_rule_id_is_a_flexible_dotted_string(db_session: AsyncSession) -> None:
    """rule_id accepts any dotted-namespace string — it is not an enum."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    for rule_id in ("income.paystub_recency", "fha.mip_required", "documentation.missing_w2_2023"):
        finding = await _add_finding(db_session, loan_file, rule_id=rule_id)
        await db_session.refresh(finding)
        assert finding.rule_id == rule_id


async def test_details_round_trips_structured_json(db_session: AsyncSession) -> None:
    """details stores and retrieves a structured dict."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    details = {"stated": 16400, "verified": 14200, "variance_pct": 0.15, "sources": ["w2", "voe"]}
    finding = await _add_finding(db_session, loan_file, details=details)

    await db_session.refresh(finding)
    assert finding.details == details
    assert finding.details["sources"] == ["w2", "voe"]


async def test_status_check_constraint_rejects_invalid_value(db_session: AsyncSession) -> None:
    """The DB CHECK constraint rejects an out-of-range status."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    finding = await _add_finding(db_session, loan_file)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE findings SET status = :bad WHERE id = :id"),
                {"bad": "orange", "id": finding.id},
            )


async def test_category_check_constraint_rejects_invalid_value(db_session: AsyncSession) -> None:
    """The DB CHECK constraint rejects an out-of-range category."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    finding = await _add_finding(db_session, loan_file)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE findings SET category = :bad WHERE id = :id"),
                {"bad": "vibes", "id": finding.id},
            )


async def test_resolution_status_check_constraint_rejects_invalid_value(
    db_session: AsyncSession,
) -> None:
    """The DB CHECK constraint rejects an out-of-range resolution_status."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    finding = await _add_finding(db_session, loan_file)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE findings SET resolution_status = :bad WHERE id = :id"),
                {"bad": "ignored", "id": finding.id},
            )


async def test_all_enum_values_accepted(db_session: AsyncSession) -> None:
    """Every status, category, and resolution_status value is valid."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    for status in FindingStatus:
        for category in FindingCategory:
            finding = await _add_finding(db_session, loan_file, status=status, category=category)
            await db_session.refresh(finding)
            assert finding.status is status
            assert finding.category is category


async def test_file_level_finding_has_null_source_document(db_session: AsyncSession) -> None:
    """A file-level finding has no source document; a document finding links one."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    document = await _make_document(db_session, loan_file)

    file_level = await _add_finding(db_session, loan_file, source_document_id=None)
    doc_level = await _add_finding(db_session, loan_file, source_document_id=document.id)

    await db_session.refresh(file_level)
    await db_session.refresh(doc_level)
    assert file_level.source_document_id is None
    assert doc_level.source_document_id == document.id


async def test_relationships_load(db_session: AsyncSession) -> None:
    """finding.loan_file, source_document, resolved_by, and loan_file.findings load."""
    company = await _make_company(db_session, "acme")
    user = await _make_user(db_session, company, "u@acme.test")
    loan_file = await _make_loan_file(db_session, company)
    document = await _make_document(db_session, loan_file)
    finding = await _add_finding(db_session, loan_file, source_document_id=document.id)
    finding.resolved_by_user_id = user.id
    await db_session.flush()

    stmt = (
        select(Finding)
        .where(Finding.id == finding.id)
        .options(
            selectinload(Finding.loan_file),
            selectinload(Finding.source_document),
            selectinload(Finding.resolved_by),
        )
    )
    loaded = (await db_session.scalars(stmt)).one()
    assert loaded.loan_file.id == loan_file.id
    assert loaded.source_document is not None
    assert loaded.source_document.id == document.id
    assert loaded.resolved_by is not None
    assert loaded.resolved_by.id == user.id

    file_stmt = (
        select(LoanFile).where(LoanFile.id == loan_file.id).options(selectinload(LoanFile.findings))
    )
    loaded_file = (await db_session.scalars(file_stmt)).one()
    assert finding.id in {f.id for f in loaded_file.findings}


async def test_multiple_findings_per_loan_file(db_session: AsyncSession) -> None:
    """loan_file.findings returns every finding attached to the file."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    f1 = await _add_finding(db_session, loan_file, rule_id="income.paystub_recency")
    f2 = await _add_finding(db_session, loan_file, rule_id="assets.large_deposit")
    f3 = await _add_finding(db_session, loan_file, rule_id="property.appraisal_low")

    stmt = (
        select(LoanFile).where(LoanFile.id == loan_file.id).options(selectinload(LoanFile.findings))
    )
    loaded = (await db_session.scalars(stmt)).one()
    assert {f.id for f in loaded.findings} == {f1.id, f2.id, f3.id}


async def test_soft_delete_and_only_active(db_session: AsyncSession) -> None:
    """Soft delete sets deleted_at; only_active() filters the finding out."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    live = await _add_finding(db_session, loan_file, rule_id="income.live")
    gone = await _add_finding(db_session, loan_file, rule_id="income.gone")

    gone.deleted_at = utcnow()
    await db_session.flush()
    assert gone.is_deleted is True

    stmt = only_active(select(Finding), Finding)
    ids = {f.id for f in (await db_session.scalars(stmt)).all()}
    assert live.id in ids
    assert gone.id not in ids


async def test_findings_are_isolated_by_company_through_their_loan_file(
    db_session: AsyncSession,
) -> None:
    """Findings carry no company_id; isolation is transitive via the loan file."""
    company_a = await _make_company(db_session, "company-a")
    company_b = await _make_company(db_session, "company-b")
    file_a = await _make_loan_file(db_session, company_a)
    file_b = await _make_loan_file(db_session, company_b)

    finding_a = await _add_finding(db_session, file_a, rule_id="income.a")
    finding_b = await _add_finding(db_session, file_b, rule_id="income.b")

    stmt_a = scope_to_company(
        select(Finding).join(LoanFile, Finding.loan_file_id == LoanFile.id),
        LoanFile,
        company_a.id,
    )
    ids_a = {f.id for f in (await db_session.scalars(stmt_a)).all()}
    assert ids_a == {finding_a.id}
    assert finding_b.id not in ids_a

    stmt_b = scope_to_company(
        select(Finding).join(LoanFile, Finding.loan_file_id == LoanFile.id),
        LoanFile,
        company_b.id,
    )
    ids_b = {f.id for f in (await db_session.scalars(stmt_b)).all()}
    assert ids_b == {finding_b.id}
    assert ids_a.isdisjoint(ids_b)
