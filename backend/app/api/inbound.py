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

from fastapi import APIRouter, HTTPException, status

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
    list_triage_queue,
    reject_attachment,
)

router = APIRouter(prefix="/loan-files/{file_identifier}/inbound", tags=["inbound"])
company_router = APIRouter(prefix="/inbound", tags=["inbound"])

_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="No such inbound attachment on this loan file"
)


def _attachment_public(attachment: InboundAttachment) -> InboundAttachmentPublic:
    return InboundAttachmentPublic(
        id=attachment.id,
        filename_original=attachment.filename_original,
        filename_normalized=attachment.filename_normalized,
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
    return InboundMessagePublic(
        id=message.id,
        loan_file_id=message.loan_file_id,
        routing_state=message.routing_state.value,
        routing_signal=message.routing_signal,
        routing_confidence=message.routing_confidence,
        is_dsn=message.is_dsn,
        is_auto_reply=message.is_auto_reply,
        from_address=message.from_address,
        subject=message.subject,
        received_at=message.received_at,
        auth_verdicts={k: str(v) for k, v in (message.auth_verdicts or {}).items()},
        attachments=[_attachment_public(a) for a in attachments],
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
