"""People: the company's users, their details, roles and access (LP-MB-Admin-03).

Every route needs ``users.manage``. A user of another company is a 404, never a 403, so an id from
another tenant reveals nothing. The rules live in ``services/users``; a refusal arrives as a 409 or 422
with the sentence the People sheet shows.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.dependencies import CurrentActor, require_permission
from app.core.database import DbSession
from app.core.permissions import Permission
from app.models.user import User, UserRole, UserRoleAssignment
from app.schemas.users import UserAdminView, UserDetailsUpdate, UserRolesUpdate
from app.services import users as service
from app.services.loan_teams import live_place_counts, reassign_user_loans

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_permission(Permission.USERS_MANAGE))],
)
#: LP-MB-Admin-05 — the one users route any signed-in person may call: who can be put on a team.
#: A separate router because `router` requires `users.manage` for everything on it, and MOUNTED
#: BEFORE IT, because `/users/{user_id}` would otherwise take `/users/assignable` and refuse it.
assignable_router = APIRouter(prefix="/users", tags=["users"])


class Assignable(BaseModel):
    """A person who can take a team slot."""

    id: UUID
    name: str
    roles: list[UserRole]
    #: Live files they are on now, so a picker can show the load.
    file_count: int


class ReassignBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_user_id: UUID


class Reassigned(BaseModel):
    moved: int


@assignable_router.get("/assignable", response_model=list[Assignable])
async def assignable(
    db: DbSession,
    actor: CurrentActor,
    team_role: Literal["loan_officer", "processor"],
) -> list[Assignable]:
    """Active people of the company who hold the slot's role, by name."""
    needed = UserRole.LOAN_OFFICER if team_role == "loan_officer" else UserRole.PROCESSOR
    people = await db.scalars(
        select(User)
        .where(
            User.company_id == actor.company_id,
            User.deleted_at.is_(None),
            User.is_active.is_(True),
            User.id.in_(
                select(UserRoleAssignment.user_id).where(UserRoleAssignment.role == needed)
            ),
        )
        .order_by(User.first_name, User.last_name)
    )
    counts = await live_place_counts(db, actor.company_id)
    return [
        Assignable(
            id=user.id,
            name=user.full_name,
            roles=sorted(user.role_set),
            file_count=counts.get(user.id, 0),
        )
        for user in people
    ]


_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")


async def _view(db: DbSession, actor: CurrentActor, user: User | None) -> UserAdminView:
    if user is None:
        raise _NOT_FOUND
    counts = await live_place_counts(db, actor.company_id)
    return UserAdminView.of(
        user,
        owner_user_id=await service.company_owner_id(db, actor),
        file_count=counts.get(user.id, 0),
    )


@router.get("", response_model=list[UserAdminView])
async def list_people(
    db: DbSession,
    actor: CurrentActor,
    # Aliased: `status` is FastAPI's module, imported above for the 404.
    status_: Annotated[Literal["active", "inactive"] | None, Query(alias="status")] = None,
    role: UserRole | None = None,
) -> list[UserAdminView]:
    """The company's people, active and inactive. No pagination: a company's people fit a page."""
    people = await service.list_users(db, actor, status=status_, role=role)
    owner = await service.company_owner_id(db, actor)
    counts = await live_place_counts(db, actor.company_id)
    return [
        UserAdminView.of(user, owner_user_id=owner, file_count=counts.get(user.id, 0))
        for user in people
    ]


@router.get("/{user_id}", response_model=UserAdminView)
async def get_person(user_id: UUID, db: DbSession, actor: CurrentActor) -> UserAdminView:
    return await _view(db, actor, await service.get_user(db, actor, user_id))


@router.patch("/{user_id}", response_model=UserAdminView)
async def update_person(
    user_id: UUID, payload: UserDetailsUpdate, db: DbSession, actor: CurrentActor
) -> UserAdminView:
    """Change any of the sent fields. A request that changes nothing writes nothing."""
    user = await service.update_user_details(
        db, actor, user_id, payload.model_dump(exclude_unset=True)
    )
    view = await _view(db, actor, user)
    await db.commit()
    return view


@router.put("/{user_id}/roles", response_model=UserAdminView)
async def set_roles(
    user_id: UUID, payload: UserRolesUpdate, db: DbSession, actor: CurrentActor
) -> UserAdminView:
    """Replace the person's roles with the sent set."""
    user = await service.set_user_roles(db, actor, user_id, set(payload.roles))
    view = await _view(db, actor, user)
    await db.commit()
    return view


@router.post("/{user_id}/deactivate", response_model=UserAdminView)
async def deactivate(user_id: UUID, db: DbSession, actor: CurrentActor) -> UserAdminView:
    """End the person's access from their next request."""
    view = await _view(db, actor, await service.deactivate_user(db, actor, user_id))
    await db.commit()
    return view


@router.post("/{user_id}/reactivate", response_model=UserAdminView)
async def reactivate(user_id: UUID, db: DbSession, actor: CurrentActor) -> UserAdminView:
    view = await _view(db, actor, await service.reactivate_user(db, actor, user_id))
    await db.commit()
    return view


@router.post("/{user_id}/reassign-loans", response_model=Reassigned)
async def reassign_loans(
    user_id: UUID, payload: ReassignBody, db: DbSession, actor: CurrentActor
) -> Reassigned:
    """Move every file this person works to another person, slot for slot (LP-MB-Admin-05)."""
    moved = await reassign_user_loans(db, actor, user_id, payload.to_user_id)
    if moved is None:
        raise _NOT_FOUND
    await db.commit()
    return Reassigned(moved=moved)
