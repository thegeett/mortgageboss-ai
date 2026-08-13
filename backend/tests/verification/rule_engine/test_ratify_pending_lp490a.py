"""LP-490a / ADR-378 — the `ratify-pending` activation path and its guardrails.

⚠️ THIS STATUS INVERTS THE GATE'S STATED PRINCIPLE ("activation never trusts what it hasn't measured").
Ratification is the entire safety substitute, so these tests exist to keep the substitute real.

⚠️ NO RULE IS ON THIS STATUS YET. Every candidate failed a precondition (see LP-490a.md), so the
mechanism ships proven-but-unused. These tests exercise it directly against constructed bars, which is
legitimate for a LOADER contract; the rule-evaluation proof required by LP-487 lands with the first rule
that actually activates, and `test_ratify_pending_wires_ratification_through_evaluation` below is written
to fail loudly if one is added without it.
"""

from __future__ import annotations

import pytest
from app.verification.rule_engine.activation_bars import (
    ActivationBarError,
    is_eligible,
    load_activation_bars,
    parse_bar,
    ratifies_every_finding,
)
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS

_BASE = {
    "status": "ratify-pending",
    "ships": "auto",
    "threshold": None,
    "validated": False,
    "load_bearing_ai_tags": ["x.y"],
    "fp_fn": "f",
    "rationale": "r" * 40,
    "input_resolves": True,
    "self_consistency_rate": 0.95,
    "self_consistency_cases": 40,
    "self_consistency_disagreements": 2,
    "self_consistency_model": "claude-sonnet-4-5",
    "self_consistency_date": "2026-08-13",
}


def test_a_ratify_pending_bar_with_a_consistency_rate_is_eligible() -> None:
    assert is_eligible(parse_bar("X-1", dict(_BASE)))


def test_a_bar_carrying_both_numbers_is_rejected() -> None:
    """⚠️ THE NON-NEGOTIABLE SEPARATION. `measured_accuracy` means a HUMAN said what the right answer
    was; `self_consistency_rate` means the MODEL said the same thing twice. Collapsing them destroys the
    only signal telling a future reader which kind of number a bar carries."""
    with pytest.raises(ActivationBarError, match="cannot carry BOTH"):
        parse_bar("X-2", {**_BASE, "measured_accuracy": 0.9})


def test_a_self_consistency_rate_cannot_satisfy_the_calibrated_path() -> None:
    """⚠️ `calibratable-now` still requires a MEASURED accuracy. A consistency number must never open
    the calibrated door."""
    bar = parse_bar(
        "X-3",
        {
            **_BASE,
            "status": "calibratable-now",
            "threshold": 0.9,
            "validated": True,
            "input_resolves": False,
        },
    )
    assert bar.self_consistency_rate == 0.95
    assert bar.measured_accuracy is None
    assert not is_eligible(bar), "a consistency rate must not satisfy calibratable-now"


def test_a_ratify_pending_bar_needs_a_rate_at_all() -> None:
    with pytest.raises(ActivationBarError, match="needs a self_consistency_rate"):
        parse_bar("X-4", {**_BASE, "self_consistency_rate": None})


def test_a_rate_over_zero_cases_is_rejected() -> None:
    """⚠️ A rate over ZERO cases is not a number. CR-5 (one inquiry row), CR-6 (zero derogatory events)
    and CR-10 (zero collection codes) have nothing to derive twice, and must stay held rather than
    activate on a vacuous 1.0."""
    with pytest.raises(ActivationBarError, match="not a number"):
        parse_bar("X-5", {**_BASE, "self_consistency_cases": 0})


def test_a_rate_without_a_case_count_is_rejected() -> None:
    """A 1.0 over 2 cases and a 1.0 over 200 are different claims."""
    with pytest.raises(ActivationBarError, match="needs self_consistency_cases"):
        parse_bar("X-6", {**_BASE, "self_consistency_cases": None})


def test_a_measured_and_failing_rule_can_never_take_this_path() -> None:
    """⚠️ AS-4's `stmt.is_reserve_eligible` measured 0/5 against Priya's labels (LP-390-5) — a SYSTEMATIC
    domain disagreement, which two independent derivations would score 1.0 on precisely because the model
    is consistently wrong. Measured-and-failing is not unmeasured. The gate requires
    `measured_accuracy is None`, so no consistency rate can override a real measurement."""
    bar = parse_bar("X-7", dict(_BASE))
    assert bar.measured_accuracy is None and is_eligible(bar)
    # the same bar with a real (failing) measurement cannot even load, let alone activate
    with pytest.raises(ActivationBarError):
        parse_bar("X-8", {**_BASE, "measured_accuracy": 0.0})


def test_as4_is_still_held() -> None:
    assert "AS-4" not in ACTIVE_RULE_IDS


def test_ratify_pending_wires_ratification_through_evaluation() -> None:
    """⚠️ THE SUBSTITUTE MUST BE REAL. `deterministic.py` never set `ratification_pending` before
    LP-490a, so an ai_fuzzy_match rule on this status would have shipped an unmeasured AI judgment as an
    AUTO verdict with no human in the loop.

    No rule is on this status yet, so this asserts the wiring exists and that the set is empty. ⚠️ WHEN
    THE FIRST RULE ACTIVATES, this test FAILS — deliberately — and whoever adds it must replace this with
    a per-rule proof THROUGH A RULE EVALUATION that every finding carries the flag (LP-487's standing
    rule; LP-508's guard passed by calling the mechanism directly and reached 1 of 5 rules)."""
    on_status = [r for r, b in load_activation_bars().items() if b.status == "ratify-pending"]
    assert on_status == [], (
        "a rule now uses ratify-pending — replace this test with a per-rule proof, through a real rule "
        f"evaluation, that every finding from {on_status} carries ratification_pending=True"
    )
    assert not ratifies_every_finding("CR-1")
