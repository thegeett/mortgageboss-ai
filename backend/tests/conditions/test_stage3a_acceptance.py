"""Stage 3A acceptance (build prompt §6): round 1 of the fictional UWM file produces plan §6's table.

With the AI MOCKED (`reading_fixture`), round 1 must produce exactly:
- the items and who acts on each, and the proposed option per code (§6's table);
- three drafts (borrower: 7086, 6132, 6637; title/attorney: 6637, 0132, 1947, 6378; LO: 0132), plus
  the push-back to the underwriter on 6178;
- 1582 and 0007 as her tasks (0007 waits on 1228), 0006 already in the file (the credit invoice of
  07/15, page 1), 6178 a push-back, 1228 "Lender is doing it", and 0132 needing confirmation at 0.64.

Marking the three drafts sent moves exactly those conditions to Waiting on the right owner. The same
plan comes out with the AI switched off (library fallback, every reading marked to confirm), and after
round 2 is imported the six conditions seen again keep their plan.

The table below is written from plan §6 by hand, not from the code's output.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from app.models.condition import (
    Condition,
    ConditionPrepStatus,
    ConditionReadingStatus,
    OwnerHint,
)
from app.models.condition_item import ConditionItem
from app.models.condition_round import ConditionRound, ConditionSourceKind
from app.models.condition_vocabulary import ConditionItemStatus, PlanOption
from app.models.document import Document
from app.models.loan_file import LoanFile
from app.services import condition_reading
from app.services.condition_drafts import mark_sent
from app.services.condition_import import import_round
from app.services.condition_plan import build_plan, confirm_round_plan, round_plan_blockers
from app.services.condition_reading import ConfirmedItem, confirm_reading, read_round
from app.services.condition_rounds import SheetBytes, create_round_from_sheet
from app.tasks.conditions import parse_round
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.fixture_helpers import UWM_ROUND_2
from tests.conditions.reading_fixture import fake_complete
from tests.conditions.test_condition_drafts import _drafts, _people
from tests.conditions.test_condition_plan import _actor, _conditions, _credit_invoice, _items
from tests.conditions.test_condition_reading import _file_with_round
from tests.conditions.uwm_pdf_fixture import render_uwm_pdf

ASK_B = PlanOption.ASK_BORROWER
ASK_3P = PlanOption.ASK_THIRD_PARTY

#: Plan §6, by code: the condition's own step, and each item as (key, who acts, option).
#: "who acts" is the performers list; `lender_doing_it` for 1228's inspection is the item's step.
SECTION_6: dict[str, tuple[PlanOption | None, list[tuple[str, list[str], PlanOption]]]] = {
    # Final inspection → the appraiser, through the lender's AMC: the lender is doing it. LP-954 (the
    # owner, superseding §6 for this row): "possibly a Change of Circumstance" is an item for the LO
    # (re-disclosure), asked in the LO email, so the condition's items carry their own steps.
    "1228": (
        None,
        [
            ("inspection", ["appraiser"], PlanOption.LENDER_DOING_IT),
            ("change_of_circumstance", ["lo"], ASK_3P),
        ],
    ),
    # $27,148.22 more in assets, 2 months of statements → borrower. Ask the borrower.
    "7086": (None, [("statements", ["borrower"], ASK_B), ("other_accounts", ["borrower"], ASK_B)]),
    # The next month's statement → borrower.
    "6132": (None, [("statement", ["borrower"], ASK_B)]),
    # Source → borrower · receipt → title/escrow · clearance → borrower. Borrower + title emails.
    "6637": (
        None,
        [
            ("source", ["borrower"], ASK_B),
            ("receipt", ["title"], ASK_3P),
            ("clearance", ["borrower"], ASK_B),
        ],
    ),
    # → none, closing is on or after 09/30. Push back. (The item is dropped, not asked.)
    "6178": (PlanOption.PUSH_BACK, [("declarations", ["insurance"], ASK_3P)]),
    # Re-signed disclosure → borrower + LO · approved attorney → LO · wire instructions → attorney.
    "0132": (
        None,
        [
            ("disclosure", ["borrower", "lo"], ASK_3P),
            ("attorney", ["lo"], ASK_3P),
            ("wire_instructions", ["attorney"], ASK_3P),
        ],
    ),
    # → title. Title email (prior to funding).
    "1947": (None, [("seller_cd", ["title"], ASK_3P)]),
    # → you. I'll do it.
    "1582": (None, [("invoice", ["processor"], PlanOption.I_WILL_DO_IT)]),
    # → you. Already in the file (credit invoice 07/15, page 1).
    "0006": (None, [("invoice", ["processor"], PlanOption.ALREADY_IN_FILE)]),
    # → you, after 1228. I'll do it, waits on 1228.
    "0007": (None, [("invoice", ["processor"], PlanOption.I_WILL_DO_IT)]),
    # → title (information to pass on). Added to the title email.
    "6378": (None, [("instruction", ["title"], ASK_3P)]),
}


@pytest.fixture(autouse=True)
def _mocked_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())


async def _round_one(db: AsyncSession, *, use_ai: bool) -> tuple[LoanFile, ConditionRound]:
    loan_file, round_ = await _file_with_round(db)
    await _credit_invoice(db, loan_file)
    await _people(db, loan_file)
    await read_round(db, round_id=round_.id, use_ai=use_ai)
    await build_plan(db, round_id=round_.id, today=date(2026, 8, 28))
    return loan_file, round_


async def _plan(db: AsyncSession, loan_file: LoanFile) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for code, condition in (await _conditions(db, loan_file)).items():
        items = await _items(db, condition)
        out[code] = (
            condition.next_step,
            [(i.key, list(i.performers), i.option) for i in items],
        )
    return out


async def test_round_one_is_plan_section_6(db_session: AsyncSession) -> None:
    loan_file, round_ = await _round_one(db_session, use_ai=True)
    assert await _plan(db_session, loan_file) == SECTION_6

    conditions = await _conditions(db_session, loan_file)
    items = {code: await _items(db_session, c) for code, c in conditions.items()}

    # 7086's arithmetic, by code: $38,210.40 required less $11,062.18 verified = $27,148.22.
    shortfall = conditions["7086"].reading["figures"]["shortfall"]
    assert Decimal(shortfall["required"]) - Decimal(shortfall["verified"]) == Decimal("27148.22")
    assert Decimal(shortfall["amount"]) == Decimal("27148.22")

    # 0007 waits on 1228; 0006 is the credit invoice of 07/15, page 1; 6178's item is not asked.
    (waits,) = items["0007"]
    assert waits.waits_on_condition_id == conditions["1228"].id
    (in_file,) = items["0006"]
    document = await db_session.get(Document, in_file.document_id)
    assert document is not None and document.document_name == "Credit invoice 07/15"
    assert (in_file.document_page, in_file.status) == (1, ConditionItemStatus.DONE)
    assert [i.status for i in items["6178"]] == [ConditionItemStatus.NOT_NEEDED]
    assert conditions["6178"].reading["push_back"] == {
        "must_not_close_before": "2026-09-30",
        "policy_starts": "2026-09-30",
    }

    # 0132 needs her at 0.64, and nothing else does; the plan cannot be confirmed past it.
    needing = {
        code
        for code, c in conditions.items()
        if c.reading_status is ConditionReadingStatus.NEEDS_CONFIRMATION
    }
    assert needing == {"0132"}
    assert conditions["0132"].reading_confidence == Decimal("0.64")
    assert await round_plan_blockers(db_session, round_=round_) == ["0132"]

    # No condition is left without a plan.
    for code, condition in conditions.items():
        live = [i for i in items[code] if i.status is not ConditionItemStatus.NOT_NEEDED]
        assert condition.next_step is not None or live, code


async def test_confirming_makes_the_three_drafts_and_the_question(db_session: AsyncSession) -> None:
    loan_file, round_ = await _round_one(db_session, use_ai=True)
    actor = await _actor(db_session, loan_file)
    conditions = await _conditions(db_session, loan_file)
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

    drafts = await _drafts(db_session, loan_file)
    assert set(drafts) == {"borrower", "title_attorney", "lo", "question 6178"}

    async def codes(key: str) -> set[str]:
        rows = (
            await db_session.execute(
                select(Condition.lender_code)
                .join(ConditionItem, ConditionItem.condition_id == Condition.id)
                .where(ConditionItem.draft_id == drafts[key][0].id)
            )
        ).scalars()
        return {code or "" for code in rows}

    assert await codes("borrower") == {"7086", "6132", "6637"}
    assert await codes("title_attorney") == {"6637", "0132", "1947", "6378"}
    assert await codes("lo") == {"0132", "1228"}  # LP-954: 1228's re-disclosure

    # Two of her own tasks, one already in the file (now Ready), 1228 the lender's.
    tasks = {
        code
        for code, c in conditions.items()
        if any(i.option is PlanOption.I_WILL_DO_IT for i in await _items(db_session, c))
    }
    assert tasks == {"1582", "0007"}
    assert conditions["0006"].prep_status is ConditionPrepStatus.READY
    # LP-954: the inspection is still the lender's; the re-disclosure is the LO's.
    assert conditions["1228"].next_step is None
    assert (await _items(db_session, conditions["1228"]))[0].option is PlanOption.LENDER_DOING_IT

    # Marking the THREE drafts sent moves exactly those conditions, to the right owner.
    for key in ("borrower", "title_attorney", "lo"):
        await mark_sent(db_session, loan_file=loan_file, draft=drafts[key][0], actor_user_id=actor)
    waiting = {
        code: c.waiting_on
        for code, c in conditions.items()
        if c.prep_status is ConditionPrepStatus.WAITING
    }
    assert waiting == {
        "7086": OwnerHint.BORROWER,
        "6132": OwnerHint.BORROWER,
        "6637": OwnerHint.BORROWER,
        "0132": OwnerHint.BROKER,  # "Waiting on LO"
        "1947": OwnerHint.TITLE,
        "6378": OwnerHint.TITLE,
        "1228": OwnerHint.BROKER,  # LP-954: the LO's re-disclosure
    }
    # 6178 waits for its own question; the lender's track has not moved anywhere.
    assert conditions["6178"].prep_status is ConditionPrepStatus.TO_DO
    assert {c.lender_status.value for c in conditions.values()} == {"open"}


async def test_the_same_plan_with_the_ai_switched_off(db_session: AsyncSession) -> None:
    loan_file, round_ = await _round_one(db_session, use_ai=False)
    # WITHOUT THE AI NOBODY READS 1228'S CLAUSES: the library's PA-03 alone, the lender's, as §6 had it.
    # The reading is marked for her to confirm (below), which is where the re-disclosure is added.
    library_only = {
        **SECTION_6,
        "1228": (
            PlanOption.LENDER_DOING_IT,
            [("inspection", ["appraiser"], PlanOption.LENDER_DOING_IT)],
        ),
    }
    assert await _plan(db_session, loan_file) == library_only
    conditions = await _conditions(db_session, loan_file)
    # Library fallback: every reading is marked for her to confirm, and nothing is drafted past them.
    assert {c.reading_status for c in conditions.values()} == {
        ConditionReadingStatus.NEEDS_CONFIRMATION
    }
    assert len(await round_plan_blockers(db_session, round_=round_)) == 11


async def test_round_two_keeps_the_plan_for_the_six_seen_again(db_session: AsyncSession) -> None:
    loan_file, _ = await _round_one(db_session, use_ai=True)
    before = await _plan(db_session, loan_file)

    round_2 = await create_round_from_sheet(
        db_session,
        loan_file=loan_file,
        sheet=SheetBytes(
            content=render_uwm_pdf(UWM_ROUND_2), source_kind=ConditionSourceKind.PDF_UPLOAD
        ),
    )
    await db_session.flush()
    await parse_round(db_session, round_2.id)
    await db_session.refresh(round_2)
    await import_round(db_session, round_=round_2)
    await read_round(db_session, round_id=round_2.id)
    await build_plan(db_session, round_id=round_2.id)

    conditions = await _conditions(db_session, loan_file)
    seen_again = {c.lender_code for c in conditions.values() if c.last_seen_round_id == round_2.id}
    seen_again.discard(None)
    assert len(seen_again) == 6
    after = await _plan(db_session, loan_file)
    for code in seen_again:
        assert after[code] == before[code], code
