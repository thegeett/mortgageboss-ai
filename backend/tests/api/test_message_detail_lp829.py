"""LP-829 — clicking a message on the timeline opens it.

WHAT DID NOT EXIST. Nothing in the product could show a processor the text of a message already
sent. `MessagePublic` says "Never the body — the caller already has what they typed", which is right
for a write response, so a sent document request was unreadable from the moment it was recorded.

The two things worth protecting are the ones that fail quietly: a message from another company
answering with anything other than a 404, and the dialog rendering a raw stored body — which would
put `Hello $borrower_first_name,` back on screen in a third place, one ticket after LP-823 took it
off the other two.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest_asyncio
from app.core.database import get_db
from app.main import app
from app.models import Borrower, Company, LoanProgram, User, UserRole
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.needs_item import NeedsItem, NeedsItemOrigin
from app.services.email_draft import add_needs_to_draft
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


async def _company_user_token(db: AsyncSession, *, slug: str, first: str = "Dana"):
    from app.core.jwt import create_access_token

    company = Company(name=slug, slug=f"{slug}-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u-{uuid4().hex[:6]}@{slug}.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name=first,
        last_name="Reyes",
        role=UserRole.PROCESSOR,
    )
    db.add(user)
    await db.flush()
    return company, create_access_token(user.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _file_with_draft(db: AsyncSession, company, *, borrower: str = "Sarah"):
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    db.add(
        Borrower(
            loan_file_id=loan_file.id,
            first_name=borrower,
            last_name="Borrower",
            email="sarah@example.com",
            is_primary=True,
            borrower_position=1,
        )
    )
    need = NeedsItem(
        loan_file_id=loan_file.id,
        title="Bank statements",
        needs_type="bank_statement",
        origin=NeedsItemOrigin.FINDING,
    )
    db.add(need)
    await db.flush()
    from app.models.user import User as U
    from sqlalchemy import select

    actor = (await db.execute(select(U).where(U.company_id == company.id))).scalars().first()
    assert actor is not None
    result = await add_needs_to_draft(db, loan_file=loan_file, needs=[need], actor_user_id=actor.id)
    return loan_file, result.draft


async def test_a_message_reads_back_in_full(client: AsyncClient, db: AsyncSession) -> None:
    """The body is the point. Before this endpoint the only message a processor could read was the
    file's ONE open draft, through a different route that returns no id."""
    company, token = await _company_user_token(db, slug="acme")
    loan_file, draft = await _file_with_draft(db, company)
    await db.commit()

    resp = await client.get(
        f"{API}/{loan_file.display_id}/messages/{draft.id}", headers=_auth(token)
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["id"] == str(draft.id)
    assert payload["direction"] == "outbound"
    assert payload["body"].strip()
    assert payload["documents"] == ["Bank statements"]
    assert payload["is_open_draft"] is True


async def test_the_open_draft_resolves_its_placeholders(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-823 IN A THIRD PLACE. The stored draft keeps `$borrower_first_name` and `$processor_name`
    so the send decides who signs; every screen that RENDERS it has to resolve them, or this dialog
    reintroduces the defect one ticket after it was fixed on the panel and in the send."""
    company, token = await _company_user_token(db, slug="acme", first="Dana")
    loan_file, draft = await _file_with_draft(db, company, borrower="Sarah")
    await db.commit()

    body = (
        await client.get(f"{API}/{loan_file.display_id}/messages/{draft.id}", headers=_auth(token))
    ).json()["body"]

    assert "$borrower_first_name" not in body
    assert "$processor_name" not in body
    # POSITIVE CONTROLS: absence alone passes on an empty body and on one whose placeholders were
    # deleted rather than resolved.
    assert "Hello Sarah," in body
    assert "Dana Reyes" in body


async def test_an_inbound_body_is_returned_exactly_as_written(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE ASYMMETRY THAT MATTERS, and the reason the resolution is not applied uniformly.

    A borrower who writes `$processor_name` in their email must get it back unchanged. Substituting
    there would rewrite what somebody wrote to us, which is the one thing a record of their message
    must never do — and it would look exactly like the fix working.
    """
    company, token = await _company_user_token(db, slug="acme")
    loan_file, _draft = await _file_with_draft(db, company)
    inbound = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.INBOUND,
        status=CommunicationStatus.RECEIVED,
        subject="Re: documents",
        body="Who is $processor_name? I paid $10,000 in earnest money.",
    )
    db.add(inbound)
    await db.flush()
    await db.commit()

    body = (
        await client.get(
            f"{API}/{loan_file.display_id}/messages/{inbound.id}", headers=_auth(token)
        )
    ).json()["body"]

    assert body == "Who is $processor_name? I paid $10,000 in earnest money."


async def test_a_sent_message_is_readable_after_the_fact(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The state this endpoint exists for. A sent message's words were visible NOWHERE — not on the
    timeline, which carries a summary, and not through the draft route, which returns the OPEN one."""
    company, token = await _company_user_token(db, slug="acme")
    loan_file, _draft = await _file_with_draft(db, company)
    sent = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.SENT,
        recipient="sarah@example.com",
        subject="Documents we need",
        body="Hello Sarah,\n\nPlease send the bank statements.\n\nDana Reyes",
    )
    db.add(sent)
    await db.flush()
    await db.commit()

    payload = (
        await client.get(f"{API}/{loan_file.display_id}/messages/{sent.id}", headers=_auth(token))
    ).json()

    assert "Please send the bank statements." in payload["body"]
    assert payload["counterparty"] == "sarah@example.com"
    assert payload["is_open_draft"] is False


async def test_another_companys_message_is_a_404(client: AsyncClient, db: AsyncSession) -> None:
    """A message id that belongs to another company must be INDISTINGUISHABLE from one that does not
    exist. Any other answer lets a caller enumerate what another tenant has, one id at a time."""
    company_a, _token_a = await _company_user_token(db, slug="acme")
    _company_b, token_b = await _company_user_token(db, slug="other")
    loan_file_a, draft_a = await _file_with_draft(db, company_a)
    await db.commit()

    resp = await client.get(
        f"{API}/{loan_file_a.display_id}/messages/{draft_a.id}", headers=_auth(token_b)
    )

    assert resp.status_code == 404


async def test_a_message_on_a_sibling_file_is_a_404(client: AsyncClient, db: AsyncSession) -> None:
    """SAME COMPANY, TWO FILES — the axis a company-scoped check would pass while showing one
    borrower's mail under another borrower's file. The id is not the address; the file is."""
    company, token = await _company_user_token(db, slug="acme")
    _mine, _draft = await _file_with_draft(db, company)
    theirs, their_draft = await _file_with_draft(db, company)
    await db.commit()

    resp = await client.get(
        f"{API}/{_mine.display_id}/messages/{their_draft.id}", headers=_auth(token)
    )

    assert resp.status_code == 404
    # THE CONTROL: the same message under its OWN file is a 200, so the 404 above is about scoping
    # and not about the endpoint refusing everything.
    assert (
        await client.get(
            f"{API}/{theirs.display_id}/messages/{their_draft.id}", headers=_auth(token)
        )
    ).status_code == 200


async def test_a_soft_deleted_message_is_gone(client: AsyncClient, db: AsyncSession) -> None:
    """`db.get` does not know about soft deletion, so this is checked on the row. Without it a
    message a processor deleted would still be readable by id."""
    from app.models.base import utcnow

    company, token = await _company_user_token(db, slug="acme")
    loan_file, draft = await _file_with_draft(db, company)
    draft.deleted_at = utcnow()
    await db.flush()
    await db.commit()

    resp = await client.get(
        f"{API}/{loan_file.display_id}/messages/{draft.id}", headers=_auth(token)
    )

    assert resp.status_code == 404
