"""Replying to a message, and composing one with nothing behind it (LP-818).

WHY THIS IS A SERVICE AND NOT A BUTTON. §C.5 states the blockage precisely: LP-809 creates a draft
*plus* a `communication_needs_items` join, and LP-811's send endpoint requires a `draft_id`. A reply
to *"is page 4 really needed?"* has no needs behind it — so under the existing shape it could not
become a draft, and therefore could not be sent. Spec 4.3 asks for reply and nothing existed.

THE NEEDS-LESS DRAFT NEEDS NO COLUMN, and that is worth stating because it looks like it should. The
one-open-draft index is `(loan_file_id, template_key) WHERE status = 'draft'` and carries no
`NULLS NOT DISTINCT`, so Postgres treats every NULL `template_key` as distinct: several open replies
on one file coexist, and none of them collides with the accumulating request. `get_open_draft` reads
by that template key too, so a reply is invisible to the request path rather than competing with it.

A NULL `template_key` is also the truth. `Communication`'s own docstring says the column is "NULL for
inbound mail and for anything composed by hand", and a reply is composed by hand.

WHO A REPLY GOES TO COMES FROM THE STORED MESSAGE, never from a header at reply time. The address is
read off the `inbound_message` row that was recorded when the message arrived — the same row the
routing decision was made against — so a reply cannot be redirected by anything that happened
afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.helpers import only_active
from app.models.inbound_message import InboundMessage
from app.models.loan_file import LoanFile
from app.services.activity_log import log_activity
from app.services.inbound_participants import normalise_address

logger = get_logger(__name__)


class CannotReplyError(Exception):
    """The reply cannot be prepared. Always names the rule that stopped it."""


@dataclass(frozen=True)
class ReplyContext:
    """What a reply needs to know about the message it answers."""

    recipient: str
    subject: str
    in_reply_to_message_id: str | None


def _reply_subject(original: str | None) -> str:
    """`Re: …`, added once.

    NOT `Re: Re: Re:`. Mail clients differ about whether they add another, and a subject that grows a
    prefix per exchange is the visible sign of a thread nobody is managing. Case-insensitive because
    some clients write `RE:` and some `Re:`.
    """
    subject = (original or "").strip()
    if not subject:
        return "Re: your message"
    return subject if subject[:3].lower() == "re:" else f"Re: {subject}"


async def reply_context(
    db: AsyncSession, *, loan_file: LoanFile, communication_id: UUID
) -> ReplyContext:
    """Who to answer, what to call it, and what to thread it to.

    THE RECIPIENT COMES FROM THE STORED `inbound_message`, not from the `Communication` and not from
    a header read now. LP-805 deliberately writes no sender onto the Communication — "copying them
    here would put borrower prose in a second place with its own exposure decisions" — so the
    address lives on the message row, which is also the row the routing decision was made against.
    """
    original = await db.get(Communication, communication_id)
    if original is None or original.deleted_at is not None:
        raise CannotReplyError("No such message on this loan file.")
    if original.loan_file_id != loan_file.id:
        # THE SAME MESSAGE AS "no such message". Telling them apart would confirm the id exists —
        # an oracle over another tenant's rows, the same reasoning as LP-806's 404.
        raise CannotReplyError("No such message on this loan file.")
    if original.direction is not CommunicationDirection.INBOUND:
        raise CannotReplyError("Only a message that arrived can be replied to.")
    if original.inbound_message_id is None:
        raise CannotReplyError("The original message is no longer available to reply to.")

    message = await db.get(InboundMessage, original.inbound_message_id)
    if message is None or message.deleted_at is not None:
        raise CannotReplyError("The original message is no longer available to reply to.")

    recipient = normalise_address(message.from_address)
    if recipient is None:
        # A message with no usable `From` is malformed or a bounce. Replying to nowhere is at best
        # wasted and at worst backscatter — the same rule LP-815's nudge applies.
        raise CannotReplyError("That message has no address to reply to.")

    return ReplyContext(
        recipient=recipient,
        subject=_reply_subject(message.subject),
        in_reply_to_message_id=message.message_id,
    )


async def create_reply_draft(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    communication_id: UUID,
    body: str,
    actor_user_id: UUID,
) -> Communication:
    """A needs-less draft answering one inbound message. ``flush`` only; the caller commits.

    THREADED VIA `in_reply_to_message_id`. RFC 5322 §3.6.4: without it the borrower sees an unrelated
    message rather than an answer, and their client cannot collapse the two — which for a borrower
    juggling a mortgage is the difference between one conversation and six.

    It is also what keeps THEIR next reply on rung 2: their client will carry our id in `References`,
    and rung 2 matches the whole array against ids we generated. That only works while
    `external_message_id` means "this message's own id", which is why this column exists separately.
    """
    if not (body or "").strip():
        raise CannotReplyError("An empty reply cannot be saved.")

    context = await reply_context(db, loan_file=loan_file, communication_id=communication_id)
    reply = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.DRAFT,
        recipient=context.recipient,
        subject=context.subject,
        body=body,
        # NULL — see the module docstring. It is the truth (composed by hand) and it is what lets
        # several replies be open at once without colliding on the one-open-draft index.
        template_key=None,
        template_version=None,
        in_reply_to_message_id=context.in_reply_to_message_id,
        initiated_by_user_id=actor_user_id,
    )
    db.add(reply)
    await db.flush()
    # METADATA ONLY — never the body, never the recipient.
    logger.info("reply_draft_created", loan_file_id=str(loan_file.id))
    return reply


async def create_compose_draft(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    recipient: str,
    subject: str,
    body: str,
    actor_user_id: UUID,
) -> Communication:
    """A message with nothing behind it — no needs, no message being answered.

    Spec 4.3's "compose". The same needs-less shape as a reply, without the threading, and it exists
    because a processor telling a borrower "your file went to underwriting" is answering nothing and
    requesting nothing, and had no way to record that it happened.
    """
    address = normalise_address(recipient)
    if address is None:
        raise CannotReplyError("That is not an address a message can be sent to.")
    if not (body or "").strip():
        raise CannotReplyError("An empty message cannot be saved.")
    if not (subject or "").strip():
        # REFUSED RATHER THAN DEFAULTED. A subject a system invented is one a borrower cannot
        # recognise, and the request path never has this problem because its template supplies one.
        raise CannotReplyError("A message needs a subject.")

    draft = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.DRAFT,
        recipient=address,
        subject=subject.strip(),
        body=body,
        template_key=None,
        template_version=None,
        initiated_by_user_id=actor_user_id,
    )
    db.add(draft)
    await db.flush()
    logger.info("compose_draft_created", loan_file_id=str(loan_file.id))
    return draft


async def set_important(
    db: AsyncSession, *, loan_file: LoanFile, communication_id: UUID, important: bool
) -> Communication:
    """Flag a message, or unflag it. ``flush`` only.

    A PROCESSOR'S OWN JUDGEMENT. Nothing computes it, no rule sets it and no model suggests it — the
    standing rule is that AI may classify and extract and may not decide, and "this matters" is the
    most decision-shaped flag on the record.
    """
    message = await _scoped(db, loan_file=loan_file, communication_id=communication_id)
    message.is_important = important
    await db.flush()
    return message


async def mark_read(
    db: AsyncSession, *, loan_file: LoanFile, communication_id: UUID, read: bool = True
) -> Communication:
    """Record that somebody looked at an inbound message, or put it back to unread.

    REVERSIBLE, DELIBERATELY. A processor who opens something at the end of the day and cannot deal
    with it needs to put it back, and a one-way flag makes the badge a thing to be got rid of rather
    than a thing to act on.
    """
    message = await _scoped(db, loan_file=loan_file, communication_id=communication_id)
    if message.direction is not CommunicationDirection.INBOUND:
        # OUTBOUND IS NEVER UNREAD — we wrote it. Refused rather than ignored, because a caller
        # marking a sent message read is confused about something and a silent success hides it.
        raise CannotReplyError("Only a message that arrived can be marked read.")
    message.read_at = utcnow() if read else None
    await db.flush()
    return message


async def unread_count(db: AsyncSession, *, loan_file: LoanFile) -> int:
    """How many arrived messages nobody has looked at.

    THE BADGE. §C.5: "without the badge the queue is pull-only and an evening reply sits unseen until
    she happens to open the tab." Counted rather than derived from a list, so the number is right on
    a file with more history than one page.
    """
    return int(
        await db.scalar(
            only_active(
                select(func.count())
                .select_from(Communication)
                .where(
                    Communication.loan_file_id == loan_file.id,
                    Communication.direction == CommunicationDirection.INBOUND,
                    Communication.read_at.is_(None),
                ),
                Communication,
            )
        )
        or 0
    )


async def _scoped(
    db: AsyncSession, *, loan_file: LoanFile, communication_id: UUID
) -> Communication:
    """One message, only if it is on this file. The route proves the caller owns the FILE; the
    message id is a path parameter anybody can type."""
    message = await db.get(Communication, communication_id)
    if message is None or message.deleted_at is not None or message.loan_file_id != loan_file.id:
        raise CannotReplyError("No such message on this loan file.")
    return message


async def log_reply_sent(
    db: AsyncSession, *, loan_file: LoanFile, reply: Communication, actor_user_id: UUID
) -> None:
    """Record that a reply went out.

    A SEPARATE ACTIVITY FROM THE REQUEST SEND, because LP-812's timeline drops every
    `COMMUNICATION_*` activity as a duplicate of the Communication it describes — so this exists for
    the AUDIT trail, which is a different reader from the timeline, and the timeline correctly shows
    the reply once.
    """
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.COMMUNICATION_SENT,
        summary="A reply was sent",
        actor_user_id=actor_user_id,
        # Metadata only — never the body, the subject or the recipient.
        detail={"communication_id": str(reply.id), "kind": "reply"},
    )


__all__ = [
    "CannotReplyError",
    "ReplyContext",
    "create_compose_draft",
    "create_reply_draft",
    "log_reply_sent",
    "mark_read",
    "reply_context",
    "set_important",
    "unread_count",
]
