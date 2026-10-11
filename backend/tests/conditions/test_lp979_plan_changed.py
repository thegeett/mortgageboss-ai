"""LP-979 — "Changed by you · Go back to the suggested plan", shown only when she has changed the plan.

From the history: a `condition_plan_changed` of hers after the condition's latest reset ("Go back to the
suggested plan", or Read again replacing the plan).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_vocabulary import ConditionItemStatus
from app.services import condition_reading
from app.services.condition_plan import plans_changed_for_file, revert_to_suggested, update_item
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.test_condition_plan import _actor, _conditions, _items, _planned_round_one


@pytest.fixture(autouse=True)
def _mocked_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())


async def _drop_first_task(db: AsyncSession, condition: Any, actor: Any) -> None:
    item = (await _items(db, condition))[0]
    await update_item(
        db,
        condition=condition,
        item=item,
        option=None,
        name=None,
        performers=None,
        due_date=None,
        actor_user_id=actor,
        status=ConditionItemStatus.NOT_NEEDED,
        note="Title sent it already",
    )


async def test_a_plan_as_suggested_is_not_changed(db_session: AsyncSession) -> None:
    loan_file, _ = await _planned_round_one(db_session)
    assert await plans_changed_for_file(db_session, loan_file_id=loan_file.id) == set()


async def test_her_change_marks_that_condition_only(db_session: AsyncSession) -> None:
    loan_file, _ = await _planned_round_one(db_session)
    conditions = await _conditions(db_session, loan_file)
    actor = await _actor(db_session, loan_file)
    await _drop_first_task(db_session, conditions["1947"], actor)
    assert await plans_changed_for_file(db_session, loan_file_id=loan_file.id) == {
        conditions["1947"].id
    }


async def test_going_back_clears_it_and_a_later_change_sets_it_again(
    db_session: AsyncSession,
) -> None:
    loan_file, _ = await _planned_round_one(db_session)
    condition = (await _conditions(db_session, loan_file))["1947"]
    actor = await _actor(db_session, loan_file)
    await _drop_first_task(db_session, condition, actor)
    await revert_to_suggested(db_session, condition=condition, actor_user_id=actor)
    assert await plans_changed_for_file(db_session, loan_file_id=loan_file.id) == set()
    await _drop_first_task(db_session, condition, actor)
    assert await plans_changed_for_file(db_session, loan_file_id=loan_file.id) == {condition.id}


async def test_read_again_is_a_fresh_plan_not_her_change(db_session: AsyncSession) -> None:
    """LP-973's Read again writes `read_again`: the plan is replaced, so nothing of hers departs from it."""
    loan_file, _ = await _planned_round_one(db_session)
    condition = (await _conditions(db_session, loan_file))["1947"]
    actor = await _actor(db_session, loan_file)
    await _drop_first_task(db_session, condition, actor)
    db_session.add(
        ConditionEvent(
            company_id=condition.company_id,
            loan_file_id=condition.loan_file_id,
            condition_id=condition.id,
            round_id=condition.last_seen_round_id,
            kind=ConditionEventKind.CONDITION_PLAN_CHANGED,
            actor_user_id=actor,
            detail={"change": "read_again", "items_removed": 1},
        )
    )
    await db_session.flush()
    assert await plans_changed_for_file(db_session, loan_file_id=loan_file.id) == set()


@pytest.fixture
def _no_db_override() -> Any:
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


async def test_the_list_carries_it(db_session: AsyncSession, _no_db_override: Any) -> None:
    """The plan panel reads the conditions list, so the flag must reach that door."""
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, _ = await _planned_round_one(db_session)
    conditions = await _conditions(db_session, loan_file)
    actor = await _actor(db_session, loan_file)
    await _drop_first_task(db_session, conditions["1947"], actor)
    client, _, processor = await _clients(db_session, loan_file)
    async with client:
        got = await client.get(f"/api/v1/loan-files/{loan_file.id}/conditions", headers=processor)
    assert got.status_code == 200, got.text
    flags = {row["lender_code"]: row["plan_changed"] for row in got.json()}
    assert flags["1947"] is True
    assert flags["0006"] is False
