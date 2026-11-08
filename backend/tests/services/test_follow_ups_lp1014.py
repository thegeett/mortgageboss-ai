"""LP-1014 — the three backend fixes behind the follow-up screen: the file's Follow-ups list, a
deactivated sender stops the follow-up, and a time zone Postgres does not know is refused.

Fixtures and helpers are LP-1013's (`test_follow_ups_lp1013`), imported so both files build the same
originals the same way.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

import pytest
from app.models import Company, LoanProgram
from app.models.base import utcnow
from app.models.communication import CommunicationStatus, FollowUpStatus
from app.schemas import communication as schemas
from app.services.loan_files import create_loan_file
from app.services.timeline import build_timeline
from app.tasks import follow_ups as job
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from tests.outbound_send import FakeSender
from tests.services import test_follow_ups_lp1013 as lp1013
from tests.services.test_follow_ups_lp1013 import WED_2PM, _api, _original, _path, _reminders, _user

# LP-1013's fixtures, under their own names so pytest finds them here.
db = lp1013.db
enqueued = lp1013.enqueued
sender = lp1013.sender
_storage_dir = lp1013._storage_dir


def _list_path(original: object) -> str:
    return f"/loan-files/{original.ready.loan_file.display_id}/follow-ups"  # type: ignore[attr-defined]


# --------------------------------------------------------------------------------------------- #
# 1. The list
# --------------------------------------------------------------------------------------------- #
async def test_the_list_holds_started_follow_ups_newest_first(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    older = await _original(db, subject="Older")
    newer = await _original(db, subject="Newer", ready=older.ready)
    never = await _original(db, subject="Never on", ready=older.ready, follow_up=None)
    stopped = await _original(db, subject="Stopped", ready=older.ready)
    stopped.row.follow_up_status = FollowUpStatus.STOPPED
    # After all four: each `_original` back-dates every send on the file to the same moment.
    base = older.row.send_requested_at
    assert base is not None
    newer.row.send_requested_at = base + timedelta(hours=1)
    stopped.row.send_requested_at = base - timedelta(hours=1)
    await db.commit()
    await job.send_follow_ups(db, now=WED_2PM)  # a reminder on the file must not be listed

    status, body = await _api(db, older.ready.user, "GET", _list_path(older))
    assert status == 200, body
    rows = list(body)  # type: ignore[call-overload]
    assert [r["subject"] for r in rows] == ["Newer", "Older", "Stopped"]
    assert str(never.row.id) not in {r["communication_id"] for r in rows}
    first = rows[0]
    assert first["communication_id"] == str(newer.row.id)
    assert first["recipient"] == "borrower@example.test"
    assert first["sender_name"] == older.ready.user.full_name
    assert first["sender_active"] is True
    assert first["follow_up"]["status"] == "on"
    assert first["follow_up"]["tz"] == "America/New_York"
    assert rows[2]["follow_up"]["status"] == "stopped"


async def test_the_list_says_when_the_sender_is_deactivated(db: AsyncSession) -> None:
    original = await _original(db)
    original.ready.user.is_active = False
    reader = await _user(db, original.ready.company, "Reader")
    await db.commit()
    status, body = await _api(db, reader, "GET", _list_path(original))
    assert status == 200, body
    [row] = list(body)  # type: ignore[call-overload]
    assert row["sender_active"] is False
    assert row["sender_name"] == original.ready.user.full_name


async def test_the_list_is_scoped_to_the_callers_company(db: AsyncSession) -> None:
    original = await _original(db)
    other = Company(name="Other", slug=f"other-{uuid4().hex[:8]}")
    db.add(other)
    await db.flush()
    outsider = await _user(db, other, "Out")
    own_file = await create_loan_file(
        db, company_id=other.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await db.commit()
    status, _ = await _api(db, outsider, "GET", _list_path(original))
    assert status == 404
    status, body = await _api(db, outsider, "GET", f"/loan-files/{own_file.display_id}/follow-ups")
    assert status == 200 and body == []  # type: ignore[comparison-overlap]


# --------------------------------------------------------------------------------------------- #
# 2. A deactivated sender
# --------------------------------------------------------------------------------------------- #
async def test_a_deactivated_sender_stops_it_and_sends_nothing(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    original = await _original(db)
    original.ready.user.is_active = False
    await db.commit()
    assert await job.send_follow_ups(db, now=WED_2PM) == {"stopped_sender_inactive": 1}
    await db.refresh(original.row)
    assert original.row.follow_up_status is FollowUpStatus.STOPPED
    assert await _reminders(db, original.row) == []
    assert enqueued == []


async def test_an_active_sender_still_sends(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    """The positive control for the test above: same original, sender active."""
    await _original(db)
    assert await job.send_follow_ups(db, now=WED_2PM) == {"sent": 1}


# --------------------------------------------------------------------------------------------- #
# 3. The time zone: Python's list AND Postgres's
# --------------------------------------------------------------------------------------------- #
@pytest.fixture
def python_only_zone(monkeypatch: pytest.MonkeyPatch) -> str:
    """A zone Python's check lets through and Postgres does not know. No real one differs on this
    machine (measured: the two lists are equal), so Python's check is told to accept it."""
    zone = "Mars/Olympus_Mons"
    monkeypatch.setattr(schemas, "is_known_time_zone", lambda name: True)
    return zone


async def test_start_refuses_a_zone_postgres_does_not_know(
    db: AsyncSession, python_only_zone: str
) -> None:
    original = await _original(db, follow_up=None)
    status, body = await _api(
        db,
        original.ready.user,
        "POST",
        _path(original, "/follow-up/start"),
        {"tz": python_only_zone},
    )
    assert status == 422, body
    assert f"Unknown time zone: {python_only_zone}" in str(body)
    await db.refresh(original.row)
    assert original.row.follow_up_status is FollowUpStatus.OFF


async def test_patch_refuses_a_zone_postgres_does_not_know(
    db: AsyncSession, python_only_zone: str
) -> None:
    original = await _original(db)
    status, body = await _api(
        db, original.ready.user, "PATCH", _path(original, "/follow-up"), {"tz": python_only_zone}
    )
    assert status == 422, body
    await db.refresh(original.row)
    assert original.row.follow_up_tz == "America/New_York"


async def test_send_refuses_a_zone_postgres_does_not_know(
    db: AsyncSession, sender: FakeSender, enqueued: list[str], python_only_zone: str
) -> None:
    """The third writer of `follow_up_tz`: the Send with follow-up ticked."""
    from tests.outbound_send import ready_to_send

    ready = await ready_to_send(db)
    await db.commit()
    path = f"/loan-files/{ready.loan_file.display_id}/outbound/draft/{ready.draft.id}/send"
    status, body = await _api(
        db,
        ready.user,
        "POST",
        path,
        {
            "recipient": "borrower@example.test",
            "body": "Please send.",
            "transmit": True,
            "follow_up": {"tz": python_only_zone},
        },
    )
    assert status == 422, body
    await db.refresh(ready.draft)
    assert ready.draft.status is CommunicationStatus.DRAFT


async def test_a_zone_both_know_is_accepted(db: AsyncSession) -> None:
    original = await _original(db)
    status, body = await _api(
        db,
        original.ready.user,
        "PATCH",
        _path(original, "/follow-up"),
        {"tz": "America/Los_Angeles"},
    )
    assert status == 200, body
    assert body["tz"] == "America/Los_Angeles"


# --------------------------------------------------------------------------------------------- #
# The timeline row of a reminder
# --------------------------------------------------------------------------------------------- #
async def test_the_timeline_marks_an_automatic_reminder_with_its_senders_first_name(
    db: AsyncSession, sender: FakeSender, enqueued: list[str]
) -> None:
    original = await _original(db)
    await job.send_follow_ups(db, now=WED_2PM)
    [reminder] = await _reminders(db, original.row)
    clicker = await _user(db, original.ready.company, "Sam")
    await db.commit()
    original.row.sent_at = utcnow() - timedelta(days=1)  # rate limit: nothing recent
    reminder.send_requested_at = utcnow() - timedelta(days=1)
    await db.commit()
    status, _ = await _api(db, clicker, "POST", _path(original, "/follow-up/send-now"))
    assert status == 200
    entries, _ = await build_timeline(db, loan_file=original.ready.loan_file)
    by_id = {e.id: e for e in entries}
    automatic = by_id[reminder.id].detail
    assert automatic["automatic_reminder"] is True
    assert automatic["reminder_for"] == original.ready.user.first_name
    assert automatic["follow_up_of_id"] == str(original.row.id)
    [send_now] = [r for r in await _reminders(db, original.row) if r.id != reminder.id]
    clicked = by_id[send_now.id].detail
    assert clicked["automatic_reminder"] is False and clicked["reminder_for"] is None
    assert by_id[original.row.id].detail["automatic_reminder"] is False


# --------------------------------------------------------------------------------------------- #
# LP-1014 review fixes
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("method", "tail", "body"),
    [
        ("POST", "/follow-up/start", {"max_auto": 0}),
        ("PATCH", "/follow-up", {"max_auto": 0}),
    ],
)
async def test_zero_reminders_is_refused(
    db: AsyncSession, method: str, tail: str, body: dict[str, object]
) -> None:
    """Review finding 5: "follow up, with no reminders" read as No reply the moment it was sent."""
    original = await _original(db)
    status, _ = await _api(db, original.ready.user, method, _path(original, tail), body)
    assert status == 422
    with pytest.raises(ValueError):
        from app.services.email_send import FollowUp

        FollowUp(max_auto=0)


async def test_the_list_row_carries_the_emails_own_status(db: AsyncSession) -> None:
    """Review finding 7: a failed original cannot be started again, so the screen needs to know."""
    original = await _original(db)
    original.row.status = CommunicationStatus.FAILED
    original.row.follow_up_status = FollowUpStatus.STOPPED
    await db.commit()
    status, body = await _api(db, original.ready.user, "GET", _list_path(original))
    assert status == 200
    [row] = list(body)  # type: ignore[call-overload]
    assert row["email_status"] == "failed"


@contextmanager
def _statements(db: AsyncSession) -> Iterator[list[str]]:
    """Every SQL statement run on the test's connection while the block runs."""
    seen: list[str] = []
    engine = db.bind.engine.sync_engine  # type: ignore[union-attr]

    def record(_conn: object, _cursor: object, statement: str, *_: object) -> None:
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


async def test_the_list_costs_the_same_queries_for_one_row_or_four(db: AsyncSession) -> None:
    """Review finding 8: it asked for each row's needs and sender separately."""
    first = await _original(db, subject="One")
    with _statements(db) as seen:
        status, _ = await _api(db, first.ready.user, "GET", _list_path(first))
    one = len(seen)
    for n in range(3):
        await _original(db, subject=f"More {n}", ready=first.ready)
    with _statements(db) as seen:
        status, body = await _api(db, first.ready.user, "GET", _list_path(first))
    four = len(seen)
    assert status == 200 and len(list(body)) == 4  # type: ignore[call-overload]
    assert four == one, (one, four)


async def test_postgres_zone_names_are_read_once(db: AsyncSession) -> None:
    """Review finding 9: `pg_timezone_names` reads the whole tz database each time."""
    from app.api import communications as api

    original = await _original(db)
    api._POSTGRES_ZONES = None
    with _statements(db) as seen:
        for zone in ("America/Chicago", "America/Denver"):
            status, _ = await _api(
                db, original.ready.user, "PATCH", _path(original, "/follow-up"), {"tz": zone}
            )
            assert status == 200
    assert sum("pg_timezone_names" in s for s in seen) == 1
