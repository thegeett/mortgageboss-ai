"""LP-857 — the version does not offer what it cannot do.

ACCEPTANCE 2, 3 AND 5 at the layer the screen reaches, plus the flag they share.

WHAT MAKES THIS ONE FILE. `receiving_enabled` decides two things that a processor and a borrower see
in different places: whether the Communication page offers the upload and inbound panels, and
whether a generated request PROMISES a borrower an upload link. Two flags with two names could hide
the panel and keep the promise, which is the failure this ticket removes rather than a new place to
introduce it — so the fact is one setting, served by one endpoint, and asserted here together.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from app.communications.templates import SECURITY_CAUTION, SECURITY_NOTICE
from app.core.config import settings
from app.core.database import get_db
from app.documents.catalog import ResponsibleParty
from app.main import app
from app.models import Borrower, Company, LoanProgram, User, UserRole
from app.models.loan_file_participant import ParticipantRole
from app.models.needs_item import NeedsItem, NeedsItemOrigin, NeedsItemStatus
from app.services.email_draft import compose_request
from app.services.loan_files import create_loan_file
from app.services.party_requests import add_participant
from app.services.upload_links import list_links, mint_upload_link
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

API = "/api/v1/loan-files"
# The same clean PDF LP-815's own cases use. A handful of bytes that merely START with %PDF is
# refused by `assess`, which is the safety gate doing its job and would make this test pass for the
# wrong reason — a 400 that looks like the flag refusing the upload.
_PDF = (Path(__file__).resolve().parents[1] / "fixtures" / "attachments" / "clean.pdf").read_bytes()


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


def _draft_for(composed, party: ResponsibleParty):
    """The one party's draft, named rather than indexed.

    `parties[0]` is whatever `by_party` iterated first, which is insertion order over the needs —
    a test that indexed it would silently start asserting about the title company's email the day a
    fixture gained a second document.
    """
    matches = [p for p in composed.update.parties if p.party is party]
    assert len(matches) == 1, (
        f"{party} is not in this request: {[p.party for p in composed.update.parties]}"
    )
    draft = matches[0].draft
    assert draft is not None, f"{party} got no draft"
    return draft


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _file_needing_a_title_document(db: AsyncSession, company: Company):
    """A file with one outstanding TITLE need and no title address."""
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    db.add(Borrower(loan_file_id=loan_file.id, first_name="Akash", last_name="Shah"))
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
    return loan_file


# --- The flag itself ------------------------------------------------------------------------- #


async def test_the_version_says_it_cannot_receive(client: AsyncClient, db: AsyncSession) -> None:
    """ACCEPTANCE 4's server half. The page asks; the default answer is no."""
    _company, _user, token = await _company_user_token(db, slug="cap")
    await db.commit()

    resp = await client.get("/api/v1/capabilities", headers=_auth(token))

    assert resp.status_code == 200
    assert resp.json() == {"receiving": False}
    # THE DEFAULT IS THE PRODUCT, not a test convenience. Every other assertion in this file is
    # about the off state, so if the default flipped they would all be describing a configuration
    # nobody runs.
    assert settings.receiving_enabled is False, "the default changed; this file's premise is gone"


async def test_capabilities_needs_a_caller(client: AsyncClient, db: AsyncSession) -> None:
    """Nothing here is secret, but an unauthenticated route is a surface with no reason to exist."""
    await db.commit()
    assert (await client.get("/api/v1/capabilities")).status_code in (401, 403)


async def test_the_flag_is_reported_as_it_is_set(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE POSITIVE CONTROL for the endpoint. `{"receiving": False}` is what a route returning a
    hardcoded false would say, and what one reading a setting it never looks at again would say."""
    _company, _user, token = await _company_user_token(db, slug="capon")
    await db.commit()
    monkeypatch.setattr(settings, "receiving_enabled", True)

    assert (await client.get("/api/v1/capabilities", headers=_auth(token))).json() == {
        "receiving": True
    }


# --- Acceptance 5: the body does not promise what the version cannot do --------------------- #


async def test_a_generated_request_does_not_offer_an_upload_link(
    client: AsyncClient, db: AsyncSession
) -> None:
    """ACCEPTANCE 5, at the words a borrower reads.

    LP-824's argument was that a caution needs a route that exists — it rewrote v1's "reply and tell
    us and we will arrange another route" precisely because it named nothing anybody could act on.
    With receiving off there IS no route, so the offer becomes the same kind of empty promise one
    ticket later, and in a borrower's inbox rather than on a processor's screen.
    """
    company, user, _token = await _company_user_token(db, slug="nolink")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    db.add(Borrower(loan_file_id=loan_file.id, first_name="Akash", last_name="Shah"))
    db.add(
        NeedsItem(
            loan_file_id=loan_file.id,
            # `pay_stub`, NOT `bank_statements`. The catalog routes bank statements to the
            # PROCESSOR ("we order it ourselves"), which is never a draft — a fixture using one
            # would assert about a party that is not in the request.
            title="Most recent pay stub",
            needs_type="pay_stub",
            origin=NeedsItemOrigin.FINDING,
            status=NeedsItemStatus.PENDING,
        )
    )
    await db.flush()

    composed = await compose_request(
        db,
        loan_file=loan_file,
        document_types=["pay_stub"],
        actor_user_id=user.id,
    )
    draft = _draft_for(composed, ResponsibleParty.BORROWER)
    body = draft.body or ""

    # THE CAUTION STAYS. It is true whether or not anything can be received, and dropping it would
    # be a different and worse change than the one this ticket makes.
    assert SECURITY_CAUTION in body
    # THE OFFER GOES, and so does every other way of naming the thing.
    assert SECURITY_NOTICE not in body
    assert "upload" not in body.lower()
    assert "http" not in body


async def test_with_receiving_on_the_offer_comes_back(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE POSITIVE CONTROL. "upload is not mentioned" passes against a template that never
    mentioned it, against a render that failed, and against a body that came back empty."""
    company, user, _token = await _company_user_token(db, slug="linkon")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    db.add(Borrower(loan_file_id=loan_file.id, first_name="Akash", last_name="Shah"))
    db.add(
        NeedsItem(
            loan_file_id=loan_file.id,
            # `pay_stub`, NOT `bank_statements`. The catalog routes bank statements to the
            # PROCESSOR ("we order it ourselves"), which is never a draft — a fixture using one
            # would assert about a party that is not in the request.
            title="Most recent pay stub",
            needs_type="pay_stub",
            origin=NeedsItemOrigin.FINDING,
            status=NeedsItemStatus.PENDING,
        )
    )
    await db.flush()
    monkeypatch.setattr(settings, "receiving_enabled", True)

    composed = await compose_request(
        db,
        loan_file=loan_file,
        document_types=["pay_stub"],
        actor_user_id=user.id,
    )
    assert SECURITY_NOTICE in (_draft_for(composed, ResponsibleParty.BORROWER).body or "")


async def test_a_link_cannot_be_minted_into_a_draft(client: AsyncClient, db: AsyncSession) -> None:
    """ACCEPTANCE 5, THE OTHER WAY IN. The template stops naming an upload link, and this is the
    call that would put a live one in a body anyway — one click, on a version where nothing can
    receive through it. Refused on the server, not only hidden on the client: a hidden button is a
    claim about the only caller we happen to know about.
    """
    company, user, token = await _company_user_token(db, slug="nomint")
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
    draft = _draft_for(composed, ResponsibleParty.BORROWER)
    await db.commit()

    resp = await client.post(
        f"{API}/{loan_file.display_id}/messages/{draft.id}/upload-link", headers=_auth(token)
    )

    assert resp.status_code == 409, resp.text
    assert "cannot receive uploads" in resp.text
    # AND THE BODY IS UNTOUCHED. A refusal that had already rewritten the draft would be worse than
    # the thing it refused.
    await db.refresh(draft)
    assert "/upload/" not in (draft.body or "")


async def test_a_link_can_be_minted_when_the_version_can_receive(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE POSITIVE CONTROL. A 409 also comes back from a draft that is not editable, from a
    message id that does not exist, and from a route that was never reachable."""
    company, user, token = await _company_user_token(db, slug="canmint")
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
    monkeypatch.setattr(settings, "receiving_enabled", True)
    composed = await compose_request(
        db, loan_file=loan_file, document_types=["pay_stub"], actor_user_id=user.id
    )
    draft = _draft_for(composed, ResponsibleParty.BORROWER)
    await db.commit()

    resp = await client.post(
        f"{API}/{loan_file.display_id}/messages/{draft.id}/upload-link", headers=_auth(token)
    )

    assert resp.status_code == 200, resp.text
    assert "/upload/" in resp.json()["body"]


async def test_the_file_level_mint_is_refused_too(client: AsyncClient, db: AsyncSession) -> None:
    """LP-857 REVIEW — THE SAME ACT THROUGH THE OTHER DOOR.

    `POST /messages/{id}/upload-link` was refused because a refusal living only in a hidden button
    is a claim about the only caller we happen to know about. That argument does not distinguish
    between the two mints: both create a live route into a loan file for a borrower, and they differ
    only in where the URL ends up. Gating one and not the other would have left the fence wherever
    somebody's attention happened to fall.
    """
    company, _user, token = await _company_user_token(db, slug="filemint")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await db.commit()

    resp = await client.post(
        f"{API}/{loan_file.display_id}/upload-links", json={}, headers=_auth(token)
    )

    assert resp.status_code == 409, resp.text
    assert "cannot receive uploads" in resp.text
    # NOTHING WAS WRITTEN. A refusal that had already minted the row would leave a live token behind
    # the sentence saying none could exist.
    assert await list_links(db, loan_file=loan_file) == []


async def test_the_file_level_mint_works_when_the_version_can_receive(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE POSITIVE CONTROL. A 409 also comes back from a file that does not exist and from a route
    that was never reachable."""
    company, _user, token = await _company_user_token(db, slug="filemint2")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await db.commit()
    monkeypatch.setattr(settings, "receiving_enabled", True)

    resp = await client.post(
        f"{API}/{loan_file.display_id}/upload-links", json={}, headers=_auth(token)
    )

    assert resp.status_code == 201, resp.text
    assert "/upload/" in resp.json()["url"]


async def test_a_token_already_in_a_borrowers_hands_still_redeems(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE BOUNDARY, ASSERTED DELIBERATELY — this is a decision, not a gap.

    REFUSING A CREATION COSTS NOBODY ANYTHING. REFUSING A REDEMPTION DESTROYS A DOCUMENT. A token
    holder was told by us to upload; a refusal on the way in loses the file they just chose and
    gives them no way to know whether to try again. With both mints gated the set of live tokens can
    only shrink, so the hole closes on its own.

    Written as a test rather than a comment because "we chose not to gate this" and "we forgot to
    gate this" look identical in a diff, and the next person to read the flag's name will assume the
    second.
    """
    company, _user, _token = await _company_user_token(db, slug="redeems")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    # MINTED AS IT WOULD HAVE BEEN BEFORE THE FLAG — through the service, because the route now
    # refuses. That is exactly the population this test is about.
    monkeypatch.setattr(settings, "receiving_enabled", True)
    minted = await mint_upload_link(db, loan_file=loan_file)
    await db.commit()
    monkeypatch.setattr(settings, "receiving_enabled", False)

    url_token = minted.url.rsplit("/", 1)[-1]
    described = await client.get(f"/api/v1/upload/{url_token}")
    accepted = await client.post(
        f"/api/v1/upload/{url_token}",
        files={"file": ("statement.pdf", _PDF, "application/pdf")},
    )

    assert described.status_code == 200, described.text
    assert accepted.status_code == 201, accepted.text
    assert accepted.json() == {"status": "received"}


# --- Acceptance 2 and 3: the address is asked where it blocks --------------------------------- #


async def test_a_title_request_with_no_address_still_becomes_a_draft(
    client: AsyncClient, db: AsyncSession
) -> None:
    """ACCEPTANCE 2's server half: a draft, unaddressed, and it knows whose it is.

    LP-841 already keeps the draft — "the message is the part a processor wants". What LP-857 adds
    is that the modal can now tell WHY the box is empty and WHO an address would belong to. Before
    this, `party` was absent from the payload and `suggested_recipient` was null on every party
    draft, so the screen had nothing to say.
    """
    company, user, token = await _company_user_token(db, slug="notitle")
    loan_file = await _file_needing_a_title_document(db, company)

    composed = await compose_request(
        db,
        loan_file=loan_file,
        document_types=["title_commitment"],
        actor_user_id=user.id,
    )
    await db.commit()
    title = [p for p in composed.update.parties if p.party is ResponsibleParty.TITLE]
    assert len(title) == 1, "the fixture's document does not route to the title company any more"
    draft = title[0].draft
    assert draft is not None

    resp = await client.get(
        f"{API}/{loan_file.display_id}/messages/{draft.id}", headers=_auth(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    # CANNOT BE SENT YET, which the list reads off this: no address, and nothing suggested because
    # the file holds none.
    assert body["counterparty"] is None
    assert body["suggested_recipient"] is None
    # AND WHOSE DRAFT IT IS, which is what the address form needs and cannot derive: five parties
    # share `document_request_third_party`.
    assert body["party"] == "title"
    assert body["is_editable"] is True


async def test_saving_the_address_makes_the_draft_sendable_without_re_requesting(
    client: AsyncClient, db: AsyncSession
) -> None:
    """ACCEPTANCE 3, and it must survive a reload.

    A modal that only filled its own "Send to" box would satisfy the sentence and lose the address
    the moment the processor closed it — the form says "Saved to the file — used for every future
    message to this party", which is a claim about the FILE, not about this dialog's state.
    """
    company, user, token = await _company_user_token(db, slug="addr")
    loan_file = await _file_needing_a_title_document(db, company)
    composed = await compose_request(
        db, loan_file=loan_file, document_types=["title_commitment"], actor_user_id=user.id
    )
    draft = _draft_for(composed, ResponsibleParty.TITLE)
    await db.commit()

    saved = await client.post(
        f"{API}/{loan_file.display_id}/party-requests/addresses",
        json={"role": "title", "email": "closings@acmetitle.example", "name": "Acme Title"},
        headers=_auth(token),
    )
    assert saved.status_code == 201, saved.text

    # THE SAME DRAFT, RE-READ. Not a new request, not a rebuild — reopening the one that was
    # already there is what "without re-requesting the document" means.
    reread = await client.get(
        f"{API}/{loan_file.display_id}/messages/{draft.id}", headers=_auth(token)
    )
    assert reread.json()["suggested_recipient"] == "closings@acmetitle.example"


async def test_the_borrower_is_never_suggested_on_a_party_draft(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The rule the old narrow condition was protecting, kept.

    Suggesting the borrower's address on a title draft would put a third party's document request in
    the borrower's inbox — and a file almost always HAS a borrower address, so a resolution that
    fell back to "whoever we know about" would do it on every unaddressed party draft.
    """
    company, user, token = await _company_user_token(db, slug="noborrow")
    loan_file = await _file_needing_a_title_document(db, company)
    borrower = Borrower(
        loan_file_id=loan_file.id,
        first_name="Jane",
        last_name="Borrower",
        email="jane@borrower.example",
        is_primary=True,
    )
    db.add(borrower)
    await db.flush()
    composed = await compose_request(
        db, loan_file=loan_file, document_types=["title_commitment"], actor_user_id=user.id
    )
    draft = _draft_for(composed, ResponsibleParty.TITLE)
    await db.commit()

    body = (
        await client.get(f"{API}/{loan_file.display_id}/messages/{draft.id}", headers=_auth(token))
    ).json()

    # THE FIXTURE HAS AN ADDRESS TO LEAK. Without this the assertion below passes on a file where
    # there was nothing to suggest in the first place.
    assert borrower.email == "jane@borrower.example"
    assert body["suggested_recipient"] is None


async def test_an_address_recorded_before_the_request_is_suggested_too(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE POSITIVE CONTROL for the two nulls above: the resolution works, so "None" means "none on
    file" rather than "this code path is dead"."""
    company, user, token = await _company_user_token(db, slug="hadaddr")
    loan_file = await _file_needing_a_title_document(db, company)
    await add_participant(
        db, loan_file=loan_file, role=ParticipantRole.TITLE, email="known@title.example"
    )
    composed = await compose_request(
        db, loan_file=loan_file, document_types=["title_commitment"], actor_user_id=user.id
    )
    draft = _draft_for(composed, ResponsibleParty.TITLE)
    await db.commit()

    body = (
        await client.get(f"{API}/{loan_file.display_id}/messages/{draft.id}", headers=_auth(token))
    ).json()

    # Addressed at creation, so `counterparty` carries it and there is nothing to suggest — which is
    # the branch the LP-831 comment describes and this ticket did not change.
    assert body["counterparty"] == "known@title.example"
    assert body["party"] == "title"
