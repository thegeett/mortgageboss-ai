"""Endpoint tests for the LP-70 needs disposition flow (confirm/adjust/dismiss/waive/add).

The writes are nested under a loan file and use the LP-29 file gate, so the crux is
**transitive tenant scoping** (a Company A user gets ``404`` for a Company B file's
need) plus a per-need 404 (a need not in the path file). Each action updates the
need (the captured correction signal) and is **audited** (an activity-log entry the
activity endpoint surfaces). The read endpoint exposes the dashboard's fields
(reasoning, disposition, the satisfying document) and no raw PII.
"""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest_asyncio
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.needs_item import (
    NeedsItemDisposition,
    NeedsItemOrigin,
)
from app.services.loan_files import create_loan_file
from app.services.needs_items import create_needs_item
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


async def _proposed_need(db: AsyncSession, loan_file_id):
    """An AI-proposed need with reasoning — the typical LP-69 starting point."""
    return await create_needs_item(
        db,
        loan_file_id=loan_file_id,
        title="Two years of tax returns",
        needs_type="tax_return",
        origin=NeedsItemOrigin.AI_REASONING,
        disposition=NeedsItemDisposition.PROPOSED,
        reasoning="Self-employment income is qualified from tax returns, not pay stubs.",
    )


# --------------------------------------------------------------------------- #
# Read — the dashboard fields
# --------------------------------------------------------------------------- #


async def test_read_exposes_reasoning_disposition_and_no_raw_pii(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme", email="u@acme.com")
    lf = await create_loan_file(db_session, company_id=company.id)
    await _proposed_need(db_session, lf.id)

    rows = (await client.get(_needs_url(lf.display_id), headers=_auth(token))).json()
    assert len(rows) == 1
    item = rows[0]
    # The explainability "why" + the human-confirmation lifecycle are surfaced.
    assert item["disposition"] == "proposed"
    assert item["origin"] == "ai_reasoning"
    assert "tax returns" in item["reasoning"]
    assert item["satisfied_by_document_filename"] is None
    # No raw PII leaks through the needs response.
    assert "ssn" not in item and "masked_ssn" not in item


# --------------------------------------------------------------------------- #
# The disposition writes — update + audit
# --------------------------------------------------------------------------- #


async def _activity_types(client: AsyncClient, ident: str, token: str) -> set[str]:
    rows = (await client.get(f"/api/v1/loan-files/{ident}/activity", headers=_auth(token))).json()
    return {entry["activity_type"] for entry in rows}


async def test_confirm_sets_confirmed_and_audits(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme", email="u@acme.com")
    lf = await create_loan_file(db_session, company_id=company.id)
    need = await _proposed_need(db_session, lf.id)

    res = await client.post(f"{_needs_url(lf.display_id)}/{need.id}/confirm", headers=_auth(token))
    assert res.status_code == 200
    assert res.json()["disposition"] == "confirmed"
    assert "needs_item_confirmed" in await _activity_types(client, lf.display_id, token)


async def test_adjust_updates_fields_and_confirms(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme", email="u@acme.com")
    lf = await create_loan_file(db_session, company_id=company.id)
    need = await _proposed_need(db_session, lf.id)

    res = await client.patch(
        f"{_needs_url(lf.display_id)}/{need.id}",
        headers=_auth(token),
        json={"title": "2023 + 2022 federal returns", "priority": "blocking"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "2023 + 2022 federal returns"
    assert body["priority"] == "blocking"
    assert body["disposition"] == "confirmed"  # adjusting = taking ownership
    assert "needs_item_adjusted" in await _activity_types(client, lf.display_id, token)


async def test_dismiss_sets_dismissed_waived_with_reason(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme", email="u@acme.com")
    lf = await create_loan_file(db_session, company_id=company.id)
    need = await _proposed_need(db_session, lf.id)

    res = await client.post(
        f"{_needs_url(lf.display_id)}/{need.id}/dismiss",
        headers=_auth(token),
        json={"reason": "W-2 employee only — no business returns needed."},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["disposition"] == "dismissed"
    assert body["status"] == "waived"  # taken out of the open set
    assert "W-2 employee" in body["reason"]
    assert "needs_item_dismissed" in await _activity_types(client, lf.display_id, token)


async def test_waive_sets_waived_with_reason(client: AsyncClient, db_session: AsyncSession) -> None:
    company, _user, token = await _make_user(db_session, slug="acme", email="u@acme.com")
    lf = await create_loan_file(db_session, company_id=company.id)
    need = await _proposed_need(db_session, lf.id)

    res = await client.post(
        f"{_needs_url(lf.display_id)}/{need.id}/waive",
        headers=_auth(token),
        json={"reason": "Lender waived the reserve requirement."},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "waived"
    assert body["disposition"] == "waived"
    assert "Lender waived" in body["reason"]
    assert "needs_item_waived" in await _activity_types(client, lf.display_id, token)


async def test_add_creates_a_confirmed_manual_need_and_audits(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company, _user, token = await _make_user(db_session, slug="acme", email="u@acme.com")
    lf = await create_loan_file(db_session, company_id=company.id)

    res = await client.post(
        _needs_url(lf.display_id),
        headers=_auth(token),
        json={"title": "Homeowner's insurance declaration", "needs_type": "insurance"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["title"] == "Homeowner's insurance declaration"
    assert body["origin"] == "manual"  # the AI missed it (a correction signal)
    assert body["disposition"] == "confirmed"  # a processor-added need is real
    assert body["status"] == "pending"
    assert "needs_item_created" in await _activity_types(client, lf.display_id, token)


# --------------------------------------------------------------------------- #
# Tenant scoping + per-need 404
# --------------------------------------------------------------------------- #


async def test_cross_company_confirm_is_404(client: AsyncClient, db_session: AsyncSession) -> None:
    """A Company A user cannot dispose a Company B file's need (the file gate 404s)."""
    company_b, _ub, _tb = await _make_user(db_session, slug="globex", email="u@globex.com")
    _ca, _ua, token_a = await _make_user(db_session, slug="acme", email="u@acme.com")
    lf_b = await create_loan_file(db_session, company_id=company_b.id)
    need_b = await _proposed_need(db_session, lf_b.id)

    res = await client.post(
        f"{_needs_url(lf_b.display_id)}/{need_b.id}/confirm", headers=_auth(token_a)
    )
    assert res.status_code == 404


async def test_need_from_another_file_is_404(client: AsyncClient, db_session: AsyncSession) -> None:
    """A need that isn't in the path file 404s, even within the same company."""
    company, _user, token = await _make_user(db_session, slug="acme", email="u@acme.com")
    lf1 = await create_loan_file(db_session, company_id=company.id)
    lf2 = await create_loan_file(db_session, company_id=company.id)
    need_in_lf2 = await _proposed_need(db_session, lf2.id)

    res = await client.post(
        f"{_needs_url(lf1.display_id)}/{need_in_lf2.id}/confirm", headers=_auth(token)
    )
    assert res.status_code == 404


async def test_missing_need_is_404(client: AsyncClient, db_session: AsyncSession) -> None:
    company, _user, token = await _make_user(db_session, slug="acme", email="u@acme.com")
    lf = await create_loan_file(db_session, company_id=company.id)
    res = await client.post(f"{_needs_url(lf.display_id)}/{uuid4()}/confirm", headers=_auth(token))
    assert res.status_code == 404
