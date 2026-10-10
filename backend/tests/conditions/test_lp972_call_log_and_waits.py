"""LP-972 — "Call or talk to someone" and "Wait for something".

A call is a RECORD in the condition's history, never a task, so it cannot make a condition ready. A wait
is a task that waits on someone by a date, with no email, and a reminder appears on that date (Eastern)
on the Reminders page while it is still open.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from app.models.condition import ConditionPrepStatus
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_item import ConditionItem
from app.models.condition_vocabulary import ConditionItemStatus, Performer, PlanOption
from app.models.reminder_snooze import ReminderKind
from app.schemas.condition import ConditionEventPublic
from app.services import condition_reading
from app.services.condition_plan import (
    CALL_NEEDS_WORDS,
    WAIT_NEEDS_A_DATE,
    WAIT_NEEDS_SOMEONE,
    PlanRefused,
    add_item,
    log_call,
)
from app.services.reminders import build_suggestions, snooze
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.test_condition_plan import _actor, _conditions, _planned_round_one

_ET = ZoneInfo("America/New_York")
DUE = date(2026, 10, 15)


@pytest.fixture(autouse=True)
def _mocked_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())


async def _file(db: AsyncSession) -> tuple[Any, dict[str, Any], Any]:
    loan_file, _ = await _planned_round_one(db)
    return loan_file, await _conditions(db, loan_file), await _actor(db, loan_file)


async def _wait(db: AsyncSession, condition: Any, actor: Any, **over: Any) -> ConditionItem:
    return await add_item(
        db,
        condition=condition,
        name=over.pop("name", "the payoff letter"),
        performers=over.pop("performers", [Performer.TITLE]),
        option=over.pop("option", None),
        actor_user_id=actor,
        waiting=True,
        due_date=over.pop("due_date", DUE),
    )


# --------------------------------------------------------------------------------------------- #
# Call or talk to someone
# --------------------------------------------------------------------------------------------- #


async def test_a_call_is_a_record_in_the_history_not_a_task(db_session: AsyncSession) -> None:
    _, conditions, actor = await _file(db_session)
    condition = conditions["1947"]
    items_before = await db_session.scalar(
        select(func.count()).where(ConditionItem.condition_id == condition.id)
    )
    prep_before = condition.prep_status

    event = await log_call(
        db_session,
        condition=condition,
        with_whom=Performer.TITLE,
        on=date(2026, 10, 9),
        agreed="  They will send the final CD   on Monday ",
        actor_user_id=actor,
    )

    assert event.kind is ConditionEventKind.CONDITION_CALL_LOGGED
    assert event.detail == {
        "with": "title",
        "on": "2026-10-09",
        "agreed": "They will send the final CD on Monday",
    }
    # NOT A TASK: nothing was added to the plan, and the condition did not move.
    assert (
        await db_session.scalar(
            select(func.count()).where(ConditionItem.condition_id == condition.id)
        )
        == items_before
    )
    assert condition.prep_status is prep_before is ConditionPrepStatus.TO_DO


async def test_a_call_needs_what_was_agreed(db_session: AsyncSession) -> None:
    _, conditions, actor = await _file(db_session)
    with pytest.raises(PlanRefused, match=CALL_NEEDS_WORDS):
        await log_call(
            db_session,
            condition=conditions["1947"],
            with_whom=Performer.TITLE,
            on=date(2026, 10, 9),
            agreed="   ",
            actor_user_id=actor,
        )


async def test_the_history_shows_the_call_and_only_on_its_own_kind(
    db_session: AsyncSession,
) -> None:
    _, conditions, actor = await _file(db_session)
    event = await log_call(
        db_session,
        condition=conditions["1947"],
        with_whom=Performer.LO,
        on=date(2026, 10, 9),
        agreed="He will re-disclose today",
        actor_user_id=actor,
    )
    shown = ConditionEventPublic.from_model(event)
    assert (shown.call_with, shown.call_on, shown.call_agreed) == (
        Performer.LO,
        date(2026, 10, 9),
        "He will re-disclose today",
    )
    # GUARDED BY KIND: the same keys on any other event do not travel.
    other = ConditionEvent(
        company_id=event.company_id,
        loan_file_id=event.loan_file_id,
        condition_id=event.condition_id,
        round_id=event.round_id,
        kind=ConditionEventKind.CONDITION_PLAN_CHANGED,
        detail={"with": "lo", "on": "2026-10-09", "agreed": "should not show"},
        occurred_at=datetime.now(UTC),
    )
    hidden = ConditionEventPublic.from_model(other)
    assert (hidden.call_with, hidden.call_on, hidden.call_agreed) == (None, None, None)


# --------------------------------------------------------------------------------------------- #
# Wait for something
# --------------------------------------------------------------------------------------------- #


async def test_a_wait_is_her_task_waiting_on_someone_with_no_email(
    db_session: AsyncSession,
) -> None:
    _, conditions, actor = await _file(db_session)
    item = await _wait(db_session, conditions["1947"], actor, option=PlanOption.ASK_THIRD_PARTY)
    # No email goes, even when an ask was asked for: she asked some other way.
    assert item.option is PlanOption.I_WILL_DO_IT and item.draft_id is None
    assert item.waiting and item.due_date == DUE
    assert item.performer is Performer.TITLE and item.status is ConditionItemStatus.OPEN
    events = list(
        await db_session.scalars(
            select(ConditionEvent.detail).where(
                ConditionEvent.condition_id == conditions["1947"].id,
                ConditionEvent.kind == ConditionEventKind.CONDITION_PLAN_CHANGED,
            )
        )
    )
    assert {"change": "item_added", "option": "i_will_do_it", "waiting": True} in events


async def test_a_wait_needs_a_date_and_someone_to_wait_on(db_session: AsyncSession) -> None:
    _, conditions, actor = await _file(db_session)
    with pytest.raises(PlanRefused, match=WAIT_NEEDS_A_DATE):
        await _wait(db_session, conditions["1947"], actor, due_date=None)
    with pytest.raises(PlanRefused, match=WAIT_NEEDS_SOMEONE):
        await _wait(db_session, conditions["1947"], actor, performers=[Performer.PROCESSOR])


# --------------------------------------------------------------------------------------------- #
# The reminder
# --------------------------------------------------------------------------------------------- #


def _at(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=_ET).astimezone(UTC)


async def _waits(db: AsyncSession, loan_file: Any, now: datetime) -> list[Any]:
    return [
        s
        for s in await build_suggestions(db, company_id=loan_file.company_id, now=now)
        if s.kind is ReminderKind.CONDITION_WAIT_DUE
    ]


async def test_the_reminder_comes_on_the_date_in_eastern_time(db_session: AsyncSession) -> None:
    loan_file, conditions, actor = await _file(db_session)
    item = await _wait(db_session, conditions["1947"], actor)

    # The evening before, in Eastern time — already the 15th in UTC — is still too early.
    assert await _waits(db_session, loan_file, _at(date(2026, 10, 14), 21)) == []
    due = await _waits(db_session, loan_file, _at(DUE, 9))
    assert [(s.subject_id, s.summary) for s in due] == [
        (item.id, "1947: still waiting on the payoff letter from Title/attorney")
    ]
    # Still there afterwards while it has not come.
    assert await _waits(db_session, loan_file, _at(date(2026, 10, 20), 9))


async def test_no_reminder_once_it_has_come_or_she_marked_it_done(
    db_session: AsyncSession,
) -> None:
    loan_file, conditions, actor = await _file(db_session)
    item = await _wait(db_session, conditions["1947"], actor)
    item.status = ConditionItemStatus.DONE
    await db_session.flush()
    assert await _waits(db_session, loan_file, _at(DUE, 9)) == []
    item.status = ConditionItemStatus.RECEIVED  # a document arrived and is being checked
    await db_session.flush()
    assert await _waits(db_session, loan_file, _at(DUE, 9)) == []


async def test_an_ordinary_task_with_a_date_raises_no_wait_reminder(
    db_session: AsyncSession,
) -> None:
    """THE CONTROL: asks carry due dates too (ASK_DUE_BUSINESS_DAYS). Only a wait is a wait."""
    loan_file, conditions, actor = await _file(db_session)
    ask = await add_item(
        db_session,
        condition=conditions["1947"],
        name="The final CD",
        performers=[Performer.TITLE],
        option=PlanOption.ASK_THIRD_PARTY,
        actor_user_id=actor,
    )
    assert ask.due_date is not None and not ask.waiting
    assert await _waits(db_session, loan_file, _at(date(2027, 1, 4), 9)) == []


async def test_a_snooze_is_about_this_date_and_a_new_date_brings_it_back(
    db_session: AsyncSession,
) -> None:
    loan_file, conditions, actor = await _file(db_session)
    item = await _wait(db_session, conditions["1947"], actor)
    now = _at(DUE, 9)
    decided = await snooze(
        db_session,
        loan_file=loan_file,
        kind=ReminderKind.CONDITION_WAIT_DUE,
        subject_id=item.id,
        until=None,
    )
    # She dismisses it when she SEES it, on the date; the test clock is ahead of the real one, so the
    # decision is dated where she would have made it (`_is_suppressed` compares it with `since`).
    decided.created_at = now
    await db_session.flush()
    assert await _waits(db_session, loan_file, now) == []
    item.due_date = date(2026, 10, 22)
    await db_session.flush()
    assert await _waits(db_session, loan_file, _at(date(2026, 10, 22), 9))


# --------------------------------------------------------------------------------------------- #
# The doors
# --------------------------------------------------------------------------------------------- #


@pytest.fixture
def _no_db_override() -> Any:
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


async def test_the_routes_log_a_call_and_add_a_wait(
    db_session: AsyncSession, _no_db_override: Any
) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, conditions, _ = await _file(db_session)
    condition = conditions["1947"]
    client, _, processor = await _clients(db_session, loan_file)
    base = f"/api/v1/conditions/{condition.id}"
    async with client:
        called = await client.post(
            f"{base}/calls",
            json={"with_whom": "title", "on": "2026-10-09", "agreed": "CD on Monday"},
            headers=processor,
        )
        herself = await client.post(
            f"{base}/calls",
            json={"with_whom": "processor", "on": "2026-10-09", "agreed": "x"},
            headers=processor,
        )
        waited = await client.post(
            f"{base}/items",
            json={
                "name": "the payoff letter",
                "performers": ["title"],
                "waiting": True,
                "due_date": "2026-10-15",
            },
            headers=processor,
        )
        no_date = await client.post(
            f"{base}/items",
            json={"name": "the payoff letter", "performers": ["title"], "waiting": True},
            headers=processor,
        )
    assert called.status_code == 200
    assert herself.status_code == 409
    assert waited.status_code == 200
    wait = next(i for i in waited.json()["items"] if i["name"] == "the payoff letter")
    assert (wait["waiting"], wait["due_date"], wait["option"]) == (
        True,
        "2026-10-15",
        "i_will_do_it",
    )
    assert no_date.status_code == 409
    logged = await db_session.scalar(
        select(func.count()).where(
            ConditionEvent.condition_id == condition.id,
            ConditionEvent.kind == ConditionEventKind.CONDITION_CALL_LOGGED,
        )
    )
    assert logged == 1


def test_the_screens_reminder_kinds_are_exactly_the_servers() -> None:
    """`ReminderKind` IS NOT IN `test_condition_type_mirror._MIRRORED`, and LP-972 adds a member. The
    Reminders page keys its icon on the kind (`suggestion-cards.tsx`), so a kind the server sends and the
    screen's union lacks renders with no icon and compiles, because the payload is not typed at runtime."""
    import re
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "frontend" / "lib" / "types" / "reminder.ts"
    assert path.is_file(), path
    match = re.search(r"export type ReminderKind =(.*?);", path.read_text(), re.S)
    assert match is not None, "ReminderKind is where this test reads it"
    kinds = set(re.findall(r'"([a-z_]+)"', match.group(1)))
    assert kinds, "parsed something"
    assert kinds == {kind.value for kind in ReminderKind}
