"""Endpoint tests for GET /lenders (LP-32).

Verifies the lender list is auth-gated and **company-scoped** (a company sees
only its own lenders), and returns an empty list when there are none.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, Lender, User, UserRole
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

LENDERS_URL = "/api/v1/lenders"


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _user_and_token(db: AsyncSession, *, slug: str, email: str) -> tuple[Company, str]:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=email,
        hashed_password=hash_password("irrelevant"),
        first_name="Test",
        last_name="User",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return company, create_access_token(user.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_empty_when_no_lenders(client: AsyncClient, db_session: AsyncSession) -> None:
    """A company with no lenders gets an empty list (graceful, not an error)."""
    _company, token = await _user_and_token(db_session, slug="acme", email="u@acme.com")
    resp = await client.get(LENDERS_URL, headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_lenders_are_company_scoped(client: AsyncClient, db_session: AsyncSession) -> None:
    """Each company sees only its own lenders."""
    company_a, a_token = await _user_and_token(db_session, slug="company-a", email="a@a.com")
    company_b, b_token = await _user_and_token(db_session, slug="company-b", email="b@b.com")
    db_session.add(
        Lender(
            company_id=company_a.id,
            name="Acme Bank",
            slug="acme-bank",
            supported_programs=["conventional"],
        )
    )
    db_session.add(
        Lender(
            company_id=company_b.id, name="Beta Lending", slug="beta", supported_programs=["fha"]
        )
    )
    await db_session.flush()

    a_list = (await client.get(LENDERS_URL, headers=_auth(a_token))).json()
    assert [lender["name"] for lender in a_list] == ["Acme Bank"]
    assert a_list[0]["supported_programs"] == ["conventional"]

    b_list = (await client.get(LENDERS_URL, headers=_auth(b_token))).json()
    assert [lender["name"] for lender in b_list] == ["Beta Lending"]


async def test_unauthenticated_is_401(client: AsyncClient) -> None:
    """The lenders list requires authentication."""
    assert (await client.get(LENDERS_URL)).status_code == 401
