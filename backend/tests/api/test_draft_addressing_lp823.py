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
