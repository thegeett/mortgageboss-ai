"""Endpoint tests for the overview reads — needs + activity (LP-34).

Both are nested under a loan file and use the LP-29 file gate, so the crux is
**transitive tenant scoping**: a Company A user gets ``404`` for a Company B
file's needs/activity (the file lookup fails first). Also: they return the file's
items, and an empty list for a bare file.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.lender import LoanProgram
from app.services.loan_files import create_loan_file, create_loan_file_with_setup
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


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


async def _make_user(db: AsyncSession, *, slug: str, email: str) -> tuple[Company, User, str]:
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
    return company, user, create_access_token(user.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _needs_url(ident: str) -> str:
    return f"/api/v1/loan-files/{ident}/needs"


def _activity_url(ident: str) -> str:
    return f"/api/v1/loan-files/{ident}/activity"


async def test_needs_and_activity_list_the_files_items(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A file created with setup has template needs + a FILE_CREATED activity."""
    company, user, token = await _make_user(db_session, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file_with_setup(
        db_session,
        company_id=company.id,
        actor_user_id=user.id,
        loan_program=LoanProgram.FHA,
    )

    needs = (await client.get(_needs_url(loan_file.display_id), headers=_auth(token))).json()
    assert len(needs) == 5  # universal baseline + FHA placeholder (LP-30)
    assert all(item["origin"] == "template" for item in needs)
    assert all(item["status"] == "pending" for item in needs)  # LP-68 default (was outstanding)

    activity = (await client.get(_activity_url(loan_file.display_id), headers=_auth(token))).json()
    assert any(entry["activity_type"] == "file_created" for entry in activity)
    assert activity[0]["actor_user_id"] == str(user.id)


async def test_empty_for_a_bare_file(client: AsyncClient, db_session: AsyncSession) -> None:
    """A file created without the workflow has no needs and no activity."""
    company, _user, token = await _make_user(db_session, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    assert (await client.get(_needs_url(loan_file.display_id), headers=_auth(token))).json() == []
    assert (
        await client.get(_activity_url(loan_file.display_id), headers=_auth(token))
    ).json() == []


async def test_cross_tenant_needs_and_activity_are_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Company B cannot read Company A's needs/activity — 404 at the file gate."""
    company_a, user_a, _a_token = await _make_user(db_session, slug="company-a", email="a@a.com")
    _company_b, _user_b, b_token = await _make_user(db_session, slug="company-b", email="b@b.com")
    a_file = await create_loan_file_with_setup(
        db_session, company_id=company_a.id, actor_user_id=user_a.id
    )

    assert (
        await client.get(_needs_url(a_file.display_id), headers=_auth(b_token))
    ).status_code == 404
    assert (
        await client.get(_activity_url(a_file.display_id), headers=_auth(b_token))
    ).status_code == 404


async def test_unauthenticated_is_401(client: AsyncClient, db_session: AsyncSession) -> None:
    """The overview reads require authentication."""
    company, _user, _token = await _make_user(db_session, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    assert (await client.get(_needs_url(loan_file.display_id))).status_code == 401
    assert (await client.get(_activity_url(loan_file.display_id))).status_code == 401
