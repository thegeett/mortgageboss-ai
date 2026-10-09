"""LP-973 — Read again for conditions the AI did not read.

When the model call fails (the owner's case: an expired AWS login), `read_round` still reads every
condition, from the library alone, and records the round as read. Nothing is unread, so LP-952's Read
again had nothing to offer and the plan stayed a guess. Round 1 of the fictional UWM sheet, on a file
with no lender (LP-949's fixture).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.ai.client import AIClientError
from app.models.condition import ConditionReadingSource, ConditionReadingStatus
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_item import ConditionItem
from app.models.condition_vocabulary import ConditionItemStatus, PlanOption
from app.services import condition_reading
from app.services.condition_plan import build_plan, update_item
from app.services.condition_reading import read_round
from app.services.condition_reading_state import (
    DONE,
    WITHOUT_AI,
    clear_for_reading,
    read_without_ai,
    reading_state,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.test_condition_plan import _actor
from tests.conditions.test_lp949_lender_on_the_file import _by_code, _file_without_lender


async def _no_ai(*_: Any, **__: Any) -> Any:
    raise AIClientError("the AWS login expired")


@pytest.fixture(autouse=True)
def _drop_db_override() -> Any:
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from app.api import conditions as conditions_api

    calls: list[str] = []

    def _send(round_id: Any) -> bool:
        calls.append(str(round_id))
        return True

    monkeypatch.setattr(conditions_api, "_enqueue_reading", _send)
    return calls


async def _read_without_the_ai(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, Any, dict[str, Any]]:
    loan_file, round_ = await _file_without_lender(db)
    monkeypatch.setattr(condition_reading, "complete", _no_ai)
    outcome = await read_round(db, round_id=round_.id)
    assert outcome.fell_back  # THE PREMISE: the model call failed and the library read them
    await build_plan(db, round_id=round_.id)
    return loan_file, round_, await _by_code(db, loan_file)


async def _live_items(db: AsyncSession, condition: Any) -> list[ConditionItem]:
    return list(
        await db.scalars(
            select(ConditionItem).where(
                ConditionItem.condition_id == condition.id, ConditionItem.deleted_at.is_(None)
            )
        )
    )


async def test_a_failed_ai_reading_is_offered_again(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, round_, conditions = await _read_without_the_ai(db_session, monkeypatch)
    assert all(c.reading_source is ConditionReadingSource.LIBRARY for c in conditions.values())
    state = await reading_state(db_session, round_=round_)
    # Nothing is unread — the reason LP-952's Read again offered nothing — but every one is offered.
    assert state["unread"] == 0
    assert (state["state"], state["without_ai"]) == (WITHOUT_AI, len(conditions))


async def test_an_ai_reading_is_not_offered(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE CONTROL: read with the AI, even below the bar, is not "without the AI"."""
    _, round_ = await _file_without_lender(db_session)
    monkeypatch.setattr(condition_reading, "complete", fake_complete())
    await read_round(db_session, round_id=round_.id)
    state = await reading_state(db_session, round_=round_)
    assert (state["state"], state["without_ai"]) == (DONE, 0)


async def test_what_she_worked_on_is_never_read_again(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    loan_file, _, conditions = await _read_without_the_ai(db_session, monkeypatch)
    actor = await _actor(db_session, loan_file)
    with_items = [c for c in conditions.values() if await _live_items(db_session, c)]
    assert len(with_items) >= 2, "the fallback gives a condition with an owner hint a generic task"
    marked, rerouted = with_items[0], with_items[1]
    confirmed = next(c for c in conditions.values() if c not in with_items)
    # Her change of step leaves the task OPEN and from the reading: only the plan-change record
    # says she worked on it.
    (task,) = (await _live_items(db_session, rerouted))[:1]
    await update_item(
        db_session,
        condition=rerouted,
        item=task,
        option=PlanOption.I_WILL_DO_IT
        if task.option is not PlanOption.I_WILL_DO_IT
        else PlanOption.ASK_THIRD_PARTY,
        name=None,
        performers=None,
        due_date=None,
        actor_user_id=actor,
    )
    assert task.status is ConditionItemStatus.OPEN
    (item,) = (await _live_items(db_session, marked))[:1]
    await update_item(
        db_session,
        condition=marked,
        item=item,
        option=None,
        name=None,
        performers=None,
        due_date=None,
        actor_user_id=actor,
        status=ConditionItemStatus.NOT_NEEDED,
        note="Title already sent it",
    )
    confirmed.reading_status = ConditionReadingStatus.CONFIRMED
    await db_session.flush()

    offered = {c.id for c in await read_without_ai(db_session, loan_file_id=loan_file.id)}
    assert not {marked.id, confirmed.id, rerouted.id} & offered
    assert len(offered) == len(conditions) - 3


async def test_read_again_clears_them_for_the_ai_and_keeps_her_work(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, queued: list[str]
) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, round_, conditions = await _read_without_the_ai(db_session, monkeypatch)
    kept = next(c for c in conditions.values() if c.reading is not None)
    kept.reading_status = ConditionReadingStatus.CONFIRMED
    await db_session.flush()

    client, _, processor = await _clients(db_session, loan_file)
    async with client:
        again = await client.post(f"/api/v1/condition-rounds/{round_.id}/read", headers=processor)
        assert again.status_code == 200
    assert queued == [str(round_.id)]

    for condition in conditions.values():
        await db_session.refresh(condition)
        if condition.id == kept.id:
            assert condition.reading_status is ConditionReadingStatus.CONFIRMED
            assert condition.reading is not None
            continue
        assert condition.reading_status is ConditionReadingStatus.UNREAD
        assert condition.reading is None and condition.next_step is None
        assert await _live_items(db_session, condition) == []
    events = list(
        await db_session.scalars(
            select(ConditionEvent).where(
                ConditionEvent.loan_file_id == loan_file.id,
                ConditionEvent.kind == ConditionEventKind.CONDITION_PLAN_CHANGED,
            )
        )
    )
    assert len([e for e in events if e.detail.get("change") == "read_again"]) == len(conditions) - 1


async def test_after_clearing_the_ai_reads_and_plans_them(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the queued task then does (`_run_read`): read the unread, plan the unplanned."""
    loan_file, round_, conditions = await _read_without_the_ai(db_session, monkeypatch)
    actor = await _actor(db_session, loan_file)
    await clear_for_reading(
        db_session,
        conditions=await read_without_ai(db_session, loan_file_id=loan_file.id),
        actor_user_id=actor,
    )
    monkeypatch.setattr(condition_reading, "complete", fake_complete())
    outcome = await read_round(db_session, round_id=round_.id)
    assert outcome.read == len(conditions) and not outcome.fell_back
    await build_plan(db_session, round_id=round_.id)

    assert all(c.reading_source is ConditionReadingSource.AI for c in conditions.values())
    assert (await reading_state(db_session, round_=round_))["without_ai"] == 0
    planned = [c for c in conditions.values() if await _live_items(db_session, c) or c.next_step]
    assert planned  # the AI's plan, not the guess


async def test_another_failure_can_be_read_again_again(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Read again that fails too leaves them offered: its own `read_again` event is not her work."""
    loan_file, round_, conditions = await _read_without_the_ai(db_session, monkeypatch)
    actor = await _actor(db_session, loan_file)
    await clear_for_reading(
        db_session,
        conditions=await read_without_ai(db_session, loan_file_id=loan_file.id),
        actor_user_id=actor,
    )
    await read_round(db_session, round_id=round_.id)  # the AI still fails
    await build_plan(db_session, round_id=round_.id)
    assert len(await read_without_ai(db_session, loan_file_id=loan_file.id)) == len(conditions)


async def test_an_asked_task_keeps_its_condition_out(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A task whose email went out is REQUESTED with no plan change of hers (`mark_sent` moves the
    status, not the plan): only the every-task-OPEN rule keeps that condition from being cleared."""
    loan_file, _, conditions = await _read_without_the_ai(db_session, monkeypatch)
    asked = None
    for condition in conditions.values():
        if await _live_items(db_session, condition):
            asked = condition
            break
    assert asked is not None
    (task,) = (await _live_items(db_session, asked))[:1]
    task.status = ConditionItemStatus.REQUESTED
    await db_session.flush()
    offered = {c.id for c in await read_without_ai(db_session, loan_file_id=loan_file.id)}
    assert asked.id not in offered
    assert len(offered) == len(conditions) - 1
