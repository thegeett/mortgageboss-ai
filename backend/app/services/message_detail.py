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

from app.models.communication import Communication, CommunicationDirection, CommunicationStatus
from app.models.loan_file import LoanFile
from app.models.user import User
from app.services.email_draft import (
    DRAFT_TEMPLATE,
    _needs_in_draft,
    draft_for_reading,
)
from app.services.email_send import MAILTO_MAX_CHARS, build_outbound
from app.services.timeline import TimelineAttachment, _attachment_manifest, _inbound_senders


@dataclass(frozen=True)
class MessageDetail:
    """Everything the dialog shows, for whichever state this message is in."""

    id: UUID
    direction: str
    status: str
    subject: str | None
    body: str
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
    #: LP-831 — who to address it to, when nobody has yet. The borrower's email for a borrower
    #: draft; None once `recipient` is set, because a party draft carries its own address and a
    #: suggestion would be wrong there.
    suggested_recipient: str | None
    #: LP-831 REVIEW — WHAT THE MESSAGE NEEDS IN ORDER TO ACTUALLY LEAVE.
    #:
    #: Nothing in this product transmits mail. "Mark as sent" records an outbound event, moves every
    #: need to REQUESTED and starts LP-814's reminder clock; the message reaches a borrower only
    #: because a processor copied it or opened it in their own mail client. Those two controls lived
    #: on `OutboundDraftPanel`, which LP-831 took off the page — so the dialog that replaced it could
    #: record a send with no way to perform one. These three carry `build_outbound`'s answer to the
    #: editor, exactly as `OutboundDraftPublic` carries it to the panel that no longer renders.
    suggested_bcc: str
    mailto_available: bool
    mailto_max_chars: int


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
        if message.recipient is None and message.template_key == DRAFT_TEMPLATE.value:
            suggested_recipient = borrower_email
    else:
        body = message.body or ""

    # LP-831 REVIEW — over the RESOLVED body, which is what a processor copies. Computing it from
    # the stored one would answer about text nobody sees.
    outbound = build_outbound(loan_file, subject=message.subject or "", body=body)

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

    return MessageDetail(
        id=message.id,
        direction=message.direction.value,
        status=message.status.value,
        subject=message.subject,
        body=body,
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
        is_editable=(
            message.direction is CommunicationDirection.OUTBOUND
            and message.status is CommunicationStatus.DRAFT
        ),
        suggested_recipient=suggested_recipient,
        suggested_bcc=outbound.suggested_bcc,
        mailto_available=outbound.mailto_available,
        mailto_max_chars=MAILTO_MAX_CHARS,
    )


__all__ = ["MessageDetail", "message_detail"]
