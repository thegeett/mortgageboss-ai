"""LP-994 — the worker sends the email a person approved. Only the worker sends mail (rule 8).

The API's Send (`send_draft(..., transmit=True)`) runs every guard, records the message `queued`
with `send_requested_at`, commits, and enqueues :func:`send_communication`. This module does the
rest: `queued → sending → sent`.

THE SAFETY RULES, each enforced here rather than assumed:

- **Atomic claim.** One `UPDATE … WHERE status = 'queued' … RETURNING id`, committed before
  anything else. A second task for the same row (a duplicate enqueue, the re-enqueue job, a broker
  redelivery) finds nothing to claim and stops, so a row is sent at most once.
- **Only what a person asked for.** The claim also requires `send_requested_at`, which only a
  person's Send sets. LP-815's automatic replies are `queued` without it, so they are never sent
  (§3 "Automatic replies to inbound").
- **No automatic retry.** The task has no retry policy and the SES client makes one attempt
  (LP-993). A clean failure (`failed`) unwinds the request; the processor can send again.
- **Not confirmed is not failed.** When the provider may have taken the email (`SendError` with
  `outcome_unknown`, or anything unexpected during the call) the row stays `sending` with a note,
  and nothing is unwound: the borrower may have it.

LP-995 — `read_delivery_events` reads what SES reported about each sent email from the events queue
and applies it with `services.delivery_events.apply_delivery_event`.

LOGS CARRY IDS AND ERROR CODES ONLY. Never a recipient, subject, body, or the provider's own message,
which can quote the recipient. `SendError` is caught explicitly, so its chained provider exception
never reaches a traceback.
"""

import asyncio
import json
from datetime import timedelta
from email.message import EmailMessage
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.base import utcnow
from app.models.communication import (
    NOT_CONFIRMED_PREFIX,
    BodyFormat,
    Communication,
    CommunicationStatus,
)
from app.models.communication_evidence import CommunicationEvidence, EvidenceEvent
from app.models.company import Company
from app.models.loan_file import LoanFile
from app.models.user import User
from app.services.bounce_handling import record_not_sent
from app.services.delivery_events import apply_delivery_event
from app.services.mail_domain import file_address
from app.services.mail_sender import MailSender, SendError, get_mail_sender
from app.services.outbound_mime import build_mime
from app.storage import get_mail_storage
from app.tasks.base import BaseTask, run_async, task_session
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

#: A queued Send older than this was not picked up (broker down at enqueue, worker stopped). The
#: re-enqueue job hands it to the worker again; the atomic claim makes a duplicate harmless.
STALE_AFTER = timedelta(minutes=5)
REQUEUE_BATCH = 50


class _NotSent(Exception):
    """A clean failure: nothing reached the provider. `reason` is for the processor, `code` for logs."""

    def __init__(self, reason: str, code: str) -> None:
        super().__init__(code)
        self.reason = reason
        self.code = code


async def _claim(db: AsyncSession, communication_id: UUID) -> bool:
    """`queued` → `sending`, atomically, only for a person's Send. Committed before anything else."""
    claimed = await db.scalar(
        update(Communication)
        .where(
            Communication.id == communication_id,
            Communication.status == CommunicationStatus.QUEUED,
            Communication.send_requested_at.is_not(None),
            Communication.deleted_at.is_(None),
        )
        .values(status=CommunicationStatus.SENDING)
        .returning(Communication.id)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return claimed is not None


async def _build(db: AsyncSession, row: Communication) -> tuple[EmailMessage, MailSender]:
    loan_file = await db.get(LoanFile, row.loan_file_id)
    if loan_file is None:
        raise _NotSent("the loan file is gone", "no_loan_file")
    company = await db.get(Company, loan_file.company_id)
    # The approver is on the evidence record `send_draft` wrote with the row.
    approver_id = await db.scalar(
        select(CommunicationEvidence.approver_user_id).where(
            CommunicationEvidence.communication_id == row.id,
            CommunicationEvidence.event == EvidenceEvent.SENT,
        )
    )
    approver = await db.get(User, approver_id) if approver_id else None
    if company is None or approver is None:
        raise _NotSent("no approver on record", "no_approver")
    # Read again, not trusted from the click: the domain may have been switched off since.
    address = await file_address(db, loan_file)
    if address is None:
        raise _NotSent("this company can't send email from the app", "no_domain")
    sender = get_mail_sender()
    if sender is None:
        raise _NotSent("sending email is not set up", "no_sender")
    try:
        message = build_mime(
            from_name=f"{approver.full_name}, {company.name}",
            from_address=address,
            to=row.recipient or "",
            cc=approver.email,
            reply_to=address,
            subject=row.subject or "",
            body=row.body or "",
            html=row.body_format is BodyFormat.HTML,
            in_reply_to=row.in_reply_to_message_id,
            references=[row.in_reply_to_message_id] if row.in_reply_to_message_id else None,
        )
    except ValueError as exc:
        raise _NotSent("the email could not be built", "build_failed") from exc
    return message, sender


async def _fail(db: AsyncSession, row: Communication, *, reason: str, code: str) -> None:
    """Clean failure: nothing went. The needs go back to pending so the next request asks again."""
    await record_not_sent(db, communication=row, reason=reason, code=code)
    await db.commit()
    logger.warning("send_failed", communication_id=str(row.id), error_code=code)


async def _not_confirmed(db: AsyncSession, row: Communication, *, code: str) -> None:
    """The email may have gone. Left `sending` for a person; nothing unwound, never retried."""
    row.error_detail = f"{NOT_CONFIRMED_PREFIX}{code}. Check before sending again."
    await db.commit()
    logger.warning("send_not_confirmed", communication_id=str(row.id), error_code=code)


async def _send_communication(db: AsyncSession, communication_id: str) -> str:
    """Send one claimed row. Returns what happened (`sent`, `failed`, `not_confirmed`, `skipped`)."""
    try:
        pk = UUID(communication_id)
    except ValueError:
        logger.warning("send_skipped", communication_id=communication_id)
        return "skipped"
    if not await _claim(db, pk):
        logger.info("send_skipped", communication_id=str(pk))
        return "skipped"
    row = await db.get(Communication, pk, populate_existing=True)
    if row is None:  # claimed a moment ago in this session; cannot be gone
        return "skipped"

    try:
        message, sender = await _build(db, row)
        path = f"outbound/{row.id}.eml"
        try:
            await get_mail_storage().save_at(storage_path=path, content=message.as_bytes())
        except Exception as exc:
            raise _NotSent("the copy could not be saved", f"storage_{type(exc).__name__}") from exc
        row.raw_storage_path = path
        await db.commit()
    except _NotSent as exc:
        await _fail(db, row, reason=exc.reason, code=exc.code)
        return "failed"
    except Exception as exc:
        # LP-994 REVIEW — ANYTHING ELSE BEFORE THE PROVIDER CALL IS STILL A CLEAN FAILURE: a database
        # error, a bug in building the body, the commit after the copy was saved. Nothing has been
        # handed to the provider, so leaving the row `sending` ("not confirmed") would tell a person
        # to check on an email that cannot have gone, and no job would ever pick it up again. Rolled
        # back first, since the session may be unusable; the claim was committed, so the row reloads
        # as `sending`. Only the class name is kept, like every other code here.
        await db.rollback()
        await db.refresh(row)
        await _fail(db, row, reason="something went wrong before sending", code=type(exc).__name__)
        return "failed"

    try:
        provider_id = await asyncio.to_thread(sender.send, message)
    except SendError as exc:
        if exc.outcome_unknown:
            await _not_confirmed(db, row, code=exc.code)
            return "not_confirmed"
        await _fail(db, row, reason=f"the mail provider refused it ({exc.code})", code=exc.code)
        return "failed"
    except Exception as exc:  # not ours to classify (a soft time limit, a bug): it may have gone
        await _not_confirmed(db, row, code=type(exc).__name__)
        return "not_confirmed"

    # A CRASH BETWEEN HERE AND THE COMMIT leaves the row `sending` with no MessageId. That is the
    # "not confirmed" case by design: the claim is already committed, so no later task can send it
    # again, and a person checks (LP-997's "not confirmed" notice). LP-995's delivery events cannot
    # settle it: they match on the MessageId, which this crash never stored, so they come back
    # `unmatched`.
    row.external_message_id = provider_id
    row.status = CommunicationStatus.SENT
    row.sent_at = utcnow()
    row.error_detail = None
    await db.commit()
    logger.info("send_sent", communication_id=str(row.id))
    return "sent"


async def _run_send(communication_id: str) -> str:
    async with task_session() as db:
        return await _send_communication(db, communication_id)


@celery_app.task(base=BaseTask, name="communications.send")  # type: ignore[untyped-decorator]
def send_communication(communication_id: str) -> str:
    """Send one queued, person-approved email. No retry policy, on purpose (module docstring)."""
    return run_async(_run_send(communication_id))


async def _requeue_stale(db: AsyncSession) -> list[str]:
    """Queued Sends older than `STALE_AFTER`, oldest first, at most `REQUEUE_BATCH`.

    Rows without `send_requested_at` (LP-815's automatic replies) are never selected.
    """
    ids = (
        await db.scalars(
            select(Communication.id)
            .where(
                Communication.status == CommunicationStatus.QUEUED,
                Communication.send_requested_at.is_not(None),
                Communication.send_requested_at < utcnow() - STALE_AFTER,
                Communication.deleted_at.is_(None),
            )
            .order_by(Communication.send_requested_at)
            .limit(REQUEUE_BATCH)
        )
    ).all()
    requeued: list[str] = []
    for pk in ids:
        try:
            send_communication.delay(str(pk))
        except Exception:
            logger.warning("send_requeue_failed", communication_id=str(pk))
            continue
        requeued.append(str(pk))
    if requeued:
        logger.info("send_requeued", count=len(requeued))
    return requeued


async def _run_requeue() -> list[str]:
    async with task_session() as db:
        return await _requeue_stale(db)


@celery_app.task(base=BaseTask, name="communications.requeue_stale")  # type: ignore[untyped-decorator]
def requeue_stale() -> int:
    """Beat, every 5 minutes: hand stale queued Sends to the worker again."""
    return len(run_async(_run_requeue()))


#: LP-995 — the events queue is read in batches of ten (the SQS maximum), at most five per run, so
#: one run handles up to 50 events and finishes well inside its one-minute interval.
EVENTS_BATCH = 10
EVENTS_MAX_BATCHES = 5


def _events_client() -> Any:
    import boto3
    from botocore.config import Config

    return boto3.client(
        "sqs",
        region_name=settings.s3_region,
        config=Config(connect_timeout=5, read_timeout=10, retries={"total_max_attempts": 2}),
    )


async def _read_delivery_events(db: AsyncSession, client: Any, queue_url: str) -> int:
    """Apply each event and delete it; leave anything that fails for SQS to redeliver.

    COMMIT, THEN DELETE. A crash between the two redelivers an event already applied, and the
    handler answers `duplicate`. The other order would lose an event.

    NOT DELETED: a body that is not JSON, and any event the handler raises on. Each is rolled back
    and logged by id and error class, and the rest of the batch goes on. After three receives SQS
    moves it to the dead-letter queue, which alarms (LP-987). `unmatched`, `ignored` and `duplicate`
    are handled, so they are deleted.

    AN SQS ERROR DOES NOT END THE BATCH. A failed delete is logged and the next message handled: the
    event is committed, so its redelivery answers `duplicate`. A failed receive ends the run; the
    next one, a minute later, tries again.
    """
    handled = 0
    for _ in range(EVENTS_MAX_BATCHES):
        try:
            received = await asyncio.to_thread(
                client.receive_message,
                QueueUrl=queue_url,
                MaxNumberOfMessages=EVENTS_BATCH,
                WaitTimeSeconds=1,
            )
        except Exception as exc:
            logger.warning("delivery_events_receive_failed", error=type(exc).__name__)
            break
        messages = received.get("Messages") or []
        for message in messages:
            sqs_id = message.get("MessageId")
            try:
                await apply_delivery_event(db, json.loads(message["Body"]))
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.warning(
                    "delivery_event_failed", sqs_message_id=sqs_id, error=type(exc).__name__
                )
                continue
            try:
                await asyncio.to_thread(
                    client.delete_message,
                    QueueUrl=queue_url,
                    ReceiptHandle=message["ReceiptHandle"],
                )
            except Exception as exc:
                logger.warning(
                    "delivery_event_delete_failed", sqs_message_id=sqs_id, error=type(exc).__name__
                )
                continue
            handled += 1
        if len(messages) < EVENTS_BATCH:
            break
    return handled


async def _run_read_delivery_events(queue_url: str) -> int:
    async with task_session() as db:
        return await _read_delivery_events(db, _events_client(), queue_url)


@celery_app.task(base=BaseTask, name="communications.read_delivery_events")  # type: ignore[untyped-decorator]
def read_delivery_events() -> int:
    """Beat, every minute: apply what SES reported about sent emails (LP-995)."""
    queue_url = settings.events_queue_url
    if not queue_url:
        logger.debug("delivery_events_not_configured")
        return 0
    return run_async(_run_read_delivery_events(queue_url))
