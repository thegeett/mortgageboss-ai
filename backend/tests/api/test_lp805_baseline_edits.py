"""LP-80.5 — value-recording audit + verification staleness on baseline edits.

Editing stated financials, loan terms, the target lender, or the subject property
now (a) records the actual **from→to values** in the activity_log ``detail`` (a real
change history — superseding the LP-56 value-free posture) and (b) marks the
cross-source verification **stale** (a baseline change on the file's side of the
comparison, the same as a document change). Property edits — previously silent — are
now audited. Uses the in-process client + a shared rollback session so the API call
and the DB assertions see the same data.
"""

from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import UUID

import pytest_asyncio
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import (
    ActivityLog,
    ActivityType,
    Company,
    Lender,
    LoanProgram,
    StatedLiability,
    User,
    UserRole,
)
from app.models.loan_file import LoanFile
from app.models.property import Property
from app.services.loan_files import create_loan_file
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

V1 = "/api/v1"


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
        hashed_password=hash_password("x"),
        first_name="Pro",
        last_name="Cessor",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return company, create_access_token(user.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _is_stale(db: AsyncSession, loan_file_id: UUID) -> bool:
    return bool(
        await db.scalar(select(LoanFile.verification_stale).where(LoanFile.id == loan_file_id))
    )


async def _set_current(db: AsyncSession, loan_file_id: UUID) -> None:
    """Reset the staleness flag so the next edit's effect is unambiguous."""
    lf = await db.get(LoanFile, loan_file_id)
    assert lf is not None
    lf.verification_stale = False
    await db.flush()


async def _latest_file_updated(db: AsyncSession, loan_file_id: UUID) -> ActivityLog:
    return (
        await db.execute(
            select(ActivityLog)
            .where(
                ActivityLog.loan_file_id == loan_file_id,
                ActivityLog.activity_type == ActivityType.FILE_UPDATED,
            )
            .order_by(ActivityLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one()


# --- Stated financials: from→to values + mark stale --------------------------


async def test_stated_liability_edit_records_values_and_marks_stale(
    client: AsyncClient, db: AsyncSession
) -> None:
    company, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    row = StatedLiability(
        loan_file_id=loan_file.id, liability_type="Installment", monthly_payment=Decimal("100")
    )
    db.add(row)
    await db.flush()
    await _set_current(db, loan_file.id)

    resp = await client.patch(
        f"{V1}/stated-liabilities/{row.id}",
        json={"monthly_payment": "250.00"},
        headers=_auth(token),
    )
    assert resp.status_code == 200

    entry = await _latest_file_updated(db, loan_file.id)
    assert entry.detail["section"] == "stated_liability"
    assert entry.detail["action"] == "edit"
    # The from→to value is recorded (a real change history) — superseding value-free.
    assert entry.detail["changes"] == [{"field": "monthly_payment", "from": "100", "to": "250.00"}]
    assert await _is_stale(db, loan_file.id) is True


async def test_stated_liability_add_marks_stale(client: AsyncClient, db: AsyncSession) -> None:
    company, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    await _set_current(db, loan_file.id)

    resp = await client.post(
        f"{V1}/loan-files/{loan_file.display_id}/stated-liabilities",
        json={"liability_type": "Card", "monthly_payment": "50"},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    entry = await _latest_file_updated(db, loan_file.id)
    assert entry.detail["action"] == "add"
    assert entry.detail["values"]["monthly_payment"] == "50"
    assert await _is_stale(db, loan_file.id) is True


# --- Property: previously silent → now audited with values + marks stale ------


async def test_property_edit_is_audited_with_values_and_marks_stale(
    client: AsyncClient, db: AsyncSession
) -> None:
    company, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    prop = Property(loan_file_id=loan_file.id, estimated_value=Decimal("400000"))
    db.add(prop)
    await db.flush()
    await _set_current(db, loan_file.id)

    resp = await client.patch(
        f"{V1}/loan-files/{loan_file.display_id}/property",
        json={"estimated_value": "450000", "city": "Austin"},
        headers=_auth(token),
    )
    assert resp.status_code == 200

    entry = await _latest_file_updated(db, loan_file.id)
    assert entry.detail["section"] == "property"
    changes = {c["field"]: (c["from"], c["to"]) for c in entry.detail["changes"]}
    assert changes["estimated_value"] == ("400000", "450000")
    assert changes["city"] == (None, "Austin")
    assert await _is_stale(db, loan_file.id) is True


async def test_valuation_amount_edit_is_exposed_audited_and_marks_stale(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-90: valuation_amount (the field the LTV reads first) is now exposed in the property
    response, and editing it is audited from→to + marks verification stale — no hidden field."""
    company, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    prop = Property(loan_file_id=loan_file.id, valuation_amount=Decimal("200000"))
    db.add(prop)
    await db.flush()
    await _set_current(db, loan_file.id)

    resp = await client.patch(
        f"{V1}/loan-files/{loan_file.display_id}/property",
        json={"valuation_amount": "210000"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    # Exposed in the response (previously absent → the Overview couldn't read it).
    assert resp.json()["valuation_amount"] == "210000"

    entry = await _latest_file_updated(db, loan_file.id)
    changes = {c["field"]: (c["from"], c["to"]) for c in entry.detail["changes"]}
    assert changes["valuation_amount"] == ("200000", "210000")
    assert await _is_stale(db, loan_file.id) is True  # the property drives the LTV baseline


async def test_loan_file_detail_exposes_valuation_amount(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-90: the loan-file detail (what the Overview reads) now includes valuation_amount."""
    company, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    db.add(Property(loan_file_id=loan_file.id, valuation_amount=Decimal("345000")))
    await db.flush()

    resp = await client.get(
        f"{V1}/loan-files/{loan_file.display_id}",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["property"]["valuation_amount"] == "345000.00"


# --- Loan terms / target lender: baseline → stale; contact fields → not -------


async def test_setting_target_lender_marks_stale(client: AsyncClient, db: AsyncSession) -> None:
    company, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    lender = Lender(
        company_id=company.id, name="UWM", slug="uwm", supported_programs=["conventional"]
    )
    db.add(lender)
    loan_file = await create_loan_file(db, company_id=company.id)
    await db.flush()
    await _set_current(db, loan_file.id)

    resp = await client.patch(
        f"{V1}/loan-files/{loan_file.display_id}",
        json={"lender_id": str(lender.id)},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert await _is_stale(db, loan_file.id) is True  # lender selects the overlay → baseline


async def test_program_change_marks_stale(client: AsyncClient, db: AsyncSession) -> None:
    company, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await _set_current(db, loan_file.id)

    resp = await client.patch(
        f"{V1}/loan-files/{loan_file.display_id}",
        json={"loan_program": "fha"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert await _is_stale(db, loan_file.id) is True


async def test_contact_field_edit_does_not_mark_stale(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A non-baseline field (loan officer) is audited with values but does NOT mark stale."""
    company, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    await _set_current(db, loan_file.id)

    resp = await client.patch(
        f"{V1}/loan-files/{loan_file.display_id}",
        json={"loan_officer_name": "Jordan LO"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    entry = await _latest_file_updated(db, loan_file.id)
    assert entry.detail["changes"] == [
        {"field": "loan_officer_name", "from": None, "to": "Jordan LO"}
    ]
    assert await _is_stale(db, loan_file.id) is False  # contact info is not a baseline input


# --- Tenant scoping on the edit paths ----------------------------------------


async def test_cross_company_property_edit_is_404(client: AsyncClient, db: AsyncSession) -> None:
    _a, token_a = await _user_and_token(db, slug="company-a", email="a@a.com")
    company_b, _tb = await _user_and_token(db, slug="company-b", email="b@b.com")
    other = await create_loan_file(db, company_id=company_b.id)
    db.add(Property(loan_file_id=other.id))
    await db.flush()

    resp = await client.patch(
        f"{V1}/loan-files/{other.display_id}/property",
        json={"city": "Nope"},
        headers=_auth(token_a),
    )
    assert resp.status_code == 404
