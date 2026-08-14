"""LP-490a / ADR-378 — the `ratify-pending` activation path and its guardrails.

⚠️ THIS STATUS INVERTS THE GATE'S STATED PRINCIPLE ("activation never trusts what it hasn't measured").
Ratification is the entire safety substitute, so these tests exist to keep the substitute real.

⚠️ SEVEN RULES ARE ON THIS STATUS (CR-1/CR-4/CR-6/CR-8/CR-10 at LP-490a, TI-2/TI-6 at LP-491). Every candidate failed a precondition (see LP-490a.md), so the
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


def test_every_ratify_pending_rule_is_wired_to_ratify() -> None:
    """⚠️ THE SUBSTITUTE MUST BE REAL. `deterministic.py` never set `ratification_pending` before LP-490a,
    so a ratify-pending ai_fuzzy_match rule would have shipped an unmeasured AI judgment as an AUTO
    verdict with no human in the loop.

    The per-rule proof THROUGH A REAL RULE EVALUATION lives in
    test_cr1_undisclosed_liability_lp490.py::test_ratify_pending_findings_carry_ratification — it
    materialises tags and runs the real evaluator, then asserts every finding carries the flag. This test
    guards the SET: if a rule joins the status without that proof being extended to it, it fails."""
    # The set the assertion below pins, NAMED so the failure message diffs against the same thing
    # the assertion checks — the two cannot drift apart the way the old literal did.
    _EXPECTED_RATIFY_PENDING = {
        "CR-1",
        "CR-4",
        "CR-8",
        "CR-6",
        "CR-10",
        "TI-2",
        "TI-6",
        "PR-3",
        "PR-4",
        "PR-5",
        "PC-8",  # LP-493 — personal property (surfaces only, no firing path)
        # LP-495a — the per-rule evaluation proof lives in
        # test_oc1_occupancy_consistency_lp495a.py::test_every_oc1_finding_carries_ratification.
        "OC-1",
        # LP-495b — OC-3; its ratification proof is in test_oc3_investment_rental_lp495b.py.
        "OC-3",
        # LP-495b — IN-13 and IN-14; their ratification proofs are in
        # test_in13_in14_income_continuance_lp495b.py.
        "IN-13",
        "IN-14",
    }
    on_status = {r for r, b in load_activation_bars().items() if b.status == "ratify-pending"}
    assert on_status == _EXPECTED_RATIFY_PENDING, (
        # ⚠️ The diff was against a HAND-LISTED set from two tickets ago (reported finding), so once
        # TI-2/TI-6 and the PR-* lane joined, the failure message printed a symmetric difference that
        # named rules which had NOT drifted. Diffing against the asserted set keeps the message true.
        f"a rule joined ratify-pending without a ratification proof: "
        f"{on_status ^ _EXPECTED_RATIFY_PENDING} — extend the per-rule evaluation proof before adding it"
    )
    for rule_id in on_status:
        assert ratifies_every_finding(rule_id)
    assert not ratifies_every_finding("CR-5")  # a held rule must NOT be wired to ratify
