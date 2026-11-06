"""Triage endpoints (LP-806) — see what arrived, and decide what it is.

TENANCY. Every file-scoped route declares `ScopedLoanFile`, so the file is fetched and
company-scope-checked before anything here runs. The attachment id is a PATH PARAMETER, which is why
`accept_attachment` re-checks that the attachment's message was routed to that same file — the route
proves the caller owns the FILE, and nothing but that check proves the ATTACHMENT belongs to it.

Nothing in this module derives a `company_id` from a message, a sender or a header. LP-805's resolver
remains the only place that turns an address into a company; here the company comes from the
authenticated user, as it does everywhere else in the API.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING
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
    MoveMessageRequest,
    UseAsConditionSheetRequest,
    UseAsConditionSheetResponse,
)
from app.services.condition_enrich import RoundNotEnrichable
from app.services.condition_rounds import ConditionSheetRejected
from app.services.condition_wrong_file import WrongFileRefused

if TYPE_CHECKING:
    from app.models.communication import Communication

from app.services.inbound_triage import (
    AcceptAs,
    CannotAcceptError,
    accept_attachment,
    attachment_preview,
    forward_attachment_as_sheet,
    list_file_messages,
    list_triage_queue,
    merge_attachment_into_round,
    move_unrouted_message,
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
        document_id=attachment.document_id,
    )


async def _messages_public(
    db: DbSession, messages: Sequence[InboundMessage]
) -> list[InboundMessagePublic]:
    """Each message with its attachments and its Communication, in two queries for the whole list."""
    from collections import defaultdict

    from sqlalchemy import select

    from app.models.communication import Communication
    from app.models.helpers import only_active

    ids = [message.id for message in messages]
    if not ids:
        return []
    attachments: defaultdict[UUID, list[InboundAttachment]] = defaultdict(list)
    for attachment in (
        await db.execute(
            only_active(
                select(InboundAttachment)
                .where(InboundAttachment.inbound_message_id.in_(ids))
                .order_by(InboundAttachment.created_at, InboundAttachment.id),
                InboundAttachment,
            )
        )
    ).scalars():
        attachments[attachment.inbound_message_id].append(attachment)
    communications: dict[UUID, Communication] = {
        communication.inbound_message_id: communication
        for communication in (
            await db.execute(
                only_active(
                    select(Communication).where(Communication.inbound_message_id.in_(ids)),
                    Communication,
                )
            )
        ).scalars()
        if communication.inbound_message_id is not None
    }
    return [
        _message_public(
            message,
            attachments=attachments.get(message.id, []),
            communication=communications.get(message.id),
        )
        for message in messages
    ]


def _message_public(
    message: InboundMessage,
    *,
    attachments: Sequence[InboundAttachment],
    communication: "Communication | None",
) -> InboundMessagePublic:
    # A MESSAGE WITH NO COMPANY NEVER REACHES THIS FROM A ROUTE: `list_triage_queue` returns only the
    # caller's company's rows (LP-1008). Kept as a second lock, because the cost of being wrong is
    # one tenant reading another tenant's borrower's address, subject line and filenames, as was once
    # measured here.
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
        communication_id=communication.id if communication else None,
        unread=communication is not None and communication.read_at is None,
    )


@company_router.get("/queue", response_model=list[InboundMessagePublic])
async def triage_queue(db: DbSession, current_user: CurrentUser) -> list[InboundMessagePublic]:
    """This company's mail, and no other company's. See `list_triage_queue`."""
    messages = await list_triage_queue(db, company_id=current_user.company_id)
    return await _messages_public(db, messages)


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
    return await _messages_public(db, messages)


@company_router.post("/messages/{message_id}/move", response_model=InboundMessagePublic)
async def move_to_file(
    message_id: UUID,
    payload: MoveMessageRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> InboundMessagePublic:
    """Move an unmatched email of this company to one of this company's files (LP-1009).

    The same 404 for another company's message or file as for one that does not exist; 409 when it
    is already on a file.
    """
    try:
        message = await move_unrouted_message(
            db,
            company_id=current_user.company_id,
            message_id=message_id,
            file_identifier=payload.file_identifier,
            actor_user_id=current_user.id,
        )
    except CannotAcceptError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such message or loan file")
    await db.commit()
    return (await _messages_public(db, [message]))[0]


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
    file, so no route can produce a preview for a message nobody owns. A thumbnail is the sender's
    content in the most legible form there is.

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


@router.post(
    "/attachments/{attachment_id}/condition-round",
    response_model=UseAsConditionSheetResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def use_as_condition_sheet(
    attachment_id: UUID,
    payload: UseAsConditionSheetRequest,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
    response: Response,
) -> UseAsConditionSheetResponse:
    """Use an emailed PDF as this file's condition sheet (LP-905, screen S1-13).

    THE PATH CARRIES THE LOAN FILE, AND THE SPEC'S DOES NOT. Spec §LP-905 writes
    `POST /api/inbound/attachments/{attachment_id}/condition-round` with `loan_file_id` in the body
    when the message is unrouted. This router is mounted at `/loan-files/{file_identifier}/inbound`,
    so the real path is `…/inbound/attachments/{id}/condition-round` — and that is the better shape,
    because `ScopedLoanFile` fetches the file scoped to the caller's company BEFORE the handler runs.
    A file id in the body would have to be scoped by hand, which is the check everyone forgets.
    Recorded as a spec-vs-code difference; the code wins, per the survey's rule.

    THE CAPABILITY THE SPEC DESCRIBED IS GENUINELY GONE, AND THAT IS AN EXISTING RULE RATHER THAN
    A NEW ONE. Spec §LP-905 puts `loan_file_id` in the body "if the message is unrouted"; here an
    unrouted attachment 404s at `_scoped_attachment`. `attachment_preview` in this module refuses
    the same way on purpose, and forwarding has the same exposure: it would create a round on a file
    from a message no company owns yet. Route the message first, then forward it.

    TWO OUTCOMES, TWO STATUS CODES, AND THE DIFFERENCE IS WHETHER ANYTHING WAS CREATED. Without
    `attach_to_round_id` this opens a new round and answers **202**: the round comes back `PARSING`
    and the UI polls it. With one, it MERGES into that round and answers **200** — nothing was
    created, nothing was queued, and there is nothing to poll. LP-905 refused that branch with a
    `501` because the merge did not exist; LP-907 is the merge.
    """
    attachment = await _scoped_attachment(
        db, loan_file_id=loan_file.id, attachment_id=attachment_id
    )

    if payload.attach_to_round_id is not None:
        # LP-907 ARRIVED, SO THE `501` IS GONE. This merges into the named round and creates NO
        # second round — which is why it answers 200 rather than the 202 the create path uses: there
        # is nothing to poll, because nothing was queued and nothing was created.
        try:
            merged = await merge_attachment_into_round(
                db,
                loan_file=loan_file,
                attachment=attachment,
                round_id=payload.attach_to_round_id,
                actor_user_id=current_user.id,
                confirm_wrong_file=payload.confirm_wrong_file,
            )
        except WrongFileRefused as exc:
            # LP-951 — the attach door's shape: a code, so the client offers the confirmation.
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail={"message": exc.message, "code": "wrong_file"}
            ) from exc
        except ConditionSheetRejected as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.reason) from exc
        except RoundNotEnrichable as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.reason) from exc
        except CannotAcceptError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        await db.commit()
        await db.refresh(merged)
        await db.refresh(attachment)
        # SET EXPLICITLY, BECAUSE THE DECORATOR'S 202 IS THE DEFAULT FOR THE WHOLE HANDLER AND
        # RETURNING A MODEL DOES NOT OVERRIDE IT. The first version of this branch documented "two
        # outcomes, two status codes" and shipped one — the merge answered 202 while the docstring
        # said 200, which is a comment asserting behaviour the code did not have. `auth.py` injects
        # `Response` for the same reason.
        #
        # The distinction is worth the parameter: 202 means "accepted, still being worked on", and
        # the UI polls a `PARSING` round on the strength of it. A merge is finished when it answers
        # and queued nothing, so a client polling it would be polling a round that never changes.
        response.status_code = status.HTTP_200_OK
        return UseAsConditionSheetResponse(
            round_id=merged.id,
            status=merged.status.value,
            disposition=attachment.disposition.value,
        )
    try:
        round_ = await forward_attachment_as_sheet(
            db, loan_file=loan_file, attachment=attachment, actor_user_id=current_user.id
        )
    except ConditionSheetRejected as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.reason) from exc
    except CannotAcceptError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await db.commit()
    await db.refresh(round_)
    await db.refresh(attachment)

    # After the commit, for the same reason the upload endpoint enqueues there: a worker that picked
    # the round up before the transaction landed would find no row.
    # UNGUARDED, DELIBERATELY. `api/conditions.py`'s `_enqueue_split_or_fail` guards the same call
    # on the paste door and this one does not: the round is committed in `PARSING` before `.delay()`
    # is reached, so a broker that is down strands it exactly the same way. Left as LP-905 shipped
    # it — changing a committed door inside an AI-split ticket is how a ticket becomes a refactor —
    # and the mitigation belongs with the reaper that closes it properly (LP-908 review).
    from app.tasks.conditions import parse_condition_round

    parse_condition_round.delay(str(round_.id))

    return UseAsConditionSheetResponse(
        round_id=round_.id,
        status=round_.status.value,
        disposition=attachment.disposition.value,
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
