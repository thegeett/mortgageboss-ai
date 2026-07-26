"""LP-334 — the live calibration harness: keyless plumbing + a flag-gated live seam.

The KEYLESS tests (always run, no key, no cost) prove the harness scores + records the per-case detail
that makes a failure inspectable, and that a correct abstention is not counted as a failure. The LIVE
seam runs the REAL model — gated on an EXPLICIT env flag (never the mere presence of a key), so normal CI
never makes a paid call even on a machine that has ANTHROPIC_API_KEY set.
"""

from __future__ import annotations

import os

import pytest
from app.verification.eval.live_calibration import (
    LabeledDoc,
    calibrate,
    failing_cases,
    format_report,
    summarize,
)
from app.verification.tag_materialization.ai import (
    AiGroupResult,
    AiSubjectJudgment,
    AiTagJudgment,
    Reasoner,
)

pytestmark = pytest.mark.anyio


def _stub(short_name: str, value: str, *, conf: float | None = 0.9) -> Reasoner:
    """A keyless reasoner returning one tag value for the single-subject (index 1) calibration doc."""

    async def _r(_context_json: str) -> AiGroupResult:
        return AiGroupResult(
            judgments=[
                AiSubjectJudgment(
                    index=1, tags={short_name: AiTagJudgment(value, conf, "stub-reason")}
                )
            ],
            input_tokens=1,
            output_tokens=1,
            model="stub",
            truncated=False,
        )

    return _r


_NAME_DOC = LabeledDoc(
    "d1",
    "drivers_license",
    "id_name",
    {"full_name": "Robert Smith"},
    {"id.name_normalized": "Robert Smith"},
)


async def test_scores_a_correct_prediction_and_records_detail() -> None:
    (scored,) = await calibrate([_NAME_DOC], reasoner=_stub("name_normalized", "Robert Smith"))
    assert scored.correct and not scored.abstained
    # THE ACTIONABLE DETAIL — a case carries predicted / golden / confidence / reasoning, inspectable.
    assert scored.predicted == "Robert Smith" and scored.golden == "Robert Smith"
    assert scored.confidence == 0.9 and scored.reasoning == "stub-reason"


async def test_a_wrong_prediction_is_a_failing_case_and_inspectable() -> None:
    (scored,) = await calibrate([_NAME_DOC], reasoner=_stub("name_normalized", "Someone Else"))
    assert (
        not scored.correct
        and scored.predicted == "Someone Else"
        and scored.golden == "Robert Smith"
    )
    assert failing_cases([scored]) == [scored]  # the wrong case surfaces, with its reasoning
    report = format_report([scored], live=False)
    assert "WRONG" in report and "Someone Else" in report and "stub-reason" in report


async def test_normalized_comparison_accepts_valid_renderings() -> None:
    # 'Robert J. Smith' matches golden 'Robert J Smith' — drop_punct removes the '.', so a valid rendering
    # is not a false failure (the same casefold+drop_punct chain ID-1 applies to id.name_normalized).
    doc = LabeledDoc(
        "d1",
        "drivers_license",
        "id_name",
        {"full_name": "Robert J Smith"},
        {"id.name_normalized": "Robert J Smith"},
    )
    (scored,) = await calibrate([doc], reasoner=_stub("name_normalized", "Robert J. Smith"))
    assert scored.correct  # casefold + drop_punct + collapse-ws


async def test_numeric_tags_are_compared_numerically_not_as_strings() -> None:
    # income.documented_monthly is NUMERIC (feeds IN-1's fraud verdict). A string normalizer would strip
    # the '.' and collide magnitudes; numeric comparison must catch a 10x error and accept a re-formatted
    # equal value.
    num_doc = LabeledDoc(
        "ps",
        "pay_stub",
        "income_amounts",
        {"gross_pay": "x"},
        {"income.documented_monthly": "6000"},
    )
    wrong = await calibrate([num_doc], reasoner=_stub("documented_monthly", "60000"))  # 10x off
    assert not wrong[0].correct  # a decimal-point string collision must NOT score this correct
    same = await calibrate(
        [num_doc], reasoner=_stub("documented_monthly", "6000.00")
    )  # equal value
    assert same[
        0
    ].correct  # '6000' == '6000.00' numerically (a string normalizer would call it WRONG)


async def test_a_wrong_commit_on_a_golden_abstention_still_fails() -> None:
    # Excluding golden-abstention docs from the unknown-RATE must not hide a wrong COMMIT: a doc whose
    # golden is 'unknown' where the model invents a name is still a failing case.
    no_name = LabeledDoc("du", "drivers_license", "id_name", {}, {"id.name_normalized": "unknown"})
    (scored,) = await calibrate([no_name], reasoner=_stub("name_normalized", "Invented Name"))
    assert not scored.correct and failing_cases([scored]) == [scored]


async def test_over_abstention_counts_as_unknown() -> None:
    (scored,) = await calibrate([_NAME_DOC], reasoner=_stub("name_normalized", "unknown"))
    assert scored.abstained
    (dim,) = summarize([scored])
    assert dim.unknown_rate == 1.0  # abstained on an ANSWERABLE doc → over-abstention (a failure)
    assert failing_cases([scored]) == [scored]


async def test_a_correct_abstention_is_not_a_failure() -> None:
    # A doc with no name: the golden IS 'unknown', so abstaining is CORRECT — not a failing case.
    no_name = LabeledDoc("du", "drivers_license", "id_name", {}, {"id.name_normalized": "unknown"})
    (scored,) = await calibrate([no_name], reasoner=_stub("name_normalized", "unknown"))
    assert scored.abstained and scored.correct and failing_cases([scored]) == []


async def test_the_metric_is_not_inert() -> None:
    # A concrete-but-wrong committer → accuracy-when-concrete drops (fabrication), the dangerous direction.
    docs = [_NAME_DOC] * 4
    wrong = await calibrate(docs, reasoner=_stub("name_normalized", "Wrong Name"))
    (dim,) = summarize(wrong)
    assert dim.concrete == 4 and dim.accuracy_when_concrete == 0.0


# --------------------------------------------------------------------------- #
# LIVE seam — the REAL model, gated on an EXPLICIT flag (never the key alone → CI never pays)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    os.getenv("LP334_LIVE") != "1", reason="live calibration is opt-in (set LP334_LIVE=1)"
)
async def test_live_seam_runs_the_real_model_and_records_detail() -> None:
    (scored,) = await calibrate([_NAME_DOC], reasoner=None)  # None → the real model (one paid call)
    assert scored.predicted is not None and scored.reasoning  # real output + detail recorded
