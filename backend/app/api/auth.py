"""Authentication endpoints: login, refresh, logout (LP-23).

Thin orchestration over the LP-22 token/password utilities and the LP-23 auth
service. The substance here is the **hybrid token transport**:

  * the short-lived **access** token is returned in the JSON body — the client
    holds it in memory and sends it as ``Authorization: Bearer`` (LP-25);
  * the long-lived **refresh** token is set as an **httpOnly** cookie scoped to
    the refresh path — JavaScript can't read it (XSS resistance) and the browser
    only sends it back on refresh requests.

See :mod:`app.core.jwt` for the token primitives and ``docs/authentication.md``
for the full transport rationale and the V1 gaps (no rate limiting, SameSite-only
CSRF posture, stateless / no server-side revocation).
"""

from fastapi import APIRouter, Cookie, HTTPException, Response, status

from app.api.dependencies import CurrentUser
from app.core.config import settings
from app.core.database import DbSession
from app.core.jwt import (
    InvalidTokenError,
    TokenExpiredError,
    TokenType,
    WrongTokenTypeError,
    create_access_token,
    create_refresh_token,
    verify_token,
)
from app.schemas.auth import LoginRequest, TokenResponse, UserPublic
from app.services.auth import (
    AuthenticationError,
    InactiveUserError,
    authenticate_user,
    get_user_by_id,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# The refresh cookie. Its path is scoped to the refresh endpoint so the browser
# attaches it only to refresh requests, never to ordinary API calls. This MUST
# match the mounted path of the refresh route (router prefix "/auth" under the
# "/api/v1" app prefix) — kept in sync by the route definitions below.
REFRESH_TOKEN_COOKIE = "refresh_token"  # pragma: allowlist secret (cookie name)
REFRESH_COOKIE_PATH = "/api/v1/auth/refresh"

# A generic, identical message for every credential failure — never reveal
# whether the email exists (anti-enumeration).
_INVALID_CREDENTIALS = "Invalid email or password"
_INVALID_REFRESH = "Invalid refresh token"


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Set the refresh token as an httpOnly cookie with the V1 flag policy.

    ``secure`` follows the environment: ``True`` in production (cookie only sent
    over HTTPS), ``False`` in local dev (so it works over plain-HTTP localhost).
    ``samesite="lax"`` is the V1 CSRF posture; ``path`` scopes the cookie to the
    refresh endpoint; ``max_age`` matches the refresh-token lifetime.
    """
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
        max_age=settings.jwt_refresh_token_expire_days * 24 * 60 * 60,
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Expire the refresh cookie, matching the path/flags it was set with.

    The path (and flags) must match :func:`_set_refresh_cookie` or the browser
    treats it as a different cookie and the original is not removed.
    """
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: DbSession, response: Response) -> TokenResponse:
    """Authenticate credentials; return an access token + set the refresh cookie.

    On any credential failure returns a generic ``401`` (identical for unknown
    email and wrong password). An inactive account returns ``403``.
    """
    try:
        user = await authenticate_user(db, email=payload.email, password=payload.password)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS
        ) from exc
    except InactiveUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive"
        ) from exc

    _set_refresh_cookie(response, create_refresh_token(user.id))
    return TokenResponse(
        access_token=create_access_token(user.id),
        user=UserPublic.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    db: DbSession,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_TOKEN_COOKIE),
) -> TokenResponse:
    """Exchange a valid refresh cookie for a new access token (and a rotated cookie).

    Rotation-lite: every successful refresh issues a *new* refresh token (a
    sliding window). There is no server-side reuse-detection in V1. Any problem
    — missing cookie, expired/invalid/wrong-type token, or a user that no longer
    exists or is inactive — returns a generic ``401``.
    """
    if refresh_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_REFRESH)

    try:
        token_payload = verify_token(refresh_token, TokenType.REFRESH)
    except (TokenExpiredError, InvalidTokenError, WrongTokenTypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_REFRESH
        ) from exc

    user = await get_user_by_id(db, token_payload.subject)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_REFRESH)

    _set_refresh_cookie(response, create_refresh_token(user.id))
    return TokenResponse(
        access_token=create_access_token(user.id),
        user=UserPublic.model_validate(user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> Response:
    """Clear the refresh cookie. Returns ``204``.

    Stateless: the access token is not server-invalidated (it simply expires).
    Clearing the cookie stops future refreshes from this client.
    """
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserPublic)
async def read_current_user(current_user: CurrentUser) -> UserPublic:
    """Return the authenticated user (the first protected endpoint).

    Proves the whole auth chain end to end: Bearer access token → live-user
    lookup → active check (all in :func:`app.api.dependencies.get_current_user`).
    Returns ``UserPublic`` — never ``hashed_password``.
    """
    return UserPublic.model_validate(current_user)
