"""LP-812 at the layer the screen reaches — the filter, the address, and the tenant gate."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest_asyncio
from app.core.database import get_db
from app.main import app
from app.models import Company, LoanProgram, User, UserRole
from app.models.activity_log import ActivityType
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.services.activity_log import log_activity
from app.services.loan_files import create_loan_file
from httpx import AsyncClient
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
        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http_client:
            yield http_client
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _company_user_token(db: AsyncSession, *, slug: str):
    from app.core.jwt import create_access_token

    company = Company(name=slug, slug=f"{slug}-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u-{uuid4().hex[:6]}@{slug}.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name="Pat",
        last_name="Processor",
        role=UserRole.PROCESSOR,
    )
    db.add(user)
    await db.flush()
    return company, create_access_token(user.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _history(db: AsyncSession, loan_file) -> None:
    db.add(
        Communication(
            loan_file_id=loan_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationStatus.SENT,
            recipient="jane@borrower.example",
            subject="Please send these",
        )
    )
    db.add(
        Communication(
            loan_file_id=loan_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationStatus.DRAFT,
            template_key="document_request",
        )
    )
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.DOCUMENT_UPLOADED,
        summary="A document was uploaded",
    )
    await db.flush()


async def test_the_timeline_reads_back(client: AsyncClient, db: AsyncSession) -> None:
    company, token = await _company_user_token(db, slug="acme")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await _history(db, loan_file)
    await db.commit()

    resp = await client.get(f"{API}/{loan_file.display_id}/timeline", headers=_auth(token))

    assert resp.status_code == 200
    assert len(resp.json()["entries"]) == 3
    # Spec 4.3 asks for the address on this screen; ADR-397's accessor is what produces it.
    assert resp.json()["inbox_address"] == loan_file.get_inbox_address()


async def test_the_filter_is_a_server_parameter(client: AsyncClient, db: AsyncSession) -> None:
    """A "sent" pill that showed drafts would tell a processor they had already asked for something
    they had not. The definition lives on the server so there is only one of it."""
    company, token = await _company_user_token(db, slug="filtered")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await _history(db, loan_file)
    await db.commit()

    sent = await client.get(
        f"{API}/{loan_file.display_id}/timeline", params={"filter": "sent"}, headers=_auth(token)
    )
    drafts = await client.get(
        f"{API}/{loan_file.display_id}/timeline", params={"filter": "drafts"}, headers=_auth(token)
    )

    assert [row["status"] for row in sent.json()["entries"]] == ["sent"]
    assert [row["status"] for row in drafts.json()["entries"]] == ["draft"]


async def test_an_unknown_filter_is_refused(client: AsyncClient, db: AsyncSession) -> None:
    """422, NOT a silent fallback to `all`. A pill whose name changed would otherwise show
    everything and read as "this filter matches everything", which is a wrong answer rather than an
    error."""
    company, token = await _company_user_token(db, slug="badfilter")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await db.commit()

    resp = await client.get(
        f"{API}/{loan_file.display_id}/timeline",
        params={"filter": "everything"},
        headers=_auth(token),
    )

    assert resp.status_code == 422


async def test_another_companys_file_is_a_404(client: AsyncClient, db: AsyncSession) -> None:
    theirs, _their_token = await _company_user_token(db, slug="theirs")
    _mine, my_token = await _company_user_token(db, slug="mine")
    their_file = await create_loan_file(
        db, company_id=theirs.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await _history(db, their_file)
    await db.commit()

    resp = await client.get(f"{API}/{their_file.display_id}/timeline", headers=_auth(my_token))

    assert resp.status_code == 404


async def test_no_message_body_reaches_the_response(client: AsyncClient, db: AsyncSession) -> None:
    """A timeline is a list anybody scrolls past. The body would make it the fullest copy of a
    borrower's prose in the product — asserted against a message that HAS one."""
    company, token = await _company_user_token(db, slug="nobody")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    db.add(
        Communication(
            loan_file_id=loan_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationStatus.SENT,
            subject="Your documents",
            body="Dear Jane, your account ending 4821 needs a statement.",
        )
    )
    await db.commit()

    resp = await client.get(f"{API}/{loan_file.display_id}/timeline", headers=_auth(token))

    assert "4821" not in resp.text
    assert "Dear Jane" not in resp.text
    assert resp.json()["entries"][0]["subject"] == "Your documents"
