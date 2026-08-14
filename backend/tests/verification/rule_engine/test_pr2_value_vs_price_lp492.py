"""LP-492 — PR-2 (appraised value vs purchase price).

⚠️ EVERY VERDICT ASSERTION RUNS THROUGH A REAL RULE EVALUATION (LP-487's standing rule).

⚠️ n=2. Two appraisals is the whole corpus (`appraised_value` 2/2). These fixtures use invented amounts
because no borrower PII enters the repo; they prove wiring and direction, not accuracy.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.verification.eval.fire_path_scenarios import (
    build_pr2_no_price_snapshot,
    build_pr2_no_purpose_snapshot,
    build_pr2_refinance_snapshot,
    build_pr2_shortfall_snapshot,
    build_pr2_two_appraisals_snapshot,
    build_pr2_value_supports_price_snapshot,
)
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.distrust import distrusted_tag_ids
from app.verification.rules.specs import load_rule_spec
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio


async def _one(builder) -> Verdict:
    snapshot = await materialize_tags(builder(), only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("PR-2",))
    assert len(evaluations) == 1, f"PR-2 is loan-scoped, got {evaluations}"
    return evaluations[0].verdict


async def test_value_at_or_above_price_is_satisfied() -> None:
    assert await _one(build_pr2_value_supports_price_snapshot) is Verdict.SATISFIED


async def test_a_shortfall_fires() -> None:
    """⚠️ `fired`, argued rather than inherited. IH-2 and TI-1 chose needs_review because a NAME
    difference is frequently legitimate (a trust, a name change). A value shortfall is not ambiguous in
    that way: the number is the number, and it has a definite consequence — cash, a renegotiation, or a
    rebuttal. That is an actionable requirement, which is what `fired` means here (PR-6 uses it the same
    way for "a new appraisal is required")."""
    assert await _one(build_pr2_shortfall_snapshot) is Verdict.FIRED


async def test_two_appraisals_take_the_lowest_value_pinned_by_value() -> None:
    """⚠️ THE LP-488 DEFECT SHAPE, guarded here BY VALUE rather than by verdict.

    `property.appraised_value` is per-appraisal-document. The first version of that reader took whichever
    subject iterated FIRST, giving an arbitrary answer on an ordinary file (an original plus a
    replacement, or a 1004D the classifier cannot distinguish from a full report).

    $410,000 and $380,000 against a $400,000 price: the LOWEST gives -20,000 and fires; the highest would
    give +10,000 and SILENTLY CLEAR A REAL SHORTFALL. Asserting the verdict alone would still pass if the
    fixture happened to fire for the wrong reason, so the gap itself is pinned."""
    snapshot = await materialize_tags(build_pr2_two_appraisals_snapshot(), only_groups=frozenset())
    gap = snapshot.tags.by_subject["loan"]["property.value_vs_price_gap"]
    assert Decimal(str(gap.value)) == Decimal("-20000.00"), (
        "the LOWEST appraised value must drive the gap"
    )
    assert await _one(build_pr2_two_appraisals_snapshot) is Verdict.FIRED


# --------------------------------------------------------------------------- #
# Purpose scoping — all three directions
# --------------------------------------------------------------------------- #
async def test_a_refinance_is_not_applicable() -> None:
    """A refinance has no contract price; there is nothing to compare."""
    assert await _one(build_pr2_refinance_snapshot) is Verdict.NOT_APPLICABLE


async def test_a_file_with_no_stated_purpose_couldnt_checks() -> None:
    """⚠️ The same shortfall that FIRES under `purchase` must be SURFACED, not skipped, when the purpose
    is unstated. As an outcome rather than an applicability predicate it would have produced nothing."""
    assert await _one(build_pr2_no_purpose_snapshot) is Verdict.COULDNT_CHECK


async def test_no_price_couldnt_checks_never_satisfied() -> None:
    verdict = await _one(build_pr2_no_price_snapshot)
    assert verdict is Verdict.COULDNT_CHECK
    assert verdict is not Verdict.SATISFIED


async def test_lf6t3n_never_clears_on_a_missing_appraisal() -> None:
    """⚠️ "The appraisal supports the value" on a file with no appraisal is a false all-clear."""
    snapshot = await materialize_tags(build_lf6t3n_snapshot(), only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("PR-2",))
    assert Verdict.SATISFIED not in [e.verdict for e in evaluations]


# --------------------------------------------------------------------------- #
# Provenance and the gate
# --------------------------------------------------------------------------- #
def test_the_lesser_of_citation_is_recorded() -> None:
    """⚠️ TIER P, VERIFIED against the live page in this session (2026-08-13) rather than taken from the
    ticket: Fannie Mae B2-1.2-01, page dated 06/01/2022 — the property value is the LOWER of sales price
    and appraised value, which is why a shortfall lands on the borrower as cash."""
    spec = load_rule_spec("PR-2")
    assert spec.reference_values.values["shortfall_boundary"] == "0"
    assert "06/01/2022" in spec.guideline_reference
    assert "B2-1.2-01" in spec.guideline_reference


def test_pr2_is_live_without_a_self_consistency_rate() -> None:
    """No model in its chain, so no derivation and no ratification load."""
    bar = load_activation_bars()["PR-2"]
    assert bar.status == "no-ai-dependency"
    assert bar.load_bearing_ai_tags == ()
    assert bar.self_consistency_rate is None and bar.measured_accuracy is None
    assert is_eligible(bar) and "PR-2" in ACTIVE_RULE_IDS


def test_pr2_reads_no_distrusted_tag() -> None:
    gated = set(load_rule_spec("PR-2").deterministic.gated_tags)
    assert not (gated & set(distrusted_tag_ids()))
