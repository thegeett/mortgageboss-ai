"""LP-389 — the FIRST activation pass, gated by a DECLARED, testable eligibility check (not a blind list edit).

The discipline these pin: a rule goes live ONLY by passing ``activation_bars.is_eligible`` — an AI rule needs a
Priya-VALIDATED bar its MEASURED accuracy clears; a no-AI rule needs its parsed input VERIFIED to resolve on a
real file AT THE SUBJECT THE RULE READS. Everything else (unmeasured tag, unvalidated bar, unresolved input,
needs-producer) is HELD, fail-closed. And the live set is exactly ``base + eligible`` — so a future rule CANNOT
sneak into ``ACTIVE_RULE_IDS`` without meeting the gate (this test fails if it tries), and an activated rule
cannot linger if its evidence is withdrawn.

ID-5 shows the gate BOTH ways across LP-389 → LP-389-A. LP-389 HELD it: its inputs materialized on the
DOCUMENT subject while ID-5 read them at ``tags.by_subject["loan"]`` (a producer/consumer subject mismatch), so
``input_resolves`` was honestly false and the gate held it — the safety catching what a blind list edit would
have shipped. LP-389-A FIXED the mismatch (ID-5 is now per-borrower, reading the attributed ID against the
loan's closing date), so its input resolves, ``input_resolves`` flips true, and the SAME gate now lets it
through. The gate never changed — only the evidence did.
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

# LP-389 activated IN-1/IN-5; LP-389-A added ID-5; LP-384 added AS-9/IN-4/AS-10 (the stuck deterministic rules).
_ACTIVATED = frozenset({"IN-1", "IN-5", "ID-5", "AS-9", "IN-4", "AS-10"})


def _specs() -> set[str]:
    return {p.stem for p in (Path(ab.__file__).resolve().parents[1] / "rules/specs").glob("*.yaml")}


# --------------------------------------------------------------------------- #
# THE GATE — exactly the eligible candidates pass, the rest are held
# --------------------------------------------------------------------------- #
def test_exactly_the_eligible_candidates_pass() -> None:
    bars = load_activation_bars()
    eligible = {rid for rid, bar in bars.items() if is_eligible(bar)}
    held = set(bars) - eligible
    # IN-1/IN-5 (AI, validated, measured >= bar); ID-5 + AS-9/IN-4/AS-10 (no-AI, input resolves).
    assert eligible == set(_ACTIVATED)
    assert len(held) == 17 and not (held & _ACTIVATED)  # every other candidate is held


def test_eligible_rule_ids_is_sorted_and_matches() -> None:
    assert eligible_rule_ids() == ("AS-10", "AS-9", "ID-5", "IN-1", "IN-4", "IN-5")  # sorted


def test_id5_now_passes_after_the_subject_fix() -> None:
    # The gate BOTH ways: LP-389 held ID-5 (input resolved at the wrong subject); LP-389-A fixed the mismatch
    # (per-borrower, reading the attributed ID), so input_resolves flipped true and the SAME gate admits it.
    bars = load_activation_bars()
    assert bars["ID-5"].status == "no-ai-dependency" and bars["ID-5"].input_resolves
    assert is_eligible(bars["ID-5"]) and "ID-5" in ACTIVE_RULE_IDS


def test_the_held_rules_each_fail_for_a_named_reason() -> None:
    bars = load_activation_bars()
    # a not-calibratable-yet rule: unmeasured AI tag → held regardless of anything else
    assert not is_eligible(bars["AS-2"]) and bars["AS-2"].status == "not-calibratable-yet"
    # a needs-producer rule: the tag doesn't even materialize → held
    assert not is_eligible(bars["IN-14"]) and bars["IN-14"].status == "needs-producer"
    # AS-3 — no-ai but its recipe is a STUB (no §3B cash-to-close calculator): the input never resolves → held
    assert not is_eligible(bars["AS-3"]) and not bars["AS-3"].input_resolves
    # IN-3 — reclassified to an AI rule (its recipe reads documented_monthly, AI) but Priya has not validated
    # its shortfall bar → held; the loader now forbids input_resolves on it (that gate is no-ai-only) (LP-384)
    assert not is_eligible(bars["IN-3"]) and bars["IN-3"].status == "calibratable-now"
    assert not bars["IN-3"].validated and not bars["IN-3"].input_resolves


# --------------------------------------------------------------------------- #
# THE LIVE SET IS base + eligible — the gate is the SOURCE, not a hand-list
# --------------------------------------------------------------------------- #
def test_active_set_is_exactly_base_plus_eligible() -> None:
    # the invariant that keeps a rule from being activated without passing the gate
    assert set(ACTIVE_RULE_IDS) - set(_BASE_ACTIVE) == set(eligible_rule_ids()) == set(_ACTIVATED)
    assert len(ACTIVE_RULE_IDS) == 17 and len(_BASE_ACTIVE) == 11
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
