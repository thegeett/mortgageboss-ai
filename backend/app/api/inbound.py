"""Triage endpoints (LP-806) — see what arrived, and decide what it is.

TENANCY. Every file-scoped route declares `ScopedLoanFile`, so the file is fetched and
company-scope-checked before anything here runs. The attachment id is a PATH PARAMETER, which is why
`accept_attachment` re-checks that the attachment's message was routed to that same file — the route
proves the caller owns the FILE, and nothing but that check proves the ATTACHMENT belongs to it.

Nothing in this module derives a `company_id` from a message, a sender or a header. LP-805's resolver
remains the only place that turns an address into a company; here the company comes from the
authenticated user, as it does everywhere else in the API.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status

from app.api.dependencies import CurrentUser, ScopedLoanFile
from app.core.database import DbSession
from app.models.inbound_attachment import InboundAttachment
from app.models.inbound_message import InboundMessage
from app.schemas.inbound import (
    AcceptAttachmentRequest,
    AcceptAttachmentResponse,
    InboundAttachmentPublic,
    InboundMessagePublic,
)
from app.services.inbound_triage import (
    AcceptAs,
    CannotAcceptError,
    accept_attachment,
    attachment_preview,
    list_file_messages,
    list_triage_queue,
    reject_attachment,
)

router = APIRouter(prefix="/loan-files/{file_identifier}/inbound", tags=["inbound"])
company_router = APIRouter(prefix="/inbound", tags=["inbound"])

_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="No such inbound attachment on this loan file"
)


def _attachment_public(
    attachment: InboundAttachment, *, redacted: bool = False
) -> InboundAttachmentPublic:
    """One attachment, with the sender's own words dropped when nobody owns the message yet.

    `redacted` is keyword-only and defaults to False so the file-scoped callers are unchanged; the
    queue passes True for an unclaimed message. Size, safety state and content types stay — they are
    OUR assessment of the bytes, not the sender's text, and they are what a processor needs to judge
    whether a message is worth claiming.
    """
    return InboundAttachmentPublic(
        id=attachment.id,
        filename_original=None if redacted else attachment.filename_original,
        filename_normalized=None if redacted else attachment.filename_normalized,
        declared_content_type=attachment.declared_content_type,
        sniffed_content_type=attachment.sniffed_content_type,
        size_bytes=attachment.size_bytes,
        safety_state=attachment.safety_state.value,
        safety_reason=attachment.safety_reason,
        disposition=attachment.disposition.value,
        nesting_depth=attachment.nesting_depth,
    )


async def _message_public(db: DbSession, message: InboundMessage) -> InboundMessagePublic:
    from sqlalchemy import select

    from app.models.helpers import only_active

    attachments = (
        (
            await db.execute(
                only_active(
                    select(InboundAttachment).where(
                        InboundAttachment.inbound_message_id == message.id
                    ),
                    InboundAttachment,
                )
            )
        )
        .scalars()
        .all()
    )
    # AN UNROUTED MESSAGE IS SHOWN TO EVERY COMPANY, so nothing the SENDER wrote may travel with it.
    #
    # It has no `company_id` — LP-805 refuses to guess one — so the queue returns it to whoever
    # asks. Before this redaction that meant one tenant received another tenant's borrower's
    # personal email address, a subject line that in this domain routinely names the borrower and
    # the property, and the sender's own filenames. Measured: `from_address` came back as
    # `jane.borrower@personal-email.com` and the subject as "Docs for 42 Maple Ave - Jane Borrower"
    # to a company with no connection to either.
    #
    # `phase4.md` §2.2 requires an unrouted message to stay VISIBLE — "confidence gates
    # auto-acceptance, never visibility" — and visible is satisfied by the fact of it, its shape and
    # its age. `InboundAttachmentPublic`'s own docstring names the condition that makes returning
    # `filename_original` safe: "an authenticated user of the OWNING COMPANY, over a route already
    # scoped to their loan file". An unrouted message has no owning company and this route is not
    # file-scoped, so that condition simply is not met here.
    #
    # Everything comes back the moment a company CLAIMS the message, which is the reassign
    # operation this ticket deliberately left for its own design.
    unclaimed = message.company_id is None
    return InboundMessagePublic(
        id=message.id,
        loan_file_id=message.loan_file_id,
        routing_state=message.routing_state.value,
        routing_signal=message.routing_signal,
        routing_confidence=message.routing_confidence,
        is_dsn=message.is_dsn,
        is_auto_reply=message.is_auto_reply,
        from_address=None if unclaimed else message.from_address,
        subject=None if unclaimed else message.subject,
        received_at=message.received_at,
        auth_verdicts={k: str(v) for k, v in (message.auth_verdicts or {}).items()},
        attachments=[_attachment_public(a, redacted=unclaimed) for a in attachments],
    )


@company_router.get("/queue", response_model=list[InboundMessagePublic])
async def triage_queue(
    db: DbSession, current_user: CurrentUser, include_unrouted: bool = True
) -> list[InboundMessagePublic]:
    """Everything awaiting a decision for this company.

    COMPANY-LEVEL, not file-level, because the interesting rows have no file. `phase4.md` §2.2:
    "confidence gates auto-acceptance, never visibility" — an unrouted message must be visible, and
    it has no `company_id` precisely because LP-805 refuses to guess one from the sender.

    `include_unrouted` is a parameter rather than an assumption so a caller has to ask.
    """
    messages = await list_triage_queue(
        db, company_id=current_user.company_id, include_unrouted=include_unrouted
    )
    return [await _message_public(db, message) for message in messages]


@router.get("/messages", response_model=list[InboundMessagePublic])
async def file_messages(
    loan_file: ScopedLoanFile, db: DbSession, current_user: CurrentUser
) -> list[InboundMessagePublic]:
    """Everything that arrived for this loan file, newest first.

    FILE-SCOPED, so every message it can return has a `company_id` — it was routed to a file, and a
    file has an owner. The redaction `_message_public` applies to unclaimed messages is therefore
    unreachable from here, which is the intended shape: the sender's words are visible exactly where
    somebody owns them.
    """
    messages = await list_file_messages(db, loan_file=loan_file)
    return [await _message_public(db, message) for message in messages]


async def _scoped_attachment(
    db: DbSession, *, loan_file_id: UUID, attachment_id: UUID
) -> InboundAttachment:
    attachment = await db.get(InboundAttachment, attachment_id)
    if attachment is None or attachment.deleted_at is not None:
        raise _NOT_FOUND
    message = await db.get(InboundMessage, attachment.inbound_message_id)
    if message is None or message.loan_file_id != loan_file_id:
        # SAME 404 AS A MISSING ONE. Distinguishing "no such attachment" from "that attachment is on
        # another company's file" would confirm the id exists — an oracle over other tenants' rows.
        raise _NOT_FOUND
    return attachment


@router.get(
    "/attachments/{attachment_id}/preview",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def attachment_preview_png(
    attachment_id: UUID,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> Response:
    """A PNG thumbnail of one attachment. 409 when it is not safe, 415 when it cannot be rendered.

    ONLY REACHABLE FOR A ROUTED MESSAGE. The route is file-scoped and an unrouted message has no
    file, so the company-level queue cannot produce a preview for a message nobody owns — which
    matters more here than anywhere else in this module: the unrouted queue is visible to every
    company, and a thumbnail is the sender's content in the most legible form there is. Dropping
    their filename from that queue and then rendering their document would give back everything the
    redaction took, and more.

    NOT CACHEABLE BY A SHARED CACHE. The bytes are one borrower's document, served over a route whose
    authorisation is per-user.
    """
    attachment = await _scoped_attachment(
        db, loan_file_id=loan_file.id, attachment_id=attachment_id
    )
    try:
        png = await attachment_preview(db, attachment=attachment)
    except CannotAcceptError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if png is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="This file has no preview. Accept it to open it in the document viewer.",
        )
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Cache-Control": "private, no-store",
            # The body is a PNG this server rendered, but the header costs nothing and the rule is
            # that nothing on this path relies on a browser agreeing with us about a type.
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/attachments/{attachment_id}/accept", response_model=AcceptAttachmentResponse)
async def accept(
    attachment_id: UUID,
    payload: AcceptAttachmentRequest,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> AcceptAttachmentResponse:
    """Accept one attachment onto this file, as a document or as correspondence."""
    attachment = await _scoped_attachment(
        db, loan_file_id=loan_file.id, attachment_id=attachment_id
    )
    try:
        result = await accept_attachment(
            db,
            loan_file=loan_file,
            attachment=attachment,
            actor_user_id=current_user.id,
            accept_as=AcceptAs.CORRESPONDENCE if payload.as_correspondence else AcceptAs.DOCUMENT,
        )
    except CannotAcceptError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    return AcceptAttachmentResponse(
        document_id=result.document.id if result.document else None,
        disposition=result.attachment.disposition.value,
        possible_duplicate=result.flagged_possible_duplicate,
    )


@router.post("/attachments/{attachment_id}/reject", response_model=AcceptAttachmentResponse)
async def reject(
    attachment_id: UUID,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> AcceptAttachmentResponse:
    """Refuse one attachment. It stays on the message and does not become a document."""
    attachment = await _scoped_attachment(
        db, loan_file_id=loan_file.id, attachment_id=attachment_id
    )
    try:
        updated = await reject_attachment(
            db, loan_file=loan_file, attachment=attachment, actor_user_id=current_user.id
        )
    except CannotAcceptError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    return AcceptAttachmentResponse(
        document_id=None, disposition=updated.disposition.value, possible_duplicate=False
    )
