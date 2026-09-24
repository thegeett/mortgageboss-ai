"""The AI structure split (LP-908, spec §LP-908).

⚠️ THE MODEL IS MOCKED IN EVERY TEST HERE, AND WHAT IS BEING TESTED IS THE CODE AROUND IT. The spec's
done-when has two halves and both are about OUR validation rather than the model's skill: an
unstructured paste of the six round-2 conditions splits into six rows with EXACT wording, and a
response containing text that is not in the input is REJECTED.

That second half is the whole safety property. "AI only splits" cannot be enforced by asking a model
nicely; it is enforced because every `verbatim` it returns is checked against the input by code, and
anything else is dropped.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from app.ai.client import AIClientError, AICompletion
from app.ai.cost import estimate_cost
from app.conditions.readers.model import AI_SPLIT_CONFIDENCE
from app.models.condition import BucketKind
from app.models.condition_round import ConditionSheetFormat
from app.services import condition_split as split_module
from app.services.condition_split import ConditionSplitUnavailable, split_conditions

#: The six round-2 conditions with their codes and headings stripped — spec §8 step 6's input.
ROUND_2_TEXTS = [
    "Final inspection is required (and possibly a Change of Circumstance) to confirm the following "
    "has been completed: being completed to match the plans and specs provided. (On new "
    "construction transactions this condition can be moved to closing at the request of the client.)",
    "TC: Title to provide final Seller Closing Disclosure with final closing package",
    "Provide a copy of the Third Party Processing Invoice.",
    "Provide copy of invoice for credit report.",
    "Provide copy of invoice for final inspection.",
    "TC: Title company to include lender loan number on all checks sent to lender.",
]
UNSTRUCTURED = "\n".join(ROUND_2_TEXTS)


def _reply(payload: dict[str, Any], **usage: int) -> AICompletion:
    return AICompletion(
        text=json.dumps(payload),
        input_tokens=usage.get("input_tokens", 1200),
        output_tokens=usage.get("output_tokens", 400),
        model="claude-haiku-4-5",
        stop_reason="end_turn",
        cache_read_tokens=usage.get("cache_read_tokens", 0),
        cache_write_tokens=usage.get("cache_write_tokens", 0),
    )


def _mock(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], **usage: int) -> AsyncMock:
    mock = AsyncMock(return_value=_reply(payload, **usage))
    monkeypatch.setattr(split_module, "complete", mock)
    return mock


async def test_six_conditions_split_with_exact_wording(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec §LP-908's done-when, first half — and §8 step 6's acceptance."""
    _mock(
        monkeypatch,
        {
            "conditions": [
                {"verbatim": t, "code": None, "bucket_heading": None} for t in ROUND_2_TEXTS
            ],
            "ignored": [],
        },
    )

    outcome = await split_conditions(UNSTRUCTURED)

    assert len(outcome.sheet.rows) == 6
    assert [row.verbatim_text for row in outcome.sheet.rows] == ROUND_2_TEXTS
    assert outcome.rejected == 0
    assert outcome.sheet.unassigned_lines == []
    assert outcome.sheet.sheet_format is ConditionSheetFormat.PASTED_TEXT


async def test_text_that_is_not_in_the_input_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ SPEC §LP-908's DONE-WHEN, SECOND HALF, AND THE SAFETY PROPERTY OF THE WHOLE TICKET.

    "AI only splits" is not enforceable by instruction. It is enforced here: a model that
    paraphrases, summarises, tidies or invents cannot get that text into `verbatim_text`, because
    the string is checked against the input and dropped when it is not found.
    """
    _mock(
        monkeypatch,
        {
            "conditions": [
                {"verbatim": ROUND_2_TEXTS[3], "code": None, "bucket_heading": None},
                # Plausible, helpful, adjacent to the real one — and never written by the lender.
                {
                    "verbatim": "Provide a copy of the invoice for the credit report fee.",
                    "code": None,
                    "bucket_heading": None,
                },
            ],
            "ignored": [],
        },
    )

    outcome = await split_conditions(UNSTRUCTURED)

    assert [row.verbatim_text for row in outcome.sheet.rows] == [ROUND_2_TEXTS[3]]
    assert outcome.rejected == 1
    assert any("not found in the text you pasted" in w for w in outcome.sheet.warnings)
    # ⚠️ The dropped string is NOT in the warning. It is text the MODEL produced — the one thing here
    # most likely to be wrong, and it could contain anything (spec §9.5).
    assert all("credit report fee" not in w for w in outcome.sheet.warnings)


async def test_the_same_span_returned_twice_yields_one_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⚠️ A PER-ROW CHECK PASSES A DUPLICATE TWICE OVER, because substring-ness says nothing about
    the relationship BETWEEN rows. Both copies are genuinely in the input.

    Nothing downstream would remove them either: rule 6's duplicate dedup lives in the READER, and
    this path never touches it — so two identical conditions would reach the review screen at
    confidence 0.6 with no way to tell they came from one demand. Claiming a SPAN makes the second
    copy impossible: the stretch of sheet it needs is already taken.
    """
    _mock(
        monkeypatch,
        {
            "conditions": [
                {"verbatim": ROUND_2_TEXTS[3], "code": None, "bucket_heading": None},
                {"verbatim": ROUND_2_TEXTS[3], "code": None, "bucket_heading": None},
            ],
            "ignored": [],
        },
    )

    outcome = await split_conditions(UNSTRUCTURED)

    assert [row.verbatim_text for row in outcome.sheet.rows] == [ROUND_2_TEXTS[3]]
    assert outcome.rejected == 1


async def test_a_row_assembled_from_two_distant_fragments_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⚠️ THE REASON THE CHECK IS NOT `in`. Every word below appears in the input — just never
    together. A membership test on the joined text would accept this; claiming a contiguous span
    cannot, because no such stretch of the sheet exists."""
    stitched = "Provide copy of invoice for credit report. TC: Title company to include lender"
    _mock(
        monkeypatch,
        {
            "conditions": [{"verbatim": stitched, "code": None, "bucket_heading": None}],
            "ignored": [],
        },
    )

    outcome = await split_conditions(UNSTRUCTURED)

    assert outcome.sheet.rows == []
    assert outcome.rejected == 1


async def test_a_span_crossing_a_real_boundary_leaves_the_rest_unassigned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⚠️ THE AI'S MOST NATURAL ERROR ON UNSTRUCTURED TEXT, and the one every per-row check misses.

    The tail of one condition plus the head of the next IS a contiguous substring, reads as
    plausible prose, and is a demand the lender never made. It passes the span claim — correctly, it
    is real text — so what catches it is the PARTITION: the genuine conditions either side can no
    longer claim their own spans, and everything they could not take is reported as unassigned
    instead of vanishing. Line-based coverage would have called this accounted for, since both lines
    are covered, just cut in the wrong place.
    """
    text = f"{ROUND_2_TEXTS[3]}\n{ROUND_2_TEXTS[4]}"
    crossing = "for credit report. Provide copy of invoice for final"
    _mock(
        monkeypatch,
        {
            "conditions": [{"verbatim": crossing, "code": None, "bucket_heading": None}],
            "ignored": [],
        },
    )

    outcome = await split_conditions(text)

    assert [row.verbatim_text for row in outcome.sheet.rows] == [crossing]
    # Neither real condition survived intact, and both remnants are on screen rather than lost.
    assert outcome.sheet.unassigned_lines == ["Provide copy of invoice", "inspection."]


async def test_a_wrapped_condition_rejoined_by_the_model_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⚠️ WHY THE CHECK COLLAPSES WHITESPACE ON BOTH SIDES. A sheet prints one condition across
    several lines; the model returns it as one. A literal `in` test would call the correct answer an
    invention and drop the row — rejecting the model for being right."""
    wrapped = "Provide a copy of the\n    Third Party Processing Invoice."
    _mock(
        monkeypatch,
        {
            "conditions": [
                {
                    "verbatim": "Provide a copy of the Third Party Processing Invoice.",
                    "code": None,
                    "bucket_heading": None,
                }
            ],
            "ignored": [],
        },
    )

    outcome = await split_conditions(wrapped)

    assert len(outcome.sheet.rows) == 1
    assert outcome.rejected == 0


async def test_tidied_capitalisation_is_still_a_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⚠️ CASE IS NOT FOLDED, DELIBERATELY. The lender's capitalisation is part of the wording, and a
    check that ignored it would admit a model that "improved" a sentence into `verbatim_text`."""
    _mock(
        monkeypatch,
        {
            "conditions": [
                {
                    "verbatim": "provide copy of invoice for credit report.",
                    "code": None,
                    "bucket_heading": None,
                }
            ],
            "ignored": [],
        },
    )

    outcome = await split_conditions(UNSTRUCTURED)

    assert outcome.sheet.rows == []
    assert outcome.rejected == 1


async def test_ai_rows_are_flagged_below_the_review_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """0.6, so the review screen sorts them first and demands the flagged-rows checkbox. It is not a
    claim that the WORDING is uncertain — that is exact or the row does not exist."""
    _mock(
        monkeypatch,
        {
            "conditions": [{"verbatim": ROUND_2_TEXTS[2], "code": None, "bucket_heading": None}],
            "ignored": [],
        },
    )

    outcome = await split_conditions(UNSTRUCTURED)

    assert outcome.sheet.rows[0].confidence == AI_SPLIT_CONFIDENCE
    assert AI_SPLIT_CONFIDENCE < 0.8


async def test_a_code_keeps_its_leading_zeros(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-407: `0006` is an identifier printed on a document, not the integer 6."""
    text = f"0006  {ROUND_2_TEXTS[3]}"
    _mock(
        monkeypatch,
        {
            "conditions": [
                {"verbatim": ROUND_2_TEXTS[3], "code": "0006", "bucket_heading": "Closing (PTF)"}
            ],
            "ignored": [],
        },
    )

    outcome = await split_conditions(text)

    assert outcome.sheet.rows[0].lender_code == "0006"
    assert outcome.sheet.rows[0].bucket_heading == "Closing (PTF)"


async def test_the_bucket_is_never_interpreted(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ THE HEADING IS CARRIED, THE KIND IS NOT DERIVED. Reading "Closing (PTF)" as
    PRIOR_TO_FUNDING is interpretation, and this module does not interpret — LP-906's mapping applies
    only to layouts we recognise. The review screen asks the processor instead."""
    _mock(
        monkeypatch,
        {
            "conditions": [
                {
                    "verbatim": ROUND_2_TEXTS[3],
                    "code": None,
                    "bucket_heading": "Prior to Funding",
                }
            ],
            "ignored": [],
        },
    )

    outcome = await split_conditions(UNSTRUCTURED)

    assert outcome.sheet.rows[0].bucket_heading == "Prior to Funding"
    assert outcome.sheet.rows[0].bucket_kind is BucketKind.UNKNOWN


async def test_a_line_the_split_did_not_account_for_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§9.2: nothing is silently dropped. A line in neither a condition, a heading nor `ignored`
    reaches the review screen as unassigned."""
    text = f"{ROUND_2_TEXTS[3]}\nSomething nobody accounted for at all."
    _mock(
        monkeypatch,
        {
            "conditions": [{"verbatim": ROUND_2_TEXTS[3], "code": None, "bucket_heading": None}],
            "ignored": [],
        },
    )

    outcome = await split_conditions(text)

    assert outcome.sheet.unassigned_lines == ["Something nobody accounted for at all."]


async def test_page_furniture_the_model_ignored_is_not_unassigned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other side: a line the model put in `ignored` IS accounted for, so it is not reported
    twice."""
    text = f"Page 1 of 2\n{ROUND_2_TEXTS[3]}"
    _mock(
        monkeypatch,
        {
            "conditions": [{"verbatim": ROUND_2_TEXTS[3], "code": None, "bucket_heading": None}],
            "ignored": ["Page 1 of 2"],
        },
    )

    outcome = await split_conditions(text)

    assert outcome.sheet.unassigned_lines == []


async def test_the_model_being_unreachable_is_a_typed_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⚠️ NEVER AN EMPTY SHEET. "The model could not be reached" and "this page had no conditions on
    it" lead a processor to different actions, and returning [] for both makes the first
    indistinguishable from the second (spec §9.8)."""
    monkeypatch.setattr(split_module, "complete", AsyncMock(side_effect=AIClientError("boom")))

    with pytest.raises(ConditionSplitUnavailable) as failed:
        await split_conditions(UNSTRUCTURED)

    assert "could not be read automatically" in failed.value.detail


async def test_junk_instead_of_json_is_a_typed_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        split_module,
        "complete",
        AsyncMock(
            return_value=AICompletion(
                text="I'm afraid I can't help with that.",
                input_tokens=10,
                output_tokens=10,
                model="claude-haiku-4-5",
            )
        ),
    )

    with pytest.raises(ConditionSplitUnavailable):
        await split_conditions(UNSTRUCTURED)


async def test_an_empty_split_is_reported_rather_than_looking_successful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid response with no conditions is a legitimate answer — and it must say so, or a round
    with nothing on it reads as a sheet that was read cleanly."""
    _mock(monkeypatch, {"conditions": [], "ignored": ["Page 1 of 2"]})

    outcome = await split_conditions("Page 1 of 2")

    assert outcome.sheet.rows == []
    assert any("found no conditions" in w for w in outcome.sheet.warnings)


async def test_the_cost_counts_cached_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ `input_tokens` ALONE UNDERCOUNTS, and `AICompletion` says so in its own docstring: on a
    cached call it is the UNCACHED REMAINDER. A cost built from it excludes the prompt that was
    cached — the LP-628 bug, one layer down."""
    _mock(
        monkeypatch,
        {
            "conditions": [{"verbatim": ROUND_2_TEXTS[3], "code": None, "bucket_heading": None}],
            "ignored": [],
        },
        input_tokens=100,
        cache_read_tokens=5000,
        cache_write_tokens=2000,
    )

    outcome = await split_conditions(UNSTRUCTURED)

    # ⚠️ COMPARED AGAINST THE UNCACHED FIGURE, BECAUSE `> 0` CANNOT FAIL. An earlier version of this
    # test asserted only that the cost was positive — which stays true with the cache fields zeroed,
    # since `input_tokens` alone is already non-zero. A mutation run that dropped
    # `cache_read_tokens` from the call left all 14 tests passing. A guard with no failure mode is
    # the fault this ticket's review has now caught twice; this one fails if the cached halves are
    # ever dropped again.
    uncached = estimate_cost(model="claude-haiku-4-5", input_tokens=100, output_tokens=400)
    expected = estimate_cost(
        model="claude-haiku-4-5",
        input_tokens=100,
        output_tokens=400,
        cache_read_tokens=5000,
        cache_write_tokens=2000,
    )

    assert outcome.cost_estimate == expected
    assert outcome.cost_estimate > uncached
    assert outcome.model == "claude-haiku-4-5"


async def test_the_model_never_receives_more_than_the_pasted_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⚠️ SPEC §9.4: NO AI CALL RECEIVES THE LOAN SNAPSHOT. The only user content is the text itself
    — no borrower, no property, no stated financials — and this asserts the call's arguments rather
    than trusting the module not to have added any."""
    mock = _mock(
        monkeypatch,
        {
            "conditions": [{"verbatim": ROUND_2_TEXTS[3], "code": None, "bucket_heading": None}],
            "ignored": [],
        },
    )

    await split_conditions(UNSTRUCTURED)

    kwargs = mock.await_args.kwargs
    assert kwargs["messages"] == [{"role": "user", "content": UNSTRUCTURED}]
    assert kwargs["temperature"] == 0.0
    # The tier setting, never a hard-coded model id (spec §LP-908).
    from app.core.config import settings

    assert kwargs["model"] == settings.anthropic_model_extraction
