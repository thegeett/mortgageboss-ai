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
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS


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
    inert = specs - set(ACTIVE_RULE_IDS)
    assert set(bars) == inert  # no inert rule missing, no active rule sneaking in
    assert all(
        b.rationale.strip() for b in bars.values()
    )  # none blank — the proposal Priya reasons over


def test_the_honest_activation_state_is_reported() -> None:
    # only 2 of 23 are calibratable-now; the rest are blocked on calibration / a producer / a wiring decision
    bars = load_activation_bars()
    by = {
        s: sum(1 for b in bars.values() if b.status == s) for s in {b.status for b in bars.values()}
    }
    assert by["calibratable-now"] == 2  # IN-1, IN-5
    assert by.get("not-calibratable-yet", 0) >= 1 and by.get("no-ai-dependency", 0) >= 1


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
    with pytest.raises(ActivationBarError, match="threshold must be null"):
        ab.parse_bar(
            "AS-2",
            {
                "status": "not-calibratable-yet",
                "ships": "auto",
                "threshold": 0.9,
                "validated": False,
                "rationale": "x",
            },
        )


def test_loader_rejects_validating_a_non_calibratable_rule() -> None:
    # Priya can sign off a bar, but NOT on a rule blocked on calibration — that would sign off a tag nobody
    # measured. Only calibratable-now may be validated.
    with pytest.raises(ActivationBarError, match="only a calibratable-now rule may be validated"):
        ab.parse_bar(
            "AS-2",
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
            "AS-2",
            {
                "status": "no-ai-dependency",
                "ships": "auto",
                "threshold": None,
                "validated": "yes",
                "rationale": "x",
            },
        )


# --------------------------------------------------------------------------- #
# Priya's sign-off — exactly IN-1 and IN-5 are validated; all others stay false
# --------------------------------------------------------------------------- #
def test_exactly_in1_in5_are_validated_per_priya() -> None:
    bars = load_activation_bars()
    validated = {rid for rid, b in bars.items() if b.validated}
    assert validated == {"IN-1", "IN-5"}  # Priya's two sign-offs, no more
    assert all(b.validated is False for rid, b in bars.items() if rid not in validated)
    # a validated bar is still calibratable-now with a real threshold (never a blocked rule)
    for rid in ("IN-1", "IN-5"):
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
# EQUIVALENCE — nothing is activated
# --------------------------------------------------------------------------- #
def test_no_rule_activation_changed() -> None:
    assert ACTIVE_RULE_IDS == (
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
    )
    assert not (set(load_activation_bars()) & set(ACTIVE_RULE_IDS))  # bars are for INERT rules only
