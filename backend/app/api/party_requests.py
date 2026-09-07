"""Requests to somebody who is not the borrower (LP-820).

WHAT THIS SCREEN IS FOR. LP-800 sorts 166 document types to eight parties and, before this ticket,
only the borrower could be written to. Thirteen types across title, agent, CPA, insurer and employer
had no address anywhere in the schema — so those needs, in the build plan's words, *"sit at PENDING
forever, never get `requested_at`, and are invisible to LP-814."*

THE LIST INCLUDES THE PARTIES WE CANNOT REACH. That is the point rather than an oversight: a screen
that showed only what it could send would present a file with five outstanding title documents as
having nothing to do. `reachable` is false, and the answer is to add an address.

Every route declares `ScopedLoanFile`. Nothing here derives a `company_id`.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app.api.dependencies import CurrentUser, ScopedLoanFile
from app.core.database import DbSession
from app.documents.catalog import ResponsibleParty
from app.models.loan_file_participant import ParticipantRole
from app.services.party_requests import (
    PartyRequest,
    add_participant,
    build_party_draft,
    open_requests,
    remove_participant,
)

router = APIRouter(prefix="/loan-files/{file_identifier}/party-requests", tags=["communications"])


class NeedSummary(BaseModel):
    id: UUID
    title: str


class PartyRequestPublic(BaseModel):
    """One party's outstanding documents, and whether we can reach them."""

    party: str
    role: str
    address: str | None
    name: str | None
    reachable: bool
    needs: list[NeedSummary]

    @classmethod
    def of(cls, request: PartyRequest) -> "PartyRequestPublic":
        return cls(
            party=request.party.value,
            role=request.role.value,
            address=request.address,
            name=request.name,
            reachable=request.reachable,
            needs=[NeedSummary(id=need.id, title=need.title) for need in request.needs],
        )


class AddAddress(BaseModel):
    """Where a party can be reached.

    THE ROLE IS THE CALLER'S, not derived from the address. Two parties can share a mailbox — a small
    brokerage where the agent is also the title contact — and guessing from the domain would put one
    request in the other's thread.
    """

    role: ParticipantRole
    email: EmailStr
    name: str | None = Field(default=None, max_length=128)


class BuildDraft(BaseModel):
    party: ResponsibleParty


class DraftBuilt(BaseModel):
    communication_id: UUID
    recipient: str | None
    subject: str | None
    needs_count: int


@router.get("", response_model=list[PartyRequestPublic])
async def outstanding(
    loan_file: ScopedLoanFile, db: DbSession, current_user: CurrentUser
) -> list[PartyRequestPublic]:
    """Everything outstanding on this file, grouped by who has to be asked."""
    return [
        PartyRequestPublic.of(request) for request in await open_requests(db, loan_file=loan_file)
    ]


@router.post("/addresses", status_code=status.HTTP_201_CREATED)
async def add_address(
    payload: AddAddress,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> dict[str, str]:
    """Record where a party can be reached.

    NEVER TRUSTED. `is_trusted_sender` stays false, exactly as LP-805's seeding leaves it: an address
    a processor typed is somebody we can write TO, not somebody whose attachments should bypass
    review. §2.3's default is quarantine and this does not move it.
    """
    try:
        await add_participant(
            db, loan_file=loan_file, role=payload.role, email=payload.email, name=payload.name
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return {"status": "recorded"}


@router.delete("/addresses/{participant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_address(
    participant_id: UUID,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> None:
    """Remove an address from this file. The same 404 for missing and for another file's."""
    if not await remove_participant(db, loan_file=loan_file, participant_id=participant_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such address on this loan file")
    await db.commit()


@router.post("/draft", response_model=DraftBuilt, status_code=status.HTTP_201_CREATED)
async def draft_for_party(
    payload: BuildDraft,
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
) -> DraftBuilt:
    """Build this party's accumulating request.

    A DRAFT ON THE EXISTING SEND PATH. LP-811a's `POST /outbound/draft/{id}/send` takes it from here
    — same rate limit, same suppression check, and the same `request_needs_item` call that stamps
    `requested_at` and starts LP-814's clock. That call is the whole reason this is a real draft
    rather than a separate mailer: the build plan's complaint was that these needs never get the
    stamp, and reusing the send path is what fixes it rather than a second path that would have to
    remember to.
    """
    try:
        draft = await build_party_draft(
            db, loan_file=loan_file, party=payload.party, actor_user_id=current_user.id
        )
    except ValueError as exc:
        # 409 WITH THE SENTENCE. "There is no address on this file for that party" is the one a
        # processor can act on, and it is the common case this ticket exists for.
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    from app.services.email_draft import _needs_in_draft

    needs = await _needs_in_draft(db, draft=draft)
    await db.commit()
    return DraftBuilt(
        communication_id=draft.id,
        recipient=draft.recipient,
        subject=draft.subject,
        needs_count=len(needs),
    )
