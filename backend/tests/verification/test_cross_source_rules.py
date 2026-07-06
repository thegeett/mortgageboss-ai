"""Deterministic cross-source rules (LP-86) — the pure engine + the graduation.

Covers: the distinct cross_source rule category (xsrc.* ids, owned canonical types,
templated wording); deterministic evaluation across sources (identity / address / income
/ liability / asset / terms); the GRADUATION (the driver's-license-equals-subject finding
is now a deterministic rule that fires every run, identically — no flicker); the
mitigable threshold-as-data (income variance %) + overlay-overrideability; the guards that
keep absent-data checks from false-firing; and program-agnostic applicability.
"""

from decimal import Decimal

from app.models.finding import FindingCategory
from app.models.lender import LoanProgram
from app.verification.cross_source import (
    CROSS_SOURCE_RULES,
    OWNED_CANONICAL_TYPES,
    CrossSourceFacts,
    CrossSourceFinding,
    ObligationRef,
    SourcedValue,
    apply_cross_source_overlay,
    evaluate_cross_source,
)
from app.verification.cross_source.rules import XSRC_INCOME_STATED_VS_DOCUMENTED
from app.verification.rules.schema import Condition, Operator, RuleSeverity


def _ids(findings: list[CrossSourceFinding]) -> set[str]:
    return {f.rule.rule_id for f in findings}


# --- Structure (~18) + the distinct category ---------------------------------


def test_eighteen_cross_source_rules_distinct_category() -> None:
    assert len(CROSS_SOURCE_RULES) == 18
    ids = [r.rule_id for r in CROSS_SOURCE_RULES]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("xsrc.") for i in ids)


def test_each_rule_has_the_uniform_cross_source_structure() -> None:
    for rule in CROSS_SOURCE_RULES:
        assert rule.canonical_type  # owns a canonical type (the de-dup key)
        assert isinstance(rule.category, FindingCategory)
        assert rule.severity in (RuleSeverity.RED, RuleSeverity.YELLOW)
        assert "{" in rule.template  # templated wording
        assert callable(rule.check)
        assert rule.starter is True
        assert rule.program is None  # program-agnostic (most cross-source checks)


def test_owned_canonical_types_exclude_other_and_co_borrower() -> None:
    # The deterministic rules own the enumerable types; the AI keeps "other" (novel) +
    # co_borrower_discrepancy (not yet graduated).
    assert "other" not in OWNED_CANONICAL_TYPES
    assert "co_borrower_discrepancy" not in OWNED_CANONICAL_TYPES
    assert {
        "identity_discrepancy",
        "property_address_discrepancy",
        "liability_discrepancy",
        "income_variance",
    } <= OWNED_CANONICAL_TYPES


# --- THE GRADUATION: the driver's-license finding is now deterministic --------


def test_drivers_license_equals_subject_fires_deterministically() -> None:
    facts = CrossSourceFacts(
        dl_address=SourcedValue("123 Main St, Springfield IL", "drivers_license"),
        subject_property_address="123 Main St, Springfield IL",
    )
    r1 = evaluate_cross_source(facts)
    r2 = evaluate_cross_source(facts)
    # Fires — and IDENTICALLY every run (the consistency payoff: no flicker).
    assert "xsrc.address.dl_equals_subject" in _ids(r1)
    assert [f.message for f in r1] == [f.message for f in r2]
    msg = next(f for f in r1 if f.rule.rule_id == "xsrc.address.dl_equals_subject").message
    assert msg == (
        "Driver's license address equals the subject property "
        "(123 Main St, Springfield IL) — occupancy/identity red flag."
    )


def test_dl_not_equal_subject_does_not_fire() -> None:
    facts = CrossSourceFacts(
        dl_address=SourcedValue("9 Oak Ave", "drivers_license"),
        subject_property_address="123 Main St",
    )
    assert "xsrc.address.dl_equals_subject" not in _ids(evaluate_cross_source(facts))


# --- Identity / consistency --------------------------------------------------


def test_name_mismatch_fires_ssn_mismatch_is_red() -> None:
    facts = CrossSourceFacts(
        names=(SourcedValue("John Smith", "application"), SourcedValue("Jonathan Smith", "w2")),
        ssns=(SourcedValue("111-22-3333", "application"), SourcedValue("111-22-4444", "w2")),
    )
    findings = evaluate_cross_source(facts)
    assert "xsrc.identity.name_consistency" in _ids(findings)
    ssn = next(f for f in findings if f.rule.rule_id == "xsrc.identity.ssn_consistency")
    assert ssn.rule.severity is RuleSeverity.RED  # SSN mismatch is a serious red flag


def test_consistent_identity_does_not_fire() -> None:
    facts = CrossSourceFacts(
        names=(SourcedValue("John Smith", "application"), SourcedValue("john  smith", "w2")),
    )
    assert "xsrc.identity.name_consistency" not in _ids(evaluate_cross_source(facts))


# --- Income variance (threshold-as-data) + overlay ---------------------------


def test_income_variance_fires_beyond_the_threshold() -> None:
    facts = CrossSourceFacts(
        stated_income_monthly=Decimal("10000"), documented_income_monthly=Decimal("8000")
    )
    findings = evaluate_cross_source(facts)
    inc = next(f for f in findings if f.rule.rule_id == "xsrc.income.stated_vs_documented")
    assert "25.0%" in inc.message  # |10000-8000|/8000 = 25% > 10% default


def test_income_variance_within_threshold_does_not_fire() -> None:
    facts = CrossSourceFacts(
        stated_income_monthly=Decimal("8500"), documented_income_monthly=Decimal("8000")
    )  # 6.25% < 10%
    assert "xsrc.income.stated_vs_documented" not in _ids(evaluate_cross_source(facts))


def test_income_variance_threshold_is_overlay_overrideable() -> None:
    facts = CrossSourceFacts(
        stated_income_monthly=Decimal("10000"), documented_income_monthly=Decimal("8000")
    )
    # An overlay relaxes the variance to 30% → 25% no longer fires.
    patched = apply_cross_source_overlay(
        CROSS_SOURCE_RULES,
        {"xsrc.income.stated_vs_documented": Condition(op=Operator.LE, value=Decimal("30"))},
    )
    assert "xsrc.income.stated_vs_documented" not in _ids(
        evaluate_cross_source(facts, rules=patched)
    )
    # The base rule's threshold is unchanged (overlay is a non-mutating diff).
    assert XSRC_INCOME_STATED_VS_DOCUMENTED.threshold is not None
    assert XSRC_INCOME_STATED_VS_DOCUMENTED.threshold.value == Decimal("10")


# --- Liability: undisclosed debt (the graduate) + the absent-data guard -------


def test_undisclosed_debt_fires_per_credit_report_item_not_on_application() -> None:
    facts = CrossSourceFacts(
        credit_report_liabilities=(
            ObligationRef("Capital One", Decimal("200"), "credit_report"),
            ObligationRef("Chase Auto", Decimal("450"), "credit_report"),
        ),
        stated_liabilities=(ObligationRef("Capital One", Decimal("200"), "application"),),
    )
    findings = [
        f
        for f in evaluate_cross_source(facts)
        if f.rule.rule_id == "xsrc.liability.undisclosed_debt"
    ]
    assert len(findings) == 1  # only Chase Auto is undisclosed
    assert "Chase Auto" in findings[0].message
    assert findings[0].document_value == "450"  # feeds the APPLY→recompute add_liability spec


def test_liability_checks_do_not_false_fire_without_a_credit_report() -> None:
    """The stated-not-on-report check needs a report present (else every stated debt flags)."""
    facts = CrossSourceFacts(
        stated_liabilities=(ObligationRef("Capital One", Decimal("200"), "application"),),
    )  # no credit_report_liabilities → not a discrepancy, just not loaded
    ids = _ids(evaluate_cross_source(facts))
    assert "xsrc.liability.stated_not_on_report" not in ids
    assert "xsrc.liability.undisclosed_debt" not in ids


# --- Asset / gift ------------------------------------------------------------


def test_gift_without_letter_fires_only_when_letter_absent() -> None:
    with_letter = CrossSourceFacts(gift_amount=Decimal("5000"), gift_letter_present=True)
    without = CrossSourceFacts(gift_amount=Decimal("5000"), gift_letter_present=False)
    assert "xsrc.asset.gift_without_letter" not in _ids(evaluate_cross_source(with_letter))
    assert "xsrc.asset.gift_without_letter" in _ids(evaluate_cross_source(without))


def test_missing_document_check_is_kept() -> None:
    facts = CrossSourceFacts(stated_assets_missing_doc=("Checking — Evergreen CU",))
    findings = [
        f
        for f in evaluate_cross_source(facts)
        if f.rule.rule_id == "xsrc.asset.stated_missing_document"
    ]
    assert len(findings) == 1
    assert findings[0].rule.category is FindingCategory.DOCUMENTATION


# --- Terms / property --------------------------------------------------------


def test_price_vs_contract_and_subject_address_consistency() -> None:
    facts = CrossSourceFacts(
        stated_purchase_price=Decimal("400000"),
        contract_purchase_price=Decimal("415000"),
        subject_addresses_across_docs=(
            SourcedValue("123 Main St", "application"),
            SourcedValue("123 Maine St", "appraisal"),
        ),
    )
    ids = _ids(evaluate_cross_source(facts))
    assert "xsrc.terms.price_vs_contract" in ids
    assert "xsrc.property.subject_address_consistency" in ids


# --- Program-agnostic applicability ------------------------------------------


def test_program_agnostic_rules_fire_on_both_programs() -> None:
    facts = CrossSourceFacts(
        dl_address=SourcedValue("1 A St", "drivers_license"), subject_property_address="1 A St"
    )
    for program in (LoanProgram.CONVENTIONAL, LoanProgram.FHA, None):
        assert "xsrc.address.dl_equals_subject" in _ids(
            evaluate_cross_source(facts, program=program)
        )


def test_empty_facts_produce_no_findings() -> None:
    """No data → no findings (the engine never invents a discrepancy)."""
    assert evaluate_cross_source(CrossSourceFacts()) == []
