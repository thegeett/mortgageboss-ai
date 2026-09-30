"""LP-942: no ask ends up with no destination.

Before LP-942 three performers could be asked and had no email: the processor, the lender and the
appraiser, so their asks reached no draft. Now:
- **You (the processor):** the ask is her own task ("I'll do it").
- **The lender:** the lender's draft for the round, addressed from the lender's contacts.
- **The appraiser:** never drafted to the appraiser. Appraiser independence means loan production staff
  do not contact the appraiser directly, so the ask goes into the LENDER's draft, and the item says
  "Appraisal requests go through the lender".
"""

from __future__ import annotations

import pytest
from app.models.condition_item import ConditionItem
from app.models.condition_vocabulary import Performer, PlanOption
from app.models.lender_contact import LenderContact, LenderContactRole
from app.models.loan_file import LoanFile
from app.services.condition_plan import (
    APPRAISAL_VIA_LENDER,
    build_plan,
    items_public_for_file,
    recipient_for,
    route_ask,
    update_item,
)
from app.services.condition_reading import read_round
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.test_condition_drafts import _confirmed, _drafts
from tests.conditions.test_condition_reading import _file_with_round

_ASKS = (PlanOption.ASK_BORROWER, PlanOption.ASK_THIRD_PARTY)


async def _items(db: AsyncSession, loan_file: LoanFile) -> list[ConditionItem]:
    return list(
        (
            await db.execute(
                select(ConditionItem).where(
                    ConditionItem.loan_file_id == loan_file.id, ConditionItem.deleted_at.is_(None)
                )
            )
        ).scalars()
    )


def _stranded(items: list[ConditionItem]) -> list[str]:
    return [
        f"{i.key} ({i.performers})" for i in items if i.option in _ASKS and recipient_for(i) is None
    ]


@pytest.mark.parametrize("performer", list(Performer))
@pytest.mark.parametrize("option", _ASKS)
def test_every_performer_asked_has_a_destination(performer: Performer, option: PlanOption) -> None:
    """The rule, for every performer the vocabulary has: after routing, an ask has an email, or it is
    her task. A performer added later without a route fails here."""
    item = ConditionItem(performer=performer, performers=[performer.value], option=option)
    route_ask(item)
    assert recipient_for(item) is not None or item.option is PlanOption.I_WILL_DO_IT


def test_the_three_that_had_none() -> None:
    def routed(performer: Performer) -> ConditionItem:
        item = ConditionItem(
            performer=performer, performers=[performer.value], option=PlanOption.ASK_THIRD_PARTY
        )
        route_ask(item)
        return item

    assert routed(Performer.PROCESSOR).option is PlanOption.I_WILL_DO_IT
    assert recipient_for(routed(Performer.LENDER)) == ("lender", "Lender")
    # Never the appraiser's own email: the lender's.
    assert recipient_for(routed(Performer.APPRAISER)) == ("lender", "Lender")


async def test_no_ask_on_round_one_is_stranded(db_session: AsyncSession) -> None:
    loan_file, _, _, _ = await _confirmed(db_session)
    items = await _items(db_session, loan_file)
    assert any(i.option in _ASKS for i in items)  # the positive control
    assert _stranded(items) == []


async def test_no_ask_on_the_page_break_sheet_is_stranded(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import condition_reading
    from tests.conditions.reading_fixture import fake_complete

    monkeypatch.setattr(condition_reading, "complete", fake_complete())
    loan_file, round_ = await _file_with_round(db_session, "uwm_master_pagebreak.txt")
    await read_round(db_session, round_id=round_.id)
    await build_plan(db_session, round_id=round_.id)
    items = await _items(db_session, loan_file)
    assert items  # the positive control: the sheet was planned
    assert _stranded(items) == []


async def test_an_appraisal_request_goes_to_the_lenders_draft(db_session: AsyncSession) -> None:
    """An item re-pointed to the appraiser lands in ONE lender draft for the round, addressed to the
    lender's account executive, and the item says why it is not the appraiser's."""
    db = db_session
    loan_file, _, conditions, actor = await _confirmed(db)
    assert loan_file.lender_id is not None
    db.add(
        LenderContact(
            lender_id=loan_file.lender_id,
            name="Dana Okafor",
            email="dana.okafor@example.com",
            role=LenderContactRole.ACCOUNT_EXECUTIVE,
        )
    )
    condition = conditions["1947"]
    (item,) = (
        await db.execute(select(ConditionItem).where(ConditionItem.condition_id == condition.id))
    ).scalars()
    await update_item(
        db,
        condition=condition,
        item=item,
        option=PlanOption.ASK_THIRD_PARTY,
        name=None,
        performers=[Performer.APPRAISER],
        due_date=None,
        actor_user_id=actor,
    )
    drafts = await _drafts(db, loan_file)
    assert "lender" in drafts
    draft, message = drafts["lender"]
    assert item.draft_id == draft.id
    assert message.recipient == "Dana Okafor <dana.okafor@example.com>"
    public = await items_public_for_file(db, loan_file_id=loan_file.id)
    (row,) = public[condition.id]
    assert row.route_note == APPRAISAL_VIA_LENDER
    # A lender ask joins the SAME draft: one per round.
    other = conditions["6378"]
    (second,) = (
        await db.execute(select(ConditionItem).where(ConditionItem.condition_id == other.id))
    ).scalars()
    await update_item(
        db,
        condition=other,
        item=second,
        option=PlanOption.ASK_THIRD_PARTY,
        name=None,
        performers=[Performer.LENDER],
        due_date=None,
        actor_user_id=actor,
    )
    lender_drafts = [k for k in await _drafts(db, loan_file) if k == "lender"]
    assert lender_drafts == ["lender"] and second.draft_id == draft.id
    (plain,) = (await items_public_for_file(db, loan_file_id=loan_file.id))[other.id]
    assert plain.route_note is None  # only the appraiser's ask carries the line
