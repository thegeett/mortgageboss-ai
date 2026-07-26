"""LP-380 — activation bars: the declared decision surface for which inert rules may go live.

These pin the discipline: the table is COMPLETE (every inert rule has a proposed bar + rationale); a rule with
an UNMEASURED tag is BLOCKED ON CALIBRATION, never "just below a bar" (the two statuses are visually and
behaviourally distinct — else a rule ships on a tag nobody measured); every bar is validated=false (Priya's
sign-off flips it, not this ticket); the bar is DECLARED and resolved by data, no per-rule evaluator branch;
and it reconciles with LP-376-B as one safety with two settings (below-bar → needs_review, judgment → ratify).
Nothing is activated: ACTIVE_RULE_IDS is unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.verification.rule_engine import activation_bars as ab
from app.verification.rule_engine.activation_bars import (
    ActivationBar,
    ActivationBarError,
    activation_mode,
    load_activation_bars,
)
from app.verification.rule_engine.registry import _BASE_ACTIVE, ACTIVE_RULE_IDS


def _bar(status: str, ships: str, threshold: float | None) -> ActivationBar:
    return ActivationBar("X-1", status, ships, threshold, False, (), "", "test")


# --------------------------------------------------------------------------- #
# COMPLETE — every inert rule has a proposed bar + rationale
# --------------------------------------------------------------------------- #
def test_bars_cover_exactly_the_inert_rules() -> None:
    bars = load_activation_bars()
    specs = {
        p.stem for p in (Path(ab.__file__).resolve().parents[1] / "rules/specs").glob("*.yaml")
    }
    # Anchored to _BASE_ACTIVE, not the live set: a rule LP-389 activated (IN-1/IN-5) KEEPS its bar as the
    # record of why it went live, so the candidate set stays a stable 27 (23 + OC-1 LP-406-4 + AS-8 LP-406-2b
    # + IN-6 LP-406-3b + PC-7 LP-406-1b) rather than shrinking on activation.
    candidates = specs - set(_BASE_ACTIVE)
    assert set(bars) == candidates  # no candidate rule missing, no base-active rule sneaking in
    assert all(
        b.rationale.strip() for b in bars.values()
    )  # none blank — the proposal Priya reasons over


def test_the_honest_activation_state_is_reported() -> None:
    # 11 of 27 are calibratable-now; the rest are blocked on calibration / a producer / a wiring decision.
    # OC-1 (LP-406-4) not-calibratable-yet; AS-8 (LP-406-2b) no-ai + LIVE; IN-6 (LP-406-3b) calibratable-now
    # (transitive AI, proposed 0.95, held); PC-7 (LP-406-1b) no-ai but HELD (its window is an unvalidated default).
    bars = load_activation_bars()
    by = {
        s: sum(1 for b in bars.values() if b.status == s) for s in {b.status for b in bars.values()}
    }
    # 9 SIGNED OFF (IN-1, IN-5, IN-3 + AS-2, AS-12 + IN-7, IN-10, IN-11, AS-11) + 2 PROPOSED-but-unvalidated
    # (AS-6, LP-397 — one-sided n=5; IN-6, LP-406-3b — proposed IN-5's 0.95, pending Priya).
    assert (
        by["calibratable-now"] == 11
    )  # +IN-6 (LP-406-3b, transitive AI dependency, proposed 0.95, held)
    assert by.get("not-calibratable-yet", 0) >= 1 and by.get("no-ai-dependency", 0) >= 1
    # LP-390-7 signed off AS-2 + AS-12; LP-390-9 signed off IN-3; LP-393-6 signed off IN-7/IN-10/IN-11/AS-11 —
    # those NINE calibratable rules are validated; AS-6 (LP-397) is calibratable but NOT yet validated.
    assert all(
        bars[r].validated
        for r in ("IN-1", "IN-5", "AS-2", "AS-12", "IN-3", "IN-7", "IN-10", "IN-11", "AS-11")
    )
    assert bars["AS-6"].status == "calibratable-now" and bars["AS-6"].threshold is not None
    assert not bars[
        "AS-6"
    ].validated  # proposed, not signed off — validating it would activate it (LP-393-6)


# --------------------------------------------------------------------------- #
# not-calibratable-yet ≠ bar-unmet — the load-bearing distinction
# --------------------------------------------------------------------------- #
def test_unmeasured_rule_is_blocked_not_below_a_bar() -> None:
    # an unmeasured rule has NO threshold and resolves to 'blocked' — never 'needs_review' (which would imply a
    # measured score that merely fell short). Conflating them would ship a rule on a tag nobody measured.
    for status in ("not-calibratable-yet", "needs-producer", "no-ai-dependency"):
        bar = _bar(status, "auto", None)
        assert bar.threshold is None
        assert activation_mode(bar, 0.999) == "blocked"
    # a CALIBRATABLE rule below its bar is a different thing: needs_review, not blocked
    assert activation_mode(_bar("calibratable-now", "auto", 0.98), 0.90) == "needs_review"


def test_loader_rejects_a_threshold_on_a_non_calibratable_rule() -> None:
    # These loader-rejection tests use the neutral synthetic label "X-1" (not a real rule id) — the rejected
    # bar shapes below are invalid on purpose, and "AS-2" is now a real validated calibratable-now rule.
    with pytest.raises(ActivationBarError, match="threshold must be null"):
        ab.parse_bar(
            "X-1",
            {
                "status": "not-calibratable-yet",
                "ships": "auto",
                "threshold": 0.9,
                "validated": False,
                "rationale": "x",
            },
        )


def test_loader_rejects_a_boolean_threshold() -> None:
    # A YAML bool is an int in Python (bool ⊂ int); `threshold: true` must fail loud, never coerce to a
    # silent 1.0 bar in an otherwise fail-loud loader.
    with pytest.raises(ActivationBarError, match="proposed threshold in"):
        ab.parse_bar(
            "X-1",
            {
                "status": "calibratable-now",
                "ships": "auto",
                "threshold": True,
                "validated": False,
                "rationale": "x",
            },
        )


def test_loader_rejects_validating_a_non_calibratable_rule() -> None:
    # Priya can sign off a bar, but NOT on a rule blocked on calibration — that would sign off a tag nobody
    # measured. Only calibratable-now may be validated.
    with pytest.raises(ActivationBarError, match="only a calibratable-now rule may be validated"):
        ab.parse_bar(
            "X-1",
            {
                "status": "not-calibratable-yet",
                "ships": "auto",
                "threshold": None,
                "validated": True,
                "rationale": "x",
            },
        )


def test_loader_rejects_non_bool_validated() -> None:
    with pytest.raises(ActivationBarError, match="validated must be a boolean"):
        ab.parse_bar(
            "X-1",
            {
                "status": "no-ai-dependency",
                "ships": "auto",
                "threshold": None,
                "validated": "yes",
                "rationale": "x",
            },
        )


# --------------------------------------------------------------------------- #
# Priya's sign-off — IN-1/IN-5 (LP-389) + AS-2/AS-12 (LP-390-7) + IN-3 (LP-390-9) are validated; rest stay false
# --------------------------------------------------------------------------- #
def test_exactly_the_signed_off_bars_are_validated() -> None:
    bars = load_activation_bars()
    validated = {rid for rid, b in bars.items() if b.validated}
    # IN-1/IN-5 (LP-389) + AS-2/AS-12 (LP-390-7) + IN-3 (LP-390-9) + IN-7/IN-10/IN-11/AS-11 (LP-393-6) — every
    # calibratable rule is signed off now.
    assert validated == {
        "IN-1",
        "IN-5",
        "AS-2",
        "AS-12",
        "IN-3",
        "IN-7",
        "IN-10",
        "IN-11",
        "AS-11",
    }
    assert all(b.validated is False for rid, b in bars.items() if rid not in validated)
    # a validated bar is always calibratable-now with a real threshold (never a blocked rule — loader invariant)
    for rid in validated:
        assert bars[rid].status == "calibratable-now" and bars[rid].threshold is not None


def test_thresholds_exist_only_where_calibratable() -> None:
    for b in load_activation_bars().values():
        assert (b.threshold is not None) == (b.status == "calibratable-now")
        if b.threshold is not None:
            assert 0.0 <= b.threshold <= 1.0


# --------------------------------------------------------------------------- #
# DECLARED, not branched — activation_mode depends only on bar DATA, not rule identity
# --------------------------------------------------------------------------- #
def test_mode_is_data_driven_not_per_rule() -> None:
    a = ActivationBar("IN-1", "calibratable-now", "auto", 0.98, False, (), "", "r")
    b = ActivationBar("ZZ-9", "calibratable-now", "auto", 0.98, False, (), "", "r")
    assert activation_mode(a, 0.99) == activation_mode(b, 0.99) == "auto"  # same data → same mode


# --------------------------------------------------------------------------- #
# Reconciled with LP-376-B — one safety, two settings
# --------------------------------------------------------------------------- #
def test_below_bar_routes_to_needs_review_and_judgment_ratifies() -> None:
    assert activation_mode(_bar("calibratable-now", "auto", 0.98), 0.97) == "needs_review"
    assert activation_mode(_bar("calibratable-now", "auto", 0.98), 0.98) == "auto"
    # a judgment rule NEVER auto-ships (LP-376-B) — it ratifies even at 100%
    assert activation_mode(_bar("calibratable-now", "ratify", 0.98), 1.0) == "ratify"


# --------------------------------------------------------------------------- #
# ACTIVATION — LP-380 activated nothing; LP-389 (the first pass) activated exactly IN-1/IN-5 via the gate
# --------------------------------------------------------------------------- #
def test_active_set_is_base_plus_lp389() -> None:
    assert (
        ACTIVE_RULE_IDS
        == (
            "AS-1",
            "OC-2",
            "ID-2",
            "ID-4",
            "ID-1",
            "ID-3",
            "ID-6",
            "ID-7",
            "ID-9",
            "ID-8",
            "IN-2",
            # LP-389 — the first activation pass, via the eligibility gate (activation_bars.is_eligible)
            "IN-1",
            "IN-5",
            "ID-5",  # LP-389-A — the subject mismatch fixed (per-borrower), input now resolves
            # LP-384 — the second activation pass: the stuck deterministic rules, verified on build_lf6t3n_plus
            "AS-9",
            "IN-4",
            "AS-10",
            # LP-390-7 — the first income-wave activation: AS-2 (auto) + AS-12 (ratify), Priya's 0.90 bars signed off
            "AS-2",
            "AS-12",
            "IN-3",  # LP-390-9 — YTD-annualized shortfall (auto), Priya signed off the 0.98 bar (same tag as IN-1)
            # LP-393-6 — the scenario-calibrated income/asset rules; Priya signed off her heights + chose AUTO
            # (IN-7 still ships RATIFY by kind — LP-376-B armor). is_declining/has_2yr_history/liquidation scored
            # on the LP-393-1 fixture; has_2yr_history RE-SCORED after her B14 ruling.
            "IN-7",
            "IN-10",
            "IN-11",
            "AS-11",
            # LP-406-2b — the first Bucket 2 rule live: AS-8 (statement chaining) on the derived stmt.continuity
            # tag; no-ai-dependency, input resolves ("chained" on LF-6T3N).
            "AS-8",
        )
    )
    # A bar persists after activation as the record of WHY the rule went live, so the bars now intersect the
    # active set at EXACTLY the activated candidates — never a base-active rule (those never had a bar).
    assert set(load_activation_bars()) & set(ACTIVE_RULE_IDS) == {
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
        "AS-8",  # LP-406-2b — live via its bar (no-ai-dependency, input resolves)
    }
    assert not (set(load_activation_bars()) & set(_BASE_ACTIVE))
