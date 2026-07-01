"""LP-100 — the PURPOSE dimension of rule applicability (purchase-only / refi-only / cash-out).

The applicability framework had no PURPOSE gate (ALL_LOANS | PROGRAM | LENDER only), so the
purchase-agreement doc rule fired on refinances → a spurious "missing purchase agreement" finding.
These tests prove the new PURPOSE dimension: a purchase-only rule is SKIPPED on a refinance
(no finding), still evaluates on a purchase, composes with the program scope + RuleGate, and is
UNDER-gated (an unknown purpose still applies the rule; only clearly-purpose-specific rules gated;
DTI is never purpose-gated). Pure — no DB, no AI.
"""

from decimal import Decimal

from app.models.finding import FindingCategory
from app.models.lender import LoanProgram
from app.models.loan_file import LoanPurpose, RefinanceType
from app.verification.cross_source.engine import evaluate_cross_source
from app.verification.cross_source.facts import CrossSourceFacts
from app.verification.engine import evaluate
from app.verification.facts import Fact, FileFacts
from app.verification.registry import RuleRegistry
from app.verification.rules.conventional.credit_property_docs import CONV_DOCS_PURCHASE_AGREEMENT
from app.verification.rules.fha.property_docs import FHA_DOC_PRE_APPRAISAL_SALES_CONTRACT
from app.verification.rules.samples import CONV_DTI_BACK_END_MAX
from app.verification.rules.schema import (
    Applicability,
    ApplicabilityScope,
    Condition,
    Operator,
    PurposeScope,
    RuleLayer,
    RuleSeverity,
    RuleSource,
    VerificationRule,
    purpose_applies,
)

_PRESENT = Fact(value=Decimal("1"))  # the doc-presence datum, so the rule would evaluate
_DOC_FACTS = FileFacts(
    values={
        "documents.purchase_agreement_present": _PRESENT,
        "documents.sales_contract_present": _PRESENT,
    }
)


def _result(findings, rule_id):
    return next(f for f in findings if f.rule.rule_id == rule_id)


# --- purpose_applies: the under-gated truth table ----------------------------


def test_purpose_none_applies_to_every_purpose() -> None:
    """No purpose scope → the rule applies to purchase, refi, and unknown alike (the default)."""
    for lp in (LoanPurpose.PURCHASE, LoanPurpose.REFINANCE, None):
        assert purpose_applies(None, loan_purpose=lp, refinance_type=None) is True


def test_purchase_only_skipped_only_on_a_known_refi() -> None:
    P = PurposeScope.PURCHASE
    assert purpose_applies(P, loan_purpose=LoanPurpose.PURCHASE, refinance_type=None) is True
    assert purpose_applies(P, loan_purpose=LoanPurpose.REFINANCE, refinance_type=None) is False
    # UNDER-GATE: an unknown purpose still applies (a spurious flag is safe; hiding is not).
    assert purpose_applies(P, loan_purpose=None, refinance_type=None) is True


def test_cash_out_only_needs_a_cash_out_refi() -> None:
    CO = PurposeScope.CASH_OUT
    assert (
        purpose_applies(
            CO, loan_purpose=LoanPurpose.REFINANCE, refinance_type=RefinanceType.CASH_OUT
        )
        is True
    )
    assert (
        purpose_applies(
            CO, loan_purpose=LoanPurpose.REFINANCE, refinance_type=RefinanceType.RATE_TERM
        )
        is False
    )
    assert purpose_applies(CO, loan_purpose=LoanPurpose.PURCHASE, refinance_type=None) is False
    # UNDER-GATE: a refi whose determination is unknown (LP-99 surfaces it) still applies.
    assert purpose_applies(CO, loan_purpose=LoanPurpose.REFINANCE, refinance_type=None) is True


def test_rate_term_only_needs_a_rate_term_refi() -> None:
    RT = PurposeScope.RATE_TERM
    assert (
        purpose_applies(
            RT, loan_purpose=LoanPurpose.REFINANCE, refinance_type=RefinanceType.RATE_TERM
        )
        is True
    )
    assert (
        purpose_applies(
            RT, loan_purpose=LoanPurpose.REFINANCE, refinance_type=RefinanceType.CASH_OUT
        )
        is False
    )
    assert purpose_applies(RT, loan_purpose=LoanPurpose.PURCHASE, refinance_type=None) is False


# --- The engine: a purchase-only rule is SKIPPED on a refinance ---------------


def test_purchase_agreement_skipped_on_a_refinance() -> None:
    """The bug fixed: the purchase-agreement rule does NOT fire on a refi (skipped, no finding)."""
    results = evaluate(
        _DOC_FACTS,
        [CONV_DOCS_PURCHASE_AGREEMENT],
        loan_purpose=LoanPurpose.REFINANCE,
        refinance_type=RefinanceType.CASH_OUT,
    )
    result = _result(results, "conv.docs.purchase_agreement_present")
    assert result.evaluated is False  # skipped — not evaluated, never a finding
    assert result.observed is None


def test_purchase_agreement_still_fires_on_a_purchase() -> None:
    """No regression (Mahesh is a purchase): the rule still evaluates for a purchase."""
    results = evaluate(
        _DOC_FACTS,
        [CONV_DOCS_PURCHASE_AGREEMENT],
        loan_purpose=LoanPurpose.PURCHASE,
        refinance_type=None,
    )
    assert _result(results, "conv.docs.purchase_agreement_present").evaluated is True


def test_purchase_agreement_evaluates_when_purpose_unknown() -> None:
    """UNDER-GATE: a file with no purpose captured still evaluates the rule (never hide a finding)."""
    results = evaluate(_DOC_FACTS, [CONV_DOCS_PURCHASE_AGREEMENT])  # purpose defaults to None
    assert _result(results, "conv.docs.purchase_agreement_present").evaluated is True


def test_fha_sales_contract_skipped_on_a_refinance() -> None:
    results = evaluate(
        _DOC_FACTS,
        [FHA_DOC_PRE_APPRAISAL_SALES_CONTRACT],
        loan_purpose=LoanPurpose.REFINANCE,
        refinance_type=RefinanceType.RATE_TERM,
    )
    assert _result(results, "fha.doc.pre_appraisal_sales_contract").evaluated is False


# --- DTI is NOT purpose-gated (program-based) ---------------------------------


def test_dti_fires_regardless_of_purpose() -> None:
    """A refi still gets DTI findings — DTI is program-based, never purpose-gated."""
    facts = FileFacts(values={"dti.back_end_pct": Fact(value=Decimal("52"))})
    results = evaluate(
        facts,
        [CONV_DTI_BACK_END_MAX],
        loan_purpose=LoanPurpose.REFINANCE,
        refinance_type=RefinanceType.CASH_OUT,
    )
    result = results[0]
    assert result.evaluated is True and result.passed is False  # the 52 > 50 cap still fires
    assert CONV_DTI_BACK_END_MAX.applicability.purpose is None  # declared purpose-agnostic


# --- PURPOSE composes with the PROGRAM scope + a synthetic cash-out rule -------

_CONV_PURCHASE_ONLY = VerificationRule(
    rule_id="test.conv.purchase_only",
    layer=RuleLayer.INVESTOR,
    applicability=Applicability(
        scope=ApplicabilityScope.PROGRAM,
        program=LoanProgram.CONVENTIONAL,
        purpose=PurposeScope.PURCHASE,
    ),
    reads=("dti.back_end_pct",),
    condition=Condition(op=Operator.LE, value=Decimal("50")),
    severity=RuleSeverity.YELLOW,
    category=FindingCategory.CREDIT,
    description="A synthetic Conventional AND purchase-only rule (composition test).",
    source=RuleSource(type="test", citation="test"),
)
_CASH_OUT_ONLY = _CONV_PURCHASE_ONLY.model_copy(
    update={
        "rule_id": "test.conv.cash_out_only",
        "applicability": Applicability(
            scope=ApplicabilityScope.PROGRAM,
            program=LoanProgram.CONVENTIONAL,
            purpose=PurposeScope.CASH_OUT,
        ),
    }
)
_UNGATED = _CONV_PURCHASE_ONLY.model_copy(
    update={
        "rule_id": "test.conv.ungated",
        "applicability": Applicability(
            scope=ApplicabilityScope.PROGRAM, program=LoanProgram.CONVENTIONAL
        ),
    }
)
_FACTS = FileFacts(values={"dti.back_end_pct": Fact(value=Decimal("40"))})


def test_purpose_composes_with_program_scope() -> None:
    """A "Conventional AND purchase-only" rule: fires on a Conv PURCHASE, skipped on a Conv REFI.
    (The program half — skip on FHA — is enforced earlier at registry.resolve, tested there.)"""
    on_purchase = evaluate(_FACTS, [_CONV_PURCHASE_ONLY], loan_purpose=LoanPurpose.PURCHASE)
    assert on_purchase[0].evaluated is True

    on_refi = evaluate(
        _FACTS,
        [_CONV_PURCHASE_ONLY],
        loan_purpose=LoanPurpose.REFINANCE,
        refinance_type=RefinanceType.CASH_OUT,
    )
    assert on_refi[0].evaluated is False


def test_program_scope_still_excludes_the_rule_from_the_other_program() -> None:
    """The program half of the composition: a Conventional rule isn't in an FHA file's set
    (program membership is resolved at registry.resolve, before the per-rule purpose gate)."""
    registry = RuleRegistry(rules=(_CONV_PURCHASE_ONLY,), overlays={})
    fha_set = registry.resolve(program=LoanProgram.FHA, lender_slug=None)
    assert all(r.rule_id != "test.conv.purchase_only" for r in fha_set)
    conv_set = registry.resolve(program=LoanProgram.CONVENTIONAL, lender_slug=None)
    assert any(r.rule_id == "test.conv.purchase_only" for r in conv_set)


def test_cash_out_only_rule_applies_only_to_a_cash_out_refi() -> None:
    cash_out = evaluate(
        _FACTS,
        [_CASH_OUT_ONLY],
        loan_purpose=LoanPurpose.REFINANCE,
        refinance_type=RefinanceType.CASH_OUT,
    )
    assert cash_out[0].evaluated is True

    rate_term = evaluate(
        _FACTS,
        [_CASH_OUT_ONLY],
        loan_purpose=LoanPurpose.REFINANCE,
        refinance_type=RefinanceType.RATE_TERM,
    )
    assert rate_term[0].evaluated is False


def test_ungated_rule_fires_on_both_purposes() -> None:
    """UNDER-GATE: a rule with no purpose scope evaluates on BOTH a purchase and a refi."""
    on_purchase = evaluate(_FACTS, [_UNGATED], loan_purpose=LoanPurpose.PURCHASE)
    on_refi = evaluate(_FACTS, [_UNGATED], loan_purpose=LoanPurpose.REFINANCE)
    assert on_purchase[0].evaluated is True and on_refi[0].evaluated is True


# --- The cross-source engine: price-vs-contract is purchase-only --------------


def test_cross_source_price_vs_contract_skipped_on_a_refinance() -> None:
    """The purchase-only cross-source check is skipped on a refi — safe by INTENT, not just by the
    incidental absence of the contract fact (here the mismatch IS present, yet nothing fires)."""
    facts = CrossSourceFacts(
        stated_purchase_price=Decimal("500000"), contract_purchase_price=Decimal("450000")
    )
    on_refi = evaluate_cross_source(
        facts,
        program=LoanProgram.CONVENTIONAL,
        loan_purpose=LoanPurpose.REFINANCE,
        refinance_type=RefinanceType.CASH_OUT,
    )
    assert all(f.rule.rule_id != "xsrc.terms.price_vs_contract" for f in on_refi)

    on_purchase = evaluate_cross_source(
        facts, program=LoanProgram.CONVENTIONAL, loan_purpose=LoanPurpose.PURCHASE
    )
    assert any(f.rule.rule_id == "xsrc.terms.price_vs_contract" for f in on_purchase)
