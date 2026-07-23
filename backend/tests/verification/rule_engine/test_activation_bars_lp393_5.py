"""LP-393-5 — the PROPOSED activation bars for the four scenario-calibrated rules (IN-7, IN-10, IN-11, AS-11).

LP-393-4b landed all four load-bearing tags calibration-passed on the LP-393-1 scenario fixture. This ticket
writes each rule's proposed bar (status calibratable-now, a real threshold, `validated: false`) as the decision
surface Priya reasons over — it SETS no bar and ACTIVATES nothing. These pin exactly that: the four are now
calibratable with a proposed threshold and an honest measured accuracy; NONE is validated, so NONE is eligible
(proposing a bar is not activating it); the loader's fail-closed invariants still hold; and every rationale
carries the synthetic-data caveat so Priya never approves on a stronger basis than exists.
"""

from __future__ import annotations

import pytest
from app.verification.rule_engine.activation_bars import (
    ActivationBarError,
    eligible_rule_ids,
    is_eligible,
    load_activation_bars,
    parse_bar,
)
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS

_PROPOSED = ("IN-7", "IN-10", "IN-11", "AS-11")
# the expected proposal per rule: (ships, threshold, measured_accuracy)
_EXPECTED = {
    "IN-7": ("ratify", 0.90, 1.0),  # judgmental — the threshold is a surfacing floor
    "IN-10": ("auto", 0.95, 1.0),  # calculative, FN-dangerous — a high bar
    "IN-11": (
        "auto",
        0.90,
        0.85,
    ),  # measured 0.85 (honest, not rounded); below the proposed bar — see rationale
    "AS-11": ("auto", 0.90, 1.0),  # calculative, FN-dangerous, thin n=6
}


def test_the_four_are_calibratable_now_with_a_real_threshold_and_unvalidated() -> None:
    bars = load_activation_bars()
    for rid in _PROPOSED:
        b = bars[rid]
        assert b.status == "calibratable-now", rid
        assert b.threshold is not None and 0.0 <= b.threshold <= 1.0, rid
        assert b.validated is False, f"{rid} must stay validated:false — Priya's sign-off flips it"
        assert b.measured_accuracy is not None, rid


def test_the_proposed_shape_matches_the_decision_surface() -> None:
    bars = load_activation_bars()
    for rid, (ships, thr, meas) in _EXPECTED.items():
        b = bars[rid]
        assert b.ships == ships, rid
        assert b.threshold == pytest.approx(thr), rid
        assert b.measured_accuracy == pytest.approx(meas), rid


def test_in11_reports_85_percent_honestly_not_rounded_up() -> None:
    # the ticket's explicit constraint: report 85% AND the interpretation — never silently round it to 100%.
    b = load_activation_bars()["IN-11"]
    assert b.measured_accuracy == pytest.approx(0.85)  # the measured number, not 1.0
    assert b.threshold == pytest.approx(
        0.90
    )  # measured sits BELOW the proposed bar — flagged in the rationale
    low = b.rationale.lower()
    assert (
        "b14" in low and "documentation standard" in low
    )  # the interpretation + the open framing question


def test_proposing_a_bar_activates_nothing() -> None:
    # validated:false → not eligible; the eligible set + the live set are byte-for-byte unchanged (still 9 / 20).
    bars = load_activation_bars()
    for rid in _PROPOSED:
        assert not is_eligible(bars[rid]), f"{rid} must NOT be eligible — it is unvalidated"
    assert eligible_rule_ids() == (
        "AS-10",
        "AS-12",
        "AS-2",
        "AS-9",
        "ID-5",
        "IN-1",
        "IN-3",
        "IN-4",
        "IN-5",
    )
    assert len(ACTIVE_RULE_IDS) == 20
    assert not (set(_PROPOSED) & set(ACTIVE_RULE_IDS))  # none of the four went live


def test_every_proposed_rationale_carries_the_synthetic_caveat() -> None:
    # the caveat is NOT optional — a bar without it lets Priya approve on a stronger basis than exists.
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
