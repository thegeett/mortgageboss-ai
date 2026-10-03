"""LP-955 — "I'll do it" actions (item 8 of the 2026-09-30 staging trial).

- Upload is LP-953's "Upload here", on every item.
- "Ask someone for it" turns her task into an ask in that person's draft: the item's step and who acts,
  through `update_item`, which re-syncs the drafts.
- IV-01 (credit report invoice) at UWM offers two routes: "Pulled in UWM's system" asks the underwriter to
  clear it, in the type's own words; "Our vendor" keeps it her task.

The file: the UWM round-1 sheet on a UWM file, read, planned and confirmed (0006 is IV-01).
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from app.models.communication import Communication
from app.models.condition import Condition
from app.models.condition_draft import ConditionDraft, DraftRecipient
from app.models.condition_item import ConditionItem
from app.models.condition_vocabulary import Performer, PlanOption
from app.models.loan_file import LoanFile
from app.services import condition_reading
from app.services.condition_lender import set_file_lender
from app.services.condition_plan import (
    PlanRefused,
    build_plan,
    choose_route,
    confirm_round_plan,
    round_plan_blockers,
    update_item,
)
from app.services.condition_reading import ConfirmedItem, confirm_reading, read_round
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.test_condition_plan import _actor
from tests.conditions.test_lp949_lender_on_the_file import _by_code, _file_without_lender


@pytest.fixture(autouse=True)
def _model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())


@pytest.fixture(autouse=True)
def _drop_db_override() -> Any:
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


async def _confirmed(db: AsyncSession) -> tuple[LoanFile, dict[str, Condition], Any]:
    loan_file, round_ = await _file_without_lender(db)
    await set_file_lender(
        db, loan_file=loan_file, lender_key="uwm", lender_id=None, actor_user_id=None
    )
    await read_round(db, round_id=round_.id)
    await build_plan(db, round_id=round_.id)
    actor = await _actor(db, loan_file)
    conditions = await _by_code(db, loan_file)
    for code in await round_plan_blockers(db, round_=round_):
        condition = conditions[code]
        await confirm_reading(
            db,
            condition=condition,
            items=[
                ConfirmedItem(
                    name=str(i.get("name") or "Request"),
                    performers=tuple(Performer(p) for p in i.get("performers") or ["borrower"]),
                    key=i.get("key"),
                )
                for i in (condition.reading or {}).get("items") or []
            ],
            actor_user_id=actor,
        )
    await confirm_round_plan(db, round_=round_, actor_user_id=actor)
    return loan_file, conditions, actor


async def _items(db: AsyncSession, condition: Condition) -> list[ConditionItem]:
    return list(
        await db.scalars(
            select(ConditionItem)
            .where(ConditionItem.condition_id == condition.id, ConditionItem.deleted_at.is_(None))
            .order_by(ConditionItem.sequence)
        )
    )


async def _question(db: AsyncSession, condition: Condition) -> Communication | None:
    draft = await db.scalar(
        select(ConditionDraft).where(ConditionDraft.condition_id == condition.id)
    )
    if draft is None:
        return None
    message = await db.get(Communication, draft.communication_id)
    return message if message is not None and message.deleted_at is None else None


def _text(body: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()


async def test_iv01_at_uwm_offers_two_routes(db_session: AsyncSession) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, _, _ = await _confirmed(db_session)
    client, _, processor = await _clients(db_session, loan_file)
    async with client:
        rows = (
            await client.get(f"/api/v1/loan-files/{loan_file.id}/conditions", headers=processor)
        ).json()
    by_code = {row["lender_code"]: row for row in rows}
    assert [r["key"] for r in by_code["0006"]["routes"]] == ["lender_system", "our_vendor"]
    assert by_code["0006"]["routes"][0]["label"] == "Pulled in UWM's system"
    # LP-955 REVIEW: the route it is ON, not only a stepped one it was moved to. With no step, 0006's
    # item is hers to upload, which IS "Our vendor" — and it had to become derivable so that picking
    # it presses something (it read as nothing chosen before, exactly like never having chosen).
    assert by_code["0006"]["chosen_route"] == "our_vendor"
    # The positive control: a condition no route is defined for offers none.
    assert by_code["1582"]["routes"] == []


async def test_pulled_in_uwms_system_asks_the_underwriter_in_the_types_words(
    db_session: AsyncSession,
) -> None:
    _, conditions, actor = await _confirmed(db_session)
    condition = conditions["0006"]
    await choose_route(
        db_session, condition=condition, route_key="lender_system", actor_user_id=actor
    )
    assert condition.next_step is PlanOption.ASK_UNDERWRITER
    message = await _question(db_session, condition)
    assert message is not None
    text = _text(message.body or "")
    assert "pulled in UWM's system, so UWM has the invoice" in text
    assert "Could you clear 0006" in text


async def test_our_vendor_keeps_it_her_task_and_drops_the_question(
    db_session: AsyncSession,
) -> None:
    _, conditions, actor = await _confirmed(db_session)
    condition = conditions["0006"]
    await choose_route(
        db_session, condition=condition, route_key="lender_system", actor_user_id=actor
    )
    assert await _question(db_session, condition) is not None
    await choose_route(db_session, condition=condition, route_key="our_vendor", actor_user_id=actor)
    assert condition.next_step is None
    assert [i.option for i in await _items(db_session, condition)] == [PlanOption.I_WILL_DO_IT]
    assert await _question(db_session, condition) is None


async def test_our_vendor_reads_as_chosen_and_a_step_no_route_sets_reads_as_neither(
    db_session: AsyncSession,
) -> None:
    """LP-955 review — every route the condition can be on reads back, and only those.

    `chosen_route` returned the stepped routes only, so "Our vendor" could never be pressed: she
    picked it, the panel refetched, and the two buttons looked untouched. The last row is the control
    that keeps this honest — a step no route sets must still read as no route, or "pressed" would
    just mean "has no other step".
    """
    from app.services.condition_plan import chosen_route, routes_for, set_next_step

    _, conditions, actor = await _confirmed(db_session)
    condition = conditions["0006"]
    routes = routes_for("uwm", "IV-01")
    assert [r.key for r in routes] == ["lender_system", "our_vendor"]

    assert chosen_route(condition, routes) == "our_vendor"  # the default state IS her task
    await choose_route(
        db_session, condition=condition, route_key="lender_system", actor_user_id=actor
    )
    assert chosen_route(condition, routes) == "lender_system"
    await choose_route(db_session, condition=condition, route_key="our_vendor", actor_user_id=actor)
    assert chosen_route(condition, routes) == "our_vendor"
    # THE CONTROL: a step neither route sets is neither route.
    await set_next_step(
        db_session, condition=condition, next_step=PlanOption.ASK_BORROWER, actor_user_id=actor
    )
    assert chosen_route(condition, routes) is None


def test_no_two_routes_in_a_pair_share_a_step() -> None:
    """The premise `chosen_route` rests on, over the whole table: it answers with the first route
    whose step the condition carries, so two routes sharing one step (`None` counts) would make the
    answer arbitrary. A new ROUTES row that breaks this fails here rather than in a drawer."""
    from app.services.condition_plan import ROUTES

    assert ROUTES, "the positive control: an empty table would pass this vacuously"
    for pair, routes in ROUTES.items():
        steps = [route.step for route in routes]
        assert len(steps) == len(set(steps)), f"{pair} has two routes with one step"
        assert len({route.key for route in routes}) == len(routes), f"{pair} repeats a route key"


async def test_a_route_not_offered_is_refused(db_session: AsyncSession) -> None:
    _, conditions, actor = await _confirmed(db_session)
    with pytest.raises(PlanRefused):
        await choose_route(
            db_session, condition=conditions["1582"], route_key="lender_system", actor_user_id=actor
        )
    with pytest.raises(PlanRefused):
        await choose_route(
            db_session, condition=conditions["0006"], route_key="nonsense", actor_user_id=actor
        )


async def test_a_question_without_a_type_question_keeps_the_reading(
    db_session: AsyncSession,
) -> None:
    """The positive control for the type's own words: 1582 (IV-02) has none, so its question is the
    reading's summary and the general request."""
    from app.services.condition_plan import set_next_step

    _, conditions, actor = await _confirmed(db_session)
    condition = conditions["1582"]
    await set_next_step(
        db_session, condition=condition, next_step=PlanOption.ASK_UNDERWRITER, actor_user_id=actor
    )
    message = await _question(db_session, condition)
    assert message is not None
    text = _text(message.body or "")
    assert "system, so" not in text
    assert "Could you let me know what you need to clear 1582?" in text


async def test_ask_someone_for_it_puts_her_task_in_their_draft(db_session: AsyncSession) -> None:
    _, conditions, actor = await _confirmed(db_session)
    condition = conditions["0006"]
    [task] = await _items(db_session, condition)
    assert task.option is PlanOption.I_WILL_DO_IT and task.draft_id is None
    await update_item(
        db_session,
        condition=condition,
        item=task,
        option=PlanOption.ASK_THIRD_PARTY,
        name=None,
        performers=[Performer.LO],
        due_date=None,
        actor_user_id=actor,
    )
    assert getattr(task, "option") is PlanOption.ASK_THIRD_PARTY  # noqa: B009 (mypy narrowing)
    assert task.draft_id is not None
    draft = await db_session.get(ConditionDraft, task.draft_id)
    assert draft is not None and draft.recipient is DraftRecipient.LO
    # THE SAME ROW, CHANGED IN PLACE: evidence, her unlinks and the draft link are keyed by its id.
    assert [i.id for i in await _items(db_session, condition)] == [task.id]


async def test_the_route_endpoint(db_session: AsyncSession) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, conditions, _ = await _confirmed(db_session)
    client, _, processor = await _clients(db_session, loan_file)
    async with client:
        chose = await client.put(
            f"/api/v1/conditions/{conditions['0006'].id}/route",
            json={"route": "lender_system"},
            headers=processor,
        )
        assert chose.status_code == 200, chose.text
        assert chose.json()["chosen_route"] == "lender_system"
        refused = await client.put(
            f"/api/v1/conditions/{conditions['1582'].id}/route",
            json={"route": "lender_system"},
            headers=processor,
        )
        assert refused.status_code == 409
