"""Communication service — minimal record creation (sending is Phase 4, LP-20)."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.communication import (
    Communication,
    CommunicationChannel,
    CommunicationDirection,
    CommunicationStatus,
)


async def create_communication(
    db: AsyncSession,
    *,
    loan_file_id: UUID,
    direction: CommunicationDirection,
    status: CommunicationStatus,
    channel: CommunicationChannel = CommunicationChannel.EMAIL,
    sender: str | None = None,
    recipient: str | None = None,
    subject: str | None = None,
    body: str | None = None,
    needs_item_id: UUID | None = None,
    initiated_by_user_id: UUID | None = None,
    external_message_id: str | None = None,
) -> Communication:
    """Create a communication record on a loan file.

    Just persists the message state — actually sending an email (outbound) and
    routing an inbound one are Phase 4. Uses ``flush`` rather than ``commit`` so
    the caller controls the transaction.
    """
    communication = Communication(
        loan_file_id=loan_file_id,
        direction=direction,
        status=status,
        channel=channel,
        sender=sender,
        recipient=recipient,
        subject=subject,
        body=body,
        needs_item_id=needs_item_id,
        initiated_by_user_id=initiated_by_user_id,
        external_message_id=external_message_id,
    )
    db.add(communication)
    await db.flush()
    return communication
