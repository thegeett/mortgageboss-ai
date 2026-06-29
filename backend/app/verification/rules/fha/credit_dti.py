"""FHA CREDIT + DTI rules (LP-84) — grounded starters into the LP-74 engine.

================================ READ THIS FIRST ================================
~14 FHA rules (credit 8 + DTI 6) poured into the LP-74 engine as ``program=fha``
(CONTENT, not mechanism), the same shape + posture as the Conventional LP-82/83
content: **GROUNDED STARTERS** researched against the current HUD Handbook 4000.1
(retrieved 2026-06) with real section citations, every rule ``starter=True`` and
pending the domain expert's (Priya's) validation. FHA is GENUINELY DIFFERENT from
Conventional — these encode FHA's own structures, not Conventional patterns:

  • **MDCS is TIERED to the down payment — NOT a flat "min 580".** The Minimum
    Decision Credit Score sets the minimum required investment: **580+ → 3.5% down**
    (96.5% LTV); **500-579 → 10% down** (90% LTV); **below 500 → ineligible** for
    FHA-insured financing (II.A.4 / II.A.5). Encoded as an eligibility floor (≥500),
    the 3.5%-tier threshold (≥580), and a gated low-tier rule that requires 10% down
    when the score is 500-579.
  • **Manual-underwriting triggers (the "conservative flag"):** a score below 620
    (and/or a DTI above 43%) routes the file to MANUAL underwriting, where the
    underwriter evaluates compensating factors (vs the TOTAL Mortgage Scorecard AUS).
  • **DTI is the COMPENSATING-FACTORS model — NOT a hard DU-style ceiling.** Baseline
    31% front / 43% back (II.A.5); with documented compensating factors a manually
    underwritten file may go up to **40% front / 50% back**. Encoded as the MITIGABLE
    model: the baseline finding is YELLOW (a flag resolvable by DOCUMENTING a
    compensating factor via LP-75's resolution — OVERRIDDEN-with-reason / APPLIED),
    escalating to a RED hard finding only past the 40/50 uplifted ceiling.

**Cross-links (confirm, don't duplicate):** the DTI rules CONSUME LP-76's computed
``dti.front_end_pct`` / ``dti.back_end_pct`` (read them, never recompute).
``dti.back_end_pct`` is promoted today (evaluable); ``dti.front_end_pct`` is
promotion-pending. The sample ``fha.dti.back_end_max`` (LP-74 plumbing, a 57% sample
placeholder) is SUPERSEDED by these grounded rules.

**Overlays are explicitly common in FHA:** most lenders set 580-640 floors over FHA's
500/580 — Sun-West / UWM overlays tighten the MDCS + DTI. Because each threshold is
data, an overlay overrides it by ``rule_id`` (LP-80) — a strong enforcement case.

**Typed-core promotion:** the credit facts (``credit.mdcs``, derogatory months,
``down_payment.pct``) and ``dti.front_end_pct`` are promotion-pending (``notes`` say
so); the engine records those rules not-evaluated (graceful) until the facts land.
================================================================================
"""

from __future__ import annotations

from decimal import Decimal

from app.models.finding import FindingCategory
from app.verification.rules.fha._base import fha_rule, hud
from app.verification.rules.schema import (
    Condition,
    Operator,
    RuleGate,
    RuleSeverity,
    VerificationRule,
)

# Applicability gates (LP-83 mechanism, FHA content).
# A score in the 500-579 band (below the 3.5%-down tier, at/above the eligibility floor).
_LOW_MDCS_TIER = RuleGate(
    reads="credit.mdcs", condition=Condition(op=Operator.LT, value=Decimal("580"))
)
# Back-end DTI strictly above the 43% baseline → the compensating-factors regime applies.
_OVER_BACK_END_BASELINE = RuleGate(
    reads="dti.back_end_pct", condition=Condition(op=Operator.GT, value=Decimal("43"))
)

_PRESENT = Condition(op=Operator.GE, value=Decimal("1"), unit="boolean")


# --------------------------------------------------------------------------- #
# CREDIT (HUD 4000.1 II.A) — the TIERED MDCS + manual-underwriting triggers
# --------------------------------------------------------------------------- #

FHA_CREDIT_MDCS_ELIGIBILITY_FLOOR = fha_rule(
    "fha.credit.mdcs_eligibility_floor",
    reads=("credit.mdcs",),
    condition=Condition(op=Operator.GE, value=Decimal("500"), unit="score"),
    severity=RuleSeverity.RED,
    category=FindingCategory.CREDIT,
    description="The Minimum Decision Credit Score is at least 500 (below 500 is ineligible for FHA).",
    source=hud("II.A.4"),
    notes=(
        "STARTER — the FHA eligibility FLOOR: a Minimum Decision Credit Score (MDCS) below 500 is "
        "NOT eligible for FHA-insured financing. This is the hard tier; see "
        "fha.credit.mdcs_minimum_down_3_5_tier + fha.credit.mdcs_low_tier_down_payment for the "
        "down-payment tiering above it. A prime validate-with-Priya item. Promotion pending: credit.mdcs."
    ),
)

FHA_CREDIT_MDCS_3_5_TIER = fha_rule(
    "fha.credit.mdcs_minimum_down_3_5_tier",
    reads=("credit.mdcs",),
    condition=Condition(op=Operator.GE, value=Decimal("580"), unit="score"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.CREDIT,
    description="An MDCS of 580+ qualifies for the 3.5% minimum down payment (96.5% LTV).",
    source=hud("II.A.4"),
    notes=(
        "STARTER — TIERED, do NOT read as a flat 'min 580': MDCS 580+ → 3.5% minimum down payment; "
        "500-579 → 10% minimum down (see fha.credit.mdcs_low_tier_down_payment); <500 → ineligible "
        "(fha.credit.mdcs_eligibility_floor). A score in 500-579 flags for the 10%-down tier (YELLOW, "
        "not a block). Promotion pending: credit.mdcs."
    ),
)

FHA_CREDIT_MDCS_LOW_TIER_DOWN_PAYMENT = fha_rule(
    "fha.credit.mdcs_low_tier_down_payment",
    reads=("down_payment.pct",),
    condition=Condition(op=Operator.GE, value=Decimal("10"), unit="percent"),
    severity=RuleSeverity.RED,
    category=FindingCategory.CREDIT,
    gate=_LOW_MDCS_TIER,
    description="An MDCS of 500-579 requires a minimum 10% down payment (max 90% LTV).",
    source=hud("II.A.4"),
    notes=(
        "STARTER — the tiered consequence: GATED to a 500-579 MDCS (gate: credit.mdcs < 580). When the "
        "score is in that band the minimum required investment rises to 10% (LTV capped at 90%). For a "
        "580+ score the gate is closed and the standard 3.5% applies. Promotion pending: credit.mdcs + "
        "down_payment.pct."
    ),
)

FHA_CREDIT_MANUAL_UW_SCORE_TRIGGER = fha_rule(
    "fha.credit.manual_underwriting_score_trigger",
    reads=("credit.mdcs",),
    condition=Condition(op=Operator.GE, value=Decimal("620"), unit="score"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.CREDIT,
    description="A score below 620 routes the file to manual underwriting (compensating factors).",
    source=hud("II.A.5", to_verify=True),
    notes=(
        "STARTER — the FHA 'conservative flag': a score below 620 (and/or a DTI above 43% — see "
        "fha.dti.compensating_factors_required) routes to MANUAL underwriting, where the underwriter "
        "evaluates compensating factors, vs the TOTAL Mortgage Scorecard AUS path. The exact AUS-vs-"
        "manual routing thresholds are TO VERIFY against II.A.5. Promotion pending: credit.mdcs."
    ),
)

FHA_CREDIT_MDCS_PRESENT = fha_rule(
    "fha.credit.minimum_decision_score_present",
    reads=("credit.mdcs_present",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.CREDIT,
    description="A Minimum Decision Credit Score is determinable (else nontraditional credit applies).",
    source=hud("II.A.4", to_verify=True),
    notes=(
        "STARTER — when no MDCS can be derived, FHA's nontraditional / insufficient-credit guidance "
        "applies (manual underwriting). Section TO VERIFY. Promotion pending: credit.mdcs_present."
    ),
)

FHA_CREDIT_DEROG_BANKRUPTCY_CH7 = fha_rule(
    "fha.credit.derogatory_bankruptcy_ch7_waiting",
    reads=("credit.months_since_ch7_bankruptcy",),
    condition=Condition(op=Operator.GE, value=Decimal("24"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.CREDIT,
    description="A Chapter 7 bankruptcy waiting period (~2 years) has elapsed before the case number.",
    source=hud("II.A.5", to_verify=True),
    notes=(
        "STARTER — FHA waiting periods are SHORTER than Conventional (~2 years after Chapter 7). The "
        "exact period + citation are TO VERIFY against II.A.5 (extenuating circumstances can shorten "
        "it). Promotion pending: credit.months_since_ch7_bankruptcy."
    ),
)

FHA_CREDIT_DEROG_FORECLOSURE = fha_rule(
    "fha.credit.derogatory_foreclosure_waiting",
    reads=("credit.months_since_foreclosure",),
    condition=Condition(op=Operator.GE, value=Decimal("36"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.CREDIT,
    description="A foreclosure waiting period (~3 years) has elapsed before the case number.",
    source=hud("II.A.5", to_verify=True),
    notes=(
        "STARTER — ~3 years after a foreclosure (shorter than Conventional's ~7). Exact period + "
        "citation TO VERIFY. Promotion pending: credit.months_since_foreclosure."
    ),
)

FHA_CREDIT_DEROG_CH13 = fha_rule(
    "fha.credit.derogatory_ch13_seasoning",
    reads=("credit.months_into_ch13",),
    condition=Condition(op=Operator.GE, value=Decimal("12"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.CREDIT,
    description="At least ~1 year of a Chapter 13 plan has elapsed with satisfactory payment.",
    source=hud("II.A.5", to_verify=True),
    notes=(
        "STARTER — FHA permits a Chapter 13 in progress with ~1 year of on-time plan payments + court "
        "approval (distinct from Chapter 7). Exact period + citation TO VERIFY. Promotion pending: "
        "credit.months_into_ch13."
    ),
)


# --------------------------------------------------------------------------- #
# DTI (HUD 4000.1 II.A.5) — the compensating-factors "conservative-flag" model
# --------------------------------------------------------------------------- #

FHA_DTI_FRONT_END_BASELINE = fha_rule(
    "fha.dti.front_end_baseline",
    reads=("dti.front_end_pct",),
    condition=Condition(op=Operator.LE, value=Decimal("31"), unit="percent"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.INCOME,
    description="Front-end (housing) ratio is at or under the 31% FHA baseline.",
    source=hud("II.A.5"),
    notes=(
        "STARTER — the MITIGABLE baseline (not a hard cutoff): over 31% is a YELLOW flag resolvable by "
        "DOCUMENTING a compensating factor (LP-75 resolution — OVERRIDDEN-with-reason / APPLIED); it "
        "becomes hard only past the 40% uplifted ceiling (fha.dti.front_end_max_with_factors). CONSUMES "
        "LP-76's computed dti.front_end_pct (does not recompute). Promotion pending: dti.front_end_pct."
    ),
)

FHA_DTI_FRONT_END_MAX = fha_rule(
    "fha.dti.front_end_max_with_factors",
    reads=("dti.front_end_pct",),
    condition=Condition(op=Operator.LE, value=Decimal("40"), unit="percent"),
    severity=RuleSeverity.RED,
    category=FindingCategory.INCOME,
    description="Front-end ratio is at or under 40% even with documented compensating factors.",
    source=hud("II.A.5"),
    notes=(
        "STARTER — the HARD front-end ceiling: with documented compensating factors a manually "
        "underwritten file may reach 40% front-end; beyond that is RED (compensating factors cannot "
        "rescue it). The uplifted tier above fha.dti.front_end_baseline. CONSUMES dti.front_end_pct. "
        "Promotion pending: dti.front_end_pct."
    ),
)

FHA_DTI_BACK_END_BASELINE = fha_rule(
    "fha.dti.back_end_baseline",
    reads=("dti.back_end_pct",),
    condition=Condition(op=Operator.LE, value=Decimal("43"), unit="percent"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.INCOME,
    description="Back-end (total) DTI is at or under the 43% FHA baseline.",
    source=hud("II.A.5"),
    notes=(
        "STARTER — the MITIGABLE baseline: over 43% is a YELLOW flag resolvable by documenting a "
        "compensating factor (LP-75 resolution), hard only past the 50% uplifted ceiling "
        "(fha.dti.back_end_max_with_factors). A DTI over 43% also routes to MANUAL underwriting "
        "(the AUS-vs-manual distinction). CONSUMES LP-76's computed dti.back_end_pct (evaluable today)."
    ),
)

FHA_DTI_BACK_END_MAX = fha_rule(
    "fha.dti.back_end_max_with_factors",
    reads=("dti.back_end_pct",),
    condition=Condition(op=Operator.LE, value=Decimal("50"), unit="percent"),
    severity=RuleSeverity.RED,
    category=FindingCategory.INCOME,
    description="Back-end DTI is at or under 50% even with documented compensating factors.",
    source=hud("II.A.5"),
    notes=(
        "STARTER — the HARD back-end ceiling: documented compensating factors lift the manual maximum "
        "to ~50%; beyond that is RED. SUPERSEDES the LP-74 sample fha.dti.back_end_max (a 57% "
        "placeholder). The exact two-factor maxima are a validate-with-Priya item. CONSUMES "
        "dti.back_end_pct."
    ),
)

FHA_DTI_COMPENSATING_FACTORS_REQUIRED = fha_rule(
    "fha.dti.compensating_factors_required",
    reads=("dti.compensating_factor_count",),
    condition=Condition(op=Operator.GE, value=Decimal("1"), unit="count"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.INCOME,
    gate=_OVER_BACK_END_BASELINE,
    description="Over the 43% baseline, at least one documented compensating factor is present.",
    source=hud("II.A.5", to_verify=True),
    notes=(
        "STARTER — the explicit conservative-flag/Accept-risk encoding: GATED to a back-end DTI above "
        "43% (gate: dti.back_end_pct > 43); when it applies, at least one DOCUMENTED compensating "
        "factor is required (substantial reserves, conservative credit use + excellent history, "
        "residual income, minimal payment shock). Resolvable via the LP-75 resolution flow. Exact "
        "factor list + count TO VERIFY. Promotion pending: dti.compensating_factor_count."
    ),
)

FHA_DTI_PAYMENT_SHOCK_REVIEWED = fha_rule(
    "fha.dti.payment_shock_reviewed",
    reads=("dti.payment_shock_pct",),
    condition=Condition(op=Operator.LE, value=Decimal("100"), unit="percent"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.INCOME,
    description="Payment shock (housing-payment increase) is reviewed as a compensating-factor input.",
    source=hud("II.A.5", to_verify=True),
    notes=(
        "STARTER — minimal payment shock is a documented compensating factor; a large increase is "
        "reviewed. The 100% starter threshold + section are TO VERIFY. Promotion pending: "
        "dti.payment_shock_pct."
    ),
)


FHA_CREDIT_RULES: tuple[VerificationRule, ...] = (
    FHA_CREDIT_MDCS_ELIGIBILITY_FLOOR,
    FHA_CREDIT_MDCS_3_5_TIER,
    FHA_CREDIT_MDCS_LOW_TIER_DOWN_PAYMENT,
    FHA_CREDIT_MANUAL_UW_SCORE_TRIGGER,
    FHA_CREDIT_MDCS_PRESENT,
    FHA_CREDIT_DEROG_BANKRUPTCY_CH7,
    FHA_CREDIT_DEROG_FORECLOSURE,
    FHA_CREDIT_DEROG_CH13,
)

FHA_DTI_RULES: tuple[VerificationRule, ...] = (
    FHA_DTI_FRONT_END_BASELINE,
    FHA_DTI_FRONT_END_MAX,
    FHA_DTI_BACK_END_BASELINE,
    FHA_DTI_BACK_END_MAX,
    FHA_DTI_COMPENSATING_FACTORS_REQUIRED,
    FHA_DTI_PAYMENT_SHOCK_REVIEWED,
)

# The full LP-84 credit + DTI set: credit (8) + DTI (6).
FHA_CREDIT_DTI_RULES: tuple[VerificationRule, ...] = (
    *FHA_CREDIT_RULES,
    *FHA_DTI_RULES,
)
