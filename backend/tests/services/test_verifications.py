"""Tests for the verification run creation service (LP-18)."""

from app.models import (
    Company,
    VerificationStatus,
    VerificationTrigger,
)
from app.services.loan_files import create_loan_file
from app.services.verifications import create_verification_run
from sqlalchemy.ext.asyncio import AsyncSession


async def test_create_verification_run_starts_running_with_zero_counts(
    db_session: AsyncSession,
) -> None:
    """create_verification_run makes a RUNNING run with started_at and zero counts."""
    company = Company(name="Acme", slug="acme")
    db_session.add(company)
    await db_session.flush()
    loan_file = await create_loan_file(db_session, company_id=company.id)

    run = await create_verification_run(
        db_session, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
    )

    assert run.loan_file_id == loan_file.id
    assert run.status is VerificationStatus.RUNNING
    assert run.trigger is VerificationTrigger.MANUAL
    assert run.started_at is not None
    assert run.started_at.tzinfo is not None
    assert run.red_count == 0
    assert run.yellow_count == 0
    assert run.green_count == 0
    assert run.completed_at is None
