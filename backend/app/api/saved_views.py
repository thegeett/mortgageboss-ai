"""Saved-view endpoints (LP-UI-015).

CRUD over a company's saved pipeline views. Two rules run through all of it:

**The company is never taken from the request.** Every query is scoped to
`current_user.company_id`, so a view id from another tenant is a 404 rather than
a 403 — the same discipline as the loan-file endpoints, and for the same reason:
a 403 confirms the row exists.

**Visibility is not ownership.** A shared view is readable by the whole company
and writable only by its owner. A processor can use a colleague's "Blocked to
submit" without being able to change it underneath them.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import or_, select

from app.api.dependencies import CurrentUser
from app.core.database import DbSession
from app.models.base import utcnow
from app.models.saved_view import SavedView
from app.models.user import User
from app.schemas.saved_view import (
    SavedViewCreate,
    SavedViewFilters,
    SavedViewPublic,
    SavedViewUpdate,
)

router = APIRouter(prefix="/saved-views", tags=["saved-views"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved view not found.")


def _to_public(view: SavedView, viewer: User) -> SavedViewPublic:
    """Serialise, resolving `is_mine` against the caller."""
    return SavedViewPublic(
        id=view.id,
        name=view.name,
        filters=SavedViewFilters.model_validate(view.filters),
        sort=view.sort,
        is_shared=view.is_shared,
        owner_user_id=view.owner_user_id,
        is_mine=view.owner_user_id == viewer.id,
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


async def _get_scoped(db: DbSession, view_id: UUID, user: User) -> SavedView:
    """One view the caller may READ, or 404.

    Soft-deleted rows are excluded here rather than by a global filter, so a
    deleted view can never reappear through any path that goes through this.
    """
    stmt = select(SavedView).where(
        SavedView.id == view_id,
        SavedView.company_id == user.company_id,
        SavedView.deleted_at.is_(None),
        or_(SavedView.owner_user_id == user.id, SavedView.is_shared.is_(True)),
    )
    view = (await db.execute(stmt)).scalar_one_or_none()
    if view is None:
        raise _NOT_FOUND
    return view


@router.get("", response_model=list[SavedViewPublic])
async def list_saved_views(db: DbSession, current_user: CurrentUser) -> list[SavedViewPublic]:
    """The caller's own views plus their company's shared ones, oldest first."""
    stmt = (
        select(SavedView)
        .where(
            SavedView.company_id == current_user.company_id,
            SavedView.deleted_at.is_(None),
            or_(
                SavedView.owner_user_id == current_user.id,
                SavedView.is_shared.is_(True),
            ),
        )
        .order_by(SavedView.created_at)
    )
    views = (await db.execute(stmt)).scalars().all()
    return [_to_public(view, current_user) for view in views]


@router.post("", response_model=SavedViewPublic, status_code=status.HTTP_201_CREATED)
async def create_saved_view(
    payload: SavedViewCreate, db: DbSession, current_user: CurrentUser
) -> SavedViewPublic:
    """Create a view owned by the caller, in the caller's company."""
    view = SavedView(
        company_id=current_user.company_id,
        owner_user_id=current_user.id,
        name=payload.name,
        filters=payload.filters.model_dump(mode="json"),
        sort=payload.sort,
        is_shared=payload.is_shared,
    )
    db.add(view)
    await db.commit()
    await db.refresh(view)
    return _to_public(view, current_user)


@router.patch("/{view_id}", response_model=SavedViewPublic)
async def update_saved_view(
    view_id: UUID, payload: SavedViewUpdate, db: DbSession, current_user: CurrentUser
) -> SavedViewPublic:
    """Update a view the caller OWNS. Only the provided fields change."""
    view = await _get_scoped(db, view_id, current_user)
    if view.owner_user_id != current_user.id:
        # Readable but not writable. 404 rather than 403 for the same reason as
        # everywhere else: a 403 would confirm someone else's view exists.
        raise _NOT_FOUND

    if payload.name is not None:
        view.name = payload.name
    if payload.filters is not None:
        view.filters = payload.filters.model_dump(mode="json")
    if payload.sort is not None:
        view.sort = payload.sort
    if payload.is_shared is not None:
        view.is_shared = payload.is_shared

    await db.commit()
    await db.refresh(view)
    return _to_public(view, current_user)


@router.delete("/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_view(view_id: UUID, db: DbSession, current_user: CurrentUser) -> None:
    """Soft-delete a view the caller owns. It never comes back through any read."""
    view = await _get_scoped(db, view_id, current_user)
    if view.owner_user_id != current_user.id:
        raise _NOT_FOUND
    view.deleted_at = utcnow()
    await db.commit()
