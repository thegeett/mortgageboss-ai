"""LP-823 — the draft resolves what the file already knows, at the layer a processor reads it.

REPORTED FROM STAGING, and worse than it was reported. The screen showed `$borrower_first_name` and
`$processor_name`, which reads as a preview problem. It is not: there is no send button, so the
message leaves through "Copy message" or "Open in mail client", and both take the text the screen is
showing. `finalise_draft_body` — the function that resolves them — had NO CALLER anywhere in `app/`.
Every document request this system produced went to the borrower reading `Hello $borrower_first_name,`
and signed `$processor_name`.

The tests below are at the endpoint for that reason: the API response IS the text that gets copied.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest_asyncio
from app.core.database import get_db
from app.main import app
from app.models import Borrower, Company, LoanProgram, User, UserRole
from app.models.communication import Communication
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


async def _company_user_token(db: AsyncSession, *, first: str = "Pat", last: str = "Processor"):
    from app.core.jwt import create_access_token

    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u-{uuid4().hex[:6]}@acme.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name=first,
        last_name=last,
        role=UserRole.PROCESSOR,
    )
    db.add(user)
    await db.flush()
    return company, user, create_access_token(user.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _borrower(db, loan_file, *, first: str, email: str | None, primary: bool, position: int):
    borrower = Borrower(
        loan_file_id=loan_file.id,
        first_name=first,
        last_name="Borrower",
        email=email,
        is_primary=primary,
        borrower_position=position,
    )
    db.add(borrower)
    await db.flush()
    return borrower


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
    return loan_file, result.draft


# --------------------------------------------------------------------------------------------- #
# The defect itself
# --------------------------------------------------------------------------------------------- #
async def test_the_draft_a_processor_copies_has_no_placeholders(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE ONE THAT WAS BROKEN. This body is what "Copy message" puts on the clipboard and what
    "Open in mail client" puts in the compose window. A `$` in it is not a preview artifact — it is
    what the borrower reads."""
    company, user, token = await _company_user_token(db, first="Dana", last="Reyes")
    loan_file, _draft = await _file_with_draft(db, company, user)
    await _borrower(
        db, loan_file, first="Sarah", email="sarah@example.com", primary=True, position=1
    )
    await db.commit()

    body = (
        await client.get(f"{API}/{loan_file.display_id}/outbound/draft", headers=_auth(token))
    ).json()["body"]

    assert "$borrower_first_name" not in body
    assert "$processor_name" not in body
    # POSITIVE CONTROLS. Asserting only the absence would pass on an empty body, and pass on a body
    # whose placeholders were deleted rather than resolved.
    assert "Hello Sarah," in body
    assert "Dana Reyes" in body


async def test_the_stored_draft_keeps_its_placeholders(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE HALF THAT MUST NOT MOVE. Resolving on the way IN would look identical on every screen and
    would sign the email with whoever clicked "request" — not whoever sends it days later. The
    deferral is the point; only the rendering of it changed."""
    company, user, token = await _company_user_token(db)
    loan_file, draft = await _file_with_draft(db, company, user)
    await _borrower(
        db, loan_file, first="Sarah", email="sarah@example.com", primary=True, position=1
    )
    await db.commit()

    await client.get(f"{API}/{loan_file.display_id}/outbound/draft", headers=_auth(token))

    stored = await db.get(Communication, draft.id)
    assert stored is not None
    assert "$borrower_first_name" in (stored.body or "")
    assert "$processor_name" in (stored.body or "")


async def test_two_processors_each_see_their_own_name(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The reason the placeholder is kept, asserted rather than described. One stored draft, two
    readers, two signatures — which a body resolved at composition time could not produce."""
    company, user_a, token_a = await _company_user_token(db, first="Dana", last="Reyes")
    loan_file, _draft = await _file_with_draft(db, company, user_a)
    await _borrower(db, loan_file, first="Sarah", email="s@example.com", primary=True, position=1)

    from app.core.jwt import create_access_token

    user_b = User(
        company_id=company.id,
        email=f"b-{uuid4().hex[:6]}@acme.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name="Marco",
        last_name="Silva",
        role=UserRole.PROCESSOR,
    )
    db.add(user_b)
    await db.flush()
    token_b = create_access_token(user_b.id)
    await db.commit()

    url = f"{API}/{loan_file.display_id}/outbound/draft"
    body_a = (await client.get(url, headers=_auth(token_a))).json()["body"]
    body_b = (await client.get(url, headers=_auth(token_b))).json()["body"]

    assert "Dana Reyes" in body_a and "Marco Silva" not in body_a
    assert "Marco Silva" in body_b and "Dana Reyes" not in body_b


# --------------------------------------------------------------------------------------------- #
# The recipient
# --------------------------------------------------------------------------------------------- #
async def test_the_borrowers_address_is_suggested(client: AsyncClient, db: AsyncSession) -> None:
    company, user, token = await _company_user_token(db)
    loan_file, _draft = await _file_with_draft(db, company, user)
    await _borrower(
        db, loan_file, first="Sarah", email="sarah@example.com", primary=True, position=1
    )
    await db.commit()

    payload = (
        await client.get(f"{API}/{loan_file.display_id}/outbound/draft", headers=_auth(token))
    ).json()

    assert payload["suggested_recipient"] == "sarah@example.com"


async def test_a_borrower_with_no_email_suggests_nothing(
    client: AsyncClient, db: AsyncSession
) -> None:
    """`borrowers.email` is nullable, so this file is ordinary rather than broken. The box must be
    empty — a suggestion that is not an address is worse than no suggestion."""
    company, user, token = await _company_user_token(db)
    loan_file, _draft = await _file_with_draft(db, company, user)
    await _borrower(db, loan_file, first="Sarah", email=None, primary=True, position=1)
    await db.commit()

    payload = (
        await client.get(f"{API}/{loan_file.display_id}/outbound/draft", headers=_auth(token))
    ).json()

    assert payload["suggested_recipient"] is None
    # The NAME still resolves. The two facts are independent, and a file missing an address must not
    # lose its greeting as well.
    assert "Hello Sarah," in payload["body"]


async def test_the_primary_borrower_wins_over_position(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Two borrowers, and the answer decides which mailbox a document request goes to. `is_primary`
    first — asserted with the primary at the LATER position, so an implementation ordering only on
    position gets it wrong rather than accidentally right."""
    company, user, token = await _company_user_token(db)
    loan_file, _draft = await _file_with_draft(db, company, user)
    await _borrower(
        db, loan_file, first="Alex", email="alex@example.com", primary=False, position=1
    )
    await _borrower(
        db, loan_file, first="Sarah", email="sarah@example.com", primary=True, position=2
    )
    await db.commit()

    payload = (
        await client.get(f"{API}/{loan_file.display_id}/outbound/draft", headers=_auth(token))
    ).json()

    assert payload["suggested_recipient"] == "sarah@example.com"
    assert "Hello Sarah," in payload["body"]


async def test_with_no_primary_flagged_the_first_position_answers(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A file whose primary was soft-deleted has no flagged borrower. The next one on the file is
    the answer, not nobody — `_primary_borrower_name` returns None here, which is right for a
    display name and wrong for choosing who to write to."""
    company, user, token = await _company_user_token(db)
    loan_file, _draft = await _file_with_draft(db, company, user)
    await _borrower(
        db, loan_file, first="Sarah", email="sarah@example.com", primary=False, position=2
    )
    await _borrower(
        db, loan_file, first="Alex", email="alex@example.com", primary=False, position=1
    )
    await db.commit()

    payload = (
        await client.get(f"{API}/{loan_file.display_id}/outbound/draft", headers=_auth(token))
    ).json()

    assert payload["suggested_recipient"] == "alex@example.com"


async def test_a_file_with_no_borrower_still_renders(client: AsyncClient, db: AsyncSession) -> None:
    """No borrower, no address, and still no `$` in the words. The fallback greeting is ordinary
    English; leaving the placeholder would put it one copy-and-paste from a stranger's inbox."""
    company, user, token = await _company_user_token(db)
    loan_file, _draft = await _file_with_draft(db, company, user)
    await db.commit()

    payload = (
        await client.get(f"{API}/{loan_file.display_id}/outbound/draft", headers=_auth(token))
    ).json()

    assert payload["suggested_recipient"] is None
    assert "$borrower_first_name" not in payload["body"]
    assert "Hello there," in payload["body"]


# --------------------------------------------------------------------------------------------- #
# The send path, which is a separate guard and not a duplicate of the above
# --------------------------------------------------------------------------------------------- #
async def test_sending_the_stored_body_still_resolves_it(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE PATH THAT IS NOT THE PANEL. The panel posts text it read from the endpoint, so it is
    already resolved and `send_draft`'s pass is a no-op there. This posts the STORED body — what a
    script, a retry, or a future route would send — and the recorded message must still be the words
    a borrower can read.

    Recorded, not just displayed: `draft.body` after a send is the evidence record of what went out,
    and once a transport exists it is what actually leaves.
    """
    company, user, token = await _company_user_token(db, first="Dana", last="Reyes")
    loan_file, draft = await _file_with_draft(db, company, user)
    await _borrower(
        db, loan_file, first="Sarah", email="sarah@example.com", primary=True, position=1
    )
    await db.commit()

    stored_before = await db.get(Communication, draft.id)
    assert stored_before is not None
    raw = stored_before.body or ""
    assert "$borrower_first_name" in raw, "fixture is not exercising the case"

    resp = await client.post(
        f"{API}/{loan_file.display_id}/outbound/draft/{draft.id}/send",
        headers=_auth(token),
        json={"recipient": "sarah@example.com", "body": raw},
    )
    assert resp.status_code == 200

    sent = await db.get(Communication, draft.id)
    assert sent is not None
    assert "$borrower_first_name" not in (sent.body or "")
    assert "$processor_name" not in (sent.body or "")
    assert "Hello Sarah," in (sent.body or "")
    # THE SIGNER IS THE APPROVER. Same user here, but the assertion names the rule the code follows,
    # so a change to resolve from the composer instead fails rather than passing by coincidence.
    assert "Dana Reyes" in (sent.body or "")


# --------------------------------------------------------------------------------------------- #
# Review — the placeholder is shared with drafts that are not the borrower's
# --------------------------------------------------------------------------------------------- #
async def test_a_party_request_is_not_addressed_to_the_borrower_by_name(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A title company must not be GREETED as the borrower — while still being told whose loan it is.

    LP-823's finding: `build_party_draft` rendered the borrower's template for every party, so a
    title request carried `Hello $borrower_first_name,` and `send_draft` resolved it from
    `primary_borrower`. Measured then: a request to `t@title.example` went out reading "Hello Akash,".

    Worse than what it replaced, which is why it was a finding rather than a nit. A placeholder in a
    message to the wrong reader is visibly broken and gets noticed; a real borrower's name in it is
    not.

    LP-843 SPLIT THE TWO THINGS THIS TEST WAS CONFLATING. It asserted the borrower's name appeared
    NOWHERE in a third-party message, which was the right guard while the only place a name could
    appear was the greeting. The third party now needs the borrower's name — it is how a title
    company finds the file in their own system, and an email carrying only our `display_id` names
    nothing they can search.

    So the property is about the ROLE the name plays, not its presence: the borrower is the SUBJECT
    of this message and never its ADDRESSEE. "Borrower: Akash Shah" is the file being identified;
    "Hello Akash," is us mistaking a title company for the borrower.

    The positive control is the second half: the borrower's OWN draft on the same file still greets
    them by name. Without it, a build that greeted nobody anywhere would pass.
    """
    from app.documents.catalog import ResponsibleParty
    from app.models.loan_file_participant import ParticipantRole
    from app.models.needs_item import NeedsItemStatus
    from app.services.email_send import send_draft
    from app.services.party_requests import add_participant, build_party_draft

    company, user, _token = await _company_user_token(db, first="Dana", last="Reyes")
    loan_file, borrower_draft = await _file_with_draft(db, company, user)
    await _borrower(
        db, loan_file, first="Akash", email="akash@example.com", primary=True, position=1
    )
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
    party_draft = await build_party_draft(
        db, loan_file=loan_file, party=ResponsibleParty.TITLE, actor_user_id=user.id
    )
    # LP-843 — NO GREETING SLOT AT ALL, which is stronger than a slot that resolves safely. The
    # third-party template cannot leak a borrower's name into a greeting because it has no greeting
    # to leak it into; that is the difference between a guard and an absence of the hazard.
    assert "$borrower_first_name" not in (party_draft.body or "")

    sent = await send_draft(
        db,
        loan_file=loan_file,
        draft_id=party_draft.id,
        recipient="t@title.example",
        body=party_draft.body or "",
        approver_user_id=user.id,
    )

    body = sent.body or ""
    # THE DEFECT ITSELF: the title company greeted as though they were the borrower.
    assert "Hello Akash" not in body, "the title company was addressed as the borrower"
    assert "$borrower_first_name" not in body, (
        "the placeholder survived to the title company — the greeting resolved to nothing"
    )
    assert "Hello," in body
    # AND THE NAME IS STILL THERE, as the subject of the message rather than its addressee. Asserting
    # its absence would now fail the thing LP-843 exists to provide: a title company cannot match
    # "LF-…" to anything in their own system.
    assert "Akash" in body, "the title company was not told whose loan this is"

    # THE CONTROL: the same borrower, the same file, their own draft — still resolved by name.
    assert borrower_draft is not None
    sent_to_borrower = await send_draft(
        db,
        loan_file=loan_file,
        draft_id=borrower_draft.id,
        recipient="akash@example.com",
        body=borrower_draft.body or "",
        approver_user_id=user.id,
    )
    assert "Hello Akash," in (sent_to_borrower.body or "")


async def test_a_message_nobody_edited_is_not_recorded_as_edited(
    client: AsyncClient, db: AsyncSession
) -> None:
    """`EvidencePublic.was_edited` says "the processor changed the drafted words". It stopped being
    true of every message the moment the send resolved placeholders.

    The evidence row holds `body_composed` (the STORED body, still holding the placeholders) and
    `body_as_sent` (resolved), and the field is `body_composed != body_as_sent`. Measured: a send
    where the panel's own text was posted back untouched recorded composed "Hello
    $borrower_first_name," against as-sent "Hello Akash," — `was_edited` True, with nobody having
    typed a character.

    Both halves asserted, because "not edited" is also what a broken fixture produces: the second
    send changes one word and must come back True.
    """
    from app.models.communication_evidence import CommunicationEvidence
    from app.services.email_draft import draft_for_reading
    from app.services.email_send import send_draft
    from sqlalchemy import select

    company, user, _token = await _company_user_token(db, first="Dana", last="Reyes")
    loan_file, draft = await _file_with_draft(db, company, user)
    await _borrower(
        db, loan_file, first="Akash", email="akash@example.com", primary=True, position=1
    )
    await db.flush()
    assert draft is not None

    # Exactly what the panel does: GET the resolved body, then post the textarea back UNCHANGED.
    shown, _suggested = await draft_for_reading(db, draft=draft, loan_file=loan_file, reader=user)
    sent = await send_draft(
        db,
        loan_file=loan_file,
        draft_id=draft.id,
        recipient="akash@example.com",
        body=shown,
        approver_user_id=user.id,
    )
    row = (
        (
            await db.execute(
                select(CommunicationEvidence).where(
                    CommunicationEvidence.communication_id == sent.id
                )
            )
        )
        .scalars()
        .one()
    )
    assert row.body_composed is not None
    assert row.body_composed == row.body_as_sent, (
        "nobody typed a character and the evidence record says the processor edited the message"
    )

    # THE CONTROL: a real edit still shows. A second draft on a second file, sent with one word
    # changed — if this came back equal, the assertion above would be measuring nothing.
    other_file, other_draft = await _file_with_draft(db, company, user)
    await _borrower(
        db, other_file, first="Mira", email="mira@example.com", primary=True, position=1
    )
    await db.flush()
    assert other_draft is not None
    edited, _ = await draft_for_reading(db, draft=other_draft, loan_file=other_file, reader=user)
    sent_edited = await send_draft(
        db,
        loan_file=other_file,
        draft_id=other_draft.id,
        recipient="mira@example.com",
        body=edited + "\n\nPS: whenever is convenient.",
        approver_user_id=user.id,
    )
    edited_row = (
        (
            await db.execute(
                select(CommunicationEvidence).where(
                    CommunicationEvidence.communication_id == sent_edited.id
                )
            )
        )
        .scalars()
        .one()
    )
    assert edited_row.body_composed != edited_row.body_as_sent


async def test_the_file_tag_is_not_stamped_on_the_message_twice(
    client: AsyncClient, db: AsyncSession
) -> None:
    """`build_outbound` runs twice over one message, and stamped its footer both times.

    `GET /outbound/draft` returns `build_outbound(...).body` — tag included — the panel puts exactly
    that in the textarea, and the send posts the textarea back through `build_outbound` again.
    Measured over the real round trip before the fix: every sent message ended
    `[LF-H5HH]\\n\\n[LF-H5HH]`.

    Pre-existing rather than caused by LP-823, and found only because the composed-vs-sent
    comparison could not be written while it was true. It reaches the borrower: the tag is the
    footer LP-805 matches a reply on, and it was in their email twice.

    Asserted over HTTP rather than on `build_outbound` directly, because the defect is the two calls
    and a unit test on one of them cannot see it. The count is asserted at each stage, so a fix that
    dropped the tag entirely — which would break LP-805's fallback routing — fails here too.
    """
    company, user, token = await _company_user_token(db)
    loan_file, draft = await _file_with_draft(db, company, user)
    await _borrower(
        db, loan_file, first="Akash", email="akash@example.com", primary=True, position=1
    )
    await db.commit()
    tag = f"[{loan_file.display_id}]"

    shown = (
        await client.get(f"{API}/{loan_file.display_id}/outbound/draft", headers=_auth(token))
    ).json()["body"]
    assert shown.count(tag) == 1, "the draft a processor copies must carry the tag exactly once"

    resp = await client.post(
        f"{API}/{loan_file.display_id}/outbound/draft/{draft.id}/send",
        headers=_auth(token),
        json={"recipient": "akash@example.com", "body": shown},
    )
    assert resp.status_code == 200

    sent = await db.get(Communication, draft.id)
    assert sent is not None
    await db.refresh(sent)
    assert (sent.body or "").count(tag) == 1, (
        "the borrower's email carried the file tag twice — once from the GET, once from the send"
    )
