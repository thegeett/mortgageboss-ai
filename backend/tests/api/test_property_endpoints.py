"""Endpoint tests for the nested property singleton (LP-29).

Same commit-safe session pattern as the borrower tests. Covers the singleton
semantics (get 404 when none, create 201, second create 409, update, delete) and
transitive tenant isolation: a Company A user cannot touch the property on a
Company B file (the file gate returns 404 first).
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.loan_file import LoanFile
from app.services.loan_files import create_loan_file
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


@pytest_asyncio.fixture
async def db(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    connection = await test_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db

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


async def _loan_file(db: AsyncSession, company: Company) -> LoanFile:
    return await create_loan_file(db, company_id=company.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _property_url(file_ident: str) -> str:
    return f"/api/v1/loan-files/{file_ident}/property"


async def test_singleton_lifecycle(client: AsyncClient, db: AsyncSession) -> None:
    """get(404) → create(201) → create-again(409) → update → delete → get(404)."""
    company, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await _loan_file(db, company)
    url = _property_url(loan_file.display_id)

    # No property yet.
    assert (await client.get(url, headers=_auth(token))).status_code == 404

    created = await client.post(
        url,
        json={"address_line": "123 Main St", "city": "Austin", "state": "TX"},
        headers=_auth(token),
    )
    assert created.status_code == 201
    assert created.json()["address_line"] == "123 Main St"

    # Second create → 409 (singleton).
    again = await client.post(url, json={"city": "Dallas"}, headers=_auth(token))
    assert again.status_code == 409

    # Update the existing one.
    upd = await client.patch(url, json={"city": "Dallas"}, headers=_auth(token))
    assert upd.status_code == 200
    assert upd.json()["city"] == "Dallas"
    assert upd.json()["state"] == "TX"  # untouched

    # Delete (soft) → then get is 404 again.
    assert (await client.delete(url, headers=_auth(token))).status_code == 204
    assert (await client.get(url, headers=_auth(token))).status_code == 404


async def test_update_and_delete_404_when_no_property(
    client: AsyncClient, db: AsyncSession
) -> None:
    """PATCH/DELETE on a file with no property return 404."""
    company, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await _loan_file(db, company)
    url = _property_url(loan_file.display_id)
    assert (await client.patch(url, json={"city": "X"}, headers=_auth(token))).status_code == 404
    assert (await client.delete(url, headers=_auth(token))).status_code == 404


async def test_cross_tenant_property_is_404_via_the_file_gate(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Company B cannot get/create/update/delete the property on Company A's file."""
    company_a, a_token = await _user_and_token(db, slug="company-a", email="a@a.com")
    _company_b, b_token = await _user_and_token(db, slug="company-b", email="b@b.com")
    a_file = await _loan_file(db, company_a)
    a_url = _property_url(a_file.display_id)
    await client.post(a_url, json={"city": "Austin"}, headers=_auth(a_token))

    assert (await client.get(a_url, headers=_auth(b_token))).status_code == 404
    assert (await client.post(a_url, json={"city": "X"}, headers=_auth(b_token))).status_code == 404
    assert (
        await client.patch(a_url, json={"city": "X"}, headers=_auth(b_token))
    ).status_code == 404
    assert (await client.delete(a_url, headers=_auth(b_token))).status_code == 404

    # A's property is untouched.
    still = await client.get(a_url, headers=_auth(a_token))
    assert still.status_code == 200
    assert still.json()["city"] == "Austin"


async def test_unauthenticated_is_401(client: AsyncClient, db: AsyncSession) -> None:
    """Property endpoints require auth."""
    company, _token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await _loan_file(db, company)
    url = _property_url(loan_file.display_id)
    assert (await client.get(url)).status_code == 401
    assert (await client.post(url, json={"city": "X"})).status_code == 401
