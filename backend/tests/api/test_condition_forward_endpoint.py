"""Using an emailed PDF as a condition sheet (LP-905 section 3, spec §6, screen S1-13).

⚠️ THE ATTACHMENT IS NEVER TURNED INTO A DOCUMENT, and that is the property most worth pinning. A
lender's letter satisfies no need and would be classified against a 166-type BORROWER taxonomy —
the reasoning that created `CORRESPONDENCE` in the first place (ADR-403). So the bytes are
re-derived and stored with `save_at`, and the classify → extract → needs pipeline is never entered.

The messages here arrive through `process_raw_message` with a real RFC-5322 body, so the attachment
carries a genuine `safety_state` and `declared_content_type` rather than values a fixture asserted
into existence — which is what makes the guards meaningful rather than decorative.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from email import policy
from email.message import EmailMessage
from uuid import UUID, uuid4

import pymupdf
import pytest
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, User, UserRole
from app.models.condition_round import ConditionRound, ConditionRoundStatus, ConditionSourceKind
from app.models.document import Document
from app.models.inbound_attachment import (
    AttachmentDisposition,
    AttachmentSafetyState,
    InboundAttachment,
)
from app.models.inbound_message import InboundMessage
from app.services.inbound_ingest import process_raw_message
from app.services.loan_files import create_loan_file
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Shadows the root fixture so the request shares this test's session (see LP-905 §1)."""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _pdf() -> bytes:
    document = pymupdf.open()
    document.new_page().insert_text((72.0, 100.0), "LOAN APPROVAL CONDITIONS", fontsize=9)
    return bytes(document.tobytes())


async def _user(db: AsyncSession, *, slug: str) -> tuple[Company, User, str]:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u@{slug}.com",
        hashed_password=hash_password("irrelevant"),
        first_name="Test",
        last_name="User",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return company, user, create_access_token(user.id)


async def _arrive(db: AsyncSession, *, address: str, content: bytes) -> InboundAttachment:
    """A real message through the real ingest path, so the attachment is genuinely assessed."""
    message = EmailMessage()
    message["From"] = "processor@example-broker.test"
    message["To"] = address
    message["Subject"] = "Approval letter"
    message["Message-ID"] = f"<{uuid4().hex}@example.test>"
    message.set_content("attached")
    message.add_attachment(content, maintype="application", subtype="pdf", filename="approval.pdf")
    result = await process_raw_message(
        db, raw=message.as_bytes(policy=policy.default), raw_storage_path=None, store_raw=True
    )
    inbound = await db.get(InboundMessage, UUID(result.message_id))
    assert inbound is not None
    return (
        await db.execute(
            select(InboundAttachment).where(InboundAttachment.inbound_message_id == inbound.id)
        )
    ).scalar_one()


def _url(file_id: object, attachment_id: object) -> str:
    return f"/api/v1/loan-files/{file_id}/inbound/attachments/{attachment_id}/condition-round"


async def _setup(db: AsyncSession, *, slug: str) -> tuple[object, InboundAttachment, str]:
    company, _user_row, token = await _user(db, slug=slug)
    loan_file = await create_loan_file(db, company_id=company.id)
    attachment = await _arrive(db, address=loan_file.get_inbox_address(), content=_pdf())
    message = await db.get(InboundMessage, attachment.inbound_message_id)
    assert message is not None
    message.loan_file_id = loan_file.id
    await db.flush()
    return loan_file, attachment, token


async def test_an_emailed_pdf_becomes_a_parsing_round(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Spec §LP-905: same round creation as an upload, with source EMAIL."""
    loan_file, attachment, token = await _setup(db_session, slug="fwd-happy")

    response = await client.post(_url(loan_file.id, attachment.id), headers=_auth(token), json={})

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == ConditionRoundStatus.PARSING.value
    assert body["disposition"] == AttachmentDisposition.CORRESPONDENCE.value

    round_ = await db_session.get(ConditionRound, UUID(body["round_id"]))
    assert round_ is not None
    assert round_.sources[0]["kind"] == ConditionSourceKind.EMAIL.value
    # ⚠️ The link screen S1-13 renders ("Used as condition sheet → Round N") is derivable from this,
    # so no column was needed to join a round back to the attachment it came from.
    assert round_.sources[0]["inbound_attachment_id"] == str(attachment.id)


async def test_the_attachment_is_kept_as_correspondence_not_made_a_document(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ ADR-403's boundary, at the forward door this time. A condition sheet is not a borrower
    document: no `Document` row means it cannot enter classify → extract → needs, cannot satisfy a
    need, and cannot be classified against a taxonomy with no bucket for it."""
    loan_file, attachment, token = await _setup(db_session, slug="fwd-corr")

    await client.post(_url(loan_file.id, attachment.id), headers=_auth(token), json={})
    await db_session.refresh(attachment)

    assert attachment.disposition is AttachmentDisposition.CORRESPONDENCE
    documents = (
        (
            await db_session.execute(
                select(Document).where(Document.loan_file_id == loan_file.id)  # type: ignore[attr-defined]
            )
        )
        .scalars()
        .all()
    )
    assert documents == []


async def test_attaching_to_a_round_that_is_not_on_this_file_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ `attach_to_round_id` ARRIVES IN THE REQUEST BODY, which makes it the one id here that
    cannot be trusted. The route proves the caller owns the FILE; only the scoped lookup proves the
    ROUND is on it. An unknown id is refused and leaves nothing behind.

    This test used to assert a `501` — LP-905 declared the field and refused it because the LP-907
    merge did not exist. It does now, so what is worth pinning moved from "refused" to "refused for
    the right reason".
    """
    loan_file, attachment, token = await _setup(db_session, slug="fwd-attach")

    response = await client.post(
        _url(loan_file.id, attachment.id),
        headers=_auth(token),
        json={"attach_to_round_id": str(uuid4())},
    )

    assert response.status_code == 409
    assert "No such condition round on this loan file" in response.text

    rounds = (
        (
            await db_session.execute(
                select(ConditionRound).where(ConditionRound.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert rounds == [], "a refused attach must not leave a round behind"


async def test_forwarding_into_an_existing_round_merges_instead_of_creating_one(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ THE `501` LP-905 LEFT BEHIND, NOW CLOSED — and the property it was protecting is the one
    asserted here: forwarding into a round enriches THAT round and creates no second one.

    200 rather than 202, because nothing was created and nothing was queued, so there is nothing to
    poll. The attachment is still kept as CORRESPONDENCE, never turned into a document.
    """
    from app.models.condition_round import ConditionRoundCompleteness
    from app.services.condition_rounds import create_round_from_paste
    from tests.conditions.fixture_helpers import portal_excerpt

    loan_file, attachment, token = await _setup(db_session, slug="fwd-merge")
    pasted = await create_round_from_paste(
        db_session,
        loan_file=loan_file,  # type: ignore[arg-type]
        text=portal_excerpt(),
        completeness=ConditionRoundCompleteness.PARTIAL,
    )

    response = await client.post(
        _url(loan_file.id, attachment.id),
        headers=_auth(token),
        json={"attach_to_round_id": str(pasted.id)},
    )

    assert response.status_code == 200, response.text
    assert response.json()["round_id"] == str(pasted.id)
    assert response.json()["disposition"] == AttachmentDisposition.CORRESPONDENCE.value

    rounds = (
        (
            await db_session.execute(
                select(ConditionRound).where(ConditionRound.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rounds) == 1, "a merge must not leave a second round behind"
    # S1-13's link still derives from `sources` — now pointing at the round the PDF enriched.
    await db_session.refresh(pasted)
    assert any(
        source.get("inbound_attachment_id") == str(attachment.id) for source in pasted.sources
    )


async def test_forwarding_the_same_attachment_twice_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ A SELF-PERMITTING LOOP, AND IT BROKE A STATED INVARIANT.

    The disposition guard admits PENDING *or* CORRESPONDENCE, and the action ends by setting
    CORRESPONDENCE — so the first call creates exactly the condition the second one requires, and it
    stays true forever. N forwards gave N rounds, all in PARSING, all parsing identical bytes.

    The wasted work was the least of it. Every one of those rounds carries the SAME
    `inbound_attachment_id` in its `sources`, and that field is what the attachment→round link is
    derived from — deliberately, instead of materialising a column. The derivation assumes
    one-to-one; this made it one-to-many, so screen S1-13's "Used as condition sheet → Round N" had
    no single answer to render.

    Refusing with the EXISTING round's id is also what a processor who clicked twice actually wants:
    "this is already round 3", not a second round to discard.
    """
    loan_file, attachment, token = await _setup(db_session, slug="fwd-twice")

    first = await client.post(_url(loan_file.id, attachment.id), headers=_auth(token), json={})
    assert first.status_code == 202

    second = await client.post(_url(loan_file.id, attachment.id), headers=_auth(token), json={})

    assert second.status_code == 409
    # The refusal names the round that already exists, so the UI can link straight to it.
    assert first.json()["round_id"] in second.text

    rounds = (
        (
            await db_session.execute(
                select(ConditionRound).where(ConditionRound.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rounds) == 1, "a second forward must not create a second round"


async def test_an_unsafe_attachment_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """⚠️ PENDING IS NOT A PASS. The malware scan is asynchronous, so "nobody has looked yet" is a
    state that genuinely persists and must never read as "nothing was found"."""
    loan_file, attachment, token = await _setup(db_session, slug="fwd-unsafe")
    attachment.safety_state = AttachmentSafetyState.QUARANTINED
    attachment.safety_reason = "Scan found something."
    await db_session.flush()

    response = await client.post(_url(loan_file.id, attachment.id), headers=_auth(token), json={})

    assert response.status_code == 409
    assert "quarantined" in response.text


async def test_another_companys_attachment_is_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The same 404 as a missing one — distinguishing them would confirm the id exists, an oracle
    over another tenant's rows."""
    loan_file_a, attachment_a, _token_a = await _setup(db_session, slug="fwd-tenant-a")
    _company_b, _user_b, token_b = await _user(db_session, slug="fwd-tenant-b")
    loan_file_b = await create_loan_file(db_session, company_id=_company_b.id)

    response = await client.post(
        _url(loan_file_b.id, attachment_a.id), headers=_auth(token_b), json={}
    )

    assert response.status_code == 404
    assert loan_file_a.id != loan_file_b.id


async def test_an_unauthenticated_forward_is_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    loan_file, attachment, _token = await _setup(db_session, slug="fwd-anon")

    response = await client.post(_url(loan_file.id, attachment.id), json={})

    assert response.status_code == 401
