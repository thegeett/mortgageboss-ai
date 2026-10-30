"""LP-995 — what SES reports about a sent email, applied to that email.

SES publishes one event per outcome to the configuration set's topic, and the events queue receives
it as-is (raw delivery, LP-983): the SQS message body IS the SES event. `apply_delivery_event` takes
one parsed event. The queue job (`tasks/outbound.read_delivery_events`) and the dev script
(`scripts/inject_delivery_event`) both call it; neither applies an event any other way.

| `eventType` | For the To recipient | Status |
|---|---|---|
| `Delivery` | — | `sent` → `delivered`; `failed` stays `failed` unless a temporary bounce failed it |
| `Bounce` | `record_delivery_failure`: permanent blocks the address and unwinds | `failed` |
| `Complaint` | block the address (`COMPLAINT`), log it on the file | unchanged |
| `Reject`, `Rendering Failure` | `record_not_sent`: needs unwound | `failed` |

ONLY THE EMAIL'S OWN TO RECIPIENT COUNTS. Every email is CC'd to the processor who approved it, and
SES reports on each recipient. A bounce from the processor's mailbox must not fail the borrower's
email, and a processor marking it as spam must not block the borrower.

A LATE DELIVERY NEVER UNDOES A PERMANENT FAILURE. Events arrive in no guaranteed order, and a
permanent bounce or a refusal is the more informative report. After a temporary or unclear bounce,
a Delivery means the email did arrive (`_delivered_after_failure`).

LOGS CARRY THE EVENT TYPE, THE OUTCOME AND THE COMMUNICATION ID ONLY. Never an address, a diagnostic
or a subject: the provider's diagnostic quotes the recipient, so it goes to `error_detail` only.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.activity_log import ActivityLog, ActivityType
from app.models.communication import Communication, CommunicationDirection, CommunicationStatus
from app.models.loan_file import LoanFile
from app.models.suppressed_address import SuppressionReason
from app.services.activity_log import log_activity
from app.services.bounce_handling import (
    BounceClass,
    parse_ses_bounce,
    record_delivery_failure,
    record_not_sent,
    suppress_address,
)

logger = get_logger(__name__)

#: `error_detail` for SES's `OnAccountSuppressionList` bounce: SES did not even try.
SUPPRESSED_BEFORE = (
    "Not delivered: this address bounced or complained before. "
    "Ask the borrower for another address."
)
COMPLAINT_SUMMARY = "The recipient marked this email as spam. Their address is now blocked."
DELIVERED_AFTER_FAILURE = (
    "A document request was delivered after an earlier temporary failure. "
    "The documents it asked for are still pending: request them again if needed."
)


def _normalised(address: object) -> str:
    return address.strip().lower() if isinstance(address, str) else ""


def _is_to(communication: Communication, addresses: Iterable[object]) -> bool:
    """Whether the email's own To recipient is among the addresses an event reports on."""
    to = _normalised(communication.recipient)
    return bool(to) and to in {_normalised(address) for address in addresses}


async def _failure_details(db: AsyncSession, row: Communication) -> list[dict[str, Any]]:
    """The `detail` of every `communication_failed` entry about this email, oldest first.

    Filtered in SQL: a file can carry many such entries, and this runs on every complaint and on a
    Delivery for a failed email.
    """
    return list(
        (
            await db.scalars(
                select(ActivityLog.detail)
                .where(
                    ActivityLog.loan_file_id == row.loan_file_id,
                    ActivityLog.activity_type == ActivityType.COMMUNICATION_FAILED,
                    ActivityLog.detail["communication_id"].as_string() == str(row.id),
                )
                .order_by(ActivityLog.created_at)
            )
        ).all()
    )


async def _delivery(db: AsyncSession, row: Communication, event: dict[str, Any]) -> str:
    recipients = (event.get("delivery") or {}).get("recipients") or []
    if not _is_to(row, recipients):
        return "ignored"
    if row.status is CommunicationStatus.DELIVERED:
        return "duplicate"
    if row.status is CommunicationStatus.FAILED:
        return await _delivered_after_failure(db, row)
    if row.status is not CommunicationStatus.SENT:
        return "ignored"
    row.status = CommunicationStatus.DELIVERED
    return "delivered"


async def _delivered_after_failure(db: AsyncSession, row: Communication) -> str:
    """A Delivery for an email already `failed`.

    A PERMANENT BOUNCE OR A REFUSAL IS NEVER UNDONE: the address is dead, or SES sent nothing, and
    a Delivery that says otherwise is the less informative report. A TEMPORARY OR UNCLEAR BOUNCE
    FOLLOWED BY A DELIVERY means the email did arrive, so the email becomes `delivered`.

    The needs that bounce put back to pending are LEFT PENDING. Putting them back to requested would
    also mean restoring the finding markers the unwind cleared and choosing whose request it was; the
    activity entry tells the processor instead, and the next request asks again.
    """
    failures = await _failure_details(db, row)
    bounces = [detail for detail in failures if "bounce_class" in detail]
    if not bounces or len(bounces) != len(failures):
        return "ignored"  # a refusal (Reject, Rendering Failure, the worker's "Not sent")
    if any(detail["bounce_class"] == BounceClass.PERMANENT.value for detail in bounces):
        return "ignored"
    row.status = CommunicationStatus.DELIVERED
    row.error_detail = None
    await log_activity(
        db,
        loan_file_id=row.loan_file_id,
        activity_type=ActivityType.COMMUNICATION_SENT,
        summary=DELIVERED_AFTER_FAILURE,
        detail={"communication_id": str(row.id), "event": "delivered_after_failure"},
    )
    return "delivered"


async def _bounce(db: AsyncSession, row: Communication, event: dict[str, Any]) -> str:
    to = _normalised(row.recipient)
    failures = [failure for failure in parse_ses_bounce(event) if failure.recipient == to]
    if not to or not failures:
        return "ignored"
    if row.status is CommunicationStatus.FAILED:
        return "duplicate"
    await record_delivery_failure(db, failure=failures[0], communication=row)
    if (event.get("bounce") or {}).get("bounceSubType") == "OnAccountSuppressionList":
        row.error_detail = SUPPRESSED_BEFORE
    return "bounced"


async def _complaint(db: AsyncSession, row: Communication, event: dict[str, Any]) -> str:
    complained = (event.get("complaint") or {}).get("complainedRecipients") or []
    if not _is_to(row, [r.get("emailAddress") for r in complained if isinstance(r, dict)]):
        return "ignored"
    # Idempotent per email, not per address: the same address can complain about two emails on two
    # files, and each file should show it.
    if any(detail.get("event") == "complaint" for detail in await _failure_details(db, row)):
        return "duplicate"
    loan_file = await db.get(LoanFile, row.loan_file_id)
    if loan_file is None:
        return "ignored"
    await suppress_address(
        db,
        company_id=loan_file.company_id,
        address=row.recipient or "",
        reason=SuppressionReason.COMPLAINT,
    )
    # COMMUNICATION_FAILED, not a new type: a new value needs a constraint-swap migration, and the
    # email's own status stays as it is. `detail.event` tells the two apart.
    await log_activity(
        db,
        loan_file_id=row.loan_file_id,
        activity_type=ActivityType.COMMUNICATION_FAILED,
        summary=COMPLAINT_SUMMARY,
        detail={"communication_id": str(row.id), "event": "complaint"},
    )
    return "complaint"


async def _refused(db: AsyncSession, row: Communication, event: dict[str, Any]) -> str:
    """`Reject` or `Rendering Failure`: SES took the call and then sent nothing."""
    if row.status is CommunicationStatus.FAILED:
        return "duplicate"
    reason = (event.get("reject") or {}).get("reason") or (event.get("failure") or {}).get(
        "errorMessage"
    )
    is_reject = event.get("eventType") == "Reject"
    await record_not_sent(
        db,
        communication=row,
        reason=f"SES refused it ({reason})" if reason else "SES refused it",
        code="ses_reject" if is_reject else "ses_rendering_failure",
    )
    return "rejected"


_Handler = Callable[[AsyncSession, Communication, dict[str, Any]], Awaitable[str]]

_HANDLERS: dict[str, _Handler] = {
    "Delivery": _delivery,
    "Bounce": _bounce,
    "Complaint": _complaint,
    "Reject": _refused,
    # SES documents the event type with a space; the loan-email doc writes it without.
    "Rendering Failure": _refused,
    "RenderingFailure": _refused,
}


async def apply_delivery_event(db: AsyncSession, event: dict[str, Any]) -> str:
    """Apply one SES event. ``flush`` only; the caller commits.

    Returns what it did: `delivered`, `bounced`, `complaint`, `rejected`, `duplicate`, `ignored` or
    `unmatched`. Raises on a message with no `eventType` or no `mail.messageId`: that is not an SES
    event, and the queue job leaves it to the dead-letter queue. A deleted email is `unmatched`, as
    LP-994's worker treats it.
    """
    if not isinstance(event.get("eventType"), str):
        # NOT AN SES EVENT: an SNS envelope (raw delivery switched off), an identity notification
        # (`notificationType`), anything else. Raised, so the queue job leaves it for the DLQ and
        # its alarm, instead of deleting every report as "ignored".
        raise ValueError("message without eventType")
    event_type = str(event["eventType"])
    handler = _HANDLERS.get(event_type)
    if handler is None:
        logger.info("delivery_event", event_type=event_type[:40], outcome="ignored")
        return "ignored"
    message_id = event["mail"]["messageId"]
    if not isinstance(message_id, str) or not message_id:
        raise ValueError("SES event without mail.messageId")
    row = await db.scalar(
        select(Communication).where(
            Communication.external_message_id == message_id,
            Communication.direction == CommunicationDirection.OUTBOUND,
            Communication.deleted_at.is_(None),
        )
    )
    if row is None:
        logger.info("delivery_event", event_type=event_type, outcome="unmatched")
        return "unmatched"
    outcome = await handler(db, row, event)
    await db.flush()
    logger.info(
        "delivery_event", event_type=event_type, outcome=outcome, communication_id=str(row.id)
    )
    return outcome


__all__ = [
    "COMPLAINT_SUMMARY",
    "DELIVERED_AFTER_FAILURE",
    "SUPPRESSED_BEFORE",
    "apply_delivery_event",
]
