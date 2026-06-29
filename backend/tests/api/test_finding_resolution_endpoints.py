"""Per-finding resolution endpoints (LP-81) — Apply / Override / Add note.

The verification tab resolves findings: APPLY incorporates a finding into the
structured data (→ recompute interlock), OVERRIDE dismisses it with a required
reason, NOTE annotates it without resolving. Each returns the re-filtered status.
Tenant-scoped (cross-company → 404). Uses the in-process client + rollback session.
"""

from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest_asyncio
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import (
    Company,
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingStatus,
    StatedLiability,
    User,
    UserRole,
)
from app.models.finding import FindingResolutionStatus
from app.services.loan_files import create_loan_file
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

V1 = "/api/v1/loan-files"


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


async def _finding(
    db: AsyncSession,
    loan_file_id: UUID,
    *,
    apply_spec: dict[str, object] | None = None,
) -> Finding:
    details: dict[str, object] = {"type": "liability_discrepancy", "document_value": "800/mo"}
    if apply_spec is not None:
        details["apply"] = apply_spec
    f = Finding(
        loan_file_id=loan_file_id,
        rule_id="cross_source.liability_discrepancy",
        origin=FindingOrigin.AI_CROSS_SOURCE,
        confidence=0.9,
        status=FindingStatus.YELLOW,
        category=FindingCategory.CREDIT,
        message="An undisclosed obligation appears in the documents.",
        details=details,
    )
    db.add(f)
    await db.flush()
    return f


def _find(status: dict[str, Any], finding_id: UUID) -> dict[str, Any]:
    return next(f for f in status["findings"] if f["id"] == str(finding_id))


# --- Apply -------------------------------------------------------------------


async def test_apply_incorporates_and_returns_applied(
    client: AsyncClient, db: AsyncSession
) -> None:
    company, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    finding = await _finding(
        db,
        loan_file.id,
        apply_spec={
            "action": "add_liability",
            "liability_type": "Installment",
            "monthly_payment": "800",
        },
    )
    await db.commit()

    resp = await client.post(
        f"{V1}/{loan_file.display_id}/findings/{finding.id}/apply", headers=_auth(token)
    )
    assert resp.status_code == 200
    assert _find(resp.json(), finding.id)["resolution_status"] == "applied"
    # The apply incorporated the obligation into the structured data.
    liabilities = (
        (
            await db.execute(
                select(StatedLiability).where(StatedLiability.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert any(liability.monthly_payment == Decimal("800") for liability in liabilities)


# --- Override ----------------------------------------------------------------


async def test_override_requires_a_reason(client: AsyncClient, db: AsyncSession) -> None:
    company, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    finding = await _finding(db, loan_file.id)
    await db.commit()
    base = f"{V1}/{loan_file.display_id}/findings/{finding.id}/override"

    # Missing/empty reason → 422 (schema), whitespace-only → 400 (service).
    assert (await client.post(base, json={"reason": ""}, headers=_auth(token))).status_code == 422
    assert (
        await client.post(base, json={"reason": "   "}, headers=_auth(token))
    ).status_code == 400

    ok = await client.post(base, json={"reason": "Already in the AUS"}, headers=_auth(token))
    assert ok.status_code == 200
    assert _find(ok.json(), finding.id)["resolution_status"] == "overridden"


# --- Add note ----------------------------------------------------------------


async def test_note_annotates_without_resolving(client: AsyncClient, db: AsyncSession) -> None:
    company, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    finding = await _finding(db, loan_file.id)
    await db.commit()

    resp = await client.post(
        f"{V1}/{loan_file.display_id}/findings/{finding.id}/note",
        json={"note": "Asked the borrower to clarify"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    row = _find(resp.json(), finding.id)
    assert row["resolution_status"] == "open"  # a note does not resolve
    assert row["details"]["notes"][0]["note"] == "Asked the borrower to clarify"


# --- Not found / tenant scoping ----------------------------------------------


async def test_unknown_finding_is_404(client: AsyncClient, db: AsyncSession) -> None:
    company, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    await db.commit()
    resp = await client.post(
        f"{V1}/{loan_file.display_id}/findings/{uuid4()}/apply", headers=_auth(token)
    )
    assert resp.status_code == 404


async def test_cross_company_resolution_is_404(client: AsyncClient, db: AsyncSession) -> None:
    _a, token_a = await _user_and_token(db, slug="company-a", email="a@a.com")
    company_b, _tb = await _user_and_token(db, slug="company-b", email="b@b.com")
    other = await create_loan_file(db, company_id=company_b.id)
    finding = await _finding(db, other.id)
    await db.commit()

    resp = await client.post(
        f"{V1}/{other.display_id}/findings/{finding.id}/apply", headers=_auth(token_a)
    )
    assert resp.status_code == 404
    # A's view never resolved B's finding.
    row = await db.get(Finding, finding.id)
    assert row is not None and row.resolution_status is FindingResolutionStatus.OPEN
