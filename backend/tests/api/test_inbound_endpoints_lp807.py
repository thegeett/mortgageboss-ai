"""LP-807 at the layer a processor's browser reaches — the file's messages and the preview.

The service tests cover the rules. These cover what a caller can actually reach, and one thing that
is only true at this layer: **the preview is structurally unreachable for an unrouted message.**

That matters more here than anywhere else in the module. The unrouted queue is shown to EVERY
company, because a message nobody owns cannot be scoped to one — LP-806's review had to redact the
sender, the subject and both filenames out of it after measuring one tenant receiving another
tenant's borrower's personal address. A thumbnail is the same disclosure in its most legible form:
dropping the filename and then rendering the document would give back everything the redaction took,
and more. The defence is not a flag on the preview route; it is that the route is file-scoped and an
unrouted message has no file. This asserts that, so a later convenience endpoint cannot quietly undo
it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from email import policy
from email.message import EmailMessage
from pathlib import Path
from uuid import UUID, uuid4

import pytest_asyncio
from app.core.database import get_db
from app.main import app
from app.models import Company, LoanProgram, User, UserRole
from app.models.inbound_attachment import AttachmentSafetyState, InboundAttachment
from app.models.inbound_message import InboundMessage
from app.services.inbound_ingest import process_raw_message
from app.services.loan_files import create_loan_file
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

API = "/api/v1/loan-files"
QUEUE = "/api/v1/inbound/queue"

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "attachments"
_PDF = (_FIXTURES / "clean.pdf").read_bytes()
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# The endpoints COMMIT, so the plain rollback `db_session` fixture will not do — same savepoint-
# joining shape as `test_communications_lp811a.py`.
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
    return company, user, create_access_token(user.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _message_to(address: str, *, message_id: str, content: bytes = _PDF) -> bytes:
    message = EmailMessage()
    message["From"] = "jane.borrower@personal-email.com"
    message["To"] = address
    message["Subject"] = "Docs for 42 Maple Ave - Jane Borrower"
    message["Message-ID"] = f"<{message_id}>"
    message.set_content("attached")
    message.add_attachment(
        content, maintype="application", subtype="pdf", filename="Jane_2024_tax_return.pdf"
    )
    return message.as_bytes(policy=policy.default)


async def _arrive(db: AsyncSession, *, address: str, message_id: str) -> InboundMessage:
    result = await process_raw_message(
        db, raw=_message_to(address, message_id=message_id), raw_storage_path=None, store_raw=True
    )
    message = await db.get(InboundMessage, UUID(result.message_id))
    assert message is not None
    return message


async def _attachment_of(db: AsyncSession, message: InboundMessage) -> InboundAttachment:
    return (
        await db.execute(
            select(InboundAttachment).where(InboundAttachment.inbound_message_id == message.id)
        )
    ).scalar_one()


# --------------------------------------------------------------------------------------------- #
# The file's own messages
# --------------------------------------------------------------------------------------------- #
async def test_a_files_messages_come_back_with_the_senders_words(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Unredacted, because somebody owns this one. It is on their file, in their company."""
    company, _user, token = await _company_user_token(db, slug="acme")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    message = await _arrive(db, address=loan_file.get_inbox_address(), message_id="a1@example.com")
    await db.commit()

    resp = await client.get(f"{API}/{loan_file.display_id}/inbound/messages", headers=_auth(token))

    assert resp.status_code == 200
    payload = resp.json()
    assert [row["id"] for row in payload] == [str(message.id)]
    assert payload[0]["from_address"] == "jane.borrower@personal-email.com"
    assert payload[0]["subject"] == "Docs for 42 Maple Ave - Jane Borrower"
    assert payload[0]["attachments"][0]["filename_original"] == "Jane_2024_tax_return.pdf"
    assert payload[0]["attachments"][0]["safety_state"] == "safe"


async def test_another_companys_file_is_not_readable(client: AsyncClient, db: AsyncSession) -> None:
    theirs, _their_user, _their_token = await _company_user_token(db, slug="theirs")
    _mine, _my_user, my_token = await _company_user_token(db, slug="mine")
    their_file = await create_loan_file(
        db, company_id=theirs.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await _arrive(db, address=their_file.get_inbox_address(), message_id="t1@example.com")
    await db.commit()

    resp = await client.get(
        f"{API}/{their_file.display_id}/inbound/messages", headers=_auth(my_token)
    )

    assert resp.status_code == 404


# --------------------------------------------------------------------------------------------- #
# The preview
# --------------------------------------------------------------------------------------------- #
async def test_a_safe_attachment_previews_as_a_png(client: AsyncClient, db: AsyncSession) -> None:
    company, _user, token = await _company_user_token(db, slug="prev")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    message = await _arrive(db, address=loan_file.get_inbox_address(), message_id="p1@example.com")
    attachment = await _attachment_of(db, message)
    await db.commit()

    resp = await client.get(
        f"{API}/{loan_file.display_id}/inbound/attachments/{attachment.id}/preview",
        headers=_auth(token),
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(_PNG_MAGIC)
    # NOT the PDF a stranger sent, under a content type we hoped the browser would believe.
    assert not resp.content.startswith(b"%PDF")
    assert resp.headers["cache-control"] == "private, no-store"


async def test_an_unsafe_attachment_will_not_be_rendered(
    client: AsyncClient, db: AsyncSession
) -> None:
    company, _user, token = await _company_user_token(db, slug="unsafe")
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    message = await _arrive(db, address=loan_file.get_inbox_address(), message_id="u1@example.com")
    attachment = await _attachment_of(db, message)
    assert attachment.safety_state is AttachmentSafetyState.SAFE, (
        "the fixture must START safe, or flipping it below proves nothing"
    )
    attachment.safety_state = AttachmentSafetyState.QUARANTINED
    attachment.safety_reason = "Archives are not accepted."
    await db.commit()

    resp = await client.get(
        f"{API}/{loan_file.display_id}/inbound/attachments/{attachment.id}/preview",
        headers=_auth(token),
    )

    assert resp.status_code == 409
    # The safety REASON reaches the processor — "quarantined" alone tells them nothing about
    # whether to ask for a different format, a password, or the file again.
    assert "Archives" in resp.json()["error"]["message"]


async def test_an_attachment_on_another_file_is_the_same_404_as_a_missing_one(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A REAL attachment on a real other file. The preview route inherits `_scoped_attachment`, and
    the two 404s must be indistinguishable or the id is an oracle over another tenant's rows."""
    theirs, _tu, _tt = await _company_user_token(db, slug="oracle-theirs")
    mine, _mu, my_token = await _company_user_token(db, slug="oracle-mine")
    their_file = await create_loan_file(
        db, company_id=theirs.id, loan_program=LoanProgram.CONVENTIONAL
    )
    my_file = await create_loan_file(db, company_id=mine.id, loan_program=LoanProgram.CONVENTIONAL)
    their_message = await _arrive(
        db, address=their_file.get_inbox_address(), message_id="o1@example.com"
    )
    their_attachment = await _attachment_of(db, their_message)
    await db.commit()

    real_but_theirs = await client.get(
        f"{API}/{my_file.display_id}/inbound/attachments/{their_attachment.id}/preview",
        headers=_auth(my_token),
    )
    never_existed = await client.get(
        f"{API}/{my_file.display_id}/inbound/attachments/{uuid4()}/preview",
        headers=_auth(my_token),
    )

    assert real_but_theirs.status_code == never_existed.status_code == 404
    assert real_but_theirs.json() == never_existed.json()


# --------------------------------------------------------------------------------------------- #
# The unrouted queue, and the thing it must not become
# --------------------------------------------------------------------------------------------- #
async def test_an_unrouted_message_reaches_every_company_with_nothing_the_sender_wrote(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-806's redaction, asserted from the other company's session rather than from the service.

    The fixture's sender and subject are the ones that were actually measured leaking.
    """
    _mine, _user, token = await _company_user_token(db, slug="stranger")
    message = await _arrive(db, address="nobody@example.com", message_id="n1@example.com")
    assert message.company_id is None
    await db.commit()

    resp = await client.get(QUEUE, headers=_auth(token))

    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == str(message.id))
    assert row["from_address"] is None
    assert row["subject"] is None
    assert row["attachments"][0]["filename_original"] is None
    assert row["attachments"][0]["filename_normalized"] is None
    # Still visible, and still useful — §2.2's "confidence gates auto-acceptance, never visibility".
    assert row["routing_state"] == "unrouted"
    assert row["attachments"][0]["safety_state"] == "safe"
    assert row["attachments"][0]["size_bytes"] > 0


async def test_an_unrouted_attachment_cannot_be_previewed_by_anyone(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE ONE THAT MATTERS. A thumbnail is the sender's content in its most legible form.

    There is no unscoped preview route to call, so this asserts the shape that makes it impossible:
    the only preview route is file-scoped, and an unrouted message has no file — so every file a
    caller could name gives the same 404 as a missing attachment. If a later ticket adds a
    company-level preview for the queue's convenience, this test is what should stop it.
    """
    mine, _user, token = await _company_user_token(db, slug="unrouted-prev")
    my_file = await create_loan_file(db, company_id=mine.id, loan_program=LoanProgram.CONVENTIONAL)
    message = await _arrive(db, address="nobody@example.com", message_id="n2@example.com")
    attachment = await _attachment_of(db, message)
    assert message.loan_file_id is None
    assert attachment.safety_state is AttachmentSafetyState.SAFE, (
        "a SAFE attachment, or the refusal below could be about safety rather than about ownership"
    )
    await db.commit()

    resp = await client.get(
        f"{API}/{my_file.display_id}/inbound/attachments/{attachment.id}/preview",
        headers=_auth(token),
    )

    assert resp.status_code == 404
