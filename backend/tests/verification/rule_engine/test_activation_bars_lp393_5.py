"""LP-393-5 — the activation bars for the four scenario-calibrated rules (IN-7, IN-10, IN-11, AS-11).

LP-393-5 PROPOSED these bars (calibratable-now, real thresholds, `validated: false`) from LP-393-4b's
scenario-fixture scores. **LP-393-6 then validated + activated them** — Priya signed off her heights and chose
AUTO (overriding the ratify-only recommendation), and IN-11 was RE-SCORED to 100% after her B14 ruling. These
pin the decision-surface SHAPE that survives that transition: each of the four is calibratable-now with a real
threshold and its measured accuracy, and every rationale carries the synthetic-data caveat so a sign-off never
rests on a stronger basis than exists. The validated/active/re-scored state itself is pinned in
test_activation_bars_lp393_6 (and the gate invariant in test_activation_gate_lp389).
"""

from __future__ import annotations

import pytest
from app.verification.rule_engine.activation_bars import (
    ActivationBarError,
    load_activation_bars,
    parse_bar,
)

_PROPOSED = ("IN-7", "IN-10", "IN-11", "AS-11")
# the decision-surface shape per rule: (ships, threshold, measured_accuracy). IN-11's measured is 1.0 as of
# LP-393-6 (re-scored under Priya's B14 ruling — see test_activation_bars_lp393_6 for the re-score story).
_EXPECTED = {
    "IN-7": (
        "ratify",
        0.90,
        1.0,
    ),  # judgmental — the threshold is a surfacing floor (ships stays ratify)
    "IN-10": ("auto", 0.95, 1.0),  # calculative, FN-dangerous — a high bar
    "IN-11": ("auto", 0.90, 1.0),  # calculative, FN-dangerous — re-scored to 1.0 (LP-393-6)
    "AS-11": ("auto", 0.90, 1.0),  # calculative, FN-dangerous, thin n=6
}


def test_the_four_are_calibratable_now_with_a_real_threshold() -> None:
    bars = load_activation_bars()
    for rid in _PROPOSED:
        b = bars[rid]
        assert b.status == "calibratable-now", rid
        assert b.threshold is not None and 0.0 <= b.threshold <= 1.0, rid
        assert b.measured_accuracy is not None, rid


def test_the_shape_matches_the_decision_surface() -> None:
    bars = load_activation_bars()
    for rid, (ships, thr, meas) in _EXPECTED.items():
        b = bars[rid]
        assert b.ships == ships, rid
        assert b.threshold == pytest.approx(thr), rid
        assert b.measured_accuracy == pytest.approx(meas), rid


def test_every_rationale_carries_the_synthetic_caveat() -> None:
    # the caveat is NOT optional — a bar without it lets a sign-off rest on a stronger basis than exists.
    bars = load_activation_bars()
    for rid in _PROPOSED:
        r = bars[rid].rationale.lower()
        assert r.strip(), rid  # non-blank
        assert "synthetic" in r and "lf-6t3n" in r, (
            f"{rid} rationale must carry the synthetic-data caveat"
        )


def test_loader_reject_rule_still_fires_the_as5_guard() -> None:
    # the fail-closed invariant is UNBROKEN: a validated bar on a non-calibratable rule (null threshold) is
    # rejected, so a stray validated:true can never leak a blocked rule live (the AS-5 protection).
    with pytest.raises(ActivationBarError, match="only a calibratable-now rule may be validated"):
        parse_bar(
            "IN-11",
            {
                "status": "not-calibratable-yet",
                "ships": "auto",
                "threshold": None,
                "validated": True,
                "load_bearing_ai_tags": ["income.has_2yr_history"],
                "rationale": "r",
            },
        )
