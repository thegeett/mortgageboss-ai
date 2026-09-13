"""LP-856 acceptance 1 and 5 — the free draft, at the layer the screen reaches.

WHY AT THE API AND NOT THE SERVICE. `create_compose_draft` has been covered since LP-818 and those
tests still pass; what LP-856 adds is a claim about two things the service cannot see. "It appears in
the list and opens in the same modal" is a statement about `/timeline` and `/messages/{id}`, and a
draft the service wrote correctly can be invisible to both — `get_open_draft` filtering on a
template key is exactly how a title company's request was built and no screen could send it.

NOT A SECOND KIND OF OBJECT. Every assertion below is that the free draft goes down the SAME path,
so a branch added later for "is this a free draft" fails here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest_asyncio
from app.core.database import get_db
from app.main import app
from app.models import Company, LoanProgram, User, UserRole
from app.models.loan_file_participant import LoanFileParticipant
from app.services.loan_files import create_loan_file
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

API = "/api/v1/loan-files"
TYPED = "someone.typed@borrower.example"


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


async def _file_and_token(db: AsyncSession, *, slug: str):
    company, token = await _company_user_token(db, slug=slug)
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await db.commit()
    return loan_file, token


async def _compose(client: AsyncClient, loan_file, token: str, **overrides):
    payload = {
        "recipient": TYPED,
        "subject": "Your file went to underwriting",
        "body": "Hi — your file is with the underwriter now. Nothing needed from you.",
    } | overrides
    return await client.post(
        f"{API}/{loan_file.display_id}/messages", json=payload, headers=_auth(token)
    )


async def test_a_composed_draft_appears_in_the_list_and_opens_in_the_same_modal(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Acceptance 1, both halves, through the two endpoints the screen actually calls."""
    loan_file, token = await _file_and_token(db, slug="compose")

    created = await _compose(client, loan_file, token)
    assert created.status_code == 201, created.text
    draft_id = created.json()["id"]

    timeline = await client.get(f"{API}/{loan_file.display_id}/timeline", headers=_auth(token))
    assert timeline.status_code == 200
    rows = timeline.json()["entries"]
    assert [row["id"] for row in rows] == [draft_id]
    # THE SAME ROW SHAPE as every other draft — the list renders one component, and a free draft
    # missing `kind` or carrying a different one would be the second kind of object the ticket
    # forbids rather than a row that happens to ask for nothing.
    assert rows[0]["kind"] == "message"
    assert rows[0]["status"] == "draft"

    detail = await client.get(
        f"{API}/{loan_file.display_id}/messages/{draft_id}", headers=_auth(token)
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    # OPENS IN THE SAME MODAL means editable and sendable, not merely readable. A draft the modal
    # renders read-only is one a processor cannot send, and nothing on the list would say why.
    assert body["is_editable"] is True
    # `is_open_draft` IS FALSE HERE, AND THAT IS CORRECT. It has meant one specific thing since
    # LP-829 — the BORROWER's document-request draft, under `DRAFT_TEMPLATE` — and a free draft has
    # no template at all. `is_editable` is the wider flag LP-831 added precisely because the narrow
    # one was being asked a question it does not answer, and it is the one the modal reads: measured
    # — `is_open_draft` appears nowhere in the frontend outside the type declaration. Asserted so
    # that widening it later, or gating the modal on it, fails here.
    assert body["is_open_draft"] is False
    # ZERO NEEDS — "What it asks for" is empty, which is the whole point of the free draft.
    assert body["documents"] == []
    assert body["counterparty"] == TYPED
    # THE BODY IS THE PROCESSOR'S OWN WORDS, VERBATIM — no template wrapped them. `custom.v1` is a
    # real, fingerprinted template carrying the secure-channel notice every other outbound message
    # gets, and `create_compose_draft` has bypassed it since LP-818 by storing `template_key=None`.
    # Asserted as it stands rather than fixed here: routing compose through the renderer would
    # change an endpoint LP-818 shipped, which is scope this ticket does not claim. Recorded in
    # `docs/tickets/LP-856.md` under "Not done".
    assert body["body"] == ("Hi — your file is with the underwriter now. Nothing needed from you.")
    assert "not a fully secure channel" not in body["body"]
    assert body["template_key"] is None


async def test_a_typed_recipient_is_not_written_back_to_the_files_parties(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Acceptance 5. An address typed for ONE message is not a fact about the file.

    A compose that quietly added a participant would put that address on every future party request
    for the role it guessed, and the processor who typed it once would have no idea where it came
    from.
    """
    loan_file, token = await _file_and_token(db, slug="noparty")
    before = (
        (
            await db.execute(
                select(LoanFileParticipant).where(LoanFileParticipant.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    # THE POSITIVE CONTROL FOR THE COUNT. A file with participants already on it would make "still
    # zero" say nothing; this states the starting point instead of assuming it.
    assert len(before) == 0

    assert (await _compose(client, loan_file, token)).status_code == 201

    after = (
        (
            await db.execute(
                select(LoanFileParticipant).where(LoanFileParticipant.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert [p.email for p in after] == []


async def test_a_composed_draft_can_be_polished_like_any_other(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The ✦ button is not a free-draft feature — the route takes this draft too.

    With `email_draft_enabled` off it refuses, which is the ordinary answer today; what this asserts
    is that the refusal comes from the MODEL being unavailable and not from the endpoint rejecting a
    draft with no template key.
    """
    loan_file, token = await _file_and_token(db, slug="polishfree")
    draft_id = (await _compose(client, loan_file, token)).json()["id"]

    resp = await client.post(
        f"{API}/{loan_file.display_id}/outbound/draft/{draft_id}/polish",
        json={"body": "hi there could you send that thing over"},
        headers=_auth(token),
    )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"polished": None, "refusal": "unavailable"}
