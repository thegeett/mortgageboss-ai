"""LP-811a at the layer a processor clicks — the send endpoint and its refusals.

The service tests cover the rules. These cover what a caller can actually reach: the tenant gate, the
409s, and the fact that one file's draft cannot be sent under another file's address even though the
draft id is a path parameter anyone can type.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest_asyncio
from app.core.database import get_db
from app.main import app
from app.models import Company, LoanProgram, User, UserRole
from app.models.needs_item import NeedsItem, NeedsItemOrigin, NeedsItemStatus
from app.services.email_draft import add_needs_to_draft
from app.services.loan_files import create_loan_file
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

API = "/api/v1/loan-files"


# The endpoint COMMITS, so the plain rollback `db_session` fixture will not do: a committed
# transaction cannot be rolled back around it. Same shape as `test_verification_endpoints.py` —
# a savepoint-joining session shared with the app, so the route's commit lands on a savepoint and
# the outer transaction still rolls back.
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
        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http_client:
            yield http_client
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _company_user_token(db: AsyncSession, *, slug: str, email: str):
    from app.core.jwt import create_access_token

    company = Company(name=slug, slug=f"{slug}-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=email,
        hashed_password="x",  # pragma: allowlist secret
        first_name="Pat",
        last_name="Processor",
        role=UserRole.PROCESSOR,
    )
    db.add(user)
    await db.flush()
    return company, user, create_access_token(user.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _file_with_draft(db: AsyncSession, company, user):
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    need = NeedsItem(
        loan_file_id=loan_file.id,
        title="Bank statements",
        needs_type="bank_statement",
        origin=NeedsItemOrigin.FINDING,
    )
    db.add(need)
    await db.flush()
    result = await add_needs_to_draft(db, loan_file=loan_file, needs=[need], actor_user_id=user.id)
    return loan_file, need, result.draft


async def test_the_draft_reads_back_as_a_message(client: AsyncClient, db: AsyncSession) -> None:
    company, user, token = await _company_user_token(db, slug="acme", email="u@acme.com")
    loan_file, _need, draft = await _file_with_draft(db, company, user)
    await db.commit()

    resp = await client.get(f"{API}/{loan_file.display_id}/outbound/draft", headers=_auth(token))

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["id"] == str(draft.id)
    assert payload["reply_to"] == loan_file.get_inbox_address()
    assert payload["suggested_bcc"] == loan_file.get_inbox_address()
    assert f"[{loan_file.display_id}]" in payload["body"]
    assert payload["needs_item_count"] == 1
    assert payload["mailto_available"] is True


async def test_a_file_with_no_draft_is_a_404(client: AsyncClient, db: AsyncSession) -> None:
    company, _user, token = await _company_user_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await db.commit()

    resp = await client.get(f"{API}/{loan_file.display_id}/outbound/draft", headers=_auth(token))
    assert resp.status_code == 404


async def test_sending_records_it_and_starts_the_clock(
    client: AsyncClient, db: AsyncSession
) -> None:
    company, user, token = await _company_user_token(db, slug="acme", email="u@acme.com")
    loan_file, need, draft = await _file_with_draft(db, company, user)
    await db.commit()

    resp = await client.post(
        f"{API}/{loan_file.display_id}/outbound/draft/{draft.id}/send",
        headers=_auth(token),
        json={"recipient": "borrower@example.com", "body": "Please send these when you can."},
    )

    assert resp.status_code == 200
    assert resp.json()["needs_items_requested"] == 1
    await db.refresh(need)
    assert need.status is NeedsItemStatus.REQUESTED
    assert need.requested_at is not None


async def test_sending_the_same_draft_twice_is_a_409(client: AsyncClient, db: AsyncSession) -> None:
    company, user, token = await _company_user_token(db, slug="acme", email="u@acme.com")
    loan_file, _need, draft = await _file_with_draft(db, company, user)
    await db.commit()
    url = f"{API}/{loan_file.display_id}/outbound/draft/{draft.id}/send"
    body = {"recipient": "borrower@example.com", "body": "Once."}

    assert (await client.post(url, headers=_auth(token), json=body)).status_code == 200
    second = await client.post(url, headers=_auth(token), json=body)

    assert second.status_code == 409
    # The app renders HTTPException through its own error envelope, so the message is not at
    # `detail`. Asserted on the whole payload rather than guessing the key: what matters is that the
    # refusal SAYS why, and a 409 with an opaque body would read as a bug to whoever hit it.
    assert "already sent" in second.text


async def test_another_companys_file_is_not_reachable(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The tenant gate, on the route rather than in the service. `ScopedLoanFile` 404s before any of
    this module's code runs — asserted here because the draft id is a path parameter, so a caller who
    guessed one would otherwise be relying on the service check alone."""
    theirs, their_user, _their_token = await _company_user_token(
        db, slug="theirs", email="a@theirs.com"
    )
    loan_file, _need, draft = await _file_with_draft(db, theirs, their_user)
    _mine, _my_user, my_token = await _company_user_token(db, slug="mine", email="b@mine.com")
    await db.commit()

    resp = await client.post(
        f"{API}/{loan_file.display_id}/outbound/draft/{draft.id}/send",
        headers=_auth(my_token),
        json={"recipient": "borrower@example.com", "body": "Not mine."},
    )
    assert resp.status_code == 404


async def test_an_empty_body_is_rejected_before_it_reaches_the_service(
    client: AsyncClient, db: AsyncSession
) -> None:
    """422 from the schema, not 409 from the service. An empty send is a malformed request, and the
    distinction matters because a 409 reads as "the state is wrong" when the payload is."""
    company, user, token = await _company_user_token(db, slug="acme", email="u@acme.com")
    loan_file, _need, draft = await _file_with_draft(db, company, user)
    await db.commit()

    resp = await client.post(
        f"{API}/{loan_file.display_id}/outbound/draft/{draft.id}/send",
        headers=_auth(token),
        json={"recipient": "borrower@example.com", "body": ""},
    )
    assert resp.status_code == 422
