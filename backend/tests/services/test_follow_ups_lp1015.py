"""LP-1015 — the test command that moves a follow-up's conversation back N days, and two job fixes:
a blocked address stops the follow-up, and a closed or withdrawn file is skipped.

Fixtures and helpers are LP-1013's (`test_follow_ups_lp1013`), as in LP-1014's tests.
"""

from __future__ import annotations

import argparse
from datetime import timedelta
from uuid import uuid4

import pytest
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
    FollowUpStatus,
)
from app.models.inbound_message import InboundMessage, InboundRoutingState
from app.models.loan_file import LoanFileStatus
from app.models.suppressed_address import SuppressionReason
from app.scripts import follow_up_clock
from app.scripts.follow_up_clock import Refused, move_back
from app.services.bounce_handling import suppress_address
from app.services.follow_ups import due_moment
from app.tasks import follow_ups as job
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs
from tests.outbound_send import FakeSender
from tests.services import test_follow_ups_lp1013 as lp1013
from tests.services.test_follow_ups_lp1013 import TO, WED_2PM, _api, _original, _reminders

db = lp1013.db
enqueued = lp1013.enqueued
sender = lp1013.sender
_storage_dir = lp1013._storage_dir


def _list_path(original: lp1013.Original) -> str:
    return f"/loan-files/{original.ready.loan_file.display_id}/follow-ups"


async def _reply(db: AsyncSession, original: lp1013.Original, address: str = TO) -> InboundMessage:
    message = InboundMessage(
        ingest_key=uuid4().hex,
        from_address=address,
        loan_file_id=original.ready.loan_file.id,
        company_id=original.ready.company.id,
        routing_state=InboundRoutingState.ROUTED,
    )
    db.add(message)
    await db.flush()
    return message


# --------------------------------------------------------------------------------------------- #
# The command
# --------------------------------------------------------------------------------------------- #
async def test_it_moves_every_timestamp_the_job_and_the_rate_limit_read(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    original = await _original(db)
    await job.send_follow_ups(db, now=WED_2PM)  # one reminder, so there is one to move
    [reminder] = await _reminders(db, original.row)
    reply = await _reply(db, original)
    other_address = await _reply(db, original, "someone.else@example.test")
    original.row.follow_up_paused_at = WED_2PM
    await db.commit()
    before = {
        "clock": original.row.follow_up_clock_at,
        "paused": original.row.follow_up_paused_at,
        "requested": original.row.send_requested_at,
        "sent": original.row.sent_at,
        "reminder": reminder.send_requested_at,
        "reply": reply.created_at,
        "other": other_address.created_at,
    }

    report = await move_back(db, original.row.id, 3)

    three = timedelta(days=3)
    assert original.row.follow_up_clock_at == before["clock"] - three
    assert original.row.follow_up_paused_at == before["paused"] - three
    assert original.row.send_requested_at == before["requested"] - three
    assert original.row.sent_at == before["sent"] - three
    assert reminder.send_requested_at == before["reminder"] - three
    assert reply.created_at == before["reply"] - three
    assert other_address.created_at == before["other"]  # not the recipient: left alone
    assert report.status == "on"
    assert report.next_reminder_at == due_moment(original.row)
    assert {(m.what, m.field) for m in report.moved} >= {
        ("original", "follow_up_clock_at"),
        ("original", "follow_up_paused_at"),
        ("original", "send_requested_at"),
        ("reminder", "send_requested_at"),
        ("reply", "created_at"),
    }


async def test_no_next_reminder_is_reported_when_none_will_go(db: AsyncSession) -> None:
    """Spent or paused: the screen shows no next date, and neither does the command."""
    original = await _original(db)
    original.row.follow_up_auto_sent = original.row.follow_up_max_auto
    report = await move_back(db, original.row.id, 1)
    assert report.next_reminder_at is None
    original.row.follow_up_auto_sent = 0
    original.row.follow_up_status = FollowUpStatus.PAUSED
    report = await move_back(db, original.row.id, 1)
    assert (report.status, report.next_reminder_at) == ("paused", None)


async def test_other_emails_to_the_same_address_keep_their_times(db: AsyncSession) -> None:
    """The 5-minute and 3-a-day limits still count them."""
    first = await _original(db)
    second = await _original(db, ready=first.ready)
    kept = second.row.send_requested_at
    await move_back(db, first.row.id, 3)
    assert second.row.send_requested_at == kept


async def test_moved_back_by_the_interval_the_job_sends_it(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    """The command's purpose: a reminder due without waiting, on the job's next run."""
    original = await _original(db)
    original.row.follow_up_clock_at = WED_2PM - timedelta(days=1)
    await db.commit()
    assert await job.send_follow_ups(db, now=WED_2PM) == {}
    await move_back(db, original.row.id, 3)
    await db.commit()
    assert await job.send_follow_ups(db, now=WED_2PM) == {"sent": 1}


async def test_it_refuses_a_reminder(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    original = await _original(db)
    await job.send_follow_ups(db, now=WED_2PM)
    [reminder] = await _reminders(db, original.row)
    with pytest.raises(Refused, match="This is a reminder"):
        await move_back(db, reminder.id, 3)


async def test_it_refuses_what_is_not_a_sent_original(db: AsyncSession) -> None:
    original = await _original(db)
    inbound = Communication(
        loan_file_id=original.ready.loan_file.id,
        direction=CommunicationDirection.INBOUND,
        status=CommunicationStatus.RECEIVED,
    )
    db.add(inbound)
    await db.flush()
    with pytest.raises(Refused, match="not an email sent from the app"):
        await move_back(db, inbound.id, 3)
    with pytest.raises(Refused, match="No such email"):
        await move_back(db, uuid4(), 3)
    with pytest.raises(Refused, match="1 or more"):
        await move_back(db, original.row.id, 0)


async def test_it_refuses_outside_dev_and_staging(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Before the database is touched: no id is even looked up."""
    monkeypatch.setattr(follow_up_clock.settings, "environment", "production")
    args = argparse.Namespace(communication_id=str(uuid4()), days=3)
    assert await follow_up_clock._main(args) == 1
    assert "runs only in development or staging" in capsys.readouterr().err


@pytest.mark.parametrize("environment", ["development", "staging"])
def test_dev_and_staging_are_allowed(environment: str) -> None:
    assert environment in follow_up_clock.ALLOWED_ENVIRONMENTS


# --------------------------------------------------------------------------------------------- #
# A blocked address stops it
# --------------------------------------------------------------------------------------------- #
async def test_a_blocked_address_stops_it_with_its_own_log_line(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    original = await _original(db)
    await suppress_address(
        db, company_id=original.ready.company.id, address=TO, reason=SuppressionReason.COMPLAINT
    )
    await db.commit()
    with capture_logs() as logs:
        assert await job.send_follow_ups(db, now=WED_2PM) == {"stopped_suppressed": 1}
    assert [e["event"] for e in logs if e["event"].startswith("follow_up_")] == [
        "follow_up_recipient_suppressed"
    ]
    await db.refresh(original.row)
    assert original.row.follow_up_status is FollowUpStatus.STOPPED
    # Not picked again: the next run has nothing.
    assert await job.send_follow_ups(db, now=WED_2PM + timedelta(minutes=15)) == {}


async def test_a_rate_limit_is_still_retried(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    """The control: the other refusal stays `on`, with the general log line."""
    from app.models.base import utcnow

    original = await _original(db)
    original.row.sent_at = utcnow()
    await db.commit()
    with capture_logs() as logs:
        assert await job.send_follow_ups(db, now=WED_2PM) == {"refused_rate_limited": 1}
    assert "follow_up_refused" in [e["event"] for e in logs]
    await db.refresh(original.row)
    assert original.row.follow_up_status is FollowUpStatus.ON


async def test_the_list_says_the_address_is_blocked(db: AsyncSession) -> None:
    blocked = await _original(db)
    fine = await _original(db, recipient="title@title-co.example.test", ready=blocked.ready)
    await suppress_address(
        db,
        company_id=blocked.ready.company.id,
        address=f"  {TO.upper()} ",
        reason=SuppressionReason.HARD_BOUNCE,
    )
    await db.commit()
    status, body = await _api(db, blocked.ready.user, "GET", _list_path(blocked))
    assert status == 200
    by_id = {r["communication_id"]: r for r in body}  # type: ignore[union-attr]
    assert by_id[str(blocked.row.id)]["recipient_suppressed"] is True
    assert by_id[str(fine.row.id)]["recipient_suppressed"] is False


# --------------------------------------------------------------------------------------------- #
# A closed or withdrawn file is skipped
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("done", [LoanFileStatus.CLOSED, LoanFileStatus.WITHDRAWN])
async def test_a_closed_or_withdrawn_file_is_skipped(
    db: AsyncSession, sender: FakeSender, enqueued: list[str], done: LoanFileStatus
) -> None:
    original = await _original(db)
    original.ready.loan_file.status = done
    await db.commit()
    assert await job.send_follow_ups(db, now=WED_2PM) == {}
    assert await _reminders(db, original.row) == []
    await db.refresh(original.row)
    assert original.row.follow_up_status is FollowUpStatus.ON  # set back, it goes again


async def test_a_file_still_in_progress_is_not_skipped(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    """The control for the test above."""
    original = await _original(db)
    original.ready.loan_file.status = LoanFileStatus.CLEAR_TO_CLOSE
    await db.commit()
    assert await job.send_follow_ups(db, now=WED_2PM) == {"sent": 1}
