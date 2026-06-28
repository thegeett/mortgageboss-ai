"""Endpoint tests for the LTV calculator (LP-77).

GET returns the auto-populated calculation (three ratios + breakdown); PUT/DELETE
set/clear an override and return the recomputed result. Cross-company → 404.
"""

from collections.abc import AsyncIterator
from decimal import Decimal

import pytest_asyncio
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, LoanProgram, LoanPurpose, Property, User, UserRole
from app.models.loan_file import LoanFile
from app.services.loan_files import create_loan_file
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

API = "/api/v1/loan-files"


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


async def _user_and_token(db: AsyncSession, *, slug: str, email: str) -> tuple[Company, User, str]:
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


async def _seed(db: AsyncSession, company: Company) -> LoanFile:
    loan_file = await create_loan_file(
        db,
        company_id=company.id,
        loan_program=LoanProgram.CONVENTIONAL,
        loan_purpose=LoanPurpose.PURCHASE,
    )
    loan_file.loan_amount = Decimal("180000")
    db.add(
        Property(
            loan_file_id=loan_file.id,
            purchase_price=Decimal("190000"),
            valuation_amount=Decimal("200000"),
        )
    )
    await db.commit()
    return loan_file


async def test_get_ltv_returns_three_ratios_and_breakdown(
    client: AsyncClient, db: AsyncSession
) -> None:
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await _seed(db, company)

    resp = await client.get(f"{API}/{loan_file.display_id}/ltv", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["ltv"] == "94.74"  # 180000 / 190000 (lesser-of)
    assert body["value_basis"] == "190000.00"
    assert "lesser of" in body["value_basis_label"]
    assert body["limit"]["ltv_max"] == "97"
    assert body["limit"]["status"] == "pass"
    assert len(body["loan_items"]) == 4  # first / second / HELOC drawn / HELOC limit
    assert len(body["value_items"]) == 2  # purchase price / appraised value


async def test_put_override_recomputes(client: AsyncClient, db: AsyncSession) -> None:
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await _seed(db, company)

    resp = await client.put(
        f"{API}/{loan_file.display_id}/ltv/overrides/ltv.appraised_value",
        json={"amount": "180000", "note": "Per appraisal"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["value_basis"] == "180000.00"  # lesser-of(190k, 180k)
    assert body["ltv"] == "100.00"  # 180000 / 180000

    cleared = await client.delete(
        f"{API}/{loan_file.display_id}/ltv/overrides/ltv.appraised_value", headers=_auth(token)
    )
    assert cleared.status_code == 200
    assert cleared.json()["ltv"] == "94.74"  # back to the auto basis


async def test_ltv_is_tenant_scoped(client: AsyncClient, db: AsyncSession) -> None:
    _company_a, _ua, token_a = await _user_and_token(db, slug="acme", email="a@acme.com")
    company_b, _ub, _tb = await _user_and_token(db, slug="other", email="b@other.com")
    theirs = await _seed(db, company_b)

    resp = await client.get(f"{API}/{theirs.display_id}/ltv", headers=_auth(token_a))
    assert resp.status_code == 404
