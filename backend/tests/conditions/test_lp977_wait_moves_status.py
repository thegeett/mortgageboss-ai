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


async def _email_waiting_then_her_task_done(
    db_session: AsyncSession, others_status: ConditionItemStatus, by: str = "email"
) -> Any:
    """A condition code moved to Waiting on Title, with her own task marked done and every other task
    at `others_status`. `by` is what made the move: a sent email, or (LP-980 review) a mechanism added
    later, which must behave the same way because neither is a status she picked."""
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
                "by": by,
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
        other.status = others_status
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
    return condition


async def test_a_waiting_an_email_made_stays_while_its_ask_is_out(db_session: AsyncSession) -> None:
    """THE OTHER SIDE OF THE DISCRIMINATION (the LP-977 peer): a Waiting a sent email made is someone
    genuinely being waited on while the asked task is still out, so her own task being done does not
    move it.

    LP-980 — WHAT HOLDS THIS NOW IS `ready_because`, NOT THE WAITING RULE. `_waiting_moves_on` lets an
    email's Waiting through; the asked task is REQUESTED, not done, so `ready_because` refuses. A change
    to `ready_because` that fails this test is the place to look, not the Waiting rule."""
    condition = await _email_waiting_then_her_task_done(db_session, ConditionItemStatus.REQUESTED)
    assert _status(condition) is ConditionPrepStatus.WAITING


async def test_a_waiting_an_email_made_moves_on_once_nothing_is_asked(
    db_session: AsyncSession,
) -> None:
    """LP-980 — THE OWNER'S CHOICE (a). The email went out, then she found the document and marked the
    asked task done (or not needed): nobody is waited on any more, so "Waiting on Title" moves to Ready
    like any finished plan. This test asserted the opposite before LP-980 (same setup: every asked task
    off, her task done, the condition left at Waiting for good)."""
    condition = await _email_waiting_then_her_task_done(db_session, ConditionItemStatus.NOT_NEEDED)
    assert _status(condition) is ConditionPrepStatus.READY


async def test_marking_the_sent_ask_already_done_moves_it_on(db_session: AsyncSession) -> None:
    """LP-980 — THE OWNER'S CASE (a), through the door the button uses. 1947's email to Title went out
    (the ask is REQUESTED, the condition Waiting on Title); she finds the CD on the file and marks THAT
    task Already done, with how she knows. Nothing is waited on, so the condition is Ready."""
    from app.models.condition_item import ConditionItem

    condition = await _email_waiting_then_her_task_done(db_session, ConditionItemStatus.REQUESTED)
    assert _status(condition) is ConditionPrepStatus.WAITING, "the premise: the ask is out"
    asked = list(
        await db_session.scalars(
            select(ConditionItem).where(
                ConditionItem.condition_id == condition.id,
                ConditionItem.status == ConditionItemStatus.REQUESTED,
            )
        )
    )
    assert asked, "the premise: something is asked"
    from app.models.loan_file import LoanFile

    loan_file = await db_session.get(LoanFile, condition.loan_file_id)
    actor = await _actor(db_session, loan_file)
    for item in asked:
        await update_item(
            db_session,
            condition=condition,
            item=item,
            option=None,
            name=None,
            performers=None,
            due_date=None,
            actor_user_id=actor,
            status=ConditionItemStatus.DONE,
            note="Found the final CD on the file",
        )
    assert _status(condition) is ConditionPrepStatus.READY


async def test_a_waiting_no_person_chose_moves_on_whatever_made_it(
    db_session: AsyncSession,
) -> None:
    """LP-980 REVIEW — THE RULE IS "SHE DID NOT CHOOSE IT", NOT A LIST OF THE MECHANISMS.

    The Waiting rule read `by in ("wait", "email")`, and the LP-977 review had already taken that shape
    out of `condition_drafts` for the reason it fails: a mechanism the list does not name reads as a
    status SHE picked, so the condition sits at Waiting for ever with nothing left to wait on, and the
    event history cannot change to free it. `by: "reminder"` here stands for the next one added; today's
    two are covered by the tests above. Both callers now ask `condition_status.last_move_was_not_hers`.

    Its control is `test_a_waiting_she_set_herself_is_not_moved_on_by_the_plan`, where the move carries
    no `by` at all and the condition stays at Waiting.
    """
    condition = await _email_waiting_then_her_task_done(
        db_session, ConditionItemStatus.NOT_NEEDED, by="reminder"
    )
    assert _status(condition) is ConditionPrepStatus.READY


async def test_a_later_send_still_names_who_we_wait_on(db_session: AsyncSession) -> None:
    """LP-977 REVIEW — a wait's move left every later send unable to say who we are waiting on.

    The send renames `waiting_on` only when the condition is already Waiting on someone ELSE and
    `condition_drafts`' guard allows it. That guard asked whether the last move was a SEND, which was
    the same question as "is this ours to rename?" while only a send and her own hand could leave a
    condition at Waiting. A wait makes a third kind, so: wait on Title, then the borrower's email goes,
    and the row said "Waiting on Title" with the newest email in the borrower's inbox — permanently,
    because the event history does not change.

    The guard now asks whether the move carries a `by` at all: every code-made move has one and the
    move she makes by hand has none, so her own choice is still protected.
    """
    from app.models.condition_draft import ConditionDraft, DraftRecipient
    from app.models.condition_round import ConditionRound
    from app.models.condition_vocabulary import PlanOption
    from app.services.condition_drafts import mark_sent, resync_file
    from tests.conditions.test_condition_drafts import _people
    from tests.conditions.test_lp975_carried_plan_confirmed import _confirm

    loan_file, condition, actor = await _setup(db_session)
    await _people(db_session, loan_file)
    await db_session.flush()

    await _wait(db_session, condition, actor, Performer.TITLE)
    await db_session.flush()
    assert condition.waiting_on is OwnerHint.TITLE  # THE PREMISE: the wait named Title

    await add_item(
        db_session,
        condition=condition,
        name="the signed letter of explanation",
        performers=[Performer.BORROWER],
        option=PlanOption.ASK_BORROWER,
        actor_user_id=actor,
    )
    await resync_file(db_session, loan_file_id=loan_file.id, actor_user_id=actor)
    round_ = await db_session.get(ConditionRound, condition.last_seen_round_id)
    assert round_ is not None
    await _confirm(db_session, round_, loan_file, actor)
    draft = await db_session.scalar(
        select(ConditionDraft).where(
            ConditionDraft.loan_file_id == loan_file.id,
            ConditionDraft.recipient == DraftRecipient.BORROWER,
        )
    )
    assert draft is not None

    await mark_sent(db_session, loan_file=loan_file, draft=draft, actor_user_id=actor)
    await db_session.flush()

    assert condition.waiting_on is OwnerHint.BORROWER, (
        "the newest email went to the borrower, so that is who the row must name"
    )
    assert _status(condition) is ConditionPrepStatus.WAITING
