"""Endpoint tests for nested borrower CRUD (LP-29).

Drives the app via httpx with ``get_db`` overridden to a commit-safe session
(these endpoints commit; SAVEPOINT join keeps isolation). Focus:

  * **Transitive tenant isolation** — a Company A user cannot touch borrowers on
    a Company B file (the file gate returns ``404`` before any borrower is seen),
    and a borrower from a *different* file under the same company is ``404``.
  * **SSN in-but-masked-out** — ``ssn`` is accepted on create/update and stored
    encrypted at rest (verified via raw SQL); no response ever contains the raw
    SSN, only ``masked_ssn``.
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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

SSN = "123-45-6789"  # pragma: allowlist secret
SSN_DIGITS = "123456789"
MASKED = "***-**-6789"


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


def _borrowers_url(file_ident: str) -> str:
    return f"/api/v1/loan-files/{file_ident}/borrowers"


# --------------------------------------------------------------------------- #
# create + SSN handling
# --------------------------------------------------------------------------- #


async def test_add_borrower_masks_ssn_and_encrypts_at_rest(
    client: AsyncClient, db: AsyncSession
) -> None:
    """POST a borrower with an SSN: 201, masked in the body, encrypted in the DB."""
    company, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await _loan_file(db, company)

    resp = await client.post(
        _borrowers_url(loan_file.display_id),
        json={"first_name": "Pat", "last_name": "Buyer", "ssn": SSN},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["masked_ssn"] == MASKED
    assert body["is_primary"] is True  # first borrower
    assert body["borrower_position"] == 1
    # No raw SSN anywhere in the response.
    assert "ssn" not in body or body.get("ssn") is None
    assert SSN not in resp.text
    assert SSN_DIGITS not in resp.text

    # Encrypted at rest: the raw column is ciphertext, not the SSN.
    raw = await db.scalar(text("SELECT ssn FROM borrowers WHERE id = :id"), {"id": body["id"]})
    assert raw is not None
    assert SSN not in raw
    assert SSN_DIGITS not in raw


async def test_no_response_leaks_raw_ssn(client: AsyncClient, db: AsyncSession) -> None:
    """List / get / update responses expose masked_ssn only — never the raw SSN."""
    company, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await _loan_file(db, company)
    url = _borrowers_url(loan_file.display_id)

    created = (
        await client.post(
            url, json={"first_name": "Pat", "last_name": "Buyer", "ssn": SSN}, headers=_auth(token)
        )
    ).json()
    bid = created["id"]

    listed = await client.get(url, headers=_auth(token))
    got = await client.get(f"{url}/{bid}", headers=_auth(token))
    updated = await client.patch(f"{url}/{bid}", json={"phone": "555-0100"}, headers=_auth(token))

    for resp in (listed, got, updated):
        assert resp.status_code == 200
        assert SSN not in resp.text
        assert SSN_DIGITS not in resp.text
        assert MASKED in resp.text  # masked form is present


# --------------------------------------------------------------------------- #
# list / get / update / delete
# --------------------------------------------------------------------------- #


async def test_list_get_update_delete(client: AsyncClient, db: AsyncSession) -> None:
    """The borrower collection supports list/get/update/soft-delete under the file."""
    company, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await _loan_file(db, company)
    url = _borrowers_url(loan_file.display_id)

    a = (
        await client.post(url, json={"first_name": "A", "last_name": "One"}, headers=_auth(token))
    ).json()
    await client.post(url, json={"first_name": "B", "last_name": "Two"}, headers=_auth(token))

    listed = await client.get(url, headers=_auth(token))
    assert listed.status_code == 200
    assert [b["borrower_position"] for b in listed.json()] == [1, 2]

    got = await client.get(f"{url}/{a['id']}", headers=_auth(token))
    assert got.status_code == 200
    assert got.json()["first_name"] == "A"

    upd = await client.patch(
        f"{url}/{a['id']}", json={"last_name": "Updated"}, headers=_auth(token)
    )
    assert upd.status_code == 200
    assert upd.json()["last_name"] == "Updated"

    deleted = await client.delete(f"{url}/{a['id']}", headers=_auth(token))
    assert deleted.status_code == 204
    gone = await client.get(f"{url}/{a['id']}", headers=_auth(token))
    assert gone.status_code == 404
    assert len((await client.get(url, headers=_auth(token))).json()) == 1


# --------------------------------------------------------------------------- #
# tenant isolation (through the file) + cross-file borrower
# --------------------------------------------------------------------------- #


async def test_cross_tenant_borrowers_are_404_via_the_file_gate(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Company B cannot list/add/get/update/delete borrowers on Company A's file."""
    company_a, a_token = await _user_and_token(db, slug="company-a", email="a@a.com")
    _company_b, b_token = await _user_and_token(db, slug="company-b", email="b@b.com")
    a_file = await _loan_file(db, company_a)
    a_url = _borrowers_url(a_file.display_id)
    borrower = (
        await client.post(
            a_url, json={"first_name": "Pat", "last_name": "Buyer"}, headers=_auth(a_token)
        )
    ).json()

    # Every borrower operation on A's file, as B, is 404 at the file gate.
    assert (await client.get(a_url, headers=_auth(b_token))).status_code == 404
    assert (
        await client.post(a_url, json={"first_name": "X", "last_name": "Y"}, headers=_auth(b_token))
    ).status_code == 404
    assert (
        await client.get(f"{a_url}/{borrower['id']}", headers=_auth(b_token))
    ).status_code == 404
    assert (
        await client.patch(f"{a_url}/{borrower['id']}", json={"phone": "1"}, headers=_auth(b_token))
    ).status_code == 404
    assert (
        await client.delete(f"{a_url}/{borrower['id']}", headers=_auth(b_token))
    ).status_code == 404

    # A's borrower is untouched.
    still = await client.get(f"{a_url}/{borrower['id']}", headers=_auth(a_token))
    assert still.status_code == 200


async def test_borrower_from_a_different_file_is_404(client: AsyncClient, db: AsyncSession) -> None:
    """A borrower id from another file (same company) is 404 under this file."""
    company, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    file1 = await _loan_file(db, company)
    file2 = await _loan_file(db, company)
    borrower = (
        await client.post(
            _borrowers_url(file1.display_id),
            json={"first_name": "Pat", "last_name": "Buyer"},
            headers=_auth(token),
        )
    ).json()

    # Same borrower id, but addressed under file2 → 404 (loan_file_id mismatch).
    resp = await client.get(
        f"{_borrowers_url(file2.display_id)}/{borrower['id']}", headers=_auth(token)
    )
    assert resp.status_code == 404


async def test_unauthenticated_is_401(client: AsyncClient, db: AsyncSession) -> None:
    """Borrower endpoints require auth."""
    company, _token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await _loan_file(db, company)
    url = _borrowers_url(loan_file.display_id)
    assert (await client.get(url)).status_code == 401
    assert (await client.post(url, json={"first_name": "A", "last_name": "B"})).status_code == 401
