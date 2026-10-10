"""LP-977 — a "Wait for something" step moves the condition from To do to Waiting on its performer, the way
marking an email sent does, and names the owner by the email's own rule (`WAITING_ON`).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from app.models.condition import ConditionPrepStatus, OwnerHint
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_vocabulary import ConditionItemStatus, Performer
from app.schemas.condition import ConditionEventPublic
from app.services import condition_reading
from app.services.condition_plan import add_item, update_item
from app.services.conditions import condition_summary
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.test_condition_plan import _actor, _conditions, _planned_round_one

DUE = date(2026, 10, 15)


@pytest.fixture(autouse=True)
def _mocked_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())


async def _setup(db: AsyncSession) -> tuple[Any, Any, Any]:
    loan_file, _ = await _planned_round_one(db)
    condition = (await _conditions(db, loan_file))["1947"]
    assert condition.prep_status is ConditionPrepStatus.TO_DO  # THE PREMISE
    return loan_file, condition, await _actor(db, loan_file)


async def _wait(
    db: AsyncSession, condition: Any, actor: Any, who: Performer = Performer.TITLE
) -> Any:
    return await add_item(
        db,
        condition=condition,
        name="the payoff letter",
        performers=[who],
        option=None,
        actor_user_id=actor,
        waiting=True,
        due_date=DUE,
    )


def _status(condition: Any) -> ConditionPrepStatus:
    """Read without narrowing: the code under test changes it between two assertions."""
    status: ConditionPrepStatus = condition.prep_status
    return status


async def _moves(db: AsyncSession, condition: Any) -> list[ConditionEvent]:
    return list(
        await db.scalars(
            select(ConditionEvent).where(
                ConditionEvent.condition_id == condition.id,
                ConditionEvent.kind == ConditionEventKind.CONDITION_PREP_MOVED,
            )
        )
    )


async def test_a_wait_moves_to_do_to_waiting_on_its_person(db_session: AsyncSession) -> None:
    loan_file, condition, actor = await _setup(db_session)
    before = await condition_summary(db_session, loan_file_id=loan_file.id)

    await _wait(db_session, condition, actor)

    assert condition.prep_status is ConditionPrepStatus.WAITING
    assert condition.waiting_on is OwnerHint.TITLE
    (moved,) = await _moves(db_session, condition)
    assert moved.detail == {
        "prep_status_from": "to_do",
        "prep_status_to": "waiting",
        "waiting_on": "title",
        "by": "wait",
    }
    after = await condition_summary(db_session, loan_file_id=loan_file.id)
    assert after.waiting_on_others == before.waiting_on_others + 1


@pytest.mark.parametrize(
    ("who", "named"),
    [
        (Performer.BORROWER, OwnerHint.BORROWER),
        (Performer.TITLE, OwnerHint.TITLE),
        # Title and the attorney share one email, so a wait on either reads Title.
        (Performer.ATTORNEY, OwnerHint.TITLE),
        # The LO is the broker (M5), as a sent LO email reads.
        (Performer.LO, OwnerHint.BROKER),
        (Performer.LENDER, OwnerHint.LENDER),
        # Appraisal requests go through the lender.
        (Performer.APPRAISER, OwnerHint.LENDER),
        (Performer.HOA, OwnerHint.UNKNOWN),
        (Performer.EMPLOYER, OwnerHint.UNKNOWN),
    ],
)
async def test_who_it_names_is_the_sent_emails_rule(
    db_session: AsyncSession, who: Performer, named: OwnerHint
) -> None:
    _, condition, actor = await _setup(db_session)
    await _wait(db_session, condition, actor, who)
    assert condition.waiting_on is named


async def test_a_status_she_picked_is_never_moved(db_session: AsyncSession) -> None:
    _, condition, actor = await _setup(db_session)
    condition.prep_status = ConditionPrepStatus.READY
    await db_session.flush()
    await _wait(db_session, condition, actor)
    assert condition.prep_status is ConditionPrepStatus.READY
    assert await _moves(db_session, condition) == []


async def test_the_first_wait_names_who_and_a_second_does_not_move_it(
    db_session: AsyncSession,
) -> None:
    _, condition, actor = await _setup(db_session)
    await _wait(db_session, condition, actor, Performer.TITLE)
    await _wait(db_session, condition, actor, Performer.BORROWER)
    assert condition.waiting_on is OwnerHint.TITLE
    assert len(await _moves(db_session, condition)) == 1


async def test_not_needed_after_all_leaves_the_status(db_session: AsyncSession) -> None:
    _, condition, actor = await _setup(db_session)
    wait = await _wait(db_session, condition, actor)
    await update_item(
        db_session,
        condition=condition,
        item=wait,
        option=None,
        name=None,
        performers=None,
        due_date=None,
        actor_user_id=actor,
        status=ConditionItemStatus.NOT_NEEDED,
        note="Title emailed it already",
    )
    assert condition.prep_status is ConditionPrepStatus.WAITING


async def test_an_ordinary_task_does_not_move_it(db_session: AsyncSession) -> None:
    """THE CONTROL: only a wait moves the status; her own task added the same way does not."""
    _, condition, actor = await _setup(db_session)
    await add_item(
        db_session,
        condition=condition,
        name="Call the title company",
        performers=[Performer.PROCESSOR],
        option=None,
        actor_user_id=actor,
    )
    assert condition.prep_status is ConditionPrepStatus.TO_DO


async def test_the_history_says_a_wait_did_it(db_session: AsyncSession) -> None:
    _, condition, actor = await _setup(db_session)
    await _wait(db_session, condition, actor)
    (moved,) = await _moves(db_session, condition)
    assert ConditionEventPublic.from_model(moved).moved_by_wait is True
    # A move the email made says nothing about a wait.
    moved.detail = {**moved.detail, "by": "email", "recipient": "title_attorney"}
    assert ConditionEventPublic.from_model(moved).moved_by_wait is None


async def test_marking_the_wait_done_moves_it_on_as_it_would_have_from_to_do(
    db_session: AsyncSession,
) -> None:
    """THE REGRESSION THE PEER'S QUESTION FOUND. Before LP-977 a condition whose every task she marked
    done went To do → Ready (`apply_step_status`). Once the wait put it at Waiting, the plan's move only
    acted on To do, so marking the wait done left it at Waiting with nothing left to wait on."""
    from app.models.condition_item import ConditionItem

    loan_file, condition, actor = await _setup(db_session)
    # The plan's steps come into force only once she has confirmed it (`_plan_in_force`), and that
    # holds before LP-977 too: an unconfirmed To do does not move to Ready either.
    from app.models.condition_round import ConditionRound
    from tests.conditions.test_lp975_carried_plan_confirmed import _confirm

    round_ = await db_session.get(ConditionRound, condition.last_seen_round_id)
    assert round_ is not None
    await _confirm(db_session, round_, loan_file, actor)
    assert _status(condition) is ConditionPrepStatus.TO_DO  # still, after the confirm
    wait = await _wait(db_session, condition, actor)
    # Every other task off the plan, so the wait is the last thing between it and Ready.
    for other in await db_session.scalars(
        select(ConditionItem).where(
            ConditionItem.condition_id == condition.id,
            ConditionItem.deleted_at.is_(None),
            ConditionItem.id != wait.id,
        )
    ):
        other.status = ConditionItemStatus.NOT_NEEDED
    await db_session.flush()
    assert _status(condition) is ConditionPrepStatus.WAITING

    await update_item(
        db_session,
        condition=condition,
        item=wait,
        option=None,
        name=None,
        performers=None,
        due_date=None,
        actor_user_id=actor,
        status=ConditionItemStatus.DONE,
    )
    assert condition.prep_status is ConditionPrepStatus.READY


async def test_a_waiting_she_set_herself_is_not_moved_on_by_the_plan(
    db_session: AsyncSession,
) -> None:
    """THE CONTROL: "never overrides a move she made herself" (`apply_step_status`) still holds for a
    Waiting she picked, so the fix is about the wait's own move only."""
    from app.models.condition_item import ConditionItem

    loan_file, condition, actor = await _setup(db_session)
    # The plan's steps come into force only once she has confirmed it (`_plan_in_force`), and that
    # holds before LP-977 too: an unconfirmed To do does not move to Ready either.
    from app.models.condition_round import ConditionRound
    from tests.conditions.test_lp975_carried_plan_confirmed import _confirm

    round_ = await db_session.get(ConditionRound, condition.last_seen_round_id)
    assert round_ is not None
    await _confirm(db_session, round_, loan_file, actor)
    assert _status(condition) is ConditionPrepStatus.TO_DO  # still, after the confirm
    condition.prep_status = ConditionPrepStatus.WAITING
    condition.waiting_on = OwnerHint.TITLE
    await db_session.flush()
    mine = await add_item(
        db_session,
        condition=condition,
        name="Upload the CD",
        performers=[Performer.PROCESSOR],
        option=None,
        actor_user_id=actor,
    )
    for other in await db_session.scalars(
        select(ConditionItem).where(
            ConditionItem.condition_id == condition.id,
            ConditionItem.deleted_at.is_(None),
            ConditionItem.id != mine.id,
        )
    ):
        other.status = ConditionItemStatus.NOT_NEEDED
    await db_session.flush()
    await update_item(
        db_session,
        condition=condition,
        item=mine,
        option=None,
        name=None,
        performers=None,
        due_date=None,
        actor_user_id=actor,
        status=ConditionItemStatus.DONE,
    )
    assert condition.prep_status is ConditionPrepStatus.WAITING


async def test_a_waiting_an_email_made_is_not_moved_on_by_the_plan(
    db_session: AsyncSession,
) -> None:
    """THE OTHER SIDE OF THE DISCRIMINATION (the LP-977 peer). The rule is "the WAIT made this Waiting",
    not "Waiting may advance": a Waiting a sent email made is the lender's side genuinely waiting on
    someone, and must not advance when her tasks are done. Fails if the `by` values drift, if the
    latest-move lookup changes, or if the branch is widened to a set of statuses."""
    from app.models.condition_item import ConditionItem
    from app.models.condition_round import ConditionRound
    from app.services.condition_status import _event as status_event
    from tests.conditions.test_lp975_carried_plan_confirmed import _confirm

    loan_file, condition, actor = await _setup(db_session)
    round_ = await db_session.get(ConditionRound, condition.last_seen_round_id)
    assert round_ is not None
    await _confirm(db_session, round_, loan_file, actor)
    condition.prep_status = ConditionPrepStatus.WAITING
    condition.waiting_on = OwnerHint.TITLE
    db_session.add(
        status_event(
            condition,
            ConditionEventKind.CONDITION_PREP_MOVED,
            {
                "prep_status_from": "to_do",
                "prep_status_to": "waiting",
                "waiting_on": "title",
                "by": "email",
                "recipient": "title_attorney",
            },
            actor_user_id=actor,
        )
    )
    await db_session.flush()
    mine = await add_item(
        db_session,
        condition=condition,
        name="Upload the CD",
        performers=[Performer.PROCESSOR],
        option=None,
        actor_user_id=actor,
    )
    for other in await db_session.scalars(
        select(ConditionItem).where(
            ConditionItem.condition_id == condition.id,
            ConditionItem.deleted_at.is_(None),
            ConditionItem.id != mine.id,
        )
    ):
        other.status = ConditionItemStatus.NOT_NEEDED
    await db_session.flush()
    await update_item(
        db_session,
        condition=condition,
        item=mine,
        option=None,
        name=None,
        performers=None,
        due_date=None,
        actor_user_id=actor,
        status=ConditionItemStatus.DONE,
    )
    assert _status(condition) is ConditionPrepStatus.WAITING
