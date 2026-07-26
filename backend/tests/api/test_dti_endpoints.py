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
    Document,
    DocumentStatus,
    Extraction,
    ExtractionStatus,
    LoanProgram,
    StatedIncomeItem,
    StatedLiability,
    UploadSource,
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


async def _seed(db: AsyncSession, company: Company, *, with_housing: bool = True) -> LoanFile:
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
    await db.flush()
    # LP-375: seed the REQUIRED housing inputs (taxes $300/mo + insurance $100/mo) so the DTI is
    # computable, not fail-closed — a missing tax bill / hazard binder now gates the ratio (absent≠0).
    # ``with_housing=False`` leaves them absent to exercise the gated display.
    for doc_type, field, value in (
        ()
        if not with_housing
        else (
            ("property_tax_bill", "annual_tax_amount", "3600"),
            ("homeowners_insurance", "annual_premium", "1200"),
        )
    ):
        doc = Document(
            loan_file_id=loan_file.id,
            original_filename=f"{doc_type}.pdf",
            mime_type="application/pdf",
            file_size_bytes=1,
            storage_path=f"seed/{doc_type}",
            document_type=doc_type,
            status=DocumentStatus.COMPLETED,
            upload_source=UploadSource.USER_UPLOAD,
        )
        db.add(doc)
        await db.flush()
        db.add(
            Extraction(
                document_id=doc.id,
                version=1,
                is_current=True,
                extracted_data={field: {"value": value}},
                extraction_status=ExtractionStatus.SUCCEEDED,
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
    assert body["back_end_dti"] == "26.78"
    assert body["limit"]["back_end_max"] == "50"
    assert body["limit"]["status"] == "pass"
    assert len(body["income_items"]) == 1
    assert body["back_end_formula"].startswith("Back-end DTI")


async def test_get_dti_gated_when_no_insurance_binder(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-375 — the $0.00 fix end-to-end: a file with no tax bill / insurance binder returns a GATED DTI
    (ratios null, a reason, the inputs marked unknown) — NOT a fabricated $0.00 and a confident ratio."""
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await _seed(db, company, with_housing=False)

    body = (await client.get(f"{API}/{loan_file.display_id}/dti", headers=_auth(token))).json()

    assert body["gated"] is True
    assert body["front_end_dti"] is None and body["back_end_dti"] is None
    assert "unknown" in body["gate_reason"]
    assert body["limit"]["status"] == "unknown"
    insurance = next(i for i in body["housing_items"] if i["key"] == "housing.insurance")
    assert insurance["unknown"] is True
    assert insurance["auto_amount"] is None  # never a fabricated "0.00"


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
    assert body["back_end_dti"] == "6.78"  # the debt removed
    debt = next(i for i in body["debt_items"] if i["key"] == debt_key)
    assert debt["overridden"] is True

    # DELETE reverts.
    cleared = await client.delete(
        f"{API}/{loan_file.display_id}/dti/overrides/{debt_key}", headers=_auth(token)
    )
    assert cleared.status_code == 200
    assert cleared.json()["back_end_dti"] == "26.78"


async def test_dti_is_tenant_scoped(client: AsyncClient, db: AsyncSession) -> None:
    """Another company's file is 404 (existence not revealed)."""
    _company_a, _ua, token_a = await _user_and_token(db, slug="acme", email="a@acme.com")
    company_b, _ub, _tb = await _user_and_token(db, slug="other", email="b@other.com")
    theirs = await _seed(db, company_b)

    resp = await client.get(f"{API}/{theirs.display_id}/dti", headers=_auth(token_a))
    assert resp.status_code == 404
