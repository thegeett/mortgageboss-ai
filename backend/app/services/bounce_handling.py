"""What happens when a message does not arrive (LP-819).

BOUNCES ARE EVENTS, NOT MAIL. The plan says "ingest the `bounces.` subdomain", and that is not
possible: a custom MAIL FROM domain must carry exactly one MX pointing at SES's feedback endpoint,
so `bounces.` cannot also be a receipt domain and a bounce never arrives as a message anyone can
read. INFRA-3 builds the real path — an SES configuration set publishing delivery events to SNS —
and this is what reads them. The escalation is in the progress file.

THE CLASSIFICATION IS RFC 3463's, QUOTED RATHER THAN RECALLED. From "Enhanced Mail System Status
Codes", read 2026-09-07:

    4.XXX.XXX  Persistent Transient Failure — "the message as sent is valid, but persistence of some
               temporary condition has caused abandonment or delay ... sending in the future may be
               successful."
    5.XXX.XXX  Permanent Failure — "not likely to be resolved by resending the message in the
               current form."

So a `5.x.x` suppresses the address and a `4.x.x` does not. Getting that backwards either abandons a
borrower over a full mailbox or hammers a dead one forever.

AND THE SUPPRESSION HAS TO REACH THE REMINDER CLOCK. This is the failure the plan names: LP-814
counts "no reply > 5 days" against `requested_at`, and a hard bounce means the borrower NEVER
RECEIVED THE REQUEST. Left alone, the clock escalates against a mailbox that does not exist, forever,
and every nudge bounces too. So a hard bounce UNWINDS the request — `requested_at` cleared, the need
back to PENDING — because a request that bounced was never made.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.communication import Communication, CommunicationStatus
from app.models.loan_file import LoanFile
from app.models.needs_item import NeedsItem, NeedsItemStatus
from app.models.suppressed_address import SuppressedAddress, SuppressionReason
from app.services.activity_log import log_activity

logger = get_logger(__name__)

#: An RFC 3463 status code: class.subject.detail. Anchored so a code embedded in prose is not
#: mistaken for the status — a diagnostic string routinely quotes the sender's address, which can
#: contain digits and dots.
_STATUS_CODE = re.compile(r"\b([245])\.(\d{1,3})\.(\d{1,3})\b")


class BounceClass(StrEnum):
    """RFC 3463's class subfield, as the only three answers that change what we do."""

    PERMANENT = "permanent"  # 5.x.x — stop
    TRANSIENT = "transient"  # 4.x.x — it may work later
    UNKNOWN = "unknown"  # no parseable status


@dataclass(frozen=True)
class DeliveryFailure:
    """One provider report about one message."""

    message_id: str | None
    recipient: str
    status_code: str | None
    diagnostic: str | None
    bounce_class: BounceClass


def classify_status(status: str | None, *, diagnostic: str | None = None) -> BounceClass:
    """The RFC 3463 class of a status code, from the status field or the diagnostic text.

    UNKNOWN IS NOT TREATED AS PERMANENT. A report we cannot parse is a report we do not understand,
    and suppressing an address on it would abandon a borrower because a provider phrased something
    unexpectedly. Unknown is left for a person, which is the conservative direction on a decision
    that stops someone being contacted about their mortgage.
    """
    for candidate in (status, diagnostic):
        if not candidate:
            continue
        if found := _STATUS_CODE.search(candidate):
            return {"5": BounceClass.PERMANENT, "4": BounceClass.TRANSIENT}.get(
                found.group(1), BounceClass.UNKNOWN
            )
    return BounceClass.UNKNOWN


def parse_ses_bounce(event: dict[str, Any]) -> tuple[DeliveryFailure, ...]:
    """Every failed recipient in one SES bounce notification.

    ONE EVENT CAN CARRY SEVERAL RECIPIENTS, each with its own status. Taking only the first would
    silently leave the others un-suppressed — and they are the ones a second send would bounce off
    again.
    """
    bounce = event.get("bounce") or {}
    mail = event.get("mail") or {}
    message_id = mail.get("messageId")
    failures: list[DeliveryFailure] = []
    for recipient in bounce.get("bouncedRecipients") or []:
        address = (recipient.get("emailAddress") or "").strip().lower()
        if not address:
            continue
        status = recipient.get("status")
        diagnostic = recipient.get("diagnosticCode")
        failures.append(
            DeliveryFailure(
                message_id=message_id,
                recipient=address,
                status_code=status,
                diagnostic=diagnostic,
                bounce_class=classify_status(status, diagnostic=diagnostic),
            )
        )
    return tuple(failures)


async def is_suppressed(db: AsyncSession, *, company_id: UUID, address: str) -> bool:
    """Whether this company must not email this address. Case-insensitive."""
    found = await db.scalar(
        select(SuppressedAddress.id).where(
            SuppressedAddress.company_id == company_id,
            SuppressedAddress.address == address.strip().lower(),
        )
    )
    return found is not None


async def suppress_address(
    db: AsyncSession,
    *,
    company_id: UUID,
    address: str,
    reason: SuppressionReason,
    status_code: str | None = None,
    diagnostic: str | None = None,
) -> SuppressedAddress:
    """Record that this company must not email this address. Idempotent. ``flush`` only."""
    normalised = address.strip().lower()
    existing = await db.scalar(
        select(SuppressedAddress).where(
            SuppressedAddress.company_id == company_id,
            SuppressedAddress.address == normalised,
        )
    )
    if existing is not None:
        return existing
    record = SuppressedAddress(
        company_id=company_id,
        address=normalised,
        reason=reason,
        status_code=status_code,
        diagnostic=diagnostic,
        suppressed_at=utcnow(),
    )
    db.add(record)
    await db.flush()
    # METADATA ONLY — never the address, which identifies a borrower, and never the diagnostic,
    # which quotes it back.
    logger.warning("address_suppressed", reason=reason.value, status_code=status_code)
    return record


async def _unwind_requests(db: AsyncSession, *, communication: Communication) -> int:
    """Undo the REQUESTED transition for everything this message asked for.

    THE PART THE PLAN NAMES. LP-814's reminders read `requested_at`; a hard bounce means the borrower
    never received the request, so leaving the stamp set makes the clock escalate against a mailbox
    that does not exist — and every nudge bounces too. A request that bounced was never made.

    Only needs still in ``REQUESTED`` are touched: one that has since been satisfied by a document
    arriving another way must not be dragged backwards.
    """
    from app.models.communication_needs_item import CommunicationNeedsItem

    needs = (
        (
            await db.execute(
                select(NeedsItem)
                .join(
                    CommunicationNeedsItem,
                    CommunicationNeedsItem.needs_item_id == NeedsItem.id,
                )
                .where(
                    CommunicationNeedsItem.communication_id == communication.id,
                    NeedsItem.status == NeedsItemStatus.REQUESTED,
                )
            )
        )
        .scalars()
        .all()
    )
    for need in needs:
        need.status = NeedsItemStatus.PENDING
        need.requested_at = None
    return len(needs)


async def record_delivery_failure(
    db: AsyncSession, *, failure: DeliveryFailure
) -> Communication | None:
    """Apply one provider report. Returns the communication it was about, or None.

    Returns None rather than raising when the message is unknown to us — SES publishes events for
    everything sent through the configuration set, and an event we cannot match is not an error.
    """
    if not failure.message_id:
        return None
    communication = await db.scalar(
        select(Communication).where(Communication.external_message_id == failure.message_id)
    )
    if communication is None:
        logger.info("delivery_event_unmatched", bounce_class=failure.bounce_class.value)
        return None

    communication.status = CommunicationStatus.FAILED
    # THE COLUMN THAT HAS NEVER HAD A WRITER. `error_detail` has existed on this model since LP-20.
    # It carries the provider's own words, which quote the recipient's address — so it is stored and
    # never logged, and the readonly view already drops it.
    communication.error_detail = failure.diagnostic or failure.status_code

    unwound = 0
    if failure.bounce_class is BounceClass.PERMANENT and communication.loan_file_id:
        loan_file = await db.get(LoanFile, communication.loan_file_id)
        if loan_file is not None:
            await suppress_address(
                db,
                company_id=loan_file.company_id,
                address=failure.recipient,
                reason=SuppressionReason.HARD_BOUNCE,
                status_code=failure.status_code,
                diagnostic=failure.diagnostic,
            )
        unwound = await _unwind_requests(db, communication=communication)

    await log_activity(
        db,
        loan_file_id=communication.loan_file_id,
        activity_type=ActivityType.COMMUNICATION_FAILED,
        summary=(
            "A document request did not reach the borrower"
            if failure.bounce_class is BounceClass.PERMANENT
            else "A document request was delayed and will be retried"
        ),
        detail={
            "communication_id": str(communication.id),
            "bounce_class": failure.bounce_class.value,
            "status_code": failure.status_code,
            "needs_items_unwound": unwound,
        },
    )
    await db.flush()
    return communication


__all__ = [
    "BounceClass",
    "DeliveryFailure",
    "classify_status",
    "is_suppressed",
    "parse_ses_bounce",
    "record_delivery_failure",
    "suppress_address",
]
