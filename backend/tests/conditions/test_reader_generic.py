"""The fallback reader for layouts nobody has taught us (LP-906 section 3, spec §6).

⚠️ `needs_ai` IS THE ASSERTION THAT MATTERS HERE, and it is not a failure flag. It means the RULES
could not split this text, so LP-908 must — and LP-908 only ever SPLITS, never interprets. Setting it
when structure WAS found would pay for an AI call to redo work the rules already did; failing to set
it when there is none would hand LP-909 a single undifferentiated blob and call it a condition.
"""

from __future__ import annotations

from app.conditions.readers import lines_from_text, read_generic
from app.models.condition import BucketKind
from app.models.condition_round import ConditionSheetFormat


def test_a_numbered_list_is_structure() -> None:
    """Spec: `^\\s*(\\d{1,4})[.)]\\s+`. Both `1.` and `2)` are list markers on real pastes."""
    sheet = read_generic(
        lines_from_text("1. Provide the final settlement statement.\n2) Provide the signed note.")
    )

    assert sheet.sheet_format is ConditionSheetFormat.GENERIC
    assert [r.lender_code for r in sheet.rows] == ["1", "2"]
    assert sheet.rows[0].verbatim_text == "Provide the final settlement statement."
    assert sheet.needs_ai is False


def test_lender_style_leading_codes_are_structure() -> None:
    """A four-digit code then the text — the shape UWM prints, pasted without its letterhead."""
    sheet = read_generic(
        lines_from_text(
            " 0006         Provide copy of invoice for credit report.\n"
            " 0007         Provide copy of invoice for final inspection."
        )
    )

    assert [r.lender_code for r in sheet.rows] == ["0006", "0007"]
    assert sheet.rows[0].verbatim_text == "Provide copy of invoice for credit report."
    assert sheet.needs_ai is False
    # ⚠️ The leading zeros survive. `0006` is an identifier printed on a document (ADR-407); reading
    # it as the integer 6 is a silent loss that surfaces later as a failed match.
    assert sheet.rows[0].lender_code == "0006"


def test_paragraphs_without_numbers_still_need_ai() -> None:
    """⚠️ PARAGRAPH SPLITTING IS NOT THE SAME AS FINDING STRUCTURE.

    Blank lines do separate these into three rows, and the spec lists blank-line paragraphs as a
    signal — but none carries a number or a code, so the rules have not actually identified where a
    condition begins. They guessed from whitespace. `needs_ai` says so rather than presenting the
    guess as a rule-read result.
    """
    sheet = read_generic(
        lines_from_text(
            "Provide the appraisal report.\n\nProvide the title commitment.\n\nProvide insurance."
        )
    )

    assert len(sheet.rows) == 3
    assert all(r.lender_code is None for r in sheet.rows)
    assert sheet.needs_ai is True


def test_prose_with_no_structure_at_all_needs_ai() -> None:
    sheet = read_generic(
        lines_from_text("Please send over whatever you have for this file when you get a chance.")
    )

    assert sheet.needs_ai is True
    assert len(sheet.rows) == 1


def test_empty_input_needs_ai_rather_than_raising() -> None:
    """An unreadable paste must degrade to "the AI splits it", never to a 500."""
    sheet = read_generic(lines_from_text(""))

    assert sheet.rows == []
    assert sheet.needs_ai is True
    assert sheet.warnings == ["nothing to read"]


def test_nothing_is_dropped_whichever_branch_runs() -> None:
    """§9.2 applies to an unknown layout exactly as it does to a known one: every non-blank line
    ends up in a row. The kind stays UNKNOWN because an unknown layout's words mean nothing yet."""
    text = "1. First condition.\nContinued on a second line.\n2. Second condition."
    sheet = read_generic(lines_from_text(text))

    joined = " ".join(r.verbatim_text for r in sheet.rows)
    for fragment in ("First condition.", "Continued on a second line.", "Second condition."):
        assert fragment in joined
    assert all(r.bucket_kind is BucketKind.UNKNOWN for r in sheet.rows)
