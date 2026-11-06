"""One message, in full, for the dialog a processor opens from the timeline (LP-829).

WHAT DID NOT EXIST BEFORE THIS. Nothing in the product could show a processor the text of a message
that had already been sent. The whole message surface was: the file's ONE open draft, the send, a
reply's recipient and subject, and the two flags. `MessagePublic` says it outright — *"Never the
body — the caller already has what they typed"* — which is correct for a WRITE response and does not
transfer to a read. So a sent document request was, from the moment it was recorded, unreadable.

A READER, NEVER AN EDITOR, and that is the design rather than a limitation. The open draft is
already rendered and editable in `OutboundDraftPanel` on the same page; a dialog that also edited it
would be two components holding separate local state for one body, and the second one to save wins
silently. Sent and received messages are not editable at all — the first because LP-821's evidence
record must not change after the fact, the second because a borrower's words are not ours to rewrite.

THE PLACEHOLDER RULE, WHICH IS NOT UNIFORM AND MUST NOT BE. LP-823 left `$borrower_first_name` and
`$processor_name` in a stored DRAFT so the send decides who signs, and resolves them for whoever is
reading. That resolution belongs here too, or this dialog reintroduces LP-823's defect in a third
place. It applies to OUTBOUND DRAFTS ONLY:

* a **sent** message's stored body was already resolved when it went out, so substituting again is a
  no-op — and running it would be indistinguishable from a body that had never been resolved;
* an **inbound** message is a borrower's own words, and a borrower who writes "$processor_name" in
  their email must get it back unchanged. Substituting there would rewrite what somebody wrote to us,
  which is the one thing a record of their message must never do.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.documents.catalog import ResponsibleParty
from app.models.communication import (
    BodyFormat,
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.loan_file import LoanFile
from app.models.user import User
from app.services.email_draft import (
    DRAFT_TEMPLATE,
    _needs_in_draft,
    _party_address,
    draft_for_reading,
    party_for_draft_template,
)
from app.services.email_send import MAILTO_MAX_CHARS, build_outbound, transmit_blocker
from app.services.mail_domain import MAIL_DOMAIN_PAUSED, file_address_and_sending
from app.services.timeline import TimelineAttachment, _attachment_manifest, _inbound_senders

logger = get_logger(__name__)


@dataclass(frozen=True)
class MessageDetail:
    """Everything the dialog shows, for whichever state this message is in."""

    id: UUID
    direction: str
    status: str
    subject: str | None
    body: str
    #: LP-853 — `"plain"` or `"html"`. See `Communication.body_format`.
    body_format: str
    #: Sender for inbound, recipient for outbound. Either can be absent: an outbound DRAFT has no
    #: recipient until a processor types one, which is the ordinary state of the thing being read.
    counterparty: str | None
    template_key: str | None
    template_version: str | None
    created_at: datetime
    sent_at: datetime | None
    read_at: datetime | None
    is_important: bool
    #: Why a send failed, in the provider's own words (LP-821). None on everything else.
    error_detail: str | None
    #: OUTBOUND: what this message asks for. INBOUND: what arrived on it, and what became of each.
    documents: tuple[str, ...]
    attachments: tuple[TimelineAttachment, ...]
    #: Whether this is the BORROWER's document-request draft (LP-829 kept this narrow deliberately).
    is_open_draft: bool
    #: LP-831 — whether a processor may edit and send this. WIDER than `is_open_draft`: a party
    #: request is a draft under its own template key, and the reason it was unsendable is that
    #: `get_open_draft` filters on the borrower's. `send_draft` takes a draft id and has never cared
    #: which template rendered it, so the screen was the whole missing piece.
    is_editable: bool
    #: LP-831 — who to address it to, when nobody has yet. None once `recipient` is set.
    #:
    #: LP-857 — AND A PARTY'S ADDRESS TOO, not only the borrower's. The old rule suggested nothing
    #: on a party draft, reasoning that "a party draft carries the title company's address on the
    #: row". That is true only when there WAS one at creation: LP-841 deliberately creates a party
    #: draft with no recipient when the file has no address, because "the message is the part a
    #: processor wants", and 13 of 166 document types had no address anywhere (LP-820). Those drafts
    #: reached the modal with an empty box and no hint of why. Resolved through `_party_address`,
    #: which is the same function the draft's own creation uses — the borrower is never suggested on
    #: a party draft, which is what the old rule was protecting against.
    suggested_recipient: str | None
    #: LP-857 — whose draft this is (`borrower`, `title`, `lender`, …), or None.
    #:
    #: FROM THE SERVER, like the timeline's. The modal needs it to know which party an address is
    #: being saved FOR, and `template_key` cannot answer: five parties share
    #: `document_request_third_party`, so a client deriving the party from the key would file a
    #: lender's address under the title company. Same order as `_party_of`: the stored column first,
    #: the template key as the fallback for a draft written before the column existed.
    party: str | None
    #: LP-831 REVIEW — WHAT THE MESSAGE NEEDS IN ORDER TO ACTUALLY LEAVE.
    #:
    #: Nothing in this product transmits mail. "Mark as sent" records an outbound event, moves every
    #: need to REQUESTED and starts LP-814's reminder clock; the message reaches a borrower only
    #: because a processor copied it or opened it in their own mail client. Those two controls lived
    #: on `OutboundDraftPanel`, which LP-831 took off the page — so the dialog that replaced it could
    #: record a send with no way to perform one. These three carry `build_outbound`'s answer to the
    #: editor, exactly as `OutboundDraftPublic` carries it to the panel that no longer renders.
    #: `suggested_bcc` is None when the company has no active mail domain (LP-991).
    suggested_bcc: str | None
    mailto_available: bool
    mailto_max_chars: int
    #: LP-997 — the dialog offers Send (instead of copy / mail app / "Mark as sent"). An editable
    #: draft the app can send itself: `email_send.transmit_blocker` found nothing, which is the same
    #: check the Send endpoint refuses on. False on everything else.
    can_send: bool = False
    #: LP-1009 — why Send is off, ONLY when the company's domain is paused (LP-1006 Open 4). The other
    #: reasons are not for a processor to act on, and the dialog already offers her own mail for them.
    send_blocked_reason: str | None = None
    #: LP-997 — when a person pressed Send (LP-994's `send_requested_at`). The dialog re-checks for
    #: a while after it and then says "Not confirmed"; None for anything not sent from the app.
    send_requested_at: datetime | None = None
    #: LP-1009 — True when a received email's stored original could not be read, so `body` is
    #: empty because we could not read it, not because the sender wrote nothing.
    body_unavailable: bool = False


async def message_detail(
    db: AsyncSession, *, loan_file: LoanFile, communication_id: UUID, reader: User
) -> MessageDetail | None:
    """This message in full, or None if it is not on this file.

    NONE RATHER THAN A RAISE, and the endpoint turns it into the same 404 a wrong file identifier
    gets. A message id that belongs to another company must be indistinguishable from one that does
    not exist — telling the two apart is how a caller enumerates what another tenant has.

    The file is resolved by the route before this is called, so the scoping axis here is the FILE:
    `loan_file_id` is checked on the row itself rather than trusted from the id.
    """
    message = await db.get(Communication, communication_id)
    if message is None or message.loan_file_id != loan_file.id or message.deleted_at is not None:
        return None

    is_open_draft = (
        message.direction is CommunicationDirection.OUTBOUND
        and message.status is CommunicationStatus.DRAFT
        and message.template_key == DRAFT_TEMPLATE.value
    )
    # LP-829 REVIEW — RESOLUTION IS DECIDED BY THE BODY'S ORIGIN, NOT BY WHICH DRAFT THIS IS.
    #
    # It was gated on `is_open_draft`, which additionally requires the BORROWER template key — so a
    # party request (`party_requests` renders the SAME template for title, agent, lender, CPA,
    # insurer and employer, each under its own key) fell to the raw body. `build_timeline` selects
    # every Communication on the file with no template filter, so those drafts are on the timeline
    # and clickable. Measured: opening one showed "Hello $borrower_first_name," signed
    # "$processor_name" — LP-823's defect in the third place this module's own docstring says it
    # exists to prevent.
    #
    # `template_key is not None` is the honest test: a body rendered from a template HAS the
    # placeholders by construction, and a reply or compose draft is text a processor typed, where a
    # literal `$processor_name` is theirs and not ours to substitute. That is the same line the
    # inbound case is drawn on, one direction over.
    renders_from_a_template = (
        message.direction is CommunicationDirection.OUTBOUND
        and message.status is CommunicationStatus.DRAFT
        and message.template_key is not None
        # LP-853 — AND THE BODY IS STILL THE TEMPLATE'S. Once a processor has written into it the
        # body is authored content: there are no placeholders left to resolve (the editor was handed
        # a body that had already been resolved for reading), and `refresh_if_stale` must not run
        # over it. Running `safe_substitute` on markup is also how a `$` inside a link or an
        # attribute becomes something nobody typed.
        and message.body_format is BodyFormat.PLAIN
    )
    suggested_recipient: str | None = None
    if renders_from_a_template:
        # LP-823 — the same resolution the panel reads, so the dialog and the textarea show the same
        # words. Reading them apart is exactly how "Hello $borrower_first_name," survived.
        body, borrower_email = await draft_for_reading(
            db, draft=message, loan_file=loan_file, reader=reader
        )
        # LP-831 — SUGGESTED ONLY WHEN NOBODY HAS BEEN ADDRESSED YET, and only for a draft addressed
        # to the borrower. A party draft carries the title company's or the employer's address on the
        # row (`party_requests` sets it at creation), and offering the borrower's there would put a
        # third party's document request in the borrower's inbox.
        if message.recipient is None:
            # LP-857 — THE PARTY'S OWN ADDRESS, and the borrower's only on the borrower's draft.
            # `_party_address` resolves the borrower through their row and everybody else through
            # the participants table, which is the same resolution the draft's creation used; going
            # through it rather than reading `party_addresses` here is what stops a second
            # definition of "the title company's address" existing.
            suggested_recipient = (
                borrower_email
                if message.template_key == DRAFT_TEMPLATE.value
                else await _suggested_party_address(db, loan_file=loan_file, message=message)
            )
    else:
        body = message.body or ""

    subject = message.subject
    body_format = message.body_format.value
    body_unavailable = False
    if (
        message.direction is CommunicationDirection.INBOUND
        and message.inbound_message_id
        and not message.body
    ):
        # LP-1009 — THE EMAIL'S OWN WORDS. The Communication row holds no subject or body (see
        # `_record_arrival`); the subject is on the inbound row and the text is in the stored `.eml`,
        # re-read on each open rather than copied into a second place. A row that does carry a body
        # keeps it, and the text read here is always plain, whatever the row's column says.
        stored_subject, body, body_unavailable = await _inbound_subject_and_text(
            db, message.inbound_message_id
        )
        subject = message.subject or stored_subject
        body_format = BodyFormat.PLAIN.value

    # LP-831 REVIEW — over the RESOLVED body, which is what a processor copies. Computing it from
    # the stored one would answer about text nobody sees.
    # LP-997 — one read of the company's mail-domain row, for the address and the Send check.
    address_and_sending = await file_address_and_sending(db, loan_file)
    outbound = build_outbound(
        loan_file,
        address=address_and_sending[0],
        subject=subject or "",
        body=body,
    )

    documents: tuple[str, ...] = ()
    if message.direction is CommunicationDirection.OUTBOUND:
        documents = tuple(need.title for need in await _needs_in_draft(db, draft=message))

    attachments: tuple[TimelineAttachment, ...] = ()
    counterparty = message.recipient
    if message.direction is CommunicationDirection.INBOUND and message.inbound_message_id:
        attachments = (await _attachment_manifest(db, [message.inbound_message_id])).get(
            message.inbound_message_id, ()
        )
        # LP-805 declined to copy the sender onto the Communication, so it is read from the stored
        # message. `message.sender` is tried first anyway, so a future writer is not ignored.
        counterparty = message.sender or (
            await _inbound_senders(db, [message.inbound_message_id])
        ).get(message.inbound_message_id)

    is_editable = (
        message.direction is CommunicationDirection.OUTBOUND
        and message.status is CommunicationStatus.DRAFT
    )
    blocker = (
        await transmit_blocker(
            db, loan_file=loan_file, draft=message, address_and_sending=address_and_sending
        )
        if is_editable
        else None
    )
    can_send = is_editable and blocker is None
    return MessageDetail(
        id=message.id,
        direction=message.direction.value,
        status=message.status.value,
        subject=subject,
        body=body,
        # LP-853 — WHICH LANGUAGE `body` IS IN, so the one editor can load it and the reader can
        # choose between rendering the plain form and showing the stored HTML. Derived from nothing:
        # it is the column, which is also LP-851's `body_edited`.
        body_format=body_format,
        counterparty=counterparty,
        template_key=message.template_key,
        template_version=message.template_version,
        created_at=message.created_at,
        sent_at=message.sent_at,
        read_at=message.read_at,
        is_important=message.is_important,
        error_detail=message.error_detail,
        documents=documents,
        attachments=attachments,
        is_open_draft=is_open_draft,
        is_editable=is_editable,
        suggested_recipient=suggested_recipient,
        party=_party_of_draft(message),
        suggested_bcc=outbound.suggested_bcc,
        mailto_available=outbound.mailto_available,
        mailto_max_chars=MAILTO_MAX_CHARS,
        can_send=can_send,
        send_blocked_reason=blocker if blocker == MAIL_DOMAIN_PAUSED else None,
        body_unavailable=body_unavailable,
        send_requested_at=message.send_requested_at,
    )


async def _inbound_subject_and_text(
    db: AsyncSession, inbound_message_id: UUID
) -> tuple[str | None, str, bool]:
    """A received email's subject, its text, and whether the text could not be read.

    NEVER RAISES. A missing or unreadable original leaves the rest of the message (sender,
    attachments) on screen with a sentence in place of the text, rather than a failed dialog.
    """
    from app.models.inbound_message import InboundMessage
    from app.services.inbound_mime import body_text
    from app.services.inbound_triage import CannotAcceptError, raw_message

    inbound = await db.get(InboundMessage, inbound_message_id)
    if inbound is None:
        return None, "", True
    try:
        raw = await raw_message(inbound)
    except CannotAcceptError:
        return inbound.subject, "", True
    except Exception as exc:
        # Storage maps its own failures to `CannotAcceptError` above; anything else is unexpected,
        # and still must not take the dialog down.
        logger.warning("inbound_raw_message_unexpected_error", error_type=type(exc).__name__)
        return inbound.subject, "", True
    try:
        return inbound.subject, body_text(raw), False
    except Exception as exc:
        # A malformed message must not take the dialog down; the type is logged, never the text.
        logger.warning("inbound_body_unparseable", error_type=type(exc).__name__)
        return inbound.subject, "", True


def _party_of_draft(message: Communication) -> str | None:
    """Whose draft this is, by the same rule the timeline uses (LP-857).

    THE STORED COLUMN FIRST, the template key as a fallback. LP-843 added `Communication.party`
    because `template_key` stopped being able to answer once five parties came to share
    `document_request_third_party` — a lender draft and a title draft are the same key — and the
    fallback is for rows written before the column existed.

    NOT `_party_of`. That function additionally places an outbound message by the address it was
    sent to, which needs the file's whole address book and is a page-level lookup. What the modal
    asks is narrower: whose draft is this, so an address saved from it lands on the right party. A
    draft with no address is exactly the case here, so the address route could never answer anyway.
    """
    if message.party:
        return message.party
    party = party_for_draft_template(message.template_key)
    return party.value if party else None


async def _suggested_party_address(
    db: AsyncSession, *, loan_file: LoanFile, message: Communication
) -> str | None:
    """This party's address from the file, or None when nobody has recorded one."""
    name = _party_of_draft(message)
    if name is None:
        return None
    try:
        party = ResponsibleParty(name)
    except ValueError:
        # A `party` column holding something outside the enum is a data problem, not a reason to
        # guess — and guessing here means putting an address on somebody else's draft.
        return None
    return await _party_address(db, loan_file=loan_file, party=party)


__all__ = ["MessageDetail", "message_detail"]
