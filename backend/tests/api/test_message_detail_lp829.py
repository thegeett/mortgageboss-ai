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


async def test_a_party_request_resolves_its_placeholders_too(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-829 REVIEW — LP-823's DEFECT IN THE THIRD PLACE, which is what this module exists to stop.

    Resolution was gated on `is_open_draft`, which additionally requires the BORROWER template key.
    `party_requests` renders the SAME template for title, agent, lender, CPA, insurer and employer,
    each under its own key, so a party request fell through to the raw stored body. And
    `build_timeline` selects every Communication on the file with no template filter, so those
    drafts are on the timeline and clickable.

    Measured before the fix: opening one showed "Hello $borrower_first_name," signed
    "$processor_name" — the exact words a processor reported on the panel in LP-823.

    The greeting resolves to the generic form rather than the borrower's name, which is LP-823's
    review fix doing its job one layer down: this message is addressed to the title company, and
    Akash's name has no business in it. Both halves are asserted — no placeholder survives, and the
    borrower is not named — because either alone passes on the other being wrong.
    """
    from app.documents.catalog import ResponsibleParty
    from app.models.loan_file_participant import ParticipantRole
    from app.models.needs_item import NeedsItemStatus
    from app.services.party_requests import add_participant, build_party_draft

    company, token = await _company_user_token(db, slug="party")
    loan_file, _draft = await _file_with_draft(db, company, borrower="Akash")
    db.add(
        NeedsItem(
            loan_file_id=loan_file.id,
            title="Title commitment",
            needs_type="title_commitment",
            origin=NeedsItemOrigin.FINDING,
            status=NeedsItemStatus.PENDING,
        )
    )
    await db.flush()
    await add_participant(
        db, loan_file=loan_file, role=ParticipantRole.TITLE, email="t@title.example"
    )
    from app.models.user import User as U
    from sqlalchemy import select as _select

    actor = (await db.execute(_select(U).where(U.company_id == company.id))).scalars().first()
    assert actor is not None
    party = await build_party_draft(
        db, loan_file=loan_file, party=ResponsibleParty.TITLE, actor_user_id=actor.id
    )
    assert "$borrower_first_name" in (party.body or ""), (
        "the fixture must actually store a placeholder, or this test asserts nothing"
    )
    await db.commit()

    resp = await client.get(
        f"{API}/{loan_file.display_id}/messages/{party.id}", headers=_auth(token)
    )
    assert resp.status_code == 200
    body = resp.json()["body"]

    assert "$borrower_first_name" not in body
    assert "$processor_name" not in body
    assert "Akash" not in body, (
        "the borrower's name went into a message addressed to the title company"
    )
    assert "Hello there," in body
    # `is_open_draft` still means what it says: the panel above is NOT editing this one.
    assert resp.json()["is_open_draft"] is False


# --------------------------------------------------------------------------------------------- #
# LP-831 — the modal is the editor, and a party draft is reachable through it
# --------------------------------------------------------------------------------------------- #
async def test_a_borrower_draft_is_editable_and_suggests_the_borrower(
    client: AsyncClient, db: AsyncSession
) -> None:
    company, token = await _company_user_token(db, slug="acme")
    loan_file, draft = await _file_with_draft(db, company)
    await db.commit()

    payload = (
        await client.get(f"{API}/{loan_file.display_id}/messages/{draft.id}", headers=_auth(token))
    ).json()

    assert payload["is_editable"] is True
    assert payload["suggested_recipient"] == "sarah@example.com"


async def test_a_sent_message_is_not_editable(client: AsyncClient, db: AsyncSession) -> None:
    """LP-821 — the evidence record must not change after the fact. The flag comes from the server so
    the screen and the send path cannot disagree about what may be edited."""
    company, token = await _company_user_token(db, slug="acme")
    loan_file, draft = await _file_with_draft(db, company)
    draft.status = CommunicationStatus.SENT
    await db.flush()
    await db.commit()

    payload = (
        await client.get(f"{API}/{loan_file.display_id}/messages/{draft.id}", headers=_auth(token))
    ).json()

    assert payload["is_editable"] is False
    assert payload["suggested_recipient"] is None


async def test_a_party_draft_is_editable_and_keeps_its_own_address(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE ESCALATED LP-820 DEFECT, at the layer that closes it.

    A party request is a draft under its OWN template key. `get_open_draft` filters on the borrower's,
    so the outbound panel never returned one — while the party panel's success message said "Send it
    from the document request above", where the draft above is the borrower's. A processor following
    that instruction mailed the BORROWER believing they had contacted the title company.

    `send_draft` takes a draft id and has never cared which template rendered it, so the missing piece
    was a screen. `is_editable` therefore must NOT be `is_open_draft`, which is the narrower flag.

    And the address must stay the party's: suggesting the borrower's here would put a title company's
    document request in the borrower's inbox, which is the same wrong mailbox by a shorter route.
    """
    company, token = await _company_user_token(db, slug="acme")
    loan_file, _borrower_draft = await _file_with_draft(db, company)
    party = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.DRAFT,
        template_key="title_document_request",
        recipient="t@title.example",
        subject="Documents we need",
        body="Hello $borrower_first_name,\n\nPlease send the title commitment.\n\n$processor_name",
    )
    db.add(party)
    await db.flush()
    await db.commit()

    payload = (
        await client.get(f"{API}/{loan_file.display_id}/messages/{party.id}", headers=_auth(token))
    ).json()

    assert payload["is_editable"] is True
    assert payload["is_open_draft"] is False, "the narrow flag must stay narrow"
    assert payload["suggested_recipient"] is None
    # LP-829's review fix, still holding: a party draft resolves to the generic greeting, never to
    # the borrower's first name.
    assert "$borrower_first_name" not in payload["body"]
    assert "Sarah" not in payload["body"]


async def test_the_modal_can_send_a_party_draft(client: AsyncClient, db: AsyncSession) -> None:
    """The other half of the same defect: reachable is not the same as sendable."""
    company, token = await _company_user_token(db, slug="acme")
    loan_file, _borrower_draft = await _file_with_draft(db, company)
    party = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.DRAFT,
        template_key="title_document_request",
        recipient="t@title.example",
        subject="Documents we need",
        body="Hello there,\n\nPlease send the title commitment.\n\nPat Processor",
    )
    db.add(party)
    await db.flush()
    await db.commit()

    resp = await client.post(
        f"{API}/{loan_file.display_id}/outbound/draft/{party.id}/send",
        headers=_auth(token),
        json={
            "recipient": "t@title.example",
            "subject": "Title commitment, please",
            "body": "Hello there,\n\nPlease send the title commitment.\n\nPat Processor",
        },
    )

    assert resp.status_code == 200
    sent = await db.get(Communication, party.id)
    assert sent is not None
    assert sent.status is CommunicationStatus.SENT
    assert sent.recipient == "t@title.example"
    # LP-831 — the subject the processor actually sent, not the one the template rendered.
    assert sent.subject == "Title commitment, please"


async def test_an_omitted_subject_keeps_the_stored_one(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE CONTROL ON THE SUBJECT BEING OPTIONAL. `body` refuses to default because a stale draft
    recorded as sent is a false evidence row; a subject has no such gap, and a caller that omits it
    is saying "the one already on the draft" — which must actually be what gets recorded."""
    company, token = await _company_user_token(db, slug="acme")
    loan_file, draft = await _file_with_draft(db, company)
    await db.commit()
    stored_subject = draft.subject

    resp = await client.post(
        f"{API}/{loan_file.display_id}/outbound/draft/{draft.id}/send",
        headers=_auth(token),
        json={"recipient": "sarah@example.com", "body": "Please send the bank statements."},
    )

    assert resp.status_code == 200
    sent = await db.get(Communication, draft.id)
    assert sent is not None
    assert sent.subject == stored_subject
