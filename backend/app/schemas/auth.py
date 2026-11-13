"""Authentication request/response schemas (LP-23).

Establishes the request/response model pattern for Epic 3+ endpoints. These
schemas are the public contract of the auth endpoints: what a client sends and
what it gets back. They deliberately expose only safe, public user fields —
never ``hashed_password`` or any other secret.

The refresh token is NOT modelled here: it travels only in an httpOnly cookie
(see :mod:`app.api.auth`), never in a request or response body. Login takes
credentials in the body; refresh takes its token from the cookie; so there is
no ``RefreshRequest``.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, model_validator

from app.core.file_scope import FileScope
from app.core.permissions import resolve_permissions
from app.models.user import User, UserRole


class LoginRequest(BaseModel):
    """Credentials submitted to ``POST /auth/login``."""

    email: EmailStr
    password: str


class UserPublic(BaseModel):
    """The safe, public view of a user returned in auth responses.

    Built from a ``User`` ORM instance via ``model_validate``. Carries identity and
    display fields only — never ``hashed_password``, ``is_active``, timestamps, or
    other internal state.

    ``roles`` is the set the user holds (ADR-440), for display. ``permissions`` is what
    the frontend gates on (ADR-442), resolved by the same function the API checks with,
    so the UI and the boundary cannot disagree. The single derived ``role`` is gone
    (LP-MB-Admin-02). ``restricted`` is whether the user sees only the files they are on
    (LP-MB-Admin-06): the same decision the API's ``FileScope`` makes, so the Team card can warn a
    loan officer who is about to hand their own file away. The user's company must be loaded (``get_user_by_id`` and
    ``authenticate_user`` load it).
    """

    id: UUID
    email: EmailStr
    first_name: str
    last_name: str
    roles: list[UserRole]
    permissions: list[str]
    is_owner: bool
    restricted: bool
    company_id: UUID

    @model_validator(mode="before")
    @classmethod
    def _from_user(cls, data: Any) -> Any:
        """A ``User`` → its fields, with ``roles`` and ``permissions`` sorted (a set has no order)."""
        if not isinstance(data, User):
            return data
        return {
            "id": data.id,
            "email": data.email,
            "first_name": data.first_name,
            "last_name": data.last_name,
            "roles": sorted(data.role_set),
            "permissions": sorted(resolve_permissions(data.role_set, data.company.settings_model)),
            "is_owner": data.is_owner,
            "restricted": FileScope.for_user(data).restricted,
            "company_id": data.company_id,
        }


class TokenResponse(BaseModel):
    """The body returned by ``POST /auth/login`` and ``POST /auth/refresh``.

    Contains the short-lived **access** token (held in client memory and sent
    as ``Authorization: Bearer``) plus the public user info. The **refresh**
    token is never here — it is set as an httpOnly cookie.
    """

    access_token: str
    token_type: str = "bearer"
    user: UserPublic
