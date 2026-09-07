"""Outbound communication endpoints (LP-811a) — preview a draft, and record that it was sent.

NOTHING HERE TRANSMITS. M1's send path is copy-and-send: the processor puts the text into their own
mail client, or opens a `mailto:` link. LP-816 is the ticket that transmits through a connected
mailbox. So "send" here means *record that it went out* — and record it in the one place that starts
LP-814's reminder clock.

Tenant gate: every route declares :data:`ScopedLoanFile`, so the file is fetched and company-scoped
before anything else runs, exactly as needs/borrowers/property do. Nothing in this module derives a
`company_id`; LP-805's resolver remains the only place allowed to do that.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import CurrentUser, ScopedLoanFile
from app.core.database import DbSession
from app.schemas.communication import (
    OutboundDraftPublic,
    SendDraftRequest,
    SentCommunicationPublic,
)
from app.services.email_draft import _needs_in_draft, get_open_draft
from app.services.email_send import CannotSendError, build_outbound, send_draft

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
    outbound = build_outbound(loan_file, subject=draft.subject or "", body=draft.body or "")
    return OutboundDraftPublic(
        id=draft.id,
        subject=outbound.subject,
        body=outbound.body,
        reply_to=outbound.reply_to,
        suggested_bcc=outbound.suggested_bcc,
        mailto_available=outbound.mailto_available,
        needs_item_count=len(needs),
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
