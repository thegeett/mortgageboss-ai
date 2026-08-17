"""Rule-kind classification artifact + loader (LP-301).

Guards the canonical routing table and the Priya-validation gate: all 133 rules
present with the Phase-0 counts, structural rules carry an explicit exact_match,
calculative ⟺ numeric_check, out-of-scope is static_filter (never AI), the loader
round-trips, and the validation helpers report the pending/needs-signoff sets.
"""

import pytest
from app.verification.rules.kinds import (
    EvaluationPath,
    RuleKind,
    RuleKindName,
    _to_bool,
    _validate,
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
    RuleKindName.CALCULATIVE: 29,  # LP-519 +AS-13 (repeated same-amount deposits — arithmetic over a derived aggregate)  # LP-447 IH-1 reclassified calculative -> structural (ADR-340, Priya's ruling)
    RuleKindName.STRUCTURAL: 66,  # LP-509-D1 +IH-9 (hazard policy expired — a date compare); LP-494 +CO-5 +CO-3 (was judgmental — its real inputs are typed questionnaire fields); LP-430 +IN-15; LP-433 +IN-16 (deterministic doc checks); LP-447 +IH-1
    RuleKindName.JUDGMENTAL: 27,  # LP-494 -CO-5 -CO-3
    RuleKindName.OUT_OF_SCOPE: 15,
}
_TOTAL = 137  # LP-519 +AS-13 (repeated same-amount deposits; INERT — bar held on measurement)  # LP-430 +IN-15; LP-433 +IN-16  # LP-509-D1 +IH-9 (hazard policy expired)


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

    # Threshold sign-off set: calculative rules with a regulatory threshold (19 of 28 after LP-496a —
    # IH-1's went false at LP-447 when it reclassified structural, and PE-1/PE-3 went false here:
    # every one of their values is TIER P, read from FHFA's own 2026 release and HUD Handbook 4000.1
    # this ticket, so there is no pending threshold for an expert to sign off.
    # LP-497 takes it to 18: AS-4's reserve months are now tier P from B3-4.1-01 (08/07/2024), read
    # from Fannie's own page, replacing an occupancy-only map whose un-encoded cells were 'Priya-pending'.
    needs = rules_needing_threshold_signoff()
    assert all(rk.kind is RuleKindName.CALCULATIVE for rk in needs)
    assert len(needs) == 18
    # The named examples from the architecture summary must be in it.
    ids = {rk.rule_id for rk in needs}
    # PE-1 was removed from this list at LP-496a — its thresholds are tier P and signed off by
    # citation, not pending. It is asserted ABSENT below so the removal is deliberate, not a drop.
    for rid in ("AS-1", "IN-1", "CR-6", "PC-4", "DT-1"):
        assert rid in ids, rid
    for rid in ("PE-1", "PE-3", "AS-4"):
        assert rid not in ids, (
            f"{rid} must NOT need a threshold sign-off — its values are tier P, cited in its spec's "
            "reference_values and pinned to the recipe constants by test (LP-496a)"
        )

    # Until validated, every needs-signoff rule is a ship-blocker.
    assert len(pending_threshold_signoff()) == len(needs)


def test_ids_are_unique_and_categories_present() -> None:
    rules = load_rule_kinds()
    assert len(rules) == len({rk.rule_id for rk in rules.values()})
    assert all(rk.category for rk in rules.values())


# --------------------------------------------------------------------------- #
# Loader hardening (review): read-only cache, strict bools, fail-loud invariants
# --------------------------------------------------------------------------- #


def test_loaded_table_is_read_only() -> None:
    """The cached routing table is immutable — a caller can't corrupt it in place."""
    rules = load_rule_kinds()
    with pytest.raises(TypeError):
        rules["ID-1"] = rules["ID-2"]  # type: ignore[index]


def test_bool_parsing_is_strict() -> None:
    assert _to_bool("true", column="c", rule_id="R") is True
    assert _to_bool("FALSE", column="c", rule_id="R") is False
    for bad in ("ture", "yes", "1", "y", "t"):  # a typo/alias must NOT silently become False
        with pytest.raises(ValueError, match="true/false"):
            _to_bool(bad, column="numeric_check", rule_id="R")


def _rk(**over: object) -> RuleKind:
    base: dict[str, object] = {
        "rule_id": "X-1",
        "name": "n",
        "category": "c",
        "kind": RuleKindName.STRUCTURAL,
        "evaluation_path": EvaluationPath.DETERMINISTIC_ONLY,
        "numeric_check": False,
        "exact_match": True,
        "priya_validated": False,
        "threshold_needs_signoff": False,
        "rationale": "r",
    }
    base.update(over)
    return RuleKind(**base)  # type: ignore[arg-type]


def test_validate_rejects_cross_field_violations() -> None:
    """A row whose enum values are each legal but whose combination misroutes must raise."""
    # structural exact_match=True but routed to AI → would send a deterministic check to AI
    with pytest.raises(ValueError, match="path must be"):
        _validate(_rk(exact_match=True, evaluation_path=EvaluationPath.AI_FUZZY_MATCH))
    # calculative without the numeric bookend
    with pytest.raises(ValueError, match="numeric_check"):
        _validate(
            _rk(
                kind=RuleKindName.CALCULATIVE,
                exact_match=None,
                numeric_check=False,
                evaluation_path=EvaluationPath.DETERMINISTIC_BOOKEND,
            )
        )
    # out_of_scope routed anywhere but static_filter → could reach AI
    with pytest.raises(ValueError, match="static_filter"):
        _validate(
            _rk(
                kind=RuleKindName.OUT_OF_SCOPE,
                exact_match=None,
                evaluation_path=EvaluationPath.AI_JUDGMENT,
            )
        )
    # threshold sign-off on a non-calculative rule
    with pytest.raises(ValueError, match="threshold_needs_signoff"):
        _validate(_rk(threshold_needs_signoff=True))


def test_generated_markdown_is_in_sync_with_the_csv() -> None:
    """The committed companion doc must equal the generator output — no silent drift."""
    from app.scripts.generate_rule_kinds_md import _OUT, render

    assert _OUT.read_text() == render(), "run `python -m app.scripts.generate_rule_kinds_md`"
