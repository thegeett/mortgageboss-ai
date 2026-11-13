"""Authentication and authorization dependencies for protected routes (LP-24).

Auth is enforced as **per-route FastAPI dependencies**, not global middleware:
a route is protected by *declaring* :data:`CurrentUser` (or a ``require_permission``
dependency); public routes (login, refresh, logout, health) simply don't. See
ADR for why dependencies beat global-middleware-with-exemptions.

The security core is :func:`get_current_user`. The access token carries only
identity (``sub`` = user UUID); role, company, and active-status are read from
the **live** database record on every request, never from the token. So
deactivating a user or changing a role takes effect on their next request — this
is the V1 cutoff mechanism in place of a stateless-JWT revocation store.

Authorization is by permission key (ADR-442): :data:`CurrentActor` carries the
permissions resolved once per request, and :func:`require_permission` gates a route.
Roles are compared only in :mod:`app.core.permissions`.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.database import DbSession
from app.core.file_scope import FileScope
from app.core.jwt import (
    InvalidTokenError,
    TokenExpiredError,
    TokenType,
    WrongTokenTypeError,
    verify_token,
)
from app.core.permissions import Permission, resolve_permissions
from app.models.loan_file import LoanFile
from app.models.user import User, UserRole
from app.services.auth import get_user_by_id
from app.services.loan_files import get_loan_file

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


@dataclass(frozen=True)
class Actor:
    """Who is acting, in which company, with what permissions (LP-MB-Admin-02).

    Built once per request by :func:`get_current_actor`. ``company_id`` is the EFFECTIVE company
    (ADR-443): today always the user's own, decided in that one function. New services take an
    ``Actor`` and check it with :func:`app.services.authorization.ensure`.

    ``scope`` is which loan files the actor may see (LP-MB-Admin-06, ADR-446), decided when the
    actor is built, at the start of the request: a later change in the same request (a user's
    ``_locked`` re-read unloads ``user.company``) cannot move it.
    """

    user: User
    company_id: UUID
    roles: frozenset[UserRole]
    permissions: frozenset[Permission]
    is_owner: bool
    scope: FileScope = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope", FileScope.for_actor(self))


def get_current_actor(current_user: CurrentUser) -> Actor:
    """The request's :class:`Actor`, from the user and company already loaded: no query."""
    return Actor(
        user=current_user,
        company_id=current_user.company_id,
        roles=current_user.role_set,
        permissions=resolve_permissions(current_user.role_set, current_user.company.settings_model),
        is_owner=current_user.is_owner,
    )


CurrentActor = Annotated[Actor, Depends(get_current_actor)]


def require_permission(permission: Permission) -> Callable[[Actor], Awaitable[Actor]]:
    """Dependency factory: require the actor to hold ``permission`` (ADR-442).

    Depends on :func:`get_current_actor`, so authentication precedes authorization:
    no identity is ``401``, a missing permission is ``403``.

    Usage::

        @router.get("/x", dependencies=[Depends(require_permission(Permission.LENDERS_MANAGE))])
    """

    async def _require_permission(actor: CurrentActor) -> Actor:
        if permission not in actor.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return actor

    return _require_permission


def require_role(*allowed_roles: UserRole) -> Callable[[User], Awaitable[User]]:
    """Dependency factory: require the current user to hold any of ``allowed_roles``.

    SUPERSEDED by :func:`require_permission` (ADR-442) and kept for ONE caller,
    ``api/validation_aid.py``, whose page is out of the admin work's scope. Delete it
    with that page. Do not add a caller.

    The returned dependency depends on :func:`get_current_user`, so
    authentication always precedes authorization. A wrong role raises ``403``
    (authenticated but not permitted) — distinct from the ``401`` an
    unauthenticated request gets.

    Usage::

        @router.get("/admin", dependencies=[Depends(require_role(UserRole.ADMIN))])
    """

    async def _require_role(current_user: CurrentUser) -> User:
        if current_user.role_set.isdisjoint(allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return _require_role


def get_current_company_id(actor: CurrentActor) -> UUID:
    """The request's tenant scope: the actor's effective company (ADR-443).

    The ONLY place that decides it; new code uses :data:`CurrentCompanyId` or
    ``actor.company_id``, never ``current_user.company_id``. Today it is always the
    user's own company. This is the non-forgeable company scope every business endpoint passes to
    :func:`app.models.helpers.scope_to_company`. Because it derives from the
    validated token and the live user record, a caller cannot present another
    company's id — which is what activates the Epic 2 multi-tenancy at runtime.
    """
    return actor.company_id


CurrentCompanyId = Annotated[UUID, Depends(get_current_company_id)]


def get_current_scope(actor: CurrentActor) -> FileScope:
    """The loan files the request may see (ADR-446): every loan-file gate takes this, not a company
    id."""
    return actor.scope


CurrentScope = Annotated[FileScope, Depends(get_current_scope)]


async def get_scoped_loan_file(
    file_identifier: str, db: DbSession, scope: CurrentScope
) -> LoanFile:
    """Resolve the loan file in the path, scoped to what the caller may see (ADR-446).

    This is the **tenant gate** for nested resources (borrowers, property,
    later documents): a child route declares it, so the parent file is fetched
    via ``get_loan_file(scope=...)`` *first*. If the file isn't the caller's
    company's, or is on a team the caller is restricted away from, or doesn't
    exist, it raises ``404`` and the child is never reached. ``file_identifier``
    may be the UUID or the display id.
    """
    loan_file = await get_loan_file(db, scope=scope, identifier=file_identifier)
    if loan_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan file not found")
    return loan_file


ScopedLoanFile = Annotated[LoanFile, Depends(get_scoped_loan_file)]
