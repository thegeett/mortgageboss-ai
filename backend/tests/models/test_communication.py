"""Tests for the Communication model (LP-20).

Covers messages in/out of a loan file against a real table: outbound and inbound
creation, field round-tripping, the three enum CHECK constraints
(direction/channel/status), the nullable needs-item link, relationships, soft
delete, tenant isolation, and the SET NULL behaviour when a linked needs item is
removed.

Uses the transaction-rollback ``db_session`` fixture from LP-10.
"""

import pytest
from app.models import (
    Communication,
    CommunicationChannel,
    CommunicationDirection,
    CommunicationStatus,
    Company,
    LoanFile,
    NeedsItem,
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
        first_name="Proc",
        last_name="Essor",
        role=UserRole.PROCESSOR,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_loan_file(db_session: AsyncSession, company: Company) -> LoanFile:
    return await create_loan_file(db_session, company_id=company.id)


async def _make_needs_item(db_session: AsyncSession, loan_file: LoanFile) -> NeedsItem:
    item = NeedsItem(loan_file_id=loan_file.id, title="2023 W-2")
    db_session.add(item)
    await db_session.flush()
    return item


async def _add_communication(
    db_session: AsyncSession,
    loan_file: LoanFile,
    *,
    direction: CommunicationDirection = CommunicationDirection.OUTBOUND,
    status: CommunicationStatus = CommunicationStatus.SENT,
    **kwargs: object,
) -> Communication:
    communication = Communication(
        loan_file_id=loan_file.id,
        direction=direction,
        status=status,
        **kwargs,
    )
    db_session.add(communication)
    await db_session.flush()
    return communication


async def test_create_outbound_request(db_session: AsyncSession) -> None:
    """An outbound borrower document request persists its fields and defaults to EMAIL."""
    company = await _make_company(db_session, "acme")
    user = await _make_user(db_session, company, "p@acme.test")
    loan_file = await _make_loan_file(db_session, company)
    needs_item = await _make_needs_item(db_session, loan_file)
    comm = await _add_communication(
        db_session,
        loan_file,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.SENT,
        sender="processor@mortgageboss.ai",
        recipient="borrower@example.com",
        subject="Please send your 2023 W-2",
        body="We still need your 2023 W-2 to proceed.",
        needs_item_id=needs_item.id,
        initiated_by_user_id=user.id,
        sent_at=utcnow(),
    )

    await db_session.refresh(comm)
    assert comm.direction is CommunicationDirection.OUTBOUND
    assert comm.channel is CommunicationChannel.EMAIL
    assert comm.status is CommunicationStatus.SENT
    assert comm.recipient == "borrower@example.com"
    assert comm.subject == "Please send your 2023 W-2"
    assert comm.needs_item_id == needs_item.id
    assert comm.initiated_by_user_id == user.id
    assert comm.sent_at is not None


async def test_create_inbound_message(db_session: AsyncSession) -> None:
    """An inbound message is RECEIVED with a null initiating user."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    comm = await _add_communication(
        db_session,
        loan_file,
        direction=CommunicationDirection.INBOUND,
        status=CommunicationStatus.RECEIVED,
        sender="borrower@example.com",
        recipient="lf-token@inbox.mortgageboss.ai",
        subject="Re: Please send your 2023 W-2",
        external_message_id="<abc123@mail.example.com>",
    )

    await db_session.refresh(comm)
    assert comm.direction is CommunicationDirection.INBOUND
    assert comm.status is CommunicationStatus.RECEIVED
    assert comm.initiated_by_user_id is None
    assert comm.needs_item_id is None
    assert comm.external_message_id == "<abc123@mail.example.com>"


async def test_direction_check_constraint_rejects_invalid_value(db_session: AsyncSession) -> None:
    """The DB CHECK constraint rejects an out-of-range direction."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    comm = await _add_communication(db_session, loan_file)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE communications SET direction = :bad WHERE id = :id"),
                {"bad": "sideways", "id": comm.id},
            )


async def test_channel_check_constraint_rejects_invalid_value(db_session: AsyncSession) -> None:
    """The DB CHECK constraint rejects a non-email channel (EMAIL only in V1)."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    comm = await _add_communication(db_session, loan_file)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE communications SET channel = :bad WHERE id = :id"),
                {"bad": "carrier_pigeon", "id": comm.id},
            )


async def test_status_check_constraint_rejects_invalid_value(db_session: AsyncSession) -> None:
    """The DB CHECK constraint rejects an out-of-range status."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    comm = await _add_communication(db_session, loan_file)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE communications SET status = :bad WHERE id = :id"),
                {"bad": "bounced", "id": comm.id},
            )


async def test_relationships_load(db_session: AsyncSession) -> None:
    """communication.loan_file/needs_item/initiated_by and loan_file.communications load."""
    company = await _make_company(db_session, "acme")
    user = await _make_user(db_session, company, "p@acme.test")
    loan_file = await _make_loan_file(db_session, company)
    needs_item = await _make_needs_item(db_session, loan_file)
    comm = await _add_communication(
        db_session, loan_file, needs_item_id=needs_item.id, initiated_by_user_id=user.id
    )

    stmt = (
        select(Communication)
        .where(Communication.id == comm.id)
        .options(
            selectinload(Communication.loan_file),
            selectinload(Communication.needs_item),
            selectinload(Communication.initiated_by),
        )
    )
    loaded = (await db_session.scalars(stmt)).one()
    assert loaded.loan_file.id == loan_file.id
    assert loaded.needs_item is not None
    assert loaded.needs_item.id == needs_item.id
    assert loaded.initiated_by is not None
    assert loaded.initiated_by.id == user.id

    file_stmt = (
        select(LoanFile)
        .where(LoanFile.id == loan_file.id)
        .options(selectinload(LoanFile.communications))
    )
    loaded_file = (await db_session.scalars(file_stmt)).one()
    assert comm.id in {c.id for c in loaded_file.communications}


async def test_soft_delete_and_only_active(db_session: AsyncSession) -> None:
    """Soft delete sets deleted_at; only_active() filters the message out."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    live = await _add_communication(db_session, loan_file)
    gone = await _add_communication(db_session, loan_file)

    gone.deleted_at = utcnow()
    await db_session.flush()
    assert gone.is_deleted is True

    stmt = only_active(select(Communication), Communication)
    ids = {c.id for c in (await db_session.scalars(stmt)).all()}
    assert live.id in ids
    assert gone.id not in ids


async def test_deleting_needs_item_nulls_link_and_keeps_communication(
    db_session: AsyncSession,
) -> None:
    """SET NULL: hard-deleting the linked needs item nulls needs_item_id, keeps the message."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    needs_item = await _make_needs_item(db_session, loan_file)
    comm = await _add_communication(db_session, loan_file, needs_item_id=needs_item.id)
    comm_id = comm.id

    await db_session.delete(needs_item)
    await db_session.flush()
    db_session.expire_all()

    surviving = await db_session.scalar(select(Communication).where(Communication.id == comm_id))
    assert surviving is not None
    assert surviving.needs_item_id is None


async def test_communications_are_isolated_by_company_through_their_loan_file(
    db_session: AsyncSession,
) -> None:
    """Communications carry no company_id; isolation is transitive via the loan file."""
    company_a = await _make_company(db_session, "company-a")
    company_b = await _make_company(db_session, "company-b")
    file_a = await _make_loan_file(db_session, company_a)
    file_b = await _make_loan_file(db_session, company_b)

    comm_a = await _add_communication(db_session, file_a)
    comm_b = await _add_communication(db_session, file_b)

    stmt_a = scope_to_company(
        select(Communication).join(LoanFile, Communication.loan_file_id == LoanFile.id),
        LoanFile,
        company_a.id,
    )
    ids_a = {c.id for c in (await db_session.scalars(stmt_a)).all()}
    assert ids_a == {comm_a.id}
    assert comm_b.id not in ids_a

    stmt_b = scope_to_company(
        select(Communication).join(LoanFile, Communication.loan_file_id == LoanFile.id),
        LoanFile,
        company_b.id,
    )
    ids_b = {c.id for c in (await db_session.scalars(stmt_b)).all()}
    assert ids_b == {comm_b.id}
    assert ids_a.isdisjoint(ids_b)
