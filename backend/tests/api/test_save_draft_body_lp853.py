"""LP-853 at the layer a screen reads — the save route, and what the modal gets back.

WRITTEN AT THIS LAYER ON PURPOSE. LP-850's review found that every assertion about the open-draft
refusal read the EXCEPTION OBJECT at the service layer, so the contract LP-851 depends on was green
at the only layer no UI can reach, and the payload never left the server. The editor reads
`body_format` off this response and posts back to this route; both halves are asserted here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models import Borrower, Company, LoanProgram, User, UserRole
from app.models.communication import BodyFormat, Communication
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


async def _file(db: AsyncSession):
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
    await db.flush()
    return loan_file, create_access_token(user.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _draft(client: AsyncClient, db: AsyncSession):
    loan_file, token = await _file(db)
    await db.commit()
    resp = await client.post(
        f"{API}/{loan_file.display_id}/outbound/compose",
        headers=_auth(token),
        json={"document_types": ["bank_statement"]},
    )
    assert resp.status_code == 201, resp.text
    return loan_file, token, resp.json()["draft_id"]


async def test_a_generated_draft_reads_back_as_plain(client: AsyncClient, db: AsyncSession) -> None:
    """ACCEPTANCE 1 AND 2, at the layer the editor reads. Composing and then READING must not flip
    it — the read is what happens when a processor opens the modal and types nothing."""
    loan_file, token, draft_id = await _draft(client, db)

    detail = (
        await client.get(f"{API}/{loan_file.display_id}/messages/{draft_id}", headers=_auth(token))
    ).json()
    assert detail["body_format"] == "plain"
    assert "<" not in detail["body"]

    # Read it again — still plain. Focus is not an edit, and neither is opening it twice.
    again = (
        await client.get(f"{API}/{loan_file.display_id}/messages/{draft_id}", headers=_auth(token))
    ).json()
    assert again["body_format"] == "plain"


async def test_saving_stores_html_and_reads_back_as_html(
    client: AsyncClient, db: AsyncSession
) -> None:
    loan_file, token, draft_id = await _draft(client, db)

    saved = await client.put(
        f"{API}/{loan_file.display_id}/outbound/draft/{draft_id}/body",
        headers=_auth(token),
        json={"body": "<p>March statement only, not <strong>February</strong>.</p>"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["body_format"] == "html"

    detail = (
        await client.get(f"{API}/{loan_file.display_id}/messages/{draft_id}", headers=_auth(token))
    ).json()
    assert detail["body_format"] == "html"
    assert detail["body"] == "<p>March statement only, not <strong>February</strong>.</p>"


async def test_a_hand_built_request_is_stripped_server_side(
    client: AsyncClient, db: AsyncSession
) -> None:
    """ACCEPTANCE 5 — THE REQUEST IS BUILT BY HAND, NOT THROUGH THE EDITOR.

    That is the criterion's own wording and the reason is that the editor is not a security
    boundary: a processor cannot type `<script>` into Tiptap, so a test that went through it would
    prove only that Tiptap works. This is what a `curl` sends.
    """
    loan_file, token, draft_id = await _draft(client, db)

    hostile = (
        "<script>alert(1)</script>"
        '<p onclick="steal()" style="color:red" class="x">Please send it</p>'
        '<a href="javascript:alert(1)">click</a>'
        "<img src=x onerror=alert(1)>"
    )
    saved = await client.put(
        f"{API}/{loan_file.display_id}/outbound/draft/{draft_id}/body",
        headers=_auth(token),
        json={"body": hostile},
    )
    assert saved.status_code == 200, saved.text

    stored = await db.get(Communication, draft_id)
    assert stored is not None
    await db.refresh(stored)
    body = stored.body or ""
    # THE COLUMN, not the response — this is about what was STORED, and every later reader of the
    # row inherits whatever is in it.
    for forbidden in ("<script", "onclick", "style=", "class=", "javascript:", "<img", "onerror"):
        assert forbidden not in body, f"{forbidden!r} survived into the column"
    # And the processor's actual sentence is still there — a sanitiser that ate the message would
    # satisfy every assertion above.
    assert "Please send it" in body
    assert stored.body_format is BodyFormat.HTML


async def test_saving_a_sent_message_is_refused(client: AsyncClient, db: AsyncSession) -> None:
    """LP-821's evidence record is what actually went out."""
    loan_file, token, draft_id = await _draft(client, db)
    await client.post(
        f"{API}/{loan_file.display_id}/outbound/draft/{draft_id}/send",
        headers=_auth(token),
        json={"recipient": "sarah@example.com", "body": "Sent it.", "subject": "s"},
    )

    refused = await client.put(
        f"{API}/{loan_file.display_id}/outbound/draft/{draft_id}/body",
        headers=_auth(token),
        json={"body": "<p>after the fact</p>"},
    )
    assert refused.status_code == 409


async def test_another_companys_draft_is_not_saveable(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The tenant gate, on a route that writes. `ScopedLoanFile` resolves the file under the
    caller's company before anything runs, and the service re-checks `loan_file_id` on the row."""
    loan_file, _token, draft_id = await _draft(client, db)
    _other_file, other_token = await _file(db)
    await db.commit()

    refused = await client.put(
        f"{API}/{loan_file.display_id}/outbound/draft/{draft_id}/body",
        headers=_auth(other_token),
        json={"body": "<p>not yours</p>"},
    )
    assert refused.status_code == 404

    stored = await db.get(Communication, draft_id)
    assert stored is not None
    await db.refresh(stored)
    assert stored.body_format is BodyFormat.PLAIN


async def test_an_empty_body_is_refused(client: AsyncClient, db: AsyncSession) -> None:
    """There is no message to have written without one, and an empty save would flip the format on
    a draft nobody touched."""
    loan_file, token, draft_id = await _draft(client, db)
    refused = await client.put(
        f"{API}/{loan_file.display_id}/outbound/draft/{draft_id}/body",
        headers=_auth(token),
        json={"body": ""},
    )
    assert refused.status_code == 422

    stored = await db.get(Communication, draft_id)
    assert stored is not None
    await db.refresh(stored)
    assert stored.body_format is BodyFormat.PLAIN


async def test_adding_a_link_to_an_edited_draft_is_refused_with_a_readable_sentence(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The link is written INTO the body, so on an edited draft there is nowhere for it to go.

    The message has to say which of the two things went wrong — LP-UI rule 9, "every error names
    what failed and offers the next move".

    LP-857 — RECEIVING IS ON HERE, deliberately. The route now refuses the same call with a 409
    when the version cannot receive at all, and that check runs FIRST because it is the more
    fundamental reason. Without the flag this test would pass on the wrong refusal — a 409 whose
    sentence says nothing about editing — which is exactly what "name which of the two things went
    wrong" is about. The off state is asserted in `test_next_phase_off_lp857.py`.
    """
    monkeypatch.setattr(settings, "receiving_enabled", True)
    loan_file, token, draft_id = await _draft(client, db)
    await client.put(
        f"{API}/{loan_file.display_id}/outbound/draft/{draft_id}/body",
        headers=_auth(token),
        json={"body": "<p>Mine.</p>"},
    )

    refused = await client.post(
        f"{API}/{loan_file.display_id}/messages/{draft_id}/upload-link",
        headers=_auth(token),
    )
    assert refused.status_code == 409
    assert "edited" in refused.json()["error"]["message"]
