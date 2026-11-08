"""LP-1013 — automatic follow-ups: when one is due, the job that sends it, the reply that pauses it,
and the API LP-1014 builds on.

Times: each test picks a fixed weekday moment in the recent past (14:00 New York, the follow-up's
time of day), and back-dates the original's Send to four days before it, so the 3-day interval's day
has come and the rate limit (which reads the real clock) sees nothing recent. The due rule's own
tests use fixed dates around the November 2026 daylight-saving change.

The session joins the test transaction with savepoints, as LP-994's tests do, so the job's commit
lands and the worker can then send the reminder it queued.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from email import message_from_bytes, policy
from email.message import EmailMessage, Message
from email.policy import default as email_policy
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from app.core.config import settings
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.main import app
from app.models import Company, LoanProgram, User, UserRole
from app.models.activity_log import ActivityLog, ActivityType
from app.models.base import utcnow
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
    FollowUpStatus,
)
from app.models.communication_evidence import CommunicationEvidence
from app.models.communication_needs_item import CommunicationNeedsItem
from app.models.company_mail_domain import CompanyMailDomain, MailDomainStatus
from app.models.inbound_message import InboundMessage, InboundRoutingState
from app.models.needs_item import NeedsItem, NeedsItemOrigin, NeedsItemStatus
from app.models.suppressed_address import SuppressionReason
from app.services.bounce_handling import suppress_address
from app.services.email_send import FollowUp, send_draft
from app.services.follow_ups import (
    Decision,
    due_moment,
    due_moment_sql,
    evaluate,
    has_reply_since,
    pause_for_reply,
    reply_subject,
    thread_message_id,
)
from app.services.inbound_ingest import process_raw_message
from app.services.loan_files import create_loan_file
from app.storage import get_storage_backend
from app.tasks import follow_ups as job
from app.tasks import outbound
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from tests.outbound_send import FakeSender, FakeStorage, Ready, ready_to_send

TO = "borrower@example.test"
TITLE = "title@title-co.example.test"
SUBJECT = "Documents for your loan"
NEW_YORK = ZoneInfo("America/New_York")
LOS_ANGELES = ZoneInfo("America/Los_Angeles")


def _last(weekday: int, hour: int, minute: int = 0) -> datetime:
    """The most recent `weekday` (Mon=0) at least two days ago, at `hour:minute` New York."""
    day = datetime.now(NEW_YORK).date() - timedelta(days=2)
    while day.weekday() != weekday:
        day -= timedelta(days=1)
    return datetime.combine(day, time(hour, minute), tzinfo=NEW_YORK)


WED_2PM = _last(2, 14)
DEFAULT_FOLLOW_UP = FollowUp(time=time(14, 0), tz="America/New_York")


# --------------------------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def db(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    connection = await test_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest.fixture(autouse=True)
def _storage_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "mail_transport", "smtp")  # a server that can send
    get_storage_backend.cache_clear()
    yield
    get_storage_backend.cache_clear()


@pytest.fixture
def sender(monkeypatch: pytest.MonkeyPatch) -> FakeSender:
    monkeypatch.setattr(settings, "mail_transport", "smtp")  # for send_draft's own check
    fake = FakeSender()
    monkeypatch.setattr(outbound, "get_mail_sender", lambda: fake)
    return fake


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> FakeStorage:
    fake = FakeStorage()
    monkeypatch.setattr(outbound, "get_mail_storage", lambda: fake)
    return fake


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    monkeypatch.setattr(outbound.send_communication, "delay", seen.append)
    return seen


@dataclass
class Original:
    ready: Ready
    row: Communication
    needs: list[NeedsItem]


async def _need(db: AsyncSession, ready: Ready, title: str, needs_type: str) -> NeedsItem:
    need = NeedsItem(
        loan_file_id=ready.loan_file.id,
        title=title,
        needs_type=needs_type,
        origin=NeedsItemOrigin.FINDING,
    )
    db.add(need)
    await db.flush()
    return need


async def _original(
    db: AsyncSession,
    *,
    needs: int = 1,
    recipient: str = TO,
    follow_up: FollowUp | None = DEFAULT_FOLLOW_UP,
    at: datetime = WED_2PM,
    subject: str = SUBJECT,
    ready: Ready | None = None,
) -> Original:
    """An email sent with Send, gone out (`sent`, an SES id), its clock four days before `at`.

    `needs=0` is a general email (no needs); 1 is `ready_to_send`'s bank statements; 2 adds a W-2.
    """
    ready = ready or await ready_to_send(db)
    linked: list[NeedsItem] = []
    if needs == 0:
        draft = Communication(
            loan_file_id=ready.loan_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationStatus.DRAFT,
            subject=subject,
            body="Can you confirm the closing date?",
        )
        db.add(draft)
        await db.flush()
    else:
        draft = Communication(
            loan_file_id=ready.loan_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationStatus.DRAFT,
            subject=subject,
            body="Please send these.",
            template_key="initial_documentation_request",
            party="borrower",
        )
        db.add(draft)
        await db.flush()
        linked = [ready.need] if ready.draft is not None and needs >= 1 else []
        if needs == 2:
            linked.append(await _need(db, ready, "W-2", "w2"))
        for need in linked:
            db.add(CommunicationNeedsItem(communication_id=draft.id, needs_item_id=need.id))
        await db.flush()
    await send_draft(
        db,
        loan_file=ready.loan_file,
        draft_id=draft.id,
        recipient=recipient,
        body=draft.body or "",
        subject=subject,
        approver_user_id=ready.user.id,
        transmit=True,
        follow_up=follow_up,
    )
    draft.status = CommunicationStatus.SENT
    draft.external_message_id = f"0100018f-{uuid4().hex[:12]}"
    await _backdate(db, ready, to=at - timedelta(days=4))
    draft.follow_up_clock_at = at - timedelta(days=4) if follow_up else None
    await db.commit()
    return Original(ready, draft, linked)


async def _backdate(db: AsyncSession, ready: Ready, *, to: datetime) -> None:
    """Every outbound email on the file sent at `to`, so the rate limit sees nothing recent."""
    rows = (
        await db.execute(
            select(Communication).where(
                Communication.loan_file_id == ready.loan_file.id,
                Communication.direction == CommunicationDirection.OUTBOUND,
            )
        )
    ).scalars()
    for row in rows:
        if row.send_requested_at is not None:
            row.send_requested_at = to
        if row.sent_at is not None or row.status is CommunicationStatus.SENT:
            row.sent_at = to
    await db.flush()


async def _reminders(db: AsyncSession, original: Communication) -> list[Communication]:
    return list(
        (
            await db.execute(
                select(Communication)
                .where(Communication.follow_up_of_id == original.id)
                .order_by(Communication.created_at)
            )
        )
        .scalars()
        .all()
    )


async def _wire(db: AsyncSession, reminder: Communication, storage: FakeStorage) -> Message:
    """Have the worker send the queued reminder, and return the email as sent."""
    assert await outbound._send_communication(db, str(reminder.id)) == "sent"
    await db.refresh(reminder)
    assert reminder.raw_storage_path is not None
    return message_from_bytes(storage.saved[reminder.raw_storage_path], policy=policy.SMTP)


def _text(message: Message) -> str:
    assert isinstance(message, EmailMessage)
    part = message.get_body(preferencelist=("plain",))
    assert part is not None
    return str(part.get_content()).replace("\r\n", "\n")


async def _user(db: AsyncSession, company: Company, first: str) -> User:
    user = User(
        company_id=company.id,
        email=f"{first.lower()}-{uuid4().hex[:6]}@example.test",
        hashed_password="x",  # pragma: allowlist secret
        first_name=first,
        last_name="Clicker",
        role=UserRole.PROCESSOR,
    )
    db.add(user)
    await db.flush()
    return user


# --------------------------------------------------------------------------------------------- #
# When a reminder is due — `evaluate`, each condition on its own
# --------------------------------------------------------------------------------------------- #
async def test_due_when_every_condition_holds(db: AsyncSession) -> None:
    original = await _original(db)
    assert await evaluate(db, original.row, now=WED_2PM) is Decision.DUE


@pytest.mark.parametrize(
    "status",
    [FollowUpStatus.OFF, FollowUpStatus.PAUSED, FollowUpStatus.FINISHED, FollowUpStatus.STOPPED],
)
async def test_not_due_unless_on(db: AsyncSession, status: FollowUpStatus) -> None:
    original = await _original(db)
    original.row.follow_up_status = status
    assert await evaluate(db, original.row, now=WED_2PM) is Decision.WAIT


async def test_a_failed_original_stops(db: AsyncSession) -> None:
    original = await _original(db)
    original.row.status = CommunicationStatus.FAILED
    assert await evaluate(db, original.row, now=WED_2PM) is Decision.STOP


async def test_an_original_not_yet_sent_waits(db: AsyncSession) -> None:
    original = await _original(db)
    original.row.status = CommunicationStatus.SENDING
    assert await evaluate(db, original.row, now=WED_2PM) is Decision.WAIT


async def test_a_delivered_original_is_due(db: AsyncSession) -> None:
    original = await _original(db)
    original.row.status = CommunicationStatus.DELIVERED
    assert await evaluate(db, original.row, now=WED_2PM) is Decision.DUE


async def test_count_reached_waits(db: AsyncSession) -> None:
    original = await _original(db)
    original.row.follow_up_auto_sent = 2
    assert await evaluate(db, original.row, now=WED_2PM) is Decision.WAIT


async def test_the_interval_is_counted_in_days(db: AsyncSession) -> None:
    """Clock Monday 23:00, 3 days: due Thursday at 14:00, her time, though 72 hours from the clock
    would be Thursday 23:00."""
    original = await _original(db)
    original.row.follow_up_clock_at = WED_2PM - timedelta(days=2, hours=-9)  # Monday 23:00
    thursday_2pm = WED_2PM + timedelta(days=1)
    assert (
        await evaluate(db, original.row, now=thursday_2pm - timedelta(minutes=1)) is Decision.WAIT
    )
    assert await evaluate(db, original.row, now=thursday_2pm) is Decision.DUE


async def test_due_at_the_chosen_time_not_before(db: AsyncSession) -> None:
    """09:30 New York: not due at 09:29 on the day, due at 09:30."""
    at = _last(2, 9, 30)
    original = await _original(
        db, at=at, follow_up=FollowUp(time=time(9, 30), tz="America/New_York")
    )
    original.row.follow_up_clock_at = at - timedelta(days=3)  # Sunday → due Wednesday
    assert await evaluate(db, original.row, now=at - timedelta(minutes=1)) is Decision.WAIT
    assert await evaluate(db, original.row, now=at) is Decision.DUE


def _row(
    clock: datetime, *, days: int = 3, at: time = time(9, 30), tz: str = "America/New_York"
) -> Communication:
    return Communication(
        follow_up_clock_at=clock,
        follow_up_interval_days=days,
        follow_up_time=at,
        follow_up_tz=tz,
    )


def _ny(day: date, hour: int = 10, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=NEW_YORK)


@pytest.mark.parametrize(
    ("clock_day", "due_day"),
    [
        (date(2026, 10, 13), date(2026, 10, 16)),  # Tuesday → Friday
        (date(2026, 10, 14), date(2026, 10, 19)),  # Wednesday → Saturday → Monday
        (date(2026, 10, 15), date(2026, 10, 19)),  # Thursday → Sunday → Monday
        (date(2026, 10, 16), date(2026, 10, 19)),  # Friday → Monday
    ],
)
def test_a_weekend_due_day_moves_to_monday(clock_day: date, due_day: date) -> None:
    assert due_moment(_row(_ny(clock_day))) == datetime.combine(
        due_day, time(9, 30), tzinfo=NEW_YORK
    )


def test_her_time_zone_is_honoured() -> None:
    """Wednesday 20:00 in Los Angeles is already Thursday in UTC and New York. One day later is
    Thursday 09:30 LOS ANGELES (16:30 UTC), not Friday, and not 09:30 anywhere else."""
    clock = datetime(2026, 10, 14, 20, 0, tzinfo=LOS_ANGELES)
    due = due_moment(_row(clock, days=1, tz="America/Los_Angeles"))
    assert due == datetime(2026, 10, 15, 9, 30, tzinfo=LOS_ANGELES)
    assert due is not None and due.astimezone(UTC) == datetime(2026, 10, 15, 16, 30, tzinfo=UTC)


def test_daylight_saving_keeps_the_local_time() -> None:
    """Clocks go back Sunday 1 November 2026. Friday 30 October 09:30 EDT is 13:30 UTC; four days on
    is Tuesday 3 November, and 09:30 there is EST, 14:30 UTC. 24-hour days would say 08:30."""
    clock = datetime(2026, 10, 30, 9, 30, tzinfo=NEW_YORK)
    due = due_moment(_row(clock, days=4))
    assert due is not None
    assert due.astimezone(NEW_YORK).time() == time(9, 30)
    assert due.astimezone(UTC) == datetime(2026, 11, 3, 14, 30, tzinfo=UTC)
    assert clock.astimezone(UTC).hour == 13


@pytest.mark.parametrize(
    ("clock", "days", "at", "tz"),
    [
        (datetime(2026, 10, 13, 10, 0, tzinfo=NEW_YORK), 3, time(9, 30), "America/New_York"),
        (datetime(2026, 10, 14, 10, 0, tzinfo=NEW_YORK), 3, time(9, 30), "America/New_York"),
        (datetime(2026, 10, 15, 23, 59, tzinfo=NEW_YORK), 3, time(0, 0), "America/New_York"),
        (datetime(2026, 10, 14, 20, 0, tzinfo=LOS_ANGELES), 1, time(9, 30), "America/Los_Angeles"),
        (datetime(2026, 10, 30, 9, 30, tzinfo=NEW_YORK), 4, time(9, 30), "America/New_York"),
        (datetime(2026, 10, 23, 18, 0, tzinfo=UTC), 7, time(17, 45), "Europe/London"),
        (datetime(2026, 11, 6, 3, 0, tzinfo=UTC), 30, time(23, 15), "Asia/Kolkata"),
    ],
)
async def test_the_jobs_sql_agrees_with_the_rule(
    db: AsyncSession, clock: datetime, days: int, at: time, tz: str
) -> None:
    """The job picks and orders by `due_moment_sql`; it must say what `due_moment` says."""
    original = await _original(db)
    row = original.row
    row.follow_up_clock_at, row.follow_up_interval_days = clock, days
    row.follow_up_time, row.follow_up_tz = at, tz
    await db.flush()
    in_sql = await db.scalar(select(due_moment_sql()).where(Communication.id == row.id))
    assert in_sql == due_moment(row)


async def test_all_needs_arrived_finishes(db: AsyncSession) -> None:
    original = await _original(db, needs=2)
    for need in original.needs:
        need.status = NeedsItemStatus.RECEIVED
    assert await evaluate(db, original.row, now=WED_2PM) is Decision.FINISH


async def test_one_need_still_requested_is_due(db: AsyncSession) -> None:
    original = await _original(db, needs=2)
    original.needs[0].status = NeedsItemStatus.VERIFIED
    assert await evaluate(db, original.row, now=WED_2PM) is Decision.DUE


async def test_a_rejected_need_is_still_waited_for(db: AsyncSession) -> None:
    original = await _original(db)
    original.needs[0].status = NeedsItemStatus.REJECTED
    assert await evaluate(db, original.row, now=WED_2PM) is Decision.DUE


async def test_a_general_email_is_never_finished_by_needs(db: AsyncSession) -> None:
    original = await _original(db, needs=0)
    assert await evaluate(db, original.row, now=WED_2PM) is Decision.DUE


async def test_a_reminder_is_never_itself_due(db: AsyncSession) -> None:
    original = await _original(db)
    original.row.follow_up_of_id = uuid4()
    assert await evaluate(db, original.row, now=WED_2PM) is Decision.WAIT


# --------------------------------------------------------------------------------------------- #
# Turning it on with the Send
# --------------------------------------------------------------------------------------------- #
async def test_send_with_follow_up_turns_it_on_from_the_send(db: AsyncSession) -> None:
    ready = await ready_to_send(db)
    row = await send_draft(
        db,
        loan_file=ready.loan_file,
        draft_id=ready.draft.id,
        recipient=TO,
        body="Please send.",
        approver_user_id=ready.user.id,
        transmit=True,
        follow_up=FollowUp(interval_days=5, max_auto=4),
    )
    assert row.follow_up_status is FollowUpStatus.ON
    assert (row.follow_up_interval_days, row.follow_up_max_auto) == (5, 4)
    assert row.follow_up_clock_at == row.send_requested_at is not None
    # No time given: the moment she sent, to the minute, in the default time zone.
    assert row.follow_up_tz == "America/New_York"
    sent_local = row.send_requested_at.astimezone(NEW_YORK)
    assert row.follow_up_time == time(sent_local.hour, sent_local.minute)


async def test_send_with_a_chosen_time_and_zone(db: AsyncSession) -> None:
    ready = await ready_to_send(db)
    row = await send_draft(
        db,
        loan_file=ready.loan_file,
        draft_id=ready.draft.id,
        recipient=TO,
        body="Please send.",
        approver_user_id=ready.user.id,
        transmit=True,
        follow_up=FollowUp(time=time(8, 15), tz="America/Los_Angeles"),
    )
    assert (row.follow_up_time, row.follow_up_tz) == (time(8, 15), "America/Los_Angeles")


async def test_the_company_check_runs_once_per_send(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding 8: the refusal's code was read first and `transmit_blocker` then asked the
    same company question again."""
    from app.services import email_send

    calls: list[object] = []
    real = email_send.company_send_blocker

    async def counting(*args: object, **kwargs: object) -> str | None:
        calls.append(kwargs)
        return await real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(email_send, "company_send_blocker", counting)
    ready = await ready_to_send(db)
    await send_draft(
        db,
        loan_file=ready.loan_file,
        draft_id=ready.draft.id,
        recipient=TO,
        body="Please send.",
        approver_user_id=ready.user.id,
        transmit=True,
    )
    assert len(calls) == 1


async def test_follow_up_is_ignored_without_transmit(db: AsyncSession) -> None:
    ready = await ready_to_send(db)
    row = await send_draft(
        db,
        loan_file=ready.loan_file,
        draft_id=ready.draft.id,
        recipient=TO,
        body="Please send.",
        approver_user_id=ready.user.id,
        transmit=False,
        follow_up=FollowUp(),
    )
    assert row.status is CommunicationStatus.SENT
    assert row.follow_up_status is FollowUpStatus.OFF
    assert row.follow_up_clock_at is None


def test_follow_up_settings_are_bounded() -> None:
    with pytest.raises(ValueError):
        FollowUp(interval_days=0)
    with pytest.raises(ValueError):
        FollowUp(max_auto=11)
    with pytest.raises(ValueError):
        FollowUp(tz="America/Nowhere")


def test_subject_and_thread_id() -> None:
    assert reply_subject("Documents") == "Re: Documents"
    assert reply_subject("Re: Documents") == "Re: Documents"
    assert reply_subject("RE: Documents") == "RE: Documents"
    assert thread_message_id("0100abc") == "<0100abc@email.amazonses.com>"
    assert thread_message_id("<x@mb-mail.localhost>") == "<x@mb-mail.localhost>"
    assert thread_message_id(None) is None


# --------------------------------------------------------------------------------------------- #
# The job
# --------------------------------------------------------------------------------------------- #
async def test_the_document_reminder(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage, enqueued: list[str]
) -> None:
    original = await _original(db, needs=2)
    w2 = original.needs[1]
    w2.status = NeedsItemStatus.RECEIVED
    await db.commit()

    outcomes = await job.send_follow_ups(db, now=WED_2PM)
    assert outcomes == {"sent": 1}
    [reminder] = await _reminders(db, original.row)
    assert enqueued == [str(reminder.id)]
    assert reminder.template_key == "reminder_follow_up"
    assert reminder.template_version == "v4"
    assert reminder.status is CommunicationStatus.QUEUED
    assert reminder.initiated_by_user_id is None

    await db.refresh(original.row)
    assert original.row.follow_up_auto_sent == 1
    assert original.row.follow_up_clock_at == WED_2PM
    assert original.row.follow_up_status is FollowUpStatus.ON

    wire = await _wire(db, reminder, storage)
    ready = original.ready
    address = f"{ready.loan_file.display_id.lower()}@{ready.domain}"
    assert wire["From"] == f'"Pat Processor, Summit Mortgage Processing" <{address}>'
    assert wire["Cc"] == ready.user.email
    assert wire["To"] == TO
    assert wire["Subject"] == f"Re: {SUBJECT}"
    expected_id = f"<{original.row.external_message_id}@email.amazonses.com>"
    assert wire["In-Reply-To"] == expected_id
    assert wire["References"] == expected_id
    assert wire["Auto-Submitted"] == "auto-generated"
    assert wire["Precedence"] is None
    assert wire["X-Auto-Response-Suppress"] is None

    body = _text(wire)
    assert "Just following up. We've received your W-2, thank you." in body
    assert "- Bank statements" in body
    waiting = body.split("still waiting on the following:")[1].split("You can reply")[0].strip()
    assert waiting == "- Bank statements — the two most recent months"
    assert (
        "This is an automatic reminder from Summit Mortgage Processing's loan file system. "
        "Replies go straight to Pat Processor." in body
    )
    assert "Pat Processor\n\nThis is an automatic reminder" in body

    activity = (
        (
            await db.execute(
                select(ActivityLog).where(
                    ActivityLog.loan_file_id == ready.loan_file.id,
                    ActivityLog.activity_type == ActivityType.COMMUNICATION_SENT,
                )
            )
        )
        .scalars()
        .all()
    )
    summaries = {
        a.summary for a in activity if (a.detail or {}).get("communication_id") == str(reminder.id)
    }
    assert summaries == {"Automatic reminder sent (for Pat Processor)"}


async def test_the_second_reminder_lists_only_what_is_still_missing(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage, enqueued: list[str]
) -> None:
    first_at, second_at, third_at = (WED_2PM - timedelta(days=d) for d in (14, 7, 0))
    original = await _original(db, needs=2, at=first_at)
    assert await job.send_follow_ups(db, now=first_at) == {"sent": 1}
    first = (await _reminders(db, original.row))[0]
    body = _text(await _wire(db, first, storage))
    assert "- Bank statements" in body and "- W-2s" in body
    assert "We've received" not in body

    original.needs[0].status = NeedsItemStatus.RECEIVED  # bank statements arrive
    original.row.follow_up_clock_at = second_at - timedelta(days=4)
    await _backdate(db, original.ready, to=second_at - timedelta(days=4))
    await db.commit()
    assert await job.send_follow_ups(db, now=second_at) == {"sent": 1}
    second = (await _reminders(db, original.row))[1]
    body = _text(await _wire(db, second, storage))
    assert "We've received your bank statement, thank you." in body
    waiting = body.split("still waiting on the following:")[1].split("You can reply")[0].strip()
    assert waiting == "- W-2s — the last two years"

    await db.refresh(original.row)
    assert original.row.follow_up_auto_sent == 2
    # Count reached: no third.
    original.row.follow_up_clock_at = third_at - timedelta(days=4)
    await _backdate(db, original.ready, to=third_at - timedelta(days=4))
    await db.commit()
    assert await job.send_follow_ups(db, now=third_at) == {}
    assert len(await _reminders(db, original.row)) == 2


async def test_a_reply_subject_is_not_doubled(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage, enqueued: list[str]
) -> None:
    original = await _original(db, subject="Re: Your title commitment")
    await job.send_follow_ups(db, now=WED_2PM)
    [reminder] = await _reminders(db, original.row)
    assert (await _wire(db, reminder, storage))["Subject"] == "Re: Your title commitment"


async def test_the_general_reminder(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage, enqueued: list[str]
) -> None:
    original = await _original(db, needs=0, recipient=TITLE, subject="Closing date")
    assert await job.send_follow_ups(db, now=WED_2PM) == {"sent": 1}
    [reminder] = await _reminders(db, original.row)
    assert reminder.template_key == "follow_up_general"
    wire = await _wire(db, reminder, storage)
    assert wire["Subject"] == "Re: Closing date"
    assert wire["To"] == TITLE
    body = _text(wire)
    assert body.startswith(
        "Hello there,\n\nJust following up on my email below. "
        "Could you let me know when you get a chance?"
    )
    assert "still waiting" not in body
    assert "This is an automatic reminder from" in body


async def test_all_arrived_finishes_and_sends_nothing(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    original = await _original(db)
    original.needs[0].status = NeedsItemStatus.VERIFIED
    await db.commit()
    assert await job.send_follow_ups(db, now=WED_2PM) == {"finished": 1}
    await db.refresh(original.row)
    assert original.row.follow_up_status is FollowUpStatus.FINISHED
    assert await _reminders(db, original.row) == []
    assert enqueued == []


async def test_a_failed_original_is_stopped(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    original = await _original(db)
    original.row.status = CommunicationStatus.FAILED
    await db.commit()
    assert await job.send_follow_ups(db, now=WED_2PM) == {"stopped_failed": 1}
    await db.refresh(original.row)
    assert original.row.follow_up_status is FollowUpStatus.STOPPED
    assert enqueued == []


async def test_before_her_time_nothing_is_picked(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    """Due today at 14:00: the 13:45 run leaves it, the 14:00 run sends it."""
    original = await _original(db)
    original.row.follow_up_clock_at = WED_2PM - timedelta(days=3)
    await db.commit()
    assert await job.send_follow_ups(db, now=WED_2PM - timedelta(minutes=15)) == {}
    assert await _reminders(db, original.row) == []
    assert await job.send_follow_ups(db, now=WED_2PM) == {"sent": 1}


async def test_earliest_due_first(
    db: AsyncSession, sender: FakeSender, enqueued: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap takes the earliest DUE MOMENT, not the oldest clock: an older clock with a later
    time of day waits behind a newer one already due."""
    monkeypatch.setattr(job, "DUE_CAP", 1)
    late = await _original(db, follow_up=FollowUp(time=time(13, 0), tz="America/New_York"))
    early = await _original(db, follow_up=FollowUp(time=time(9, 0), tz="America/New_York"))
    late.row.follow_up_clock_at = WED_2PM - timedelta(days=4)  # Saturday → Tuesday 13:00
    early.row.follow_up_clock_at = WED_2PM - timedelta(days=3)  # Sunday → Wednesday 09:00
    late.row.follow_up_interval_days = 4  # → Wednesday 13:00
    await db.commit()
    assert await job.send_follow_ups(db, now=WED_2PM) == {"sent": 1}
    assert len(await _reminders(db, early.row)) == 1
    assert await _reminders(db, late.row) == []


async def test_a_reply_found_before_sending_pauses_instead(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    """The job's own re-check: a reply that reached the file without the ingest hook (here written
    directly, as a message moved from the Inbox would be)."""
    original = await _original(db)
    db.add(
        InboundMessage(
            ingest_key=uuid4().hex,
            from_address=f"  {TO.upper()} ",
            loan_file_id=original.ready.loan_file.id,
            company_id=original.ready.company.id,
            routing_state=InboundRoutingState.ROUTED,
        )
    )
    await db.commit()
    assert await job.send_follow_ups(db, now=WED_2PM) == {"paused_reply": 1}
    await db.refresh(original.row)
    assert original.row.follow_up_status is FollowUpStatus.PAUSED
    assert original.row.follow_up_paused_at == WED_2PM
    assert enqueued == []


async def test_a_rate_limit_leaves_the_counts_and_retries_later(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    original = await _original(db)
    original.row.sent_at = utcnow()  # emailed a moment ago
    await db.commit()
    assert await job.send_follow_ups(db, now=WED_2PM) == {"refused_rate_limited": 1}
    await db.refresh(original.row)
    assert original.row.follow_up_auto_sent == 0
    assert original.row.follow_up_clock_at == WED_2PM - timedelta(days=4)
    assert original.row.follow_up_status is FollowUpStatus.ON
    assert await _reminders(db, original.row) == []  # the savepoint took the row with it


async def _domain(db: AsyncSession, original: Original) -> CompanyMailDomain:
    domain = await db.scalar(
        select(CompanyMailDomain).where(CompanyMailDomain.company_id == original.ready.company.id)
    )
    assert domain is not None
    return domain


async def test_sending_switched_off_at_the_send_is_refused_with_its_code(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    """Switched off between the job's query and the send: refused, left `on`, nothing sent."""
    from app.services import follow_ups as service

    original = await _original(db)
    real = service.send_draft

    async def switched_off_first(*args: object, **kwargs: object) -> Communication:
        (await _domain(db, original)).sending_enabled = False
        await db.flush()  # the session does not autoflush
        return await real(*args, **kwargs)  # type: ignore[arg-type]

    service.send_draft = switched_off_first  # type: ignore[assignment]
    try:
        assert await job.send_follow_ups(db, now=WED_2PM) == {"refused_sending_off": 1}
    finally:
        service.send_draft = real
    await db.refresh(original.row)
    assert original.row.follow_up_status is FollowUpStatus.ON
    assert await _reminders(db, original.row) == []


@pytest.mark.parametrize("blocked", ["sending_off", "domain_problem"])
async def test_a_company_that_cannot_send_does_not_hold_up_another(
    db: AsyncSession,
    sender: FakeSender,
    enqueued: list[str],
    monkeypatch: pytest.MonkeyPatch,
    blocked: str,
) -> None:
    """Review finding 2. Company A cannot send and has more due than a run takes, all due earlier;
    company B's one still goes. A's wait, still `on`, and go once A can send again."""
    monkeypatch.setattr(job, "DUE_CAP", 2)
    stuck = [await _original(db) for _ in range(3)]
    for other in stuck[1:]:  # all on company A's file
        other.row.loan_file_id = stuck[0].row.loan_file_id
        other.row.recipient = f"other-{uuid4().hex[:6]}@example.test"
    domain = await _domain(db, stuck[0])
    if blocked == "sending_off":
        domain.sending_enabled = False
    else:
        domain.status = MailDomainStatus.PROBLEM
    other_company = await _original(db)
    other_company.row.follow_up_clock_at = WED_2PM - timedelta(days=3)  # due later than A's
    await db.commit()

    assert await job.send_follow_ups(db, now=WED_2PM) == {"sent": 1}
    assert len(await _reminders(db, other_company.row)) == 1
    for original in stuck:
        await db.refresh(original.row)
        assert original.row.follow_up_status is FollowUpStatus.ON
        assert await _reminders(db, original.row) == []

    domain.sending_enabled, domain.status = True, MailDomainStatus.ACTIVE
    await db.commit()
    assert await job.send_follow_ups(db, now=WED_2PM + timedelta(minutes=15)) == {"sent": 2}


async def test_an_original_not_yet_gone_out_is_left_out(
    db: AsyncSession, sender: FakeSender, enqueued: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stuck `queued`: `evaluate` says wait every run, so it must not take one of the run's places."""
    monkeypatch.setattr(job, "DUE_CAP", 1)
    stuck = await _original(db)
    stuck.row.status = CommunicationStatus.QUEUED
    later = await _original(db)
    later.row.follow_up_clock_at = WED_2PM - timedelta(days=3)  # due after the stuck one
    await db.commit()
    assert await job.send_follow_ups(db, now=WED_2PM) == {"sent": 1}
    assert len(await _reminders(db, later.row)) == 1


async def test_a_deleted_file_is_left_out(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    original = await _original(db)
    original.ready.loan_file.deleted_at = utcnow()
    await db.commit()
    assert await job.send_follow_ups(db, now=WED_2PM) == {}
    assert await _reminders(db, original.row) == []


async def test_no_known_sender_stops_it(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    """Skipped and left `on`, it would be picked every run for ever."""
    original = await _original(db)
    for evidence in (
        await db.execute(
            select(CommunicationEvidence).where(
                CommunicationEvidence.communication_id == original.row.id
            )
        )
    ).scalars():
        await db.delete(evidence)
    await db.commit()
    assert await job.send_follow_ups(db, now=WED_2PM) == {"stopped_no_sender": 1}
    await db.refresh(original.row)
    assert original.row.follow_up_status is FollowUpStatus.STOPPED


async def test_no_mail_set_up_on_the_server_sends_nothing(
    db: AsyncSession, enqueued: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = await _original(db)
    monkeypatch.setattr(settings, "mail_transport", None)
    assert await job.send_follow_ups(db, now=WED_2PM) == {}
    await db.refresh(original.row)
    assert original.row.follow_up_status is FollowUpStatus.ON


async def test_a_suppressed_recipient_stops_it(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    original = await _original(db)
    await suppress_address(
        db,
        company_id=original.ready.company.id,
        address=TO,
        reason=SuppressionReason.HARD_BOUNCE,
    )
    await db.commit()
    assert await job.send_follow_ups(db, now=WED_2PM) == {"stopped_suppressed": 1}
    await db.refresh(original.row)
    assert original.row.follow_up_status is FollowUpStatus.STOPPED
    assert enqueued == []


async def test_the_run_is_capped(
    db: AsyncSession, sender: FakeSender, enqueued: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(job, "DUE_CAP", 2)
    for _ in range(3):
        await _original(db)
    outcomes = await job.send_follow_ups(db, now=WED_2PM)
    assert sum(outcomes.values()) == 2
    assert outcomes == {"sent": 2}
    assert job.DUE_CAP == 2
    monkeypatch.undo()
    assert job.DUE_CAP == 50


def test_the_candidates_are_locked_and_locked_rows_skipped() -> None:
    sql = str(job.candidates_stmt(WED_2PM).compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE OF communications SKIP LOCKED" in sql
    assert "LIMIT" in sql


async def test_only_due_emails_are_picked(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    due = await _original(db)
    off = await _original(db, follow_up=None)
    early = await _original(db)
    early.row.follow_up_clock_at = WED_2PM - timedelta(days=1)
    await db.commit()
    assert await job.send_follow_ups(db, now=WED_2PM) == {"sent": 1}
    assert len(await _reminders(db, due.row)) == 1
    assert await _reminders(db, off.row) == []
    assert await _reminders(db, early.row) == []


def test_the_job_runs_every_15_minutes() -> None:
    from app.tasks.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["send-follow-ups"]
    assert entry["task"] == "communications.send_follow_ups"
    assert entry["schedule"] == 900.0
    assert entry["options"] == {"expires": 900}


# --------------------------------------------------------------------------------------------- #
# A reply pauses it (at ingest)
# --------------------------------------------------------------------------------------------- #
def _raw(to: str, *, sender: str, headers: dict[str, str] | None = None) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = f"Re: {SUBJECT}"
    message["Message-ID"] = f"<{uuid4().hex}@borrower.example>"
    message["Date"] = "Tue, 03 Nov 2026 10:00:00 +0000"
    for name, value in (headers or {}).items():
        message[name] = value
    message.set_content("I'll send them Friday.")
    return message.as_bytes(policy=email_policy)


async def _arrive(db: AsyncSession, original: Original, raw: bytes) -> InboundMessage:
    address = f"{original.ready.loan_file.display_id.lower()}@{original.ready.domain}"
    result = await process_raw_message(
        db,
        raw=raw,
        raw_storage_path=None,
        store_raw=True,
        receipt={
            "recipients": [address],
            "dmarcVerdict": {"status": "PASS"},
            "virusVerdict": {"status": "PASS"},
        },
    )
    message = await db.get(InboundMessage, UUID(result.message_id))
    assert message is not None
    await db.refresh(original.row)
    return message


def _to_file(original: Original) -> str:
    return f"{original.ready.loan_file.display_id.lower()}@{original.ready.domain}"


async def test_a_reply_from_the_recipient_pauses_it(db: AsyncSession) -> None:
    original = await _original(db)
    message = await _arrive(db, original, _raw(_to_file(original), sender=f"Jane <{TO.upper()}>"))
    assert message.loan_file_id == original.ready.loan_file.id
    assert original.row.follow_up_status is FollowUpStatus.PAUSED
    assert original.row.follow_up_paused_at is not None
    paused = (
        (
            await db.execute(
                select(ActivityLog).where(ActivityLog.loan_file_id == original.ready.loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert [a.summary for a in paused if (a.detail or {}).get("kind") == "follow_up_paused"] == [
        f"Follow-up paused: {TO} replied"
    ]


async def test_a_reply_from_someone_else_does_not(db: AsyncSession) -> None:
    original = await _original(db)
    await _arrive(db, original, _raw(_to_file(original), sender="other@example.test"))
    assert original.row.follow_up_status is FollowUpStatus.ON


async def test_an_out_of_office_does_not(db: AsyncSession) -> None:
    original = await _original(db)
    message = await _arrive(
        db,
        original,
        _raw(_to_file(original), sender=TO, headers={"Auto-Submitted": "auto-replied"}),
    )
    assert message.is_auto_reply
    assert original.row.follow_up_status is FollowUpStatus.ON


async def test_bulk_mail_does_not(db: AsyncSession) -> None:
    original = await _original(db)
    message = await _arrive(
        db, original, _raw(_to_file(original), sender=TO, headers={"Precedence": "bulk"})
    )
    assert message.is_bulk
    assert original.row.follow_up_status is FollowUpStatus.ON


async def test_only_the_matching_follow_up_pauses(db: AsyncSession) -> None:
    borrower = await _original(db)
    title = await _original(db, needs=0, recipient=TITLE, ready=borrower.ready)
    await _arrive(db, borrower, _raw(_to_file(borrower), sender=TITLE))
    await db.refresh(title.row)
    assert title.row.follow_up_status is FollowUpStatus.PAUSED
    assert borrower.row.follow_up_status is FollowUpStatus.ON


async def test_pause_skips_a_message_that_is_not_routed(db: AsyncSession) -> None:
    original = await _original(db)
    message = InboundMessage(
        ingest_key=uuid4().hex, from_address=TO, routing_state=InboundRoutingState.REJECTED
    )
    assert await pause_for_reply(db, message=message, loan_file=original.ready.loan_file) == 0
    assert original.row.follow_up_status is FollowUpStatus.ON


# --------------------------------------------------------------------------------------------- #
# The API
# --------------------------------------------------------------------------------------------- #
async def _api(
    db: AsyncSession, user: User, method: str, path: str, json: dict[str, object] | None = None
) -> tuple[int, dict[str, object]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = _get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.request(
                method,
                f"/api/v1{path}",
                headers={"Authorization": f"Bearer {create_access_token(user.id)}"},
                json=json,
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
    return response.status_code, response.json() if response.content else {}


def _path(original: Original, tail: str = "") -> str:
    return f"/loan-files/{original.ready.loan_file.display_id}/messages/{original.row.id}{tail}"


async def test_resume_restarts_the_clock_from_the_reply(db: AsyncSession) -> None:
    original = await _original(db)
    await _arrive(db, original, _raw(_to_file(original), sender=TO))
    replied = original.row.follow_up_paused_at
    assert replied is not None
    status, body = await _api(db, original.ready.user, "POST", _path(original, "/follow-up/resume"))
    assert status == 200, body
    await db.refresh(original.row)
    assert original.row.follow_up_status is FollowUpStatus.ON
    assert original.row.follow_up_clock_at == replied
    assert body["status"] == "on"
    # The time of day stays, and the screen is told when the next one goes.
    assert (original.row.follow_up_time, body["time"], body["tz"]) == (
        time(14, 0),
        "14:00",
        "America/New_York",
    )
    assert body["next_reminder_at"] is not None
    assert datetime.fromisoformat(str(body["next_reminder_at"])) == due_moment(original.row)
    # Resuming something not paused is refused.
    status, _ = await _api(db, original.ready.user, "POST", _path(original, "/follow-up/resume"))
    assert status == 409


async def test_resume_after_send_now_keeps_the_send_now_clock(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    """Paused by a reply, then Send now, then Resume: the clock stays at Send now. Back at the reply,
    an automatic reminder would be due a day or two after the one she just sent."""
    original = await _original(db)
    await _arrive(db, original, _raw(_to_file(original), sender=TO))
    status, _ = await _api(db, original.ready.user, "POST", _path(original, "/follow-up/send-now"))
    assert status == 200
    await db.refresh(original.row)
    sent_now = original.row.follow_up_clock_at
    assert sent_now is not None and original.row.follow_up_status is FollowUpStatus.PAUSED
    status, _ = await _api(db, original.ready.user, "POST", _path(original, "/follow-up/resume"))
    assert status == 200
    await db.refresh(original.row)
    assert original.row.follow_up_clock_at == sent_now


async def test_resume_counts_from_the_latest_reply(db: AsyncSession) -> None:
    """Review finding 1: she writes twice while paused. Resume from the first reply left the second
    "since the clock", and the job paused it again at its first due time; nothing ever went."""
    original = await _original(db)
    await _arrive(db, original, _raw(_to_file(original), sender=TO))
    first = original.row.follow_up_paused_at
    second = await _arrive(db, original, _raw(_to_file(original), sender=TO))
    assert first is not None and second.created_at > first
    status, body = await _api(db, original.ready.user, "POST", _path(original, "/follow-up/resume"))
    assert status == 200, body
    await db.refresh(original.row)
    assert original.row.follow_up_clock_at == second.created_at
    assert not await has_reply_since(db, original.row)


async def test_start_on_an_old_email(db: AsyncSession) -> None:
    original = await _original(db, follow_up=None)
    assert original.row.follow_up_status is FollowUpStatus.OFF
    before = utcnow()
    status, body = await _api(
        db,
        original.ready.user,
        "POST",
        _path(original, "/follow-up/start"),
        {"interval_days": 2, "max_auto": 3},
    )
    assert status == 200, body
    await db.refresh(original.row)
    assert original.row.follow_up_status is FollowUpStatus.ON
    assert (original.row.follow_up_interval_days, original.row.follow_up_max_auto) == (2, 3)
    assert original.row.follow_up_clock_at is not None and original.row.follow_up_clock_at >= before
    assert body["waiting_for"] == ["Bank statements"]
    assert body["next_reminder_at"] is not None
    # No time given: the moment she clicked, in the default time zone.
    clicked = original.row.follow_up_clock_at.astimezone(NEW_YORK)
    assert body["tz"] == "America/New_York"
    assert body["time"] == f"{clicked.hour:02d}:{clicked.minute:02d}"


@pytest.mark.parametrize("tz", ["America/Nowhere", "EST-5", "../../etc/passwd", ""])
async def test_an_unknown_time_zone_is_refused(db: AsyncSession, tz: str) -> None:
    original = await _original(db)
    for method, tail in (("POST", "/follow-up/start"), ("PATCH", "/follow-up")):
        status, _ = await _api(db, original.ready.user, method, _path(original, tail), {"tz": tz})
        assert status == 422, (method, tz)
    await db.refresh(original.row)
    assert original.row.follow_up_tz == "America/New_York"


async def test_start_refuses_an_email_that_has_not_gone_out(db: AsyncSession) -> None:
    original = await _original(db, follow_up=None)
    original.row.status = CommunicationStatus.FAILED
    await db.commit()
    status, _ = await _api(db, original.ready.user, "POST", _path(original, "/follow-up/start"), {})
    assert status == 409


async def test_stop_and_patch(db: AsyncSession) -> None:
    original = await _original(db)
    status, body = await _api(
        db, original.ready.user, "PATCH", _path(original, "/follow-up"), {"interval_days": 7}
    )
    assert status == 200, body
    assert (body["interval_days"], body["max_auto"], body["status"]) == (7, 2, "on")
    status, body = await _api(
        db, original.ready.user, "PATCH", _path(original, "/follow-up"), {"max_auto": 11}
    )
    assert status == 422
    status, body = await _api(
        db,
        original.ready.user,
        "PATCH",
        _path(original, "/follow-up"),
        {"time": "08:45", "tz": "America/Los_Angeles"},
    )
    assert status == 200, body
    assert (body["time"], body["tz"], body["interval_days"]) == ("08:45", "America/Los_Angeles", 7)
    await db.refresh(original.row)
    assert datetime.fromisoformat(str(body["next_reminder_at"])) == due_moment(original.row)
    status, body = await _api(db, original.ready.user, "POST", _path(original, "/follow-up/stop"))
    assert status == 200 and body["status"] == "stopped"
    assert body["next_reminder_at"] is None


async def test_send_now_from_the_clicking_user(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage, enqueued: list[str]
) -> None:
    original = await _original(db, follow_up=None)  # off
    clicker = await _user(db, original.ready.company, "Sam")
    await db.commit()
    before = utcnow()
    status, body = await _api(db, clicker, "POST", _path(original, "/follow-up/send-now"))
    assert status == 200, body
    [reminder] = await _reminders(db, original.row)
    assert enqueued == [str(reminder.id)]
    assert reminder.initiated_by_user_id == clicker.id

    await db.refresh(original.row)
    assert original.row.follow_up_auto_sent == 0
    assert original.row.follow_up_clock_at is not None and original.row.follow_up_clock_at >= before
    assert original.row.follow_up_status is FollowUpStatus.OFF

    wire = await _wire(db, reminder, storage)
    assert wire["From"].startswith('"Sam Clicker, Summit Mortgage Processing"')
    assert wire["Cc"] == clicker.email
    assert wire["Auto-Submitted"] is None
    assert wire["In-Reply-To"] == f"<{original.row.external_message_id}@email.amazonses.com>"
    text = _text(wire)
    assert "automatic reminder" not in text
    assert "Sam Clicker" in text

    activity = (
        (
            await db.execute(
                select(ActivityLog).where(ActivityLog.loan_file_id == original.ready.loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert any(a.summary == "Sent a reminder" and a.actor_user_id == clicker.id for a in activity)


async def test_send_now_does_not_count_toward_the_automatic_count(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    original = await _original(db)
    status, _ = await _api(db, original.ready.user, "POST", _path(original, "/follow-up/send-now"))
    assert status == 200
    await db.refresh(original.row)
    assert original.row.follow_up_auto_sent == 0
    # The next automatic one waits a full interval from now, at the same time of day.
    assert await evaluate(db, original.row, now=WED_2PM) is Decision.WAIT
    assert (original.row.follow_up_time, original.row.follow_up_tz) == (
        time(14, 0),
        "America/New_York",
    )


async def test_send_now_refusal_is_a_409(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    original = await _original(db)
    original.row.sent_at = utcnow()
    await db.commit()
    status, body = await _api(
        db, original.ready.user, "POST", _path(original, "/follow-up/send-now")
    )
    assert status == 409
    assert "minutes ago" in str(body["error"])
    assert await _reminders(db, original.row) == []
    assert enqueued == []


async def test_another_companys_email_is_a_404(db: AsyncSession) -> None:
    original = await _original(db)
    other = Company(name="Other", slug=f"other-{uuid4().hex[:8]}")
    db.add(other)
    await db.flush()
    outsider = await _user(db, other, "Out")
    own_file = await create_loan_file(
        db, company_id=other.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await db.commit()
    for tail in ("/follow-up/stop", "/follow-up/send-now", "/follow-up/resume"):
        status, _ = await _api(db, outsider, "POST", _path(original, tail))
        assert status == 404
        path = f"/loan-files/{own_file.display_id}/messages/{original.row.id}{tail}"
        status, _ = await _api(db, outsider, "POST", path)
        assert status == 404
    await db.refresh(original.row)
    assert original.row.follow_up_status is FollowUpStatus.ON


async def test_the_message_api_returns_the_follow_up(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    original = await _original(db, needs=2)
    original.needs[1].status = NeedsItemStatus.RECEIVED
    await db.commit()
    status, body = await _api(db, original.ready.user, "GET", _path(original))
    assert status == 200, body
    follow_up = body["follow_up"]
    assert isinstance(follow_up, dict)
    assert follow_up["status"] == "on"
    assert follow_up["waiting_for"] == ["Bank statements"]
    assert (follow_up["interval_days"], follow_up["max_auto"], follow_up["auto_sent"]) == (3, 2, 0)
    assert follow_up["next_reminder_at"] is not None
    assert body["follow_up_of_id"] is None and body["automatic_reminder"] is False

    await job.send_follow_ups(db, now=WED_2PM)
    [reminder] = await _reminders(db, original.row)
    path = f"/loan-files/{original.ready.loan_file.display_id}/messages/{reminder.id}"
    status, body = await _api(db, original.ready.user, "GET", path)
    assert status == 200
    assert body["follow_up"] is None
    assert body["follow_up_of_id"] == str(original.row.id)
    assert body["automatic_reminder"] is True


async def test_a_general_email_waits_for_a_reply(db: AsyncSession) -> None:
    original = await _original(db, needs=0)
    status, body = await _api(db, original.ready.user, "GET", _path(original))
    assert status == 200
    follow_up = body["follow_up"]
    assert isinstance(follow_up, dict)
    assert follow_up["waiting_for"] == ["a reply"]


async def test_the_send_endpoint_takes_follow_up_only_with_transmit(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    ready = await ready_to_send(db)
    await db.commit()
    path = f"/loan-files/{ready.loan_file.display_id}/outbound/draft/{ready.draft.id}/send"
    status, body = await _api(
        db,
        ready.user,
        "POST",
        path,
        {"recipient": TO, "body": "Please send.", "follow_up": {"interval_days": 4}},
    )
    assert status == 200, body
    await db.refresh(ready.draft)
    assert ready.draft.follow_up_status is FollowUpStatus.OFF

    ready2 = await ready_to_send(db)
    await db.commit()
    path = f"/loan-files/{ready2.loan_file.display_id}/outbound/draft/{ready2.draft.id}/send"
    status, body = await _api(
        db,
        ready2.user,
        "POST",
        path,
        {
            "recipient": TO,
            "body": "Please send.",
            "transmit": True,
            "follow_up": {"interval_days": 4, "max_auto": 1},
        },
    )
    assert status == 200, body
    await db.refresh(ready2.draft)
    assert ready2.draft.follow_up_status is FollowUpStatus.ON
    assert (ready2.draft.follow_up_interval_days, ready2.draft.follow_up_max_auto) == (4, 1)
