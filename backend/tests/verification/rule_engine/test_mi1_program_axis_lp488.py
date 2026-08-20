"""LP-488 — MI-1 (conventional MI requirement) and the PROGRAM AXIS's first use.

⚠️ EVERY VERDICT ASSERTION RUNS THROUGH A REAL RULE EVALUATION (LP-487's standing rule):
materialize_tags() then evaluate_rules(), never by calling a recipe or the gate directly. A green test
over an unexercised path is ADR-286/289 at the test layer.

⚠️ THE PROGRAM AXIS. LP-501 established that conventional-vs-FHA IS expressible (`LoanProgram` is a
two-value enum reaching the snapshot as `program.type`) while Fannie-vs-Freddie and DU-vs-manual are NOT.
MI-1 is conventional-only. The scoping is an APPLICABILITY PREDICATE, never an outcome, because the
applicability layer resolves absent/"unknown" to couldnt_check and only definitely-false to
not_applicable — as an outcome, a file that states no program would be SILENTLY SKIPPED. Both directions
are proven below, and so is the absent case.

⚠️ MI-1 CANNOT FIRE. It can prove MI is REQUIRED (LTV > 80) but not that MI is PRESENT: no document type
in the system carries an MI certificate, `mi.certificate_present` is an uncalibrated AI tag (LP-484), and
`housing.mi_monthly` reaches nothing. So the requirement routes to needs_review — the IH-2 shape.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.verification.eval.fire_path_scenarios import (
    build_mi1_fha_snapshot,
    build_mi1_high_ltv_snapshot,
    build_mi1_low_ltv_snapshot,
    build_mi1_no_program_snapshot,
    build_mi1_no_value_snapshot,
    build_mi1_two_appraisals_snapshot,
)
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.distrust import distrusted_tag_ids
from app.verification.rules.specs import load_rule_spec
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio


async def _verdicts(builder) -> list[Verdict]:
    snapshot = await materialize_tags(builder(), only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("MI-1",))
    return [e.verdict for e in evaluations]


async def _one(builder) -> Verdict:
    verdicts = await _verdicts(builder)
    assert len(verdicts) == 1, f"MI-1 is loan-scoped — expected one verdict, got {verdicts}"
    return verdicts[0]


# --------------------------------------------------------------------------- #
# The LTV test
# --------------------------------------------------------------------------- #
async def test_ltv_above_80_needs_review() -> None:
    """$340,000 on a $400,000 purchase = 85% → MI is required."""
    assert await _one(build_mi1_high_ltv_snapshot) is Verdict.NEEDS_REVIEW


async def test_ltv_at_or_below_80_off_a_sales_price_alone_cannot_clear_mi() -> None:
    """$300,000 on a $400,000 purchase = 75%, and MI-1 no longer clears it. THIS ASSERTION WAS FLIPPED
    BY LP-600, deliberately — the old one encoded the bug.

    `build_mi1_low_ltv_snapshot` carries a purchase price and NO DOCUMENTS. Its 75% is computed from
    the sales price, because `value_basis` divides a purchase by the lesser of price and appraised
    value and only one of them exists. B2-1.2-01 puts the APPRAISED value in that denominator, and a
    sales price is what the parties agreed rather than what the property is worth — so dismissing a
    mortgage-insurance requirement on it clears a real monthly cost before the evidence exists.

    The guard LP-597 added was inert here: `_loan_ltv_basis_is_appraised` did not look at
    `property.purchase_price`, returned "unknown", and MI-1's `eq "no"` branch never matched. The
    companion test below is what keeps this honest — with an appraisal on the file, 75% still passes.
    """
    assert await _one(build_mi1_low_ltv_snapshot) is Verdict.COULDNT_CHECK


async def test_an_appraisal_on_the_file_still_clears_a_low_ltv() -> None:
    """THE OTHER HALF, so the guard is discriminating rather than merely strict. Same rule, a file
    that carries appraisals — MI-1 clears it, exactly as before."""
    assert await _one(build_mi1_two_appraisals_snapshot) is not Verdict.COULDNT_CHECK


async def test_mi1_cannot_fire_from_any_outcome() -> None:
    """⚠️ STRUCTURAL, not incidental to the fixtures. MI-1 knows MI is REQUIRED; it cannot know MI is
    MISSING, and firing would assert the latter. If someone adds a `fired` outcome, this fails."""
    outcomes = load_rule_spec("MI-1").deterministic.outcomes
    assert Verdict.FIRED.value not in [o.verdict for o in outcomes]
    # LP-597 inserted a `couldnt_check` between them: MI-1 must not CLEAR an MI requirement off
    # the value stated on the application, because B2-1.2-01 puts the appraised value in that
    # denominator. The invariant this test protects is the line above — MI-1 knows MI is required and
    # cannot know it is missing — and a couldnt_check asserts strictly less than either of the others,
    # so it cannot violate it.
    assert [o.verdict for o in outcomes] == ["needs_review", "couldnt_check", "satisfied"]


# --------------------------------------------------------------------------- #
# ⚠️ THE PROGRAM AXIS — both directions, plus absent
# --------------------------------------------------------------------------- #
async def test_an_fha_file_is_not_applicable_not_fired() -> None:
    """The SAME 85% LTV that needs_reviews on a conventional file. MI-1 must not reach an FHA loan at
    all — MI-4 covers FHA, and an FHA loan's MIP is not optional above 80%."""
    verdict = await _one(build_mi1_fha_snapshot)
    assert verdict is Verdict.NOT_APPLICABLE
    assert verdict is not Verdict.NEEDS_REVIEW


async def test_a_file_with_no_stated_program_couldnt_checks() -> None:
    """⚠️ THE REASON THE SCOPING IS A PREDICATE. The same 85% LTV with no program stated must be
    SURFACED, not skipped. As an outcome this file would have produced nothing at all."""
    assert await _one(build_mi1_no_program_snapshot) is Verdict.COULDNT_CHECK


def test_the_program_scoping_is_an_applicability_predicate() -> None:
    applicability = load_rule_spec("MI-1").deterministic.applicability
    assert applicability is not None
    assert (applicability.tag, applicability.op, applicability.value) == (
        "program.type",
        "eq",
        "conventional",
    )


# --------------------------------------------------------------------------- #
# Fail closed
# --------------------------------------------------------------------------- #
async def test_no_value_basis_couldnt_checks_never_satisfied() -> None:
    """A loan amount with no purchase price and no appraisal cannot form an LTV. ⚠️ Never satisfied:
    clearing the MI requirement because the property value is missing is the costly direction."""
    verdict = await _one(build_mi1_no_value_snapshot)
    assert verdict is Verdict.COULDNT_CHECK
    assert verdict is not Verdict.SATISFIED


async def test_two_appraisals_take_the_lowest_value() -> None:
    """⚠️ A REPORTED DEFECT, of the same shape as the LP-487 review findings: `property.appraised_value`
    is PER APPRAISAL DOCUMENT, and the first version of this recipe took whichever subject iterated
    FIRST — an arbitrary LTV denominator on an ordinary file (an original plus a replacement appraisal,
    or a 1004D the classifier cannot tell from a full report).

    The pick follows the policy LP-485 already set for this document family: where the guideline is
    silent, take the CONSERVATIVE value. A lower appraisal means a HIGHER LTV, which keeps MI-1's costly
    direction — an MI requirement silently cleared — closed.

    Pinned by VALUE, not just verdict: both appraisals here produce an over-threshold LTV, so asserting
    the verdict alone would not catch a regression to first-wins."""
    snapshot = await materialize_tags(build_mi1_two_appraisals_snapshot(), only_groups=frozenset())
    assert Decimal(str(snapshot.tags.by_subject["loan"]["property.value_basis"].value)) == Decimal(
        "360000.00"
    ), "the LOWEST appraisal must drive the LTV denominator"
    # LP-496 — the tag now carries B2-1.2-01's DELIVERED whole percent (truncate to two decimals,
    # then round up), because its consumer MI-1 asks a whole-percent eligibility question. The exact
    # 94.44% is preserved in the tag's REASONING, asserted below, so the pin is still by value and a
    # regression to first-wins would still be caught.
    # This assertion previously read 94.44 and encoded the defect LP-496 fixes.
    assert Decimal(str(snapshot.tags.by_subject["loan"]["loan.ltv_percent"].value)) == Decimal("95")
    assert "94.44% (delivered as 95%)" in (
        snapshot.tags.by_subject["loan"]["loan.ltv_percent"].reasoning or ""
    ), "the exact ratio must stay visible on the finding — a bare 95% is not checkable"
    assert await _one(build_mi1_two_appraisals_snapshot) is Verdict.NEEDS_REVIEW


async def test_lf6t3n_abstains() -> None:
    """The real fixture states no program, no loan amount and no property type — MI-1 abstains rather
    than clearing."""
    snapshot = await materialize_tags(build_lf6t3n_snapshot(), only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("MI-1",))
    assert [e.verdict for e in evaluations] == [Verdict.COULDNT_CHECK]


# --------------------------------------------------------------------------- #
# The threshold, the tags, and the gate
# --------------------------------------------------------------------------- #
def test_the_threshold_lives_in_the_spec_not_in_a_producer() -> None:
    """⚠️ TAGS DESCRIBE, RULES JUDGE. `mi.required` exists in fact_tags.csv as "Is MI required (LTV>80
    conv)" — a conclusion with the threshold baked in. It is deliberately left INERT; materialising it
    would move an 80 that belongs in reviewable reference_values into a producer."""
    assert load_rule_spec("MI-1").reference_values.values["mi_required_above_ltv_percent"] == "80"
    assert "mi.required" not in load_declarations(), (
        "mi.required must stay inert — it embeds MI-1's threshold in a producer"
    )


async def test_the_ltv_recipe_uses_the_shared_arithmetic() -> None:
    """The recipe calls app/verification/ltv.py rather than reimplementing the lesser-of rule, so the
    rule path and the display path cannot drift into two different LTVs for one file. Proven by value:
    340000/400000 = 85.00 exactly, through a real materialisation."""
    snapshot = await materialize_tags(build_mi1_high_ltv_snapshot(), only_groups=frozenset())
    tag = snapshot.tags.by_subject["loan"]["loan.ltv_percent"]
    assert Decimal(str(tag.value)) == Decimal("85.00")


def test_mi1_is_live_and_earned_it_through_the_gate() -> None:
    bars = load_activation_bars()
    assert "MI-1" in ACTIVE_RULE_IDS
    assert is_eligible(bars["MI-1"])
    # ⚠️ `validated` is NOT read for a no-ai-dependency bar — is_eligible reads input_resolves alone.
    # It stays false rather than being set decoratively; the bar's comment records why.
    assert bars["MI-1"].validated is False


def test_mi1_reads_no_distrusted_tag() -> None:
    gated = set(load_rule_spec("MI-1").deterministic.gated_tags)
    assert not (gated & set(distrusted_tag_ids()))


def test_the_spec_mi_ltv_trigger_matches_the_calculator_constant() -> None:
    """⚠️ TWO SOURCES OF TRUTH (reported finding). MI-1's mi_required_above_ltv_percent duplicates
    `_PMI_REQUIRED_LTV` in app/verification/mortgage_insurance.py — the constant that decides whether PMI
    is required AND whether it flows into the DTI's PITI line. If Fannie moves the trigger and only one
    is updated, MI-1 and the DTI disagree about the same loan with nothing failing."""
    from decimal import Decimal

    from app.verification.mortgage_insurance import _PMI_REQUIRED_LTV
    from app.verification.rules.specs import load_rule_spec

    values = dict(load_rule_spec("MI-1").reference_values.values)
    assert Decimal(values["mi_required_above_ltv_percent"]) == _PMI_REQUIRED_LTV
