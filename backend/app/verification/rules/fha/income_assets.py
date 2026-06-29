"""FHA INCOME + ASSET rules (LP-84) — grounded starters into the LP-74 engine.

~11 FHA rules (income 6 + asset 5) as ``program=fha``, the same posture as the
Conventional LP-82 income/asset content: GROUNDED STARTERS researched against the
current HUD Handbook 4000.1 (retrieved 2026-06), every rule ``starter=True``,
pending Priya's validation. These PARALLEL the Conventional LP-82 rules (FHA is a
separate program, similar fields) but carry FHA's own overlays on the shared
income/asset structure and FHA's distinct asset treatment:

  • **Income (II.A.4):** a 2-year employment/income history; self-employment needs
    2 years of personal + business returns + a year-to-date P&L; effective income
    must be stable + likely to continue. Income document recency is FHA's own —
    marked TO VERIFY (do NOT assume the Fannie 4-month).
  • **Assets (II.A.4):** the Minimum Required Investment (MRI) sourced + verified;
    gift funds need a gift letter + documented transfer; **reserves count only 60%
    of vested retirement-account balances** (an FHA-specific haircut — marked TO
    VERIFY); large deposits / source-of-funds verified (FHA's own standard).

**Typed-core reuse (no new promotion needed):** these read the SAME promoted fact
paths the LP-82 Conventional rules use — ``assets.gift.total_amount``,
``assets.retirement.total_amount``, ``income.self_employment.monthly_amount``,
``assets.largest_deposit_amount`` — so they are EVALUABLE today on an FHA file
(program-gating selects the FHA variant). The rest are promotion-pending.
"""

from __future__ import annotations

from decimal import Decimal

from app.models.finding import FindingCategory
from app.verification.rules.fha._base import fha_rule, hud
from app.verification.rules.schema import (
    Condition,
    Operator,
    RuleSeverity,
    VerificationRule,
)

_PRESENT = Condition(op=Operator.GE, value=Decimal("1"), unit="boolean")
# A presence amount compared LE 0: a positive stated amount fires the documentation
# requirement (mirrors the LP-82 evaluable-from-stated pattern).
_AMOUNT_ABSENT = Condition(op=Operator.LE, value=Decimal("0"), unit="usd")


# --------------------------------------------------------------------------- #
# INCOME (HUD 4000.1 II.A.4)
# --------------------------------------------------------------------------- #

FHA_INCOME_EMPLOYMENT_HISTORY = fha_rule(
    "fha.income.employment_history_two_years",
    reads=("income.employment_history_months",),
    condition=Condition(op=Operator.GE, value=Decimal("24"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.INCOME,
    description="At least a 2-year employment/income history is documented (gaps scrutinized).",
    source=hud("II.A.4"),
    notes=(
        "STARTER — generally a 2-year history; gaps/job-changes are scrutinized + explained. "
        "Promotion pending: income.employment_history_months."
    ),
)

FHA_INCOME_SELF_EMPLOYMENT_PRESENT = fha_rule(
    "fha.income.self_employment_present",
    reads=("income.self_employment.monthly_amount",),
    condition=_AMOUNT_ABSENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.INCOME,
    description="Self-employment income present → 2-year returns + YTD P&L required (FHA).",
    source=hud("II.A.4"),
    notes=(
        "STARTER — EVALUABLE from stated income (reuses the LP-82 promotion "
        "income.self_employment.monthly_amount). Self-employment → 2 years of personal + business "
        "tax returns + a year-to-date P&L (see fha.income.self_employment_two_year_returns + "
        "fha.income.self_employment_ytd_pl). Relevant to a two-business borrower."
    ),
)

FHA_INCOME_SELF_EMPLOYMENT_RETURNS = fha_rule(
    "fha.income.self_employment_two_year_returns",
    reads=("documents.income.self_employment.two_year_returns_present",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="Self-employment is documented with 2 years of personal + business tax returns.",
    source=hud("II.A.4"),
    notes=(
        "STARTER — 2 years of personal AND business returns for a self-employed borrower. Promotion "
        "pending: documents.income.self_employment.two_year_returns_present."
    ),
)

FHA_INCOME_SELF_EMPLOYMENT_YTD_PL = fha_rule(
    "fha.income.self_employment_ytd_pl",
    reads=("documents.income.self_employment.ytd_pl_present",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="A year-to-date profit-and-loss statement is present for self-employment income.",
    source=hud("II.A.4", to_verify=True),
    notes=(
        "STARTER — the exact YTD P&L recency/audit requirement is TO VERIFY. Promotion pending: "
        "documents.income.self_employment.ytd_pl_present."
    ),
)

FHA_INCOME_EFFECTIVE_STABLE = fha_rule(
    "fha.income.effective_income_stable",
    reads=("income.effective_income_stable",),
    condition=_PRESENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.INCOME,
    description="Effective income is stable and reasonably likely to continue.",
    source=hud("II.A.4"),
    notes=(
        "STARTER — FHA 'effective income' = stable + likely to continue; declining/temporary income is "
        "scrutinized. Promotion pending: income.effective_income_stable."
    ),
)

FHA_INCOME_DOCUMENT_RECENCY = fha_rule(
    "fha.income.document_recency",
    reads=("documents.income.most_recent_age_months",),
    condition=Condition(op=Operator.LE, value=Decimal("4"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="Income documents are within FHA's recency window on the closing/note date.",
    source=hud("II.A.1", to_verify=True),
    notes=(
        "STARTER — FHA has its OWN document recency; the 4-month starter is a placeholder, NOT assumed "
        "from the Fannie 4-month — TO VERIFY against II.A.1. Promotion pending: "
        "documents.income.most_recent_age_months."
    ),
)


# --------------------------------------------------------------------------- #
# ASSETS (HUD 4000.1 II.A.4) — incl. the FHA 60% retirement-reserve haircut
# --------------------------------------------------------------------------- #

FHA_ASSETS_MRI_VERIFIED = fha_rule(
    "fha.assets.mri_sourced_verified",
    reads=("assets.unverified_amount",),
    condition=_AMOUNT_ABSENT,
    severity=RuleSeverity.RED,
    category=FindingCategory.ASSETS,
    description="The Minimum Required Investment (down payment) is sourced and verified.",
    source=hud("II.A.4"),
    notes=(
        "STARTER — FHA's Minimum Required Investment (MRI) must be from an acceptable, verified source; "
        "unverified funds are unacceptable. Reuses the LP-82 promotion assets.unverified_amount."
    ),
)

FHA_ASSETS_GIFT_DOCUMENTATION = fha_rule(
    "fha.assets.gift_letter_and_transfer",
    reads=("assets.gift.total_amount",),
    condition=_AMOUNT_ABSENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.ASSETS,
    description="Gift funds present → a gift letter + documented transfer of funds required.",
    source=hud("II.A.4"),
    notes=(
        "STARTER — EVALUABLE from stated assets (reuses the LP-82 promotion assets.gift.total_amount). "
        "FHA permits gift funds with a proper gift letter + documentation of the transfer/receipt; "
        "donor eligibility is verified."
    ),
)

FHA_ASSETS_RETIREMENT_HAIRCUT = fha_rule(
    "fha.assets.reserves_retirement_haircut",
    reads=("assets.retirement.total_amount",),
    condition=_AMOUNT_ABSENT,
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.ASSETS,
    description="Reserves from vested retirement accounts count at only 60% (FHA-specific haircut).",
    source=hud("II.A.4", to_verify=True),
    notes=(
        "STARTER — FHA-SPECIFIC: reserves count only ~60% of vested retirement-account balances, and "
        "gifts/borrowed funds do NOT count toward reserves. EVALUABLE presence from the LP-82 promotion "
        "assets.retirement.total_amount; the 60% factor is researched-FHA-specific + TO VERIFY against "
        "II.A.4."
    ),
)

FHA_ASSETS_LARGE_DEPOSIT = fha_rule(
    "fha.assets.large_deposit_source",
    reads=("assets.largest_deposit_amount",),
    condition=Condition(op=Operator.LE, value=Decimal("10000"), unit="usd"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.ASSETS,
    description="Large deposits are sourced (FHA's own large-deposit / source-of-funds standard).",
    source=hud("II.A.4", to_verify=True),
    notes=(
        "STARTER PLACEHOLDER THRESHOLD — FHA's large-deposit standard is its OWN (do NOT assume the "
        "Fannie DU-driven model); the $10,000 starter + section are TO VERIFY and are overlay "
        "territory. Reuses the LP-82 promotion assets.largest_deposit_amount."
    ),
)

FHA_ASSETS_STATEMENT_DOC_AGE = fha_rule(
    "fha.assets.statement_doc_age",
    reads=("documents.asset_statement.most_recent_age_months",),
    condition=Condition(op=Operator.LE, value=Decimal("4"), unit="months"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="The most recent asset statement is within FHA's recency window.",
    source=hud("II.A.1", to_verify=True),
    notes=(
        "STARTER — FHA's own statement recency; the 4-month starter is a placeholder TO VERIFY against "
        "II.A.1. Promotion pending: documents.asset_statement.most_recent_age_months."
    ),
)


FHA_INCOME_RULES: tuple[VerificationRule, ...] = (
    FHA_INCOME_EMPLOYMENT_HISTORY,
    FHA_INCOME_SELF_EMPLOYMENT_PRESENT,
    FHA_INCOME_SELF_EMPLOYMENT_RETURNS,
    FHA_INCOME_SELF_EMPLOYMENT_YTD_PL,
    FHA_INCOME_EFFECTIVE_STABLE,
    FHA_INCOME_DOCUMENT_RECENCY,
)

FHA_ASSET_RULES: tuple[VerificationRule, ...] = (
    FHA_ASSETS_MRI_VERIFIED,
    FHA_ASSETS_GIFT_DOCUMENTATION,
    FHA_ASSETS_RETIREMENT_HAIRCUT,
    FHA_ASSETS_LARGE_DEPOSIT,
    FHA_ASSETS_STATEMENT_DOC_AGE,
)

# The full LP-84 income + asset set: income (6) + asset (5).
FHA_INCOME_ASSET_RULES: tuple[VerificationRule, ...] = (
    *FHA_INCOME_RULES,
    *FHA_ASSET_RULES,
)
