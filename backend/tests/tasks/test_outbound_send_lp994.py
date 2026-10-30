"""LP-994 — the worker sends: `queued → sending → sent`, at most once, only what a person asked for.

The session joins the test transaction with savepoints, so the task's own commits land and a
simulated crash can roll back to the last one, as a dead worker's connection would.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from email import message_from_bytes, policy

import pytest
import pytest_asyncio
from app.core.config import settings
from app.models.activity_log import ActivityLog, ActivityType
from app.models.base import utcnow
from app.models.communication import Communication, CommunicationDirection, CommunicationStatus
from app.models.company_mail_domain import MailDomainStatus
from app.models.needs_item import NeedsItem, NeedsItemOrigin, NeedsItemStatus
from app.services.email_send import send_draft
from app.services.mail_domain import set_company_mail_domain
from app.services.mail_sender import SendError
from app.tasks import outbound
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from structlog.testing import capture_logs
from tests.outbound_send import FakeSender, FakeStorage, Ready, ready_to_send

TO = "borrower@example.test"
SUBJECT = "Documents for your loan"


@pytest_asyncio.fixture
async def db(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    connection = await test_engine.connect()
    transaction = await connection.begin()
    # `autoflush=False`, as `task_session` has: the worker's queries see the database, not its own
    # unflushed changes. Review mutation F1d survived until this matched.
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


@pytest.fixture
def sender(file_addresses_on: None, monkeypatch: pytest.MonkeyPatch) -> FakeSender:
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


async def _queued(db: AsyncSession, **reply: str) -> Ready:
    """A person's Send, recorded and committed as the API leaves it."""
    ready = await ready_to_send(db)
    if reply:
        ready.draft.in_reply_to_message_id = reply["in_reply_to"]
    await send_draft(
        db,
        loan_file=ready.loan_file,
        draft_id=ready.draft.id,
        recipient=TO,
        body="Please send your bank statements.",
        subject=SUBJECT,
        approver_user_id=ready.user.id,
        transmit=True,
    )
    await db.commit()
    assert ready.draft.status is CommunicationStatus.QUEUED
    return ready


async def _reload(db: AsyncSession, row: Communication) -> Communication:
    await db.refresh(row)
    return row


def _logged_text(logs: list[dict[str, object]]) -> str:
    return repr(logs)


# --------------------------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------------------------- #
async def test_queued_send_goes_out_once_and_the_copy_is_what_was_sent(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage
) -> None:
    ready = await _queued(db)
    assert await outbound._send_communication(db, str(ready.draft.id)) == "sent"

    row = await _reload(db, ready.draft)
    assert row.status is CommunicationStatus.SENT
    assert row.external_message_id == "ses-1"
    assert row.sent_at is not None
    assert row.raw_storage_path == f"outbound/{row.id}.eml"
    assert len(sender.sent) == 1
    assert storage.saved[row.raw_storage_path] == sender.sent[0].as_bytes()

    parsed = message_from_bytes(storage.saved[row.raw_storage_path], policy=policy.SMTP)
    address = f"{ready.loan_file.display_id.lower()}@{ready.domain}"
    assert parsed["From"] == f'"Pat Processor, Summit Mortgage Processing" <{address}>'
    assert parsed["To"] == TO
    assert parsed["Cc"] == ready.user.email
    assert parsed["Reply-To"] == address
    assert parsed["Subject"] == SUBJECT
    assert parsed["In-Reply-To"] is None
    assert parsed["Bcc"] is None
    # The need stays requested: the email went.
    assert ready.need.status is NeedsItemStatus.REQUESTED


async def test_a_reply_carries_the_threading_headers(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage
) -> None:
    ready = await _queued(db, in_reply_to="<abc@borrower.test>")
    await outbound._send_communication(db, str(ready.draft.id))
    message = sender.sent[0]
    assert message["In-Reply-To"] == "<abc@borrower.test>"
    assert message["References"] == "<abc@borrower.test>"


# --------------------------------------------------------------------------------------------- #
# Never twice; never an automatic reply
# --------------------------------------------------------------------------------------------- #
async def test_running_the_task_twice_sends_once(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage
) -> None:
    ready = await _queued(db)
    assert await outbound._send_communication(db, str(ready.draft.id)) == "sent"
    with capture_logs() as logs:
        assert await outbound._send_communication(db, str(ready.draft.id)) == "skipped"
    assert len(sender.sent) == 1
    assert [entry["event"] for entry in logs] == ["send_skipped"]
    assert logs[0]["communication_id"] == str(ready.draft.id)


async def test_a_row_already_sending_is_not_sent(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage
) -> None:
    """A redelivered task finding another worker's claim: the atomic claim refuses it."""
    ready = await _queued(db)
    ready.draft.status = CommunicationStatus.SENDING
    await db.commit()
    assert await outbound._send_communication(db, str(ready.draft.id)) == "skipped"
    assert sender.sent == []


async def test_a_deleted_message_is_not_sent(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage
) -> None:
    ready = await _queued(db)
    ready.draft.deleted_at = utcnow()
    await db.commit()
    assert await outbound._send_communication(db, str(ready.draft.id)) == "skipped"
    assert sender.sent == []


async def _auto_reply(db: AsyncSession, ready: Ready, **extra: object) -> Communication:
    """LP-815's shape: `queued`, composed by the system, requested by nobody."""
    row = Communication(
        loan_file_id=ready.loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.QUEUED,
        recipient=TO,
        subject="We received your message",
        body="Thanks",
        **extra,
    )
    db.add(row)
    await db.commit()
    return row


async def test_an_automatic_reply_is_never_sent(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage, enqueued: list[str]
) -> None:
    ready = await ready_to_send(db)
    row = await _auto_reply(db, ready, created_at=utcnow() - timedelta(hours=1))
    assert await outbound._send_communication(db, str(row.id)) == "skipped"
    assert sender.sent == []
    assert (await _reload(db, row)).status is CommunicationStatus.QUEUED
    assert await outbound._requeue_stale(db) == []


# --------------------------------------------------------------------------------------------- #
# Clean failure: nothing went, the request is unwound
# --------------------------------------------------------------------------------------------- #
async def _assert_clean_failure(
    db: AsyncSession, ready: Ready, logs: list[dict[str, object]], *, code: str
) -> None:
    row = await _reload(db, ready.draft)
    assert row.status is CommunicationStatus.FAILED
    assert row.error_detail is not None and row.error_detail.startswith("Not sent: ")
    await db.refresh(ready.need)
    assert ready.need.status is NeedsItemStatus.PENDING
    assert ready.need.requested_at is None
    activity = await db.scalar(
        select(ActivityLog).where(
            ActivityLog.loan_file_id == row.loan_file_id,
            ActivityLog.activity_type == ActivityType.COMMUNICATION_FAILED,
        )
    )
    assert activity is not None and activity.summary == "Not sent"
    assert activity.detail["error_code"] == code
    failed = [entry for entry in logs if entry["event"] == "send_failed"]
    assert failed == [
        {
            "event": "send_failed",
            "communication_id": str(row.id),
            "error_code": code,
            "log_level": "warning",
        }
    ]
    text = _logged_text(logs)
    assert TO not in text and SUBJECT not in text and "bank statements" not in text


async def test_provider_refusal_is_a_clean_failure(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage
) -> None:
    sender.error = SendError("MessageRejected", outcome_unknown=False)
    ready = await _queued(db)
    with capture_logs() as logs:
        assert await outbound._send_communication(db, str(ready.draft.id)) == "failed"
    await _assert_clean_failure(db, ready, logs, code="MessageRejected")
    assert "MessageRejected" in (ready.draft.error_detail or "")


async def test_domain_switched_off_after_send_is_a_clean_failure(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage
) -> None:
    ready = await _queued(db)
    await set_company_mail_domain(
        db, company_id=ready.company.id, domain=ready.domain, status=MailDomainStatus.INACTIVE
    )
    await db.commit()
    with capture_logs() as logs:
        assert await outbound._send_communication(db, str(ready.draft.id)) == "failed"
    await _assert_clean_failure(db, ready, logs, code="no_domain")
    assert sender.sent == [] and storage.saved == {}


async def test_an_email_that_cannot_be_built_is_a_clean_failure(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage
) -> None:
    ready = await _queued(db)
    ready.draft.subject = "Line one\r\nBcc: someone@else.test"
    await db.commit()
    with capture_logs() as logs:
        assert await outbound._send_communication(db, str(ready.draft.id)) == "failed"
    await _assert_clean_failure(db, ready, logs, code="build_failed")
    assert sender.sent == []


async def test_a_copy_that_cannot_be_saved_is_a_clean_failure_and_nothing_is_sent(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage
) -> None:
    storage.fail = True
    ready = await _queued(db)
    with capture_logs() as logs:
        assert await outbound._send_communication(db, str(ready.draft.id)) == "failed"
    await _assert_clean_failure(db, ready, logs, code="storage_OSError")
    assert sender.sent == []


# --------------------------------------------------------------------------------------------- #
# Not confirmed: the email may have gone
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "error", [SendError("ReadTimeoutError", outcome_unknown=True), RuntimeError("boom")]
)
async def test_an_unknown_outcome_stays_sending_and_is_not_unwound(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage, error: Exception
) -> None:
    sender.error = error
    ready = await _queued(db)
    with capture_logs() as logs:
        assert await outbound._send_communication(db, str(ready.draft.id)) == "not_confirmed"
    row = await _reload(db, ready.draft)
    assert row.status is CommunicationStatus.SENDING
    assert row.error_detail is not None
    assert row.error_detail.startswith("Not confirmed: ")
    assert row.error_detail.endswith("Check before sending again.")
    await db.refresh(ready.need)
    assert ready.need.status is NeedsItemStatus.REQUESTED
    assert ready.need.requested_at is not None
    assert [e["event"] for e in logs if e["event"].startswith("send_")] == ["send_not_confirmed"]
    assert "boom" not in _logged_text(logs)
    # And it is not sent again.
    assert await outbound._send_communication(db, str(ready.draft.id)) == "skipped"
    assert len(sender.sent) == 1


async def test_a_crash_after_the_provider_answered_leaves_one_email(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The last commit dies after `send` returned. The row stays `sending` with no MessageId, and a
    second run does not send again."""
    ready = await _queued(db)
    real_commit = db.commit

    async def commit() -> None:
        if sender.sent:  # the provider has answered: this is the final commit
            raise ConnectionError("worker killed")
        await real_commit()

    monkeypatch.setattr(db, "commit", commit)
    with pytest.raises(ConnectionError):
        await outbound._send_communication(db, str(ready.draft.id))
    monkeypatch.setattr(db, "commit", real_commit)
    await db.rollback()

    row = await _reload(db, ready.draft)
    assert row.status is CommunicationStatus.SENDING
    assert row.external_message_id is None
    assert await outbound._send_communication(db, str(ready.draft.id)) == "skipped"
    assert len(sender.sent) == 1


# --------------------------------------------------------------------------------------------- #
# Re-enqueue job
# --------------------------------------------------------------------------------------------- #
async def _age(db: AsyncSession, row: Communication, minutes: int) -> None:
    row.send_requested_at = utcnow() - timedelta(minutes=minutes)
    await db.commit()


async def test_requeue_picks_stale_sends_and_nothing_else(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    stale = await _queued(db)
    await _age(db, stale.draft, 6)
    fresh = await _queued(db)
    auto = await _auto_reply(db, fresh, created_at=utcnow() - timedelta(hours=1))
    sent = await _queued(db)
    sent.draft.status = CommunicationStatus.SENT
    await _age(db, sent.draft, 30)

    assert await outbound._requeue_stale(db) == [str(stale.draft.id)]
    assert enqueued == [str(stale.draft.id)]
    assert str(fresh.draft.id) not in enqueued and str(auto.id) not in enqueued


async def test_requeue_is_capped_per_run(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    ready = await ready_to_send(db)
    old = utcnow() - timedelta(minutes=10)
    for i in range(outbound.REQUEUE_BATCH + 1):
        db.add(
            Communication(
                loan_file_id=ready.loan_file.id,
                direction=CommunicationDirection.OUTBOUND,
                status=CommunicationStatus.QUEUED,
                recipient=TO,
                send_requested_at=old + timedelta(seconds=i),
            )
        )
    await db.commit()
    assert len(await outbound._requeue_stale(db)) == outbound.REQUEUE_BATCH == 50
    assert len(enqueued) == 50


def test_requeue_runs_on_the_beat_and_expires_like_the_heartbeat() -> None:
    from app.tasks.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["requeue-stale-sends"]
    assert entry["task"] == "communications.requeue_stale"
    assert entry["schedule"] == 300.0
    assert entry["options"] == {"expires": 300}
    assert "communications.send" in celery_app.tasks


# --------------------------------------------------------------------------------------------- #
# Read paths
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("status", "requested", "summary"),
    [
        (CommunicationStatus.QUEUED, True, "A message is being sent"),
        (CommunicationStatus.SENDING, True, "A message is being sent"),
        (CommunicationStatus.QUEUED, False, "An automatic reply is queued"),
    ],
)
def test_the_timeline_tells_a_send_from_an_automatic_reply(
    status: CommunicationStatus, requested: bool, summary: str
) -> None:
    from app.services.timeline import _summarise

    row = Communication(
        direction=CommunicationDirection.OUTBOUND,
        status=status,
        send_requested_at=utcnow() if requested else None,
    )
    assert _summarise(row) == summary


def test_the_drafts_pill_keeps_a_sending_row_and_sent_does_not() -> None:
    from app.services.timeline import TimelineFilter, _matches

    class _Entry:
        direction = CommunicationDirection.OUTBOUND.value
        status = CommunicationStatus.SENDING.value

    assert _matches(_Entry(), TimelineFilter.DRAFTS)  # type: ignore[arg-type]
    assert not _matches(_Entry(), TimelineFilter.SENT)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------------- #
# Review fixes
# --------------------------------------------------------------------------------------------- #
async def _asked_twice(db: AsyncSession) -> tuple[Ready, Communication, NeedsItem]:
    """Need X asked in email #1 (went out an hour ago), asked again in #2 with a new need Y.
    #2 is a person's Send, queued for the worker. Returns (ready, #2, Y)."""
    from app.services.email_draft import add_needs_to_draft

    ready = await ready_to_send(db)
    first = await send_draft(
        db,
        loan_file=ready.loan_file,
        draft_id=ready.draft.id,
        recipient=TO,
        body="First request.",
        approver_user_id=ready.user.id,
    )
    an_hour_ago = utcnow() - timedelta(hours=1)
    first.sent_at = an_hour_ago
    ready.need.requested_at = an_hour_ago
    y = NeedsItem(
        loan_file_id=ready.loan_file.id,
        title="Pay stubs",
        needs_type="pay_stub",
        origin=NeedsItemOrigin.FINDING,
    )
    db.add(y)
    await db.flush()
    second = (
        await add_needs_to_draft(
            db, loan_file=ready.loan_file, needs=[ready.need, y], actor_user_id=ready.user.id
        )
    ).draft
    await db.commit()
    first.sent_at = an_hour_ago  # restated: nothing above may move it
    await send_draft(
        db,
        loan_file=ready.loan_file,
        draft_id=second.id,
        recipient=TO,
        body="Second request.",
        approver_user_id=ready.user.id,
        transmit=True,
    )
    await db.commit()
    assert ready.need.requested_at is not None and ready.need.requested_at > an_hour_ago
    return ready, second, y


async def test_a_failed_send_does_not_unask_what_an_earlier_email_asked(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage
) -> None:
    """Review #1. The earlier email went out, so X stays requested with ITS time; Y, asked only by
    the failed email, goes back to pending (the control)."""
    ready, second, y = await _asked_twice(db)
    sender.error = SendError("MessageRejected", outcome_unknown=False)
    assert await outbound._send_communication(db, str(second.id)) == "failed"

    await db.refresh(ready.need)
    await db.refresh(y)
    assert ready.need.status is NeedsItemStatus.REQUESTED
    first = await db.get(Communication, ready.draft.id)
    assert first is not None and ready.need.requested_at == first.sent_at
    assert y.status is NeedsItemStatus.PENDING
    assert y.requested_at is None
    activity = await db.scalar(
        select(ActivityLog).where(
            ActivityLog.loan_file_id == ready.loan_file.id,
            ActivityLog.activity_type == ActivityType.COMMUNICATION_FAILED,
        )
    )
    assert activity is not None and activity.detail["needs_items_unwound"] == 1


async def test_a_bounce_does_not_unask_what_an_earlier_email_asked(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage
) -> None:
    """The same rule on the bounce path, which shares `_unwind_requests`."""
    from app.services.bounce_handling import (
        BounceClass,
        DeliveryFailure,
        record_delivery_failure,
    )

    ready, second, y = await _asked_twice(db)
    assert await outbound._send_communication(db, str(second.id)) == "sent"
    await record_delivery_failure(
        db,
        failure=DeliveryFailure(
            message_id=second.external_message_id,
            recipient=TO,
            status_code="5.1.1",
            diagnostic=None,
            bounce_class=BounceClass.PERMANENT,
        ),
    )
    await db.flush()
    first = await db.get(Communication, ready.draft.id)
    assert first is not None
    assert ready.need.status is NeedsItemStatus.REQUESTED
    assert ready.need.requested_at == first.sent_at
    assert y.status is NeedsItemStatus.PENDING


@pytest.mark.parametrize("where", ["file_address", "database_error", "commit_after_copy"])
async def test_an_unexpected_error_before_sending_is_a_clean_failure(
    db: AsyncSession,
    sender: FakeSender,
    storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
    where: str,
) -> None:
    """Review #2. Nothing reached the provider, so the row must not be left `sending`."""
    ready = await _queued(db)
    if where == "file_address":

        async def broken(*_args: object) -> str:
            raise RuntimeError("database went away")

        monkeypatch.setattr(outbound, "file_address", broken)
    elif where == "database_error":
        # A REAL database error, which leaves the session needing a rollback before it can write
        # the failure. Review mutation F2c (no rollback) survived the plain RuntimeError above.
        from sqlalchemy import text

        async def failing_query(session: AsyncSession, *_args: object) -> str:
            await session.execute(text("SELECT 1 / 0"))
            return ""

        monkeypatch.setattr(outbound, "file_address", failing_query)
    else:
        real_commit = db.commit
        calls = {"n": 0}

        async def commit() -> None:
            calls["n"] += 1
            if calls["n"] == 2:  # 1 = the claim, 2 = after the copy is saved
                raise RuntimeError("connection reset")
            await real_commit()

        monkeypatch.setattr(db, "commit", commit)
    with capture_logs() as logs:
        assert await outbound._send_communication(db, str(ready.draft.id)) == "failed"
    code = "DBAPIError" if where == "database_error" else "RuntimeError"
    await _assert_clean_failure(db, ready, logs, code=code)
    assert sender.sent == []
    assert "database went away" not in _logged_text(logs)
    assert "connection reset" not in _logged_text(logs)


async def test_the_timeline_says_an_unconfirmed_send_needs_checking(
    db: AsyncSession, sender: FakeSender, storage: FakeStorage
) -> None:
    """Review #5. Built through the worker, so the reader is checked against what the writer wrote."""
    from app.services.timeline import _summarise

    sender.error = SendError("ReadTimeoutError", outcome_unknown=True)
    ready = await _queued(db)
    await outbound._send_communication(db, str(ready.draft.id))
    row = await _reload(db, ready.draft)
    assert _summarise(row) == "Sending was not confirmed; check before sending again"
