"""Authentication and authorization dependencies for protected routes (LP-24).

Auth is enforced as **per-route FastAPI dependencies**, not global middleware:
a route is protected by *declaring* :data:`CurrentUser` (or a ``require_role``
dependency); public routes (login, refresh, logout, health) simply don't. See
ADR for why dependencies beat global-middleware-with-exemptions.

The security core is :func:`get_current_user`. The access token carries only
identity (``sub`` = user UUID); role, company, and active-status are read from
the **live** database record on every request, never from the token. So
deactivating a user or changing a role takes effect on their next request — this
is the V1 cutoff mechanism in place of a stateless-JWT revocation store.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.database import DbSession
from app.core.jwt import (
    InvalidTokenError,
    TokenExpiredError,
    TokenType,
    WrongTokenTypeError,
    verify_token,
)
from app.models.user import User, UserRole
from app.services.auth import get_user_by_id

# auto_error=False: HTTPBearer won't raise its own 403 on a missing header, so
# we return a consistent 401 (with WWW-Authenticate: Bearer) ourselves.
bearer_scheme = HTTPBearer(auto_error=False)

BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(db: DbSession, credentials: BearerCredentials) -> User:
    """Resolve and return the live, active authenticated user.

    Extracts the Bearer access token, verifies it (signature/expiry/type), then
    looks the user up in the database and confirms they still exist and are
    active. Raises ``401`` if the token is missing/invalid/expired/wrong-type or
    the user is gone/inactive — every failure looks the same to the client.
    """
    if credentials is None or not credentials.credentials:
        raise _UNAUTHENTICATED

    try:
        payload = verify_token(credentials.credentials, TokenType.ACCESS)
    except (TokenExpiredError, InvalidTokenError, WrongTokenTypeError) as exc:
        raise _UNAUTHENTICATED from exc

    user = await get_user_by_id(db, payload.subject)
    if user is None or not user.is_active:
        raise _UNAUTHENTICATED

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_user_optional(db: DbSession, credentials: BearerCredentials) -> User | None:
    """Like :func:`get_current_user` but returns ``None`` instead of raising
    when authentication is absent or invalid.

    For routes whose behaviour varies by auth state rather than requiring it. An
    *invalid* token is treated the same as *no* token (``None``) — it never
    raises — so the same security checks (live lookup, active) still apply before
    a user is returned.
    """
    if credentials is None or not credentials.credentials:
        return None
    try:
        payload = verify_token(credentials.credentials, TokenType.ACCESS)
    except (TokenExpiredError, InvalidTokenError, WrongTokenTypeError):
        return None
    user = await get_user_by_id(db, payload.subject)
    if user is None or not user.is_active:
        return None
    return user


OptionalCurrentUser = Annotated[User | None, Depends(get_current_user_optional)]


def require_role(*allowed_roles: UserRole) -> Callable[[User], Awaitable[User]]:
    """Dependency factory: require the current user to hold one of ``allowed_roles``.

    The returned dependency depends on :func:`get_current_user`, so
    authentication always precedes authorization. A wrong role raises ``403``
    (authenticated but not permitted) — distinct from the ``401`` an
    unauthenticated request gets.

    Usage::

        @router.get("/admin", dependencies=[Depends(require_role(UserRole.ADMIN))])
    """

    async def _require_role(current_user: CurrentUser) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return _require_role


def get_current_company_id(current_user: CurrentUser) -> UUID:
    """The request's tenant scope: the authenticated user's ``company_id``.

    This is the non-forgeable company scope every business endpoint passes to
    :func:`app.models.helpers.scope_to_company`. Because it derives from the
    validated token and the live user record, a caller cannot present another
    company's id — which is what activates the Epic 2 multi-tenancy at runtime.
    """
    return current_user.company_id


CurrentCompanyId = Annotated[UUID, Depends(get_current_company_id)]
