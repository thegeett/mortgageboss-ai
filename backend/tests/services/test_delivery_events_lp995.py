"""LP-995 — what SES reports about a sent email, applied to that email, and the job that reads them.

The events are the shapes AWS documents for configuration-set events with raw delivery
(`tests/fixtures/ses_events/`), with the message id and recipients filled in per test.

The session joins the test transaction with savepoints, so the queue job's own commits and rollbacks
behave as they do in the worker.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from app.core.config import settings
from app.models.activity_log import ActivityLog, ActivityType
from app.models.base import utcnow
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.needs_item import NeedsItem, NeedsItemOrigin, NeedsItemStatus
from app.models.suppressed_address import SuppressedAddress, SuppressionReason
from app.scripts.inject_delivery_event import KINDS, build_event
from app.services.delivery_events import (
    COMPLAINT_SUMMARY,
    DELIVERED_AFTER_FAILURE,
    SUPPRESSED_BEFORE,
    apply_delivery_event,
)
from app.services.email_draft import add_needs_to_draft
from app.services.email_send import CannotSendError, send_draft
from app.tasks import outbound
from app.tasks.celery_app import celery_app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from structlog.testing import capture_logs
from tests.outbound_send import Ready, ready_to_send

FIXTURES = Path(__file__).parent.parent / "fixtures" / "ses_events"
TO = "borrower@example.test"
SUBJECT = "Documents we need for your loan"
MESSAGE_ID = "0100019a0b0c0d0e-1f2a3b4c-5d6e-7f80-9a0b-1c2d3e4f5a6b-000000"


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


def ses_event(
    name: str,
    *,
    recipient: str = TO,
    cc: str = "processor@example.test",
    message_id: str = MESSAGE_ID,
    status: str | None = "5.1.1",
) -> dict[str, Any]:
    """A fixture event with the message id and addresses filled in. `status` is for Undetermined."""
    text = (FIXTURES / name).read_text()
    for placeholder, value in (
        ("MESSAGE_ID", message_id),
        ("TO_ADDRESS", TO),
        ("CC_ADDRESS", cc),
        ("RECIPIENT", recipient),
        ("SUBJECT_TEXT", SUBJECT),
    ):
        text = text.replace(placeholder, value)
    event: dict[str, Any] = json.loads(text)
    if name == "bounce_undetermined.json":
        bounced = event["bounce"]["bouncedRecipients"][0]
        if status is None:
            del bounced["status"]
        else:
            bounced["status"] = status
    return event


async def _sent(db: AsyncSession, *, recipient: str = TO) -> tuple[Ready, Communication]:
    """A sent email asking for one need, with SES's message id, as LP-994's worker leaves it."""
    ready = await ready_to_send(db)
    row = await send_draft(
        db,
        loan_file=ready.loan_file,
        draft_id=ready.draft.id,
        recipient=recipient,
        subject=SUBJECT,
        body="Please send these.",
        approver_user_id=ready.user.id,
    )
    row.external_message_id = MESSAGE_ID
    await db.commit()
    assert row.status is CommunicationStatus.SENT
    assert ready.need.status is NeedsItemStatus.REQUESTED
    return ready, row


async def _failed_activities(db: AsyncSession, row: Communication) -> list[ActivityLog]:
    rows = (
        await db.scalars(
            select(ActivityLog).where(
                ActivityLog.loan_file_id == row.loan_file_id,
                ActivityLog.activity_type == ActivityType.COMMUNICATION_FAILED,
            )
        )
    ).all()
    return [a for a in rows if a.detail.get("communication_id") == str(row.id)]


async def _suppressed(
    db: AsyncSession, ready: Ready, address: str = TO
) -> SuppressedAddress | None:
    return await db.scalar(
        select(SuppressedAddress).where(
            SuppressedAddress.company_id == ready.company.id,
            SuppressedAddress.address == address,
        )
    )


# --------------------------------------------------------------------------------------------- #
# Delivery
# --------------------------------------------------------------------------------------------- #
async def test_delivery_marks_a_sent_email_delivered_once(db: AsyncSession) -> None:
    _ready, row = await _sent(db)

    assert await apply_delivery_event(db, ses_event("delivery.json")) == "delivered"
    assert row.status is CommunicationStatus.DELIVERED
    assert await apply_delivery_event(db, ses_event("delivery.json")) == "duplicate"
    assert row.status is CommunicationStatus.DELIVERED


async def test_a_late_delivery_never_undoes_a_bounce(db: AsyncSession) -> None:
    _ready, row = await _sent(db)
    await apply_delivery_event(db, ses_event("bounce_permanent.json"))
    detail = row.error_detail

    assert await apply_delivery_event(db, ses_event("delivery.json")) == "ignored"
    assert row.status is CommunicationStatus.FAILED
    assert row.error_detail == detail


# --------------------------------------------------------------------------------------------- #
# Bounce
# --------------------------------------------------------------------------------------------- #
async def test_a_permanent_bounce_fails_blocks_and_unwinds_once(db: AsyncSession) -> None:
    ready, row = await _sent(db)

    assert await apply_delivery_event(db, ses_event("bounce_permanent.json")) == "bounced"
    assert row.status is CommunicationStatus.FAILED
    assert row.error_detail is not None and "5.1.1" in row.error_detail
    blocked = await _suppressed(db, ready)
    assert blocked is not None and blocked.reason is SuppressionReason.HARD_BOUNCE
    assert ready.need.status is NeedsItemStatus.PENDING
    assert len(await _failed_activities(db, row)) == 1

    ready.need.status = NeedsItemStatus.REQUESTED  # anything a second apply would unwind again
    assert await apply_delivery_event(db, ses_event("bounce_permanent.json")) == "duplicate"
    assert ready.need.status is NeedsItemStatus.REQUESTED
    assert len(await _failed_activities(db, row)) == 1


async def test_a_bounce_after_a_delivery_still_fails_the_email(db: AsyncSession) -> None:
    """A receiving server can accept a message and bounce it later; SES reports both, in order."""
    ready, row = await _sent(db)
    await apply_delivery_event(db, ses_event("delivery.json"))

    assert await apply_delivery_event(db, ses_event("bounce_permanent.json")) == "bounced"
    assert row.status is CommunicationStatus.FAILED
    assert ready.need.status is NeedsItemStatus.PENDING


async def test_on_account_suppression_list_is_permanent_with_its_own_message(
    db: AsyncSession,
) -> None:
    ready, row = await _sent(db)

    assert await apply_delivery_event(db, ses_event("bounce_suppressed.json")) == "bounced"
    assert row.status is CommunicationStatus.FAILED
    assert row.error_detail == (
        "Not delivered: this address bounced or complained before. "
        "Ask the borrower for another address."
    )
    assert row.error_detail == SUPPRESSED_BEFORE
    assert await _suppressed(db, ready) is not None
    assert ready.need.status is NeedsItemStatus.PENDING


async def test_a_transient_bounce_is_final_unwinds_but_does_not_block(db: AsyncSession) -> None:
    ready, row = await _sent(db)

    assert await apply_delivery_event(db, ses_event("bounce_transient.json")) == "bounced"
    assert row.status is CommunicationStatus.FAILED
    assert await _suppressed(db, ready) is None
    assert ready.need.status is NeedsItemStatus.PENDING  # review #1: SES will not retry it
    assert ready.need.requested_at is None
    (activity,) = await _failed_activities(db, row)
    assert "temporary problem at the recipient's mail server" in activity.summary
    assert "retried" not in activity.summary
    assert activity.detail["bounce_class"] == "transient"


@pytest.mark.parametrize(
    ("status", "blocked", "bounce_class"),
    [("5.1.1", True, "permanent"), (None, False, "unknown")],
)
async def test_undetermined_falls_back_to_the_status_code(
    db: AsyncSession, status: str | None, blocked: bool, bounce_class: str
) -> None:
    ready, row = await _sent(db)

    event = ses_event("bounce_undetermined.json", status=status)
    assert await apply_delivery_event(db, event) == "bounced"
    assert row.status is CommunicationStatus.FAILED
    assert (await _suppressed(db, ready) is not None) is blocked
    (activity,) = await _failed_activities(db, row)
    assert activity.detail["bounce_class"] == bounce_class


# --------------------------------------------------------------------------------------------- #
# Complaint
# --------------------------------------------------------------------------------------------- #
async def test_a_complaint_blocks_the_address_and_keeps_the_status(db: AsyncSession) -> None:
    ready, row = await _sent(db)
    await apply_delivery_event(db, ses_event("delivery.json"))

    assert await apply_delivery_event(db, ses_event("complaint.json")) == "complaint"
    assert row.status is CommunicationStatus.DELIVERED
    blocked = await _suppressed(db, ready)
    assert blocked is not None and blocked.reason is SuppressionReason.COMPLAINT
    (activity,) = await _failed_activities(db, row)
    assert activity.summary == COMPLAINT_SUMMARY
    assert activity.detail["event"] == "complaint"
    assert ready.need.status is NeedsItemStatus.REQUESTED

    assert await apply_delivery_event(db, ses_event("complaint.json")) == "duplicate"
    assert len(await _failed_activities(db, row)) == 1


async def test_sending_to_a_complained_address_is_refused_with_the_new_wording(
    db: AsyncSession,
) -> None:
    ready, _row = await _sent(db)
    await apply_delivery_event(db, ses_event("complaint.json"))
    need = NeedsItem(
        loan_file_id=ready.loan_file.id,
        title="Pay stubs",
        needs_type="pay_stub",
        origin=NeedsItemOrigin.FINDING,
    )
    db.add(need)
    await db.flush()
    draft = await add_needs_to_draft(
        db, loan_file=ready.loan_file, needs=[need], actor_user_id=ready.user.id
    )

    with pytest.raises(CannotSendError) as refused:
        await send_draft(
            db,
            loan_file=ready.loan_file,
            draft_id=draft.draft.id,
            recipient=TO,
            body="Please send these.",
            approver_user_id=ready.user.id,
        )
    assert str(refused.value) == (
        f"{TO} is blocked: an earlier email to it bounced or was marked as spam. "
        "Confirm the address with the borrower before sending again."
    )


# --------------------------------------------------------------------------------------------- #
# Reject and Rendering Failure
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("fixture", "detail"),
    [
        ("reject.json", "Not sent: SES refused it (Bad content)."),
        (
            "rendering_failure.json",
            "Not sent: SES refused it "
            "(Attribute 'borrower_name' is not present in the rendering data.).",
        ),
    ],
)
async def test_a_refusal_fails_and_unwinds(db: AsyncSession, fixture: str, detail: str) -> None:
    ready, row = await _sent(db)

    assert await apply_delivery_event(db, ses_event(fixture)) == "rejected"
    assert row.status is CommunicationStatus.FAILED
    assert row.error_detail == detail
    assert ready.need.status is NeedsItemStatus.PENDING
    assert ready.need.requested_at is None
    assert await _suppressed(db, ready) is None
    assert await apply_delivery_event(db, ses_event(fixture)) == "duplicate"
    assert len(await _failed_activities(db, row)) == 1


# --------------------------------------------------------------------------------------------- #
# Only the To recipient counts
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "fixture",
    ["delivery.json", "bounce_permanent.json", "bounce_suppressed.json", "complaint.json"],
)
async def test_an_event_about_the_ccd_processor_changes_nothing(
    db: AsyncSession, fixture: str
) -> None:
    ready, row = await _sent(db)
    processor = ready.user.email

    event = ses_event(fixture, recipient=processor, cc=processor)
    assert await apply_delivery_event(db, event) == "ignored"
    assert row.status is CommunicationStatus.SENT
    assert row.error_detail is None
    assert await _suppressed(db, ready, processor) is None
    assert await _suppressed(db, ready) is None
    assert ready.need.status is NeedsItemStatus.REQUESTED
    assert await _failed_activities(db, row) == []


@pytest.mark.parametrize("stored", ["Borrower@Example.TEST", "  borrower@example.test "])
@pytest.mark.parametrize("fixture", ["delivery.json", "bounce_permanent.json", "complaint.json"])
async def test_the_to_recipient_matches_case_and_spacing(
    db: AsyncSession, stored: str, fixture: str
) -> None:
    _ready, row = await _sent(db)
    row.recipient = stored  # as a processor might have typed it
    await db.flush()

    event = ses_event(fixture, recipient=f" {TO.upper()} ")
    assert await apply_delivery_event(db, event) in {"delivered", "bounced", "complaint"}


# --------------------------------------------------------------------------------------------- #
# What is not ours
# --------------------------------------------------------------------------------------------- #
async def test_an_unknown_message_id_is_unmatched(db: AsyncSession) -> None:
    _ready, row = await _sent(db)
    event = ses_event("bounce_permanent.json", message_id="someone-elses-message")

    assert await apply_delivery_event(db, event) == "unmatched"
    assert row.status is CommunicationStatus.SENT


@pytest.mark.parametrize("event_type", ["Open", "DeliveryDelay", "Send"])
async def test_an_unknown_event_type_is_ignored(db: AsyncSession, event_type: str) -> None:
    _ready, row = await _sent(db)
    event = ses_event("delivery.json")
    event["eventType"] = event_type

    assert await apply_delivery_event(db, event) == "ignored"
    assert row.status is CommunicationStatus.SENT


async def test_logs_carry_no_address_subject_or_diagnostic(db: AsyncSession) -> None:
    """Every event type and outcome, captured; none may name the borrower or quote the email."""
    _ready, row = await _sent(db)
    with capture_logs() as logs:
        for fixture in ("delivery.json", "complaint.json", "bounce_permanent.json"):
            await apply_delivery_event(db, ses_event(fixture))
        await apply_delivery_event(
            db, ses_event("delivery.json", recipient="processor@example.test")
        )
        await apply_delivery_event(db, ses_event("reject.json", message_id="unknown"))
    blob = json.dumps(logs, default=str)
    assert {log["outcome"] for log in logs if log["event"] == "delivery_event"} >= {
        "delivered",
        "complaint",
        "bounced",
        "ignored",
        "unmatched",
    }
    for secret in (TO, "processor@example.test", SUBJECT, "user unknown", "example.test"):
        assert secret not in blob
    assert str(row.id) in blob  # the positive control: the logs do say which email


# --------------------------------------------------------------------------------------------- #
# The dev script's events
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("kind", "outcome", "status"),
    [
        ("delivery", "delivered", CommunicationStatus.DELIVERED),
        ("bounce", "bounced", CommunicationStatus.FAILED),
        ("bounce-suppressed", "bounced", CommunicationStatus.FAILED),
        ("bounce-transient", "bounced", CommunicationStatus.FAILED),
        ("complaint", "complaint", CommunicationStatus.SENT),
        ("reject", "rejected", CommunicationStatus.FAILED),
    ],
)
async def test_the_dev_script_builds_events_the_handler_applies(
    db: AsyncSession, kind: str, outcome: str, status: CommunicationStatus
) -> None:
    _ready, row = await _sent(db)
    assert kind in KINDS

    event = build_event(kind, message_id=MESSAGE_ID, recipient=TO)
    assert await apply_delivery_event(db, event) == outcome
    assert row.status is status


# --------------------------------------------------------------------------------------------- #
# The queue job
# --------------------------------------------------------------------------------------------- #
class FakeSqs:
    """Hands out queued batches; records deletes. `repeat` returns the same batch forever.

    With `session`, a delete while that session still has uncommitted work fails the test: commit,
    then delete, or a crash between the two loses the event.
    """

    def __init__(
        self,
        batches: list[list[dict[str, Any]]],
        *,
        repeat: bool = False,
        session: AsyncSession | None = None,
    ) -> None:
        self.batches = batches
        self.repeat = repeat
        self.session = session
        self.receives = 0
        self.deleted: list[str] = []

    def receive_message(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["MaxNumberOfMessages"] == 10 and kwargs["WaitTimeSeconds"] == 1
        self.receives += 1
        if self.repeat:
            return {"Messages": self.batches[0]}
        return {"Messages": self.batches.pop(0)} if self.batches else {}

    def delete_message(self, *, QueueUrl: str, ReceiptHandle: str) -> None:
        assert self.session is None or not self.session.in_transaction(), "deleted before commit"
        self.deleted.append(ReceiptHandle)


def _message(handle: str, body: str | dict[str, Any]) -> dict[str, Any]:
    return {
        "MessageId": f"sqs-{handle}",
        "ReceiptHandle": handle,
        "Body": body if isinstance(body, str) else json.dumps(body),
    }


async def test_the_job_deletes_what_it_handled_and_keeps_what_failed(db: AsyncSession) -> None:
    _ready, row = await _sent(db)
    no_mail = ses_event("delivery.json")
    del no_mail["mail"]
    client = FakeSqs(
        [
            [
                _message("not-json", "{this is not json"),
                _message("raises", no_mail),
                _message("delivered", ses_event("delivery.json")),
                _message("duplicate", ses_event("delivery.json")),
                _message("unmatched", ses_event("delivery.json", message_id="nobody")),
                _message("ignored", ses_event("delivery.json", recipient="processor@example.test")),
            ]
        ],
        session=db,
    )

    with capture_logs() as logs:
        handled = await outbound._read_delivery_events(db, client, "https://sqs/events")

    assert handled == 4
    assert client.deleted == ["delivered", "duplicate", "unmatched", "ignored"]
    await db.refresh(row)
    assert row.status is CommunicationStatus.DELIVERED
    failed = [log for log in logs if log["event"] == "delivery_event_failed"]
    assert [(log["sqs_message_id"], log["error"]) for log in failed] == [
        ("sqs-not-json", "JSONDecodeError"),
        ("sqs-raises", "KeyError"),
    ]
    assert "this is not json" not in json.dumps(logs, default=str)


async def test_a_handler_error_is_rolled_back_and_the_batch_goes_on(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first event writes and then raises: its write must not survive into the next commit."""
    _ready, row = await _sent(db)
    real = outbound.apply_delivery_event
    calls = 0

    async def half_applies_then_raises(session: AsyncSession, event: dict[str, Any]) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            row.error_detail = "written by a handler that then failed"
            await session.flush()
            raise RuntimeError("boom")
        return await real(session, event)

    monkeypatch.setattr(outbound, "apply_delivery_event", half_applies_then_raises)
    client = FakeSqs(
        [
            [
                _message("first", ses_event("delivery.json")),
                _message("second", ses_event("delivery.json")),
            ]
        ]
    )

    assert await outbound._read_delivery_events(db, client, "https://sqs/events") == 1
    assert client.deleted == ["second"]
    await db.refresh(row)
    assert row.status is CommunicationStatus.DELIVERED
    assert row.error_detail is None


async def test_the_job_reads_at_most_five_batches(db: AsyncSession) -> None:
    unmatched = [
        _message(f"m{i}", ses_event("delivery.json", message_id=f"x{i}")) for i in range(10)
    ]
    client = FakeSqs([unmatched], repeat=True)

    assert await outbound._read_delivery_events(db, client, "https://sqs/events") == 50
    assert client.receives == 5


async def test_the_job_stops_when_the_queue_is_drained(db: AsyncSession) -> None:
    client = FakeSqs([[_message("one", ses_event("delivery.json", message_id="x"))], []])

    assert await outbound._read_delivery_events(db, client, "https://sqs/events") == 1
    assert client.receives == 1


def test_no_queue_url_means_no_sqs_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_client() -> None:
        raise AssertionError("SQS was called")

    monkeypatch.setattr(settings, "events_queue_url", None)
    monkeypatch.setattr(outbound, "_events_client", no_client)
    assert outbound.read_delivery_events() == 0

    # The positive control: with a URL, the client IS built.
    monkeypatch.setattr(settings, "events_queue_url", "https://sqs/events")
    with pytest.raises(AssertionError, match="SQS was called"):
        outbound.read_delivery_events()


def test_the_beat_reads_the_events_queue_every_minute() -> None:
    entry = celery_app.conf.beat_schedule["read-delivery-events"]
    assert entry == {
        "task": "communications.read_delivery_events",
        "schedule": 60.0,
        "options": {"expires": 60},
    }
    assert entry["task"] in celery_app.tasks


def test_a_blank_events_queue_url_is_none() -> None:
    assert type(settings)(events_queue_url="  ").events_queue_url is None


# --------------------------------------------------------------------------------------------- #
# Review fixes
# --------------------------------------------------------------------------------------------- #
#: An SES event as it arrives with raw delivery switched OFF: wrapped in the SNS envelope.
SNS_ENVELOPE = {
    "Type": "Notification",
    "MessageId": "8f6e0a6c-0000-0000-0000-000000000000",
    "TopicArn": "arn:aws:sns:us-east-1:123456789012:mbai-staging-outbound-mail-events",
    "Message": '{"eventType": "Bounce"}',
    "Timestamp": "2026-10-21T02:56:12.300Z",
}
#: An SES identity notification: `notificationType`, not `eventType`.
IDENTITY_NOTIFICATION = {"notificationType": "Bounce", "mail": {"messageId": MESSAGE_ID}}


@pytest.mark.parametrize("message", [SNS_ENVELOPE, IDENTITY_NOTIFICATION, {"eventType": None}])
async def test_a_message_without_an_event_type_raises(
    db: AsyncSession, message: dict[str, Any]
) -> None:
    """Review #2. "Ignored" is deleted; a message that is not an SES event must reach the DLQ."""
    await _sent(db)
    with pytest.raises(ValueError, match="eventType"):
        await apply_delivery_event(db, message)


async def test_the_job_keeps_an_sns_envelope_for_the_dlq(db: AsyncSession) -> None:
    client = FakeSqs([[_message("wrapped", SNS_ENVELOPE)]], session=db)

    assert await outbound._read_delivery_events(db, client, "https://sqs/events") == 0
    assert client.deleted == []


async def test_a_deleted_email_is_unmatched(db: AsyncSession) -> None:
    """Review #9: as LP-994's worker treats a deleted row."""
    ready, row = await _sent(db)
    row.deleted_at = utcnow()
    await db.flush()

    assert await apply_delivery_event(db, ses_event("bounce_permanent.json")) == "unmatched"
    assert row.status is CommunicationStatus.SENT
    assert await _suppressed(db, ready) is None


async def test_the_bounce_lands_on_the_email_the_handler_matched(db: AsyncSession) -> None:
    """Review #7. An inbound row with the same message id, inserted first: the old lookup inside
    `record_delivery_failure` had no direction filter and could fail that row instead. (Which row an
    unordered query returns is not guaranteed; insertion order makes the old code pick the inbound
    one here.)"""
    ready, row = await _sent(db)
    inbound = Communication(
        loan_file_id=ready.loan_file.id,
        direction=CommunicationDirection.INBOUND,
        status=CommunicationStatus.RECEIVED,
        external_message_id=MESSAGE_ID,
    )
    db.add(inbound)
    await db.flush()
    # Put the inbound row first in the heap, so an unfiltered lookup finds it.
    row.external_message_id = None
    await db.flush()
    row.external_message_id = MESSAGE_ID
    await db.flush()

    assert await apply_delivery_event(db, ses_event("bounce_permanent.json")) == "bounced"
    assert row.status is CommunicationStatus.FAILED
    assert inbound.status is CommunicationStatus.RECEIVED


async def test_a_delivery_after_a_temporary_bounce_marks_it_delivered(db: AsyncSession) -> None:
    """Review #8. The email did arrive. The needs the bounce unwound stay pending, and the file
    says so."""
    ready, row = await _sent(db)
    await apply_delivery_event(db, ses_event("bounce_transient.json"))
    assert ready.need.status is NeedsItemStatus.PENDING

    assert await apply_delivery_event(db, ses_event("delivery.json")) == "delivered"
    assert row.status is CommunicationStatus.DELIVERED
    assert row.error_detail is None
    assert ready.need.status is NeedsItemStatus.PENDING
    entry = await db.scalar(
        select(ActivityLog).where(
            ActivityLog.loan_file_id == row.loan_file_id,
            ActivityLog.activity_type == ActivityType.COMMUNICATION_SENT,
            ActivityLog.summary == DELIVERED_AFTER_FAILURE,
        )
    )
    assert entry is not None and entry.detail["communication_id"] == str(row.id)
    assert await apply_delivery_event(db, ses_event("delivery.json")) == "duplicate"


@pytest.mark.parametrize(
    "failure", ["bounce_permanent.json", "bounce_suppressed.json", "reject.json"]
)
async def test_a_delivery_never_undoes_a_permanent_failure(db: AsyncSession, failure: str) -> None:
    """The control for review #8: only a temporary or unclear bounce can be followed by delivery."""
    _ready, row = await _sent(db)
    await apply_delivery_event(db, ses_event(failure))

    assert await apply_delivery_event(db, ses_event("delivery.json")) == "ignored"
    assert row.status is CommunicationStatus.FAILED


class FlakySqs(FakeSqs):
    """`delete_message` fails for the handles in `fail_delete`; `receive_message` can fail outright."""

    def __init__(self, *args: Any, fail_delete: set[str], fail_receive: bool = False, **kw: Any):
        super().__init__(*args, **kw)
        self.fail_delete = fail_delete
        self.fail_receive = fail_receive

    def receive_message(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail_receive:
            raise ConnectionError("sqs unreachable")
        return super().receive_message(**kwargs)

    def delete_message(self, *, QueueUrl: str, ReceiptHandle: str) -> None:
        if ReceiptHandle in self.fail_delete:
            raise ConnectionError("throttled")
        super().delete_message(QueueUrl=QueueUrl, ReceiptHandle=ReceiptHandle)


async def test_a_failed_delete_does_not_end_the_batch(db: AsyncSession) -> None:
    """Review #4. The first event is committed; its delete fails; the second is still handled."""
    _ready, row = await _sent(db)
    client = FlakySqs(
        [
            [
                _message("first", ses_event("delivery.json")),
                _message("second", ses_event("delivery.json")),
            ]
        ],
        fail_delete={"first"},
        session=db,
    )

    with capture_logs() as logs:
        assert await outbound._read_delivery_events(db, client, "https://sqs/events") == 1
    assert client.deleted == ["second"]
    await db.refresh(row)
    assert row.status is CommunicationStatus.DELIVERED
    assert [log["error"] for log in logs if log["event"] == "delivery_event_delete_failed"] == [
        "ConnectionError"
    ]


async def test_a_failed_receive_ends_the_run_quietly(db: AsyncSession) -> None:
    client = FlakySqs([], fail_delete=set(), fail_receive=True)

    with capture_logs() as logs:
        assert await outbound._read_delivery_events(db, client, "https://sqs/events") == 0
    assert [log["event"] for log in logs] == ["delivery_events_receive_failed"]


@pytest.mark.parametrize("environment", ["staging", "production"])
async def test_the_dev_script_refuses_outside_development(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], environment: str
) -> None:
    """Review #3: refused before the database is touched."""
    from app.scripts import inject_delivery_event as script

    def no_db() -> None:
        raise AssertionError("the database was opened")

    monkeypatch.setattr(settings, "environment", environment)
    monkeypatch.setattr(script, "async_session_maker", no_db)
    args = argparse.Namespace(communication=str(uuid4()), type="complaint")

    assert await script._main(args) == 1
    assert "only in development" in capsys.readouterr().err

    # The positive control: in development the guard lets it through to the database.
    monkeypatch.setattr(settings, "environment", "development")
    with pytest.raises(AssertionError, match="database was opened"):
        await script._main(args)


async def test_complaints_about_two_emails_on_one_file_are_each_applied(db: AsyncSession) -> None:
    """Review #6: the duplicate check is per email. A complaint already logged about ANOTHER email
    on the same file must not make this one a duplicate."""
    ready, first = await _sent(db)
    need = NeedsItem(
        loan_file_id=ready.loan_file.id,
        title="Pay stubs",
        needs_type="pay_stub",
        origin=NeedsItemOrigin.FINDING,
    )
    db.add(need)
    await db.flush()
    draft = await add_needs_to_draft(
        db, loan_file=ready.loan_file, needs=[need], actor_user_id=ready.user.id
    )
    other = "co-borrower@example.test"
    second = await send_draft(
        db,
        loan_file=ready.loan_file,
        draft_id=draft.draft.id,
        recipient=other,
        body="Please send these.",
        approver_user_id=ready.user.id,
    )
    second.external_message_id = "second-message-id"
    await db.flush()

    assert await apply_delivery_event(db, ses_event("complaint.json")) == "complaint"
    event = ses_event("complaint.json", recipient=other, message_id="second-message-id")
    assert await apply_delivery_event(db, event) == "complaint"
    assert await _suppressed(db, ready, other) is not None
    assert len(await _failed_activities(db, first)) == 1
    assert len(await _failed_activities(db, second)) == 1
