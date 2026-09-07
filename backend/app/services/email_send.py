"""Marking a draft as sent, and everything that has to be true at that moment (LP-811a).

WHAT "SEND" MEANS IN M1. Nothing transmits. The plan's send path is *copy and send* — the processor
puts the text into their own mail client — plus an "open in mail client" link. LP-816 is the ticket
that transmits as her, through a connected mailbox. So this module's job is to record that a draft
went out, produce the artefacts the message needs to carry, and start the clocks.

THE CLOCK IS THE POINT. `request_needs_item` has existed since LP-19 at `services/needs_items.py`
with **zero callers**, so `requested_at` is NULL on every needs item that has ever existed. LP-814's
reminders are a Celery beat over that column; until something writes it, every reminder rule is a
query over an empty set that cannot fail and cannot fire. This is the ticket that writes it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.user import User
from app.services.activity_log import log_activity
from app.services.bounce_handling import is_suppressed
from app.services.email_draft import (
    _needs_in_draft,
    finalise_draft_body,
    get_open_draft,
    greeting_name_for,
)
from app.services.needs_items import request_needs_item

#: `mailto:` is truncated somewhere around 2,000 characters in several mail clients, and a truncated
#: `mailto:` does not fail — it opens a compose window containing HALF AN EMAIL, which a processor may
#: not notice before sending. The link is offered below this length and refused above it; copy-to-
#: clipboard has no such limit and is always available.
#:
#: Conservative on purpose: the real limits differ per client (and per browser, and per OS handler),
#: so the threshold is set below the lowest one anybody documents rather than at it.
MAILTO_MAX_CHARS = 1800

#: One send per address per five minutes, and three per day. HEADER-INDEPENDENT, which is the whole
#: point: `Auto-Submitted` and friends ask a well-behaved correspondent not to reply, and a loop
#: forms with one that is not. A count over what we have actually recorded cannot be talked out of.
RATE_LIMIT_WINDOW = timedelta(minutes=5)
RATE_LIMIT_PER_DAY = 3

#: Headers that tell an autoresponder not to answer. Set on anything AUTOMATED — LP-815's nudge and
#: LP-819's bounce handling are the consumers; a human-approved send is not automated and carries
#: none of them.
#:
#: NOTHING IN THIS TICKET TRANSMITS, so nothing reads these yet, and that is a deliberate exception to
#: a rule this codebase otherwise holds to (no API with no reader). The plan places them in LP-811 and
#: the alternative is that no ticket owns them at all — a suppression header omitted from an
#: auto-reply is how a mail loop starts, and the loop is with a borrower's mailbox.
AUTO_REPLY_SUPPRESSION_HEADERS: dict[str, str] = {
    "Auto-Submitted": "auto-generated",
    "X-Auto-Response-Suppress": "All",
    "Precedence": "bulk",
}

_FOOTER_TAG = re.compile(r"\[(LF-[A-Za-z0-9]+)\]")


class CannotSendError(Exception):
    """The draft cannot be sent. Always tells the caller which rule stopped it."""


#: LP-815 — OUTBOUND MAIL CARRIES NO ATTACHMENTS, AND THAT IS ENFORCED HERE RATHER THAN ASSUMED.
#:
#: `phase4.md` §6: GLBA Safeguards 16 CFR 314.4(c)(3) requires customer information to be encrypted
#: in transit over external networks, and opportunistic STARTTLS is not a defensible compensating
#: control on its own. So outbound carries an authenticated, expiring link — "the attachment path is
#: blocked in code, not by policy".
#:
#: The block is this: `OutboundMessage` has no field an attachment could travel in, and a test
#: asserts that rather than trusting the absence. Today that is true because nobody has added one,
#: which is exactly the state a rule like this exists to survive — the day somebody adds
#: `attachments: list[bytes]` because a lender needs a PDF, this is what refuses.
_ATTACHMENT_FIELD_NAMES = frozenset({"attachment", "attachments", "files", "parts", "documents"})


@dataclass(frozen=True)
class OutboundMessage:
    """Everything the processor's mail client needs, assembled once so it cannot disagree with itself.

    NO ATTACHMENT FIELD, DELIBERATELY — see `_ATTACHMENT_FIELD_NAMES`. A message this system helps
    send carries a link to the document, never the document.
    """

    subject: str
    body: str
    reply_to: str
    #: Offered, not applied — the processor chooses. Bccing the file address is how the sent copy is
    #: captured when the message goes out through their own client rather than ours.
    suggested_bcc: str
    #: False when the body is too long for a `mailto:` link to survive intact.
    mailto_available: bool


def footer_tag(loan_file: LoanFile) -> str:
    """The routing tag a reply carries back, as it appears at the foot of the message.

    `display_id`, NOT `inbox_token`. ADR-048 draws the line this depends on: the display id is an
    IDENTIFIER whose predictability is low-risk, and the token is a CAPABILITY whose possession lets
    anyone post documents into the file. A footer is quoted into every reply, forwarded, and pasted
    into other threads — putting the capability there would hand it to everyone the borrower ever
    forwards the message to, which is precisely what ADR-397 narrowed rather than widened.

    The tag is a FALLBACK. `Reply-To` is what routes a well-behaved reply; this is what LP-805 can
    still match on when a client strips or rewrites the header, which several do.
    """
    return f"[{loan_file.display_id}]"


def loan_reference_in(text: str) -> str | None:
    """The display id a footer tag carries, or None — LP-805's fallback match."""
    found = _FOOTER_TAG.search(text)
    return found.group(1) if found else None


def build_outbound(loan_file: LoanFile, *, subject: str, body: str) -> OutboundMessage:
    """Assemble the message a processor will send, footer tag included."""
    address = loan_file.get_inbox_address()
    # LP-823 REVIEW — IDEMPOTENT, because this function runs TWICE over one message. `GET
    # /outbound/draft` returns `build_outbound(...).body`, the panel puts that in the textarea, and
    # the send posts the textarea back through here again. Measured over the real HTTP round trip:
    # every sent message ended "[LF-H5HH]\n\n[LF-H5HH]". Pre-existing rather than new, but it is on
    # the path this ticket changed, and it also made the composed-vs-sent comparison in `send_draft`
    # impossible to write honestly. Appending only when it is not already the last thing leaves the
    # single-pass case untouched.
    stripped = body.rstrip()
    tag = footer_tag(loan_file)
    tagged = stripped if stripped.endswith(tag) else f"{stripped}\n\n{tag}"
    return OutboundMessage(
        subject=subject,
        body=tagged,
        reply_to=address,
        suggested_bcc=address,
        mailto_available=len(tagged) + len(subject) <= MAILTO_MAX_CHARS,
    )


logger = structlog.get_logger(__name__)


async def _recent_sends(
    db: AsyncSession, *, company_id: UUID, recipient: str, since_hours: int
) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(Communication)
            .join(LoanFile, LoanFile.id == Communication.loan_file_id)
            .where(
                LoanFile.company_id == company_id,
                Communication.recipient == recipient,
                Communication.status == CommunicationStatus.SENT,
                Communication.direction == CommunicationDirection.OUTBOUND,
                Communication.sent_at >= utcnow() - timedelta(hours=since_hours),
            )
        )
        or 0
    )


async def _refuse_if_rate_limited(db: AsyncSession, *, company_id: UUID, recipient: str) -> None:
    """One per address per five minutes, three per day, ACROSS THIS COMPANY'S FILES.

    ACROSS FILES, NOT WITHIN ONE: a borrower with two loan files in progress is one mailbox, and
    limiting per file would let them be mailed twice in a minute while every individual limit read
    as respected.

    AND WITHIN ONE COMPANY, NOT ACROSS ALL OF THEM. Counting system-wide reads as the safer
    direction and is not: two processing companies can hold a file for the same person — a borrower
    shopping two brokers is the ordinary case — and an unscoped count means one tenant's send blocks
    another's, and says so. Measured before this was scoped: company B's send was refused with
    "was emailed less than 5 minutes ago", which tells B that somebody else has been in touch with
    their borrower. A rate limit is not worth a cross-tenant disclosure, and one tenant must not be
    able to stall another's mail by writing to the same address.
    """
    last = await db.scalar(
        select(func.max(Communication.sent_at))
        .join(LoanFile, LoanFile.id == Communication.loan_file_id)
        .where(
            LoanFile.company_id == company_id,
            Communication.recipient == recipient,
            Communication.status == CommunicationStatus.SENT,
            Communication.direction == CommunicationDirection.OUTBOUND,
        )
    )
    if last is not None and utcnow() - last < RATE_LIMIT_WINDOW:
        raise CannotSendError(
            f"{recipient} was emailed less than {int(RATE_LIMIT_WINDOW.total_seconds() // 60)} "
            "minutes ago; wait before sending again"
        )
    if (
        await _recent_sends(db, company_id=company_id, recipient=recipient, since_hours=24)
        >= RATE_LIMIT_PER_DAY
    ):
        raise CannotSendError(
            f"{recipient} has already been emailed {RATE_LIMIT_PER_DAY} times today"
        )


async def send_draft(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    draft_id: UUID,
    recipient: str,
    body: str,
    approver_user_id: UUID,
) -> Communication:
    """Record that ``draft_id`` was sent, and start the clock on everything it asked for.

    ``body`` is what the processor is actually sending — their edit of the draft, not the draft as
    composed. It replaces the stored body, because the record of an outbound message must be what
    went out; LP-821 builds the full three-way evidence record (composed / edited / as sent) and is
    where the composed version gets its own field.

    NO BULK SEND, by construction: this takes one ``draft_id``. The plan says so and the reason is
    the rate limit above — a bulk path would either bypass it or fail halfway through a list with no
    way to say which half went.
    """
    draft = await db.get(Communication, draft_id)
    if draft is None or draft.loan_file_id != loan_file.id or draft.deleted_at is not None:
        raise CannotSendError("no such draft on this loan file")
    if draft.status is not CommunicationStatus.DRAFT:
        raise CannotSendError(f"this message is already {draft.status.value}")
    if not (body or "").strip():
        raise CannotSendError("an empty message cannot be sent")
    # LP-819 — a hard bounce means this mailbox does not exist. Sending again produces another
    # bounce, and enough of those damage a sending reputation shared by every borrower this system
    # writes to. Checked BEFORE the rate limit so the message says the useful thing: "this address is
    # dead" is actionable, "wait five minutes" is not.
    if await is_suppressed(db, company_id=loan_file.company_id, address=recipient):
        raise CannotSendError(
            f"{recipient} is suppressed — an earlier message to it bounced permanently. "
            "Confirm the address with the borrower before sending again."
        )
    await _refuse_if_rate_limited(db, company_id=loan_file.company_id, recipient=recipient)

    needs = await _needs_in_draft(db, draft=draft)
    # CAPTURED BEFORE THE OVERWRITE (LP-821). The next line replaces `draft.body` with what the
    # processor is actually sending, so this is the last moment the COMPOSED version exists. §6 asks
    # for the model draft, the human edit and the diff; for everything sent before LP-821 the first
    # is gone rather than unstored, and this is the line that stops that being true going forward.
    body_composed = draft.body
    # LP-823 — THE LAST GUARD, and it has to be here rather than only in the endpoint. The panel
    # already posts resolved text, so on the ordinary path this is a no-op (`safe_substitute` over a
    # string with no placeholders left). It exists for the path that is not ordinary: any caller
    # that posts the STORED body — a script, a retry, a future route — would otherwise record, and
    # on a transport send actually deliver, `Hello $borrower_first_name,`.
    #
    # THE SIGNER IS THE APPROVER, not whoever composed it or whoever last previewed it. That is the
    # distinction `render_draft_body` deferred the name for in the first place.
    #
    # WHOSE NAME, THOUGH — `greeting_name_for`, not `primary_borrower`. This route sends every
    # outbound draft on the file, and `party_requests` renders the SAME template for the title
    # company, the agent and the lender under their own template keys. Resolving from the borrower
    # unconditionally addressed a title request to the borrower by name: measured, a request to
    # `t@title.example` went out reading "Hello Akash,". A placeholder in the wrong message is
    # visibly broken; a real person's name in it is not.
    approver = await db.get(User, approver_user_id)
    greeting = await greeting_name_for(db, draft=draft, loan_file=loan_file)
    signature = approver.full_name if approver else ""
    body = finalise_draft_body(body, borrower_first_name=greeting, processor_name=signature)
    outbound = build_outbound(loan_file, subject=draft.subject or "", body=body)

    # LP-823 REVIEW — RESOLVED THE SAME WAY, so the comparison downstream is like with like.
    # `EvidencePublic.was_edited` is `body_composed != body_as_sent`, and its own comment says it
    # means "the processor changed the drafted words". The composed version is the STORED body, which
    # still holds the placeholders, and the sent body never does — so after LP-823 every message was
    # recorded as edited, including one where nobody typed a character. Measured before this line
    # existed: composed "Hello $borrower_first_name,", as sent "Hello Akash,", was_edited True.
    #
    # Resolving the composed copy with the SAME two values leaves a real edit visible and a
    # placeholder substitution invisible, which is the distinction the field is for. It is not a
    # loss of evidence: what the template stores is `render_draft_body`'s output, reproducible from
    # `template_key` and `template_version`, both of which are on the same row.
    # THROUGH THE SAME PIPELINE, not merely the same substitution: `build_outbound` also appends the
    # footer tag, so resolving alone would still leave the two strings differing by it.
    body_composed = build_outbound(
        loan_file,
        subject=draft.subject or "",
        body=finalise_draft_body(
            body_composed or "", borrower_first_name=greeting, processor_name=signature
        ),
    ).body

    draft.body = outbound.body
    draft.recipient = recipient
    draft.status = CommunicationStatus.SENT
    draft.sent_at = utcnow()

    # THE CLOCK. Every need this message asked for moves to REQUESTED and gets `requested_at`, which
    # is what LP-814's reminders read. Before this line, that column was NULL on every row that has
    # ever existed, so every reminder rule was a query over an empty set — green, silent, and unable
    # to fire.
    for need in needs:
        await request_needs_item(db, needs_item=need)

    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.COMMUNICATION_SENT,
        summary=f"Sent a document request for {len(needs)} item(s)",
        actor_user_id=approver_user_id,
        # Metadata only — never the subject, the body, or the recipient's address.
        detail={
            "communication_id": str(draft.id),
            "needs_item_ids": [str(need.id) for need in needs],
            "template_key": draft.template_key,
            "template_version": draft.template_version,
        },
    )
    # THE EVIDENCE ROW (LP-821). Written here rather than by the endpoint, so every caller of
    # `send_draft` produces one — an evidence record that depends on a route remembering to ask for
    # it is one that is missing exactly where somebody added a second route.
    from app.services.evidence import record_sent

    await record_sent(
        db,
        loan_file=loan_file,
        communication=draft,
        approver_user_id=approver_user_id,
        body_composed=body_composed,
    )

    # LP-816 — TRANSMIT, IF THERE IS ANYTHING TO TRANSMIT THROUGH.
    #
    # INSIDE THIS FUNCTION, AFTER EVERY GUARD, AND NOWHERE ELSE. The suppression check, the rate
    # limit and the approver requirement are all above this line, so a provider implementation
    # inherits them by construction rather than by remembering. A send that skipped them because it
    # went out through a different transport would be the same message with none of the checks —
    # and the way to make that impossible is to have nowhere else to call from.
    #
    # NONE IS THE ORDINARY ANSWER TODAY. §5 says build the interface and no provider, so
    # `transport_for` returns None for every connection and this stays copy-and-send: the record
    # above is the whole of what happened, exactly as it was before this ticket.
    await _transmit_if_possible(db, loan_file=loan_file, draft=draft)

    await db.flush()
    return draft


async def _transmit_if_possible(
    db: AsyncSession, *, loan_file: LoanFile, draft: Communication
) -> None:
    """Hand the message to a provider when one is connected. Silent when none is.

    THE PROVIDER'S ID IS WHAT THIS BUYS. A transmitted message has a `Message-ID` we generated, and
    LP-805's rung 2 matches a borrower's `References` against exactly that — so their reply routes
    with CERTAIN confidence instead of falling to the footer tag, which §2.2 grades "high" and which
    Gmail and Outlook mobile routinely trim out of a quoted body. On copy-and-send there is no such
    id, because the message left from her own client and we never saw it.

    A FAILURE DOES NOT UNDO THE RECORD, and the ordering above is why: `record_sent` has already run.
    Rolling back would lose the evidence row and the needs transition for a message that may well
    have gone out — a provider that timed out after accepting it is the ordinary failure, not the
    exception. The status moves to FAILED so a processor sees it and LP-819's paths treat it as one.

    WHICH MEANS THIS MUST NOT RE-RAISE, and it used to. `TransportError` derives from `Exception`,
    not from `CannotSendError`, so it went straight past the endpoint's only handler; `db.commit()`
    is the line after that handler and was never reached; and `get_db` rolls back on any exception.
    The paragraph above described the intent and the transaction boundary delivered its exact
    opposite — evidence row, FAILED status, needs transitions and the send itself, all gone.

    Worst in precisely the case the paragraph names: if the provider accepted and then timed out,
    the borrower has the message, we keep no record of it, the draft still reads as unsent, and the
    next thing a processor does is send it again.

    So a transport failure is recorded, not raised. The FAILED status IS the signal — that is what
    this docstring already said it was for — and it only exists if the transaction survives to
    carry it. A guard refusal still raises `CannotSendError`, and rolling back is right there:
    nothing should be recorded for a message that was never allowed to go.
    """
    from app.models.mailbox_connection import MailboxConnection
    from app.services.mail_transport import (
        AUTO_REPLY_HEADERS_NONE,
        OutboundEnvelope,
        TransportError,
        transmit,
    )

    connection = (
        (
            await db.execute(
                only_active(
                    select(MailboxConnection)
                    .where(MailboxConnection.company_id == loan_file.company_id)
                    # WHICH mailbox is "the" mailbox is a product answer and is escalated. That
                    # `.first()` had no ordering at all is not: two connected mailboxes made the
                    # choice undefined, so the same file could send as a different identity on two
                    # requests with nothing changed. Ordering does not decide the product question;
                    # it makes the answer reproducible while somebody decides. Same reasoning as
                    # LP-820's participant tiebreaker.
                    .order_by(MailboxConnection.created_at, MailboxConnection.id),
                    MailboxConnection,
                )
            )
        )
        .scalars()
        .first()
    )

    envelope = OutboundEnvelope(
        to=draft.recipient or "",
        subject=draft.subject or "",
        body=draft.body or "",
        in_reply_to=draft.in_reply_to_message_id,
        headers=AUTO_REPLY_HEADERS_NONE,
    )
    try:
        result = await transmit(connection, envelope)
    except TransportError as exc:
        draft.status = CommunicationStatus.FAILED
        # The provider's own words, kept for the same reason LP-819 keeps a bounce diagnostic. Never
        # logged: it can quote the recipient.
        draft.error_detail = str(exc)
        await db.flush()
        logger.warning("outbound_transport_failed")
        return
    if result is None:
        return
    # `external_message_id` MEANS "THIS MESSAGE'S OWN ID" (LP-818 separated it from the id a reply
    # answers), and this is the first thing in the product that can fill it for an outbound message.
    draft.external_message_id = result.provider_message_id
    await db.flush()


async def open_draft_preview(db: AsyncSession, *, loan_file: LoanFile) -> OutboundMessage | None:
    """What the file's open draft would look like as a message, or None if there is no draft."""
    draft = await get_open_draft(db, loan_file_id=loan_file.id)
    if draft is None:
        return None
    return build_outbound(loan_file, subject=draft.subject or "", body=draft.body or "")


__all__ = [
    "AUTO_REPLY_SUPPRESSION_HEADERS",
    "MAILTO_MAX_CHARS",
    "CannotSendError",
    "OutboundMessage",
    "build_outbound",
    "footer_tag",
    "loan_reference_in",
    "open_draft_preview",
    "send_draft",
]
