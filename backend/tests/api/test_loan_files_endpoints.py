"""Endpoint tests for loan-file CRUD (LP-28).

Drives the real FastAPI app via httpx with ``get_db`` overridden to a
**commit-safe** session: these endpoints call ``db.commit()`` (unlike earlier
tickets'), so the session joins the test's outer transaction via SAVEPOINTs
(``join_transaction_mode="create_savepoint"``) — endpoint commits release a
savepoint, and the whole thing is rolled back at the end, keeping isolation.

The crux under test is **tenant isolation**: a Company A user can never list,
retrieve, update, or delete Company B's files (each verified), out-of-company
access is ``404`` (not ``403``), and ``inbox_token`` / raw SSN never appear in a
response.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Borrower, Company, Lender, Property, User, UserRole
from app.models.activity_log import ActivityLog, ActivityType
from app.models.loan_file import LoanFile
from app.models.needs_item import NeedsItem
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

LOAN_FILES_URL = "/api/v1/loan-files"


@pytest_asyncio.fixture
async def db(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A commit-safe session: endpoint commits hit SAVEPOINTs inside one outer
    transaction that is rolled back afterwards (so writes don't leak)."""
    connection = await test_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
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
        hashed_password=hash_password("irrelevant-for-token-auth"),
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


# --------------------------------------------------------------------------- #
# create
# --------------------------------------------------------------------------- #


async def test_create_returns_draft_in_callers_company_no_secrets(
    client: AsyncClient, db: AsyncSession
) -> None:
    """POST creates a DRAFT file in the caller's company; no inbox_token leaks."""
    _company, user, token = await _user_and_token(db, slug="acme", email="u@acme.com")

    resp = await client.post(
        LOAN_FILES_URL, json={"loan_officer_name": "Jordan LO"}, headers=_auth(token)
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "draft"
    assert body["display_id"]
    assert body["loan_officer_name"] == "Jordan LO"
    assert "inbox_token" not in resp.text

    # company is derived from the user, never the request — verify in the DB.
    created = await db.scalar(select(LoanFile).where(LoanFile.display_id == body["display_id"]))
    assert created is not None
    assert created.company_id == user.company_id


async def test_create_ignores_unmodelled_company_id(client: AsyncClient, db: AsyncSession) -> None:
    """A company_id in the body is ignored — the schema doesn't accept it."""
    _company, user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    other = Company(name="Other", slug="other")
    db.add(other)
    await db.flush()

    resp = await client.post(
        LOAN_FILES_URL, json={"company_id": str(other.id)}, headers=_auth(token)
    )
    assert resp.status_code == 201
    created = await db.scalar(
        select(LoanFile).where(LoanFile.display_id == resp.json()["display_id"])
    )
    assert created is not None
    assert created.company_id == user.company_id  # NOT other.id


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #


async def test_list_is_scoped_filtered_and_paginated(client: AsyncClient, db: AsyncSession) -> None:
    """List returns only the caller's files; supports status filter + paging."""
    _a, _au, a_token = await _user_and_token(db, slug="company-a", email="a@a.com")
    _b, _bu, b_token = await _user_and_token(db, slug="company-b", email="b@b.com")

    first = await client.post(LOAN_FILES_URL, json={}, headers=_auth(a_token))
    await client.post(LOAN_FILES_URL, json={}, headers=_auth(a_token))
    await client.post(LOAN_FILES_URL, json={}, headers=_auth(b_token))  # B's — must not appear

    # Move one of A's files to in_processing for the status-filter check.
    await client.patch(
        f"{LOAN_FILES_URL}/{first.json()['display_id']}",
        json={"status": "in_processing"},
        headers=_auth(a_token),
    )

    listed = await client.get(LOAN_FILES_URL, headers=_auth(a_token))
    assert listed.status_code == 200
    data = listed.json()
    assert data["total"] == 2  # only A's two files
    assert len(data["items"]) == 2
    assert "inbox_token" not in listed.text

    drafts = await client.get(f"{LOAN_FILES_URL}?status=draft", headers=_auth(a_token))
    assert drafts.json()["total"] == 1

    page = await client.get(f"{LOAN_FILES_URL}?page=1&page_size=1", headers=_auth(a_token))
    page_data = page.json()
    assert page_data["total"] == 2
    assert len(page_data["items"]) == 1


# --------------------------------------------------------------------------- #
# retrieve (UUID + display_id) and cross-tenant 404
# --------------------------------------------------------------------------- #


async def test_retrieve_by_uuid_and_display_id(client: AsyncClient, db: AsyncSession) -> None:
    """GET resolves the file by both its UUID and its display_id."""
    _company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    created = (await client.post(LOAN_FILES_URL, json={}, headers=_auth(token))).json()

    by_id = await client.get(f"{LOAN_FILES_URL}/{created['id']}", headers=_auth(token))
    by_display = await client.get(f"{LOAN_FILES_URL}/{created['display_id']}", headers=_auth(token))
    assert by_id.status_code == 200
    assert by_display.status_code == 200
    assert by_id.json()["id"] == by_display.json()["id"] == created["id"]


async def test_cross_tenant_retrieve_is_404(client: AsyncClient, db: AsyncSession) -> None:
    """Company B cannot retrieve Company A's file — 404 (not 403)."""
    _a, _au, a_token = await _user_and_token(db, slug="company-a", email="a@a.com")
    _b, _bu, b_token = await _user_and_token(db, slug="company-b", email="b@b.com")
    a_file = (await client.post(LOAN_FILES_URL, json={}, headers=_auth(a_token))).json()

    for ident in (a_file["id"], a_file["display_id"]):
        resp = await client.get(f"{LOAN_FILES_URL}/{ident}", headers=_auth(b_token))
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# update
# --------------------------------------------------------------------------- #


async def test_update_changes_mutable_fields_only(client: AsyncClient, db: AsyncSession) -> None:
    """PATCH updates mutable fields; identifiers are unchanged."""
    _company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    created = (await client.post(LOAN_FILES_URL, json={}, headers=_auth(token))).json()

    resp = await client.patch(
        f"{LOAN_FILES_URL}/{created['id']}",
        json={"status": "in_processing", "loan_amount": "450000.00"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "in_processing"
    assert body["loan_amount"] == "450000.00"
    # Identifiers unchanged.
    assert body["id"] == created["id"]
    assert body["display_id"] == created["display_id"]


async def test_cross_tenant_update_is_404(client: AsyncClient, db: AsyncSession) -> None:
    """Company B cannot update Company A's file — 404, and A's file is untouched."""
    _a, _au, a_token = await _user_and_token(db, slug="company-a", email="a@a.com")
    _b, _bu, b_token = await _user_and_token(db, slug="company-b", email="b@b.com")
    a_file = (await client.post(LOAN_FILES_URL, json={}, headers=_auth(a_token))).json()

    resp = await client.patch(
        f"{LOAN_FILES_URL}/{a_file['id']}",
        json={"status": "withdrawn"},
        headers=_auth(b_token),
    )
    assert resp.status_code == 404
    # A still sees it as draft.
    still = await client.get(f"{LOAN_FILES_URL}/{a_file['id']}", headers=_auth(a_token))
    assert still.json()["status"] == "draft"


# --------------------------------------------------------------------------- #
# delete (soft)
# --------------------------------------------------------------------------- #


async def test_delete_soft_deletes_then_404(client: AsyncClient, db: AsyncSession) -> None:
    """DELETE soft-deletes: 204, then the file is gone (404) for the owner."""
    _company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    created = (await client.post(LOAN_FILES_URL, json={}, headers=_auth(token))).json()

    deleted = await client.delete(f"{LOAN_FILES_URL}/{created['id']}", headers=_auth(token))
    assert deleted.status_code == 204

    gone = await client.get(f"{LOAN_FILES_URL}/{created['id']}", headers=_auth(token))
    assert gone.status_code == 404
    listed = await client.get(LOAN_FILES_URL, headers=_auth(token))
    assert listed.json()["total"] == 0


async def test_cross_tenant_delete_is_404(client: AsyncClient, db: AsyncSession) -> None:
    """Company B cannot delete Company A's file — 404, and A's file survives."""
    _a, _au, a_token = await _user_and_token(db, slug="company-a", email="a@a.com")
    _b, _bu, b_token = await _user_and_token(db, slug="company-b", email="b@b.com")
    a_file = (await client.post(LOAN_FILES_URL, json={}, headers=_auth(a_token))).json()

    resp = await client.delete(f"{LOAN_FILES_URL}/{a_file['id']}", headers=_auth(b_token))
    assert resp.status_code == 404
    still = await client.get(f"{LOAN_FILES_URL}/{a_file['id']}", headers=_auth(a_token))
    assert still.status_code == 200


async def test_delete_already_deleted_is_404_not_a_crash(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Deleting an already-soft-deleted file is a clean 404 (graceful), not a 500.

    A soft-deleted file is invisible to its owner (``only_active``), so the second
    DELETE resolves nothing and returns the same 404 as any missing file — idempotent
    in effect, never an error-crash.
    """
    _company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    created = (await client.post(LOAN_FILES_URL, json={}, headers=_auth(token))).json()

    first = await client.delete(f"{LOAN_FILES_URL}/{created['id']}", headers=_auth(token))
    assert first.status_code == 204
    again = await client.delete(f"{LOAN_FILES_URL}/{created['id']}", headers=_auth(token))
    assert again.status_code == 404


# --------------------------------------------------------------------------- #
# secrets never leak; auth required
# --------------------------------------------------------------------------- #


async def test_detail_masks_ssn_and_hides_inbox_token(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Detail exposes masked_ssn only — never raw SSN or inbox_token."""
    _company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    created = (await client.post(LOAN_FILES_URL, json={}, headers=_auth(token))).json()
    loan_file = await db.scalar(select(LoanFile).where(LoanFile.id == created["id"]))
    assert loan_file is not None
    db.add(
        Borrower(
            loan_file_id=loan_file.id,
            first_name="Pat",
            last_name="Buyer",
            ssn="123-45-6789",  # pragma: allowlist secret
            is_primary=True,
            borrower_position=1,
        )
    )
    await db.commit()

    resp = await client.get(f"{LOAN_FILES_URL}/{created['id']}", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["borrowers"][0]["masked_ssn"] == "***-**-6789"
    assert "123-45-6789" not in resp.text  # raw SSN never present
    assert "ssn" not in body["borrowers"][0] or body["borrowers"][0].get("ssn") is None
    assert "inbox_token" not in resp.text


async def test_unauthenticated_requests_are_401(client: AsyncClient, db: AsyncSession) -> None:
    """Every endpoint requires auth — no token → 401."""
    _company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    created = (await client.post(LOAN_FILES_URL, json={}, headers=_auth(token))).json()
    ident = created["id"]

    assert (await client.get(LOAN_FILES_URL)).status_code == 401
    assert (await client.post(LOAN_FILES_URL, json={})).status_code == 401
    assert (await client.get(f"{LOAN_FILES_URL}/{ident}")).status_code == 401
    assert (
        await client.patch(f"{LOAN_FILES_URL}/{ident}", json={"status": "withdrawn"})
    ).status_code == 401
    assert (await client.delete(f"{LOAN_FILES_URL}/{ident}")).status_code == 401


# --------------------------------------------------------------------------- #
# LP-30: creation orchestration + activity logging side-effects
# --------------------------------------------------------------------------- #


async def test_create_generates_needs_list_and_logs_activity(
    client: AsyncClient, db: AsyncSession
) -> None:
    """POST is contract-unchanged, but now also creates needs items + FILE_CREATED.

    Verified via the DB (the side-effects aren't in the response body).
    """
    _company, user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    resp = await client.post(LOAN_FILES_URL, json={"loan_program": "fha"}, headers=_auth(token))
    assert resp.status_code == 201
    file_id = resp.json()["id"]

    needs = (
        (await db.execute(select(NeedsItem).where(NeedsItem.loan_file_id == file_id)))
        .scalars()
        .all()
    )
    assert len(needs) == 5  # universal baseline + FHA placeholder

    created = (
        (
            await db.execute(
                select(ActivityLog).where(
                    ActivityLog.loan_file_id == file_id,
                    ActivityLog.activity_type == ActivityType.FILE_CREATED,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(created) == 1
    assert created[0].actor_user_id == user.id


async def test_patch_status_and_delete_log_activities(
    client: AsyncClient, db: AsyncSession
) -> None:
    """PATCH (status) logs STATUS_CHANGED; DELETE logs FILE_DELETED — with the actor."""
    _company, user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    created = (await client.post(LOAN_FILES_URL, json={}, headers=_auth(token))).json()
    fid = created["id"]

    await client.patch(
        f"{LOAN_FILES_URL}/{fid}", json={"status": "in_processing"}, headers=_auth(token)
    )
    await client.delete(f"{LOAN_FILES_URL}/{fid}", headers=_auth(token))

    types = {
        (a.activity_type, a.actor_user_id)
        for a in (await db.execute(select(ActivityLog).where(ActivityLog.loan_file_id == fid)))
        .scalars()
        .all()
    }
    assert (ActivityType.STATUS_CHANGED, user.id) in types
    assert (ActivityType.FILE_DELETED, user.id) in types


# --------------------------------------------------------------------------- #
# LP-31: list summary extension (lender_name + property_address) + search
# --------------------------------------------------------------------------- #


async def test_list_summary_includes_lender_name_and_property_address(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The list summary resolves lender_name + property_address (None when absent)."""
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    created = (await client.post(LOAN_FILES_URL, json={}, headers=_auth(token))).json()
    loan_file = await db.scalar(select(LoanFile).where(LoanFile.id == created["id"]))
    assert loan_file is not None

    lender = Lender(company_id=company.id, name="Acme Bank", slug="acme-bank")
    db.add(lender)
    await db.flush()
    loan_file.lender_id = lender.id
    db.add(Property(loan_file_id=loan_file.id, address_line="123 Main St"))
    await db.commit()

    item = (await client.get(LOAN_FILES_URL, headers=_auth(token))).json()["items"][0]
    assert item["lender_name"] == "Acme Bank"
    assert item["property_address"] == "123 Main St"


async def test_list_search_filters_by_display_id(client: AsyncClient, db: AsyncSession) -> None:
    """The search query param narrows the list by display_id (company-scoped)."""
    _company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    first = (await client.post(LOAN_FILES_URL, json={}, headers=_auth(token))).json()
    await client.post(LOAN_FILES_URL, json={}, headers=_auth(token))

    resp = await client.get(f"{LOAN_FILES_URL}?search={first['display_id']}", headers=_auth(token))
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["display_id"] == first["display_id"]


# --------------------------------------------------------------------------- #
# blocking: ready-to-submit is gated by open in-scope findings (LP-75)
# --------------------------------------------------------------------------- #


async def test_ready_to_submit_blocked_by_open_finding(
    client: AsyncClient, db: AsyncSession
) -> None:
    """PATCH status→ready_to_submit returns 409 while an open in-scope finding exists."""
    from app.models import Finding, FindingCategory, FindingStatus

    _company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    created = (await client.post(LOAN_FILES_URL, json={}, headers=_auth(token))).json()
    loan_file = await db.scalar(
        select(LoanFile).where(LoanFile.display_id == created["display_id"])
    )
    assert loan_file is not None
    db.add(
        Finding(
            loan_file_id=loan_file.id,
            rule_id="conv.dti.back_end_max",
            confidence=1.0,
            status=FindingStatus.RED,
            category=FindingCategory.INCOME,
            message="DTI exceeds the cap.",
        )
    )
    await db.commit()

    blocked = await client.patch(
        f"{LOAN_FILES_URL}/{created['display_id']}",
        json={"status": "ready_to_submit"},
        headers=_auth(token),
    )
    assert blocked.status_code == 409

    # A non-submit transition is unaffected.
    ok = await client.patch(
        f"{LOAN_FILES_URL}/{created['display_id']}",
        json={"status": "in_processing"},
        headers=_auth(token),
    )
    assert ok.status_code == 200
