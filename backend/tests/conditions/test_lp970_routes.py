"""LP-970 — routes a condition can take, driven by the lender setting that decides them.

A route is the plan's own rules run with that setting forced, or every library task set to one step.
The suggestion is the route whose setting matches the lender's actual setting; choosing one rebuilds the
condition's step and its tasks' steps through the plan's ordinary doors.

The file: the UWM round-1 sheet on a UWM file (LP-955's `_confirmed`). 1228 is PA-03, the final
inspection (UWM orders it by default, decision 1); its second task, the Change of Circumstance, is a
clause the library's PA-03 does not cover. 6178 is IN-01, a Processor Assist type.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.models.condition import Condition
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_vocabulary import PlanOption
from app.models.lender import Lender
from app.services import condition_reading
from app.services.condition_plan import (
    ROUTES,
    LenderConditionSettings,
    PlanRefused,
    choose_route,
    chosen_route,
    lender_condition_settings,
    revert_to_suggested,
    route_target,
    routes_for,
    routes_offered,
    suggested_route,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.test_lp955_ill_do_it_actions import _confirmed, _items


@pytest.fixture(autouse=True)
def _model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())


@pytest.fixture(autouse=True)
def _drop_db_override() -> Any:
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


def _route(type_id: str, key: str, lender: str = "uwm") -> Any:
    return next(route for route in routes_for(lender, type_id) if route.key == key)


async def _chosen(db: AsyncSession, condition: Any) -> str | None:
    lender = await db.get(Lender, condition.lender_id)
    return chosen_route(
        condition,
        routes_for("uwm", condition.canonical_type_id),
        items=await _items(db, condition),
        settings=lender_condition_settings(lender),
        lender_processing=False,
    )


async def _options(db: AsyncSession, condition: Any) -> dict[str, PlanOption | None]:
    return {str(item.key): item.option for item in await _items(db, condition)}


# --- which routes, and which is suggested ------------------------------------------------------------


def test_a_lenders_own_row_wins_and_any_lender_is_the_fallback() -> None:
    assert [r.key for r in routes_for("uwm", "IV-01")] == ["lender_system", "our_vendor"]
    assert [r.key for r in routes_for("uwm", "PA-03")] == [
        "lender_orders",
        "ask_lender",
        "order_yourself",
    ]
    assert [r.key for r in routes_for("sunwest", "PA-03")] == [
        "lender_orders",
        "ask_lender",
        "order_yourself",
    ]
    assert [r.key for r in routes_for("sunwest", "IE-08")] == [
        "lender_verifies",
        "borrower_provides",
    ]
    for type_id in ("TI-01", "TI-02", "TI-05", "IN-01", "IN-02", "IN-04"):
        assert [r.key for r in routes_for("sunwest", type_id)] == ["lender_orders", "ask_party"]
    # THE CONTROLS: no lender, no type, and a type no row names have none.
    assert routes_for(None, "PA-03") == ()
    assert routes_for("uwm", None) == ()
    assert routes_for("uwm", "AS-10") == ()
    # IV-01's routes are UWM's own: another lender has none.
    assert routes_for("sunwest", "IV-01") == ()


def test_the_suggestion_follows_the_setting() -> None:
    pa03 = routes_for("uwm", "PA-03")
    assert suggested_route(pa03, LenderConditionSettings(lender_orders_final_inspection=True)) == (
        "lender_orders"
    )
    assert suggested_route(pa03, LenderConditionSettings()) == "order_yourself"
    ie08 = routes_for("uwm", "IE-08")
    assert suggested_route(
        ie08, LenderConditionSettings(lender_verifies_business_existence=True)
    ) == ("lender_verifies")
    assert suggested_route(ie08, LenderConditionSettings()) == "borrower_provides"
    in01 = routes_for("uwm", "IN-01")
    assert suggested_route(
        in01, LenderConditionSettings(lender_orders_title_insurance_payoffs=True)
    ) == ("lender_orders")
    assert suggested_route(in01, LenderConditionSettings()) == "ask_party"
    # A lender's step-only routes (LP-955) have no setting, so nothing is suggested.
    assert suggested_route(routes_for("uwm", "IV-01"), LenderConditionSettings()) is None


def test_every_setting_route_names_its_reason() -> None:
    for pair, routes in ROUTES.items():
        for route in routes:
            if route.setting is not None:
                assert route.suggested_because, f"{pair} {route.key} has no reason"
                assert hasattr(LenderConditionSettings(), route.setting), f"{pair} {route.setting}"


# --- what a route makes the condition ----------------------------------------------------------------


async def test_the_three_pa03_targets_differ(db_session: AsyncSession) -> None:
    """The premise of `chosen_route` on PA-03, measured on the condition rather than the table."""
    _, conditions, _ = await _confirmed(db_session)
    condition = conditions["1228"]
    uwm = LenderConditionSettings(lender_orders_final_inspection=True)

    orders = route_target(_route("PA-03", "lender_orders"), condition, uwm, lender_processing=False)
    asks = route_target(_route("PA-03", "ask_lender"), condition, uwm, lender_processing=False)
    yourself = route_target(
        _route("PA-03", "order_yourself"), condition, uwm, lender_processing=False
    )

    # The lender's order covers the library's task only; the clause the library does not know keeps
    # its own step, so the lender is not doing ALL of it and the condition has no step (LP-954).
    assert orders[0] is None
    assert orders[1]["inspection"] is PlanOption.LENDER_DOING_IT
    assert orders[1]["change_of_circumstance"] is not PlanOption.LENDER_DOING_IT
    assert asks == (None, {"inspection": PlanOption.ASK_THIRD_PARTY})
    assert yourself[0] is None
    assert yourself[1]["inspection"] is PlanOption.I_WILL_DO_IT
    assert len({repr(orders), repr(asks), repr(yourself)}) == 3


async def test_the_suggested_plan_reads_as_the_suggested_route(db_session: AsyncSession) -> None:
    """UWM orders final inspections, so 1228's plan as built IS `lender_orders`.

    THE TARGET IS THE PLAN THE PLANNER BUILDS, step settling included. The first `route_target` said
    LENDER_DOING_IT for the condition's step while `build_plan` clears it (the clause stays the LO's),
    so the suggestion never read as chosen and choosing it made a plan the planner never makes."""
    _, conditions, _ = await _confirmed(db_session)
    condition = conditions["1228"]
    assert condition.next_step is None
    assert (await _options(db_session, condition))["inspection"] is PlanOption.LENDER_DOING_IT
    assert await _chosen(db_session, condition) == "lender_orders"


async def test_choosing_a_route_rebuilds_the_step_and_the_tasks(db_session: AsyncSession) -> None:
    _, conditions, actor = await _confirmed(db_session)
    condition = conditions["1228"]
    clause_before = (await _options(db_session, condition))["change_of_circumstance"]

    await choose_route(
        db_session, condition=condition, route_key="order_yourself", actor_user_id=actor
    )
    assert condition.next_step is None
    assert (await _options(db_session, condition))["inspection"] is PlanOption.I_WILL_DO_IT
    assert await _chosen(db_session, condition) == "order_yourself"

    await choose_route(db_session, condition=condition, route_key="ask_lender", actor_user_id=actor)
    options = await _options(db_session, condition)
    assert options["inspection"] is PlanOption.ASK_THIRD_PARTY
    assert options["change_of_circumstance"] is clause_before, "ask_lender sets library tasks only"
    assert await _chosen(db_session, condition) == "ask_lender"

    await choose_route(
        db_session, condition=condition, route_key="lender_orders", actor_user_id=actor
    )
    assert condition.next_step is None
    options = await _options(db_session, condition)
    assert options["inspection"] is PlanOption.LENDER_DOING_IT
    assert options["change_of_circumstance"] is clause_before
    assert await _chosen(db_session, condition) == "lender_orders"


async def test_a_task_changed_by_hand_is_no_route(db_session: AsyncSession) -> None:
    """THE CONTROL for `chosen_route`: a step no route sets is not read as one."""
    from app.services.condition_plan import update_item

    _, conditions, actor = await _confirmed(db_session)
    condition = conditions["1228"]
    await choose_route(
        db_session, condition=condition, route_key="order_yourself", actor_user_id=actor
    )
    inspection = next(i for i in await _items(db_session, condition) if i.key == "inspection")
    await update_item(
        db_session,
        condition=condition,
        item=inspection,
        option=PlanOption.ASK_BORROWER,
        name=None,
        performers=None,
        due_date=None,
        actor_user_id=actor,
    )
    assert await _chosen(db_session, condition) is None


async def test_a_route_is_her_change_and_going_back_restores_the_suggestion(
    db_session: AsyncSession,
) -> None:
    _, conditions, actor = await _confirmed(db_session)
    condition = conditions["1228"]
    before = await _options(db_session, condition)

    await choose_route(
        db_session, condition=condition, route_key="order_yourself", actor_user_id=actor
    )
    changes = list(
        await db_session.scalars(
            select(ConditionEvent).where(
                ConditionEvent.condition_id == condition.id,
                ConditionEvent.kind == ConditionEventKind.CONDITION_PLAN_CHANGED,
            )
        )
    )
    assert changes, "the route wrote its changes to the history"

    await revert_to_suggested(db_session, condition=condition, actor_user_id=actor)
    assert condition.next_step is None
    assert await _options(db_session, condition) == before
    assert await _chosen(db_session, condition) == "lender_orders"


def test_a_processor_assist_route_moves_the_ask() -> None:
    """An IN-01 the insurance agent sends: Processor Assist on, the lender gets it and the whole
    condition is the lender's; off, it is an ask. In memory: the fixture's only IN-01 is pushed back."""
    condition = Condition(
        canonical_type_id="IN-01",
        reading={
            "items": [
                {"key": "declarations", "performers": ["insurance"], "option": "ask_third_party"}
            ]
        },
        info_only=False,
    )
    settings = LenderConditionSettings()
    on = route_target(
        _route("IN-01", "lender_orders"), condition, settings, lender_processing=False
    )
    off = route_target(_route("IN-01", "ask_party"), condition, settings, lender_processing=False)
    assert on == (PlanOption.LENDER_DOING_IT, {"declarations": PlanOption.LENDER_DOING_IT})
    assert off == (None, {"declarations": PlanOption.ASK_THIRD_PARTY})


def test_a_route_never_puts_a_push_back_back() -> None:
    """A route is how the work gets done, so it presumes the work is done. Once she moves a pushed-back
    condition off push back, a route must not re-impose it from the reading."""
    condition = Condition(
        canonical_type_id="IN-01",
        reading={
            "push_back": {"must_not_close_before": "2026-09-30", "policy_starts": "2026-09-30"},
            "items": [
                {"key": "declarations", "performers": ["insurance"], "option": "ask_third_party"}
            ],
        },
        info_only=False,
    )
    step, _ = route_target(
        _route("IN-01", "ask_party"), condition, LenderConditionSettings(), lender_processing=False
    )
    assert step is None


async def test_a_pushed_back_condition_offers_no_routes(db_session: AsyncSession) -> None:
    """6178 (IN-01) is pushed back at UWM: nobody does the work, so every route would be a click that
    changes nothing. None is offered, and the door refuses one."""
    _, conditions, actor = await _confirmed(db_session)
    condition = conditions["6178"]
    assert condition.next_step is PlanOption.PUSH_BACK
    assert routes_for("uwm", "IN-01"), "the premise: the type has routes at any lender"
    assert routes_offered(condition, "uwm") == ()
    with pytest.raises(PlanRefused):
        await choose_route(
            db_session, condition=condition, route_key="ask_party", actor_user_id=actor
        )
    # THE CONTROL: off push back, its routes come back.
    from app.services.condition_plan import set_next_step

    await set_next_step(db_session, condition=condition, next_step=None, actor_user_id=actor)
    assert [r.key for r in routes_offered(condition, "uwm")] == ["lender_orders", "ask_party"]


# --- the payload -------------------------------------------------------------------------------------


async def test_the_list_names_the_lender_and_the_suggestion(db_session: AsyncSession) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, conditions, _ = await _confirmed(db_session)
    lender = await db_session.get(Lender, conditions["1228"].lender_id)
    assert lender is not None
    client, _, processor = await _clients(db_session, loan_file)
    async with client:
        got = await client.get(f"/api/v1/loan-files/{loan_file.id}/conditions", headers=processor)
    assert got.status_code == 200, got.text
    row = next(each for each in got.json() if each["lender_code"] == "1228")
    by_key = {route["key"]: route for route in row["routes"]}
    assert list(by_key) == ["lender_orders", "ask_lender", "order_yourself"]
    assert by_key["lender_orders"]["label"] == f"{lender.name} orders it"
    assert by_key["lender_orders"]["suggested"] is True
    assert by_key["lender_orders"]["why"] == (
        f"{lender.name}'s settings say it orders final inspections."
    )
    for key in ("ask_lender", "order_yourself"):
        assert by_key[key]["suggested"] is False
        assert by_key[key]["why"] is None
    assert not any("{lender}" in str(route) for route in row["routes"])
    assert row["chosen_route"] == "lender_orders"
    # THE CONTROLS: a type no row names offers nothing, and neither does a pushed-back condition.
    assert next(each for each in got.json() if each["lender_code"] == "7086")["routes"] == []
    assert next(each for each in got.json() if each["lender_code"] == "6178")["routes"] == []


async def test_the_route_door_rebuilds_and_answers(db_session: AsyncSession) -> None:
    from tests.conditions.test_lender_condition_settings import _clients

    loan_file, conditions, _ = await _confirmed(db_session)
    client, _, processor = await _clients(db_session, loan_file)
    async with client:
        got = await client.put(
            f"/api/v1/conditions/{conditions['1228'].id}/route",
            json={"route": "order_yourself"},
            headers=processor,
        )
    assert got.status_code == 200, got.text
    assert got.json()["chosen_route"] == "order_yourself"


async def test_an_asked_task_stays_on_its_route_and_a_route_still_moves_it(
    db_session: AsyncSession,
) -> None:
    """Sending the email makes the task `requested`; it is still the route she chose, and choosing
    another still changes it. Only a done or not-needed task is on no route."""
    from app.models.condition_vocabulary import ConditionItemStatus

    _, conditions, actor = await _confirmed(db_session)
    condition = conditions["1228"]
    await choose_route(db_session, condition=condition, route_key="ask_lender", actor_user_id=actor)
    inspection = next(i for i in await _items(db_session, condition) if i.key == "inspection")
    inspection.status = ConditionItemStatus.REQUESTED
    await db_session.flush()
    assert await _chosen(db_session, condition) == "ask_lender"

    await choose_route(
        db_session, condition=condition, route_key="order_yourself", actor_user_id=actor
    )
    assert (await _options(db_session, condition))["inspection"] is PlanOption.I_WILL_DO_IT
    assert await _chosen(db_session, condition) == "order_yourself"


def test_an_ask_addressed_to_her_is_her_task_in_the_target_too() -> None:
    """`route_ask` (LP-942) makes an ask to the processor her own task when the plan is built, so the
    target must say so, or the route never reads as chosen."""
    condition = Condition(
        canonical_type_id="IN-01",
        reading={
            "items": [
                {"key": "declarations", "performers": ["processor"], "option": "ask_third_party"}
            ]
        },
        info_only=False,
    )
    _, tasks = route_target(
        _route("IN-01", "ask_party"), condition, LenderConditionSettings(), lender_processing=False
    )
    assert tasks == {"declarations": PlanOption.I_WILL_DO_IT}


def test_a_lender_route_on_a_pushed_back_reading_is_still_the_lenders() -> None:
    """The reading's push back is set aside before the setting is applied, not after: otherwise push back
    wins over "the lender orders it" in `_step_and_reason`, the step is dropped to none, and the
    inspection keeps its own step. Choosing "UWM orders it" would then leave her ordering it."""
    condition = Condition(
        canonical_type_id="PA-03",
        reading={
            "push_back": {"must_not_close_before": "2026-09-30"},
            "items": [{"key": "inspection", "performers": ["appraiser"], "option": "i_will_do_it"}],
        },
        info_only=False,
    )
    assert route_target(
        _route("PA-03", "lender_orders"),
        condition,
        LenderConditionSettings(),
        lender_processing=False,
    ) == (PlanOption.LENDER_DOING_IT, {"inspection": PlanOption.LENDER_DOING_IT})


def test_no_two_routes_in_a_group_can_both_match_a_condition() -> None:
    """LP-970 REVIEW — the builder's third question, over the WHOLE table rather than by example.

    `chosen_route` answers with the FIRST route whose target the condition carries, so two routes that
    can both match make the answer arbitrary and silent: she picks one and the panel shows the other.
    Two guards exist already — `test_no_two_routes_in_a_pair_share_a_step` pins that no two ROWS
    declare the same shape, and `test_the_three_pa03_targets_differ` pins that PA-03's computed targets
    differ on a condition. Neither covers the shape the question is about: `chosen_route` compares only
    LIVE tasks, and a key missing from them passes as `None`, so two routes that AGREE on one task and
    DIFFER on another both match once the differing task is done.

    This computes every group's target on a condition carrying its type's library tasks and asserts no
    pair can collide that way. Measured when it was written: every routed type has one library task
    except IN-02, whose two routes differ on BOTH of its tasks — so nothing collides today, and a row
    that would collide fails here rather than in a drawer.
    """
    from itertools import combinations

    from app.conditions.library.loader import load_library
    from app.services.condition_plan import route_target

    def collide(
        first: tuple[Any, dict[str, PlanOption]], second: tuple[Any, dict[str, PlanOption]]
    ) -> tuple[list[str], list[str]]:
        """The keys two targets differ on and agree on, once their steps match. Both non-empty is the
        collision: the ones they differ on can be done, and then both routes match."""
        (step_a, tasks_a), (step_b, tasks_b) = first, second
        if step_a is not step_b:
            return [], []
        differ = [
            key for key in set(tasks_a) | set(tasks_b) if tasks_a.get(key) is not tasks_b.get(key)
        ]
        agree = [key for key in set(tasks_a) & set(tasks_b) if tasks_a[key] is tasks_b[key]]
        return differ, agree

    # THE POSITIVE CONTROL FOR THE CHECK ITSELF, because no row in the table collides today: a guard
    # for a shape that does not exist yet passes whether or not it works, so the detector is shown to
    # fire on a constructed pair that IS the shape.
    assert collide(
        (None, {"x": PlanOption.ASK_BORROWER, "y": PlanOption.I_WILL_DO_IT}),
        (None, {"x": PlanOption.ASK_BORROWER, "y": PlanOption.LENDER_DOING_IT}),
    ) == (["y"], ["x"])
    assert collide(
        (None, {"x": PlanOption.ASK_BORROWER}),
        (PlanOption.LENDER_DOING_IT, {"x": PlanOption.ASK_BORROWER}),
    ) == ([], []), "different steps are told apart before the tasks are compared"

    library = load_library()
    assert ROUTES, "the positive control: an empty table would pass this vacuously"
    compared = 0
    for (lender_key, type_id), routes in ROUTES.items():
        condition_type = library.get(type_id)
        assert condition_type is not None, f"{type_id} has routes but no library type"
        condition = Condition(
            canonical_type_id=type_id,
            info_only=False,
            reading={
                "items": [
                    {
                        "key": each.key,
                        "performers": list(each.performers) or [each.performer],
                        "option": each.option.value,
                    }
                    for each in condition_type.items
                ]
            },
        )
        targets = {
            route.key: route_target(
                route, condition, LenderConditionSettings(), lender_processing=False
            )
            for route in routes
        }
        for first, second in combinations(targets, 2):
            compared += 1
            differ, agree = collide(targets[first], targets[second])
            tasks_a, tasks_b = targets[first][1], targets[second][1]
            if targets[first][0] is not targets[second][0]:
                continue
            assert not tasks_a or not tasks_b or differ, (
                f"{lender_key}/{type_id}: {first} and {second} have identical targets"
            )
            assert not (differ and agree), (
                f"{lender_key}/{type_id}: {first} and {second} share a step and agree on {agree} "
                f"while differing on {differ} — with those done, both match and table order decides"
            )
    assert compared >= len(ROUTES), "the control: every group contributed at least one comparison"


def test_a_route_asks_route_asks_own_rule_about_who_the_ask_goes_to() -> None:
    """LP-970 REVIEW — the builder's second question: the two rules are NOT the same set.

    `route_target` decided "an ask addressed to her is her own task" by looking at the first performer;
    `route_ask`, the rule it is copying, asks `recipient_for(item) is None`. Those agree on every shape
    but one: `recipient_for` relays any list CONTAINING the LO to the LO's email wherever it sits
    (0132's disclosure goes out in the LO's), so `[processor, lo]` HAS a destination. `route_ask` leaves
    it an ask; the copy made it hers. The route's predicted plan and the built one would then disagree
    on that task for ever and the route could never read as chosen.

    Nothing ships that shape — the library's only multi-performer item is 0132's `[borrower, lo]` — so
    this is about the rule rather than about today's data, which is why it is asserted against
    `recipient_for` itself rather than through a fixture that cannot currently exist.
    """
    from app.models.condition_vocabulary import Performer
    from app.services.condition_plan import _ask_is_hers, _RawAsk, recipient_for

    hers = {"key": "x", "performers": ["processor"], "option": "ask_third_party"}
    lo_too = {"key": "x", "performers": ["processor", "lo"], "option": "ask_third_party"}

    # THE PREMISE, from the rule being copied: one has no destination, the other goes to the LO.
    assert (
        recipient_for(_RawAsk(PlanOption.ASK_THIRD_PARTY, Performer.PROCESSOR, ["processor"]))
        is None
    )
    assert recipient_for(
        _RawAsk(PlanOption.ASK_THIRD_PARTY, Performer.PROCESSOR, ["processor", "lo"])
    ) == ("lo", "LO")

    assert _ask_is_hers(PlanOption.ASK_THIRD_PARTY, hers) is True
    assert _ask_is_hers(PlanOption.ASK_THIRD_PARTY, lo_too) is False, (
        "an ask the LO sends is not her own task, however the performers are ordered"
    )
    # A performer the vocabulary does not know keeps the old literal answer rather than raising:
    # these are raw reading dicts, not the validated items `route_ask` sees.
    assert _ask_is_hers(PlanOption.ASK_THIRD_PARTY, {"performers": ["nonsense"]}) is False
    assert (
        _ask_is_hers(PlanOption.ASK_THIRD_PARTY, {"performers": ["processor", "nonsense"]}) is True
    )
