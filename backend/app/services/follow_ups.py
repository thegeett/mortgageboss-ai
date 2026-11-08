"""Automatic follow-ups on one outbound email (LP-1013). Decisions in `loan-email.md` §3, 11-07.

Off by default. She turns it on with the Send (`send_draft(..., follow_up=...)`) or later with Start.
Then the job (`tasks/follow_ups.py`, every 15 minutes) sends a reminder when :func:`evaluate` says
it is due: on the day `interval_days` after the clock's date, at her time of day in her time zone
(:func:`due_moment`), a Saturday or Sunday moved to Monday. The reminder is:

- a reply in the same thread (`Re: <subject>`, `In-Reply-To` the original's Message-ID);
- from the person who sent the original, Cc her (the worker reads both off the approver, as for
  any Send), with a footer saying it is automatic;
- a document request gets the still-waiting list (`reminder_follow_up`), any other email the
  general wording (`follow_up_general`).

A reply from the recipient pauses it (:func:`pause_for_reply`, at ingest). Resume restarts the
clock from the latest reply. A document request whose needs are no longer requested finishes; a
failed original or a blocked recipient stops. Send now is the same reminder from whoever clicks,
at once.

EVERY REMINDER GOES THROUGH `send_draft(transmit=True)`, so it gets every check a person's Send
gets: suppression, the rate limit, the company's domain and sending switch. There is no second send
path. The reminder is its own `Communication` (`follow_up_of_id` = the original), created and sent
in one transaction, so it is never seen as an open draft.

LOGS CARRY IDS AND CODES ONLY.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import ColumnElement, Date, case, cast, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.communications.templates import TemplateKey, file_address_phrase, render
from app.models.activity_log import ActivityLog, ActivityType
from app.models.base import utcnow
from app.models.communication import (
    BodyFormat,
    Communication,
    CommunicationDirection,
    CommunicationStatus,
    FollowUpStatus,
)
from app.models.communication_needs_item import CommunicationNeedsItem
from app.models.company import Company
from app.models.inbound_message import InboundMessage, InboundRoutingState
from app.models.loan_file import LoanFile
from app.models.needs_item import NeedsItem, NeedsItemStatus
from app.models.user import User
from app.services.activity_log import log_activity
from app.services.email_draft import DRAFT_TEMPLATE, _borrower_label, greeting_name_for
from app.services.email_send import CannotSendError, send_draft
from app.services.mail_domain import file_address
from app.services.needs_items import AWAITING_COLLECTION
from app.verification.rule_engine.reasons import document_label

logger = structlog.get_logger(__name__)

#: The original's states a reminder can follow. `failed` stops it; `queued`/`sending` wait.
_WENT_OUT = (CommunicationStatus.SENT, CommunicationStatus.DELIVERED)

#: Arrived: thanked for in the reminder. Waived needs are neither waiting nor thanked for.
_ARRIVED = (NeedsItemStatus.RECEIVED, NeedsItemStatus.VERIFIED)

#: What `waiting_for` says for an email that asked for no documents.
A_REPLY = "a reply"


class Decision(StrEnum):
    """What the job does with one original email now."""

    DUE = "due"
    WAIT = "wait"
    FINISH = "finish"
    STOP = "stop"


@dataclass(frozen=True)
class Needs:
    """The original's needs, split. Empty both ways for an email that asked for no documents."""

    waiting: list[NeedsItem]
    received: list[NeedsItem]
    is_document_request: bool


async def needs_of(db: AsyncSession, original: Communication) -> Needs:
    """The needs the original asked for, through the communication-needs link (LP-809)."""
    rows = list(
        (
            await db.execute(
                select(NeedsItem)
                .join(CommunicationNeedsItem, CommunicationNeedsItem.needs_item_id == NeedsItem.id)
                .where(
                    CommunicationNeedsItem.communication_id == original.id,
                    NeedsItem.deleted_at.is_(None),
                )
                .order_by(CommunicationNeedsItem.created_at, NeedsItem.id)
            )
        )
        .scalars()
        .all()
    )
    return Needs(
        waiting=[n for n in rows if n.status in AWAITING_COLLECTION],
        received=[n for n in rows if n.status in _ARRIVED],
        is_document_request=bool(rows),
    )


def is_original(row: Communication) -> bool:
    """An outbound email a person sent with Send, not itself a reminder."""
    return (
        row.direction is CommunicationDirection.OUTBOUND
        and row.follow_up_of_id is None
        and row.send_requested_at is not None
        and row.deleted_at is None
    )


def _weekday(day: date) -> date:
    """A Saturday or Sunday moved to the following Monday."""
    return day + timedelta(days=7 - day.weekday()) if day.weekday() >= 5 else day


def due_moment(row: Communication) -> datetime | None:
    """When the next automatic reminder is due (§3 "Follow-up timing", 11-07).

    The clock's date in her time zone, plus the interval in days; a weekend day moved to Monday; at
    her time of day in that zone. By the wall clock, so a 09:30 New York follow-up stays 09:30
    across a daylight-saving change (`zoneinfo` gives that day its own offset).
    """
    if row.follow_up_clock_at is None or row.follow_up_time is None or not row.follow_up_tz:
        return None
    zone = ZoneInfo(row.follow_up_tz)
    day = row.follow_up_clock_at.astimezone(zone).date() + timedelta(
        days=row.follow_up_interval_days
    )
    return datetime.combine(_weekday(day), row.follow_up_time, tzinfo=zone)


def due_moment_sql() -> ColumnElement[datetime]:
    """:func:`due_moment` in SQL, for the job to pick and order candidates; Postgres reads the
    same IANA names. :func:`evaluate` still decides, on the row."""
    day = (
        cast(func.timezone(Communication.follow_up_tz, Communication.follow_up_clock_at), Date)
        + Communication.follow_up_interval_days
    )
    weekend = case(
        (extract("isodow", day) == 6, 2),
        (extract("isodow", day) == 7, 1),
        else_=0,
    )
    return func.timezone(Communication.follow_up_tz, day + weekend + Communication.follow_up_time)


async def evaluate(db: AsyncSession, row: Communication, *, now: datetime) -> Decision:
    """Whether a reminder is due on this original email now — THE rule, used by the job.

    Due when all hold: follow-up `on`; the email `sent` or `delivered` (`failed` → stop); fewer
    automatic reminders than the count; :func:`due_moment` reached; for a document request, at least
    one need still requested (none → finish).
    """
    if not is_original(row) or row.follow_up_status is not FollowUpStatus.ON:
        return Decision.WAIT
    if row.status is CommunicationStatus.FAILED:
        return Decision.STOP
    if row.status not in _WENT_OUT:
        return Decision.WAIT
    if row.follow_up_auto_sent >= row.follow_up_max_auto:
        return Decision.WAIT
    due = due_moment(row)
    if due is None or now < due:
        return Decision.WAIT
    needs = await needs_of(db, row)
    if needs.is_document_request and not needs.waiting:
        return Decision.FINISH
    return Decision.DUE


def _mailbox(address: str | None) -> str:
    return (address or "").strip().lower()


def _replies_from_recipient(row: Communication) -> list[ColumnElement[bool]]:
    """The recipient's own messages on this file: routed, not an out-of-office, a bounce or bulk."""
    return [
        InboundMessage.loan_file_id == row.loan_file_id,
        InboundMessage.routing_state == InboundRoutingState.ROUTED,
        func.lower(func.trim(InboundMessage.from_address)) == _mailbox(row.recipient),
        InboundMessage.is_auto_reply.is_(False),
        InboundMessage.is_dsn.is_(False),
        InboundMessage.is_bulk.is_(False),
    ]


async def has_reply_since(db: AsyncSession, row: Communication) -> bool:
    """Whether the recipient has written to this file since the clock started.

    The job's re-check before it sends: it also sees a reply that reached the file another way (moved
    from the company Inbox) after the clock started, which the ingest hook does not.
    """
    if row.follow_up_clock_at is None or not _mailbox(row.recipient):
        return False
    found = await db.scalar(
        select(InboundMessage.id)
        .where(*_replies_from_recipient(row), InboundMessage.created_at > row.follow_up_clock_at)
        .limit(1)
    )
    return found is not None


async def resume_clock(db: AsyncSession, row: Communication) -> datetime:
    """Where Resume restarts the clock: the recipient's LATEST reply, not the first.

    A paused follow-up stays paused through her second and third replies, and only the first set
    `follow_up_paused_at`. Restarting from it left the later replies "since the clock", so the
    job's re-check paused it again at the first due time and nothing ever went (review, finding 1).

    Never earlier than the clock already is: Send now while paused restarts the clock, and Resume
    after it must not move it back to the reply and make an automatic reminder due a day after.
    """
    latest = (
        await db.scalar(
            select(func.max(InboundMessage.created_at)).where(*_replies_from_recipient(row))
        )
        if _mailbox(row.recipient)
        else None
    )
    moments = [
        m for m in (row.follow_up_paused_at, latest, row.follow_up_clock_at) if m is not None
    ]
    return max(moments) if moments else utcnow()


# --------------------------------------------------------------------------------------------- #
# The reminder email
# --------------------------------------------------------------------------------------------- #
def reply_subject(subject: str | None) -> str:
    """`Re: <subject>`, without doubling a `Re:` already there."""
    text = (subject or "").strip()
    return text if text.lower().startswith("re:") else f"Re: {text}"


def thread_message_id(external_message_id: str | None) -> str | None:
    """The original's Message-ID as a header value (LP-998).

    SES returns a bare id and the message arrives as `<id@email.amazonses.com>`; the SMTP sender
    (dev, MailHog) returns the header's own value, already in angle brackets.
    """
    if not external_message_id:
        return None
    if external_message_id.startswith("<"):
        return external_message_id
    return f"<{external_message_id}@email.amazonses.com>"


def automatic_footer(company_name: str, sender_name: str) -> str:
    return (
        f"This is an automatic reminder from {company_name}'s loan file system. "
        f"Replies go straight to {sender_name}."
    )


def _plain_name(need: NeedsItem) -> str:
    """The document's plain name for the thank-you ("W-2", "bank statement"); the catalog's
    borrower label carries a qualifier ("W-2s — the last two years") that belongs in an ask."""
    if need.needs_type:
        return document_label(need.needs_type)
    return need.title


def _and_list(words: list[str]) -> str:
    if len(words) <= 2:
        return " and ".join(words)
    return ", ".join(words[:-1]) + f" and {words[-1]}"


@dataclass(frozen=True)
class ReminderText:
    template_key: TemplateKey
    template_version: str
    subject: str
    #: `$processor_name` is left for `send_draft` to sign with the approver.
    body: str


async def build_reminder_text(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    original: Communication,
    automatic_footer_text: str | None,
) -> ReminderText:
    """The reminder's words: the still-waiting list for a document request, the general wording
    otherwise. The greeting is the original's (the borrower's first name on her request, the
    generic one to anybody else)."""
    greeting = await greeting_name_for(db, draft=original, loan_file=loan_file)
    subject = reply_subject(original.subject)
    needs = await needs_of(db, original)
    if needs.is_document_request:
        received = [_plain_name(n) for n in needs.received]
        # The file address only where the original carried it: LP-843 keeps it from third parties.
        address = (
            await file_address(db, loan_file)
            if original.template_key == DRAFT_TEMPLATE.value
            else None
        )
        rendered = render(
            TemplateKey.REMINDER_FOLLOW_UP,
            {
                "borrower_first_name": greeting,
                "processor_name": "$processor_name",
                "loan_reference": loan_file.display_id,
                "document_list": "\n".join(f"- {_borrower_label(n)}" for n in needs.waiting),
                "file_address_phrase": file_address_phrase(address),
                "received_sentence": (
                    f" We've received your {_and_list(received)}, thank you." if received else ""
                ),
            },
        )
    else:
        rendered = render(
            TemplateKey.FOLLOW_UP_GENERAL,
            {
                "borrower_first_name": greeting,
                "processor_name": "$processor_name",
                "subject_line": subject,
            },
        )
    body = rendered.body
    if automatic_footer_text:
        body = f"{body}\n\n{automatic_footer_text}"
    return ReminderText(rendered.template_key, rendered.version, subject, body)


async def send_reminder(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    original: Communication,
    sender: User,
    automatic: bool,
) -> Communication:
    """Create the reminder and send it through `send_draft(transmit=True)`. ``flush`` only.

    In a savepoint, so a refusal (`CannotSendError`, re-raised) leaves no reminder row behind.
    `automatic`: from the original's sender with the footer, `initiated_by_user_id` empty (the
    worker adds `Auto-Submitted` to such a reminder). Otherwise Send now: from `sender`, no footer.
    """
    company = await db.get(Company, loan_file.company_id)
    footer = (
        automatic_footer(company.name if company else "", sender.full_name) if automatic else None
    )
    text = await build_reminder_text(
        db, loan_file=loan_file, original=original, automatic_footer_text=footer
    )
    async with db.begin_nested():
        reminder = Communication(
            loan_file_id=loan_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationStatus.DRAFT,
            recipient=original.recipient,
            subject=text.subject,
            body=text.body,
            body_format=BodyFormat.PLAIN,
            party=original.party,
            template_key=text.template_key.value,
            template_version=text.template_version,
            in_reply_to_message_id=thread_message_id(original.external_message_id),
            follow_up_of_id=original.id,
            initiated_by_user_id=None if automatic else sender.id,
        )
        db.add(reminder)
        await db.flush()
        await send_draft(
            db,
            loan_file=loan_file,
            draft_id=reminder.id,
            recipient=original.recipient or "",
            body=text.body,
            subject=text.subject,
            approver_user_id=sender.id,
            transmit=True,
        )
        await _name_the_send(
            db,
            loan_file=loan_file,
            reminder=reminder,
            summary=(
                f"Automatic reminder sent (for {sender.full_name})"
                if automatic
                else "Sent a reminder"
            ),
        )
    return reminder


async def _name_the_send(
    db: AsyncSession, *, loan_file: LoanFile, reminder: Communication, summary: str
) -> None:
    """`send_draft`'s activity line reads "Sent a document request for 0 item(s)"; this names the
    reminder instead, as `condition_drafts._name_the_send` does for a condition email."""
    rows = (
        await db.execute(
            select(ActivityLog).where(
                ActivityLog.loan_file_id == loan_file.id,
                ActivityLog.activity_type == ActivityType.COMMUNICATION_SENT,
            )
        )
    ).scalars()
    for row in rows:
        if (row.detail or {}).get("communication_id") == str(reminder.id):
            row.summary = summary
            row.detail = {**(row.detail or {}), "follow_up_of_id": str(reminder.follow_up_of_id)}
    await db.flush()


async def original_sender(db: AsyncSession, original: Communication) -> User | None:
    """Who sent the original: the approver on its evidence record, as the worker reads it."""
    from app.models.communication_evidence import CommunicationEvidence, EvidenceEvent

    approver_id = await db.scalar(
        select(CommunicationEvidence.approver_user_id).where(
            CommunicationEvidence.communication_id == original.id,
            CommunicationEvidence.event == EvidenceEvent.SENT,
        )
    )
    return await db.get(User, approver_id) if approver_id else None


# --------------------------------------------------------------------------------------------- #
# A reply pauses it (at ingest)
# --------------------------------------------------------------------------------------------- #
async def pause_for_reply(db: AsyncSession, *, message: InboundMessage, loan_file: LoanFile) -> int:
    """Pause every follow-up on this file whose recipient sent `message`. Returns how many.

    Called by `apply_routing` on a message's first insert. Not for a delivery notice, an
    out-of-office, bulk mail, or a message routing rejected.
    """
    if (
        message.routing_state is not InboundRoutingState.ROUTED
        or message.is_auto_reply
        or message.is_dsn
        or message.is_bulk
        or not _mailbox(message.from_address)
    ):
        return 0
    rows = list(
        (
            await db.execute(
                select(Communication).where(
                    Communication.loan_file_id == loan_file.id,
                    Communication.direction == CommunicationDirection.OUTBOUND,
                    Communication.follow_up_of_id.is_(None),
                    Communication.follow_up_status == FollowUpStatus.ON,
                    Communication.deleted_at.is_(None),
                    func.lower(func.trim(Communication.recipient))
                    == _mailbox(message.from_address),
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0
    now = utcnow()
    for row in rows:
        row.follow_up_status = FollowUpStatus.PAUSED
        row.follow_up_paused_at = now
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.COMMUNICATION_RECEIVED,
        summary=f"Follow-up paused: {rows[0].recipient} replied",
        detail={
            "kind": "follow_up_paused",
            "inbound_message_id": str(message.id),
            "follow_up_communication_ids": [str(row.id) for row in rows],
        },
    )
    await db.flush()
    return len(rows)


# --------------------------------------------------------------------------------------------- #
# What the screen shows (LP-1014)
# --------------------------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FollowUpView:
    status: str
    interval_days: int
    max_auto: int
    auto_sent: int
    clock_at: datetime | None
    paused_at: datetime | None
    #: When the next automatic reminder is due (:func:`due_moment`); the job sends it within 15
    #: minutes. None when none will go (not `on`, or the count is reached).
    next_reminder_at: datetime | None
    #: Her time of day (`HH:MM`) and time zone; None until it is first turned on.
    time: str | None
    tz: str | None
    #: Still-missing needs by their titles, or [`A_REPLY`] for an email that asked for no documents.
    waiting_for: list[str]


async def follow_up_view(db: AsyncSession, row: Communication) -> FollowUpView | None:
    """The follow-up on an original email; None for anything that cannot have one."""
    if not is_original(row):
        return None
    needs = await needs_of(db, row)
    due = due_moment(row)
    next_at = (
        due
        if row.follow_up_status is FollowUpStatus.ON
        and row.follow_up_auto_sent < row.follow_up_max_auto
        else None
    )
    return FollowUpView(
        status=row.follow_up_status.value,
        interval_days=row.follow_up_interval_days,
        max_auto=row.follow_up_max_auto,
        auto_sent=row.follow_up_auto_sent,
        clock_at=row.follow_up_clock_at,
        paused_at=row.follow_up_paused_at,
        next_reminder_at=next_at,
        time=row.follow_up_time.strftime("%H:%M") if row.follow_up_time else None,
        tz=row.follow_up_tz,
        waiting_for=([n.title for n in needs.waiting] if needs.is_document_request else [A_REPLY]),
    )


__all__ = [
    "A_REPLY",
    "CannotSendError",
    "Decision",
    "FollowUpView",
    "Needs",
    "automatic_footer",
    "build_reminder_text",
    "due_moment",
    "due_moment_sql",
    "evaluate",
    "follow_up_view",
    "has_reply_since",
    "is_original",
    "needs_of",
    "original_sender",
    "pause_for_reply",
    "reply_subject",
    "resume_clock",
    "send_reminder",
    "thread_message_id",
]
