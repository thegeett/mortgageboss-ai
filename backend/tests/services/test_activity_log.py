"""Tests for the activity log service (LP-20)."""

from app.models import ActivityType, Company, User, UserRole
from app.services.activity_log import log_activity
from app.services.loan_files import create_loan_file
from sqlalchemy.ext.asyncio import AsyncSession


async def test_log_activity_creates_entry_with_detail(db_session: AsyncSession) -> None:
    """log_activity records type, summary, actor, and detail."""
    company = Company(name="Acme", slug="acme")
    db_session.add(company)
    await db_session.flush()
    user = User(
        company_id=company.id,
        email="a@acme.test",
        hashed_password="h",
        first_name="Act",
        last_name="Or",
        role=UserRole.PROCESSOR,
    )
    db_session.add(user)
    await db_session.flush()
    loan_file = await create_loan_file(db_session, company_id=company.id)

    entry = await log_activity(
        db_session,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.STATUS_CHANGED,
        summary="Status changed from In Processing to Submitted",
        actor_user_id=user.id,
        detail={"from": "in_processing", "to": "submitted"},
    )

    assert entry.loan_file_id == loan_file.id
    assert entry.activity_type is ActivityType.STATUS_CHANGED
    assert entry.summary == "Status changed from In Processing to Submitted"
    assert entry.actor_user_id == user.id
    assert entry.detail == {"from": "in_processing", "to": "submitted"}


async def test_log_activity_defaults_actor_none_and_detail_empty(db_session: AsyncSession) -> None:
    """A system activity has a null actor and an empty detail dict by default."""
    company = Company(name="Acme", slug="acme")
    db_session.add(company)
    await db_session.flush()
    loan_file = await create_loan_file(db_session, company_id=company.id)

    entry = await log_activity(
        db_session,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.VERIFICATION_RUN,
        summary="Verification run completed",
    )

    assert entry.actor_user_id is None
    assert entry.detail == {}
