"""Tests for the ActivityLog model (LP-20).

Covers the audit-trail record against a real table: creation with structured
detail, the activity_type CHECK constraint, the nullable actor (null = system),
the JSON detail round-trip, relationships, multiple entries per file, soft
delete, and tenant isolation.

Uses the transaction-rollback ``db_session`` fixture from LP-10.
"""

import pytest
from app.models import (
    ActivityLog,
    ActivityType,
    Company,
    LoanFile,
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
        first_name="Act",
        last_name="Or",
        role=UserRole.PROCESSOR,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_loan_file(db_session: AsyncSession, company: Company) -> LoanFile:
    return await create_loan_file(db_session, company_id=company.id)


async def _add_activity(
    db_session: AsyncSession,
    loan_file: LoanFile,
    *,
    activity_type: ActivityType = ActivityType.STATUS_CHANGED,
    summary: str = "Status changed.",
    **kwargs: object,
) -> ActivityLog:
    entry = ActivityLog(
        loan_file_id=loan_file.id,
        activity_type=activity_type,
        summary=summary,
        **kwargs,
    )
    db_session.add(entry)
    await db_session.flush()
    return entry


async def test_create_activity_with_detail(db_session: AsyncSession) -> None:
    """A status-change entry persists its type, summary, and structured detail."""
    company = await _make_company(db_session, "acme")
    user = await _make_user(db_session, company, "a@acme.test")
    loan_file = await _make_loan_file(db_session, company)
    entry = await _add_activity(
        db_session,
        loan_file,
        activity_type=ActivityType.STATUS_CHANGED,
        summary="Status changed from In Processing to Submitted",
        actor_user_id=user.id,
        detail={"from": "in_processing", "to": "submitted"},
    )

    await db_session.refresh(entry)
    assert entry.activity_type is ActivityType.STATUS_CHANGED
    assert entry.summary == "Status changed from In Processing to Submitted"
    assert entry.actor_user_id == user.id
    assert entry.detail == {"from": "in_processing", "to": "submitted"}


async def test_activity_type_check_constraint_rejects_invalid_value(
    db_session: AsyncSession,
) -> None:
    """The DB CHECK constraint rejects an out-of-range activity_type."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    entry = await _add_activity(db_session, loan_file)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE activity_logs SET activity_type = :bad WHERE id = :id"),
                {"bad": "file_yeeted", "id": entry.id},
            )


async def test_all_activity_types_accepted(db_session: AsyncSession) -> None:
    """Every ActivityType value is valid."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    for activity_type in ActivityType:
        entry = await _add_activity(db_session, loan_file, activity_type=activity_type)
        await db_session.refresh(entry)
        assert entry.activity_type is activity_type


async def test_actor_is_nullable_for_system_activity(db_session: AsyncSession) -> None:
    """A user-actioned activity links a user; a system activity has null actor."""
    company = await _make_company(db_session, "acme")
    user = await _make_user(db_session, company, "a@acme.test")
    loan_file = await _make_loan_file(db_session, company)

    user_action = await _add_activity(db_session, loan_file, actor_user_id=user.id)
    system_action = await _add_activity(
        db_session, loan_file, activity_type=ActivityType.VERIFICATION_RUN
    )

    await db_session.refresh(user_action)
    await db_session.refresh(system_action)
    assert user_action.actor_user_id == user.id
    assert system_action.actor_user_id is None


async def test_detail_defaults_to_empty_dict(db_session: AsyncSession) -> None:
    """detail defaults to an empty dict when not provided."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    entry = await _add_activity(db_session, loan_file)

    await db_session.refresh(entry)
    assert entry.detail == {}


async def test_relationships_load(db_session: AsyncSession) -> None:
    """activity_log.loan_file/actor and loan_file.activity_logs load."""
    company = await _make_company(db_session, "acme")
    user = await _make_user(db_session, company, "a@acme.test")
    loan_file = await _make_loan_file(db_session, company)
    entry = await _add_activity(db_session, loan_file, actor_user_id=user.id)

    stmt = (
        select(ActivityLog)
        .where(ActivityLog.id == entry.id)
        .options(selectinload(ActivityLog.loan_file), selectinload(ActivityLog.actor))
    )
    loaded = (await db_session.scalars(stmt)).one()
    assert loaded.loan_file.id == loan_file.id
    assert loaded.actor is not None
    assert loaded.actor.id == user.id

    file_stmt = (
        select(LoanFile)
        .where(LoanFile.id == loan_file.id)
        .options(selectinload(LoanFile.activity_logs))
    )
    loaded_file = (await db_session.scalars(file_stmt)).one()
    assert entry.id in {a.id for a in loaded_file.activity_logs}


async def test_multiple_activities_per_loan_file(db_session: AsyncSession) -> None:
    """loan_file.activity_logs returns every entry on the file."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    a1 = await _add_activity(db_session, loan_file, activity_type=ActivityType.FILE_CREATED)
    a2 = await _add_activity(db_session, loan_file, activity_type=ActivityType.DOCUMENT_UPLOADED)
    a3 = await _add_activity(db_session, loan_file, activity_type=ActivityType.NOTE_ADDED)

    stmt = (
        select(LoanFile)
        .where(LoanFile.id == loan_file.id)
        .options(selectinload(LoanFile.activity_logs))
    )
    loaded = (await db_session.scalars(stmt)).one()
    assert {a.id for a in loaded.activity_logs} == {a1.id, a2.id, a3.id}


async def test_soft_delete_and_only_active(db_session: AsyncSession) -> None:
    """Soft delete sets deleted_at; only_active() filters the entry out."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    live = await _add_activity(db_session, loan_file)
    gone = await _add_activity(db_session, loan_file)

    gone.deleted_at = utcnow()
    await db_session.flush()
    assert gone.is_deleted is True

    stmt = only_active(select(ActivityLog), ActivityLog)
    ids = {a.id for a in (await db_session.scalars(stmt)).all()}
    assert live.id in ids
    assert gone.id not in ids


async def test_activity_logs_are_isolated_by_company_through_their_loan_file(
    db_session: AsyncSession,
) -> None:
    """Activity logs carry no company_id; isolation is transitive via the loan file."""
    company_a = await _make_company(db_session, "company-a")
    company_b = await _make_company(db_session, "company-b")
    file_a = await _make_loan_file(db_session, company_a)
    file_b = await _make_loan_file(db_session, company_b)

    entry_a = await _add_activity(db_session, file_a)
    entry_b = await _add_activity(db_session, file_b)

    stmt_a = scope_to_company(
        select(ActivityLog).join(LoanFile, ActivityLog.loan_file_id == LoanFile.id),
        LoanFile,
        company_a.id,
    )
    ids_a = {a.id for a in (await db_session.scalars(stmt_a)).all()}
    assert ids_a == {entry_a.id}
    assert entry_b.id not in ids_a

    stmt_b = scope_to_company(
        select(ActivityLog).join(LoanFile, ActivityLog.loan_file_id == LoanFile.id),
        LoanFile,
        company_b.id,
    )
    ids_b = {a.id for a in (await db_session.scalars(stmt_b)).all()}
    assert ids_b == {entry_b.id}
    assert ids_a.isdisjoint(ids_b)
