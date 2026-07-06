"""FHA MIP (Mortgage Insurance Premium) rules (LP-84) — grounded starters.

MIP has **NO Conventional analog** — it is FHA-DEFINING, and the reason these rules
can't be cloned from LP-82/83. ~6 rules as ``program=fha``, GROUNDED STARTERS
researched against HUD Handbook 4000.1 Appendix 1.0 (retrieved 2026-06), every rule
``starter=True``, pending Priya's validation. Every FHA loan MUST carry MIP, so a
missing premium is a finding.

  • **Upfront MIP (UFMIP): 1.75% (175 bps)** of the base loan amount, all FHA
    mortgages (typically financed into the loan). A present-check + a rate-as-data
    rule (overlay/ML-letter-overrideable).
  • **Annual MIP: ~0.15%-0.75%** depending on base loan amount, LTV, and term (most
    30-year borrowers pay 0.55%). The rate is a TABLE (LTV/amount/term-tiered) — the
    starter encodes the upper bound (≤75 bps) as rate-as-data, marked TO VERIFY.
  • **MIP DURATION (the high-value rule, reads LP-77's LTV):** LTV **≤ 90%**
    (≥10% down) → annual MIP for **11 years**; LTV **> 90%** (<10% down) → annual MIP
    for the **LIFE OF THE LOAN** (the full term). Encoded as two LTV-gated rules.

**Category note:** there is no dedicated ``MORTGAGE_INSURANCE`` FindingCategory, and
adding one would require a migration (the category column is a CHECK-constrained
VARCHAR). To stay migration-free these MIP rules use ``DOCUMENTATION`` (MIP setup is
verified on the file); a dedicated MI category is a deferred typed-core promotion.

**Cross-link:** the duration rules CONSUME LP-77's computed ``ltv.ltv_pct`` (read,
never recompute) — promotion-pending, evaluated via constructed facts today.
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

# Duration gates on LP-77's LTV: > 90% → life of loan; ≤ 90% → 11 years.
_LTV_OVER_90 = RuleGate(
    reads="ltv.ltv_pct", condition=Condition(op=Operator.GT, value=Decimal("90"))
)
_LTV_AT_OR_UNDER_90 = RuleGate(
    reads="ltv.ltv_pct", condition=Condition(op=Operator.LE, value=Decimal("90"))
)

_PRESENT = Condition(op=Operator.GE, value=Decimal("1"), unit="boolean")


FHA_MIP_UFMIP_PRESENT = fha_rule(
    "fha.mip.ufmip_present",
    reads=("mip.ufmip_present",),
    condition=_PRESENT,
    severity=RuleSeverity.RED,
    category=FindingCategory.DOCUMENTATION,
    description="Upfront MIP is present on the loan (every FHA loan must carry UFMIP).",
    source=hud("Appendix 1.0"),
    notes=(
        "STARTER — the missing-MIP finding: an FHA loan MUST have upfront MIP (typically financed). "
        "Absent → RED. Promotion pending: mip.ufmip_present."
    ),
)

FHA_MIP_UFMIP_RATE = fha_rule(
    "fha.mip.ufmip_rate",
    reads=("mip.ufmip_rate_bps",),
    condition=Condition(op=Operator.EQ, value=Decimal("175"), unit="bps"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="Upfront MIP is 1.75% (175 bps) of the base loan amount.",
    source=hud("Appendix 1.0"),
    notes=(
        "STARTER — UFMIP is 1.75% = 175 bps of the base loan amount (rate-as-data, overlay / "
        "Mortgagee-Letter overrideable). Promotion pending: mip.ufmip_rate_bps."
    ),
)

FHA_MIP_ANNUAL_PRESENT = fha_rule(
    "fha.mip.annual_present",
    reads=("mip.annual_present",),
    condition=_PRESENT,
    severity=RuleSeverity.RED,
    category=FindingCategory.DOCUMENTATION,
    description="Annual MIP is present on the loan (every FHA loan must carry annual MIP).",
    source=hud("Appendix 1.0"),
    notes=(
        "STARTER — the other half of the missing-MIP finding: annual MIP must be scheduled. Absent → "
        "RED. Promotion pending: mip.annual_present."
    ),
)

FHA_MIP_ANNUAL_RATE = fha_rule(
    "fha.mip.annual_rate",
    reads=("mip.annual_rate_bps",),
    condition=Condition(op=Operator.LE, value=Decimal("75"), unit="bps"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="Annual MIP is within the FHA rate range (~0.15%-0.75%; most 30-year pay 0.55%).",
    source=hud("Appendix 1.0", to_verify=True),
    notes=(
        "STARTER — annual MIP is a rate TABLE tiered by base loan amount, LTV, and term (~15-75 bps; "
        "most 30-year borrowers 55 bps). The ≤75 bps starter is the upper bound; the exact table is "
        "TO VERIFY + rate-as-data overrideable. Promotion pending: mip.annual_rate_bps."
    ),
)

FHA_MIP_DURATION_HIGH_LTV_LIFE = fha_rule(
    "fha.mip.duration_high_ltv_life",
    reads=("mip.duration_is_life",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    gate=_LTV_OVER_90,
    description="LTV over 90% → annual MIP runs for the life of the loan.",
    source=hud("Appendix 1.0"),
    notes=(
        "STARTER — the LTV-driven duration rule: GATED to LTV > 90% (gate reads LP-77's ltv.ltv_pct); "
        "when it applies, annual MIP must run for the LIFE OF THE LOAN (the full term). Promotion "
        "pending: mip.duration_is_life (+ ltv.ltv_pct for the gate)."
    ),
)

FHA_MIP_DURATION_LOW_LTV_11YR = fha_rule(
    "fha.mip.duration_low_ltv_11yr",
    reads=("mip.duration_months",),
    condition=Condition(op=Operator.LE, value=Decimal("132"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    gate=_LTV_AT_OR_UNDER_90,
    description="LTV at or under 90% → annual MIP runs for 11 years (132 months).",
    source=hud("Appendix 1.0"),
    notes=(
        "STARTER — the other LTV tier: GATED to LTV ≤ 90% (≥10% down); annual MIP then terminates at "
        "11 years (132 months). Promotion pending: mip.duration_months (+ ltv.ltv_pct for the gate)."
    ),
)


FHA_MIP_RULES: tuple[VerificationRule, ...] = (
    FHA_MIP_UFMIP_PRESENT,
    FHA_MIP_UFMIP_RATE,
    FHA_MIP_ANNUAL_PRESENT,
    FHA_MIP_ANNUAL_RATE,
    FHA_MIP_DURATION_HIGH_LTV_LIFE,
    FHA_MIP_DURATION_LOW_LTV_11YR,
)
