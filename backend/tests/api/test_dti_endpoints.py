"""Endpoint tests for the DTI calculator (LP-76).

GET returns the auto-populated calculation; PUT/DELETE set/clear an override and
return the recomputed result (the real-time recalc in one round-trip). Tenant
isolation: a cross-company file is 404. Uses the commit-safe session pattern.
"""

from collections.abc import AsyncIterator
from decimal import Decimal

import pytest_asyncio
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import (
    Borrower,
    Company,
    LoanProgram,
    StatedIncomeItem,
    StatedLiability,
    User,
    UserRole,
)
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
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    loan_file.note_amount = Decimal("100000")
    loan_file.note_rate_percent = Decimal("0")
    loan_file.amortization_months = 360
    borrower = Borrower(loan_file_id=loan_file.id, first_name="Pat", last_name="B", is_primary=True)
    db.add(borrower)
    await db.flush()
    db.add(
        StatedIncomeItem(
            borrower_id=borrower.id, monthly_amount=Decimal("10000"), income_type="Base"
        )
    )
    db.add(
        StatedLiability(
            loan_file_id=loan_file.id, liability_type="Installment", monthly_payment=Decimal("2000")
        )
    )
    await db.commit()
    return loan_file


async def test_get_dti_returns_auto_populated_calculation(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET returns the itemized, auto-populated calculation with the limit."""
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await _seed(db, company)

    resp = await client.get(f"{API}/{loan_file.display_id}/dti", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["gross_monthly_income"] == "10000.00"
    assert body["back_end_dti"] == "22.78"
    assert body["limit"]["back_end_max"] == "50"
    assert body["limit"]["status"] == "pass"
    assert len(body["income_items"]) == 1
    assert body["back_end_formula"].startswith("Back-end DTI")


async def test_put_override_recomputes_in_response(client: AsyncClient, db: AsyncSession) -> None:
    """PUT an override → the response carries the recomputed numbers (real-time)."""
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await _seed(db, company)
    debt_key = (await client.get(f"{API}/{loan_file.display_id}/dti", headers=_auth(token))).json()[
        "debt_items"
    ][0]["key"]

    resp = await client.put(
        f"{API}/{loan_file.display_id}/dti/overrides/{debt_key}",
        json={"amount": "0", "note": "Paid at closing"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["back_end_dti"] == "2.78"  # the debt removed
    debt = next(i for i in body["debt_items"] if i["key"] == debt_key)
    assert debt["overridden"] is True

    # DELETE reverts.
    cleared = await client.delete(
        f"{API}/{loan_file.display_id}/dti/overrides/{debt_key}", headers=_auth(token)
    )
    assert cleared.status_code == 200
    assert cleared.json()["back_end_dti"] == "22.78"


async def test_dti_is_tenant_scoped(client: AsyncClient, db: AsyncSession) -> None:
    """Another company's file is 404 (existence not revealed)."""
    _company_a, _ua, token_a = await _user_and_token(db, slug="acme", email="a@acme.com")
    company_b, _ub, _tb = await _user_and_token(db, slug="other", email="b@other.com")
    theirs = await _seed(db, company_b)

    resp = await client.get(f"{API}/{theirs.display_id}/dti", headers=_auth(token_a))
    assert resp.status_code == 404
