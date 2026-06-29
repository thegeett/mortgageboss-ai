"""Conventional INCOME + ASSET rules (LP-82) — GROUNDED STARTERS, validate with Priya.

================================ READ THIS FIRST ================================
These ~20 Conventional rules are **CONTENT poured into the LP-74 engine** — they are
not new mechanism. They are **GROUNDED STARTERS**: researched against the *current*
Fannie Mae Selling Guide (retrieved 2026-06) with real B-section citations + current
values, but **NOT authoritative final rules**. They belong to the domain expert
(Priya, an active Conventional/FHA processor); she validates + corrects them against
the live guide for her lenders/scenarios. Every rule carries ``starter=True``.

Why even grounded research isn't authoritative (the honest reason for the marker):

  • the Selling Guide changes frequently (the Income Assessment chapter B3-3 was
    rewritten in 03/2026 — see ``conv.income.base_doc_w2_paystub``);
  • many requirements are **DU-message-driven** (large-deposit documentation, reserves
    — NOT fixed Selling-Guide constants); the starter thresholds here are placeholders;
  • **lender overlays** (UWM / Sun-West, LP-80) tighten the investor defaults — and
    because each threshold is data, an overlay overrides it by ``rule_id``.

The research corrected folk-knowledge: document age is **4 months** on the note date
(B1-1-03), NOT 30 days; base income is now the **most recent W-2 + pay stub** (03/2026),
NOT two years of W-2s. Citations are researched, not invented — where a subsection is
uncertain a rule's source carries ``to_verify=True``.

**Typed-core promotion (LP-74 design — the typed core grows as rules need it):** a few
rules are EVALUABLE today from stated structured data (self-employment income, gift,
retirement, large deposit, reserves); the rest read a canonical typed-field path whose
fact isn't produced yet — their ``notes`` say "typed-core promotion pending: <fact>"
and the engine records them not-evaluated (graceful) until the fact lands.
================================================================================
"""

from __future__ import annotations

from decimal import Decimal

from app.models.finding import FindingCategory
from app.verification.rules.conventional._base import conv_rule as _conv_rule
from app.verification.rules.conventional._base import sg as _sg
from app.verification.rules.conventional.credit_property_docs import (
    CONVENTIONAL_CREDIT_PROPERTY_DOC_RULES,
)
from app.verification.rules.schema import (
    Condition,
    Operator,
    RuleSeverity,
    RuleSource,
    VerificationRule,
)

# A 0/1 "presence" fact compared with GE 1 ("must be present") or LE 0 ("present →
# fires a documentation/verification requirement"). The unit labels the datum.

# --------------------------------------------------------------------------- #
# INCOME (~10)
# --------------------------------------------------------------------------- #

CONV_INCOME_DOC_AGE = _conv_rule(
    "conv.income.credit_doc_age",
    reads=("documents.income.most_recent_age_months",),
    condition=Condition(op=Operator.LE, value=Decimal("4"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="Income/credit documents are no more than 4 months old on the note date.",
    source=_sg("B1-1-03"),
    notes=(
        "STARTER (validate with Priya). 4-month doc age CORRECTS the folk '30-day pay stub'. "
        "Typed-core promotion pending: documents.income.most_recent_age_months."
    ),
)

CONV_INCOME_BASE_DOC = _conv_rule(
    "conv.income.base_doc_w2_paystub",
    reads=("documents.income.base.w2_and_paystub_present",),
    condition=Condition(op=Operator.GE, value=Decimal("1"), unit="boolean"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="Fixed base income is documented by the most recent W-2 + pay stub.",
    source=_sg("B3-3.1"),
    notes=(
        "STARTER — RECENTLY CHANGED (03/2026): the current base-income requirement is the most "
        "recent W-2 + pay stub, NOT two years of W-2s. A prime validate-with-Priya item. See also "
        "B3-3.2. Typed-core promotion pending: documents.income.base.w2_and_paystub_present."
    ),
)

CONV_INCOME_VERBAL_VOE = _conv_rule(
    "conv.income.verbal_voe",
    reads=("documents.income.verbal_voe_present",),
    condition=Condition(op=Operator.GE, value=Decimal("1"), unit="boolean"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="A verbal verification of employment is obtained close to the note date.",
    source=_sg("B3-3.1-04"),
    notes=(
        "STARTER (validate with Priya). Typed-core promotion pending: "
        "documents.income.verbal_voe_present."
    ),
)

CONV_INCOME_SELF_EMPLOYMENT_PRESENT = _conv_rule(
    "conv.income.self_employment_present",
    reads=("income.self_employment.monthly_amount",),
    condition=Condition(op=Operator.LE, value=Decimal("0"), unit="usd"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.INCOME,
    description="Self-employment income present → 2-year history + business returns required.",
    source=_sg("B3-3.5-01"),
    notes=(
        "STARTER (validate with Priya). EVALUABLE from stated income. Self-employment income → a "
        "2-year history of prior earnings + business returns are generally required (B3-3.5-01)."
    ),
)

CONV_INCOME_SELF_EMPLOYMENT_HISTORY = _conv_rule(
    "conv.income.self_employment_history",
    reads=("income.self_employment.history_months",),
    condition=Condition(op=Operator.GE, value=Decimal("24"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.INCOME,
    description="Self-employment shows at least a 2-year history of prior earnings.",
    source=_sg("B3-3.5-01"),
    notes=(
        "STARTER (validate with Priya). <2 years MAY be considered with a full 12 months from the "
        "current business + supporting history (B3-3.5-01). Promotion pending: "
        "income.self_employment.history_months."
    ),
)

CONV_INCOME_SE_BUSINESS_OPERATING = _conv_rule(
    "conv.income.self_employment_business_operating",
    reads=("documents.income.self_employment.business_operating_confirmed",),
    condition=Condition(op=Operator.GE, value=Decimal("1"), unit="boolean"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.INCOME,
    description="The borrower's business is confirmed open + operating before the note date.",
    source=_sg("B3-3.5-01", to_verify=True),
    notes=(
        "STARTER — the exact confirmation window is to verify. Promotion pending: "
        "documents.income.self_employment.business_operating_confirmed."
    ),
)

CONV_INCOME_SE_BUSINESS_DEBT = _conv_rule(
    "conv.income.self_employment_business_debt_in_dti",
    reads=("income.self_employment.business_debt_personally_obligated",),
    condition=Condition(op=Operator.LE, value=Decimal("0"), unit="usd"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.INCOME,
    description="Business debt the borrower is personally obligated on is included in DTI.",
    source=_sg("B3-3.5-01"),
    notes=(
        "STARTER (validate with Priya). Cross-links to the DTI calc (LP-76): personally-obligated "
        "business debt must be in total monthly obligations. Promotion pending: "
        "income.self_employment.business_debt_personally_obligated."
    ),
)

CONV_INCOME_OWNERSHIP_INTEREST = _conv_rule(
    "conv.income.ownership_interest_se_treatment",
    reads=("income.ownership_interest_max_pct",),
    condition=Condition(op=Operator.LT, value=Decimal("25"), unit="percent"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.INCOME,
    description="Ownership interest ≥25% triggers self-employment treatment + business returns.",
    source=_sg("B3-3.1", to_verify=True),
    notes=(
        "STARTER — the 25% threshold drives SE treatment; the exact subsection is to verify. "
        "Promotion pending: income.ownership_interest_max_pct."
    ),
)

CONV_INCOME_RENTAL_DOC = _conv_rule(
    "conv.income.rental_income_documentation",
    reads=("documents.income.rental_documented",),
    condition=Condition(op=Operator.GE, value=Decimal("1"), unit="boolean"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.INCOME,
    description="Rental income is documented (lease / Schedule E) before it's used to qualify.",
    source=_sg("B3-3.1", to_verify=True),
    notes=(
        "STARTER — section to verify (rental income guidance). Promotion pending: "
        "documents.income.rental_documented."
    ),
)

CONV_INCOME_DECLINING = _conv_rule(
    "conv.income.declining_income_review",
    reads=("income.self_employment.income_declining",),
    condition=Condition(op=Operator.LE, value=Decimal("0"), unit="boolean"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.INCOME,
    description="Declining self-employment income is reviewed/justified before it's used.",
    source=_sg("B3-3.5-01", to_verify=True),
    notes=(
        "STARTER — section to verify. Promotion pending: income.self_employment.income_declining."
    ),
)

CONVENTIONAL_INCOME_RULES: tuple[VerificationRule, ...] = (
    CONV_INCOME_DOC_AGE,
    CONV_INCOME_BASE_DOC,
    CONV_INCOME_VERBAL_VOE,
    CONV_INCOME_SELF_EMPLOYMENT_PRESENT,
    CONV_INCOME_SELF_EMPLOYMENT_HISTORY,
    CONV_INCOME_SE_BUSINESS_OPERATING,
    CONV_INCOME_SE_BUSINESS_DEBT,
    CONV_INCOME_OWNERSHIP_INTEREST,
    CONV_INCOME_RENTAL_DOC,
    CONV_INCOME_DECLINING,
)


# --------------------------------------------------------------------------- #
# ASSETS (~10)
# --------------------------------------------------------------------------- #

CONV_ASSETS_VERIFICATION = _conv_rule(
    "conv.assets.verification_required",
    reads=("assets.unverified_amount",),
    condition=Condition(op=Operator.LE, value=Decimal("0"), unit="usd"),
    severity=RuleSeverity.RED,
    category=FindingCategory.ASSETS,
    description="Funds for down payment / closing / reserves are verified (no unverified funds).",
    source=_sg("B3-4.2-01"),
    notes=(
        "STARTER (validate with Priya). Depository funds must be verified; unverified funds are not "
        "acceptable and indications of borrowed funds must be investigated (B3-4.2-01/02). "
        "Promotion pending: assets.unverified_amount."
    ),
)

CONV_ASSETS_LARGE_DEPOSIT = _conv_rule(
    "conv.assets.large_deposit_source",
    reads=("assets.largest_deposit_amount",),
    condition=Condition(op=Operator.LE, value=Decimal("10000"), unit="usd"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.ASSETS,
    description="Large single deposits are sourced (accounts <90 days / above-average balances).",
    source=_sg("B3-4.2-02"),
    notes=(
        "STARTER PLACEHOLDER THRESHOLD — large-deposit documentation is DU-MESSAGE-DRIVEN, NOT a "
        "fixed Selling-Guide constant, and is lender-overlay territory. The $10,000 is a starter to "
        "validate with Priya; an overlay overrides it by rule_id."
    ),
)

CONV_ASSETS_STATEMENT_DOC_AGE = _conv_rule(
    "conv.assets.statement_doc_age",
    reads=("documents.asset_statement.most_recent_age_months",),
    condition=Condition(op=Operator.LE, value=Decimal("4"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="The most recent asset statement is no more than 4 months old on the note date.",
    source=_sg("B1-1-03"),
    notes=(
        "STARTER (validate with Priya). The 4-month doc age applies to asset statements too "
        "(B1-1-03). Promotion pending: documents.asset_statement.most_recent_age_months."
    ),
)

CONV_ASSETS_GIFT_DOC = _conv_rule(
    "conv.assets.gift_documentation",
    reads=("assets.gift.total_amount",),
    condition=Condition(op=Operator.LE, value=Decimal("0"), unit="usd"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.ASSETS,
    description="Gift funds present → a gift letter + documentation of transfer/receipt required.",
    source=_sg("B3-4.3-04"),
    notes=(
        "STARTER (validate with Priya). EVALUABLE from stated assets. A personal gift requires a "
        "gift letter + evidence of transfer/receipt (B3-4.3-04)."
    ),
)

CONV_ASSETS_GIFT_DONOR = _conv_rule(
    "conv.assets.gift_donor_relationship",
    reads=("documents.assets.gift_donor_relationship_documented",),
    condition=Condition(op=Operator.GE, value=Decimal("1"), unit="boolean"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.ASSETS,
    description="The gift donor's eligible relationship to the borrower is documented.",
    source=_sg("B3-4.3-04"),
    notes=(
        "STARTER (validate with Priya). Promotion pending: "
        "documents.assets.gift_donor_relationship_documented."
    ),
)

CONV_ASSETS_RETIREMENT_WITHDRAWAL = _conv_rule(
    "conv.assets.retirement_withdrawal_permitted",
    reads=("assets.retirement.total_amount",),
    condition=Condition(op=Operator.LE, value=Decimal("0"), unit="usd"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.ASSETS,
    description="Retirement funds used → confirm withdrawals are permitted.",
    source=_sg("B3-4.3-03"),
    notes=(
        "STARTER (validate with Priya). EVALUABLE from stated assets. When retirement assets are "
        "used, confirm the terms permit withdrawal (B3-4.3-03 / DU)."
    ),
)

CONV_ASSETS_RETIREMENT_ELIGIBLE = _conv_rule(
    "conv.assets.retirement_eligible_amount",
    reads=("assets.retirement.eligible_amount_confirmed",),
    condition=Condition(op=Operator.GE, value=Decimal("1"), unit="boolean"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.ASSETS,
    description="Only the eligible (vested, withdrawal-net) portion of retirement assets is counted.",
    source=_sg("B3-4.3-03", to_verify=True),
    notes=(
        "STARTER — the eligible-portion factor is DU/program-driven; section to verify. Promotion "
        "pending: assets.retirement.eligible_amount_confirmed."
    ),
)

CONV_ASSETS_RESERVES = _conv_rule(
    "conv.assets.reserves_required",
    reads=("reserves.months",),
    condition=Condition(op=Operator.GE, value=Decimal("2"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.ASSETS,
    description="Required reserves are met (months of housing payment in eligible assets).",
    source=RuleSource(
        type="fannie_selling_guide",
        citation="Fannie Mae Eligibility Matrix / DU (reserves are program-driven)",
        section="Eligibility Matrix",
        retrieved="2026-06",
        to_verify=True,
    ),
    notes=(
        "STARTER PLACEHOLDER — required reserves are DU/program/property-driven (NOT a single fixed "
        "number) and lender-overlay territory. The 2-month floor is a starter to validate with Priya."
    ),
)

CONV_ASSETS_BUSINESS_FUNDS = _conv_rule(
    "conv.assets.business_funds_access",
    reads=("documents.assets.business_funds_access_confirmed",),
    condition=Condition(op=Operator.GE, value=Decimal("1"), unit="boolean"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.ASSETS,
    description="Using business funds → access is confirmed and the business is not harmed.",
    source=_sg("B3-4.2", to_verify=True),
    notes=(
        "STARTER — relevant to a self-employed borrower using business funds; section to verify. "
        "Promotion pending: documents.assets.business_funds_access_confirmed."
    ),
)

CONV_ASSETS_ACCOUNT_OWNERSHIP = _conv_rule(
    "conv.assets.account_ownership_documented",
    reads=("documents.assets.account_ownership_documented",),
    condition=Condition(op=Operator.GE, value=Decimal("1"), unit="boolean"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.ASSETS,
    description="Ownership of each asset account used is documented (borrower is an account holder).",
    source=_sg("B3-4.2-01", to_verify=True),
    notes=(
        "STARTER — section to verify. Promotion pending: documents.assets.account_ownership_documented."
    ),
)

CONVENTIONAL_ASSET_RULES: tuple[VerificationRule, ...] = (
    CONV_ASSETS_VERIFICATION,
    CONV_ASSETS_LARGE_DEPOSIT,
    CONV_ASSETS_STATEMENT_DOC_AGE,
    CONV_ASSETS_GIFT_DOC,
    CONV_ASSETS_GIFT_DONOR,
    CONV_ASSETS_RETIREMENT_WITHDRAWAL,
    CONV_ASSETS_RETIREMENT_ELIGIBLE,
    CONV_ASSETS_RESERVES,
    CONV_ASSETS_BUSINESS_FUNDS,
    CONV_ASSETS_ACCOUNT_OWNERSHIP,
)


# All ~20 Conventional income + asset rules (LP-82 content).
CONVENTIONAL_INCOME_ASSET_RULES: tuple[VerificationRule, ...] = (
    *CONVENTIONAL_INCOME_RULES,
    *CONVENTIONAL_ASSET_RULES,
)

# The full Conventional rule set for the registry: LP-82 income/asset +
# LP-83 credit/DTI + property + documentation. FHA is LP-84/85.
CONVENTIONAL_RULES: tuple[VerificationRule, ...] = (
    *CONVENTIONAL_INCOME_ASSET_RULES,
    *CONVENTIONAL_CREDIT_PROPERTY_DOC_RULES,
)
