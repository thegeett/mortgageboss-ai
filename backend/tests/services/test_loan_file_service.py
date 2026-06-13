"""Tests for the loan-file lifecycle orchestration (LP-30).

Exercises the workflow layer in :mod:`app.services.loan_files` against the
rollback ``db_session``: creation orchestration (file + provisional needs list +
``FILE_CREATED`` activity), the per-program needs list, and activity logging on
update (``STATUS_CHANGED`` / ``FILE_UPDATED``) and soft delete (``FILE_DELETED``).
"""

from uuid import UUID

from app.core.security import hash_password
from app.models import Company, User, UserRole
from app.models.activity_log import ActivityLog, ActivityType
from app.models.lender import LoanProgram
from app.models.loan_file import LoanFileStatus
from app.models.needs_item import NeedsItem, NeedsItemOrigin
from app.schemas.loan_file import LoanFileUpdate
from app.services.loan_files import (
    create_loan_file_with_setup,
    generate_initial_needs_list,
    soft_delete_loan_file_with_activity,
    update_loan_file_with_activity,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _company(db: AsyncSession, slug: str = "acme") -> Company:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    return company


async def _user(db: AsyncSession, company: Company) -> User:
    user = User(
        company_id=company.id,
        email="actor@acme.com",
        hashed_password=hash_password("x"),
        first_name="Act",
        last_name="Or",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _needs(db: AsyncSession, loan_file_id: UUID) -> list[NeedsItem]:
    result = await db.execute(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file_id))
    return list(result.scalars().all())


async def _activities(db: AsyncSession, loan_file_id: UUID) -> list[ActivityLog]:
    result = await db.execute(select(ActivityLog).where(ActivityLog.loan_file_id == loan_file_id))
    return list(result.scalars().all())


# --------------------------------------------------------------------------- #
# initial needs list
# --------------------------------------------------------------------------- #


async def test_needs_list_conventional_is_universal_baseline(db_session: AsyncSession) -> None:
    """CONVENTIONAL → the universal baseline (no FHA extras), origin TEMPLATE."""
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file = await create_loan_file_with_setup(
        db_session,
        company_id=company.id,
        actor_user_id=user.id,
        loan_program=LoanProgram.CONVENTIONAL,
    )
    needs = await _needs(db_session, loan_file.id)
    assert len(needs) == 4  # universal baseline
    assert all(n.origin is NeedsItemOrigin.TEMPLATE for n in needs)


async def test_needs_list_fha_adds_fha_items(db_session: AsyncSession) -> None:
    """FHA → universal baseline + the FHA-specific item(s)."""
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file = await create_loan_file_with_setup(
        db_session,
        company_id=company.id,
        actor_user_id=user.id,
        loan_program=LoanProgram.FHA,
    )
    needs = await _needs(db_session, loan_file.id)
    assert len(needs) == 5  # 4 universal + 1 FHA placeholder
    assert any("FHA" in n.title for n in needs)


async def test_needs_list_none_program_is_universal_only(db_session: AsyncSession) -> None:
    """No program → the universal baseline only, all origin TEMPLATE."""
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file = await create_loan_file_with_setup(
        db_session, company_id=company.id, actor_user_id=user.id
    )
    items = await generate_initial_needs_list(
        db_session, loan_file_id=loan_file.id, loan_program=None
    )
    assert len(items) == 4
    assert all(i.origin is NeedsItemOrigin.TEMPLATE for i in items)


# --------------------------------------------------------------------------- #
# creation orchestration
# --------------------------------------------------------------------------- #


async def test_create_with_setup_makes_file_needs_and_activity(db_session: AsyncSession) -> None:
    """The workflow creates a DRAFT file with ids, a needs list, and a FILE_CREATED activity."""
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file = await create_loan_file_with_setup(
        db_session,
        company_id=company.id,
        actor_user_id=user.id,
        loan_program=LoanProgram.FHA,
    )
    # File: ids + DRAFT.
    assert loan_file.display_id
    assert loan_file.inbox_token
    assert loan_file.status is LoanFileStatus.DRAFT

    # Needs list generated.
    assert len(await _needs(db_session, loan_file.id)) == 5

    # Exactly one FILE_CREATED activity, with the actor and a needs count in detail.
    activities = await _activities(db_session, loan_file.id)
    created = [a for a in activities if a.activity_type is ActivityType.FILE_CREATED]
    assert len(created) == 1
    assert created[0].actor_user_id == user.id
    assert created[0].detail["initial_needs_count"] == 5
    assert created[0].detail["loan_program"] == "fha"


# --------------------------------------------------------------------------- #
# update / delete activity logging
# --------------------------------------------------------------------------- #


async def test_update_logs_status_changed_with_from_to(db_session: AsyncSession) -> None:
    """A status change logs STATUS_CHANGED with the correct from/to and actor."""
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file = await create_loan_file_with_setup(
        db_session, company_id=company.id, actor_user_id=user.id
    )

    await update_loan_file_with_activity(
        db_session,
        loan_file=loan_file,
        data=LoanFileUpdate(status=LoanFileStatus.IN_PROCESSING),
        actor_user_id=user.id,
    )

    status_changes = [
        a
        for a in await _activities(db_session, loan_file.id)
        if a.activity_type is ActivityType.STATUS_CHANGED
    ]
    assert len(status_changes) == 1
    assert status_changes[0].detail == {"from": "draft", "to": "in_processing"}
    assert status_changes[0].actor_user_id == user.id


async def test_update_non_status_logs_file_updated(db_session: AsyncSession) -> None:
    """A non-status update logs FILE_UPDATED with the changed field names."""
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file = await create_loan_file_with_setup(
        db_session, company_id=company.id, actor_user_id=user.id
    )

    await update_loan_file_with_activity(
        db_session,
        loan_file=loan_file,
        data=LoanFileUpdate(loan_officer_name="Jordan LO"),
        actor_user_id=user.id,
    )

    updates = [
        a
        for a in await _activities(db_session, loan_file.id)
        if a.activity_type is ActivityType.FILE_UPDATED
    ]
    assert len(updates) == 1
    assert updates[0].detail == {"changed_fields": ["loan_officer_name"]}


async def test_soft_delete_logs_file_deleted(db_session: AsyncSession) -> None:
    """Soft delete logs FILE_DELETED with the actor, and marks the file deleted."""
    company = await _company(db_session)
    user = await _user(db_session, company)
    loan_file = await create_loan_file_with_setup(
        db_session, company_id=company.id, actor_user_id=user.id
    )

    await soft_delete_loan_file_with_activity(
        db_session, loan_file=loan_file, actor_user_id=user.id
    )

    assert loan_file.deleted_at is not None
    deletes = [
        a
        for a in await _activities(db_session, loan_file.id)
        if a.activity_type is ActivityType.FILE_DELETED
    ]
    assert len(deletes) == 1
    assert deletes[0].actor_user_id == user.id
