"""LP-968 — drafts when the plan is ready, nothing sent before confirm, and her edits to a task.

The owner, 2026-10-08: "go with drafting when the plan is ready". Round 1 of the fictional UWM file,
planned (`_planned_round_one`): 0132's reading needs her (0.64), so it is the condition the drafts must
leave out until she confirms it.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.models.condition import ConditionPrepStatus
from app.models.condition_draft import ConditionDraft
from app.models.condition_vocabulary import ConditionItemStatus, PlanOption
from app.services import condition_reading
from app.services.condition_drafts import DraftRefused, draft_ready_plan, mark_sent
from app.services.condition_plan import (
    PlanRefused,
    confirm_round_plan,
    follow_drafts,
    revert_to_suggested,
    set_next_step,
    update_item,
)
from app.services.condition_reading import ConfirmedItem, confirm_reading
from app.services.email_send import CannotSendError, send_draft
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.test_condition_plan import _actor, _conditions, _items, _planned_round_one


@pytest.fixture(autouse=True)
def _mocked_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())


async def _drafted(db: AsyncSession) -> tuple[Any, Any, dict[str, Any], Any]:
    loan_file, round_ = await _planned_round_one(db)
    await draft_ready_plan(db, round_id=round_.id)
    return loan_file, round_, await _conditions(db, loan_file), await _actor(db, loan_file)


async def _edit(db: AsyncSession, condition: Any, item: Any, actor: Any, **change: Any) -> None:
    await update_item(
        db,
        condition=condition,
        item=item,
        option=change.pop("option", None),
        name=None,
        performers=None,
        due_date=None,
        actor_user_id=actor,
        **change,
    )


# --------------------------------------------------------------------------------------------- #
# Drafts when the plan is ready
# --------------------------------------------------------------------------------------------- #


async def test_the_drafts_exist_as_soon_as_the_plan_is_ready(db_session: AsyncSession) -> None:
    loan_file, round_, conditions, _ = await _drafted(db_session)
    assert round_.plan_confirmed_at is None
    asks = list(await _items(db_session, conditions["7086"]))
    assert asks and all(i.draft_id is not None for i in asks if i.option is PlanOption.ASK_BORROWER)
    drafts = list(
        await db_session.scalars(
            select(ConditionDraft).where(ConditionDraft.loan_file_id == loan_file.id)
        )
    )
    assert drafts


async def test_a_reading_that_needs_her_is_not_drafted_until_she_confirms_it(
    db_session: AsyncSession,
) -> None:
    """README rule 3, which drafting at confirm kept by construction and drafting early must keep."""
    _, _, conditions, actor = await _drafted(db_session)
    pending = conditions["0132"]
    assert all(i.draft_id is None for i in await _items(db_session, pending))

    await confirm_reading(
        db_session,
        condition=pending,
        items=[
            ConfirmedItem(name=i.name, performers=(i.performer,), key=i.key)
            for i in await _items(db_session, pending)
        ],
        actor_user_id=actor,
    )
    await follow_drafts(db_session, condition=pending, actor_user_id=actor)
    asks = [i for i in await _items(db_session, pending) if i.option is PlanOption.ASK_THIRD_PARTY]
    assert asks and all(i.draft_id is not None for i in asks)


async def test_a_plan_edit_before_confirm_reaches_the_drafts(db_session: AsyncSession) -> None:
    _, _, conditions, actor = await _drafted(db_session)
    condition = conditions["1947"]
    (ask,) = [i for i in await _items(db_session, condition) if i.draft_id is not None]
    await _edit(
        db_session,
        condition,
        ask,
        actor,
        status=ConditionItemStatus.NOT_NEEDED,
        note="already in the closing package",
    )
    assert ask.draft_id is None


# --------------------------------------------------------------------------------------------- #
# Nothing is sent before confirm
# --------------------------------------------------------------------------------------------- #


async def _a_draft(db: AsyncSession, loan_file: Any) -> ConditionDraft:
    draft = await db.scalar(
        select(ConditionDraft).where(ConditionDraft.loan_file_id == loan_file.id).limit(1)
    )
    assert draft is not None
    return draft


async def test_no_door_sends_a_draft_before_the_plan_is_confirmed(db_session: AsyncSession) -> None:
    loan_file, _, _, actor = await _drafted(db_session)
    draft = await _a_draft(db_session, loan_file)
    # The general send door, which can reach a condition draft by its message id.
    with pytest.raises(CannotSendError, match="Confirm the plan for round 1 first"):
        await send_draft(
            db_session,
            loan_file=loan_file,
            draft_id=draft.communication_id,
            recipient="title@example.com",
            body="Hello",
            approver_user_id=actor,
        )
    # The conditions' own Mark sent goes through the same guard.
    from app.models.communication import Communication

    message = await db_session.get(Communication, draft.communication_id)
    assert message is not None
    message.recipient = "title@example.com"
    await db_session.flush()
    with pytest.raises((CannotSendError, DraftRefused), match="Confirm the plan"):
        await mark_sent(db_session, loan_file=loan_file, draft=draft, actor_user_id=actor)


async def test_once_confirmed_the_same_draft_sends(db_session: AsyncSession) -> None:
    """The positive control: the guard is the plan, not the draft."""
    loan_file, round_, conditions, actor = await _drafted(db_session)
    await confirm_reading(
        db_session,
        condition=conditions["0132"],
        items=[
            ConfirmedItem(name=i.name, performers=(i.performer,), key=i.key)
            for i in await _items(db_session, conditions["0132"])
        ],
        actor_user_id=actor,
    )
    await confirm_round_plan(db_session, round_=round_, actor_user_id=actor)
    draft = await _a_draft(db_session, loan_file)
    sent = await send_draft(
        db_session,
        loan_file=loan_file,
        draft_id=draft.communication_id,
        recipient="title@example.com",
        body="Hello",
        approver_user_id=actor,
    )
    assert sent.status.value != "draft"


# --------------------------------------------------------------------------------------------- #
# Her edits to a task
# --------------------------------------------------------------------------------------------- #


async def test_not_needed_needs_a_reason_and_keeps_it(db_session: AsyncSession) -> None:
    _, _, conditions, actor = await _drafted(db_session)
    condition = conditions["6378"]
    (task,) = await _items(db_session, condition)
    with pytest.raises(PlanRefused, match="Say why it isn't needed"):
        await _edit(db_session, condition, task, actor, status=ConditionItemStatus.NOT_NEEDED)
    await _edit(
        db_session,
        condition,
        task,
        actor,
        status=ConditionItemStatus.NOT_NEEDED,
        note="title confirmed by phone",
    )
    assert (task.status, task.plan_note) == (
        ConditionItemStatus.NOT_NEEDED,
        "title confirmed by phone",
    )

    # Undo clears her words with her mark.
    await _edit(db_session, condition, task, actor, status=ConditionItemStatus.OPEN)
    assert (task.status, task.plan_note) == (ConditionItemStatus.OPEN, None)


async def test_only_her_own_marks_can_be_set_back_to_open(db_session: AsyncSession) -> None:
    _, _, conditions, actor = await _drafted(db_session)
    condition = conditions["7086"]
    task = (await _items(db_session, condition))[0]
    task.status = ConditionItemStatus.REQUESTED  # the ask went out
    await db_session.flush()
    with pytest.raises(PlanRefused, match="Only a task you marked"):
        await _edit(db_session, condition, task, actor, status=ConditionItemStatus.OPEN)


async def test_doing_it_herself_takes_it_out_of_the_email_and_keeps_how(
    db_session: AsyncSession,
) -> None:
    _, _, conditions, actor = await _drafted(db_session)
    condition = conditions["1947"]
    (ask,) = [i for i in await _items(db_session, condition) if i.draft_id is not None]
    await _edit(
        db_session, condition, ask, actor, option=PlanOption.I_WILL_DO_IT, note="calling title"
    )
    assert (ask.option, ask.plan_note, ask.draft_id) == (
        PlanOption.I_WILL_DO_IT,
        "calling title",
        None,
    )


async def test_a_mark_before_confirm_moves_no_status(db_session: AsyncSession) -> None:
    """Drafts follow edits before confirm; status moves still wait for it (`_plan_in_force`)."""
    _, _, conditions, actor = await _drafted(db_session)
    condition = conditions["0006"]
    for task in await _items(db_session, condition):
        await _edit(
            db_session, condition, task, actor, status=ConditionItemStatus.DONE, note="on file"
        )
    assert condition.prep_status is ConditionPrepStatus.TO_DO


# --------------------------------------------------------------------------------------------- #
# Go back to the suggested plan
# --------------------------------------------------------------------------------------------- #


async def test_going_back_restores_the_suggested_steps_and_clears_her_notes(
    db_session: AsyncSession,
) -> None:
    _, _, conditions, actor = await _drafted(db_session)
    condition = conditions["6637"]
    first, second = (await _items(db_session, condition))[:2]
    suggested = (first.option, second.option, condition.next_step)
    await _edit(db_session, condition, first, actor, option=PlanOption.I_WILL_DO_IT, note="mine")
    await _edit(
        db_session,
        condition,
        second,
        actor,
        status=ConditionItemStatus.NOT_NEEDED,
        note="not this time",
    )
    await set_next_step(
        db_session, condition=condition, next_step=PlanOption.ASK_UNDERWRITER, actor_user_id=actor
    )

    changed = await revert_to_suggested(db_session, condition=condition, actor_user_id=actor)
    assert changed == 3
    assert (first.option, second.option, condition.next_step) == suggested
    assert second.status is ConditionItemStatus.OPEN
    assert (first.plan_note, second.plan_note) == (None, None)
    # Back in the email it came out of.
    assert first.draft_id is not None


async def test_going_back_never_unasks_a_sent_email(db_session: AsyncSession) -> None:
    _, _, conditions, actor = await _drafted(db_session)
    condition = conditions["7086"]
    task = (await _items(db_session, condition))[0]
    before = task.option
    await _edit(db_session, condition, task, actor, option=PlanOption.I_WILL_DO_IT)
    task.status = ConditionItemStatus.REQUESTED
    await db_session.flush()
    assert await revert_to_suggested(db_session, condition=condition, actor_user_id=actor) == 0
    assert task.option is PlanOption.I_WILL_DO_IT and task.option is not before


async def test_going_back_with_nothing_changed_changes_nothing(db_session: AsyncSession) -> None:
    _, _, conditions, actor = await _drafted(db_session)
    assert (
        await revert_to_suggested(db_session, condition=conditions["1947"], actor_user_id=actor)
        == 0
    )
