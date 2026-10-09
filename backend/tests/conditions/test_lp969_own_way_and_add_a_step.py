"""LP-969 — "I'll handle it my own way", and the steps she adds.

The owner, 2026-10-08: "we have to provide a free way to processor, because what if it require upload
thing, write draft, or something else." Round 1 of the fictional UWM file, planned and drafted as in
LP-968's tests.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_item import ConditionItem
from app.models.condition_vocabulary import ConditionItemStatus, Performer, PlanOption
from app.services import condition_reading
from app.services.condition_drafts import draft_ready_plan
from app.services.condition_plan import (
    OWN_WAY_NOTE,
    add_item,
    handle_own_way,
    remove_item,
    revert_to_suggested,
    set_next_step,
    update_item,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.test_condition_plan import _actor, _conditions, _planned_round_one


@pytest.fixture(autouse=True)
def _mocked_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())


async def _drafted(db: AsyncSession) -> tuple[dict[str, Any], Any]:
    loan_file, round_ = await _planned_round_one(db)
    await draft_ready_plan(db, round_id=round_.id)
    return await _conditions(db, loan_file), await _actor(db, loan_file)


async def _live(db: AsyncSession, condition: Any) -> list[ConditionItem]:
    return list(
        await db.scalars(
            select(ConditionItem)
            .where(ConditionItem.condition_id == condition.id, ConditionItem.deleted_at.is_(None))
            .order_by(ConditionItem.sequence)
        )
    )


async def _events(db: AsyncSession, condition: Any) -> list[dict[str, Any]]:
    return [
        event.detail
        for event in await db.scalars(
            select(ConditionEvent)
            .where(
                ConditionEvent.condition_id == condition.id,
                ConditionEvent.kind == ConditionEventKind.CONDITION_PLAN_CHANGED,
            )
            .order_by(ConditionEvent.occurred_at, ConditionEvent.id)
        )
    ]


# --------------------------------------------------------------------------------------------- #
# My own way
# --------------------------------------------------------------------------------------------- #


async def test_my_own_way_clears_the_path_and_takes_the_asks_out_of_the_emails(
    db_session: AsyncSession,
) -> None:
    conditions, actor = await _drafted(db_session)
    condition = conditions["1947"]
    before = await _live(db_session, condition)
    assert any(item.draft_id is not None for item in before)  # THE CONTROL: it was in an email

    dropped = await handle_own_way(db_session, condition=condition, actor_user_id=actor)

    after = await _live(db_session, condition)
    assert dropped == len(before) > 0
    assert all(item.status is ConditionItemStatus.NOT_NEEDED for item in after)
    assert all(item.plan_note == OWN_WAY_NOTE for item in after)
    assert all(item.draft_id is None for item in after)
    assert condition.next_step is None
    # Recorded in the history, once, with the count.
    assert {"change": "own_way", "count": dropped} in await _events(db_session, condition)


async def test_my_own_way_clears_the_conditions_own_step_too(db_session: AsyncSession) -> None:
    conditions, actor = await _drafted(db_session)
    condition = conditions["6637"]
    await set_next_step(
        db_session, condition=condition, next_step=PlanOption.ASK_UNDERWRITER, actor_user_id=actor
    )
    await handle_own_way(db_session, condition=condition, actor_user_id=actor)
    assert condition.next_step is None


async def test_going_back_undoes_my_own_way_exactly(db_session: AsyncSession) -> None:
    """Nothing is deleted: each drop is an ordinary not-needed edit, so the replay finds its `from`."""
    conditions, actor = await _drafted(db_session)
    condition = conditions["6637"]
    suggested = [(i.key, i.option, i.status) for i in await _live(db_session, condition)]
    step = condition.next_step

    await handle_own_way(db_session, condition=condition, actor_user_id=actor)
    await revert_to_suggested(db_session, condition=condition, actor_user_id=actor)

    assert [(i.key, i.option, i.status) for i in await _live(db_session, condition)] == suggested
    assert condition.next_step is step
    assert all(i.plan_note is None for i in await _live(db_session, condition))
    # Back in the emails it came out of.
    asks = [i for i in await _live(db_session, condition) if i.option is PlanOption.ASK_THIRD_PARTY]
    assert all(i.draft_id is not None for i in asks)


async def test_my_own_way_leaves_an_ask_that_went_out(db_session: AsyncSession) -> None:
    conditions, actor = await _drafted(db_session)
    condition = conditions["7086"]
    items = await _live(db_session, condition)
    sent = items[0]
    sent.status = ConditionItemStatus.REQUESTED
    await db_session.flush()

    dropped = await handle_own_way(db_session, condition=condition, actor_user_id=actor)

    assert sent.status is ConditionItemStatus.REQUESTED and sent.plan_note is None
    assert dropped == len(items) - 1


async def test_my_own_way_drops_every_split_part(db_session: AsyncSession) -> None:
    """LP-946 — an edit to a parent re-makes its OPEN parts. Dropping the parent first would leave
    fresh OPEN parts in their drafts; the parts go first, and a part not OPEN is kept by the re-split."""
    conditions, actor = await _drafted(db_session)
    split = conditions["1947"]
    ask = (await _live(db_session, split))[0]
    # Two outside people on one ask: LP-946 gives the second its own part, in its own draft.
    await update_item(
        db_session,
        condition=split,
        item=ask,
        option=None,
        name=None,
        performers=[Performer.TITLE, Performer.INSURANCE],
        due_date=None,
        actor_user_id=actor,
    )
    parts = [i for i in await _live(db_session, split) if i.part_of_item_id == ask.id]
    assert parts and all(p.draft_id is not None for p in parts)  # THE CONTROL: a live part

    await handle_own_way(db_session, condition=split, actor_user_id=actor)

    live = await _live(db_session, split)
    assert any(i.part_of_item_id is not None for i in live)
    assert [i.key for i in live if i.status is ConditionItemStatus.OPEN] == []

    # GOING BACK RESTORES THE PARTS TOO. The LP-968 review's limit — a revert finds no part, because
    # it matches the LIVE key and LP-946 gives a part `<base>.<performer>` — is about an edit recorded
    # against the BASE key. Own way edits each part itself, so each part's event carries the part's own
    # key, and the replay finds it.
    await revert_to_suggested(db_session, condition=split, actor_user_id=actor)
    back = await _live(db_session, split)
    assert any(i.part_of_item_id is not None for i in back)
    assert all(i.status is ConditionItemStatus.OPEN and i.draft_id is not None for i in back)


# --------------------------------------------------------------------------------------------- #
# Add a step
# --------------------------------------------------------------------------------------------- #


async def test_an_email_step_she_adds_joins_that_persons_draft(db_session: AsyncSession) -> None:
    """What "we still send the emails for every step you add" leans on."""
    conditions, actor = await _drafted(db_session)
    condition = conditions["1947"]
    await handle_own_way(db_session, condition=condition, actor_user_id=actor)

    added = await add_item(
        db_session,
        condition=condition,
        name="Send the final seller CD with the closing package",
        performers=[Performer.TITLE],
        option=PlanOption.ASK_THIRD_PARTY,
        actor_user_id=actor,
    )
    assert added.draft_id is not None
    assert {"change": "item_added", "option": "ask_third_party"} in await _events(
        db_session, condition
    )


async def test_a_to_do_she_adds_is_her_task_and_can_be_removed(db_session: AsyncSession) -> None:
    conditions, actor = await _drafted(db_session)
    condition = conditions["1947"]
    added = await add_item(
        db_session,
        condition=condition,
        name="Call the title company about the CD",
        performers=[Performer.PROCESSOR],
        option=None,
        actor_user_id=actor,
    )
    assert added.option is PlanOption.I_WILL_DO_IT and added.draft_id is None

    await remove_item(db_session, condition=condition, item=added, actor_user_id=actor)
    assert added.deleted_at is not None
    assert {"change": "item_removed", "item_key": added.key} in await _events(db_session, condition)
