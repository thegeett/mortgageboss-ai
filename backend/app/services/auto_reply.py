"""The borrower nudge — one automatic reply, and everything that stops it becoming a loop (LP-815).

WHY IT EXISTS. `phase4.md` §6 puts it plainly: ingesting is different from sending. We did not choose
the transport — the borrower already emailed a plaintext bank statement, so we inherit the artifact,
not the exposure. What we owe is to name the email channel as an assessed risk and to **auto-reply
nudging the borrower to the secure upload path**. It is "the single most useful compliance feature
available on the ingest side, and it is cheap."

AND IT IS THE ONE FEATURE IN PHASE 4 THAT CAN GENERATE MAIL BY ITSELF. Everything else needs a
processor to press something. This replies to a stranger, so the whole module is really about the
four ways that goes wrong:

* **A loop with their out-of-office.** They reply, we nudge, their assistant answers, we nudge.
* **A loop with a mailing list.** One subscribed address, two automatons, a weekend.
* **A reply to a bounce**, which is a message from a mail system, not a person.
* **Backscatter** — replying to a forged sender, which makes us the abuser.

THE HEADERS ARE NOT THE DEFENCE. LP-811a built `AUTO_REPLY_SUPPRESSION_HEADERS` and said so at the
time: they ask a well-behaved correspondent not to answer, and a loop forms with one that is not.
The defence is :func:`should_auto_reply` — a decision over what we can see and what we have already
sent, which cannot be talked out of by a header somebody chose not to send.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.base import utcnow
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.inbound_message import InboundMessage
from app.models.loan_file import LoanFile
from app.services.bounce_handling import is_suppressed
from app.services.email_send import RATE_LIMIT_PER_DAY, RATE_LIMIT_WINDOW
from app.services.inbound_participants import normalise_address
from app.services.upload_links import MintedLink, mint_upload_link

logger = get_logger(__name__)

#: `phase4.md` §5 names these three for an AUTO-REPLY specifically, and two differ from LP-811a's
#: general set: `Auto-Submitted: auto-replied` rather than `auto-generated`, and
#: `Precedence: auto_reply` rather than `bulk`. Both distinctions are real — RFC 3834 reserves
#: `auto-replied` for a reply generated to a specific message, which is exactly this, and
#: `auto-generated` for everything else a system emits unprompted. Copying LP-811a's dict would have
#: labelled this as the wrong kind of automatic mail, to the correspondents most likely to act on the
#: label.
AUTO_REPLY_HEADERS: dict[str, str] = {
    "Auto-Submitted": "auto-replied",
    "X-Auto-Response-Suppress": "All",
    "Precedence": "auto_reply",
}

#: The template's identity in the evidence record (`phase4.md` §6 requires template + version).
TEMPLATE_KEY = "borrower_secure_upload_nudge"
TEMPLATE_VERSION = "1"  # a String column, matching every other template record


@dataclass(frozen=True)
class AutoReplyDecision:
    """Whether to reply, and why not. ``reason`` is for the log and the ticket, never the borrower."""

    send: bool
    reason: str


def _machine_sent_it(message: InboundMessage) -> str | None:
    """The reason this message came from a machine rather than a person, or None.

    THREE FLAGS, ALL DECIDED AT INGEST, and `phase4.md` §5's list is exactly these:

    * ``is_dsn`` — `multipart/report; report-type=delivery-status`, or the empty `Return-Path: <>`
      that RFC 5321 requires of a notification so it cannot itself bounce.
    * ``is_auto_reply`` — RFC 3834's `Auto-Submitted` with any value other than `no`, plus the two
      `X-` conventions that predate it. Tested for INEQUALITY with "no", so an unrecognised value
      fails closed.
    * ``is_bulk`` — `Precedence: bulk|list|junk`, or any `List-Id`. Added by LP-815, because §5
      names it and nothing implemented it: `is_auto_reply` covered the RFC 3834 marker and neither
      of the other two, so a subscribed address would have been nudged. The loop a list forms is the
      worse one — a reply goes to the LIST, so every subscriber sees it and the reflector returns it.

    They are three separate columns rather than one "do not reply" boolean because they mean three
    different things everywhere else: LP-804b marks a DSN's attachments UNSUPPORTED, LP-819 reads
    bounces, and a triage card says which it was.
    """
    if message.is_dsn:
        return "a delivery status notification"
    if message.is_auto_reply:
        return "an automatic reply"
    if message.is_bulk:
        return "from a mailing list or a bulk sender"
    return None


async def should_auto_reply(
    db: AsyncSession, *, message: InboundMessage, loan_file: LoanFile
) -> AutoReplyDecision:
    """Whether this inbound message gets a nudge.

    THE ORDER IS THE ARGUMENT. The cheap, certain refusals come first; the rate limit is last,
    because it is the backstop rather than the reason. Every one of them refuses, so the default is
    silence and a new failure mode is quiet rather than loud.
    """
    address = normalise_address(message.from_address)
    if address is None:
        # No usable sender. A message with no `From` is either malformed or a bounce, and replying to
        # nowhere is at best wasted and at worst backscatter.
        return AutoReplyDecision(False, "the message has no usable sender address")

    if (machine := _machine_sent_it(message)) is not None:
        return AutoReplyDecision(False, f"the message is {machine}")

    if message.company_id is None or message.loan_file_id != loan_file.id:
        # NEVER FOR AN UNROUTED MESSAGE. It belongs to nobody, so there is no company whose name
        # would be on the reply — and a reply is the one thing that would tell a stranger their guess
        # at an address reached a real system.
        return AutoReplyDecision(False, "the message is not routed to this file")

    if await is_suppressed(db, company_id=loan_file.company_id, address=address):
        # LP-819 — mail to this address bounced permanently. An automatic reply to it produces
        # another bounce, on a sending reputation shared by every borrower this system writes to.
        return AutoReplyDecision(False, "the sender's address is suppressed after a hard bounce")

    if await _replied_recently(db, company_id=loan_file.company_id, recipient=address):
        return AutoReplyDecision(False, "this address was auto-replied to recently")

    return AutoReplyDecision(True, "a person sent documents to a file we can name")


async def _replied_recently(db: AsyncSession, *, company_id: UUID, recipient: str) -> bool:
    """The header-independent loop breaker: one per address per five minutes, three per day.

    HEADER-INDEPENDENT IS THE WHOLE POINT, and `phase4.md` §5 says why: "header detection will fail
    eventually; the rate limit is what stops two systems generating 100k messages overnight." A count
    over what we have actually recorded cannot be talked out of by a correspondent who does not set
    the headers we asked them to read.

    SCOPED TO THE COMPANY, matching LP-811a's send limit and for the reason its review established:
    two processing companies can hold a file for the same person, and an unscoped count lets one
    tenant's traffic silence another's — and says so.

    COUNTS AUTO-REPLIES ONLY, not every outbound message. A processor's own document request and an
    automatic nudge are different things at different rates; folding them together would let one
    considered email suppress the nudge, or three nudges block the email that matters.
    """
    window_start = utcnow() - RATE_LIMIT_WINDOW
    day_start = utcnow() - timedelta(hours=24)

    base = (
        select(Communication)
        .join(LoanFile, LoanFile.id == Communication.loan_file_id)
        .where(
            LoanFile.company_id == company_id,
            Communication.recipient == recipient,
            Communication.direction == CommunicationDirection.OUTBOUND,
            Communication.template_key == TEMPLATE_KEY,
        )
    )
    recent = await db.scalar(
        select(func.count()).select_from(
            base.where(Communication.created_at >= window_start).subquery()
        )
    )
    if (recent or 0) > 0:
        return True
    today = await db.scalar(
        select(func.count()).select_from(
            base.where(Communication.created_at >= day_start).subquery()
        )
    )
    return (today or 0) >= RATE_LIMIT_PER_DAY


def compose_nudge(*, loan_file: LoanFile, link: MintedLink) -> tuple[str, str]:
    """The subject and body of the nudge. ``(subject, body)``.

    NO AI, and not because a model could not write it. `phase4.md` §5 requires this exact content —
    the secure link and the plain statement that email is not a secure channel — and §5 of the
    execution protocol settles that borrowers ARE told so. A composed sentence is one that can come
    out differently, and the sentence a regulator would ask about is the one that must not.

    NOTHING IDENTIFYING. Not the borrower's name, not the property, not the loan amount. This message
    goes to whatever address wrote in, which after a spoof is not necessarily the borrower — so it
    says what to do and names nothing.
    """
    subject = f"We received your email — {loan_file.display_id}"
    body = (
        "Thank you — your message reached us and a processor will review it.\n"
        "\n"
        "For anything else you still need to send, please use this secure upload link "
        "rather than email:\n"
        f"\n{link.url}\n\n"
        "It expires shortly, so use it soon. Email is not a secure way to send documents "
        "containing personal information such as account numbers or a Social Security number, "
        "which is why we offer the link.\n"
        "\n"
        "If you did not expect this message, you can ignore it.\n"
        f"\n[{loan_file.display_id}]\n"
    )
    return subject, body


async def record_auto_reply(
    db: AsyncSession, *, loan_file: LoanFile, message: InboundMessage
) -> Communication | None:
    """Decide, mint a link, and record the nudge. Returns the record, or None when it was refused.

    NOTHING TRANSMITS. There is no send transport in the product — INFRA-3 is written and unapplied,
    and LP-816 is the ticket that transmits. The record is created with status ``QUEUED`` so that
    when a transport exists it has something to pick up, and so the decision, the headers and the
    link are all testable now.

    That is stated rather than implied because a queued row nobody drains is exactly the shape this
    repo has twice shipped by accident — a function nothing called, a column nothing wrote. The
    difference here is that the queue is the deliverable: the loop breaker either refuses correctly
    or it does not, and that is decided before anything is sent.
    """
    decision = await should_auto_reply(db, message=message, loan_file=loan_file)
    if not decision.send:
        # METADATA ONLY — the reason is our own words, never the sender or the subject.
        logger.info("auto_reply_suppressed", reason=decision.reason)
        return None

    address = normalise_address(message.from_address)
    assert address is not None  # `should_auto_reply` refuses when it is None

    minted = await mint_upload_link(
        db,
        loan_file=loan_file,
        recipient_email=address,
        purpose="Documents for your loan application",
    )
    subject, body = compose_nudge(loan_file=loan_file, link=minted)

    reply = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.QUEUED,
        recipient=address,
        subject=subject,
        body=body,
        template_key=TEMPLATE_KEY,
        template_version=TEMPLATE_VERSION,
        # THREADED TO WHAT IT ANSWERS. RFC 5322 §3.6.4 — without this the borrower sees an unrelated
        # message rather than a reply, and their client cannot collapse it into the conversation.
        external_message_id=message.message_id,
    )
    db.add(reply)
    await db.flush()
    logger.info("auto_reply_queued", loan_file_id=str(loan_file.id))
    return reply


__all__ = [
    "AUTO_REPLY_HEADERS",
    "TEMPLATE_KEY",
    "TEMPLATE_VERSION",
    "AutoReplyDecision",
    "compose_nudge",
    "record_auto_reply",
    "should_auto_reply",
]
