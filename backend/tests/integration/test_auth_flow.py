"""Auth flow (LP-45) — login → token works on a protected route; boundaries.

Phase 1 has no public *register* endpoint (users are provisioned server-side),
so the flow is: a real user logs in with a known password, receives a real JWT,
and that token authenticates the first protected endpoint (``/auth/me``). The
boundary cases — no token and a malformed token — must both be ``401``.
"""

from app.models import Company, User
from httpx import AsyncClient
from tests.integration import factories

AUTH = "/api/v1/auth"


async def test_login_returns_token_that_works_on_protected_route(
    client: AsyncClient, user_a: User
) -> None:
    resp = await client.post(
        f"{AUTH}/login",
        json={"email": user_a.email, "password": factories.DEFAULT_PASSWORD},
    )
    assert resp.status_code == 200
    body = resp.json()
    token = body["access_token"]
    assert body["token_type"] == "bearer"
    # The token authenticates /auth/me, returning this very user.
    me = await client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["id"] == str(user_a.id)
    # Never leak the password hash.
    assert "hashed_password" not in me.json()


async def test_login_wrong_password_is_401(client: AsyncClient, user_a: User) -> None:
    resp = await client.post(
        f"{AUTH}/login",
        json={"email": user_a.email, "password": "wrong-password"},  # pragma: allowlist secret
    )
    assert resp.status_code == 401


async def test_login_unknown_email_is_401(client: AsyncClient, company_a: Company) -> None:
    resp = await client.post(
        f"{AUTH}/login",
        json={"email": "nobody@nowhere.com", "password": "whatever"},  # pragma: allowlist secret
    )
    assert resp.status_code == 401


async def test_protected_route_without_token_is_401(client: AsyncClient) -> None:
    assert (await client.get(f"{AUTH}/me")).status_code == 401


async def test_protected_route_with_bad_token_is_401(client: AsyncClient) -> None:
    resp = await client.get(f"{AUTH}/me", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert resp.status_code == 401
