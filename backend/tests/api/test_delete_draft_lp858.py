"""LP-858 §7 and §8 — deleting a draft, and the two deletes that are not the same operation.

THE ROUTE THAT WAS SPECIFIED AND NEVER BUILT. `comm-v1-draft-only-spec.md` §6 listed `[Delete]` as
the quiet fourth button and `message-dialog.tsx` carried a comment describing that exact button row.
The comment shipped; the button did not, and neither did the endpoint. That is the failure mode this
ticket's design file exists to stop — *"prose can be satisfied by restating it"* — so every case here
is a behaviour rather than a description.

WHAT MATTERS MOST IS WHAT DELETE DOES **NOT** DO. *"Keep it simple, do not un-request."* The needs
items, the finding markers and `details.docs_requested` are left exactly as they are, and
`_clear_finding_markers` is not called. The consequence is recorded and accepted: the originating
finding keeps its request button greyed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest_asyncio
from app.core.database import get_db
from app.documents.catalog import ResponsibleParty
from app.main import app
from app.models import Borrower, Company, LoanProgram, User, UserRole
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.communication_needs_item import CommunicationNeedsItem
from app.models.needs_item import NeedsItem, NeedsItemOrigin, NeedsItemStatus
from app.services.email_draft import _needs_in_draft, compose_request
from app.services.email_reply import create_compose_draft
from app.services.loan_files import create_loan_file
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
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
    return company, user, create_access_token(user.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _file_with_a_generated_draft(db: AsyncSession, *, slug: str):
    """A borrower draft carrying one needs item, the way a request makes one."""
    company, user, token = await _company_user_token(db, slug=slug)
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    db.add(Borrower(loan_file_id=loan_file.id, first_name="Akash", last_name="Shah"))
    db.add(
        NeedsItem(
            loan_file_id=loan_file.id,
            title="Most recent pay stub",
            needs_type="pay_stub",
            origin=NeedsItemOrigin.FINDING,
            status=NeedsItemStatus.PENDING,
        )
    )
    await db.flush()
    composed = await compose_request(
        db, loan_file=loan_file, document_types=["pay_stub"], actor_user_id=user.id
    )
    borrower = [p for p in composed.update.parties if p.party is ResponsibleParty.BORROWER]
    assert len(borrower) == 1, "the fixture's document stopped routing to the borrower"
    draft = borrower[0].draft
    assert draft is not None
    await db.commit()
    return loan_file, user, token, draft


def _delete(client: AsyncClient, loan_file, draft_id, token: str, *, discard: bool = False):
    url = f"{API}/{loan_file.display_id}/outbound/draft/{draft_id}"
    return client.delete(url, params={"discard": "true"} if discard else None, headers=_auth(token))


# --- §7 — the processor's delete ------------------------------------------------------------- #


async def test_deleting_a_draft_sets_deleted_at_and_keeps_the_row(
    client: AsyncClient, db: AsyncSession
) -> None:
    """SOFT, per house convention. A processor wrote this, or asked for it to be written."""
    loan_file, _user, token, draft = await _file_with_a_generated_draft(db, slug="softdel")

    resp = await _delete(client, loan_file, draft.id, token)

    assert resp.status_code == 204, resp.text
    row = await db.get(Communication, draft.id)
    assert row is not None, "the row was removed; this is the SOFT delete"
    assert row.deleted_at is not None
    # AND IT LEAVES THE LIST, which is the half a `deleted_at` nobody filters on would fail.
    listed = await client.get(f"{API}/{loan_file.display_id}/timeline", headers=_auth(token))
    assert [e["id"] for e in listed.json()["entries"]] == []


async def test_deleting_a_draft_leaves_its_needs_and_finding_markers_untouched(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE DECISION, ASSERTED. *"No keep it simple, do not un-request."*

    `_clear_finding_markers` exists, was written for the bounce path, and matches on
    `requested_needs_item_id` — so reusing it here would have been one line and is exactly what this
    forbids. Deleting a draft is not a statement about whether the documents are still needed.
    """
    loan_file, _user, token, draft = await _file_with_a_generated_draft(db, slug="norequest")
    needs_before = (
        (await db.execute(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file.id)))
        .scalars()
        .all()
    )
    # THE FIXTURE HAS SOMETHING TO LOSE. Without this, "unchanged" passes on a file with no needs.
    # COUNTED RATHER THAN PINNED: `compose_request` adds its own needs item for the document type as
    # well as the one seeded here, and a hard-coded 1 would be a number about the fixture rather
    # than about the property.
    assert len(needs_before) >= 1
    linked_before = (
        (
            await db.execute(
                select(CommunicationNeedsItem).where(
                    CommunicationNeedsItem.communication_id == draft.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(linked_before) >= 1, "the draft must actually carry a needs link"
    statuses_before = {n.id: (n.status, n.requested_at) for n in needs_before}

    assert (await _delete(client, loan_file, draft.id, token)).status_code == 204

    needs_after = (
        (await db.execute(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file.id)))
        .scalars()
        .all()
    )
    for need in needs_after:
        await db.refresh(need)
    assert {n.id: (n.status, n.requested_at) for n in needs_after} == statuses_before
    # AND THE MEMBERSHIP ROW SURVIVES: it is the record that the document was asked for, and the
    # draft it names is soft-deleted rather than gone.
    linked_after = (
        (
            await db.execute(
                select(CommunicationNeedsItem).where(
                    CommunicationNeedsItem.communication_id == draft.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(linked_after) == len(linked_before)


async def test_a_sent_message_cannot_be_deleted(client: AsyncClient, db: AsyncSession) -> None:
    """LP-821's record is what actually went out. Removing it is a different request, and one this
    version does not offer — a processor tidying their list must not be able to delete evidence."""
    loan_file, _user, token, draft = await _file_with_a_generated_draft(db, slug="sentdel")
    draft.status = CommunicationStatus.SENT
    await db.commit()

    resp = await _delete(client, loan_file, draft.id, token)

    assert resp.status_code == 409
    assert "sent" in resp.text
    row = await db.get(Communication, draft.id)
    assert row is not None and row.deleted_at is None


async def test_another_files_draft_cannot_be_deleted(client: AsyncClient, db: AsyncSession) -> None:
    """The route proves the caller owns the FILE; the draft id is a path parameter anybody can type.
    The same refusal as one that does not exist, so the two are indistinguishable."""
    _mine, _user, my_token, _draft = await _file_with_a_generated_draft(db, slug="mine")
    theirs, _u2, _t2, their_draft = await _file_with_a_generated_draft(db, slug="theirs")

    resp = await _delete(client, theirs, their_draft.id, my_token)

    # Scoped by the FILE in the path, which my token does not own — so the file resolves to a 404
    # before the draft is ever looked at.
    assert resp.status_code == 404
    row = await db.get(Communication, their_draft.id)
    assert row is not None and row.deleted_at is None


async def test_the_processor_is_not_blocked_after_deleting(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE CLAIM THE "do not un-request" DECISION RESTS ON, and it was asserted in prose and never
    run — by either of us.

    Delete leaves the needs items and the finding marker alone, which means the originating
    finding's button stays greyed. The reason that is acceptable is that **requesting again still
    works**: the catalog path is a different route and does not consult the marker. If that were
    false, deleting a draft would strand the document — asked for, no message, and no way to ask
    again — and the decision would have been wrong rather than simple.

    IT COMPOSES BECAUSE `get_open_draft` READS THROUGH `only_active`. The deleted draft is invisible
    to it, so its needs are not counted as "already in a draft" and the new request carries them.
    """
    loan_file, user, token, draft = await _file_with_a_generated_draft(db, slug="notblocked")
    assert (await _delete(client, loan_file, draft.id, token)).status_code == 204

    # THE SAME DOCUMENT, REQUESTED AGAIN, through the path the catalog dialog uses.
    composed = await compose_request(
        db, loan_file=loan_file, document_types=["pay_stub"], actor_user_id=user.id
    )
    borrower = next(p for p in composed.update.parties if p.party is ResponsibleParty.BORROWER)
    fresh = borrower.draft

    assert fresh is not None, "requesting again after a delete produced no draft"
    assert fresh.id != draft.id, "it reused the deleted draft rather than making a new one"
    assert fresh.deleted_at is None
    # AND IT CARRIES THE DOCUMENT, which is the whole point — a new draft with nothing in it would
    # satisfy every assertion above and leave the processor exactly as stranded.
    titles = [n.title for n in await _needs_in_draft(db, draft=fresh)]
    assert titles, "the new draft asks for nothing"


# --- LP-859 §3 — the same predicate, asked by the timeline ------------------------------------ #


async def test_a_blank_compose_draft_says_nothing_is_written_yet(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-859 §3 — the row said the opposite of the pane beside it.

    `_summarise` returned "A document request is being prepared" for EVERY draft, so a compose draft
    with no template, no recipient, no subject, no body and nothing linked described itself as a
    document request — while the right pane correctly read "New message · To nobody yet". Screenshot
    `03-compose-row-wrong-summary.png`.

    ONE PREDICATE, NOT TWO. `draft_row_is_blank` is `_is_untouched_compose_draft`'s row half, shared
    rather than restated; the needs half comes from the batch the timeline already loads.
    """
    company, user, token = await _company_user_token(db, slug="blankrow")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    draft = await create_compose_draft(db, loan_file=loan_file, actor_user_id=user.id)
    await db.commit()

    row = next(
        e
        for e in (
            await client.get(f"{API}/{loan_file.display_id}/timeline", headers=_auth(token))
        ).json()["entries"]
        if e["id"] == str(draft.id)
    )

    assert row["summary"] == "Nothing written yet"
    assert row["nothing_written"] is True


async def test_it_stops_saying_so_the_moment_a_recipient_is_typed(
    client: AsyncClient, db: AsyncSession
) -> None:
    """§3's done-when: *"it changes the moment anything is typed into it."*

    THE CONTROL on the case above — "Nothing written yet" would otherwise be satisfied by a build
    that says it about every draft, which is the defect with different words.
    """
    company, user, token = await _company_user_token(db, slug="typedrow")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    draft = await create_compose_draft(
        db, loan_file=loan_file, recipient="jane@borrower.example", actor_user_id=user.id
    )
    await db.commit()

    row = next(
        e
        for e in (
            await client.get(f"{API}/{loan_file.display_id}/timeline", headers=_auth(token))
        ).json()["entries"]
        if e["id"] == str(draft.id)
    )

    assert row["summary"] == "A document request is being prepared"
    assert row["nothing_written"] is False


async def test_a_generated_request_still_describes_itself_as_one(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE CASE THAT MUST NOT CHANGE. A request carries a template key and needs links, so neither
    half of the predicate holds — and a build that summarised everything as "Nothing written yet"
    would pass the first test and break every row a processor actually reads."""
    loan_file, _user, token, draft = await _file_with_a_generated_draft(db, slug="genrow")

    row = next(
        e
        for e in (
            await client.get(f"{API}/{loan_file.display_id}/timeline", headers=_auth(token))
        ).json()["entries"]
        if e["id"] == str(draft.id)
    )

    assert row["summary"] == "A document request is being prepared"
    assert row["nothing_written"] is False
    # AND THE ROW STILL NAMES WHAT IS INSIDE, which is the sub-line LP-852 added and the thing that
    # makes "prepared" specific rather than four identical rows.
    assert row["documents"], "the fixture's draft carries no documents"


# --- §8 — the untouched compose draft -------------------------------------------------------- #


async def test_closing_an_untouched_compose_draft_removes_the_row_entirely(
    client: AsyncClient, db: AsyncSession
) -> None:
    """HARD. Nothing was ever written, so a `deleted_at` row would be litter with a timestamp."""
    company, user, token = await _company_user_token(db, slug="discard")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    draft = await create_compose_draft(db, loan_file=loan_file, actor_user_id=user.id)
    await db.commit()

    resp = await _delete(client, loan_file, draft.id, token, discard=True)

    assert resp.status_code == 204, resp.text
    assert await db.get(Communication, draft.id) is None


async def test_a_compose_draft_with_only_a_recipient_survives_close(
    client: AsyncClient, db: AsyncSession
) -> None:
    """§8 — *"A processor who typed a recipient and stopped has done work; do not destroy it."*

    AND THE SERVER DECIDES, NOT THE CLIENT. "No modification" is a claim about a browser session;
    a hard delete acting on that claim is how a half-written message disappears because a comparison
    somewhere was wrong about whitespace. The row is re-derived here, so a client that asks wrongly
    gets a refusal rather than data loss.
    """
    company, user, token = await _company_user_token(db, slug="typedto")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    draft = await create_compose_draft(
        db, loan_file=loan_file, recipient="jane@borrower.example", actor_user_id=user.id
    )
    await db.commit()

    resp = await _delete(client, loan_file, draft.id, token, discard=True)

    assert resp.status_code == 409
    assert "content" in resp.text
    assert await db.get(Communication, draft.id) is not None


async def test_a_generated_draft_with_no_needs_left_still_cannot_be_discarded(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE CASE THAT SEPARATES THE TWO GUARDS, and it was found by mutation rather than by reading.

    `_is_untouched_compose_draft` refuses on a template key AND on a needs link. On every fixture
    above those agree, so deleting the template-key check left every test green — a guard no
    mutation could find, which is the definition of decoration rather than protection.

    They part company on a draft that was RENDERED FROM A TEMPLATE and carries no needs links. That
    is not a compose draft however empty it looks: hard-deleting it removes the record that a
    request was ever prepared, and `deleted_at` is exactly what that case is for.
    """
    company, user, token = await _company_user_token(db, slug="templnoneeds")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    # Built directly rather than through `compose_request`, because the point is the combination
    # that path does not produce: a template key with nothing linked to it.
    draft = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.DRAFT,
        template_key="initial_documentation_request",
        template_version="v4",
        body="",
        initiated_by_user_id=user.id,
    )
    db.add(draft)
    await db.flush()
    await db.commit()
    # THE FIXTURE REALLY IS EMPTY AND UNLINKED, so the refusal below can only come from the
    # template key.
    linked = await db.execute(
        select(CommunicationNeedsItem).where(CommunicationNeedsItem.communication_id == draft.id)
    )
    assert linked.scalars().all() == []

    resp = await _delete(client, loan_file, draft.id, token, discard=True)

    assert resp.status_code == 409
    assert await db.get(Communication, draft.id) is not None


async def test_a_generated_draft_can_never_be_discarded(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A TEMPLATE KEY DISQUALIFIES IT whatever the text says. A request a processor emptied is still
    a request: its `communication_needs_items` rows are the record that the document was asked for,
    and a hard delete would take them with it."""
    loan_file, _user, token, draft = await _file_with_a_generated_draft(db, slug="notdiscard")
    draft.body = ""
    draft.subject = None
    draft.recipient = None
    await db.commit()

    resp = await _delete(client, loan_file, draft.id, token, discard=True)

    assert resp.status_code == 409
    assert await db.get(Communication, draft.id) is not None
    # AND THE SOFT DELETE IS STILL AVAILABLE — refusing the destructive option is not refusing the
    # request. This is the fallback the client takes.
    assert (await _delete(client, loan_file, draft.id, token)).status_code == 204


async def test_a_compose_draft_with_a_body_survives_close(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-858 REVIEW — THE GUARD THIS WHOLE ASYMMETRY EXISTS FOR, AND NOTHING ASSERTED IT.

    `_is_untouched_compose_draft` refuses a hard delete on four counts. Three of them had a case;
    the body did not. Measured by mutation: deleting the body check from the guard left the delete
    suite green, and left 2,141 tests across `tests/api` and `tests/services` green with it.

    That is the one the docstring is written about — *"a hard delete acting on a claim is how a
    processor's half-written message disappears because a comparison somewhere was wrong about
    whitespace"*. A client that miscomputes "no modification" on a draft somebody has TYPED INTO is
    exactly the failure the server-side re-derivation is there to stop, and it was the one shape the
    tests did not cover: the recipient case above proves the asymmetry works, this proves it works
    for the field that holds the words.
    """
    company, user, token = await _company_user_token(db, slug="typedbody")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    draft = await create_compose_draft(
        db, loan_file=loan_file, body="Half a sentence I was still", actor_user_id=user.id
    )
    await db.commit()

    resp = await _delete(client, loan_file, draft.id, token, discard=True)

    assert resp.status_code == 409
    assert "content" in resp.text
    survived = await db.get(Communication, draft.id)
    assert survived is not None
    assert survived.deleted_at is None, "a refused discard must not fall through to a soft delete"
    assert survived.body == "Half a sentence I was still"


async def test_an_arrived_message_cannot_be_deleted(client: AsyncClient, db: AsyncSession) -> None:
    """LP-858 REVIEW — the route's direction guard, also unasserted.

    Deleting it from `delete_draft` left the same 2,141 tests green. It is reachable: the route takes
    an id and `_scoped` resolves any communication on the file, so a caller passing an INBOUND id
    reaches the guard. A borrower's own words are not ours to remove, which is the same rule
    `save_draft_body` applies one ticket earlier — an inbound message is not ours to rewrite either.
    """
    company, user, token = await _company_user_token(db, slug="inbound")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    arrived = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.INBOUND,
        status=CommunicationStatus.RECEIVED,
        subject="Here are my statements",
        body="Attached.",
        initiated_by_user_id=user.id,
    )
    db.add(arrived)
    await db.commit()

    resp = await _delete(client, loan_file, arrived.id, token)

    assert resp.status_code == 409
    assert "arrived" in resp.text.lower()
    still_there = await db.get(Communication, arrived.id)
    assert still_there is not None and still_there.deleted_at is None
