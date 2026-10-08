"""LP-954 — the reading keeps every clause (item 13 of the 2026-09-30 staging trial).

1228's text: "Final inspection is required (and possibly a Change of Circumstance) to confirm …". The
trial's reading summed it up as "Final inspection required to confirm construction completion", dropping
the clause that means the LO may have to re-disclose. Now each clause becomes an item or an explicit
no-action note, a conditional clause nothing covers puts the reading below the confidence bar, and
1228's "possibly a Change of Circumstance" is an item for the LO.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from app.conditions.library import load_library
from app.core.config import settings
from app.models.condition import Condition, ConditionReadingStatus
from app.models.condition_item import ConditionItem
from app.models.condition_vocabulary import PlanOption
from app.services import condition_reading
from app.services.condition_lender import set_file_lender
from app.services.condition_plan import build_plan
from app.services.condition_reading import compose_reading, read_round, uncovered_conditionals
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.reading_fixture import CANNED, fake_complete
from tests.conditions.test_lp949_lender_on_the_file import _by_code, _file_without_lender

TEXT_1228 = (
    "Final inspection is required (and possibly a Change of Circumstance) to confirm the following has "
    "been completed: being completed to match the plans and specs provided. (On new construction "
    "transactions this condition can be moved to closing at the request of the client.)"
)
BAR = Decimal(str(settings.condition_reading_confidence_bar))


def _ai(**overrides: Any) -> dict[str, Any]:
    return {**CANNED["1228"], **overrides}


def _compose(ai: dict[str, Any] | None) -> tuple[dict[str, Any], Any, Any, Any]:
    condition = Condition(verbatim_text=TEXT_1228, lender_code="1228", underwriter_notes=[])
    return compose_reading(
        condition, condition_type=load_library().get("PA-03"), ai=ai, round_=None
    )


# --------------------------------------------------------------------------------------------- #
# The check, by code
# --------------------------------------------------------------------------------------------- #


def test_every_conditional_clause_covered_is_nothing_uncovered() -> None:
    items = [{"key": "inspection"}, {"key": "change_of_circumstance"}]
    assert uncovered_conditionals(TEXT_1228, _ai(), items) == []


def test_a_dropped_conditional_clause_is_reported_in_the_lenders_words() -> None:
    ai = _ai(clauses=[c for c in CANNED["1228"]["clauses"] if "possibly" not in c["text"]])
    [missed] = uncovered_conditionals(TEXT_1228, ai, [{"key": "inspection"}])
    assert "possibly a Change of Circumstance" in missed


def test_a_note_covers_a_clause_that_asks_nothing() -> None:
    ai = _ai(
        clauses=[
            {"text": "possibly a Change of Circumstance", "item_key": None, "note": "Informs."}
        ]
    )
    assert uncovered_conditionals(TEXT_1228, ai, [{"key": "inspection"}]) == []


@pytest.mark.parametrize(
    "clause",
    [
        # Points at an item the reading does not have.
        {"text": "possibly a Change of Circumstance", "item_key": "nonexistent", "note": None},
        # Quotes words the lender never wrote.
        {"text": "possibly a new appraisal", "item_key": "inspection", "note": None},
        # Neither an item nor a note.
        {"text": "possibly a Change of Circumstance", "item_key": None, "note": "  "},
    ],
)
def test_a_clause_that_does_not_really_cover_it_does_not_count(clause: dict[str, Any]) -> None:
    assert uncovered_conditionals(TEXT_1228, _ai(clauses=[clause]), [{"key": "inspection"}])


@pytest.mark.parametrize(
    "text",
    [
        "Provide a W2 (if applicable), Final Paystub, or a Written Verification of Employment.",
        "Short funds to close and/or reserves.",
    ],
)
def test_each_conditional_word_is_found(text: str) -> None:
    assert uncovered_conditionals(text, {"clauses": []}, [])


# --------------------------------------------------------------------------------------------- #
# The reading
# --------------------------------------------------------------------------------------------- #


def test_1228_keeps_the_library_item_and_adds_the_los_re_disclosure() -> None:
    reading, _, status, confidence = _compose(_ai())
    assert [(i["key"], i["performers"]) for i in reading["items"]] == [
        ("inspection", ["appraiser"]),
        ("change_of_circumstance", ["lo"]),
    ]
    assert reading["uncovered"] == []
    assert status is ConditionReadingStatus.READY and confidence >= BAR


def test_dropping_the_clause_puts_the_reading_below_the_bar() -> None:
    ai = _ai(
        items=[{"key": "inspection", "performers": ["appraiser"], "specifics": {}}],
        clauses=[c for c in CANNED["1228"]["clauses"] if "possibly" not in c["text"]],
    )
    reading, _, status, confidence = _compose(ai)
    assert status is ConditionReadingStatus.NEEDS_CONFIRMATION
    assert confidence is not None and confidence < BAR
    assert any("possibly a Change of Circumstance" in u for u in reading["uncovered"])
    assert [i["key"] for i in reading["items"]] == ["inspection"]


def test_an_added_item_never_replaces_a_library_item() -> None:
    ai = _ai(
        items=[
            {"key": "inspection", "performers": ["appraiser"], "specifics": {}},
            {"key": "inspection", "name": "Something else", "performers": ["borrower"]},
            {"key": "change_of_circumstance", "performers": ["lo"], "specifics": {}},
        ]
    )
    reading, *_ = _compose(ai)
    assert [i["key"] for i in reading["items"]] == ["inspection", "change_of_circumstance"]
    assert reading["items"][0]["performers"] == ["appraiser"]


# --------------------------------------------------------------------------------------------- #
# End to end, on a UWM file
# --------------------------------------------------------------------------------------------- #


async def test_1228_on_a_uwm_file_asks_the_lo_and_leaves_the_inspection_to_the_lender(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(condition_reading, "complete", fake_complete())
    loan_file, round_ = await _file_without_lender(db_session)
    await set_file_lender(
        db_session, loan_file=loan_file, lender_key="uwm", lender_id=None, actor_user_id=None
    )
    await read_round(db_session, round_id=round_.id)
    await build_plan(db_session, round_id=round_.id)
    condition = (await _by_code(db_session, loan_file))["1228"]
    items = list(
        await db_session.scalars(
            select(ConditionItem)
            .where(ConditionItem.condition_id == condition.id)
            .order_by(ConditionItem.sequence)
        )
    )
    assert [(i.key, i.performer.value, i.option) for i in items] == [
        ("inspection", "appraiser", PlanOption.LENDER_DOING_IT),
        ("change_of_circumstance", "lo", PlanOption.ASK_THIRD_PARTY),
    ]
    assert condition.next_step is None
    assert condition.plan_reason == "Ordered through the lender — confirm on your files"


# --------------------------------------------------------------------------------------------- #
# LP-954 REVIEW: the guard's floor — a real quote, saying more than the word
# --------------------------------------------------------------------------------------------- #


def test_an_echo_of_the_conditional_word_does_not_cover_it() -> None:
    """The guard's BOUNDARY, not its happy path (LP-954 review).

    It must catch the two failures that matter — a dropped clause and a quote the lender never wrote —
    and must not be satisfied by quoting the conditional word back with any item key attached, which
    would make a READY reading out of a clause nobody covered. The last two rows are the positive
    control: a real clause, covered by an item or by a note, still reads as covered.
    """
    from app.services.condition_reading import uncovered_conditionals

    text = "Final inspection is required (and possibly a Change of Circumstance) to confirm completion."
    items = [{"key": "inspection"}]
    clause = "and possibly a Change of Circumstance"

    def uncovered(clauses: list[dict[str, str]]) -> bool:
        return uncovered_conditionals(text, {"clauses": clauses}, items) != []

    assert uncovered([]) is True  # the drop this guard exists to catch
    assert (
        uncovered([{"text": "possibly a Letter of Explanation", "item_key": "inspection"}]) is True
    )
    assert (
        uncovered([{"text": "possibly", "item_key": "inspection"}]) is True
    )  # an echo, not a clause
    assert uncovered([{"text": "possibly", "note": "x"}]) is True
    assert uncovered([{"text": clause, "item_key": "inspection"}]) is False
    assert uncovered([{"text": clause, "note": "the LO re-discloses"}]) is False
