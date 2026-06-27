"""SAMPLE verification rules (LP-74) — enough to prove the engine, not the content.

These are deliberately a *handful* of rules — one per shape — so the engine's
composition and evaluation can be exercised end to end. They are **not** the real
rule content: the ~60 Conventional + ~50 FHA rules land in LP-82..85 (the LP-68
"mechanism first, content later" pattern). The thresholds below are illustrative.

The samples cover:

* a **regulatory** rule (Layer 1, every file) — an AML large-deposit review;
* two **investor** rules (Layer 2, per program) — a Conventional back-end DTI cap
  and an FHA one, so program-selection is observable (a Conventional file must
  get the Conventional rule, never the FHA rule);
* a **documentation** rule (Layer 1-style, every file) — pay-stub recency.

Each carries the two linchpins: a stable ``rule_id`` and a threshold-as-data
:class:`Condition`.
"""

from __future__ import annotations

from decimal import Decimal

from app.models.finding import FindingCategory
from app.models.lender import LoanProgram
from app.verification.rules.schema import (
    Applicability,
    ApplicabilityScope,
    Condition,
    Operator,
    RuleLayer,
    RuleSeverity,
    RuleSource,
    VerificationRule,
)

# --- Layer 1: regulatory (all loans) -----------------------------------------

AML_LARGE_DEPOSIT_REVIEW = VerificationRule(
    rule_id="reg.aml.large_deposit_review",
    layer=RuleLayer.REGULATORY,
    applicability=Applicability(scope=ApplicabilityScope.ALL_LOANS),
    reads=("assets.largest_deposit_amount",),
    condition=Condition(op=Operator.LE, value=Decimal("10000"), unit="usd"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.REGULATORY,
    description=(
        "Single asset deposit at or under the large-deposit review threshold "
        "(sourcing/AML review expected above it)."
    ),
    source=RuleSource(
        type="regulation",
        citation="FinCEN / BSA large-cash-deposit review (sample)",
    ),
)

# --- Documentation (all loans) -----------------------------------------------

PAYSTUB_RECENCY = VerificationRule(
    rule_id="doc.income.paystub_recency",
    layer=RuleLayer.REGULATORY,
    applicability=Applicability(scope=ApplicabilityScope.ALL_LOANS),
    reads=("documents.paystub.most_recent_age_days",),
    condition=Condition(op=Operator.LE, value=Decimal("30"), unit="days"),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.DOCUMENTATION,
    description="Most recent pay stub is within the 30-day recency window.",
    source=RuleSource(
        type="documentation_standard",
        citation="Agency document-age standard — pay stub within 30 days (sample)",
    ),
)

# --- Layer 2: investor (per program) -----------------------------------------

CONV_DTI_BACK_END_MAX = VerificationRule(
    rule_id="conv.dti.back_end_max",
    layer=RuleLayer.INVESTOR,
    applicability=Applicability(scope=ApplicabilityScope.PROGRAM, program=LoanProgram.CONVENTIONAL),
    reads=("dti.back_end_pct",),
    condition=Condition(op=Operator.LE, value=Decimal("50"), unit="percent"),
    severity=RuleSeverity.RED,
    category=FindingCategory.INCOME,
    description="Back-end DTI at or under the Conventional maximum.",
    source=RuleSource(
        type="investor_guide",
        citation="Fannie Mae Selling Guide B3-6-02 (sample threshold)",
    ),
)

FHA_DTI_BACK_END_MAX = VerificationRule(
    rule_id="fha.dti.back_end_max",
    layer=RuleLayer.INVESTOR,
    applicability=Applicability(scope=ApplicabilityScope.PROGRAM, program=LoanProgram.FHA),
    reads=("dti.back_end_pct",),
    condition=Condition(op=Operator.LE, value=Decimal("57"), unit="percent"),
    severity=RuleSeverity.RED,
    category=FindingCategory.INCOME,
    description="Back-end DTI at or under the FHA maximum (with compensating factors).",
    source=RuleSource(
        type="investor_guide",
        citation="HUD Handbook 4000.1 II.A.5 (sample threshold)",
    ),
)


# All sample rule definitions, in one tuple for the registry.
SAMPLE_RULES: tuple[VerificationRule, ...] = (
    AML_LARGE_DEPOSIT_REVIEW,
    PAYSTUB_RECENCY,
    CONV_DTI_BACK_END_MAX,
    FHA_DTI_BACK_END_MAX,
)
