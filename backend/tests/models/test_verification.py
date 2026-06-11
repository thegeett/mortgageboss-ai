"""Tests for the Verification model (LP-18).

Covers the verification-run record against a real table: field round-tripping,
the RUNNING status default and zero summary counts, the status/trigger enum CHECK
constraints, timezone-aware timing, relationships, soft delete, and tenant
isolation (runs reachable only through the owning company's loan files).

The run↔findings linkage and the SET-NULL-on-run-deletion behaviour live in
``test_verification_findings_link.py``.

Uses the transaction-rollback ``db_session`` fixture from LP-10.
"""

import pytest
from app.models import (
    Company,
    LoanFile,
    Verification,
    VerificationStatus,
    VerificationTrigger,
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


async def _make_loan_file(db_session: AsyncSession, company: Company) -> LoanFile:
    return await create_loan_file(db_session, company_id=company.id)


async def _add_verification(
    db_session: AsyncSession,
    loan_file: LoanFile,
    *,
    status: VerificationStatus = VerificationStatus.RUNNING,
    trigger: VerificationTrigger = VerificationTrigger.MANUAL,
) -> Verification:
    verification = Verification(
        loan_file_id=loan_file.id,
        status=status,
        trigger=trigger,
        started_at=utcnow(),
    )
    db_session.add(verification)
    await db_session.flush()
    return verification


async def test_create_verification_defaults(db_session: AsyncSession) -> None:
    """A new run defaults to RUNNING with zero summary counts."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    verification = Verification(
        loan_file_id=loan_file.id,
        trigger=VerificationTrigger.MANUAL,
        started_at=utcnow(),
    )
    db_session.add(verification)
    await db_session.flush()

    await db_session.refresh(verification)
    assert verification.status is VerificationStatus.RUNNING
    assert verification.trigger is VerificationTrigger.MANUAL
    assert verification.red_count == 0
    assert verification.yellow_count == 0
    assert verification.green_count == 0
    assert verification.total_tokens_used is None
    assert verification.completed_at is None


async def test_status_check_constraint_rejects_invalid_value(db_session: AsyncSession) -> None:
    """The DB CHECK constraint rejects an out-of-range status."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    verification = await _add_verification(db_session, loan_file)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE verifications SET status = :bad WHERE id = :id"),
                {"bad": "paused", "id": verification.id},
            )


async def test_trigger_check_constraint_rejects_invalid_value(db_session: AsyncSession) -> None:
    """The DB CHECK constraint rejects an out-of-range trigger."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    verification = await _add_verification(db_session, loan_file)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE verifications SET trigger = :bad WHERE id = :id"),
                {"bad": "cron", "id": verification.id},
            )


async def test_all_enum_values_accepted(db_session: AsyncSession) -> None:
    """Every status and trigger value is valid."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    for status in VerificationStatus:
        for trigger in VerificationTrigger:
            verification = await _add_verification(
                db_session, loan_file, status=status, trigger=trigger
            )
            await db_session.refresh(verification)
            assert verification.status is status
            assert verification.trigger is trigger


async def test_timing_fields_are_timezone_aware(db_session: AsyncSession) -> None:
    """started_at / completed_at store timezone-aware datetimes."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    verification = await _add_verification(db_session, loan_file)
    verification.completed_at = utcnow()
    await db_session.flush()

    await db_session.refresh(verification)
    assert verification.started_at is not None
    assert verification.started_at.tzinfo is not None
    assert verification.completed_at is not None
    assert verification.completed_at.utcoffset() is not None


async def test_relationships_load(db_session: AsyncSession) -> None:
    """verification.loan_file and loan_file.verifications load."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    verification = await _add_verification(db_session, loan_file)

    stmt = (
        select(Verification)
        .where(Verification.id == verification.id)
        .options(selectinload(Verification.loan_file))
    )
    loaded = (await db_session.scalars(stmt)).one()
    assert loaded.loan_file.id == loan_file.id

    file_stmt = (
        select(LoanFile)
        .where(LoanFile.id == loan_file.id)
        .options(selectinload(LoanFile.verifications))
    )
    loaded_file = (await db_session.scalars(file_stmt)).one()
    assert verification.id in {v.id for v in loaded_file.verifications}


async def test_soft_delete_and_only_active(db_session: AsyncSession) -> None:
    """Soft delete sets deleted_at; only_active() filters the run out."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    live = await _add_verification(db_session, loan_file)
    gone = await _add_verification(db_session, loan_file)

    gone.deleted_at = utcnow()
    await db_session.flush()
    assert gone.is_deleted is True

    stmt = only_active(select(Verification), Verification)
    ids = {v.id for v in (await db_session.scalars(stmt)).all()}
    assert live.id in ids
    assert gone.id not in ids


async def test_verifications_are_isolated_by_company_through_their_loan_file(
    db_session: AsyncSession,
) -> None:
    """Runs carry no company_id; isolation is transitive via the loan file."""
    company_a = await _make_company(db_session, "company-a")
    company_b = await _make_company(db_session, "company-b")
    file_a = await _make_loan_file(db_session, company_a)
    file_b = await _make_loan_file(db_session, company_b)

    run_a = await _add_verification(db_session, file_a)
    run_b = await _add_verification(db_session, file_b)

    stmt_a = scope_to_company(
        select(Verification).join(LoanFile, Verification.loan_file_id == LoanFile.id),
        LoanFile,
        company_a.id,
    )
    ids_a = {v.id for v in (await db_session.scalars(stmt_a)).all()}
    assert ids_a == {run_a.id}
    assert run_b.id not in ids_a

    stmt_b = scope_to_company(
        select(Verification).join(LoanFile, Verification.loan_file_id == LoanFile.id),
        LoanFile,
        company_b.id,
    )
    ids_b = {v.id for v in (await db_session.scalars(stmt_b)).all()}
    assert ids_b == {run_b.id}
    assert ids_a.isdisjoint(ids_b)
