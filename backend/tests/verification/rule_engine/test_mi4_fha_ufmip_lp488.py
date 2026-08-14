"""LP-488 — MI-4 (FHA upfront MIP) and the FHA side of the PROGRAM axis.

⚠️ EVERY VERDICT ASSERTION RUNS THROUGH A REAL RULE EVALUATION (LP-487's standing rule):
materialize_tags() then evaluate_rules(), never by calling a recipe or the gate directly.

⚠️ NOT AN ADR-330 VACUITY. The two operands are two DIFFERENT MISMO elements —
TERMS_OF_LOAN/BaseLoanAmount and TERMS_OF_LOAN/NoteAmount. On an FHA loan the borrower signs for the base
amount PLUS the financed upfront premium, so the difference between them IS the premium. On the three
conventional MISMO fixtures in the repo the two are equal, which is exactly right.

⚠️ ONLY THE UPFRONT PREMIUM IS EVALUATED. No document type in the system carries a monthly MIP figure for
this loan, so the annual leg is deliberately unbuilt rather than built on an invented input — and ML
2023-05's per-cell annual rate matrix, which was not obtained, is therefore not needed and is written
nowhere. Logged in docs/domain/priya-open-questions.md.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.verification.eval.fire_path_scenarios import (
    build_mi4_conventional_snapshot,
    build_mi4_correct_ufmip_snapshot,
    build_mi4_no_note_amount_snapshot,
    build_mi4_no_ufmip_financed_snapshot,
    build_mi4_over_ufmip_snapshot,
    build_mi4_under_ufmip_snapshot,
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
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("MI-4",))
    assert len(evaluations) == 1, f"MI-4 is loan-scoped, got {evaluations}"
    return evaluations[0].verdict


# --------------------------------------------------------------------------- #
# The upfront premium — $300,000 base x 1.75% = $5,250, so a correct note is $305,250
# --------------------------------------------------------------------------- #
async def test_a_correct_upfront_premium_is_satisfied() -> None:
    assert await _one(build_mi4_correct_ufmip_snapshot) is Verdict.SATISFIED


async def test_a_premium_above_the_published_rate_fires() -> None:
    """$310,000 on a $300,000 base = 3.33% — the borrower is charged more than the programme requires."""
    assert await _one(build_mi4_over_ufmip_snapshot) is Verdict.FIRED


async def test_a_premium_below_the_published_rate_fires() -> None:
    """$303,000 on a $300,000 base = 1.00% — short of the required premium."""
    assert await _one(build_mi4_under_ufmip_snapshot) is Verdict.FIRED


async def test_no_premium_financed_is_needs_review_not_fired() -> None:
    """⚠️ THE UNDETECTABLE-EXEMPTION CASE. Note == base means nothing was financed — but the premium may
    have been paid in cash at closing, and a Section 248 (Indian Lands) mortgage is exempt entirely. No
    field in the system identifies either, so this row ASKS rather than asserts."""
    verdict = await _one(build_mi4_no_ufmip_financed_snapshot)
    assert verdict is Verdict.NEEDS_REVIEW
    assert verdict is not Verdict.FIRED


async def test_the_outcome_order_is_first_match_wins_with_a_terminal_row() -> None:
    """Ordered, with a MANDATORY terminal row. The 'nothing financed' row must precede the 'below the
    rate' row — otherwise a note equal to its base would fire as an under-payment instead of asking."""
    outcomes = load_rule_spec("MI-4").deterministic.outcomes
    assert [o.verdict for o in outcomes] == ["fired", "needs_review", "fired", "satisfied"]
    assert outcomes[-1].default is True


# --------------------------------------------------------------------------- #
# ⚠️ THE PROGRAM AXIS — the FHA side
# --------------------------------------------------------------------------- #
async def test_a_conventional_file_is_not_applicable_not_fired() -> None:
    """The SAME note == base that needs_reviews on an FHA file. A conventional loan owes no upfront MIP
    at all, so MI-4 must not reach it."""
    verdict = await _one(build_mi4_conventional_snapshot)
    assert verdict is Verdict.NOT_APPLICABLE
    assert verdict is not Verdict.NEEDS_REVIEW


def test_the_program_scoping_is_an_applicability_predicate() -> None:
    applicability = load_rule_spec("MI-4").deterministic.applicability
    assert applicability is not None
    assert (applicability.tag, applicability.op, applicability.value) == (
        "program.type",
        "eq",
        "fha",
    )


async def test_lf6t3n_abstains() -> None:
    """LF-6T3N states no loan program — surfaced, not skipped."""
    snapshot = await materialize_tags(build_lf6t3n_snapshot(), only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("MI-4",))
    assert [e.verdict for e in evaluations] == [Verdict.COULDNT_CHECK]


# --------------------------------------------------------------------------- #
# Fail closed, and the threshold's provenance
# --------------------------------------------------------------------------- #
async def test_a_missing_note_amount_couldnt_checks_never_satisfied() -> None:
    verdict = await _one(build_mi4_no_note_amount_snapshot)
    assert verdict is Verdict.COULDNT_CHECK
    assert verdict is not Verdict.SATISFIED


async def test_the_rate_is_computed_from_two_distinct_mismo_amounts() -> None:
    """The non-vacuity, proven by value through a real materialisation: 305250 - 300000 = 5250, which is
    1.75% of 300000."""
    snapshot = await materialize_tags(build_mi4_correct_ufmip_snapshot(), only_groups=frozenset())
    tag = snapshot.tags.by_subject["loan"]["mi.fha_ufmip_percent"]
    assert Decimal(str(tag.value)) == Decimal("1.7500")


def test_the_published_rate_and_its_tolerance_live_in_the_spec() -> None:
    """⚠️ TIER P — HUD Mortgagee Letter 2023-05, published 2023-02-22, read this pass. The tolerance is a
    ROUNDING allowance, not a domain threshold nobody signs off (the AS-3 / CL-1 precedent)."""
    values = load_rule_spec("MI-4").reference_values.values
    assert values["fha_ufmip_percent"] == "1.75"
    assert values["fha_ufmip_max_percent"] == "1.76"
    assert values["fha_ufmip_min_percent"] == "1.74"


def test_no_annual_mip_rate_is_written_into_the_spec() -> None:
    """⚠️ THE MATRIX WAS NOT OBTAINED, so nothing from it is recorded. MI-4 does not evaluate the annual
    premium — no document carries one — and writing an unused threshold into a spec invites a later
    reader to build against a number nobody read. If someone adds one, this fails."""
    values = load_rule_spec("MI-4").reference_values.values
    assert not [k for k in values if "annual" in k], (
        "MI-4 evaluates only the UPFRONT premium; an annual rate here would be an unread number"
    )


def test_mi4_is_live_and_earned_it_through_the_gate() -> None:
    bars = load_activation_bars()
    assert "MI-4" in ACTIVE_RULE_IDS
    assert is_eligible(bars["MI-4"])
    # ⚠️ no-ai-dependency → is_eligible reads input_resolves alone; `validated` is not read, so it is
    # left false rather than set decoratively. The bar's comment records why.
    assert bars["MI-4"].validated is False


def test_mi4_reads_no_distrusted_tag() -> None:
    gated = set(load_rule_spec("MI-4").deterministic.gated_tags)
    assert not (gated & set(distrusted_tag_ids()))


# --------------------------------------------------------------------------- #
# LP-488 review — the spec's numbers must not drift from the code that computes them
# --------------------------------------------------------------------------- #
def _mi4_values() -> dict[str, str]:
    return dict(load_rule_spec("MI-4").reference_values.values)


def test_the_ufmip_bounds_are_the_rate_plus_and_minus_the_declared_tolerance() -> None:
    """⚠️ THE SILENT-EDIT TRAP (reported finding). fha_ufmip_tolerance_percent is DECLARED and documented
    as the rounding allowance, but the deterministic body binds only max/min — which are independently
    hard-written. So widening the named tolerance to 0.02 changed nothing, and the spec then described a
    rule that did not exist. The DSL cannot compute a reference, so this pins the arithmetic instead:
    edit the tolerance without the bounds and this fails."""
    values = _mi4_values()
    rate = Decimal(values["fha_ufmip_percent"])
    tolerance = Decimal(values["fha_ufmip_tolerance_percent"])
    assert Decimal(values["fha_ufmip_max_percent"]) == rate + tolerance
    assert Decimal(values["fha_ufmip_min_percent"]) == rate - tolerance


def test_the_spec_ufmip_rate_matches_the_calculator_registry_rate() -> None:
    """⚠️ TWO SOURCES OF TRUTH (reported finding). The spec's 1.75% duplicates LP-84's registry rule
    `fha.mip.ufmip_rate` (175 bps), which app/services/mi.py reads to compute the MI the DTI's PITI line
    consumes. A HUD change updating one and not the other leaves the rule and the calculator disagreeing
    about the same loan — silently. This is the same drift argument the ticket makes for the LTV
    arithmetic; it just was not applied here."""
    from app.services.mi import fha_ufmip_rate_bps

    assert Decimal(_mi4_values()["fha_ufmip_percent"]) * 100 == fha_ufmip_rate_bps()
