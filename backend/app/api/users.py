"""People: the company's users, their details, roles and access (LP-MB-Admin-03).

Every route needs ``users.manage``. A user of another company is a 404, never a 403, so an id from
another tenant reveals nothing. The rules live in ``services/users``; a refusal arrives as a 409 or 422
with the sentence the People sheet shows.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import CurrentActor, require_permission
from app.core.database import DbSession
from app.core.permissions import Permission
from app.models.user import User, UserRole
from app.schemas.users import UserAdminView, UserDetailsUpdate, UserRolesUpdate
from app.services import users as service

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_permission(Permission.USERS_MANAGE))],
)

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")


def _view(user: User | None, actor: CurrentActor) -> UserAdminView:
    if user is None:
        raise _NOT_FOUND
    return UserAdminView.of(user, owner_user_id=actor.user.company.owner_user_id)


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
    return [_view(user, actor) for user in people]


@router.get("/{user_id}", response_model=UserAdminView)
async def get_person(user_id: UUID, db: DbSession, actor: CurrentActor) -> UserAdminView:
    return _view(await service.get_user(db, actor, user_id), actor)


@router.patch("/{user_id}", response_model=UserAdminView)
async def update_person(
    user_id: UUID, payload: UserDetailsUpdate, db: DbSession, actor: CurrentActor
) -> UserAdminView:
    """Change any of the sent fields. A request that changes nothing writes nothing."""
    user = await service.update_user_details(
        db, actor, user_id, payload.model_dump(exclude_unset=True)
    )
    view = _view(user, actor)
    await db.commit()
    return view


@router.put("/{user_id}/roles", response_model=UserAdminView)
async def set_roles(
    user_id: UUID, payload: UserRolesUpdate, db: DbSession, actor: CurrentActor
) -> UserAdminView:
    """Replace the person's roles with the sent set."""
    user = await service.set_user_roles(db, actor, user_id, set(payload.roles))
    view = _view(user, actor)
    await db.commit()
    return view


@router.post("/{user_id}/deactivate", response_model=UserAdminView)
async def deactivate(user_id: UUID, db: DbSession, actor: CurrentActor) -> UserAdminView:
    """End the person's access from their next request."""
    view = _view(await service.deactivate_user(db, actor, user_id), actor)
    await db.commit()
    return view


@router.post("/{user_id}/reactivate", response_model=UserAdminView)
async def reactivate(user_id: UUID, db: DbSession, actor: CurrentActor) -> UserAdminView:
    view = _view(await service.reactivate_user(db, actor, user_id), actor)
    await db.commit()
    return view
