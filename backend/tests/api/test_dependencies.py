"""Tests for the auth dependencies and route protection (LP-24).

Exercises :mod:`app.api.dependencies` and ``GET /auth/me`` end to end. A small
test-only FastAPI app mounts the real auth router *plus* a few throwaway
protected routes (``require_role`` / tenant-context) defined here — not in app
code — so authorization and the tenant accessor can be driven over HTTP. ``get_db``
is overridden to the rollback ``db_session`` so users created in a test are
visible to the dependency and nothing commits.

The critical case is the **live-lookup deactivation cutoff**: a still-valid token
whose user has since been set ``is_active=False`` must be rejected (401).
"""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import uuid4

import pytest
import pytest_asyncio
from app.api.auth import router as auth_router
from app.api.dependencies import (
    CurrentCompanyId,
    require_role,
)
from app.core.database import get_db
from app.core.jwt import create_access_token, create_refresh_token
from app.core.security import hash_password
from app.models import Company, User, UserRole
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from tests.user_factory import make_user

ME_URL = "/api/v1/auth/me"
ADMIN_URL = "/admin-only"
STAFF_URL = "/staff"
COMPANY_URL = "/whoami-company"

PASSWORD = "correct horse battery staple"  # pragma: allowlist secret


def _build_test_app() -> FastAPI:
    """A FastAPI app with the real auth router and throwaway protected routes.

    The extra routes live here (test-only), never in ``app/`` — they exist purely
    to drive ``require_role`` and the tenant-context dependency over HTTP.
    """
    test_app = FastAPI()
    test_app.include_router(auth_router, prefix="/api/v1")

    @test_app.get(ADMIN_URL)
    async def _admin_only(
        user: Annotated[User, Depends(require_role(UserRole.ADMIN))],
    ) -> dict[str, str]:
        return {"id": str(user.id)}

    @test_app.get(STAFF_URL)
    async def _staff(
        user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.PROCESSOR))],
    ) -> dict[str, str]:
        return {"id": str(user.id)}

    @test_app.get(COMPANY_URL)
    async def _whoami_company(company_id: CurrentCompanyId) -> dict[str, str]:
        return {"company_id": str(company_id)}

    return test_app


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Client over the test app, with the DB bound to the rollback session."""
    test_app = _build_test_app()

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    test_app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
        yield c


async def _make_user(
    db_session: AsyncSession,
    *,
    email: str = "processor@acme.com",
    roles: tuple[UserRole, ...] = (UserRole.PROCESSOR,),
    is_active: bool = True,
    owner: bool = False,
) -> User:
    company = Company(name="Acme", slug="acme")
    db_session.add(company)
    await db_session.flush()
    user = make_user(
        company_id=company.id,
        email=email,
        hashed_password=hash_password(PASSWORD),
        first_name="Pat",
        last_name="Processor",
        roles=roles,
        is_active=is_active,
    )
    db_session.add(user)
    await db_session.flush()
    if owner:
        company.owner_user_id = user.id
        await db_session.flush()
    return user


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# get_current_user via GET /auth/me
# --------------------------------------------------------------------------- #


async def test_me_with_valid_token_returns_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A valid access token resolves the correct live user; no hashed_password."""
    user = await _make_user(db_session)
    resp = await client.get(ME_URL, headers=_bearer(create_access_token(user.id)))
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(user.id)
    assert body["email"] == user.email
    assert "hashed_password" not in resp.text


@pytest.mark.parametrize(
    ("roles", "owner", "derived_role"),
    [
        ((UserRole.PROCESSOR,), False, "processor"),
        ((UserRole.LOAN_OFFICER,), False, "processor"),
        ((UserRole.ADMIN,), True, "admin"),
        ((UserRole.PROCESSOR, UserRole.ADMIN, UserRole.LOAN_OFFICER), False, "admin"),
    ],
)
async def test_me_returns_the_role_set_the_derived_role_and_ownership(
    client: AsyncClient,
    db_session: AsyncSession,
    roles: tuple[UserRole, ...],
    owner: bool,
    derived_role: str,
) -> None:
    """`roles` is the set, `role` is `admin` iff the set holds ADMIN, `is_owner` is the company's."""
    user = await _make_user(db_session, roles=roles, owner=owner)
    # Expunged, so the request loads the user and company itself, as it would in production:
    # nothing the test session already holds can stand in for an eager load that is missing.
    db_session.expunge_all()

    resp = await client.get(ME_URL, headers=_bearer(create_access_token(user.id)))

    assert resp.status_code == 200
    body = resp.json()
    assert body["roles"] == sorted(role.value for role in roles)
    assert body["role"] == derived_role
    assert body["is_owner"] is owner


async def test_me_without_token_is_401(client: AsyncClient) -> None:
    """No Authorization header -> 401 with a WWW-Authenticate: Bearer challenge."""
    resp = await client.get(ME_URL)
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


async def test_me_with_malformed_header_is_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A non-Bearer or empty Authorization header -> 401."""
    user = await _make_user(db_session)
    token = create_access_token(user.id)
    for header in ({"Authorization": "Basic abc123"}, {"Authorization": "Bearer"}):
        resp = await client.get(ME_URL, headers=header)
        assert resp.status_code == 401
    # Sanity: the same token under the correct scheme works.
    ok = await client.get(ME_URL, headers=_bearer(token))
    assert ok.status_code == 200


async def test_me_with_refresh_token_is_401(client: AsyncClient, db_session: AsyncSession) -> None:
    """A refresh token used as a Bearer access token -> 401 (wrong type)."""
    user = await _make_user(db_session)
    resp = await client.get(ME_URL, headers=_bearer(create_refresh_token(user.id)))
    assert resp.status_code == 401


async def test_me_with_expired_token_is_401(client: AsyncClient, db_session: AsyncSession) -> None:
    """An expired access token -> 401."""
    from datetime import timedelta

    user = await _make_user(db_session)
    expired = create_access_token(user.id, expires_delta=timedelta(seconds=-1))
    resp = await client.get(ME_URL, headers=_bearer(expired))
    assert resp.status_code == 401


async def test_me_with_tampered_token_is_401(client: AsyncClient, db_session: AsyncSession) -> None:
    """A tampered/garbage token -> 401."""
    user = await _make_user(db_session)
    token = create_access_token(user.id)
    # Flip the FIRST char (always significant; the last base64 char may have
    # unused trailing bits, which would make this tamper a no-op and flaky).
    tampered = ("A" if token[0] != "A" else "B") + token[1:]
    assert (await client.get(ME_URL, headers=_bearer(tampered))).status_code == 401
    assert (await client.get(ME_URL, headers=_bearer("not.a.jwt"))).status_code == 401


async def test_deactivated_user_with_valid_token_is_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """CRITICAL: a still-valid token is rejected once the user is deactivated.

    role/company/is_active are read from the live DB record, not the token, so
    flipping is_active=False cuts the user off on their very next request — the
    V1 deactivation cutoff with no token-revocation store.
    """
    user = await _make_user(db_session)
    token = create_access_token(user.id)
    assert (await client.get(ME_URL, headers=_bearer(token))).status_code == 200

    user.is_active = False
    await db_session.flush()

    assert (await client.get(ME_URL, headers=_bearer(token))).status_code == 401


async def test_deleted_user_with_valid_token_is_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A valid token whose user no longer exists -> 401 (live lookup returns None)."""
    user = await _make_user(db_session)
    token = create_access_token(user.id)
    await db_session.delete(user)
    await db_session.flush()
    assert (await client.get(ME_URL, headers=_bearer(token))).status_code == 401


async def test_token_for_unknown_subject_is_401(client: AsyncClient) -> None:
    """A well-formed token whose subject matches no user -> 401."""
    resp = await client.get(ME_URL, headers=_bearer(create_access_token(uuid4())))
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# require_role (403 vs 401)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("roles", "status"),
    [
        ((UserRole.ADMIN,), 200),
        ((UserRole.PROCESSOR, UserRole.ADMIN), 200),
        ((UserRole.PROCESSOR,), 403),  # NOT 401 — they are authenticated
        ((UserRole.LOAN_OFFICER,), 403),
        ((UserRole.PROCESSOR, UserRole.LOAN_OFFICER), 403),
    ],
)
async def test_require_role_admin_checks_the_role_set(
    client: AsyncClient, db_session: AsyncSession, roles: tuple[UserRole, ...], status: int
) -> None:
    """An admin-only route admits any user whose set holds ADMIN, alone or with other roles."""
    user = await _make_user(db_session, roles=roles)
    db_session.expunge_all()
    resp = await client.get(ADMIN_URL, headers=_bearer(create_access_token(user.id)))
    assert resp.status_code == status
    if status == 200:
        assert resp.json()["id"] == str(user.id)


async def test_require_role_without_token_is_401(client: AsyncClient) -> None:
    """An unauthenticated request to a role-gated route is 401, not 403.

    Authentication precedes authorization: no identity means 401.
    """
    resp = await client.get(ADMIN_URL)
    assert resp.status_code == 401


async def test_require_role_allows_any_listed_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """require_role(ADMIN, PROCESSOR) admits a PROCESSOR (multiple roles)."""
    proc = await _make_user(db_session, roles=(UserRole.PROCESSOR,))
    resp = await client.get(STAFF_URL, headers=_bearer(create_access_token(proc.id)))
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# tenant context
# --------------------------------------------------------------------------- #


async def test_tenant_context_is_the_users_company(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """get_current_company_id surfaces the authenticated user's company_id."""
    user = await _make_user(db_session)
    resp = await client.get(COMPANY_URL, headers=_bearer(create_access_token(user.id)))
    assert resp.status_code == 200
    assert resp.json()["company_id"] == str(user.company_id)
