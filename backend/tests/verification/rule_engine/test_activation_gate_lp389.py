"""LP-389 — the FIRST activation pass, gated by a DECLARED, testable eligibility check (not a blind list edit).

The discipline these pin: a rule goes live ONLY by passing ``activation_bars.is_eligible`` — an AI rule needs a
Priya-VALIDATED bar its MEASURED accuracy clears; a no-AI rule needs its parsed input VERIFIED to resolve on a
real file AT THE SUBJECT THE RULE READS. Everything else (unmeasured tag, unvalidated bar, unresolved input,
needs-producer) is HELD, fail-closed. And the live set is exactly ``base + eligible`` — so a future rule CANNOT
sneak into ``ACTIVE_RULE_IDS`` without meeting the gate (this test fails if it tries), and an activated rule
cannot linger if its evidence is withdrawn.

ID-5 is the load-bearing NEGATIVE case: it was PROPOSED for this pass, but its parsed inputs
(id.id_expiration, contract.closing_date) are declared subject:document and materialize on the ID/contract
DOCUMENTS, while ID-5 reads them at ``tags.by_subject["loan"]`` — a producer/consumer subject mismatch, so it
couldnt_checks on every file. Its bar's ``input_resolves`` is honestly false, and the gate HOLDS it. That is
the safety catching exactly what a blind list edit would have shipped.
"""

from __future__ import annotations

from pathlib import Path

from app.verification.rule_engine import activation_bars as ab
from app.verification.rule_engine.activation_bars import (
    eligible_rule_ids,
    is_eligible,
    load_activation_bars,
    parse_bar,
)
from app.verification.rule_engine.registry import _BASE_ACTIVE, ACTIVE_RULE_IDS

_ACTIVATED = frozenset({"IN-1", "IN-5"})


def _specs() -> set[str]:
    return {p.stem for p in (Path(ab.__file__).resolve().parents[1] / "rules/specs").glob("*.yaml")}


# --------------------------------------------------------------------------- #
# THE GATE — exactly two candidates pass, the other twenty-one are held
# --------------------------------------------------------------------------- #
def test_exactly_two_candidates_are_eligible() -> None:
    bars = load_activation_bars()
    eligible = {rid for rid, bar in bars.items() if is_eligible(bar)}
    held = set(bars) - eligible
    assert eligible == set(_ACTIVATED)  # IN-1, IN-5 (AI, validated, measured >= bar)
    assert len(held) == 21 and not (held & _ACTIVATED)  # every other candidate is held


def test_eligible_rule_ids_is_sorted_and_matches() -> None:
    assert eligible_rule_ids() == ("IN-1", "IN-5")  # sorted, the two LP-389 activated


def test_id5_is_held_by_the_subject_mismatch() -> None:
    # THE negative case the gate exists for: ID-5's inputs resolve at the DOCUMENT subject, not the "loan"
    # subject it reads → input_resolves is honestly false → the gate holds it (never a blind activation).
    bars = load_activation_bars()
    assert bars["ID-5"].status == "no-ai-dependency" and not bars["ID-5"].input_resolves
    assert not is_eligible(bars["ID-5"]) and "ID-5" not in ACTIVE_RULE_IDS


def test_the_held_rules_each_fail_for_a_named_reason() -> None:
    bars = load_activation_bars()
    # a not-calibratable-yet rule: unmeasured AI tag → held regardless of anything else
    assert not is_eligible(bars["AS-2"]) and bars["AS-2"].status == "not-calibratable-yet"
    # a needs-producer rule: the tag doesn't even materialize → held
    assert not is_eligible(bars["IN-14"]) and bars["IN-14"].status == "needs-producer"
    # a no-ai-dependency rule whose input does NOT resolve → held (ID-5 subject mismatch, IN-4 data absence)
    assert not is_eligible(bars["IN-4"]) and bars["IN-4"].status == "no-ai-dependency"
    assert not bars["IN-4"].input_resolves


# --------------------------------------------------------------------------- #
# THE LIVE SET IS base + eligible — the gate is the SOURCE, not a hand-list
# --------------------------------------------------------------------------- #
def test_active_set_is_exactly_base_plus_eligible() -> None:
    # the invariant that keeps a rule from being activated without passing the gate
    assert set(ACTIVE_RULE_IDS) - set(_BASE_ACTIVE) == set(eligible_rule_ids()) == set(_ACTIVATED)
    assert len(ACTIVE_RULE_IDS) == 13 and len(_BASE_ACTIVE) == 11
    assert set(_BASE_ACTIVE) < set(ACTIVE_RULE_IDS)  # the original 11 are intact, none dropped
    # no duplicates crept in when concatenating base + activated
    assert len(set(ACTIVE_RULE_IDS)) == len(ACTIVE_RULE_IDS)


def test_every_candidate_has_a_bar_so_the_gate_sees_all_of_them() -> None:
    # the gate can only hold what it can see: every non-base spec must carry a bar (the LP-380 completeness
    # invariant, restated here because eligibility depends on it).
    assert set(load_activation_bars()) == _specs() - set(_BASE_ACTIVE)


# --------------------------------------------------------------------------- #
# FAIL-CLOSED — withdraw the evidence and the rule falls out of eligibility
# --------------------------------------------------------------------------- #
def _bar(**overrides: object):
    body = {
        "status": "calibratable-now",
        "ships": "auto",
        "threshold": 0.98,
        "validated": True,
        "measured_accuracy": 1.0,
        "rationale": "test",
    }
    body.update(overrides)
    return parse_bar("X-1", body)


def test_ai_rule_eligibility_requires_validated_measured_and_over_bar() -> None:
    assert is_eligible(_bar())  # the passing baseline
    assert not is_eligible(_bar(validated=False))  # unvalidated bar → held
    assert not is_eligible(_bar(measured_accuracy=None))  # unmeasured → held
    assert not is_eligible(_bar(measured_accuracy=0.97))  # measured BELOW the 0.98 bar → held
    assert is_eligible(_bar(measured_accuracy=0.98))  # exactly at the bar → eligible (>=)


def test_no_ai_rule_eligibility_requires_input_resolves() -> None:
    resolves = parse_bar(
        "X-2",
        {
            "status": "no-ai-dependency",
            "ships": "auto",
            "threshold": None,
            "validated": False,
            "input_resolves": True,
            "rationale": "test",
        },
    )
    assert is_eligible(resolves)
    held = parse_bar(
        "X-3",
        {
            "status": "no-ai-dependency",
            "ships": "auto",
            "threshold": None,
            "validated": False,
            "input_resolves": False,
            "rationale": "test",
        },
    )
    assert not is_eligible(held)


def test_active_rules_upstream_ai_groups_are_actually_materialized() -> None:
    # LP-389 review guard: an activated rule whose DERIVED load-bearing tag rests on an AI tag (IN-1's
    # income.documented_income_shortfall_pct rests on income.documented_monthly) needs that AI group folded
    # into _required_ai_groups — else the group never runs, the derived tag is absent, and the rule
    # couldnt_checks FOREVER, silently. Pin that every ACTIVE candidate rule's bar AI tags resolve to a group
    # _required_ai_groups actually runs, so a regression that drops the LP-389 fold-in fails loudly here.
    # (The DEEPER guarantee — that a bar's list is COMPLETE vs. the recipe's real AI deps — is LP-384's
    # declared recipe dependencies; this pins the wiring that exists.)
    from app.services.verification_run import _required_ai_groups
    from app.verification.tag_materialization.declarations import ProductionMode, load_declarations

    decls = load_declarations()
    required = _required_ai_groups()
    active = set(ACTIVE_RULE_IDS)
    for rule_id, bar in load_activation_bars().items():
        if rule_id not in active:
            continue
        for tag_id in bar.load_bearing_ai_tags:
            decl = decls.get(tag_id)
            if decl is not None and decl.mode is ProductionMode.AI:
                assert decl.data in required, (
                    f"{rule_id}: bar AI tag {tag_id} -> group {decl.data!r} is NOT in "
                    f"_required_ai_groups (the LP-389 fold-in regressed -> the rule couldnt_checks forever)"
                )
