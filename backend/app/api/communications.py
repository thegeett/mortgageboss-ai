"""Outbound communication endpoints (LP-811a) — preview a draft, and record that it was sent.

NOTHING HERE TRANSMITS. M1's send path is copy-and-send: the processor puts the text into their own
mail client, or opens a `mailto:` link. LP-816 is the ticket that transmits through a connected
mailbox. So "send" here means *record that it went out* — and record it in the one place that starts
LP-814's reminder clock.

Tenant gate: every route declares :data:`ScopedLoanFile`, so the file is fetched and company-scoped
before anything else runs, exactly as needs/borrowers/property do. Nothing in this module derives a
`company_id`; LP-805's resolver remains the only place allowed to do that.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app.api.dependencies import CurrentUser, ScopedLoanFile
from app.core.database import DbSession
from app.documents.catalog import CATALOG
from app.models.communication import Communication
from app.schemas.communication import (
    OutboundDraftPublic,
    SendDraftRequest,
    SentCommunicationPublic,
)
from app.services.email_draft import (
    _needs_in_draft,
    attach_upload_link,
    compose_request,
    draft_for_reading,
    get_open_draft,
)
from app.services.email_reply import (
    CannotReplyError,
    create_compose_draft,
    create_reply_draft,
    log_reply_sent,
    mark_read,
    reply_context,
    set_important,
)
from app.services.email_send import CannotSendError, build_outbound, send_draft
from app.services.message_detail import message_detail

router = APIRouter(prefix="/loan-files/{file_identifier}/outbound", tags=["communications"])

_NO_DRAFT = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="No open document request on this loan file"
)


@router.get("/draft", response_model=OutboundDraftPublic)
async def get_open_draft_endpoint(
    loan_file: ScopedLoanFile, db: DbSession, current_user: CurrentUser
) -> OutboundDraftPublic:
    """The file's open document request, assembled as a message."""
    draft = await get_open_draft(db, loan_file_id=loan_file.id)
    if draft is None:
        raise _NO_DRAFT
    needs = await _needs_in_draft(db, draft=draft)
    # LP-823 — RESOLVED FOR READING, and the stored body is untouched. The panel puts this text in
    # the textarea, and the textarea is what "Copy message" and "Open in mail client" send, so an
    # unresolved body here is not a display bug: it is what the borrower receives. The reader is the
    # prospective signer; `send_draft` resolves again from whoever actually sends.
    resolved, suggested_recipient = await draft_for_reading(
        db, draft=draft, loan_file=loan_file, reader=current_user
    )
    outbound = build_outbound(loan_file, subject=draft.subject or "", body=resolved)
    return OutboundDraftPublic(
        id=draft.id,
        subject=outbound.subject,
        body=outbound.body,
        reply_to=outbound.reply_to,
        suggested_bcc=outbound.suggested_bcc,
        mailto_available=outbound.mailto_available,
        needs_item_count=len(needs),
        suggested_recipient=suggested_recipient,
    )


class ComposeRequestPayload(BaseModel):
    """The document types a processor picked (LP-833)."""

    #: At least one, and a bounded list. An empty selection is a click that meant nothing, and an
    #: unbounded one is a way to put 166 documents in a borrower's inbox with one request.
    document_types: list[str] = Field(min_length=1, max_length=40)


class ComposedRequestPublic(BaseModel):
    """What the compose produced."""

    draft_id: UUID | None
    needs_added: int
    #: Whether a MODEL wrote the framing, or LP-817's template did. Served so the screen can say
    #: which — `email_draft_enabled` is off in every environment, so today this is always False and
    #: the processor gets the template. A flow claiming otherwise would be untrue about itself.
    composed_by_model: bool


@router.post("/compose", response_model=ComposedRequestPublic, status_code=status.HTTP_201_CREATED)
async def compose_request_endpoint(
    payload: ComposeRequestPayload,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> ComposedRequestPublic:
    """Ask for documents a processor picked, rather than ones a rule found (LP-833).

    REFUSES A TYPE THE CATALOG DOES NOT KNOW. A needs item with an unrecognised `needs_type` has no
    tier, no category and no extractor — LP-638 found the same defect on the correction control,
    where two of eight hardcoded options were not catalog types at all. The picker is served FROM the
    catalog, so an unknown value here is a caller that did not use it.
    """
    unknown = sorted(t for t in payload.document_types if t not in CATALOG)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Not document types in the catalog: {unknown}",
        )

    composed = await compose_request(
        db,
        loan_file=loan_file,
        document_types=payload.document_types,
        actor_user_id=current_user.id,
    )
    await db.commit()
    return ComposedRequestPublic(
        draft_id=composed.update.draft.id if composed.update.draft else None,
        needs_added=len(composed.update.added),
        composed_by_model=composed.composed_by_model,
    )


@router.post("/draft/{draft_id}/send", response_model=SentCommunicationPublic)
async def send_draft_endpoint(
    draft_id: UUID,
    payload: SendDraftRequest,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> SentCommunicationPublic:
    """Record that this draft was sent, and move everything it asked for to REQUESTED.

    ONE DRAFT PER CALL — no bulk send, which the plan requires and the rate limit depends on. A bulk
    path would either bypass the per-address limit or fail halfway through a list with no way to say
    which half went out.

    ``draft_id`` is in the path rather than inferred from the file, so sending is an action against a
    specific message a processor has looked at. Inferring it would let a draft that changed between
    the read and the click be sent unseen — which for a borrower-facing email is the whole risk.

    The approver is the authenticated user, recorded on the activity-log entry. `phase4.md` §6 wants
    an "authenticated approver" field on the evidence record itself; that record is LP-821's, and the
    activity log is where the fact lives until then.
    """
    try:
        sent = await send_draft(
            db,
            loan_file=loan_file,
            draft_id=draft_id,
            recipient=payload.recipient,
            body=payload.body,
            subject=payload.subject,
            approver_user_id=current_user.id,
        )
    except CannotSendError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    needs = await _needs_in_draft(db, draft=sent)
    await db.commit()
    return SentCommunicationPublic(
        id=sent.id,
        status=sent.status.value,
        sent_at=sent.sent_at,
        needs_items_requested=len(needs),
    )


# --------------------------------------------------------------------------------------------- #
# Reply, compose, and the two flags (LP-818)
# --------------------------------------------------------------------------------------------- #
message_router = APIRouter(prefix="/loan-files/{file_identifier}/messages", tags=["communications"])


class ReplyContextPublic(BaseModel):
    """What a reply will be addressed to, before anything is typed.

    SHOWN BEFORE THE BOX, not filled into an editable field. The recipient comes from the stored
    inbound message and is not a processor's to change — a reply that went somewhere else would
    still be threaded to this conversation and would read, to whoever received it, as part of it.
    """

    recipient: str
    subject: str


class ReplyRequest(BaseModel):
    body: str = Field(min_length=1)


class ComposeRequest(BaseModel):
    recipient: EmailStr
    subject: str = Field(min_length=1, max_length=256)
    body: str = Field(min_length=1)


class ImportantRequest(BaseModel):
    important: bool


class ReadRequest(BaseModel):
    read: bool = True


class MessagePublic(BaseModel):
    """One message after a change to it. Never the body — the caller already has what they typed."""

    id: UUID
    direction: str
    status: str
    subject: str | None
    recipient: str | None
    is_important: bool
    read_at: str | None

    @classmethod
    def of(cls, message: Communication) -> "MessagePublic":
        return cls(
            id=message.id,
            direction=message.direction.value,
            status=message.status.value,
            subject=message.subject,
            recipient=message.recipient,
            is_important=message.is_important,
            read_at=message.read_at.isoformat() if message.read_at else None,
        )


def _refuse(exc: CannotReplyError) -> HTTPException:
    """A refusal a caller can act on, at 409.

    NOT 404 FOR THE CROSS-FILE CASE EITHER — the service already returns the same sentence for "no
    such message" and "on another file", so the status carries no more information than the text.
    """
    return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))


class MessageAttachmentPublic(BaseModel):
    """One file on an inbound message, and what became of it (LP-825's manifest)."""

    name: str
    disposition: str


class MessageDetailPublic(BaseModel):
    """One message in full — the dialog a processor opens from the timeline (LP-829).

    THE BODY IS HERE, and that is the whole point. `MessagePublic` withholds it — *"the caller
    already has what they typed"* — which is right for a write response and left a sent message's
    words readable nowhere in the product.
    """

    id: UUID
    direction: str
    status: str
    subject: str | None
    body: str
    counterparty: str | None
    template_key: str | None
    template_version: str | None
    created_at: datetime
    sent_at: datetime | None
    read_at: datetime | None
    is_important: bool
    error_detail: str | None
    documents: list[str]
    attachments: list[MessageAttachmentPublic]
    is_open_draft: bool
    #: LP-831 — whether the modal offers an editor and a send. Wider than `is_open_draft`: a party
    #: request is a draft under its own template key, and that filter is why no screen could send one.
    is_editable: bool
    suggested_recipient: str | None
    #: LP-831 review — what a `mailto:` link and a copy need. Nothing here transmits mail, so these
    #: are how the message actually reaches anybody; see `MessageDetail`.
    suggested_bcc: str
    mailto_available: bool
    mailto_max_chars: int


@message_router.post("/{communication_id}/upload-link", response_model=MessageDetailPublic)
async def attach_upload_link_endpoint(
    communication_id: UUID,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> MessageDetailPublic:
    """Put a secure upload link in this draft, expiring any other live one on the file (LP-834).

    ON THE DRAFT, NOT ON THE FILE, because "the link in this draft" is the phrase that has to be
    true. A file-level mint would leave the processor to paste it, which is the gap this closes.

    REFUSES ANYTHING THAT IS NOT AN EDITABLE DRAFT. A sent message must not gain a link — LP-821's
    evidence record is what actually went out — and an inbound one is not ours to edit at all.
    """
    detail = await message_detail(
        db, loan_file=loan_file, communication_id=communication_id, reader=current_user
    )
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such message on this loan file")
    if not detail.is_editable:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This message has already been sent and cannot be changed.",
        )

    draft = await db.get(Communication, communication_id)
    assert draft is not None
    await attach_upload_link(db, loan_file=loan_file, draft=draft)
    await db.commit()
    return await read_message(communication_id, loan_file, db, current_user)


@message_router.get("/{communication_id}", response_model=MessageDetailPublic)
async def read_message(
    communication_id: UUID,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> MessageDetailPublic:
    """One message in full.

    SCOPED BY THE FILE, like every other route on this router: `ScopedLoanFile` resolves the file
    under the caller's company first, and the service then checks `loan_file_id` on the row itself
    rather than trusting the id in the path. A message on another company's file is a 404 — the same
    answer a message that does not exist gets, because telling those apart is how a caller
    enumerates what another tenant has.

    NO BODY IN ANY LOG LINE. This is the fullest copy of a borrower's prose the product serves, and
    `communications.body` is dropped from every readonly view for the same reason.
    """
    detail = await message_detail(
        db, loan_file=loan_file, communication_id=communication_id, reader=current_user
    )
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such message on this loan file")
    return MessageDetailPublic(
        id=detail.id,
        direction=detail.direction,
        status=detail.status,
        subject=detail.subject,
        body=detail.body,
        counterparty=detail.counterparty,
        template_key=detail.template_key,
        template_version=detail.template_version,
        created_at=detail.created_at,
        sent_at=detail.sent_at,
        read_at=detail.read_at,
        is_important=detail.is_important,
        error_detail=detail.error_detail,
        documents=list(detail.documents),
        attachments=[
            MessageAttachmentPublic(name=a.name, disposition=a.disposition)
            for a in detail.attachments
        ],
        is_open_draft=detail.is_open_draft,
        is_editable=detail.is_editable,
        suggested_recipient=detail.suggested_recipient,
        suggested_bcc=detail.suggested_bcc,
        mailto_available=detail.mailto_available,
        mailto_max_chars=detail.mailto_max_chars,
    )


@message_router.get("/{communication_id}/reply-context", response_model=ReplyContextPublic)
async def read_reply_context(
    communication_id: UUID,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> ReplyContextPublic:
    """Who a reply would go to, and what it would be called."""
    try:
        context = await reply_context(db, loan_file=loan_file, communication_id=communication_id)
    except CannotReplyError as exc:
        raise _refuse(exc) from exc
    return ReplyContextPublic(recipient=context.recipient, subject=context.subject)


@message_router.post(
    "/{communication_id}/reply",
    response_model=MessagePublic,
    status_code=status.HTTP_201_CREATED,
)
async def reply(
    communication_id: UUID,
    payload: ReplyRequest,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> MessagePublic:
    """Prepare a reply to one arrived message.

    IT IS A DRAFT, NOT A SEND. The send path is unchanged — LP-811a's `POST /outbound/draft/{id}/send`
    takes it from here, with the same rate limit, the same suppression check and the same record of
    what actually went out. A reply that skipped that would be the one outbound message in the
    product with no guardrails on it.
    """
    try:
        draft = await create_reply_draft(
            db,
            loan_file=loan_file,
            communication_id=communication_id,
            body=payload.body,
            actor_user_id=current_user.id,
        )
        await log_reply_sent(db, loan_file=loan_file, reply=draft, actor_user_id=current_user.id)
    except CannotReplyError as exc:
        raise _refuse(exc) from exc
    await db.commit()
    return MessagePublic.of(draft)


@message_router.post("", response_model=MessagePublic, status_code=status.HTTP_201_CREATED)
async def compose(
    payload: ComposeRequest,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> MessagePublic:
    """Prepare a message with no needs and nothing being answered."""
    try:
        draft = await create_compose_draft(
            db,
            loan_file=loan_file,
            recipient=payload.recipient,
            subject=payload.subject,
            body=payload.body,
            actor_user_id=current_user.id,
        )
    except CannotReplyError as exc:
        raise _refuse(exc) from exc
    await db.commit()
    return MessagePublic.of(draft)


@message_router.post("/{communication_id}/important", response_model=MessagePublic)
async def flag(
    communication_id: UUID,
    payload: ImportantRequest,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> MessagePublic:
    """Flag a message, or unflag it. A processor's own judgement; nothing else writes this."""
    try:
        message = await set_important(
            db,
            loan_file=loan_file,
            communication_id=communication_id,
            important=payload.important,
        )
    except CannotReplyError as exc:
        raise _refuse(exc) from exc
    await db.commit()
    return MessagePublic.of(message)


@message_router.post("/{communication_id}/read", response_model=MessagePublic)
async def read_state(
    communication_id: UUID,
    payload: ReadRequest,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> MessagePublic:
    """Mark an arrived message read, or put it back to unread."""
    try:
        message = await mark_read(
            db, loan_file=loan_file, communication_id=communication_id, read=payload.read
        )
    except CannotReplyError as exc:
        raise _refuse(exc) from exc
    await db.commit()
    return MessagePublic.of(message)
