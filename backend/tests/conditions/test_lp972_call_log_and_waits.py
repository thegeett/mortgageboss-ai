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


async def test_a_wait_is_not_one_of_her_tasks_in_any_count(db_session: AsyncSession) -> None:
    """LP-972 REVIEW — the wait's option is `i_will_do_it`, and two counters read that as "hers to do".

    The ticket's own reasoning is that a wait is "not a task now" — which is why first moves name who
    is waited on instead. The same reading was left in the two places that COUNT her tasks:

    - `conditions.has_open_step((I_WILL_DO_IT,))`, which is the dashboard's "Your tasks N" and, by its
      own docstring, the filter behind its click: "ONE PREDICATE FOR THE FILTER AND THE COUNT".
    - `condition_plan.round_plan_summary`'s `your_tasks` pill on the plan panel.

    Measured before the fix: 7086 carries only borrower asks, so it is in neither count; adding one
    wait on the title company took the file's `your_tasks` from 2 to 3 and the panel's from 2 to 3. She
    is told she has a third thing to do, and the thing is "wait for the title company".
    """
    from app.models.condition_round import ConditionRound
    from app.services.condition_plan import round_plan_summary
    from app.services.conditions import condition_summary

    loan_file, conditions, actor = await _file(db_session)
    round_ = await db_session.scalar(
        select(ConditionRound).where(ConditionRound.loan_file_id == loan_file.id)
    )
    assert round_ is not None
    before_file = (await condition_summary(db_session, loan_file_id=loan_file.id)).your_tasks
    before_panel = (await round_plan_summary(db_session, round_=round_)).your_tasks

    waited_on = conditions["7086"]
    assert all(
        item.option is PlanOption.ASK_BORROWER for item in await _live_items(db_session, waited_on)
    ), "the premise: this condition carries no task of hers, so a change in the counts is the wait"
    await _wait(db_session, waited_on, actor, performers=[Performer.TITLE])
    await db_session.flush()

    assert (
        await condition_summary(db_session, loan_file_id=loan_file.id)
    ).your_tasks == before_file
    assert (await round_plan_summary(db_session, round_=round_)).your_tasks == before_panel

    # THE POSITIVE CONTROL: a real task of hers on the same condition does count, in both.
    await add_item(
        db_session,
        condition=waited_on,
        name="Call the LO about the fee",
        performers=[Performer.PROCESSOR],
        option=PlanOption.I_WILL_DO_IT,
        actor_user_id=actor,
    )
    await db_session.flush()
    assert (
        await condition_summary(db_session, loan_file_id=loan_file.id)
    ).your_tasks == before_file + 1
    assert (await round_plan_summary(db_session, round_=round_)).your_tasks == before_panel + 1


async def _live_items(db: AsyncSession, condition: Any) -> list[ConditionItem]:
    return list(
        await db.scalars(
            select(ConditionItem).where(
                ConditionItem.condition_id == condition.id, ConditionItem.deleted_at.is_(None)
            )
        )
    )


async def test_a_wait_that_becomes_an_ask_stops_being_a_wait(db_session: AsyncSession) -> None:
    """LP-972 REVIEW — `waiting` only means anything on an `i_will_do_it` item.

    `ItemLinkActions` offers "Ask someone" on every `i_will_do_it` item, and a wait is one, so a single
    click moved a wait to `ask_borrower` while the flag stayed set: an item in a draft AND carrying a
    wait reminder, which is neither of the two things it could be. The invariant is on the server
    rather than in the menu, because deciding to email after all is a real thing to do and the API can
    reach it either way.
    """
    from app.services.condition_plan import update_item
    from app.services.reminders import build_suggestions

    loan_file, conditions, actor = await _file(db_session)
    condition = conditions["1947"]
    item = await _wait(db_session, condition, actor, performers=[Performer.TITLE])
    await db_session.flush()
    assert item.waiting is True
    assert item.option is PlanOption.I_WILL_DO_IT

    await update_item(
        db_session,
        condition=condition,
        item=item,
        option=PlanOption.ASK_THIRD_PARTY,
        name=None,
        performers=None,
        due_date=None,
        actor_user_id=actor,
    )
    await db_session.flush()

    assert item.option is PlanOption.ASK_THIRD_PARTY
    assert item.waiting is False, (
        "the wait is over: it is an ask now, and the ask is what is drafted"
    )
    # AND ITS REMINDER IS GONE WITH IT, which is the harm the stale flag would have left behind.
    on_the_day = datetime(2026, 10, 15, 9, 0, tzinfo=_ET)
    kinds = [
        s.kind
        for s in await build_suggestions(
            db_session, company_id=loan_file.company_id, now=on_the_day
        )
    ]
    assert ReminderKind.CONDITION_WAIT_DUE not in kinds


async def test_a_wait_on_an_information_line_raises_no_reminder(db_session: AsyncSession) -> None:
    """LP-972 REVIEW — the builder's third question: two spellings of "an open condition".

    `conditions.is_open` is `not info_only and lender_status in OPEN_LENDER_STATUSES`, and its own
    docstring says why it is one function: "a dozen `count(*)` queries would each be a chance to
    disagree with the row about what open means". The reminder's SQL spelled the second half and
    dropped the first, so a wait on an INFORMATION LINE — a row that asks for nothing — would nudge
    her on its date while every count on the screen says that condition is not open.
    """
    from app.services.reminders import build_suggestions

    loan_file, conditions, actor = await _file(db_session)
    condition = conditions["1947"]
    condition.info_only = True
    await db_session.flush()
    await _wait(db_session, condition, actor, performers=[Performer.TITLE])
    await db_session.flush()

    on_the_day = datetime(2026, 10, 15, 9, 0, tzinfo=_ET)
    kinds = [
        s.kind
        for s in await build_suggestions(
            db_session, company_id=loan_file.company_id, now=on_the_day
        )
    ]
    assert ReminderKind.CONDITION_WAIT_DUE not in kinds

    # THE POSITIVE CONTROL: the same wait on the same condition, once it asks for something again.
    condition.info_only = False
    await db_session.flush()
    kinds = [
        s.kind
        for s in await build_suggestions(
            db_session, company_id=loan_file.company_id, now=on_the_day
        )
    ]
    assert ReminderKind.CONDITION_WAIT_DUE in kinds


def _migration() -> Any:
    """The LP-972 migration module, loaded from its file (the LP-975 test's own trick)."""
    import importlib.util
    from pathlib import Path

    path = next((Path(__file__).parents[2] / "alembic" / "versions").glob("*_169e48fff378_*.py"))
    spec = importlib.util.spec_from_file_location("lp972_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeOp:
    """Enough of alembic's `op` to run `downgrade()` and see what it would do."""

    def __init__(self, logged: int) -> None:
        self.logged = logged
        self.statements: list[str] = []
        self.dropped: list[tuple[str, str]] = []

    def get_bind(self) -> Any:
        return self

    def execute(self, sql: Any) -> Any:
        text = str(getattr(sql, "text", sql))
        self.statements.append(text)
        return self

    def scalar(self) -> int:
        return self.logged

    def drop_column(self, table: str, column: str) -> None:
        self.dropped.append((table, column))


def test_a_rollback_refuses_to_delete_her_logged_calls() -> None:
    """LP-972 REVIEW — the builder's fifth question, and my answer is that it should refuse.

    Narrowing `condition_events.kind` means no row may hold the new value, so the rows must go first.
    But a `condition_call_logged` event is the record of a conversation — who, when, and up to 300
    characters of her own words about what was agreed — and nothing else holds it. A schema rollback
    deleting that quietly is the kind of data loss nobody discovers until they look for the call.

    So the downgrade counts them and refuses, naming the SQL that accepts the loss. A database where
    no call has been logged — which is most rollbacks, since they follow a deploy — still rolls back
    on its own. The SNOOZES still go: a snooze is derived state about a date, and its reminder returns.
    """
    module = _migration()

    with_calls = _FakeOp(logged=2)
    module.op = with_calls
    with pytest.raises(RuntimeError) as refused:
        module.downgrade()
    assert "2 logged call(s)" in str(refused.value)
    assert "DELETE FROM condition_events WHERE kind = 'condition_call_logged'" in str(refused.value)
    assert with_calls.dropped == [], "and nothing was changed before it refused"
    assert not any("DELETE FROM reminder_snoozes" in s for s in with_calls.statements)

    # THE CONTROL: with no call logged, the rollback runs — and deletes the snoozes, not the events.
    clean = _FakeOp(logged=0)
    module.op = clean
    module.downgrade()
    assert clean.dropped == [("condition_items", "waiting")]
    assert any("DELETE FROM reminder_snoozes" in s for s in clean.statements)
    assert not any("DELETE FROM condition_events" in s for s in clean.statements)


async def test_read_again_leaves_a_logged_call_alone(db_session: AsyncSession) -> None:
    """LP-972 REVIEW — the builder's first question: should a call make a condition "worked"?

    LP-973's `read_without_ai` offers a condition for re-reading only while it is exactly what the
    no-AI fallback left — no task of hers, no plan change of hers, no document she unlinked — because
    its rule is that NOTHING OF HERS IS LOST. A call is none of those, so a condition she has talked
    about is still offered. Measured here, and the answer to the question is that this is right rather
    than an omission: `clear_for_reading` replaces the reading, the items and the step, and it does
    not touch events — so the call survives the re-read with its day and her words, which is what a
    record in the history is for. If a call made a condition ineligible, one phone call would take
    "Read again" away from a condition whose reading has no type and one generic task.
    """
    from app.models.condition import ConditionReadingSource, ConditionReadingStatus
    from app.services.condition_reading_state import clear_for_reading, read_without_ai

    loan_file, conditions, actor = await _file(db_session)
    condition = conditions["1947"]
    # The state the fallback leaves: read from the library alone, still needing her.
    condition.reading_source = ConditionReadingSource.LIBRARY
    condition.reading_status = ConditionReadingStatus.NEEDS_CONFIRMATION
    for item in await _live_items(db_session, condition):
        item.deleted_at = datetime.now(UTC)
    await db_session.flush()
    offered = await read_without_ai(db_session, loan_file_id=loan_file.id)
    assert condition.id in {c.id for c in offered}, "the premise: it is offered before the call"

    await log_call(
        db_session,
        condition=condition,
        with_whom=Performer.TITLE,
        on=date(2026, 10, 9),
        agreed="He will send the payoff letter next week.",
        actor_user_id=actor,
    )
    await db_session.flush()

    offered = await read_without_ai(db_session, loan_file_id=loan_file.id)
    assert condition.id in {c.id for c in offered}, (
        "a call is not work that a re-read would destroy"
    )

    # AND THE CALL IS STILL THERE AFTERWARDS, which is why that is safe.
    await clear_for_reading(db_session, conditions=[condition], actor_user_id=actor)
    await db_session.flush()
    calls = await db_session.scalar(
        select(func.count())
        .select_from(ConditionEvent)
        .where(
            ConditionEvent.condition_id == condition.id,
            ConditionEvent.kind == ConditionEventKind.CONDITION_CALL_LOGGED,
        )
    )
    assert calls == 1
