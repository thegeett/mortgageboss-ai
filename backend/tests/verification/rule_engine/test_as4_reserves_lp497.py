"""LP-497 — AS-4 (reserves adequacy), activated after its 0/5 blocker was diagnosed rather than
calibrated.

EVERY VERDICT ASSERTION RUNS THROUGH A REAL RULE EVALUATION (LP-487's standing rule).

WHY THE 0/5 DID NOT BLOCK THIS RULE. AS-4's bar named `stmt.is_reserve_eligible` load-bearing "via the
reserves calculator". That tag is not in this chain at all: `build_reserves_view` sums assets from the
DB and takes its PITI divisor from the DTI calculation, and `reserves.required_months` reads MISMO
occupancy and financed unit count. Nothing AI-produced feeds either operand. Separately, the 0/5 was
not a model failure — the `stmt_facts` prompt asks about ACCOUNT TYPE while Priya was answering
whether those funds count as reserves for THIS loan (they do not; they are the funds to close), and
`compute_reserves` already subtracts down payment and closing costs.

CONSTRUCTED CASES, not corpus cases: only 5 loan files carry a bank statement and the calculator needs
a PITI divisor, so a corpus run abstains on every one. Amounts are invented; no borrower PII enters the
repo. These prove wiring, direction and the threshold matrix — not accuracy against real files.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.verification.eval.fire_path_scenarios import (
    build_as4_five_units_snapshot,
    build_as4_gated_calculation_snapshot,
    build_as4_investment_short_snapshot,
    build_as4_multi_unit_primary_ok_snapshot,
    build_as4_multi_unit_primary_short_snapshot,
    build_as4_no_occupancy_snapshot,
    build_as4_one_unit_primary_snapshot,
    build_as4_second_home_ok_snapshot,
    build_as4_units_unknown_snapshot,
)
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.tag_materialization.derived import (
    _RESERVE_MAX_RESIDENTIAL_UNITS,
    _RESERVE_MONTHS_INVESTMENT,
    _RESERVE_MONTHS_MULTI_UNIT_PRIMARY,
    _RESERVE_MONTHS_ONE_UNIT_PRIMARY,
    _RESERVE_MONTHS_SECOND_HOME,
)
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio


async def _verdict(builder) -> Verdict:
    snapshot = await materialize_tags(builder(), only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("AS-4",))
    assert len(evaluations) == 1, f"AS-4 is loan-scoped, got {evaluations}"
    return evaluations[0].verdict


async def _required(builder):
    snapshot = await materialize_tags(builder(), only_groups=frozenset())
    return snapshot.tags.by_subject["loan"]["reserves.required_months"]


# --------------------------------------------------------------------------- #
# The B3-4.1-01 matrix
# --------------------------------------------------------------------------- #
async def test_one_unit_principal_residence_requires_nothing() -> None:
    """ "There is no minimum reserve requirement for one-unit principal residence transactions." So
    half a month of reserves is satisfied — this is the commonest file in a normal pipeline."""
    assert await _verdict(build_as4_one_unit_primary_snapshot) is Verdict.SATISFIED


async def test_a_multi_unit_primary_short_of_six_months_fires() -> None:
    """THE CASE THAT WAS A FALSE-GREEN BEFORE THIS TICKET, and the reason the matrix gained a unit axis.

    B3-4.1-01 requires 6 months for a two- to four-unit principal residence. The previous map keyed on
    occupancy ONLY and returned 0 for every principal residence, so this file — 2.0 months against a
    real 6-month requirement — reported SATISFIED. Its own source comment recorded the defect: "a
    NON-1-unit or multiple-financed-property PRIMARY gets required=0 here and AS-4 can false-green a
    real reserve shortfall."

    Asserted as `is FIRED` and explicitly `is not SATISFIED` so a regression cannot quietly restore the
    old behaviour.
    """
    verdict = await _verdict(build_as4_multi_unit_primary_short_snapshot)
    assert verdict is Verdict.FIRED
    assert verdict is not Verdict.SATISFIED, (
        "a 2-4 unit principal residence requires 6 months — clearing it on the one-unit cell is the "
        "false-green LP-497 removed"
    )


async def test_a_multi_unit_primary_above_six_months_is_satisfied() -> None:
    """The contrast that proves the multi-unit cell is a real comparison, not a blanket fire."""
    assert await _verdict(build_as4_multi_unit_primary_ok_snapshot) is Verdict.SATISFIED


async def test_investment_property_requires_six_months() -> None:
    assert await _verdict(build_as4_investment_short_snapshot) is Verdict.FIRED


async def test_second_home_requires_two_months() -> None:
    assert await _verdict(build_as4_second_home_ok_snapshot) is Verdict.SATISFIED


# --------------------------------------------------------------------------- #
# The abstains — each one a verdict the rule must NOT reach
# --------------------------------------------------------------------------- #
async def test_a_primary_with_an_unknown_unit_count_abstains() -> None:
    """The one cell that cannot be defaulted: the requirement is 0 or 6 months and nothing between, so
    a default would DECIDE the verdict rather than inform it. The fixture is built so the two answers
    disagree — 2.0 months clears 0 and fails 6 — and the unit count reaches the snapshot on only 10 of
    19 corpus files, so this is a common branch, not an edge case."""
    verdict = await _verdict(build_as4_units_unknown_snapshot)
    assert verdict is Verdict.COULDNT_CHECK
    assert verdict is not Verdict.SATISFIED


async def test_the_unknown_unit_abstain_names_what_is_needed() -> None:
    tag = await _required(build_as4_units_unknown_snapshot)
    assert tag.value == "unknown"
    assert "unit count" in str(tag.reasoning).lower()


async def test_no_stated_occupancy_abstains() -> None:
    assert await _verdict(build_as4_no_occupancy_snapshot) is Verdict.COULDNT_CHECK


async def test_a_gated_calculator_abstains_rather_than_reading_null_as_zero() -> None:
    """The reserves calculation is gated (no PITI divisor), so `months_available` is null. Reading a
    missing number as zero months would fire on every file whose housing payment cannot be computed —
    an accusation built on an absence."""
    assert await _verdict(build_as4_gated_calculation_snapshot) is Verdict.COULDNT_CHECK


async def test_above_four_units_abstains() -> None:
    """B3-4.1-01's table covers one- to four-unit residential. Five units is outside it, so the rule
    abstains rather than applying a requirement the guide does not state for that property."""
    assert await _verdict(build_as4_five_units_snapshot) is Verdict.COULDNT_CHECK


# --------------------------------------------------------------------------- #
# The reference values are PINNED to the recipe constants (ADR-361)
# --------------------------------------------------------------------------- #
def test_reference_values_match_the_recipe_constants() -> None:
    """The citation and the code cannot drift apart. Every value is tier P from B3-4.1-01 (08/07/2024)."""
    values = load_rule_spec("AS-4").reference_values.values
    assert values["reserve_months_one_unit_primary"] == _RESERVE_MONTHS_ONE_UNIT_PRIMARY
    assert values["reserve_months_second_home"] == _RESERVE_MONTHS_SECOND_HOME
    assert values["reserve_months_multi_unit_primary"] == _RESERVE_MONTHS_MULTI_UNIT_PRIMARY
    assert values["reserve_months_investment"] == _RESERVE_MONTHS_INVESTMENT
    assert int(values["reserve_max_residential_units"]) == _RESERVE_MAX_RESIDENTIAL_UNITS
    # The guideline's own numbers, so a future edit to the constants alone fails here too.
    assert Decimal(_RESERVE_MONTHS_ONE_UNIT_PRIMARY) == 0
    assert Decimal(_RESERVE_MONTHS_MULTI_UNIT_PRIMARY) == 6


def test_as4_is_active_and_carries_no_ai_tag() -> None:
    """AS-4's bar previously named `stmt.is_reserve_eligible` load-bearing. It is not in the chain, and
    this pins the correction: an empty AI-tag list is what makes the no-ai-dependency gate legitimate."""
    bars = load_activation_bars()
    assert "AS-4" in ACTIVE_RULE_IDS
    assert is_eligible(bars["AS-4"])
    assert bars["AS-4"].status == "no-ai-dependency"
    assert list(bars["AS-4"].load_bearing_ai_tags) == [], (
        "AS-4's chain is deterministic end to end — the reserves calculator reads DB assets and the "
        "DTI housing line, and reserves.required_months reads MISMO occupancy and unit count"
    )


def test_as7_is_built_but_held() -> None:
    """AS-7 must NOT activate while `txn.is_nsf_or_overdraft` is declared without an abstain: an honest
    "unknown" coerces to confidence=None, which the orchestrator's degradation scan reads as a broken
    pipeline. LP-495c is the fix and has not landed. This test fails the moment someone activates AS-7,
    which is the intent — it should only go live with the declaration fixed."""
    bars = load_activation_bars()
    assert "AS-7" not in ACTIVE_RULE_IDS
    assert not is_eligible(bars["AS-7"])
    assert "txn.is_nsf_or_overdraft" in bars["AS-7"].load_bearing_ai_tags
