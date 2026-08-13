"""LP-397 — AS-6's activation bar (stmt.owner_matches_borrower), PROPOSED here, SIGNED OFF in LP-429.

LP-390-8a made the tag produce (5/5 structural abstain -> real comparisons); LP-397 wrote AS-6's proposed bar
(calibratable-now, 0.95, `validated: false`) as the decision surface Priya reasons over. Its one-sided caveat
(n=5, all `yes`) was resolved by LP-398's six negative cases + LP-404's multi-tag rule (four firing), and
**LP-429 is Priya's sign-off** — validated:true, AS-6 live. These tests now pin the ACTIVATED bar: the routing
rests on two 11/11 tags (owner_matches + non_borrower_co_holder), the reason-only holder_name_variance (5/11) is
excluded from the bar (ADR-338), and the AS-5 loader guard is unbroken.
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


def test_as6_is_calibratable_now_with_a_real_threshold_and_signed_off() -> None:
    b = load_activation_bars()["AS-6"]
    assert b.status == "calibratable-now"
    assert b.ships == "auto"  # structural kind -> auto (matches AS-6's rule_kinds row)
    assert b.threshold == pytest.approx(0.95)
    assert b.measured_accuracy == pytest.approx(1.0)  # the routing drivers, both 11/11
    assert b.validated is True  # LP-429 — Priya signed off (and, per LP-393-6, that activates it)


def test_the_sign_off_activated_as6() -> None:
    # LP-429: validated:true -> eligible; AS-6 is now live.
    bars = load_activation_bars()
    assert is_eligible(bars["AS-6"])
    assert "AS-6" in ACTIVE_RULE_IDS
    from tests.expected_active import EXPECTED_ACTIVE_RULE_COUNT

    assert (
        len(eligible_rule_ids())
        == 50  # LP-493 +PC-8  # LP-492 +PR-2/PR-3/PR-4/PR-5/PR-7  # LP-491 +TI-1/TI-2/TI-6  # LP-490a +CR-1/CR-4/CR-8 (ratify-pending)  # LP-488 +MI-1/MI-4/CO-1/AU-3  # LP-487 +IH-2/IH-7  # LP-486 +CR-12  # LP-485 +CL-1/CR-13/PR-6
    )  # +AS-8 +PC-2 +IH-3 +PC-3 +IN-12 +IN-8 +IN-9 +AS-6 +IN-15 +IN-16 +IH-1 (LP-447 — insurance adequacy)
    assert len(ACTIVE_RULE_IDS) == EXPECTED_ACTIVE_RULE_COUNT


def test_the_rationale_records_what_priya_signed_off() -> None:
    # LP-429: the one-sided caveat is RESOLVED (negatives now exist), so the rationale records the four things
    # her sign-off covers instead — the height, ships-auto-because-the-ratify-condition-is-met, what the bar
    # measures (routing vs the reason-only variance tag), and the synthetic + D5 caveats it ships with.
    low = load_activation_bars()["AS-6"].rationale.lower()
    assert "0.95" in low and "auto" in low  # the height + the ships mode
    assert "routing" in low  # what the bar measures (the multi-tag precedent)
    assert "synthetic" in low and "coverage gap" in low  # the caveats it ships with


def test_as6_bar_measures_the_two_routing_tags_not_the_reason_only_variance() -> None:
    # LP-429 / ADR-338 — AS-6 is the FIRST multi-tag rule. Its bar gates on the VERDICT-driving (routing) tags,
    # both 11/11; the reason-only holder_name_variance (5/11) is deliberately NOT a bar tag (a human reviews the
    # needs_review row its text populates, so its accuracy does not gate the verdict).
    lb = load_activation_bars()["AS-6"].load_bearing_ai_tags
    assert lb == ("stmt.owner_matches_borrower", "stmt.non_borrower_co_holder")
    assert "stmt.holder_name_variance" not in lb


def test_loader_reject_rule_still_fires_the_as5_guard() -> None:
    # the fail-closed invariant is UNBROKEN: a validated bar on a non-calibratable rule (null threshold) is
    # rejected, so a stray validated:true can never leak a blocked rule live (the AS-5 protection).
    with pytest.raises(ActivationBarError, match="cannot be signed off as live-able"):
        parse_bar(
            "AS-6",
            {
                "status": "not-calibratable-yet",
                "ships": "auto",
                "threshold": None,
                "validated": True,
                "load_bearing_ai_tags": ["stmt.owner_matches_borrower"],
                "rationale": "r",
            },
        )
