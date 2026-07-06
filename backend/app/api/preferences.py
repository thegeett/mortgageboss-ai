"""User preference endpoints (LP-79) — the user-level verification default.

``GET /users/me/preferences`` returns the caller's preferences; ``PUT`` updates
them. Today this carries the **default aggression level** — the verification
thoroughness applied to a file unless a per-file override dials it up/down (the
per-file override lives on the verification endpoint). The user is always the
authenticated caller, so there is no cross-tenant surface here.
"""

from fastapi import APIRouter

from app.api.dependencies import CurrentUser
from app.core.database import DbSession
from app.schemas.preferences import UserPreferences, UserPreferencesUpdate

router = APIRouter(prefix="/users/me", tags=["preferences"])


@router.get("/preferences", response_model=UserPreferences)
async def get_preferences(current_user: CurrentUser) -> UserPreferences:
    """The caller's preferences (the default verification thoroughness)."""
    return UserPreferences.model_validate(current_user)


@router.put("/preferences", response_model=UserPreferences)
async def update_preferences(
    payload: UserPreferencesUpdate, db: DbSession, current_user: CurrentUser
) -> UserPreferences:
    """Update the caller's default aggression level (their verification thoroughness).

    The default applies to every file the user opens unless that file has a per-file
    override. Changing it never re-runs any AI — it only changes the cutoff the
    read-time filter applies.
    """
    current_user.default_aggression_level = payload.default_aggression_level
    await db.commit()
    await db.refresh(current_user)
    return UserPreferences.model_validate(current_user)
