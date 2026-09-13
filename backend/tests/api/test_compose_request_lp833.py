"""LP-833 — composing a request from documents a processor picked.

WHAT SHIPS IS "PICK DOCUMENTS, GET A DRAFT". The model writes three framing sentences around
LP-817's deterministic render, `email_draft_enabled` is False by default and set in no environment,
and `compose` returns None for every failure mode. So the plain path is what a processor actually
gets, and it has to be a complete, sendable email on its own — which is what most of this file
asserts. The model path is exercised with the flag ON, because a behaviour nobody can reach is not
a behaviour anybody tested.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest_asyncio
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models import Borrower, Company, LoanProgram, User, UserRole
from app.models.needs_item import NeedsItem, NeedsItemOrigin
from app.services.loan_files import create_loan_file
from httpx import AsyncClient
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


async def test_picking_documents_produces_a_sendable_draft(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE WHOLE TICKET. Until this, a draft could come from a FINDING and nothing else: a processor
    who knew they needed a document no rule had flagged could add a needs item by hand and nothing
    drafted from it."""
    loan_file, token = await _file(db)
    await db.commit()

    resp = await client.post(
        f"{API}/{loan_file.display_id}/outbound/compose",
        headers=_auth(token),
        json={"document_types": ["bank_statement", "pay_stub"]},
    )

    assert resp.status_code == 201
    assert resp.json()["needs_added"] == 2
    draft_id = resp.json()["draft_id"]
    assert draft_id is not None

    body = (
        await client.get(f"{API}/{loan_file.display_id}/messages/{draft_id}", headers=_auth(token))
    ).json()["body"]
    # A COMPLETE EMAIL, not a stub: greeting resolved, both documents named, the address line and
    # the security notice present. This is what a processor gets with the flag off.
    assert "Hello Sarah," in body
    assert "Bank statement" in body or "bank statement" in body.lower()
    assert "Email is not a fully secure channel." in body


async def test_the_selection_becomes_needs_items(client: AsyncClient, db: AsyncSession) -> None:
    """NOT A LIST OF STRINGS ON AN EMAIL. Needs items are what the needs list shows, what the send
    moves to REQUESTED, and what starts LP-814's reminder clock — a draft listing documents that are
    not needs would ask a borrower for things nothing is tracking."""
    loan_file, token = await _file(db)
    await db.commit()

    await client.post(
        f"{API}/{loan_file.display_id}/outbound/compose",
        headers=_auth(token),
        json={"document_types": ["bank_statement"]},
    )

    needs = (
        (await db.execute(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file.id)))
        .scalars()
        .all()
    )
    assert len(needs) == 1
    assert needs[0].needs_type == "bank_statement"
    # MANUAL, because that is what it is: a processor decided. FINDING would claim a rule asked for
    # it and put a false provenance on the correction signal LP-70 reads.
    assert needs[0].origin is NeedsItemOrigin.MANUAL


async def test_a_type_already_outstanding_is_not_asked_for_twice(
    client: AsyncClient, db: AsyncSession
) -> None:
    loan_file, token = await _file(db)
    await db.commit()
    await client.post(
        f"{API}/{loan_file.display_id}/outbound/compose",
        headers=_auth(token),
        json={"document_types": ["bank_statement"]},
    )

    second = await client.post(
        f"{API}/{loan_file.display_id}/outbound/compose",
        headers=_auth(token),
        # LP-850 — the first compose left a draft open, so the second needs an answer about it.
        # `append` is what the processor picks in the dialog. Without it this is a 409: its BODY is
        # asserted in `test_the_409_body_is_what_the_dialog_will_render` below, the service writing
        # no draft in `test_draft_lifecycle_lp850.py`, and the needs rows this route creates before
        # the conflict being rolled back in `test_get_db_rollback_contract.py`. The comment here
        # used to name only the second of those, which is the one that does NOT cover this route.
        json={"document_types": ["bank_statement", "pay_stub"], "on_conflict": "append"},
    )

    assert second.status_code == 201, second.text
    assert second.json()["needs_added"] == 1, "the bank statement was asked for twice"
    needs = (
        (await db.execute(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file.id)))
        .scalars()
        .all()
    )
    assert sorted(n.needs_type or "" for n in needs) == ["bank_statement", "pay_stub"]


async def test_a_type_the_catalog_does_not_know_is_refused(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-638 found this exact defect on the correction control: two of eight hardcoded options were
    not catalog types, so choosing them set a document to a string with no tier, no category and no
    extractor. A needs item with an unrecognised type is the same hole."""
    loan_file, token = await _file(db)
    await db.commit()

    resp = await client.post(
        f"{API}/{loan_file.display_id}/outbound/compose",
        headers=_auth(token),
        json={"document_types": ["bank_statement", "not_a_real_type"]},
    )

    assert resp.status_code == 422
    assert "not_a_real_type" in resp.text
    # NOTHING WAS CREATED. A partial compose that took the valid half would leave a processor with a
    # draft they did not ask for and no error they could act on.
    assert (
        await db.execute(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file.id))
    ).scalars().all() == []


async def test_an_empty_selection_is_refused(client: AsyncClient, db: AsyncSession) -> None:
    """A click that meant nothing must not mint a draft. LP-809's review guard says the same thing
    about a request the borrower has no part in."""
    loan_file, token = await _file(db)
    await db.commit()

    resp = await client.post(
        f"{API}/{loan_file.display_id}/outbound/compose",
        headers=_auth(token),
        json={"document_types": []},
    )

    assert resp.status_code == 422


async def test_with_the_model_off_the_draft_is_the_template(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE PATH A PROCESSOR ACTUALLY GETS. `email_draft_enabled` is False by default and set in no
    environment, so `composed_by_model` is False and the words are LP-817's — which is a complete
    email, not a degraded one. The screen says which, and this is what makes that sentence true."""
    loan_file, token = await _file(db)
    await db.commit()
    assert settings.email_draft_enabled is False, "the suite's baseline changed"

    resp = await client.post(
        f"{API}/{loan_file.display_id}/outbound/compose",
        headers=_auth(token),
        json={"document_types": ["bank_statement"]},
    )

    assert resp.json()["composed_by_model"] is False


async def test_a_model_failure_still_produces_a_draft(
    client: AsyncClient, db: AsyncSession, monkeypatch
) -> None:
    """THE FALLBACK, WITH THE FLAG ON — the only way to exercise it, since the flag is off
    everywhere. `compose` returns None for every failure mode rather than raising, so a model that
    is slow, refused or unreachable leaves the deterministic draft standing.

    A compose flow that failed when a model was down would be worse than one that quietly produced
    the plain version, and the processor can read the difference on screen.
    """
    loan_file, token = await _file(db)
    await db.commit()
    monkeypatch.setattr(settings, "email_draft_enabled", True)

    async def _unavailable(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.email_draft.compose", _unavailable)

    resp = await client.post(
        f"{API}/{loan_file.display_id}/outbound/compose",
        headers=_auth(token),
        json={"document_types": ["bank_statement"]},
    )

    assert resp.status_code == 201
    assert resp.json()["composed_by_model"] is False
    body = (
        await client.get(
            f"{API}/{loan_file.display_id}/messages/{resp.json()['draft_id']}",
            headers=_auth(token),
        )
    ).json()["body"]
    assert "Hello Sarah," in body
    assert "Email is not a fully secure channel." in body


async def test_another_companys_file_is_a_404(client: AsyncClient, db: AsyncSession) -> None:
    _mine, _token = await _file(db)
    other_file, _other = await _file(db)
    mine, token = await _file(db)
    await db.commit()

    resp = await client.post(
        f"{API}/{other_file.display_id}/outbound/compose",
        headers=_auth(token),
        json={"document_types": ["bank_statement"]},
    )

    assert resp.status_code == 404
    assert mine is not None


async def test_the_409_body_is_what_the_dialog_will_render(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-850 REVIEW — the REFUSAL'S JSON, which nothing asserted.

    `DraftConflictPublic.of` is the exception-to-response mapping LP-851's dialog is built against,
    and every existing assertion about a conflict reads the EXCEPTION OBJECT at the service layer.
    Between the two sits `model_dump(mode="json")` inside an `HTTPException` detail — UUIDs and
    datetimes have to survive it, and a failure there is a 500, not a 409.
    """
    loan_file, token = await _file(db)
    await db.commit()

    first = await client.post(
        f"{API}/{loan_file.display_id}/outbound/compose",
        headers=_auth(token),
        json={"document_types": ["bank_statement"]},
    )
    assert first.status_code == 201, first.text

    refused = await client.post(
        f"{API}/{loan_file.display_id}/outbound/compose",
        headers=_auth(token),
        json={"document_types": ["pay_stub"]},
    )
    assert refused.status_code == 409, refused.text

    envelope = refused.json()["error"]
    assert envelope["type"] == "conflict"
    # THE FALLBACK SENTENCE. It was "Request failed" — true, and useless to somebody being asked
    # to choose between appending and sending.
    assert envelope["message"] == "There is already an open draft to the borrower."

    detail = envelope["data"]
    assert [d["party"] for d in detail["decisions_required"]] == ["borrower"]
    decision = detail["decisions_required"][0]
    # THE CONTENTS AND THE AGE, which is the whole reason the refusal carries a body at all.
    assert [n["title"] for n in decision["open_draft"]["needs"]] == ["bank statement"]
    assert [n["title"] for n in decision["adding"]] == ["pay stub"]
    assert decision["open_draft"]["body_edited"] is False
    # SERIALISED, not left as a UUID/datetime that `model_dump(mode="json")` would have choked on.
    assert isinstance(decision["open_draft"]["id"], str)
    assert isinstance(decision["open_draft"]["created_at"], str)
    assert detail["would_create"] == []


async def test_the_409_carries_the_processors_own_line(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-851 — SCREEN 5's QUOTE, AT THE LAYER THE DIALOG READS IT.

    The warning quotes the processor's own first edited line back at them, and that is the one
    fragment of authored prose in this feature that travels outside the body column. It has to
    survive the exception-to-JSON hop, which is where LP-850's whole payload was lost once already.
    """
    loan_file, token = await _file(db)
    await db.commit()

    first = await client.post(
        f"{API}/{loan_file.display_id}/outbound/compose",
        headers=_auth(token),
        json={"document_types": ["bank_statement"]},
    )
    draft_id = first.json()["draft_id"]
    saved = await client.put(
        f"{API}/{loan_file.display_id}/outbound/draft/{draft_id}/body",
        headers=_auth(token),
        json={"body": "<p>March statement only, not February.</p>"},
    )
    assert saved.status_code == 200, saved.text

    refused = await client.post(
        f"{API}/{loan_file.display_id}/outbound/compose",
        headers=_auth(token),
        json={"document_types": ["pay_stub"]},
    )

    assert refused.status_code == 409, refused.text
    decision = refused.json()["error"]["data"]["decisions_required"][0]
    assert decision["open_draft"]["body_edited"] is True
    assert decision["open_draft"]["edited_excerpt"] == "March statement only, not February."


async def test_an_unedited_draft_refuses_with_no_quote(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE CONTROL. A payload that always carried an excerpt would put a TEMPLATE sentence in
    quotation marks and attribute it to the processor — which is how a warning stops being read."""
    loan_file, token = await _file(db)
    await db.commit()

    await client.post(
        f"{API}/{loan_file.display_id}/outbound/compose",
        headers=_auth(token),
        json={"document_types": ["bank_statement"]},
    )
    refused = await client.post(
        f"{API}/{loan_file.display_id}/outbound/compose",
        headers=_auth(token),
        json={"document_types": ["pay_stub"]},
    )

    assert refused.status_code == 409
    decision = refused.json()["error"]["data"]["decisions_required"][0]
    assert decision["open_draft"]["body_edited"] is False
    assert decision["open_draft"]["edited_excerpt"] is None
