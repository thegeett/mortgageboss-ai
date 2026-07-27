"""LP-397 — the PROPOSED activation bar for AS-6 (stmt.owner_matches_borrower).

LP-390-8a made the tag produce (5/5 structural abstain -> 5/5 real comparisons, 100% vs Priya's goldens). This
writes AS-6's proposed bar (calibratable-now, a real threshold, `validated: false`) as the decision surface
Priya reasons over — it SETS no bar and ACTIVATES nothing. These pin that, and that the two load-bearing
caveats are PRESENT (not buried): the 100% is ONE-SIDED (n=5, all `yes` — the dangerous FN direction untested),
and the name-match strictness is Priya's underwriting call.
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


def test_as6_is_calibratable_now_with_a_real_threshold_and_unvalidated() -> None:
    b = load_activation_bars()["AS-6"]
    assert b.status == "calibratable-now"
    assert b.ships == "auto"  # structural kind -> auto (matches AS-6's rule_kinds row)
    assert b.threshold == pytest.approx(0.95)
    assert b.measured_accuracy == pytest.approx(1.0)  # 5/5 — but see the one-sided caveat
    assert b.validated is False  # Priya's sign-off flips it (and, per LP-393-6, activates it)


def test_proposing_the_bar_activates_nothing() -> None:
    # validated:false -> not eligible; the eligible set + the live set are unchanged (still 13 / 24).
    bars = load_activation_bars()
    assert not is_eligible(bars["AS-6"])
    assert "AS-6" not in ACTIVE_RULE_IDS
    assert len(eligible_rule_ids()) == 14  # +AS-8 (LP-406-2b, no-ai-dependency, input resolves)
    assert len(ACTIVE_RULE_IDS) == 25


def test_the_rationale_states_the_one_sided_n_and_the_name_match_strictness() -> None:
    # the caveats are NOT optional — a 100% that reads as "validated" would hide that the DANGEROUS direction
    # (a genuine mismatch) has never been tested, and that the tolerance is an underwriting judgment.
    low = load_activation_bars()["AS-6"].rationale.lower()
    assert "one-sided" in low  # the headline caveat: 5/5, all `yes`
    assert (
        "never been tested" in low and "negative case" in low
    )  # the untested dangerous FN direction
    assert "strictness" in low and "tolerant" in low  # the name-match call flagged for Priya
    assert "n is 5" in low or "n=5" in low  # the real n (not the 8-golden count)


def test_as6_has_a_single_load_bearing_tag_no_second_tag_trap() -> None:
    # the LP-390-6 / AS-2 check: AS-6 rests on ONE measured tag (owner_matches_borrower) — no second, unmeasured
    # load-bearing tag holding it back.
    assert load_activation_bars()["AS-6"].load_bearing_ai_tags == ("stmt.owner_matches_borrower",)


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
