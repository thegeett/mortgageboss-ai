"""Rule-kind classification artifact + loader (LP-301).

Guards the canonical routing table and the Priya-validation gate: all 133 rules
present with the Phase-0 counts, structural rules carry an explicit exact_match,
calculative ⟺ numeric_check, out-of-scope is static_filter (never AI), the loader
round-trips, and the validation helpers report the pending/needs-signoff sets.
"""

from app.verification.rules.kinds import (
    EvaluationPath,
    RuleKindName,
    kind_for,
    load_rule_kinds,
    numeric_check_rules,
    pending_threshold_signoff,
    rules_by_kind,
    rules_needing_threshold_signoff,
    unvalidated_rules,
)

# Phase-0 counts from the xlsx (formalized as-is; the file's "130" title is off by 3).
_EXPECTED = {
    RuleKindName.CALCULATIVE: 29,
    RuleKindName.STRUCTURAL: 60,
    RuleKindName.JUDGMENTAL: 29,
    RuleKindName.OUT_OF_SCOPE: 15,
}
_TOTAL = 133


def test_all_rules_present_with_expected_counts() -> None:
    rules = load_rule_kinds()
    assert len(rules) == _TOTAL
    for kind, n in _EXPECTED.items():
        assert len(rules_by_kind(kind)) == n, kind


def test_every_structural_rule_has_explicit_exact_match() -> None:
    for rk in rules_by_kind(RuleKindName.STRUCTURAL):
        assert rk.exact_match is not None, rk.rule_id
        # exact → deterministic-only (no AI); fuzzy → ai_fuzzy_match.
        expected = (
            EvaluationPath.DETERMINISTIC_ONLY if rk.exact_match else EvaluationPath.AI_FUZZY_MATCH
        )
        assert rk.evaluation_path is expected, rk.rule_id


def test_non_structural_rules_have_no_exact_match() -> None:
    for rk in load_rule_kinds().values():
        if rk.kind is not RuleKindName.STRUCTURAL:
            assert rk.exact_match is None, rk.rule_id


def test_calculative_iff_numeric_check() -> None:
    for rk in load_rule_kinds().values():
        assert rk.numeric_check == (rk.kind is RuleKindName.CALCULATIVE), rk.rule_id
    assert len(numeric_check_rules()) == _EXPECTED[RuleKindName.CALCULATIVE]


def test_calculative_paths_are_the_bookend() -> None:
    for rk in rules_by_kind(RuleKindName.CALCULATIVE):
        assert rk.evaluation_path in {
            EvaluationPath.DETERMINISTIC_BOOKEND,
            EvaluationPath.DETERMINISTIC_BOOKEND_AI,
        }, rk.rule_id


def test_out_of_scope_is_static_filter_never_ai() -> None:
    for rk in rules_by_kind(RuleKindName.OUT_OF_SCOPE):
        assert rk.evaluation_path is EvaluationPath.STATIC_FILTER
        assert not rk.numeric_check


def test_judgmental_is_ai_judgment() -> None:
    for rk in rules_by_kind(RuleKindName.JUDGMENTAL):
        assert rk.evaluation_path is EvaluationPath.AI_JUDGMENT


def test_loader_round_trips_a_known_rule() -> None:
    id2 = kind_for("ID-2")  # SSN consistency — exact structural
    assert id2 is not None
    assert id2.kind is RuleKindName.STRUCTURAL
    assert id2.exact_match is True
    assert id2.evaluation_path is EvaluationPath.DETERMINISTIC_ONLY

    dt1 = kind_for("DT-1")  # DTI vs limit — calculative, needs sign-off
    assert dt1 is not None
    assert dt1.kind is RuleKindName.CALCULATIVE
    assert dt1.numeric_check is True
    assert dt1.threshold_needs_signoff is True

    assert kind_for("NOPE-999") is None


def test_validation_gate_all_pending_and_signoff_set() -> None:
    rules = load_rule_kinds()
    # Nothing is validated yet — LP-301 invents no sign-offs.
    assert all(not rk.priya_validated for rk in rules.values())
    assert len(unvalidated_rules()) == _TOTAL

    # Threshold sign-off set: calculative rules with a regulatory threshold (22 of 29).
    needs = rules_needing_threshold_signoff()
    assert all(rk.kind is RuleKindName.CALCULATIVE for rk in needs)
    assert len(needs) == 22
    # The named examples from the architecture summary must be in it.
    ids = {rk.rule_id for rk in needs}
    for rid in ("AS-1", "IN-1", "CR-6", "PC-4", "PE-1", "DT-1"):
        assert rid in ids, rid

    # Until validated, every needs-signoff rule is a ship-blocker.
    assert len(pending_threshold_signoff()) == len(needs)


def test_ids_are_unique_and_categories_present() -> None:
    rules = load_rule_kinds()
    assert len(rules) == len({rk.rule_id for rk in rules.values()})
    assert all(rk.category for rk in rules.values())
