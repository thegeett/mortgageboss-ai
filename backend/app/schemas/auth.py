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

from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.models.user import UserRole


class LoginRequest(BaseModel):
    """Credentials submitted to ``POST /auth/login``."""

    email: EmailStr
    password: str


class UserPublic(BaseModel):
    """The safe, public view of a user returned in auth responses.

    Built from a ``User`` ORM instance via ``model_validate`` (``from_attributes``).
    Carries identity and display fields only — never ``hashed_password``,
    ``is_active``, timestamps, or other internal state.
    """

    id: UUID
    email: EmailStr
    first_name: str
    last_name: str
    role: UserRole
    company_id: UUID

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """The body returned by ``POST /auth/login`` and ``POST /auth/refresh``.

    Contains the short-lived **access** token (held in client memory and sent
    as ``Authorization: Bearer``) plus the public user info. The **refresh**
    token is never here — it is set as an httpOnly cookie.
    """

    access_token: str
    token_type: str = "bearer"
    user: UserPublic
