"""LP-921's "Done when", through the database and the routes.

Every condition on round 1 has a sensible step from the plan, and choosing a step moves our status and
writes an event — once the plan is in force, forward only, and never for a display-only step. The
summary's new numbers are the filter's own predicate. The model is mocked (`reading_fixture`).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.models.condition import Condition, ConditionPrepStatus, OwnerHint
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import ConditionRound
from app.models.condition_vocabulary import ConditionItemStatus, PlanOption
from app.models.loan_file import LoanFile
from app.schemas.condition import ConditionEventPublic, PrepStatusRequest
from app.services import condition_reading
from app.services.condition_plan import (
    PlanRefused,
    confirm_round_plan,
    set_next_step,
    update_item,
)
from app.services.condition_reading import ConfirmedItem, confirm_reading
from app.services.condition_status import move_prep_status
from app.services.conditions import condition_summary
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.test_condition_plan import (
    _actor,
    _conditions,
    _items,
    _planned_round_one,
)
from tests.conditions.test_condition_reading import _client_for, _file_with_round


@pytest.fixture(autouse=True)
def _mocked_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())


@pytest.fixture(autouse=True)
def _no_leftover_db_override() -> Any:
    """`_client_for` overrides `get_db`; drop it after each test, as the other route tests do."""
    from app.core.database import get_db
    from app.main import app

    yield
    app.dependency_overrides.pop(get_db, None)


async def _confirmed_round_one(
    db: AsyncSession,
) -> tuple[LoanFile, ConditionRound, dict[str, Condition], Any]:
    """Round 1 planned, 0132's reading confirmed as read, and the plan confirmed."""
    loan_file, round_ = await _planned_round_one(db)
    actor = await _actor(db, loan_file)
    conditions = await _conditions(db, loan_file)
    await confirm_reading(
        db,
        condition=conditions["0132"],
        items=[
            ConfirmedItem(name=i.name, performers=(i.performer,), key=i.key)
            for i in await _items(db, conditions["0132"])
        ],
        actor_user_id=actor,
    )
    await confirm_round_plan(db, round_=round_, actor_user_id=actor)
    return loan_file, round_, conditions, actor


async def _plan_moves(db: AsyncSession, condition: Condition) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(ConditionEvent).where(
                ConditionEvent.condition_id == condition.id,
                ConditionEvent.kind == ConditionEventKind.CONDITION_PREP_MOVED,
            )
        )
    ).scalars()
    return [row.detail for row in rows if row.detail.get("by") == "plan"]


async def test_every_round_one_condition_has_a_step(db_session: AsyncSession) -> None:
    loan_file, round_ = await _planned_round_one(db_session)
    conditions = await _conditions(db_session, loan_file)
    on_round = [c for c in conditions.values() if c.last_seen_round_id == round_.id]
    assert len(on_round) == 11
    for condition in on_round:
        live = [
            i
            for i in await _items(db_session, condition)
            if i.status is not ConditionItemStatus.NOT_NEEDED
        ]
        assert condition.next_step is not None or live, condition.lender_code


async def point_items_at_a_document(db: AsyncSession, condition: Condition) -> None:
    """LP-953 — "Already in the file" by hand needs a linked document. These tests are about what the
    STEP does, so each live item gets the pointer a plan-time match would set, and nothing else (a full
    manual link would also run checks and could move the condition, which is not what they test)."""
    from uuid import uuid4

    from app.models.document import Document, DocumentStatus, UploadSource

    document = Document(
        loan_file_id=condition.loan_file_id,
        original_filename="processing-invoice.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path=f"{condition.loan_file_id}/{uuid4().hex}.pdf",
        document_type="service_invoice",
        document_name="Processing invoice",
        status=DocumentStatus.COMPLETED,
        upload_source=UploadSource.USER_UPLOAD,
    )
    db.add(document)
    await db.flush()
    for item in await _items(db, condition):
        if item.status is not ConditionItemStatus.NOT_NEEDED:
            item.document_id = document.id
    await db.flush()


async def test_nothing_moves_while_the_plan_is_a_proposal(db_session: AsyncSession) -> None:
    loan_file, _ = await _planned_round_one(db_session)
    conditions = await _conditions(db_session, loan_file)
    actor = await _actor(db_session, loan_file)
    # 0006's item is already in the file, and 1582 is re-pointed there too — neither moves yet.
    await point_items_at_a_document(db_session, conditions["1582"])
    await set_next_step(
        db_session,
        condition=conditions["1582"],
        next_step=PlanOption.ALREADY_IN_FILE,
        actor_user_id=actor,
    )
    assert conditions["0006"].prep_status is ConditionPrepStatus.TO_DO
    assert conditions["1582"].prep_status is ConditionPrepStatus.TO_DO
    assert await _plan_moves(db_session, conditions["1582"]) == []


async def test_confirming_moves_already_in_file_to_ready(db_session: AsyncSession) -> None:
    _, _, conditions, _ = await _confirmed_round_one(db_session)
    assert conditions["0006"].prep_status is ConditionPrepStatus.READY
    assert await _plan_moves(db_session, conditions["0006"]) == [
        {
            "prep_status_from": "to_do",
            "prep_status_to": "ready",
            "by": "plan",
            "option": "already_in_file",
        }
    ]
    # Everything else is still owed: asks wait for a send (LP-922), tasks for her, 1228 is the lender's.
    moved = {
        code for code, c in conditions.items() if c.prep_status is not ConditionPrepStatus.TO_DO
    }
    assert moved == {"0006"}


async def test_choosing_a_step_after_confirming_moves_and_records(
    db_session: AsyncSession,
) -> None:
    _, _, conditions, actor = await _confirmed_round_one(db_session)
    condition = conditions["1582"]
    await point_items_at_a_document(db_session, condition)
    await set_next_step(
        db_session, condition=condition, next_step=PlanOption.ALREADY_IN_FILE, actor_user_id=actor
    )
    assert condition.prep_status is ConditionPrepStatus.READY
    kinds = (
        (
            await db_session.execute(
                select(ConditionEvent.kind).where(ConditionEvent.condition_id == condition.id)
            )
        )
        .scalars()
        .all()
    )
    assert ConditionEventKind.CONDITION_PLAN_CHANGED in kinds
    assert (await _plan_moves(db_session, condition))[0]["option"] == "already_in_file"


async def test_her_task_done_moves_to_ready(db_session: AsyncSession) -> None:
    _, _, conditions, actor = await _confirmed_round_one(db_session)
    condition = conditions["1582"]
    (task,) = await _items(db_session, condition)
    assert task.option is PlanOption.I_WILL_DO_IT
    await update_item(
        db_session,
        condition=condition,
        item=task,
        option=None,
        name=None,
        performers=None,
        due_date=None,
        actor_user_id=actor,
        status=ConditionItemStatus.DONE,
    )
    assert condition.prep_status is ConditionPrepStatus.READY
    assert (await _plan_moves(db_session, condition))[0]["option"] == "i_will_do_it"


async def test_an_asked_item_is_not_marked_done_by_hand(db_session: AsyncSession) -> None:
    _, _, conditions, actor = await _confirmed_round_one(db_session)
    condition = conditions["7086"]
    ask = (await _items(db_session, condition))[0]
    assert ask.option is PlanOption.ASK_BORROWER
    with pytest.raises(PlanRefused, match="Only your own tasks"):
        await update_item(
            db_session,
            condition=condition,
            item=ask,
            option=None,
            name=None,
            performers=None,
            due_date=None,
            actor_user_id=actor,
            status=ConditionItemStatus.DONE,
        )
    assert ask.status is not ConditionItemStatus.DONE
    assert condition.prep_status is ConditionPrepStatus.TO_DO


async def test_the_plan_never_overrides_her_move(db_session: AsyncSession) -> None:
    _, _, conditions, actor = await _confirmed_round_one(db_session)
    condition = conditions["1582"]
    await move_prep_status(
        db_session,
        condition=condition,
        payload=PrepStatusRequest(to=ConditionPrepStatus.WAITING, waiting_on=OwnerHint.LENDER),
        actor_user_id=actor,
    )
    await point_items_at_a_document(db_session, condition)
    await set_next_step(
        db_session, condition=condition, next_step=PlanOption.ALREADY_IN_FILE, actor_user_id=actor
    )
    assert condition.prep_status is ConditionPrepStatus.WAITING
    assert await _plan_moves(db_session, condition) == []


@pytest.mark.parametrize("option", [PlanOption.LENDER_DOING_IT, PlanOption.INFORMATION_ONLY])
async def test_a_display_only_step_never_moves(
    db_session: AsyncSession, option: PlanOption
) -> None:
    _, _, conditions, actor = await _confirmed_round_one(db_session)
    condition = conditions["1582"]
    await set_next_step(db_session, condition=condition, next_step=option, actor_user_id=actor)
    (task,) = await _items(db_session, condition)
    await update_item(
        db_session,
        condition=condition,
        item=task,
        option=None,
        name=None,
        performers=None,
        due_date=None,
        actor_user_id=actor,
        status=ConditionItemStatus.DONE,
    )
    assert condition.prep_status is ConditionPrepStatus.TO_DO
    assert conditions["1228"].next_step is PlanOption.LENDER_DOING_IT
    assert conditions["1228"].prep_status is ConditionPrepStatus.TO_DO


async def test_the_history_says_the_plan_moved_it(db_session: AsyncSession) -> None:
    _, _, conditions, _ = await _confirmed_round_one(db_session)
    event = (
        await db_session.execute(
            select(ConditionEvent).where(
                ConditionEvent.condition_id == conditions["0006"].id,
                ConditionEvent.kind == ConditionEventKind.CONDITION_PREP_MOVED,
            )
        )
    ).scalar_one()
    public = ConditionEventPublic.from_model(event)
    assert public.prep_status_to is ConditionPrepStatus.READY
    assert public.plan_option is PlanOption.ALREADY_IN_FILE


async def test_the_summary_numbers_are_the_filters(db_session: AsyncSession) -> None:
    loan_file, _, conditions, actor = await _confirmed_round_one(db_session)
    await move_prep_status(
        db_session,
        condition=conditions["7086"],
        payload=PrepStatusRequest(to=ConditionPrepStatus.WAITING, waiting_on=OwnerHint.BORROWER),
        actor_user_id=actor,
    )
    summary = await condition_summary(db_session, loan_file_id=loan_file.id)
    assert summary.has_plan is True
    assert (summary.waiting_on_others, summary.your_tasks, summary.ready_to_send) == (1, 2, 1)

    client, headers = await _client_for(db_session, loan_file)
    async with client:
        base = f"/api/v1/loan-files/{loan_file.id}/conditions"
        open_ = [("lender_status", "open"), ("lender_status", "not_cleared")]

        async def codes(params: list[tuple[str, str]]) -> set[str]:
            response = await client.get(base, params=params, headers=headers)
            assert response.status_code == 200, response.text
            return {row["lender_code"] for row in response.json()}

        # S3-12's two tasks: 1582's invoice and 0007's (which waits on 1228).
        assert await codes([*open_, ("next_step", "i_will_do_it")]) == {"1582", "0007"}
        assert await codes([*open_, ("prep_status", "waiting")]) == {"7086"}
        assert await codes([*open_, ("prep_status", "ready")]) == {"0006"}

        body = (await client.get(f"{base}/summary", headers=headers)).json()
        assert (body["waiting_on_others"], body["your_tasks"], body["ready_to_send"]) == (1, 2, 1)
        assert body["has_plan"] is True

        # A task she marked done is no longer one: the count and the filter drop it together.
        (task,) = await _items(db_session, conditions["1582"])
        response = await client.patch(
            f"/api/v1/conditions/{conditions['1582'].id}/items/{task.id}",
            json={"status": "done"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["prep_status"] == "ready"
        assert await codes([*open_, ("next_step", "i_will_do_it")]) == {"0007"}
        body = (await client.get(f"{base}/summary", headers=headers)).json()
        assert (body["your_tasks"], body["ready_to_send"]) == (1, 2)

        # The route refuses done on an ask, with the sentence.
        ask = (await _items(db_session, conditions["6637"]))[0]
        response = await client.patch(
            f"/api/v1/conditions/{conditions['6637'].id}/items/{ask.id}",
            json={"status": "done"},
            headers=headers,
        )
        assert response.status_code == 409
        assert "Only your own tasks" in response.text


async def test_a_file_without_a_plan_keeps_stage_twos_bar(db_session: AsyncSession) -> None:
    loan_file, _ = await _file_with_round(db_session)
    summary = await condition_summary(db_session, loan_file_id=loan_file.id)
    assert summary.has_plan is False
    assert summary.your_tasks == 0


async def test_the_task_wording_comes_from_the_library(db_session: AsyncSession) -> None:
    loan_file, _, conditions, _ = await _confirmed_round_one(db_session)
    client, headers = await _client_for(db_session, loan_file)
    async with client:
        response = await client.get(
            f"/api/v1/loan-files/{loan_file.id}/conditions", headers=headers
        )
        rows = {row["lender_code"]: row for row in response.json()}
        assert [item["task"] for item in rows["1582"]["items"]] == ["upload the invoice"]
        assert all(item["task"] is None for item in rows["7086"]["items"])
        assert rows["7086"]["waiting_on"] is None

        # LP-942: an ask addressed to HER is her task, so re-pointing the option alone keeps it one.
        # (This test used to expect an ask with the processor as performer: an ask with no email.)
        (task,) = await _items(db_session, conditions["1582"])
        response = await client.patch(
            f"/api/v1/conditions/{conditions['1582'].id}/items/{task.id}",
            json={"option": "ask_third_party"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        (item,) = response.json()["items"]
        assert (item["option"], item["task"]) == ("i_will_do_it", "upload the invoice")

        # Re-pointed to an ask of someone ELSE, it is no longer her task and loses the wording.
        response = await client.patch(
            f"/api/v1/conditions/{conditions['1582'].id}/items/{task.id}",
            json={"option": "ask_third_party", "performers": ["other_party"]},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert [item["task"] for item in response.json()["items"]] == [None]
