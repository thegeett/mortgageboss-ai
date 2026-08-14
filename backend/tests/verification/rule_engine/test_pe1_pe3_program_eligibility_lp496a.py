"""LP-496a — PE-1 (conforming limit / the jumbo catch) and PE-3 (FHA minimum required investment).

EVERY VERDICT ASSERTION RUNS THROUGH A REAL RULE EVALUATION (LP-487's standing rule).

THESE ARE CONSTRUCTED SCENARIO CASES, NOT CORPUS CASES, and the reason is measured rather than
assumed. No conventional loan file in the corpus carries an amount near the conforming limit, and the
four FHA files hold TWO documents between them (three carry zero) — none of them a purchase contract,
an appraisal or a credit report. A corpus derivation would return the same abstain on every case. The
constructed cases exercise every branch and their right answer is known by construction.

Amounts are invented; no borrower PII enters the repo. These prove wiring, direction and the two
design decisions that carry the rules — they do not prove accuracy against real files.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.verification.eval.fire_path_scenarios import (
    build_pe1_alaska_within_snapshot,
    build_pe1_county_band_snapshot,
    build_pe1_exceeds_limit_snapshot,
    build_pe1_fha_snapshot,
    build_pe1_multi_unit_snapshot,
    build_pe1_no_amount_snapshot,
    build_pe1_within_limit_snapshot,
    build_pe3_conventional_snapshot,
    build_pe3_investment_met_snapshot,
    build_pe3_investment_short_snapshot,
    build_pe3_low_appraisal_snapshot,
    build_pe3_low_credit_tier_snapshot,
    build_pe3_no_credit_score_snapshot,
)
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.tag_materialization.derived import (
    _CONFORMING_BASELINE_1_UNIT,
    _CONFORMING_CEILING_1_UNIT,
    _CONFORMING_SPECIAL_BASELINE_1_UNIT,
    _CONFORMING_SPECIAL_CEILING_1_UNIT,
    _FHA_MDCS_FLOOR,
    _FHA_MDCS_FULL_FINANCING,
    _FHA_MRI_RATE,
    _FHA_MRI_RATE_LOW_SCORE,
)
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio


async def _verdict(rule_id: str, builder) -> Verdict:
    snapshot = await materialize_tags(builder(), only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=(rule_id,))
    assert len(evaluations) == 1, f"{rule_id} is loan-scoped, got {evaluations}"
    return evaluations[0].verdict


async def _tag(builder, tag_id: str):
    snapshot = await materialize_tags(builder(), only_groups=frozenset())
    return snapshot.tags.by_subject["loan"][tag_id]


# --------------------------------------------------------------------------- #
# PE-1 — the conforming limit
# --------------------------------------------------------------------------- #
async def test_below_the_baseline_is_satisfied() -> None:
    """$700,000 is below the $832,750 baseline — conforming in EVERY county, so no county is needed."""
    assert await _verdict("PE-1", build_pe1_within_limit_snapshot) is Verdict.SATISFIED


async def test_above_the_high_cost_ceiling_fires() -> None:
    """$1,400,000 is above the $1,249,125 ceiling — over the limit in EVERY county.

    `fired`, argued rather than inherited: a jumbo is not ambiguous the way a name mismatch is. The
    amount either exceeds every county's limit or it does not, and the consequence is definite — the
    file moves to a different product with different pricing and disclosures.
    """
    assert await _verdict("PE-1", build_pe1_exceeds_limit_snapshot) is Verdict.FIRED


async def test_the_county_dependent_band_abstains_and_never_clears() -> None:
    """THE CASE THE WHOLE RULE IS SHAPED AROUND — acceptance criterion 4.

    $1,000,000 sits between the $832,750 baseline and the $1,249,125 ceiling. It is CONFORMING in a
    high-cost county and JUMBO in most of the country, and the snapshot carries no county: MISMO parses
    <CountyName>, but the Property model has no column to hold it, so it is dropped before projection.

    A baseline-only comparison would FIRE on a conforming high-cost loan. A ceiling-only comparison
    would SATISFY a jumbo — the exact file "the jumbo catch" exists to catch. Only couldnt_check is
    honest, and the assertion is written as `is not SATISFIED` as well as `is COULDNT_CHECK` so that a
    future widening of the comparison cannot quietly turn this into a pass.
    """
    verdict = await _verdict("PE-1", build_pe1_county_band_snapshot)
    assert verdict is Verdict.COULDNT_CHECK
    assert verdict is not Verdict.SATISFIED, (
        "a loan in the county-dependent band must NEVER clear — the county is what decides it"
    )


async def test_the_band_abstain_names_the_county_as_what_is_needed() -> None:
    """The abstain must be actionable: a processor has to see that a COUNTY resolves it, not read the
    couldnt_check as a broken pipeline."""
    tag = await _tag(build_pe1_county_band_snapshot, "program.conforming_eligibility")
    assert tag.value == "unknown"
    assert "county" in str(tag.reasoning).lower()


async def test_alaska_takes_the_special_area_baseline() -> None:
    """THE SAME $1,000,000 THAT ABSTAINS IN NORTH CAROLINA IS SATISFIED IN ALASKA.

    Alaska, Hawaii, Guam and the USVI take the national CEILING ($1,249,125) as their BASELINE. Without
    the carve-out this file would land in the band and abstain, so the pair of cases pins the carve-out
    by contrast rather than by reading a constant.
    """
    assert await _verdict("PE-1", build_pe1_alaska_within_snapshot) is Verdict.SATISFIED
    assert await _verdict("PE-1", build_pe1_county_band_snapshot) is Verdict.COULDNT_CHECK


async def test_fha_is_not_applicable() -> None:
    assert await _verdict("PE-1", build_pe1_fha_snapshot) is Verdict.NOT_APPLICABLE


async def test_a_missing_loan_amount_abstains() -> None:
    """Never satisfied on a missing figure."""
    assert await _verdict("PE-1", build_pe1_no_amount_snapshot) is Verdict.COULDNT_CHECK


async def test_multi_unit_abstains_rather_than_using_an_unverified_limit() -> None:
    """The 2-4 unit limits were NOT verified against a primary source — FHFA's release states one-unit
    figures only, and the multi-unit table ships inside a downloadable county file. Judging a 2-unit
    loan against an unverified number is exactly the recalled-threshold failure ADR-361 forbids."""
    assert await _verdict("PE-1", build_pe1_multi_unit_snapshot) is Verdict.COULDNT_CHECK


# --------------------------------------------------------------------------- #
# PE-3 — the FHA minimum required investment
# --------------------------------------------------------------------------- #
async def test_investment_meeting_the_mri_is_satisfied() -> None:
    """$20,000 invested against $14,000 required (3.5% of a $400,000 Adjusted Value, MDCS 700)."""
    assert await _verdict("PE-3", build_pe3_investment_met_snapshot) is Verdict.SATISFIED


async def test_investment_below_the_mri_fires() -> None:
    """$10,000 invested against $14,000 required."""
    assert await _verdict("PE-3", build_pe3_investment_short_snapshot) is Verdict.FIRED


async def test_the_basis_is_adjusted_value_not_purchase_price() -> None:
    """THE CATALOG RATIONALE SAYS "3.5% of price" AND IT IS WRONG — pinned by the case that separates
    the two.

    A $400,000 price, a $360,000 appraisal and a $348,000 loan:
      against the PRICE          -> investment $52,000 vs $14,000 required -> WOULD CLEAR
      against the ADJUSTED VALUE -> investment $12,000 vs $12,600 required -> FIRES
    HUD 4000.1: "the Adjusted Value is the lesser of: purchase price less any inducements to purchase;
    or the Property Value." Using the price would clear a file that fails, which is why the divergence
    from the catalog is deliberate and recorded in the spec.
    """
    assert await _verdict("PE-3", build_pe3_low_appraisal_snapshot) is Verdict.FIRED
    tag = await _tag(build_pe3_low_appraisal_snapshot, "program.fha_min_investment_met")
    assert "360,000" in str(tag.reasoning), (
        "the finding must show the Adjusted Value it used, not the purchase price"
    )


async def test_a_missing_credit_score_abstains_rather_than_assuming_the_cheapest_tier() -> None:
    """THE TIER IS NEVER ASSUMED, and the fixture is built so the assumption would CHANGE the answer.

    The same $20,000 investment on a $400,000 Adjusted Value clears the 3.5% requirement ($14,000) and
    FAILS the 10% one ($40,000). So defaulting a missing MDCS to 580+ would clear a borrower who may
    need 10% — the failure this abstain exists to prevent. The MDCS reaches only 1 of 19 corpus files,
    so this is the branch nearly every real FHA file would take today.
    """
    assert await _verdict("PE-3", build_pe3_no_credit_score_snapshot) is Verdict.COULDNT_CHECK


async def test_the_low_credit_tier_changes_the_requirement() -> None:
    """The contrast that proves the tier is really applied: an MDCS of 550 needs 10% ($40,000), so the
    $20,000 investment that SATISFIES at 580+ FIRES here."""
    assert await _verdict("PE-3", build_pe3_low_credit_tier_snapshot) is Verdict.FIRED
    assert await _verdict("PE-3", build_pe3_investment_met_snapshot) is Verdict.SATISFIED


async def test_conventional_is_not_applicable() -> None:
    assert await _verdict("PE-3", build_pe3_conventional_snapshot) is Verdict.NOT_APPLICABLE


# --------------------------------------------------------------------------- #
# The reference values are PINNED to the recipe constants (ADR-361).
# --------------------------------------------------------------------------- #
def test_pe1_reference_values_match_the_recipe_constants() -> None:
    """The spec's citation and the code's constants cannot drift apart."""
    values = load_rule_spec("PE-1").reference_values.values
    assert Decimal(values["conforming_baseline_1_unit"]) == _CONFORMING_BASELINE_1_UNIT
    assert Decimal(values["conforming_ceiling_1_unit"]) == _CONFORMING_CEILING_1_UNIT
    assert (
        Decimal(values["conforming_special_area_baseline_1_unit"])
        == _CONFORMING_SPECIAL_BASELINE_1_UNIT
    )
    assert (
        Decimal(values["conforming_special_area_ceiling_1_unit"])
        == _CONFORMING_SPECIAL_CEILING_1_UNIT
    )


def test_pe3_reference_values_match_the_recipe_constants() -> None:
    values = load_rule_spec("PE-3").reference_values.values
    assert Decimal(values["fha_mri_rate"]) == _FHA_MRI_RATE
    assert Decimal(values["fha_mri_rate_low_score"]) == _FHA_MRI_RATE_LOW_SCORE
    assert int(values["fha_mdcs_full_financing"]) == _FHA_MDCS_FULL_FINANCING
    assert int(values["fha_mdcs_floor"]) == _FHA_MDCS_FLOOR


def test_both_rules_are_active_and_eligible() -> None:
    bars = load_activation_bars()
    for rule_id in ("PE-1", "PE-3"):
        assert rule_id in ACTIVE_RULE_IDS, f"{rule_id} must be active"
        assert is_eligible(bars[rule_id]), f"{rule_id} must pass the activation gate"
