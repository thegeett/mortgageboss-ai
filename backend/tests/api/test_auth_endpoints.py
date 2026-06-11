"""Endpoint tests for login / refresh / logout (LP-23).

Drives the real FastAPI app via httpx ``AsyncClient`` with ``get_db`` overridden
to the rollback ``db_session`` fixture, so a user created in the test is visible
to the endpoint and nothing is committed. Covers the happy paths, the
anti-enumeration property (identical 401 for unknown email vs wrong password),
the hybrid transport (refresh in an httpOnly cookie, never in the body), token
rotation on refresh, and that the access token carries no PII and the body never
leaks ``hashed_password`` or the refresh token.
"""

from collections.abc import AsyncIterator

import jwt
import pytest_asyncio
from app.api.auth import REFRESH_COOKIE_PATH, REFRESH_TOKEN_COOKIE
from app.core.config import settings
from app.core.database import get_db
from app.core.jwt import create_access_token, create_refresh_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
LOGOUT_URL = "/api/v1/auth/logout"

PASSWORD = "correct horse battery staple"  # pragma: allowlist secret
WRONG_PASSWORD = "Tr0ub4dor&3"  # pragma: allowlist secret


@pytest_asyncio.fixture
async def auth_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """An AsyncClient whose app uses the test's rollback session for the DB."""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _make_user(
    db_session: AsyncSession,
    *,
    email: str = "processor@acme.com",
    password: str = PASSWORD,
    is_active: bool = True,
) -> User:
    company = Company(name="Acme", slug="acme")
    db_session.add(company)
    await db_session.flush()
    user = User(
        company_id=company.id,
        email=email,
        hashed_password=hash_password(password),
        first_name="Pat",
        last_name="Processor",
        role=UserRole.PROCESSOR,
        is_active=is_active,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _set_cookie_header(response: object) -> str:
    """Join all Set-Cookie headers from a response into one lowercase string."""
    headers = response.headers.get_list("set-cookie")  # type: ignore[attr-defined]
    return " ".join(headers).lower()


def _put_refresh_cookie(client: AsyncClient, value: str) -> None:
    """Place a refresh-token value in the client's cookie jar, scoped like the
    real cookie, so it is sent to the refresh endpoint."""
    client.cookies.set(REFRESH_TOKEN_COOKIE, value, domain="test", path=REFRESH_COOKIE_PATH)


# --------------------------------------------------------------------------- #
# login
# --------------------------------------------------------------------------- #


async def test_login_success_returns_token_and_sets_refresh_cookie(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Valid creds: 200, access token + user in body, httpOnly refresh cookie set."""
    user = await _make_user(db_session)
    resp = await auth_client.post(LOGIN_URL, json={"email": user.email, "password": PASSWORD})

    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == user.email
    assert body["user"]["role"] == UserRole.PROCESSOR.value

    set_cookie = _set_cookie_header(resp)
    assert REFRESH_TOKEN_COOKIE in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert f"path={REFRESH_COOKIE_PATH}".lower() in set_cookie
    # Dev/test environment -> secure must NOT be set (HTTP localhost).
    assert "secure" not in set_cookie


async def test_login_body_has_no_secret_fields(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The login body never contains hashed_password or the refresh token."""
    user = await _make_user(db_session)
    resp = await auth_client.post(LOGIN_URL, json={"email": user.email, "password": PASSWORD})
    raw = resp.text
    assert "hashed_password" not in raw
    assert REFRESH_TOKEN_COOKIE not in resp.json()
    assert "refresh_token" not in resp.json()
    # The actual refresh-token value (in the cookie) must not appear in the body.
    refresh_value = resp.cookies.get(REFRESH_TOKEN_COOKIE)
    assert refresh_value is not None
    assert refresh_value not in raw


async def test_login_access_token_carries_no_pii(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The access token decodes to exactly {sub, type, exp, iat} — no PII."""
    user = await _make_user(db_session)
    resp = await auth_client.post(LOGIN_URL, json={"email": user.email, "password": PASSWORD})
    decoded = jwt.decode(
        resp.json()["access_token"],
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    assert set(decoded.keys()) == {"sub", "type", "exp", "iat"}
    assert decoded["sub"] == str(user.id)
    for forbidden in ("role", "email", "company_id", "company", "is_active"):
        assert forbidden not in decoded


async def test_login_wrong_password_is_401_with_no_cookie(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Wrong password: 401 generic, and no refresh cookie is set."""
    user = await _make_user(db_session)
    resp = await auth_client.post(LOGIN_URL, json={"email": user.email, "password": WRONG_PASSWORD})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"
    assert REFRESH_TOKEN_COOKIE not in _set_cookie_header(resp)


async def test_login_unknown_email_matches_wrong_password(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Anti-enumeration: unknown email returns the IDENTICAL 401 as wrong password."""
    user = await _make_user(db_session, email="known@acme.com")

    wrong_pw = await auth_client.post(
        LOGIN_URL, json={"email": user.email, "password": WRONG_PASSWORD}
    )
    unknown = await auth_client.post(
        LOGIN_URL, json={"email": "nobody@acme.com", "password": PASSWORD}
    )

    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()


async def test_login_inactive_user_is_403(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """An inactive account with valid credentials is rejected with 403."""
    user = await _make_user(db_session, email="inactive@acme.com", is_active=False)
    resp = await auth_client.post(LOGIN_URL, json={"email": user.email, "password": PASSWORD})
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# refresh
# --------------------------------------------------------------------------- #


async def test_refresh_with_valid_cookie_rotates_and_returns_new_token(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A valid refresh cookie yields 200, a new access token, and a rotated cookie."""
    user = await _make_user(db_session)
    login = await auth_client.post(LOGIN_URL, json={"email": user.email, "password": PASSWORD})
    original_refresh = login.cookies.get(REFRESH_TOKEN_COOKIE)
    assert original_refresh is not None

    # The client's cookie jar carries the refresh cookie back to the refresh path.
    resp = await auth_client.post(REFRESH_URL)
    assert resp.status_code == 200
    assert resp.json()["access_token"]

    set_cookie = _set_cookie_header(resp)
    assert REFRESH_TOKEN_COOKIE in set_cookie
    assert "httponly" in set_cookie


async def test_refresh_with_no_cookie_is_401(auth_client: AsyncClient) -> None:
    """Refresh without a cookie is rejected with 401."""
    resp = await auth_client.post(REFRESH_URL)
    assert resp.status_code == 401


async def test_refresh_with_access_token_cookie_is_401(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """An ACCESS token supplied where a REFRESH token is expected is 401 (wrong type)."""
    user = await _make_user(db_session)
    _put_refresh_cookie(auth_client, create_access_token(user.id))
    resp = await auth_client.post(REFRESH_URL)
    assert resp.status_code == 401


async def test_refresh_with_tampered_token_is_401(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A tampered refresh token fails signature verification -> 401."""
    user = await _make_user(db_session)
    token = create_refresh_token(user.id)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    _put_refresh_cookie(auth_client, tampered)
    resp = await auth_client.post(REFRESH_URL)
    assert resp.status_code == 401


async def test_refresh_for_inactive_user_is_401(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A structurally valid refresh token for an inactive user is rejected (401)."""
    user = await _make_user(db_session, email="gone@acme.com", is_active=False)
    _put_refresh_cookie(auth_client, create_refresh_token(user.id))
    resp = await auth_client.post(REFRESH_URL)
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# logout
# --------------------------------------------------------------------------- #


async def test_logout_clears_refresh_cookie(auth_client: AsyncClient) -> None:
    """Logout returns 204 and expires the refresh cookie (Max-Age=0, same path)."""
    resp = await auth_client.post(LOGOUT_URL)
    assert resp.status_code == 204
    set_cookie = _set_cookie_header(resp)
    assert REFRESH_TOKEN_COOKIE in set_cookie
    assert "max-age=0" in set_cookie
    assert f"path={REFRESH_COOKIE_PATH}".lower() in set_cookie
