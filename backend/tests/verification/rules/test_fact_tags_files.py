"""LP-311: the fact-tag machine-source files + their generator (no DB)."""

from __future__ import annotations

import pytest
from app.scripts import generate_fact_tags
from app.verification.rules.projection import (
    ProjectionError,
    check_consistency,
    load_desired_rule_tags,
    load_desired_rules,
    load_desired_tag_dependencies,
    load_desired_tags,
)


def test_generated_csvs_are_committed_and_current() -> None:
    """The committed CSVs must match what the vocabulary xlsx generates.

    If this fails, someone edited the xlsx without re-running the generator (or
    hand-edited a CSV). Re-run ``python -m app.scripts.generate_fact_tags``.
    """
    assert generate_fact_tags.main(["--check"]) == 0


def test_value_type_parsing() -> None:
    assert generate_fact_tags._parse_value_type("enum: in | out | unknown") == (
        "enum",
        ["in", "out", "unknown"],
    )
    assert generate_fact_tags._parse_value_type("number") == ("number", [])
    assert generate_fact_tags._parse_value_type("number | unknown") == ("number", [])
    assert generate_fact_tags._parse_value_type("object: {value, breakdown[]}") == (
        "object",
        [],
    )
    assert generate_fact_tags._parse_value_type("number (from spec)") == ("number", [])


def test_range_pseudo_rules_expand() -> None:
    assert generate_fact_tags._expand_rule_id("CO-1..5") == [
        "CO-1",
        "CO-2",
        "CO-3",
        "CO-4",
        "CO-5",
    ]
    assert generate_fact_tags._expand_rule_id("AS-1") == ["AS-1"]


def test_desired_state_shape() -> None:
    rules = load_desired_rules()
    tags = load_desired_tags()
    rule_tags = load_desired_rule_tags()
    tag_deps = load_desired_tag_dependencies()

    # rule_kinds.csv is 133 rules; the vocabulary is 143 xlsx tags + 1 hand-added overlay tag
    # (id.poa_acceptable LP-329, id.residency_eligible LP-331) = 145.
    assert (
        len(rules) == 137
    )  # LP-430 +IN-15; LP-433 +IN-16 (pay-stub-only documentation)  # LP-509-D1 +IH-9 (hazard policy expired)
    # LP-430 — +2 overlay (income.terminated_employment + _end_date); LP-433 — +1 (income.history_documentation).
    # LP-447 +1 (ins.dwelling_settlement_basis — the IH-1 basis tag, a vocabulary_extra overlay).
    # LP-453 +2 (credit.tradeline_count + credit.tradeline_monthly_payment_total — the tradelines consumer).
    assert (
        len(tags)
        == 252  # LP-573 +2 (liab.stated_is_mortgage + liab.payoff_marked — DT-8's inputs, via the overlay)  # LP-556 +1 (liab.creditor_name — names WHICH debt a per-liability finding is about, via the overlay)  # LP-551 +1 (txn.stated_liability_match — FR-5's payee-vs-1003 comparison, via the hand-editable overlay)  # LP-519 +1 (stmt.repeated_money_in_max_total — AS-13's split-deposit aggregate)  # LP-509-D1 +2 (ins.expiration_date + ins.policy_expired)  # LP-498 +1 (contract.credits_warrant_review; contract.unusual_credits already existed)  # LP-496a +1 (program.conforming_eligibility; PE-3's tag already existed)
    )  # LP-495b +2 (occupancy.investment_rental_supported, dti.atr_documentation_adequate —
    # OC-3's and DT-7's judgment OUTPUT tags; a judgment output is emitted by the evaluator, so neither
    # gets a tag_production.yaml entry, the same shape as income.other_income_continues)
    # LP-495a +4 (reo.statement_disclosure + reo.statement_payment_coverage — ONE matcher
    # serving RE-1 and DT-6, ADR-375; loe.is_explanation_letter — LO-2's applicability predicate, needed
    # because the applicability DSL has only eq/ne while LO-2's scope is 8 document types; loe.completeness.
    # ⚠️ property.is_retained_reo and property.retained_pitia are DELIBERATELY still absent from
    # tag_production.yaml — 'retained' is an inference no document, field or MISMO fact states, and
    # neither rebuilt rule reads them (pinned by test_reo_reconciliation_lp495a).
    # LP-494 +8 (the condo project lane — see test_projection_db for the roll-call); LP-487 +6 (IH-2/IH-7's parsed inputs: ins.mortgagee_name, loan.lender_name_cd, loan.lender_name_le, condo.master_policy_number, condo.master_policy_basis_raw, condo.master_liability_limit — their two CONCLUSION tags already exist in fact_tags.csv);
    # LP-485 +3 (the date-compare family: rate_lock.days_to_closing,
    # credit.report_age_months_at_closing, property.appraisal_age_months_at_closing);
    # LP-444 +1 (credit.undisclosed_tradeline — CR-4, inert); prior:
    # +4 assets (LP-323-AS-B) +2 ID-5 (LP-389-A) +2 stmt variance/co-holder
    # (LP-400) +3 the LP-410 derived-producer wave (days_until_closing / stmt.continuity / employer_coverage)
    # +1 LP-407-2 (contract.loan_sales_price — the PC-2 loan promotion; its 4 other tags already exist in the CSV)
    # +1 LP-417 (ins.loan_effective_date — the IH-3 loan promotion; ins.effective_date already exists in the CSV)
    # +1 LP-418 (income.is_self_employed — the deterministic per-borrower self-employment promotion of the
    # measured income.type; the batch's other two producers, txn.is_nsf_or_overdraft + occupancy.rental_support,
    # already exist in the CSV, so they add production wiring but no vocabulary tag).
    # +1 LP-422 (income.has_rental_income — the deterministic per-borrower rental presence read off Schedule E;
    # the self-employment side reuses income.is_self_employed, extended, so it adds no tag).
    # +1 LP-424 (loan.purpose — the parsed purchase/refinance scope tag). It adds NO rule_tags edge: its
    # consumer (the PC-2/PC-7 applicability predicate) is deferred (LF-6T3N carries no loan.purpose; no refi
    # fixture), so rule_tags stays 203 — an intentionally orphan-for-now tag.
    # LP-490 review +7 rule_tags edges: the four credit rules' catalog rows were corrected to what each
    # rule actually reads (CR-5 had NO row; CR-6/CR-8 pointed at their pre-fix predicates; CR-10 listed
    # liab.balance/liab.derogatory_type rather than the aggregate, the gate and the reasoned-over set).
    # Structural subject markers (document.document_type, liability.source) are deliberately NOT edges —
    # the projection validates every edge against fact_tags.csv and rejects a non-vocabulary tag.
    # LP-491 review +3: the TI-* catalog rows were corrected to what each rule actually reads
    # (TI-1 pointed at title.parties_match, TI-2 at title.legal_desc_matches, TI-6 at
    # title.rapid_transfer — three live rules wired to dead vocabulary). Same defect the LP-490
    # review fixed for the credit rules, one ticket later.
    # LP-509-A1 +1: AS-2 -> txn.is_money_in. The catalog said AS-12 consumed the direction tag and
    # AS-2 did not, but neither SPEC gated on it — so both evaluated outgoing bill payments as
    # deposits. Fixing the specs made AS-2's dependency real, so the row is now declared too.
    assert len(rule_tags) == 214
    # No depends_on authored yet (LP-311 Phase 0): the DAG is empty.
    assert tag_deps == set()

    # An enum tag carries allowed_values; a scalar tag does not.
    assert tags["txn.is_money_in"]["allowed_values"] == ["in", "out", "unknown"]
    assert tags["txn.amount"]["allowed_values"] is None
    # tag_role/tag_version are not authored yet.
    assert tags["txn.is_money_in"]["tag_role"] is None
    assert tags["txn.is_money_in"]["tag_version"] == 1


def test_as1_gate_is_files_truth_not_seed() -> None:
    """AS-1 stays priya_validated=False — the files win over LP-118's seed TRUE."""
    rules = load_desired_rules()
    assert rules["AS-1"]["priya_validated"] is False
    assert rules["AS-1"]["threshold_needs_signoff"] is True
    # AS-1 + OC-2 + the ID family + the IN family carry specs.
    assert rules["AS-1"]["spec"] is not None
    assert rules["IN-1"]["spec"] is not None  # authored by LP-323-IN-B
    assert (
        rules["IN-6"]["spec"] is not None
    )  # LP-406-3b — written on the derived employer_coverage tag (LP-410)
    assert rules["IN-6"]["priya_validated"] is False


def test_committed_files_are_consistent() -> None:
    """The shipped files must pass the load-time consistency checks."""
    check_consistency(
        rules=load_desired_rules(),
        tags=load_desired_tags(),
        rule_tags=load_desired_rule_tags(),
        tag_dependencies=load_desired_tag_dependencies(),
    )


def test_consistency_rejects_unknown_required_tag() -> None:
    with pytest.raises(ProjectionError, match="not in the fact-tag vocabulary"):
        check_consistency(
            rules={"AS-1": {}},
            tags={},
            rule_tags={("AS-1", "txn.ghost")},
            tag_dependencies=set(),
        )


def test_consistency_rejects_rule_tag_for_unknown_rule() -> None:
    with pytest.raises(ProjectionError, match="unknown rule"):
        check_consistency(
            rules={},
            tags={"txn.amount": {}},
            rule_tags={("ZZ-9", "txn.amount")},
            tag_dependencies=set(),
        )


def test_consistency_rejects_dangling_dependency_edge() -> None:
    with pytest.raises(ProjectionError, match="depends on unknown tag"):
        check_consistency(
            rules={},
            tags={"a": {}},
            rule_tags=set(),
            tag_dependencies={("a", "missing")},
        )


def test_consistency_rejects_dependency_cycle() -> None:
    with pytest.raises(ProjectionError, match="cycle"):
        check_consistency(
            rules={},
            tags={"a": {}, "b": {}, "c": {}},
            rule_tags=set(),
            tag_dependencies={("a", "b"), ("b", "c"), ("c", "a")},
        )


def test_consistency_accepts_valid_dag() -> None:
    # A -> B -> C, A -> C is a valid DAG (no cycle).
    check_consistency(
        rules={},
        tags={"a": {}, "b": {}, "c": {}},
        rule_tags=set(),
        tag_dependencies={("a", "b"), ("b", "c"), ("a", "c")},
    )
