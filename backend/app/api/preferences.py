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
from app.models.user import User
from app.schemas.preferences import UserPreferences, UserPreferencesUpdate
from app.services.mail_clients import suggest_mail_client

router = APIRouter(prefix="/users/me", tags=["preferences"])


def _with_suggestion(user: User) -> UserPreferences:
    """The caller's preferences, plus LP-855's guess at their mail client.

    SERVED ALONGSIDE THE STORED VALUE, never instead of it. The picker shows the suggestion as a
    pre-selected radio and a sentence; the settings screen shows the same sentence to somebody
    changing their mind. Nothing here writes it.
    """
    client, reason = suggest_mail_client(user.email)
    preferences = UserPreferences.model_validate(user)
    return preferences.model_copy(
        update={"suggested_mail_client": client, "mail_client_suggestion_reason": reason}
    )


@router.get("/preferences", response_model=UserPreferences)
async def get_preferences(current_user: CurrentUser) -> UserPreferences:
    """The caller's preferences (the default verification thoroughness)."""
    return _with_suggestion(current_user)


@router.put("/preferences", response_model=UserPreferences)
async def update_preferences(
    payload: UserPreferencesUpdate, db: DbSession, current_user: CurrentUser
) -> UserPreferences:
    """Update the caller's preferences — thoroughness, row density, or the reviewer split.

    The default applies to every file the user opens unless that file has a per-file
    override. Changing it never re-runs any AI — it only changes the cutoff the
    read-time filter applies.
    """
    # Only what was sent. A partial update must not reset the field it omits.
    if payload.default_aggression_level is not None:
        current_user.default_aggression_level = payload.default_aggression_level
    if payload.density is not None:
        current_user.density = payload.density
    if payload.reviewer_pane_split is not None:
        current_user.reviewer_pane_split = payload.reviewer_pane_split
    # LP-855 — the answer to the mail-client picker. There is no way to go BACK to unanswered, and
    # that is deliberate: "nobody has asked" is a state the product creates, not one a processor
    # chooses, and a client that could clear it could make the picker reappear forever.
    if payload.mail_client is not None:
        current_user.mail_client = payload.mail_client
    await db.commit()
    await db.refresh(current_user)
    return _with_suggestion(current_user)
