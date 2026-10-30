"""LP-996 — the pre-send content check on a `transmit=True` Send (`loan-email.md` §2 rule 5)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from app.ai import email_draft
from app.communications.templates import (
    TEMPLATES,
    TemplateKey,
    file_address_phrase,
    plain_framing,
    render,
    render_document_block,
    secure_upload_block,
)
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.activity_log import ActivityLog
from app.models.communication import BodyFormat, CommunicationStatus
from app.models.communication_evidence import CommunicationEvidence
from app.models.loan_file import LoanFile
from app.services.condition_drafts import render_borrower
from app.services.content_check import CONTENT_CHECK_REASONS, content_check_grounds
from app.services.email_draft import finalise_draft_body
from app.services.email_send import (
    CannotSendError,
    ContentCheckError,
    build_outbound,
    send_draft,
)
from app.services.outbound_mime import html_to_text
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from structlog.testing import capture_logs
from tests.outbound_send import Ready, ready_to_send

TO = "borrower@example.test"
NOTE = "Borrower asked us to confirm the rate on the LE"
RATE_BODY = "Your interest rate is 6.5%."


@pytest.fixture(autouse=True)
def _can_send(file_addresses_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mail_transport", "smtp")


# --------------------------------------------------------------------------------------------- #
# The check itself
# --------------------------------------------------------------------------------------------- #
BLOCKED = [
    ("Your rate is 6.5% today", "rate"),
    ("We will send the APR separately", "rate"),
    ("Good news, you're approved", "commitment"),
    ("Your file is cleared to close", "commitment"),
    ("Please confirm the routing number", "payment_routing"),
    ("Use 021000021 for the transfer", "payment_routing"),
    ("Here are the wire instructions", "payment_routing"),
]


@pytest.mark.parametrize(("text", "ground"), BLOCKED)
def test_each_ground_blocks_in_the_body(text: str, ground: str) -> None:
    assert content_check_grounds("Documents for your loan", text, html=False) == [ground]


@pytest.mark.parametrize(("text", "ground"), BLOCKED)
def test_each_ground_blocks_in_the_subject(text: str, ground: str) -> None:
    assert content_check_grounds(text, "Please send your pay stubs.", html=False) == [ground]


@pytest.mark.parametrize(("text", "ground"), BLOCKED)
def test_each_ground_blocks_in_an_html_body(text: str, ground: str) -> None:
    assert content_check_grounds("Documents", f"<p>{text}</p>", html=True) == [ground]


def test_a_word_split_by_tags_is_read_as_text() -> None:
    body = "<p>Good news: you are <b>appro</b>ved.</p>"
    # Positive control: the raw markup does not match, so only reading it as text can.
    assert "commitment" not in email_draft.send_check_grounds(body)
    assert content_check_grounds("Documents", body, html=True) == ["commitment"]


def test_a_hidden_link_target_is_not_read() -> None:
    """The borrower reads the link's text, not its address."""
    body = '<p>See <a href="https://homes.example/listing/123456789/">the listing</a>.</p>'
    # Positive control: the plain part a text-only reader gets does carry the address.
    assert "payment_routing" in email_draft.send_check_grounds(html_to_text(body))
    assert content_check_grounds("Documents", body, html=True) == []


def test_a_link_whose_text_is_the_address_is_still_read() -> None:
    url = "https://homes.example/listing/123456789/"
    body = f'<p>See <a href="{url}">{url}</a>.</p>'
    assert content_check_grounds("Documents", body, html=True) == ["payment_routing"]


def test_a_match_cannot_be_made_across_subject_and_body() -> None:
    """ "routing" ending the subject and "number" starting the body are two harmless words."""
    assert content_check_grounds("Question about routing", "number of pages", html=False) == []


def test_every_ground_is_reported_in_a_fixed_order() -> None:
    body = "Wire instructions below. You're approved at 6.5%."
    assert content_check_grounds("", body, html=False) == [
        "rate",
        "commitment",
        "payment_routing",
    ]
    assert list(CONTENT_CHECK_REASONS) == ["rate", "commitment", "payment_routing"]


EXCLUDED = [
    "Please send the statement showing the $10,000 deposit.",
    "We need the gift letter for your down payment.",
    "Please include all pages of each statement.",
    # `identifier`: its dotted pattern matches any email address or link ("summit.example").
    "Or send them to lf-ab12@mb-mail.summit.example.",
]


@pytest.mark.parametrize("text", EXCLUDED)
def test_the_drafter_only_grounds_do_not_block_a_person(text: str) -> None:
    # Positive control: the drafter's full scanner refuses each of these, so the exclusion is real.
    assert email_draft.regulatory_grounds(text) - {"rate", "commitment", "payment_routing"}
    assert content_check_grounds("Documents for your loan", text, html=False) == []


def test_the_footer_tag_does_not_block() -> None:
    """The `[LF-XXXX]` tag every Send ends with. (It trips no drafter ground either.)"""
    assert content_check_grounds("Documents", "Thanks,\nPat\n\n[LF-AB12]", html=False) == []


def test_the_helper_uses_the_drafters_own_patterns() -> None:
    """The same compiled objects, not copies: one list, one place."""
    patterns = dict(email_draft._SEND_CHECK_GROUNDS)
    assert patterns["rate"] is email_draft._RATE
    assert patterns["commitment"] is email_draft._COMMITMENT
    assert patterns["payment_routing"] is email_draft._ROUTING
    assert set(patterns) == set(CONTENT_CHECK_REASONS)


# --------------------------------------------------------------------------------------------- #
# Every current template, rendered with realistic data, through the send path
# --------------------------------------------------------------------------------------------- #
#: Common borrower documents whose catalog guidance does NOT trip the check.
_BORROWER_DOCS = ("pay_stub", "w2", "tax_return", "drivers_license", "gift_letter")
_PARTY_LIST = "- Payoff statement\n\n- Homeowner's insurance declarations page"
_IDENTIFICATION = "Borrower: Jordan Avery\nProperty: 12 Elm Street, Springfield\nLoan: LF-AB12"

_CONTEXT: dict[str, str] = {
    "borrower_first_name": "Jordan",
    "processor_name": "Pat Processor",
    "loan_reference": "LF-AB12",
    "document_list": render_document_block(_BORROWER_DOCS),
    "file_address_phrase": file_address_phrase("lf-ab12@mb-mail.summit.example"),
    "opening": plain_framing().opening,
    "bridge": plain_framing().bridge,
    "closing": plain_framing().closing,
    "secure_upload_block": secure_upload_block("https://app.example/u/abcDEF123xyz"),
    "status_summary": "Your appraisal has come back and the underwriter is reviewing your file.",
    "next_step": "We will be in touch once the review is done.",
    "condition_list": "- Letter of explanation for the March credit inquiry\n\n- Updated pay stub",
    "borrower_name": "Jordan Avery",
    "loan_identification": _IDENTIFICATION,
    "subject_line": "A question about your documents",
    "message_body": "Could you send the pay stub for the last two weeks of October?",
}


def _sent_text(key: TemplateKey, context: dict[str, str]) -> tuple[str, str]:
    """Rendered, then finalised and tagged exactly as `send_draft` does before it checks."""
    rendered = render(key, context)
    body = finalise_draft_body(
        rendered.body, borrower_first_name="Jordan", processor_name="Pat Processor"
    )
    outbound = build_outbound(
        LoanFile(display_id="LF-AB12"),
        address="lf-ab12@mb-mail.summit.example",
        subject=rendered.subject,
        body=body,
    )
    return outbound.subject, outbound.body


@pytest.mark.parametrize("key", list(TEMPLATES), ids=lambda key: f"{key.value}")
def test_every_current_template_is_not_blocked(key: TemplateKey) -> None:
    subject, body = _sent_text(key, _CONTEXT)
    assert content_check_grounds(subject, body, html=False) == []


def test_the_template_list_is_the_one_measured() -> None:
    """The seven current versions, so a new template or version is a decision to re-measure."""
    assert {(key.value, spec.version) for key, spec in TEMPLATES.items()} == {
        ("initial_documentation_request", "v5"),
        ("reminder_follow_up", "v3"),
        ("status_update", "v1"),
        ("condition_response_request", "v3"),
        ("document_request_third_party", "v1"),
        ("document_request_employer", "v1"),
        ("custom", "v1"),
    }


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known misfire, reported in LP-996 and not fixed there: the catalog guidance for bank, "
        "investment and retirement statements says 'the account number', which `_ROUTING` matches. "
        "Strict, so the fix turns this red and the marker has to come off."
    ),
)
@pytest.mark.parametrize(
    "document_type", ["bank_statement", "investment_account", "retirement_account"]
)
def test_a_request_for_statements_is_not_blocked(document_type: str) -> None:
    context = {**_CONTEXT, "document_list": render_document_block((document_type,))}
    subject, body = _sent_text(TemplateKey.INITIAL_DOCUMENTATION_REQUEST, context)
    assert content_check_grounds(subject, body, html=False) == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known misfire, reported in LP-996: asking a title company for its title commitment or "
        "its wire instructions trips `commitment` / `payment_routing`."
    ),
)
@pytest.mark.parametrize("label", ["Title commitment", "Wire instructions"])
def test_a_title_request_is_not_blocked(label: str) -> None:
    context = {**_CONTEXT, "document_list": f"- {label}"}
    subject, body = _sent_text(TemplateKey.DOCUMENT_REQUEST_THIRD_PARTY, context)
    assert content_check_grounds(subject, body, html=False) == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known misfire, found in LP-996's review: every borrower condition email (S3-04) says "
        "'The lender approved your loan with a few conditions', which trips `commitment`."
    ),
)
def test_a_borrower_condition_email_is_not_blocked() -> None:
    subject, body = render_borrower(
        first_name="Jordan",
        lines=[],
        due=None,
        upload_url=None,
        signer="Pat Processor",
        company="Summit Mortgage Processing",
    )
    assert content_check_grounds(subject, body, html=True) == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known misfire, found in LP-996's review: `_RATE` matches any percentage, so a processor's "
        "'100% of the gift funds' reads as a rate."
    ),
)
@pytest.mark.parametrize(
    "text",
    ["Please confirm the gift covers 100% of the funds.", "Owners of 25% or more must sign."],
)
def test_a_percentage_that_is_not_a_rate_is_not_blocked(text: str) -> None:
    assert content_check_grounds("Documents", text, html=False) == []


# --------------------------------------------------------------------------------------------- #
# send_draft
# --------------------------------------------------------------------------------------------- #
async def _send(
    db: AsyncSession,
    ready: Ready,
    *,
    body: str = RATE_BODY,
    transmit: bool = True,
    note: str | None = None,
    subject: str | None = None,
) -> Any:
    return await send_draft(
        db,
        loan_file=ready.loan_file,
        draft_id=ready.draft.id,
        recipient=TO,
        body=body,
        subject=subject,
        approver_user_id=ready.user.id,
        transmit=transmit,
        override_note=note,
    )


async def _evidence(db: AsyncSession, ready: Ready) -> list[CommunicationEvidence]:
    rows = await db.execute(
        select(CommunicationEvidence).where(
            CommunicationEvidence.communication_id == ready.draft.id
        )
    )
    return list(rows.scalars())


async def _activity(db: AsyncSession, ready: Ready) -> list[ActivityLog]:
    rows = await db.execute(
        select(ActivityLog).where(ActivityLog.loan_file_id == ready.loan_file.id)
    )
    return [row for row in rows.scalars() if row.activity_type.value == "communication_sent"]


async def test_no_note_refuses_and_records_nothing(db_session: AsyncSession) -> None:
    ready = await ready_to_send(db_session)
    before = ready.need.status
    with pytest.raises(ContentCheckError) as caught:
        await _send(db_session, ready)
    assert caught.value.grounds == ["rate"]
    assert not caught.value.note_too_short
    assert isinstance(caught.value, CannotSendError)
    assert ready.draft.status is CommunicationStatus.DRAFT
    assert ready.draft.send_requested_at is None
    assert ready.need.status is before
    assert await _evidence(db_session, ready) == []
    assert await _activity(db_session, ready) == []


async def test_the_subject_is_checked(db_session: AsyncSession) -> None:
    ready = await ready_to_send(db_session)
    with pytest.raises(ContentCheckError) as caught:
        await _send(
            db_session, ready, body="Please send your pay stubs.", subject="You're approved"
        )
    assert caught.value.grounds == ["commitment"]


async def test_an_html_body_split_by_tags_is_refused(db_session: AsyncSession) -> None:
    ready = await ready_to_send(db_session)
    ready.draft.body_format = BodyFormat.HTML
    with pytest.raises(ContentCheckError) as caught:
        # `<strong>`, which the sanitiser keeps; it strips `<b>`, which would join the word first.
        await _send(db_session, ready, body="<p>You are <strong>appro</strong>ved.</p>")
    assert caught.value.grounds == ["commitment"]


@pytest.mark.parametrize("note", ["too short", "   short    ", "         "])
async def test_a_short_note_is_refused(db_session: AsyncSession, note: str) -> None:
    ready = await ready_to_send(db_session)
    with pytest.raises(ContentCheckError) as caught:
        await _send(db_session, ready, note=note)
    assert caught.value.grounds == ["rate"]
    if note.strip():
        assert caught.value.note_too_short
        assert "at least 10 characters" in caught.value.message
    assert ready.draft.status is CommunicationStatus.DRAFT
    assert await _evidence(db_session, ready) == []


async def test_a_note_of_exactly_ten_characters_is_enough(db_session: AsyncSession) -> None:
    ready = await ready_to_send(db_session)
    sent = await _send(db_session, ready, note="  0123456789  ")
    assert sent.status is CommunicationStatus.QUEUED


async def test_a_valid_note_sends_and_records_the_override(db_session: AsyncSession) -> None:
    ready = await ready_to_send(db_session)
    with capture_logs() as logs:
        sent = await _send(db_session, ready, note=f"  {NOTE}  ")
    assert sent.status is CommunicationStatus.QUEUED
    assert sent.send_requested_at is not None
    [evidence] = await _evidence(db_session, ready)
    assert evidence.content_check_grounds == "rate"
    assert evidence.content_check_override_note == NOTE
    assert evidence.guardrail_fired is None
    # ONE "sent" row for one email, carrying the override; the note is not on it, because
    # `readonly.activity_logs` exposes summary and detail.
    [row] = await _activity(db_session, ready)
    assert row.summary == (
        "Sent a document request for 1 item(s). "
        "Sent despite the content check: Mentions an interest rate or APR."
    )
    assert row.actor_user_id == ready.user.id
    assert row.detail["content_check_grounds"] == ["rate"]
    assert row.detail["communication_id"] == str(ready.draft.id)
    assert NOTE not in row.summary
    assert NOTE not in repr(row.detail)
    # Positive control: the send logged something, and none of it carries the note.
    assert logs
    assert NOTE not in repr(logs)


async def test_several_grounds_are_all_recorded(db_session: AsyncSession) -> None:
    ready = await ready_to_send(db_session)
    await _send(db_session, ready, body="Approved at 6.5%; wire instructions follow.", note=NOTE)
    [evidence] = await _evidence(db_session, ready)
    assert evidence.content_check_grounds == "rate,commitment,payment_routing"


async def test_the_worst_case_activity_line_fits_its_column(db_session: AsyncSession) -> None:
    """All three reasons on one line; a long note is kept whole on the evidence row only."""
    ready = await ready_to_send(db_session)
    note = "The borrower asked for this in writing. " * 20
    await _send(db_session, ready, body="Approved at 6.5%; wire instructions follow.", note=note)
    [evidence] = await _evidence(db_session, ready)
    assert evidence.content_check_override_note == note.strip()
    [row] = await _activity(db_session, ready)
    limit = ActivityLog.__table__.c.summary.type.length
    assert limit == 256
    # Room for a two-digit item count too.
    assert len(row.summary) + 1 <= limit
    assert row.summary.endswith("or wire instructions.")


async def test_a_clean_send_ignores_a_note(db_session: AsyncSession) -> None:
    ready = await ready_to_send(db_session)
    sent = await _send(db_session, ready, body="Please send your pay stubs.", note=NOTE)
    assert sent.status is CommunicationStatus.QUEUED
    [evidence] = await _evidence(db_session, ready)
    assert evidence.content_check_grounds is None
    assert evidence.content_check_override_note is None
    [row] = await _activity(db_session, ready)
    assert row.summary == "Sent a document request for 1 item(s)"
    assert "content_check_grounds" not in row.detail


async def test_record_only_send_is_not_checked(db_session: AsyncSession) -> None:
    """ "I've sent it": the email already went from her own mail app."""
    ready = await ready_to_send(db_session)
    sent = await _send(db_session, ready, transmit=False)
    assert sent.status is CommunicationStatus.SENT
    [evidence] = await _evidence(db_session, ready)
    assert evidence.content_check_grounds is None
    assert evidence.content_check_override_note is None


# --------------------------------------------------------------------------------------------- #
# The API
# --------------------------------------------------------------------------------------------- #
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
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from app.tasks import outbound

    seen: list[str] = []
    monkeypatch.setattr(outbound.send_communication, "delay", seen.append)
    return seen


async def _post(client: AsyncClient, ready: Ready, **extra: Any) -> Any:
    from app.core.jwt import create_access_token

    return await client.post(
        f"/api/v1/loan-files/{ready.loan_file.display_id}/outbound/draft/{ready.draft.id}/send",
        json={"recipient": TO, "body": RATE_BODY, "transmit": True, **extra},
        headers={"Authorization": f"Bearer {create_access_token(ready.user.id)}"},
    )


async def test_api_content_check_is_a_structured_409(
    db: AsyncSession, client: AsyncClient, enqueued: list[str]
) -> None:
    ready = await ready_to_send(db)
    response = await _post(client, ready, body="Approved at 6.5%.")
    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "type": "conflict",
            "message": "This email can't be sent as written.",
            "data": {
                "code": "content_check",
                "message": "This email can't be sent as written.",
                "reasons": [
                    {"ground": "rate", "text": "Mentions an interest rate or APR"},
                    {
                        "ground": "commitment",
                        "text": "Uses approval or denial wording "
                        "(for example approved, denied, cleared to close)",
                    },
                ],
                "override_allowed": True,
                "note_too_short": False,
                "min_note_length": 10,
            },
        }
    }
    assert enqueued == []
    await db.refresh(ready.draft)
    assert ready.draft.status is CommunicationStatus.DRAFT


async def test_api_short_note_says_how_long(
    db: AsyncSession, client: AsyncClient, enqueued: list[str]
) -> None:
    ready = await ready_to_send(db)
    response = await _post(client, ready, override_note="ok")
    assert response.status_code == 409
    data = response.json()["error"]["data"]
    assert data["message"] == (
        "This email can't be sent as written. Add a note of at least 10 characters to send anyway."
    )
    assert [reason["ground"] for reason in data["reasons"]] == ["rate"]
    assert data["note_too_short"] is True
    assert data["min_note_length"] == 10
    assert enqueued == []


async def test_api_override_sends(
    db: AsyncSession, client: AsyncClient, enqueued: list[str]
) -> None:
    ready = await ready_to_send(db)
    response = await _post(client, ready, override_note=NOTE)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"
    assert enqueued == [str(ready.draft.id)]


async def test_api_other_refusals_keep_their_shape(
    db: AsyncSession, client: AsyncClient, enqueued: list[str]
) -> None:
    ready = await ready_to_send(db, with_domain=False)
    response = await _post(client, ready)
    assert response.status_code == 409
    assert response.json() == {
        "error": {"type": "conflict", "message": "This company can't send email from the app yet."}
    }


async def test_the_evidence_api_shows_the_override(
    db: AsyncSession, client: AsyncClient, enqueued: list[str]
) -> None:
    from app.core.jwt import create_access_token

    ready = await ready_to_send(db)
    assert (await _post(client, ready, override_note=NOTE)).status_code == 200
    clean = await ready_to_send(db)
    assert (await _post(client, clean, body="Please send your pay stubs.")).status_code == 200
    seen = {}
    for each in (ready, clean):
        response = await client.get(
            f"/api/v1/loan-files/{each.loan_file.display_id}/evidence",
            headers={"Authorization": f"Bearer {create_access_token(each.user.id)}"},
        )
        assert response.status_code == 200, response.text
        [row] = [r for r in response.json() if r["event"] == "sent"]
        seen[each is ready] = (row["content_check_grounds"], row["content_check_override_note"])
    assert seen[True] == (["rate"], NOTE)
    assert seen[False] == ([], None)
