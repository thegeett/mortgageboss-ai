"""LP-342 — fuzzy scoring for free-text tags (LP-334 FINDING-2). The model was right; the ruler was wrong.

Calibration scored `id.name_normalized` at 33% where `Maria Garcia-Lopez` vs `Maria Garcia Lopez` is a
valid rendering, not an error — because the string normalizer DELETES the hyphen (`garcialopez`) instead of
treating it as a word boundary. This proves the corrected `normalized` scoring method BOTH DIRECTIONS: valid
renderings score EQUAL, and genuine differences still score WRONG (the leniency boundary — a ruler that fails
nothing is worthless). The enum/number path is asserted BYTE-IDENTICAL; the method is DECLARED per tag.
"""

from __future__ import annotations

import pytest
from app.verification.eval.calibration import (
    SCORING_EXACT,
    SCORING_HUMAN_REVIEW,
    SCORING_NORMALIZED,
    DimensionCalibration,
    normalized_match,
    scoring_mode,
)
from app.verification.eval.live_calibration import (
    ScoredTag,
    failing_cases,
    review_cases,
    summarize,
)
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS


def _st(tag_id: str, golden: str, predicted: str | None) -> ScoredTag:
    return ScoredTag(
        doc_id="d", tag_id=tag_id, golden=golden, predicted=predicted, confidence=0.9, reasoning="r"
    )


# The FINDING-2 tags declare `normalized`; the free-form provenance tags declare `human_review`.
_NAME = "id.name_normalized"
_ADDR = "id.address_normalized"

# INDEPENDENT of any tag's performance (chosen to prove the ruler, not tuned to results):
_MATCH_SET = [  # a valid RENDERING of the same value → must score EQUAL
    ("Maria Garcia-Lopez", "Maria Garcia Lopez"),  # THE FINDING-2 headline (hyphen = word boundary)
    ("Robert J. Smith", "Robert J Smith"),  # period
    ("123 Maple Ave", "123  Maple   Ave"),  # collapsed whitespace
    ("ACME LOGISTICS", "acme logistics"),  # case
    ("123 Main St, Apt 4", "123 Main St Apt 4"),  # comma
    (
        "Sean O'Brien",
        "Sean OBrien",
    ),  # apostrophe ELIDES, not a boundary (mirrors ID-1's drop_punct)
    ("D'Angelo Russell", "DAngelo Russell"),  # same: apostrophe is elision within a token
]
_MISMATCH_SET = [  # genuinely DIFFERENT → must score WRONG (the leniency boundary)
    ("Jordan A Rivera", "Taylor M Nguyen"),  # a different person
    ("Acme Logistics", "Sterling Retail"),  # a different name
    ("123 Maple Ave", "456 Oak St"),  # a different address
    ("124 Maple Ave", "123 Maple Ave"),  # right street, WRONG number
    ("Robert Smith", "Robert Smyth"),  # a one-letter difference is still a difference
]


# ================================================================================================= #
# PHASE 2 — PROVE THE RULER (both directions), independent of any tag
# ================================================================================================= #
@pytest.mark.parametrize(("golden", "predicted"), _MATCH_SET)
def test_match_set_scores_equal(golden: str, predicted: str) -> None:
    assert normalized_match(golden, predicted)  # the raw comparator
    assert _st(_NAME, golden, predicted).correct  # and end-to-end via the tag's declared method


@pytest.mark.parametrize(("golden", "predicted"), _MISMATCH_SET)
def test_mismatch_set_scores_wrong(golden: str, predicted: str) -> None:
    # THE IMPORTANT HALF: a scorer that never says "wrong" is worthless.
    assert not normalized_match(golden, predicted)
    assert not _st(_NAME, golden, predicted).correct


def test_the_ruler_fails_a_wrong_distribution_not_inert() -> None:
    # NOT inert: feed a genuinely-wrong distribution through the REAL scorer → low accuracy → the
    # fabrication flag fires (id.name_normalized is a registered abstaining dimension). A lenient ruler
    # that scored these "correct" would NOT fire — so this proves the ruler catches a wrong tag.
    scored = [_st(_NAME, g, p) for g, p in _MISMATCH_SET]
    (dim,) = summarize(scored)
    assert dim.concrete == len(_MISMATCH_SET) and dim.concrete_correct == 0
    assert dim.accuracy_when_concrete == 0.0 and dim.under_abstaining  # the ruler FAILS things


# ================================================================================================= #
# DECLARED, not hardcoded — dispatch by METHOD, never by tag-id
# ================================================================================================= #
def test_scoring_is_declared_not_hardcoded() -> None:
    assert scoring_mode(_NAME) == SCORING_NORMALIZED and scoring_mode(_ADDR) == SCORING_NORMALIZED
    assert scoring_mode("txn.counterparty") == SCORING_HUMAN_REVIEW
    # an UNDECLARED tag — even one named *_normalized — defaults to exact (no name-pattern magic, no branch)
    assert scoring_mode("some.future_normalized") == SCORING_EXACT
    # the SAME normalized code path serves every normalized tag (no per-tag logic): name & address agree
    assert _st(_NAME, "A B-C", "A B C").correct and _st(_ADDR, "A B-C", "A B C").correct


# ================================================================================================= #
# ENUM / NUMBER path — BYTE-IDENTICAL (must not move)
# ================================================================================================= #
def test_enum_and_number_path_unchanged() -> None:
    assert (
        _st("txn.is_money_in", "in", "in").correct
        and not _st("txn.is_money_in", "in", "out").correct
    )
    # numeric tolerance preserved (income.documented_monthly feeds IN-1's deterministic verdict)
    assert _st("income.documented_monthly", "6000", "6000.00").correct
    assert not _st("income.documented_monthly", "6000", "9999").correct
    # an enum is NOT normalized-collapsed: residence vs mailing stays wrong
    assert not _st("id.current_address_type", "residence", "mailing").correct


def test_dimension_calibration_is_backward_compatible() -> None:
    # the pre-LP-342 4-positional construction still works; review defaults 0 (byte-identical enum path)
    c = DimensionCalibration("txn.is_money_in", 50, 1, 49, 48)
    assert c.review == 0 and not c.is_human_review
    assert round(c.accuracy_when_concrete, 4) == round(48 / 49, 4)


# ================================================================================================= #
# HUMAN REVIEW — no defensible golden → recorded, NEVER %-scored
# ================================================================================================= #
def test_human_review_tag_is_recorded_not_scored() -> None:
    cases = [
        _st("txn.counterparty", "Chase Wire Dept", "chase wire"),
        _st("txn.source_reference", "payroll 3d prior", "payroll deposit"),
    ]
    (name_dim,) = summarize([_st(_NAME, "Sam", "Sam")])
    assert name_dim.accuracy_when_concrete == 1.0  # a scored tag reports a %
    dims = summarize(cases)
    for d in dims:
        assert d.is_human_review and d.review == 1 and d.concrete == 0  # no % claimed
    # the per-case detail is preserved for the human, and these are NOT counted as failures
    assert set(review_cases(cases)) == set(cases) and failing_cases(cases) == []


# ================================================================================================= #
# LP-340 interaction — the scorer must NOT re-litigate the convention (no hidden leniency)
# ================================================================================================= #
def test_scorer_does_not_strip_entity_suffixes() -> None:
    # `drop_entity_suffix` is IN-5's RULE-declared normalizer (LP-340), NOT the scorer's job. The name/
    # address scorer must NOT collapse `Acme Inc` vs `Acme LLC` — that would hide a real difference behind
    # a lenient ruler and make LP-340's convention untestable. The scorer only collapses FORMAT.
    assert not normalized_match("Acme Inc", "Acme LLC")
    assert not _st(_NAME, "Acme Inc", "Acme LLC").correct


# ================================================================================================= #
# PER-CASE DETAIL survives — a near-miss is inspectable, not just counted
# ================================================================================================= #
def test_near_miss_is_inspectable() -> None:
    miss = _st(_NAME, "Robert Smith", "Robert Smyth")  # a genuine near-miss under the fuzzy scorer
    (fail,) = failing_cases([miss])
    assert (
        fail.predicted == "Robert Smyth" and fail.golden == "Robert Smith" and fail.reasoning == "r"
    )


def test_no_rule_activation_changed() -> None:
    assert ACTIVE_RULE_IDS == (
        "AS-1",
        "OC-2",
        "ID-2",
        "ID-4",
        "ID-1",
        "ID-3",
        "ID-6",
        "ID-7",
        "ID-9",
        "ID-8",
        "IN-2",
        # LP-389 — the first activation pass, via the eligibility gate (activation_bars.is_eligible)
        "IN-1",
        "IN-5",
    )
