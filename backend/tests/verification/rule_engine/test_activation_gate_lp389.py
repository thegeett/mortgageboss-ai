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

import pytest
from app.verification.rule_engine import activation_bars as ab
from app.verification.rule_engine.activation_bars import (
    ActivationBarError,
    activation_mode,
    eligible_rule_ids,
    is_eligible,
    load_activation_bars,
    parse_bar,
)
from app.verification.rule_engine.registry import _BASE_ACTIVE, ACTIVE_RULE_IDS

# LP-389 activated IN-1/IN-5; LP-389-A added ID-5; LP-384 added AS-9/IN-4/AS-10 (the stuck deterministic rules);
# LP-390-7 added AS-2/AS-12 (the first income-wave AI rules); LP-390-9 added IN-3 (same tag+evidence as IN-1);
# LP-393-6 added IN-7/IN-10/IN-11/AS-11 (the scenario-calibrated income/asset rules, signed off by Priya).
_ACTIVATED = frozenset(
    {
        "IN-1",
        "IN-5",
        "ID-5",
        "AS-9",
        "IN-4",
        "AS-10",
        "AS-2",
        "AS-12",
        "IN-3",
        "IN-7",
        "IN-10",
        "IN-11",
        "AS-11",
        "AS-8",  # LP-406-2b — the first Bucket 2 rule live (no-ai-dependency; stmt.continuity resolves)
    }
)


def _specs() -> set[str]:
    return {p.stem for p in (Path(ab.__file__).resolve().parents[1] / "rules/specs").glob("*.yaml")}


# --------------------------------------------------------------------------- #
# THE GATE — exactly the eligible candidates pass, the rest are held
# --------------------------------------------------------------------------- #
def test_exactly_the_eligible_candidates_pass() -> None:
    bars = load_activation_bars()
    eligible = {rid for rid, bar in bars.items() if is_eligible(bar)}
    held = set(bars) - eligible
    # IN-1/IN-5/AS-2/AS-12/IN-3 (AI, validated, measured >= bar); ID-5 + AS-9/IN-4/AS-10 (no-AI, input resolves).
    assert eligible == set(_ACTIVATED)
    # 12 held: the 10 pre-LP-406 candidates + OC-1 (LP-406-4, AI tag unscored) + IN-6 (LP-406-3b, bar proposed
    # but validated:false pending Priya). AS-8 (LP-406-2b) is NOT held — it went live.
    assert len(held) == 12 and not (held & _ACTIVATED)  # every other candidate is held


def test_eligible_rule_ids_is_sorted_and_matches() -> None:
    assert eligible_rule_ids() == (
        "AS-10",
        "AS-11",
        "AS-12",
        "AS-2",
        "AS-8",  # LP-406-2b
        "AS-9",
        "ID-5",
        "IN-1",
        "IN-10",
        "IN-11",
        "IN-3",
        "IN-4",
        "IN-5",
        "IN-7",
    )  # sorted


def test_id5_now_passes_after_the_subject_fix() -> None:
    # The gate BOTH ways: LP-389 held ID-5 (input resolved at the wrong subject); LP-389-A fixed the mismatch
    # (per-borrower, reading the attributed ID), so input_resolves flipped true and the SAME gate admits it.
    bars = load_activation_bars()
    assert bars["ID-5"].status == "no-ai-dependency" and bars["ID-5"].input_resolves
    assert is_eligible(bars["ID-5"]) and "ID-5" in ACTIVE_RULE_IDS


def test_the_held_rules_each_fail_for_a_named_reason() -> None:
    bars = load_activation_bars()
    # a not-calibratable-yet rule: unmeasured AI tag → held regardless of anything else
    assert not is_eligible(bars["AS-4"]) and bars["AS-4"].status == "not-calibratable-yet"
    # AS-5 — LP-390-7 fail-closed proof: not-calibratable-yet + null threshold → held; validated stays false
    # (the loader would REJECT a stray true on it — see test_loader_rejects_validating_a_non_calibratable_rule),
    # so a mis-set flag can never leak AS-5 live even though apparent_category is now measured.
    assert not is_eligible(bars["AS-5"]) and bars["AS-5"].status == "not-calibratable-yet"
    assert bars["AS-5"].threshold is None and not bars["AS-5"].validated
    # a needs-producer rule: the tag doesn't even materialize → held
    assert not is_eligible(bars["IN-14"]) and bars["IN-14"].status == "needs-producer"
    # AS-3 — no-ai but its recipe is a STUB (no §3B cash-to-close calculator): the input never resolves → held
    assert not is_eligible(bars["AS-3"]) and not bars["AS-3"].input_resolves
    # (IN-3 was the "calibratable but not-yet-signed" held example through LP-390-7; LP-390-9 signed off its bar,
    # so it is now eligible + active — see test_in3_is_live_after_priya_signoff. Every remaining held rule fails
    # for one of the reasons above.)


# --------------------------------------------------------------------------- #
# THE LIVE SET IS base + eligible — the gate is the SOURCE, not a hand-list
# --------------------------------------------------------------------------- #
def test_active_set_is_exactly_base_plus_eligible() -> None:
    # the invariant that keeps a rule from being activated without passing the gate
    assert set(ACTIVE_RULE_IDS) - set(_BASE_ACTIVE) == set(eligible_rule_ids()) == set(_ACTIVATED)
    assert (
        len(ACTIVE_RULE_IDS) == 25 and len(_BASE_ACTIVE) == 11
    )  # +AS-8 (LP-406-2b, first Bucket 2 live)
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


# --------------------------------------------------------------------------- #
# LP-390-7 — the first income-wave activation (AS-2 auto, AS-12 ratify) + the AS-5 fail-closed proof
# --------------------------------------------------------------------------- #
def test_as2_ships_auto_and_as12_routes_to_ratify() -> None:
    # the LP-376-B routing: AS-2 (structural) ships a TRUSTED auto verdict once measured >= bar; AS-12
    # (judgmental) NEVER auto-ships — a human ratifies every verdict, so activation_mode is 'ratify'.
    bars = load_activation_bars()
    assert activation_mode(bars["AS-2"], bars["AS-2"].measured_accuracy) == "auto"
    assert activation_mode(bars["AS-12"], bars["AS-12"].measured_accuracy) == "ratify"


def test_as2_as12_are_live_and_eligible() -> None:
    bars = load_activation_bars()
    for rid in ("AS-2", "AS-12"):
        assert bars[rid].status == "calibratable-now" and bars[rid].validated
        assert bars[rid].measured_accuracy is not None and bars[rid].threshold is not None
        assert bars[rid].measured_accuracy >= bars[rid].threshold
        assert is_eligible(bars[rid]) and rid in ACTIVE_RULE_IDS


def test_as5_stays_held_and_a_stray_validated_flag_is_a_load_error() -> None:
    # the fail-closed hardening: AS-5 is not-calibratable-yet with a null threshold, so it is HELD; and the
    # loader REJECTS a validated:true on it (a mis-set sign-off is a load error, not silent eligibility).
    bars = load_activation_bars()
    assert bars["AS-5"].status == "not-calibratable-yet" and not bars["AS-5"].validated
    assert bars["AS-5"].threshold is None and not is_eligible(bars["AS-5"])
    assert "AS-5" not in ACTIVE_RULE_IDS
    with pytest.raises(ActivationBarError, match="only a calibratable-now rule may be validated"):
        parse_bar(
            "AS-5",
            {
                "status": "not-calibratable-yet",
                "ships": "auto",
                "threshold": None,
                "validated": True,  # the stray flag the ticket warned of — must fail loud
                "rationale": "x",
            },
        )


# --------------------------------------------------------------------------- #
# LP-390-9 — IN-3 activation (Priya signed off its 0.98 bar; same tag + evidence as IN-1)
# --------------------------------------------------------------------------- #
def test_in3_is_live_after_priya_signoff() -> None:
    bars = load_activation_bars()
    in3 = bars["IN-3"]
    # calibratable-now, a REAL threshold (not the AS-5 null/stray-flag class), validated, measured >= bar
    assert in3.status == "calibratable-now" and in3.ships == "auto"
    assert in3.threshold == 0.98 and in3.validated
    assert in3.measured_accuracy is not None and in3.measured_accuracy >= in3.threshold
    assert in3.load_bearing_ai_tags == ("income.documented_monthly",)  # the IN-1 tag + evidence
    assert is_eligible(in3) and "IN-3" in ACTIVE_RULE_IDS


def test_in3_validated_bar_is_legal_not_the_as5_stray_flag_class() -> None:
    # the LP-390-7 loader guard rejects validated:true on a NON-calibratable / null-threshold rule (AS-5). IN-3
    # is the legal counter-case: calibratable-now WITH a real threshold → the loader ACCEPTS the validated bar.
    ok = parse_bar(
        "IN-3",
        {
            "status": "calibratable-now",
            "ships": "auto",
            "threshold": 0.98,
            "validated": True,
            "measured_accuracy": 1.0,
            "load_bearing_ai_tags": ["income.documented_monthly"],
            "rationale": "x",
        },
    )
    assert is_eligible(ok)  # no ActivationBarError — a real bar signed off is legal
