"""LP-997 — what the Communication tab's Send button needs from the backend.

- `company_mail_domains.sending_enabled`: real email from the app, per company, off by default. The
  Send endpoint refuses while it is off, and `can_send` tells the dialog the same thing.
- `can_send` on the message detail: the one answer for "offer Send", shared with the refusal
  (`email_send.transmit_blocker`), including "not a condition draft".
- `send_requested_at` on the message detail and the timeline row, which the screens time from.
- The frontend's copy of `NOT_CONFIRMED_PREFIX`.
- The condition "Mark as sent" refusal says where the email actually is.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.core.config import settings
from app.models.communication import NOT_CONFIRMED_PREFIX, CommunicationStatus
from app.models.user import User
from app.scripts import set_email_sending as script
from app.services.condition_drafts import DraftRefused, mark_sent
from app.services.email_send import CannotSendError, send_draft
from app.services.mail_domain import MailDomainError, set_email_sending
from app.services.message_detail import message_detail
from app.services.timeline import build_timeline
from sqlalchemy.ext.asyncio import AsyncSession
from tests.mail_address import sending_switched_on
from tests.outbound_send import Ready, ready_to_send

TO = "borrower@example.test"
OFF = "Sending email from the app isn't switched on for this company yet."


@pytest.fixture(autouse=True)
def _can_send(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mail_transport", "smtp")


async def _send(db: AsyncSession, ready: Ready, *, transmit: bool = True) -> None:
    await send_draft(
        db,
        loan_file=ready.loan_file,
        draft_id=ready.draft.id,
        recipient=TO,
        body="Please send your bank statements.",
        approver_user_id=ready.user.id,
        transmit=transmit,
    )


async def _can_send_flag(db: AsyncSession, ready: Ready) -> bool:
    detail = await message_detail(
        db, loan_file=ready.loan_file, communication_id=ready.draft.id, reader=ready.user
    )
    assert detail is not None
    return detail.can_send


# --------------------------------------------------------------------------------------------- #
# The flag
# --------------------------------------------------------------------------------------------- #
async def test_sending_is_off_until_switched_on(db_session: AsyncSession) -> None:
    ready = await ready_to_send(db_session)
    await set_email_sending(db_session, company_id=ready.company.id, enabled=False)
    assert await sending_switched_on(db_session, ready.company.id) is False
    assert await _can_send_flag(db_session, ready) is False
    with pytest.raises(CannotSendError, match=re.escape(OFF)):
        await _send(db_session, ready)
    assert ready.draft.status is CommunicationStatus.DRAFT

    # The positive control: switched on, the same draft can be sent.
    await set_email_sending(db_session, company_id=ready.company.id, enabled=True)
    assert await _can_send_flag(db_session, ready) is True
    await _send(db_session, ready)
    assert ready.draft.status is CommunicationStatus.QUEUED


async def test_a_new_domain_starts_with_sending_off(db_session: AsyncSession) -> None:
    ready = await ready_to_send(db_session, with_domain=False)
    from tests.mail_address import link_mail_domain

    await link_mail_domain(db_session, ready.company.id)
    assert await sending_switched_on(db_session, ready.company.id) is False


async def test_mark_as_sent_works_with_sending_off(db_session: AsyncSession) -> None:
    ready = await ready_to_send(db_session)
    await set_email_sending(db_session, company_id=ready.company.id, enabled=False)
    await _send(db_session, ready, transmit=False)
    assert ready.draft.status is CommunicationStatus.SENT


async def test_sending_cannot_be_switched_on_without_an_active_domain(
    db_session: AsyncSession,
) -> None:
    ready = await ready_to_send(db_session, with_domain=False)
    with pytest.raises(MailDomainError, match="no active mail domain"):
        await set_email_sending(db_session, company_id=ready.company.id, enabled=True)


async def test_the_command_switches_it_by_company_name(db_session: AsyncSession) -> None:
    ready = await ready_to_send(db_session)
    company, row = await script.run(db_session, company_ref=str(ready.company.id), enabled=False)
    assert row.sending_enabled is False
    assert "sending from the app off" in script.describe(company, row)
    _, row = await script.run(db_session, company_ref=str(ready.company.id), enabled=True)
    assert row.sending_enabled is True


# --------------------------------------------------------------------------------------------- #
# can_send: the same reasons the Send endpoint refuses on
# --------------------------------------------------------------------------------------------- #
async def test_no_send_button_without_a_mail_sender(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = await ready_to_send(db_session)
    assert await _can_send_flag(db_session, ready) is True
    monkeypatch.setattr(settings, "mail_transport", None)
    assert await _can_send_flag(db_session, ready) is False
    with pytest.raises(CannotSendError, match="not set up here"):
        await _send(db_session, ready)


@pytest.fixture
def _mocked_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """The conditions fixtures read a round; the model is mocked, as in the condition tests."""
    from app.services import condition_reading
    from tests.conditions.reading_fixture import fake_complete

    monkeypatch.setattr(condition_reading, "complete", fake_complete())


@pytest.mark.usefixtures("_mocked_model")
async def test_a_condition_draft_is_not_sent_from_the_communication_tab(
    db_session: AsyncSession,
) -> None:
    from tests.conditions.test_condition_drafts import _confirmed, _drafts
    from tests.mail_address import link_mail_domain

    loan_file, _, _, actor = await _confirmed(db_session)
    await link_mail_domain(db_session, loan_file.company_id)
    await set_email_sending(db_session, company_id=loan_file.company_id, enabled=True)
    drafts = await _drafts(db_session, loan_file)
    for key in ("borrower", "question 6178"):
        _, message = drafts[key]
        reader = await db_session.get(User, actor)
        assert reader is not None
        detail = await message_detail(
            db_session, loan_file=loan_file, communication_id=message.id, reader=reader
        )
        assert detail is not None and detail.is_editable  # the control: it is a live draft
        assert detail.can_send is False
        with pytest.raises(CannotSendError, match="Condition emails can't be sent from the app"):
            await send_draft(
                db_session,
                loan_file=loan_file,
                draft_id=message.id,
                recipient=TO,
                body=message.body or "x",
                approver_user_id=actor,
                transmit=True,
            )
        assert message.status is CommunicationStatus.DRAFT


async def test_a_sent_message_offers_no_send_and_carries_its_send_time(
    db_session: AsyncSession,
) -> None:
    ready = await ready_to_send(db_session)
    await _send(db_session, ready)
    detail = await message_detail(
        db_session, loan_file=ready.loan_file, communication_id=ready.draft.id, reader=ready.user
    )
    assert detail is not None
    assert detail.can_send is False
    assert detail.send_requested_at == ready.draft.send_requested_at
    assert detail.send_requested_at is not None


# --------------------------------------------------------------------------------------------- #
# The timeline row
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("transmit", [True, False])
async def test_the_timeline_carries_the_send_time_only_for_a_send(
    db_session: AsyncSession, transmit: bool
) -> None:
    ready = await ready_to_send(db_session)
    await _send(db_session, ready, transmit=transmit)
    entries, _ = await build_timeline(db_session, loan_file=ready.loan_file)
    row = next(entry for entry in entries if entry.id == ready.draft.id)
    if transmit:
        assert ready.draft.send_requested_at is not None
        assert row.detail["send_requested_at"] == ready.draft.send_requested_at.isoformat()
    else:
        assert row.detail["send_requested_at"] is None


# --------------------------------------------------------------------------------------------- #
# The frontend's copy of the "not confirmed" prefix
# --------------------------------------------------------------------------------------------- #
def test_the_frontend_reads_the_same_not_confirmed_prefix() -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "frontend"
        / "lib"
        / "communication"
        / "send-status.ts"
    ).read_text(encoding="utf-8")
    found = re.search(r'export const NOT_CONFIRMED_PREFIX = "([^"]*)";', source)
    assert found is not None, "send-status.ts no longer declares NOT_CONFIRMED_PREFIX"
    assert found.group(1) == NOT_CONFIRMED_PREFIX


# --------------------------------------------------------------------------------------------- #
# The condition "Mark as sent" refusal (review finding 8)
# --------------------------------------------------------------------------------------------- #
@pytest.mark.usefixtures("_mocked_model")
@pytest.mark.parametrize(
    ("status", "reason"),
    [
        ("queued", "This email is already being sent from the app."),
        ("sending", "This email is already being sent from the app."),
        ("sent", "This email was already marked sent."),
        ("delivered", "This email was already sent and delivered."),
        ("failed", "This email was sent from the app and could not be delivered."),
    ],
)
async def test_mark_as_sent_says_where_the_email_already_is(
    db_session: AsyncSession, status: str, reason: str
) -> None:
    from tests.conditions.test_condition_drafts import _confirmed, _drafts

    loan_file, _, _, actor = await _confirmed(db_session)
    draft, message = (await _drafts(db_session, loan_file))["question 6178"]
    message.status = CommunicationStatus(status)
    await db_session.flush()
    with pytest.raises(DraftRefused) as refused:
        await mark_sent(db_session, loan_file=loan_file, draft=draft, actor_user_id=actor)
    assert refused.value.reason == reason
