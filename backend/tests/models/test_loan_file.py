"""Tests for the LoanFile model and create_loan_file service (LP-13).

Covers the three-identifier design (ADR-036) end-to-end against a real table:
creation via the service, identifier format/uniqueness, the inbox address
helper, status default and lifecycle enum, nullability of optional loan
attributes, the company/lender relationships, soft delete, tenant isolation,
and the enum CHECK constraints rejecting out-of-range values at the DB level.

Uses the transaction-rollback ``db_session`` fixture from LP-10.
"""

from decimal import Decimal

import pytest
from app.models import (
    Company,
    Lender,
    LoanFile,
    LoanFileStatus,
    LoanProgram,
    LoanPurpose,
    only_active,
    scope_to_company,
    utcnow,
)
from app.models.loan_file import INBOX_DOMAIN
from app.services.loan_file_ids import DISPLAY_ALPHABET, DISPLAY_PREFIX
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


async def _make_lender(db_session: AsyncSession, company: Company, slug: str) -> Lender:
    lender = Lender(company_id=company.id, name=slug.upper(), slug=slug)
    db_session.add(lender)
    await db_session.flush()
    return lender


async def test_create_loan_file_sets_identifiers_and_defaults(
    db_session: AsyncSession,
) -> None:
    """create_loan_file populates both identifiers and defaults status to DRAFT."""
    company = await _make_company(db_session, "acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    await db_session.refresh(loan_file)

    assert loan_file.id is not None
    assert loan_file.company_id == company.id

    # Display ID: 'LF-' + 4 chars from the unambiguous alphabet.
    assert loan_file.display_id.startswith(DISPLAY_PREFIX)
    code = loan_file.display_id.removeprefix(DISPLAY_PREFIX)
    assert len(code) == 4
    assert all(char in DISPLAY_ALPHABET for char in code)

    # Inbox token is populated, non-trivial, and independent of the display id.
    assert loan_file.inbox_token
    assert len(loan_file.inbox_token) >= 16
    assert loan_file.display_id not in loan_file.inbox_token
    assert code not in loan_file.inbox_token

    # Status defaults to DRAFT; optional attributes are null at creation.
    assert loan_file.status is LoanFileStatus.DRAFT
    assert loan_file.lender_id is None
    assert loan_file.loan_program is None
    assert loan_file.loan_purpose is None
    assert loan_file.loan_amount is None
    assert loan_file.loan_officer_name is None
    assert loan_file.loan_officer_email is None
    assert loan_file.deleted_at is None


async def test_get_inbox_address_format(db_session: AsyncSession) -> None:
    """get_inbox_address() returns lf-{token}@{INBOX_DOMAIN}."""
    company = await _make_company(db_session, "acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    assert loan_file.get_inbox_address() == f"lf-{loan_file.inbox_token}@{INBOX_DOMAIN}"
    assert loan_file.get_inbox_address().endswith("@inbox.mortgageboss.ai")


async def test_identifiers_are_unique_across_files(db_session: AsyncSession) -> None:
    """Many files created in a company all get distinct display IDs and tokens."""
    company = await _make_company(db_session, "acme")
    files = [await create_loan_file(db_session, company_id=company.id) for _ in range(25)]

    display_ids = {f.display_id for f in files}
    inbox_tokens = {f.inbox_token for f in files}
    assert len(display_ids) == 25
    assert len(inbox_tokens) == 25


async def test_display_id_unique_constraint_enforced(db_session: AsyncSession) -> None:
    """The DB rejects a duplicate display_id (the safety-net unique constraint)."""
    company = await _make_company(db_session, "acme")
    first = await create_loan_file(db_session, company_id=company.id)

    # Hand-construct a second file reusing the first display_id -> must fail.
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            dup = LoanFile(
                display_id=first.display_id,
                inbox_token="a-different-token-value",
                company_id=company.id,
                status=LoanFileStatus.DRAFT,
            )
            db_session.add(dup)
            await db_session.flush()


async def test_optional_loan_attributes_can_be_set(db_session: AsyncSession) -> None:
    """loan_program/purpose/amount are null at creation but can be set later."""
    company = await _make_company(db_session, "acme")
    loan_file = await create_loan_file(
        db_session,
        company_id=company.id,
        loan_program=LoanProgram.FHA,
        loan_purpose=LoanPurpose.PURCHASE,
        loan_officer_name="Dana Lo",
        loan_officer_email="dana@originator.test",
    )

    loan_file.loan_amount = Decimal("450000.00")
    await db_session.flush()
    await db_session.refresh(loan_file)

    assert loan_file.loan_program is LoanProgram.FHA
    assert loan_file.loan_purpose is LoanPurpose.PURCHASE
    assert loan_file.loan_amount == Decimal("450000.00")
    assert loan_file.loan_officer_name == "Dana Lo"
    assert loan_file.loan_officer_email == "dana@originator.test"


async def test_status_can_advance_through_lifecycle(db_session: AsyncSession) -> None:
    """Status can move to other lifecycle values (any-to-any in V1, ADR-049)."""
    company = await _make_company(db_session, "acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    loan_file.status = LoanFileStatus.IN_PROCESSING
    await db_session.flush()
    await db_session.refresh(loan_file)
    assert loan_file.status is LoanFileStatus.IN_PROCESSING


async def test_lender_can_be_linked(db_session: AsyncSession) -> None:
    """lender_id is null by default and can reference a lender."""
    company = await _make_company(db_session, "acme")
    lender = await _make_lender(db_session, company, "uwm")

    loan_file = await create_loan_file(db_session, company_id=company.id, lender_id=lender.id)
    await db_session.refresh(loan_file)
    assert loan_file.lender_id == lender.id


async def test_relationships_load(db_session: AsyncSession) -> None:
    """company/lender relationships and the reverse loan_files collections load."""
    company = await _make_company(db_session, "acme")
    lender = await _make_lender(db_session, company, "uwm")
    loan_file = await create_loan_file(db_session, company_id=company.id, lender_id=lender.id)

    # Forward relationships from the loan file.
    stmt = (
        select(LoanFile)
        .where(LoanFile.id == loan_file.id)
        .options(selectinload(LoanFile.company), selectinload(LoanFile.lender))
    )
    loaded = (await db_session.scalars(stmt)).one()
    assert loaded.company.id == company.id
    assert loaded.lender is not None
    assert loaded.lender.id == lender.id

    # Reverse one-to-many collections from company and lender.
    company_stmt = (
        select(Company).where(Company.id == company.id).options(selectinload(Company.loan_files))
    )
    loaded_company = (await db_session.scalars(company_stmt)).one()
    assert loan_file.id in {f.id for f in loaded_company.loan_files}

    lender_stmt = (
        select(Lender).where(Lender.id == lender.id).options(selectinload(Lender.loan_files))
    )
    loaded_lender = (await db_session.scalars(lender_stmt)).one()
    assert loan_file.id in {f.id for f in loaded_lender.loan_files}


async def test_soft_delete_and_only_active(db_session: AsyncSession) -> None:
    """Soft delete sets deleted_at; only_active() filters such rows out."""
    company = await _make_company(db_session, "acme")
    live = await create_loan_file(db_session, company_id=company.id)
    gone = await create_loan_file(db_session, company_id=company.id)

    gone.deleted_at = utcnow()
    await db_session.flush()
    assert gone.is_deleted is True

    stmt = only_active(select(LoanFile), LoanFile)
    ids = {f.id for f in (await db_session.scalars(stmt)).all()}
    assert live.id in ids
    assert gone.id not in ids


async def test_scope_to_company_isolates_loan_files(db_session: AsyncSession) -> None:
    """scope_to_company returns only the target company's loan files (isolation)."""
    company_a = await _make_company(db_session, "company-a")
    company_b = await _make_company(db_session, "company-b")
    a1 = await create_loan_file(db_session, company_id=company_a.id)
    a2 = await create_loan_file(db_session, company_id=company_a.id)
    b1 = await create_loan_file(db_session, company_id=company_b.id)

    stmt_a = scope_to_company(select(LoanFile), LoanFile, company_a.id)
    rows_a = (await db_session.scalars(stmt_a)).all()
    assert {f.id for f in rows_a} == {a1.id, a2.id}
    assert all(f.company_id == company_a.id for f in rows_a)

    stmt_b = scope_to_company(select(LoanFile), LoanFile, company_b.id)
    rows_b = (await db_session.scalars(stmt_b)).all()
    assert {f.id for f in rows_b} == {b1.id}


async def test_status_check_constraint_rejects_invalid_value(
    db_session: AsyncSession,
) -> None:
    """The DB CHECK constraint rejects an out-of-range status (LP-11 fix)."""
    company = await _make_company(db_session, "acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    # Bypass the Python enum and write a bad value straight to the column; the
    # CHECK constraint must reject it at the database level.
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE loan_files SET status = :bad WHERE id = :id"),
                {"bad": "banana", "id": loan_file.id},
            )


async def test_create_loan_file_flushes_not_commits(db_session: AsyncSession) -> None:
    """create_loan_file flushes (not commits): the row is visible but the
    surrounding transaction is still open and rolled back by the fixture."""
    company = await _make_company(db_session, "acme")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    # Visible within the open transaction via a fresh query.
    found = await db_session.scalar(select(LoanFile).where(LoanFile.id == loan_file.id))
    assert found is not None
    # The session has no pending unflushed changes (flush already ran)...
    assert not db_session.new
    # ...but the transaction is still active (not committed).
    assert db_session.in_transaction()
