"""Tests for the communication creation service (LP-20)."""

from app.models import (
    CommunicationChannel,
    CommunicationDirection,
    CommunicationStatus,
    Company,
    NeedsItem,
)
from app.services.communications import create_communication
from app.services.loan_files import create_loan_file
from sqlalchemy.ext.asyncio import AsyncSession


async def test_create_communication_persists_fields(db_session: AsyncSession) -> None:
    """create_communication makes a record with the given fields, defaulting to EMAIL."""
    company = Company(name="Acme", slug="acme")
    db_session.add(company)
    await db_session.flush()
    loan_file = await create_loan_file(db_session, company_id=company.id)
    needs_item = NeedsItem(loan_file_id=loan_file.id, title="2023 W-2")
    db_session.add(needs_item)
    await db_session.flush()

    comm = await create_communication(
        db_session,
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.DRAFT,
        recipient="borrower@example.com",
        subject="Please send your 2023 W-2",
        body="We still need your 2023 W-2.",
        needs_item_id=needs_item.id,
    )

    assert comm.loan_file_id == loan_file.id
    assert comm.direction is CommunicationDirection.OUTBOUND
    assert comm.status is CommunicationStatus.DRAFT
    assert comm.channel is CommunicationChannel.EMAIL
    assert comm.recipient == "borrower@example.com"
    assert comm.needs_item_id == needs_item.id
