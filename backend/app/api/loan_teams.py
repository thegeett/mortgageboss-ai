"""A loan file's team (LP-MB-Admin-05): who works it.

Nested under the file and resolved through ``ScopedLoanFile`` (the tenant gate). Reading the team is
open to anyone who can open the file; changing it is for an Admin, or the loan officer on their own
file (the service decides, and refuses with 403).
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.api.dependencies import CurrentActor, ScopedLoanFile
from app.core.database import DbSession
from app.schemas.loan_file import TeamPublic
from app.services import loan_teams as service

router = APIRouter(prefix="/loan-files/{file_identifier}/team", tags=["loan-teams"])


class TeamView(TeamPublic):
    #: Whether the caller may change this team, so the screen offers the controls only then.
    can_change: bool


class LoanOfficerPick(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID | None


class MemberPick(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID


async def _view(db: DbSession, actor: CurrentActor, loan_file: ScopedLoanFile) -> TeamView:
    members = await service.live_members(db, loan_file.id)
    return TeamView(
        **TeamPublic.model_validate(service.team_view(members)).model_dump(),
        can_change=await service.can_change(db, actor, loan_file),
    )


@router.get("", response_model=TeamView)
async def read_team(loan_file: ScopedLoanFile, db: DbSession, actor: CurrentActor) -> TeamView:
    return await _view(db, actor, loan_file)


@router.put("/loan-officer", response_model=TeamView)
async def put_loan_officer(
    payload: LoanOfficerPick, loan_file: ScopedLoanFile, db: DbSession, actor: CurrentActor
) -> TeamView:
    """Set the loan officer (a user with the Loan officer role), or clear it with null."""
    await service.set_loan_officer(db, actor, loan_file, payload.user_id)
    await db.commit()
    return await _view(db, actor, loan_file)


@router.post("/members", response_model=TeamView)
async def add_member(
    payload: MemberPick, loan_file: ScopedLoanFile, db: DbSession, actor: CurrentActor
) -> TeamView:
    """Add a processor. Already on the team: nothing changes."""
    await service.add_processor(db, actor, loan_file, payload.user_id)
    await db.commit()
    return await _view(db, actor, loan_file)


@router.delete("/members/{member_id}", response_model=TeamView)
async def remove_member(
    member_id: UUID, loan_file: ScopedLoanFile, db: DbSession, actor: CurrentActor
) -> TeamView:
    if not await service.remove_member(db, actor, loan_file, member_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")
    await db.commit()
    return await _view(db, actor, loan_file)
