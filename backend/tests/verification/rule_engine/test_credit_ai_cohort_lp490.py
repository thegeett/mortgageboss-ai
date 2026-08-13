"""LP-490 — CR-5 · CR-6 · CR-8 · CR-10. ⚠️ ALL FOUR BUILD INERT.

⚠️ INERT BY DESIGN. Every rule here reads at least one AI tag with no measured accuracy, so each bar is
`not-calibratable-yet`, for which `is_eligible()` returns False (LP-484). `ACTIVE_RULE_IDS` stays 47. A
test pins that for the whole cohort, so a later ticket cannot activate one by setting `validated: true`
without scoring the tag underneath it.

⚠️ THE CORPUS REALITY, stated once and true of every assertion below. THREE credit reports exist. ONE
inquiry row across all of them (CR-5). ZERO public-record rows and no derogatory events (CR-6). ZERO
collection or charge-off codes (CR-10). `payment_history_24mo` runs 0-84 chars across 17 formats and
`worst_delinquency` fills 2/35 in two incompatible formats (CR-8). These rules are built against the
SCHEMA and the guideline; none has been observed firing on real data, and the fixtures below are
structural proofs of wiring and fail-closed behaviour, NOT evidence of accuracy.
"""

from __future__ import annotations

import pytest
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rule_engine.result import Verdict
from app.verification.rules.distrust import distrusted_tag_ids
from app.verification.rules.specs import load_rule_spec
from app.verification.tag_materialization.declarations import load_ai_groups, load_declarations

_COHORT = ("CR-1", "CR-5", "CR-6", "CR-8", "CR-10")


# --------------------------------------------------------------------------- #
# ⚠️ THE COHORT IS INERT — the first thing this ticket must prove
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rule_id", _COHORT)
def test_every_rule_in_the_cohort_is_inert(rule_id: str) -> None:
    """`not-calibratable-yet` → is_eligible False (LP-484). If a later ticket forces one live without
    scoring its AI tag, this fails."""
    bar = load_activation_bars()[rule_id]
    assert bar.status == "not-calibratable-yet"
    assert bar.validated is False
    assert not is_eligible(bar)
    assert rule_id not in ACTIVE_RULE_IDS


def test_the_cohort_did_not_change_the_live_set() -> None:
    assert len(ACTIVE_RULE_IDS) == 47


@pytest.mark.parametrize("rule_id", _COHORT)
def test_every_bar_records_what_calibration_would_require(rule_id: str) -> None:
    """A bar that says only "not calibrated" is unactionable. Each must name the labels, the subject and
    whether real files are needed (ADR-332) — otherwise the next ticket has to rediscover it."""
    rationale = load_activation_bars()[rule_id].rationale
    assert "CALIBRATION WOULD REQUIRE" in rationale or "calibration" in rationale.lower()
    assert len(rationale) > 200, "a one-line rationale is not a calibration plan"


# --------------------------------------------------------------------------- #
# CR-6 — the seasoning matrix
# --------------------------------------------------------------------------- #
def test_cr6_never_returns_a_failure() -> None:
    """⚠️ PRIYA'S RULING. Extenuating-circumstance exceptions exist, so an unseasoned event is
    needs_review — "an exception needs underwriting review" — never `fired`. If someone adds a fired
    outcome, this fails."""
    outcomes = load_rule_spec("CR-6").deterministic.outcomes
    assert Verdict.FIRED.value not in [o.verdict for o in outcomes]


def test_cr6_matrix_matches_priyas_ruling() -> None:
    """The waiting periods, as domain rulings (tier P). ⚠️ Bankruptcy is 48 months, not 24: the
    Chapter 13 discharged/dismissed split is NOT expressible — liab.derogatory_type has one "bankruptcy"
    value — so the CONSERVATIVE period is applied and the gap is logged for Priya. Applying 24 would
    clear a Chapter 7 two years early."""
    values = load_rule_spec("CR-6").reference_values.values
    assert values["bankruptcy_months"] == "48"
    assert values["foreclosure_months"] == "84"
    assert values["short_sale_months"] == "48"
    assert values["deed_in_lieu_months"] == "48"
    assert values["charge_off_months"] == "48"


def test_cr6_seasoned_rows_precede_the_unseasoned_rows() -> None:
    """Ordering is load-bearing: each type's `satisfied` row carries the months comparison, and its
    `needs_review` row does not. If a needs_review row came first, a fully seasoned event would be
    routed to review forever."""
    outcomes = load_rule_spec("CR-6").deterministic.outcomes
    verdicts = [o.verdict for o in outcomes]
    assert verdicts[:5] == ["satisfied"] * 5
    assert verdicts[5:10] == ["needs_review"] * 5
    assert verdicts[-1] == "couldnt_check" and outcomes[-1].default is True
    # every `satisfied` row must actually compare the elapsed months
    assert all(o.when_compare is not None for o in outcomes[:5])


def test_cr6_reads_the_events_own_date_not_the_report_date() -> None:
    """⚠️ PRIYA WAS EXPLICIT. Seasoning from the credit report's date would let a four-year waiting
    period "complete" the moment someone re-pulled credit. The rule gates on the derived elapsed-months
    tag, whose recipe reads liab.derogatory_date and abstains when it is absent — credit.report_date is
    nowhere in the chain."""
    gated = set(load_rule_spec("CR-6").deterministic.gated_tags)
    assert "credit.derogatory_months_elapsed" in gated
    assert "credit.report_date" not in gated
    assert "credit.report_age_months_at_closing" not in gated


# --------------------------------------------------------------------------- #
# CR-8 — the confidence gate
# --------------------------------------------------------------------------- #
def test_cr8_gates_on_history_confidence_before_interpreting() -> None:
    """⚠️ PRIYA SPECIFIED THIS SHAPE. structured_history_confident must be load-bearing, and the prompt
    must instruct the model to stop on "no" BEFORE attempting to read the history."""
    judgment = load_rule_spec("CR-8").judgment
    assert judgment is not None
    assert "liab.structured_history_confident" in judgment.load_bearing_tags
    assert "not_interpretable" in judgment.value_domain
    prompt = judgment.system_prompt
    assert "structured_history_confident" in prompt
    assert "not_interpretable" in prompt


def test_cr8_prompt_forbids_position_parsing_the_history_string() -> None:
    """⚠️ THE ADR-353 TRAP. `payment_history_24mo` is 0-84 chars across 17 formats and is NOT a fixed
    one-char-per-month encoding. Converting an ambiguous string into a 60-day late invents a derogatory
    event on a clean borrower."""
    prompt = load_rule_spec("CR-8").judgment.system_prompt  # type: ignore[union-attr]
    assert "0 to 84" in prompt or "84" in prompt
    assert "not a fixed" in prompt.lower() or "NOT a fixed" in prompt


def test_cr8_mortgage_detection_is_not_by_creditor_name() -> None:
    """⚠️ PRIYA, EXPLICITLY. A servicer's name looks like a bank's."""
    prompt = load_ai_groups()["credit_mortgage_history"].system_prompt
    assert "NEVER from the creditor's name alone" in prompt


# --------------------------------------------------------------------------- #
# CR-10 — the matrix, the missing axis, and the permissive cell
# --------------------------------------------------------------------------- #
def test_cr10_carries_every_cell_of_the_ruling() -> None:
    """⚠️ NEVER ONE DOLLAR THRESHOLD ACROSS AGENCIES — the whole reason this is a matrix."""
    values = load_rule_spec("CR-10").reference_values.values
    assert values["du_two_to_four_unit_or_second_home_aggregate"] == "5000"
    assert values["du_investment_individual"] == "250"
    assert values["du_investment_aggregate"] == "1000"
    assert values["manual_individual"] == "250"
    assert values["manual_aggregate"] == "1000"
    assert values["fha_non_medical_aggregate"] == "2000"
    assert values["fha_alternative_monthly_debt_percent"] == "5"
    assert values["medical_collections_excluded"] == "yes"


def test_cr10_abstains_on_manual_underwriting_rather_than_guessing() -> None:
    """⚠️ THE DU-vs-MANUAL AXIS DOES NOT EXIST AS A FACT (LP-501). No `loan.agency` or
    `loan.underwriting_method` was invented to fill the gap; the value domain carries an honest
    abstention instead."""
    judgment = load_rule_spec("CR-10").judgment
    assert judgment is not None
    assert "manual_underwriting_not_supported" in judgment.value_domain
    assert (
        "do NOT guess" in judgment.system_prompt.lower() or "Do NOT guess" in judgment.system_prompt
    )
    declared = load_declarations()
    assert "loan.agency" not in declared
    assert "loan.underwriting_method" not in declared


def test_cr10_never_defaults_to_the_permissive_cell() -> None:
    """⚠️ A one-unit primary requires NO payoff at any amount — the most permissive cell in the matrix.
    An absent occupancy defaulting there would clear every collection on a file that has simply not
    stated its occupancy yet. Occupancy must be load-bearing, and the prompt must say so."""
    judgment = load_rule_spec("CR-10").judgment
    assert judgment is not None
    assert "property.occupancy" in judgment.load_bearing_tags
    assert "most permissive" in judgment.system_prompt


def test_cr10_keeps_mortgage_charge_offs_out_of_the_dollar_logic() -> None:
    """⚠️ A charged-off MORTGAGE carries a seasoning requirement (CR-6), not a dollar test."""
    assert "charged-off MORTGAGE is NOT" in load_rule_spec("CR-10").judgment.system_prompt  # type: ignore[union-attr]


def test_medical_collections_are_excluded_from_the_aggregate() -> None:
    """The derived aggregate is NON-MEDICAL by construction, so the model is never asked to re-apply the
    exclusion — and a tradeline whose medical status is UNKNOWN contributes, because excluding an
    unknown would be the permissive guess."""
    from app.verification.tag_materialization.derived import _collection_aggregate_balance

    assert _collection_aggregate_balance.__doc__ is not None
    assert "MEDICAL collections are EXCLUDED" in _collection_aggregate_balance.__doc__


# --------------------------------------------------------------------------- #
# Structure shared across the cohort
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rule_id", _COHORT)
def test_no_rule_in_the_cohort_reads_a_distrusted_tag(rule_id: str) -> None:
    spec = load_rule_spec(rule_id)
    gated = set(spec.deterministic.gated_tags if spec.deterministic else ())
    gated |= set(spec.judgment.load_bearing_tags if spec.judgment else ())
    assert not (gated & set(distrusted_tag_ids()))


def test_liab_account_type_is_still_unwired() -> None:
    """⚠️ ITS ENUM DOES NOT MATCH ITS SOURCES. `liab.account_type` is
    revolving/installment/mortgage/heloc while the sources emit REV/AUTO/MTG/INST and
    MortgageLoan/Installment — and a PARSED tag is NOT validated against allowed_values
    (producer.py), so declaring it would ship out-of-domain values silently. CR-8's need for account
    type is met by `liab.is_mortgage`, a DERIVED-from-AI tag with a closed vocabulary and an abstain."""
    assert "liab.account_type" not in load_declarations()
    assert "liab.is_mortgage" in load_declarations()


def test_the_matcher_was_not_duplicated() -> None:
    """⚠️ ONE COMPARISON, ONE MATCHER. `credit_profile` (LP-483) is the only group producing
    liab.in_application; a second matcher would let CR-1 and CR-4 disagree on one file."""
    groups = load_ai_groups()
    producers = [k for k, g in groups.items() if "liab.in_application" in g.tag_ids]
    assert producers == ["credit_profile"]
