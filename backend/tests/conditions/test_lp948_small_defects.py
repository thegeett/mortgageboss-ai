"""LP-948: four small defects, one test group each (the fourth is in `test_insurance_wiring.py`).

(a) The draft dialog names items by their labels, never their internal keys.
(b) Matching a PDF to a round: the lender code first, then the wording, and a tie is ASKED, not picked.
(c) A withdrawn condition's items are not returned by the file's item query.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.conditions.fingerprint import fingerprint
from app.conditions.readers.model import ParsedRow, ParsedSheet
from app.models.condition import BucketKind, Condition
from app.models.condition_item import ConditionItem
from app.models.condition_round import ConditionRoundStatus, ConditionSheetFormat
from app.models.condition_vocabulary import Performer, PlanOption
from app.services import condition_withdraw
from app.services.condition_drafts import condition_label, item_words
from app.services.condition_enrich import EnrichResult, _merge_conditions, _merge_draft_rows
from app.services.condition_plan import add_item, items_public_for_file
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.conditions.test_condition_drafts import _confirmed
from tests.conditions.test_condition_withdraw import _hand_added
from tests.conditions.test_round_enrich import _pasted_round

SAME = "Provide the final signed Closing Disclosure for the departing residence."
OTHER = "Provide the most recent two months of bank statements for all accounts."


# --------------------------------------------------------------------------------------------- #
# (a) labels, never keys
# --------------------------------------------------------------------------------------------- #


def _item(key: str, name: str) -> Any:
    return ConditionItem(key=key, name=name, performers=["borrower"])


def test_an_item_is_named_by_its_label_else_its_name_never_its_key() -> None:
    earnest: Any = Condition(canonical_type_id="AS-04", lender_code="6637", bucket_kind=None)
    assert item_words(earnest, _item("receipt", "Receipt of the deposit")) == (
        "earnest money receipt"  # the library label
    )
    # A re-ask and a part (LP-946) have keys no reader should see; their own name is used.
    assert item_words(earnest, _item("reask_3f2a9b1c", "Updated statement")) == (
        "updated statement"
    )
    # A part of a library item reads as the library item, never with its figure.
    assert item_words(earnest, _item("source.title", "Source of the $2,850.00")) == (
        "source of the earnest money"
    )
    # A library item whose own name carries its figure is named by the library's wording.
    assert item_words(earnest, _item("source", "Source of the $2,850.00")) == (
        "source of the earnest money"
    )


def test_the_partial_label_carries_no_key() -> None:
    earnest: Any = Condition(canonical_type_id="AS-04", lender_code="6637", bucket_kind=None)
    label = condition_label(
        earnest,
        [
            _item("source.title", "Source of the earnest money"),
            _item("reask_3f2a9b1c", "Clearance"),
        ],
    )
    assert label == "Earnest money: source of the earnest money and clearance"
    assert "reask" not in label and "." not in label


# --------------------------------------------------------------------------------------------- #
# (b) the code, then the wording, and a tie is a question
# --------------------------------------------------------------------------------------------- #


def _pdf_row(sequence: int, code: str | None, text: str) -> ParsedRow:
    return ParsedRow(
        sequence=sequence,
        lender_code=code,
        lender_category=None,
        bucket_heading="Prior to Docs",
        bucket_kind=BucketKind.PRIOR_TO_DOCS,
        verbatim_text=text,
    )


def _pasted(sequence: int, code: str | None, text: str) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "lender_code": code,
        "verbatim_text": text,
        "bucket_heading": "",
        "bucket_kind": "unknown",
    }


def _merge_rows(pasted: list[dict[str, Any]], pdf: list[ParsedRow]) -> tuple[Any, EnrichResult]:
    round_: Any = SimpleNamespace(draft_rows=pasted)
    result = EnrichResult(round_=round_)
    _merge_draft_rows(
        round_, ParsedSheet(sheet_format=ConditionSheetFormat.UWM_APPROVAL_LETTER, rows=pdf), result
    )
    return round_, result


def test_the_lender_code_decides_before_the_wording() -> None:
    """A code the PDF prints that one pasted row carries decides it, even when the wording differs
    and another row's wording matches exactly."""
    round_, result = _merge_rows(
        [_pasted(1, "5868", OTHER), _pasted(2, None, SAME)], [_pdf_row(1, "5868", SAME)]
    )
    by_seq = {row["sequence"]: row for row in round_.draft_rows}
    assert by_seq[1]["bucket_kind"] == "prior_to_docs"  # the code's row was filled
    assert by_seq[2]["bucket_kind"] == "unknown"  # the wording's row was not
    assert result.added == 0 and result.questions == []


def test_a_tie_is_asked_not_picked() -> None:
    """Two pasted rows read the same, with no code: neither PDF row may pick one. Each is a question,
    nothing is filled or added, and neither pasted row is reported as missing from the PDF."""
    round_, result = _merge_rows(
        [_pasted(3, None, SAME), _pasted(5, None, SAME), _pasted(6, None, OTHER)],
        [_pdf_row(1, "5868", SAME), _pdf_row(2, "7383", SAME), _pdf_row(3, "0006", OTHER)],
    )
    assert result.questions == [
        "Which pasted condition is the PDF's 5868? Conditions 3 and 5 read the same. "
        "Nothing was filled for it; set the code on the right one.",
        "Which pasted condition is the PDF's 7383? Conditions 3 and 5 read the same. "
        "Nothing was filled for it; set the code on the right one.",
    ]
    codes = {row["sequence"]: row["lender_code"] for row in round_.draft_rows}
    assert codes == {1: None, 2: None, 3: "0006"}  # re-sequenced; only the unique row filled
    assert result.added == 0 and result.unmatched_existing == []
    # The positive control: the unique row really matched.
    assert result.matched == 1


async def test_a_tie_on_an_imported_round_is_asked_not_picked(db_session: AsyncSession) -> None:
    db = db_session
    round_, _ = await _pasted_round(db)
    made = []
    for sequence in (3, 5):
        condition = Condition(
            company_id=round_.company_id,
            loan_file_id=round_.loan_file_id,
            first_round_id=round_.id,
            last_seen_round_id=round_.id,
            sequence=sequence,
            lender_code=None,
            bucket_heading="",
            bucket_kind=BucketKind.UNKNOWN,
            verbatim_text=SAME,
            text_fingerprint=fingerprint(SAME),
            underwriter_notes=[],
        )
        db.add(condition)
        made.append(condition)
    round_.status = ConditionRoundStatus.IMPORTED
    await db.flush()

    result = EnrichResult(round_=round_)
    sheet = ParsedSheet(
        sheet_format=ConditionSheetFormat.UWM_APPROVAL_LETTER,
        rows=[_pdf_row(1, "5868", SAME), _pdf_row(2, "7383", SAME)],
    )
    await _merge_conditions(db, round_, sheet, result)

    assert len(result.questions) == 2 and "Conditions 3 and 5" in result.questions[0]
    assert [c.lender_code for c in made] == [None, None]  # neither was picked
    assert result.added == 0 and result.unmatched_existing == []
    rows = (await db.execute(select(Condition).where(Condition.first_round_id == round_.id))).all()
    assert len(rows) == 2  # nothing added


# --------------------------------------------------------------------------------------------- #
# (c) a withdrawn condition's items
# --------------------------------------------------------------------------------------------- #


async def test_a_withdrawn_conditions_items_are_not_returned(db_session: AsyncSession) -> None:
    db = db_session
    loan_file, _, _, actor = await _confirmed(db)
    added = await _hand_added(db, loan_file, actor)
    await add_item(
        db,
        condition=added,
        name="Signed invoice",
        performers=[Performer.BORROWER],
        option=PlanOption.ASK_BORROWER,
        actor_user_id=actor,
    )
    # The positive control: before the withdrawal, its items are there.
    assert added.id in await items_public_for_file(db, loan_file_id=loan_file.id)

    await condition_withdraw.withdraw(
        db, condition=added, reason="Entered twice", actor_user_id=actor
    )
    assert added.id not in await items_public_for_file(db, loan_file_id=loan_file.id)
