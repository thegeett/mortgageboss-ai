"""LP-834 — the secure link is minted from inside the draft, and minting expires the last one.

WHAT PROVES A LINK IS DEAD IS USING IT. "Expires the previous one" is a claim about a row nobody is
looking at, and a test that reads `revoked_at` asserts that a column was written — not that a
borrower holding the old email is refused. So the first link is REDEEMED here, through the public
endpoint a borrower would reach, and the refusal is the assertion.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest_asyncio
from app.core.database import get_db
from app.main import app
from app.models import Borrower, Company, LoanProgram, User, UserRole
from app.models.communication import Communication, CommunicationStatus
from app.models.needs_item import NeedsItem, NeedsItemOrigin
from app.services.email_draft import add_needs_to_draft
from app.services.loan_files import create_loan_file
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

API = "/api/v1/loan-files"
PUBLIC = "/api/v1/upload"

#: A one-page PDF, the smallest thing `assess` accepts.
_PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


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


async def _file_with_draft(db: AsyncSession):
    from app.core.jwt import create_access_token

    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u-{uuid4().hex[:6]}@acme.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name="Dana",
        last_name="Reyes",
        role=UserRole.PROCESSOR,
    )
    db.add(user)
    await db.flush()
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    db.add(
        Borrower(
            loan_file_id=loan_file.id,
            first_name="Sarah",
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
    result = await add_needs_to_draft(db, loan_file=loan_file, needs=[need], actor_user_id=user.id)
    assert result.draft is not None
    return loan_file, result.draft, create_access_token(user.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _token_from(url: str) -> str:
    return url.rsplit("/", 1)[-1]


async def _attach(client: AsyncClient, loan_file, draft, token: str) -> dict:
    resp = await client.post(
        f"{API}/{loan_file.display_id}/messages/{draft.id}/upload-link", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_the_link_lands_in_the_draft_a_borrower_reads(
    client: AsyncClient, db: AsyncSession
) -> None:
    company_file, draft, token = await _file_with_draft(db)
    await db.commit()

    body = (await _attach(client, company_file, draft, token))["body"]

    assert "/upload/" in body
    assert "works for 3 days" in body
    # LP-824's offer is REPLACED, not stacked on top of it. An email that both names a link and
    # offers to send one is the contradiction that ticket removed, arriving from the other side.
    assert "reply and ask" not in body


async def test_minting_again_kills_the_first_link_for_a_borrower_holding_it(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE ASSERTION THIS TICKET IS FOR, and it is made by USING the old link rather than by reading
    a column. `revoked_at` being set proves a write happened; a borrower clicking the link they were
    sent is the thing that must be refused."""
    loan_file, draft, token = await _file_with_draft(db)
    await db.commit()

    body = (await _attach(client, loan_file, draft, token))["body"]
    first = _token_from(next(word for word in body.split() if "/upload/" in word))

    # THE CONTROL, before the second mint: the first link works. Without it, a link that never
    # worked would satisfy the refusal below and prove nothing.
    assert (await client.get(f"{PUBLIC}/{first}")).status_code == 200

    await _attach(client, loan_file, draft, token)
    await db.commit()

    assert (await client.get(f"{PUBLIC}/{first}")).status_code == 404
    refused = await client.post(
        f"{PUBLIC}/{first}", files={"file": ("a.pdf", _PDF, "application/pdf")}
    )
    assert refused.status_code == 404, "a borrower holding the old link could still upload"


async def test_the_second_link_replaces_the_line_rather_than_adding_one(
    client: AsyncClient, db: AsyncSession
) -> None:
    """TWO LINKS IN ONE EMAIL IS THE STATE THIS EXISTS TO PREVENT, and appending is the obvious way
    to reach it."""
    loan_file, draft, token = await _file_with_draft(db)
    await db.commit()

    await _attach(client, loan_file, draft, token)
    body = (await _attach(client, loan_file, draft, token))["body"]

    assert body.count("/upload/") == 1


async def test_a_request_after_the_link_keeps_it(client: AsyncClient, db: AsyncSession) -> None:
    """REGENERATION IS LOSSLESS, which is why the URL is a column rather than only prose.

    The body is rewritten from the template on every add and remove. A link that lived only in the
    rendered text would be wiped the first time a processor requested one more document — and could
    not be rebuilt, because `upload_links` holds a hash.
    """
    loan_file, draft, token = await _file_with_draft(db)
    await db.commit()
    await _attach(client, loan_file, draft, token)
    await db.commit()

    stored = await db.get(Communication, draft.id)
    assert stored is not None
    from app.services.email_draft import _regenerate

    await _regenerate(db, draft=stored, loan_file=loan_file)

    assert "/upload/" in (stored.body or "")


async def test_a_draft_with_no_link_is_a_complete_email(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE CONTROL ON THE SLOT. A template variable that rendered empty would leave a blank line
    where a sentence belongs, and the security caution is a fixed decision — it must be there either
    way."""
    loan_file, draft, token = await _file_with_draft(db)
    await db.commit()

    body = (
        await client.get(f"{API}/{loan_file.display_id}/messages/{draft.id}", headers=_auth(token))
    ).json()["body"]

    assert "Email is not a fully secure channel." in body
    assert "reply and ask" in body
    assert "/upload/" not in body


async def test_a_sent_message_cannot_gain_a_link(client: AsyncClient, db: AsyncSession) -> None:
    """LP-821 — the evidence record is what actually went out. Adding a link to it afterwards would
    make the stored message differ from the one the borrower received."""
    loan_file, draft, token = await _file_with_draft(db)
    draft.status = CommunicationStatus.SENT
    await db.flush()
    await db.commit()

    resp = await client.post(
        f"{API}/{loan_file.display_id}/messages/{draft.id}/upload-link", headers=_auth(token)
    )

    assert resp.status_code == 409


async def test_another_companys_draft_is_a_404(client: AsyncClient, db: AsyncSession) -> None:
    _mine, draft, _token = await _file_with_draft(db)
    other_file, _other_draft, other_token = await _file_with_draft(db)
    await db.commit()

    resp = await client.post(
        f"{API}/{other_file.display_id}/messages/{draft.id}/upload-link",
        headers=_auth(other_token),
    )

    assert resp.status_code == 404


async def test_attaching_does_not_revoke_a_link_minted_for_somebody_else(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-834 REVIEW — THE REVOKE WAS SCOPED TO THE FILE AND THE REASON IS SCOPED TO THE DRAFT.

    `attach_upload_link` revoked every usable link on the file, on the stated invariant that one live
    link per file "is the point rather than a tidiness rule". LP-815 does not agree and shipped
    first: `GET /upload-links` is documented as "every link minted for this file — a processor needs
    to see what is live before minting more", the panel lists them with a Revoke button each, and
    minting takes `recipient_email`, `purpose`, `ttl_hours` and `max_uses`. Links are per-recipient
    and per-purpose there.

    Measured before the fix: a link minted from the panel for `cosigner@example.com`, purpose
    "Co-borrower's pay stubs", stopped working the moment somebody clicked Add secure link on the
    BORROWER's draft. A different person's credential, killed with nothing on any screen saying so —
    and the button's own warning says "any link already sent to THIS BORROWER stops working", a
    narrower claim than the code was making.

    The control is the second half, and it is the property the ticket actually needs: this draft's
    own previous link must still die, or "replaces, never appends" stops being true.
    """
    from app.services.upload_links import mint_upload_link

    loan_file, draft, token = await _file_with_draft(db)
    other = await mint_upload_link(
        db,
        loan_file=loan_file,
        recipient_email="cosigner@example.com",
        purpose="Co-borrower's pay stubs",
    )
    await db.commit()
    assert other.link.is_usable(), (
        "the fixture must start with a live link, or this asserts nothing"
    )

    first = await _attach(client, loan_file, draft, token)

    await db.refresh(other.link)
    assert other.link.is_usable(), (
        "a link minted from the panel for another recipient was revoked by a draft it has nothing "
        "to do with"
    )

    # THE CONTROL: attaching again must still kill THIS draft's previous link, or the fix has
    # replaced an over-wide revoke with none at all.
    import re

    def _url_in(payload: dict) -> str:
        found = re.search(r"https?://\S+/upload/\S+", payload["body"])
        assert found is not None, "the draft body carries no link"
        return found.group(0)

    second = await _attach(client, loan_file, draft, token)
    assert _url_in(second) != _url_in(first)

    spent = await client.get(f"/api/v1/upload/{_token_from(_url_in(first))}")
    assert spent.status_code == 404, "the draft's own previous link is still live"
    await db.refresh(other.link)
    assert other.link.is_usable(), "the second attach revoked somebody else's link"


async def test_a_url_naming_another_files_link_revokes_nothing(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The lookup is scoped to the file as well as the token hash, and that is not decoration.

    Found by a surviving mutant: dropping `UploadLink.loan_file_id == loan_file.id` left every test
    green. `draft.upload_link_url` is TEXT IN A COLUMN — the token hash is 256 bits so a collision
    is not the risk, but a value that got there by any route other than this function's own mint is,
    and revoking on the hash alone would be a write into another company's row from a draft that
    does not own it.

    Constructed rather than hoped for: the other file's URL is put into the column deliberately,
    because a test that never plants one asserts nothing about the scoping. The control is that the
    attach still succeeds and still mints — a lookup that refused everything would pass the first
    assertion and break the feature.
    """
    from app.services.upload_links import mint_upload_link

    loan_file, draft, token = await _file_with_draft(db)
    other_file, _other_draft, _other_token = await _file_with_draft(db)
    theirs = await mint_upload_link(db, loan_file=other_file, purpose="Their documents")
    assert theirs.link.is_usable()

    # The other file's URL, in THIS draft's column. Nothing writes this today; the guard is what
    # keeps it that way.
    draft.upload_link_url = theirs.url
    await db.commit()

    body = (await _attach(client, loan_file, draft, token))["body"]

    await db.refresh(theirs.link)
    assert theirs.link.is_usable(), "another file's link was revoked through a draft on this one"
    # THE CONTROL: this draft still got a link of its own.
    assert "/upload/" in body


async def test_a_link_holder_is_told_a_reference_and_nothing_else(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-835's question, answered on the endpoint rather than by reading the schema.

    A party draft is addressed to somebody who is not the borrower. If it can carry a secure upload
    link, the question is what the title company can SEE with it — whether a credential meant for
    sending a title commitment also opens the borrower's documents.

    It does not. The page is write-only by construction: a reference, a purpose, a byte ceiling and
    the uses left. No name, no address, no needs list, no documents. Asserted as an exact key set so
    a field added later has to be a decision — the holder of this token is whoever the email reached,
    which after a forward is more people than the borrower.
    """
    loan_file, draft, token = await _file_with_draft(db)
    await db.commit()
    body = (await _attach(client, loan_file, draft, token))["body"]
    link_token = _token_from(next(word for word in body.split() if "/upload/" in word))

    page = await client.get(f"{PUBLIC}/{link_token}")

    assert page.status_code == 200
    assert set(page.json()) == {"reference", "purpose", "max_bytes", "remaining_uses"}
    # The reference is the file's display id — deliberately not the borrower's name.
    assert page.json()["reference"] == loan_file.display_id
    assert "Sarah" not in page.text
    assert "sarah@example.com" not in page.text
