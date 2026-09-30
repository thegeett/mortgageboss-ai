"""LP-946: an item with more than one performer is asked of each of them.

Every outside performer gets the ask in their own draft; she gets a task only if "you" is one of the
performers; the item shows where each part went. One reading kept from plan §6 (the Stage 3A
acceptance): the LO relays to the borrower, so `[borrower, lo]` is one ask, in the LO's email.
"""

from __future__ import annotations

from typing import Any

from app.models.communication import Communication, CommunicationStatus
from app.models.condition import Condition
from app.models.condition_item import ConditionItem
from app.models.condition_vocabulary import ConditionItemStatus, Performer, PlanOption
from app.models.loan_file import LoanFile
from app.services.condition_drafts import mark_sent
from app.services.condition_plan import add_item, items_public_for_file, recipient_for, update_item
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.test_condition_drafts import _confirmed, _drafts


async def _live(db: AsyncSession, condition: Condition) -> list[ConditionItem]:
    return list(
        (
            await db.execute(
                select(ConditionItem)
                .where(
                    ConditionItem.condition_id == condition.id, ConditionItem.deleted_at.is_(None)
                )
                .order_by(ConditionItem.sequence, ConditionItem.created_at)
            )
        ).scalars()
    )


async def _in_draft(
    db: AsyncSession, loan_file: LoanFile, recipient: str, item: ConditionItem
) -> bool:
    draft, _ = (await _drafts(db, loan_file))[recipient]
    return item.draft_id == draft.id


async def _edit(
    db: AsyncSession,
    condition: Condition,
    item: ConditionItem,
    performers: list[Performer],
    actor: Any,
) -> None:
    await update_item(
        db,
        condition=condition,
        item=item,
        option=PlanOption.ASK_BORROWER,
        name=None,
        performers=performers,
        due_date=None,
        actor_user_id=actor,
    )


async def test_borrower_and_you_is_the_borrowers_ask_and_her_task(db_session: AsyncSession) -> None:
    """THE OWNER'S TEST: the ask is in the borrower email AND she has her own task."""
    db = db_session
    loan_file, _, conditions, actor = await _confirmed(db)
    six = conditions["6132"]
    (item,) = await _live(db, six)
    await _edit(db, six, item, [Performer.BORROWER, Performer.PROCESSOR], actor)

    parent, part = await _live(db, six)
    assert parent.id == item.id and part.part_of_item_id == item.id
    assert (parent.performers, parent.option) == (["borrower"], PlanOption.ASK_BORROWER)
    assert await _in_draft(db, loan_file, "borrower", parent)
    assert (part.performers, part.option) == (["processor"], PlanOption.I_WILL_DO_IT)
    assert part.draft_id is None and recipient_for(part) is None
    # The item shows where each part went: the part carries its link to the item.
    rows = (await items_public_for_file(db, loan_file_id=loan_file.id))[six.id]
    assert [r.part_of_item_id for r in rows] == [None, item.id]


async def test_each_outside_performer_gets_their_own_draft(db_session: AsyncSession) -> None:
    db = db_session
    loan_file, _, conditions, actor = await _confirmed(db)
    six = conditions["6132"]
    (item,) = await _live(db, six)
    await _edit(db, six, item, [Performer.BORROWER, Performer.TITLE], actor)
    parent, part = await _live(db, six)
    assert await _in_draft(db, loan_file, "borrower", parent)
    assert part.option is PlanOption.ASK_THIRD_PARTY
    assert await _in_draft(db, loan_file, "title_attorney", part)


async def test_the_lo_relays_to_the_borrower(db_session: AsyncSession) -> None:
    """Plan §6's reading, kept: 0132's disclosure is [borrower, lo], ONE ask, in the LO's email."""
    db = db_session
    loan_file, _, conditions, _ = await _confirmed(db)
    items = await _live(db, conditions["0132"])
    disclosure = next(i for i in items if i.key == "disclosure")
    assert disclosure.performers == ["borrower", "lo"]
    assert not [i for i in items if i.part_of_item_id is not None]
    assert await _in_draft(db, loan_file, "lo", disclosure)


async def test_a_re_edit_re_splits(db_session: AsyncSession) -> None:
    db = db_session
    _, _, conditions, actor = await _confirmed(db)
    six = conditions["6132"]
    (item,) = await _live(db, six)
    await _edit(db, six, item, [Performer.BORROWER, Performer.PROCESSOR], actor)
    assert len(await _live(db, six)) == 2
    await _edit(db, six, item, [Performer.BORROWER], actor)
    assert [i.id for i in await _live(db, six)] == [item.id]


async def test_an_added_item_for_two_people_is_split(db_session: AsyncSession) -> None:
    db = db_session
    loan_file, _, conditions, actor = await _confirmed(db)
    six = conditions["6132"]
    added = await add_item(
        db,
        condition=six,
        name="Signed letter about the account",
        performers=[Performer.BORROWER, Performer.PROCESSOR],
        option=PlanOption.ASK_BORROWER,
        actor_user_id=actor,
    )
    parts = [i for i in await _live(db, six) if i.part_of_item_id == added.id]
    assert [(p.performers, p.option) for p in parts] == [(["processor"], PlanOption.I_WILL_DO_IT)]
    assert await _in_draft(db, loan_file, "borrower", added)


async def test_a_part_whose_ask_went_out_survives_a_re_edit(db_session: AsyncSession) -> None:
    """LP-946 review: a part whose email was SENT is the record of a request that went out. A re-edit
    keeps it (LP-940: a sent draft keeps its items), and does not split the same part out again."""
    db = db_session
    loan_file, _, conditions, actor = await _confirmed(db)
    six = conditions["6132"]
    (item,) = await _live(db, six)
    await _edit(db, six, item, [Performer.BORROWER, Performer.TITLE], actor)
    _, part = await _live(db, six)
    draft, _ = (await _drafts(db, loan_file))["title_attorney"]
    await mark_sent(db, loan_file=loan_file, draft=draft, actor_user_id=actor)
    await db.refresh(part)
    # THE PREMISE, so this cannot quietly stop exercising the case: the part was asked, in a sent draft.
    assert part.status is ConditionItemStatus.REQUESTED and part.draft_id == draft.id
    assert await _is_sent(db, draft)

    await _edit(db, six, item, [Performer.BORROWER], actor)
    await db.refresh(part)
    assert part.deleted_at is None and part.draft_id == draft.id
    assert [i.id for i in await _live(db, six)] == [item.id, part.id]

    # Asking title again does not make a second title part beside the one that went out.
    await _edit(db, six, item, [Performer.BORROWER, Performer.TITLE], actor)
    assert [i.id for i in await _live(db, six)] == [item.id, part.id]


async def _is_sent(db: AsyncSession, draft: Any) -> bool:
    message = await db.get(Communication, draft.communication_id)
    return message is not None and message.status is CommunicationStatus.SENT
