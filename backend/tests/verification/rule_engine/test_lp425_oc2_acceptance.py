"""LP-425 — the guard for the OC-2 acceptance (ADR-336 resolution).

DECISION (Geet's, recorded): OC-2 stays LIVE, ratify-only, on the UNSCORED occupancy.consistent_with_signals —
accepted, not deactivated. It is SAFE only because OC-2 is judgmental → it RATIFIES every verdict (LP-376-B), so
the unmeasured tag can never auto-ship. THE ACCEPTANCE IS VALID ONLY WHILE OC-2 RATIFIES — so the load-bearing
guard here is the ships-mode: if a future change made OC-2 auto-ship, these fail loud.

This ticket changes NO behaviour — the tests only PIN the facts the acceptance rests on. The sibling check
(Phase 0) confirmed OC-2 is the ONLY live rule on a genuinely unscored AI tag; that scope is recorded in ADR-336
and docs/tickets/LP-425.md.
"""

from __future__ import annotations

from app.verification.rule_engine.activation_bars import load_activation_bars
from app.verification.rule_engine.registry import _BASE_ACTIVE, ACTIVE_RULE_IDS
from app.verification.rules.kinds import RuleKindName, kind_for
from tests.expected_active import EXPECTED_ACTIVE_RULE_COUNT


# ======================================================================= #
# THE GUARD — the acceptance is valid ONLY WHILE OC-2 ratifies
# ======================================================================= #
def test_oc2_is_live_via_base_and_judgmental_so_it_ratifies() -> None:
    # The load-bearing invariant: OC-2 is live (via _BASE_ACTIVE, predating the gate) AND judgmental, so
    # judgment.py forces ratification_pending (LP-376-B) — every verdict is human-signed. If OC-2 were ever
    # reclassified to a structural/calculative kind it would AUTO-ship on an unscored tag, and the acceptance
    # (ADR-336) would no longer hold — this fails loud the moment that happens.
    assert "OC-2" in _BASE_ACTIVE
    assert "OC-2" in ACTIVE_RULE_IDS
    kind = kind_for("OC-2")
    assert kind is not None and kind.kind is RuleKindName.JUDGMENTAL  # -> ratify, never auto


def test_oc2_tag_is_unscored_the_fact_the_acceptance_rests_on() -> None:
    # occupancy.consistent_with_signals is UNSCORED (never calibrated). OC-1 reads the SAME tag and is held
    # not-calibratable-yet on it — so no bar measures it, confirming OC-2 rides an unmeasured tag. The exit
    # condition (ADR-336): when this tag is calibrated (OC-1 needs it too), OC-1 flips off not-calibratable-yet
    # and OC-2 can move into the gate — so this assertion also marks WHERE the acceptance ends.
    bars = load_activation_bars()
    # ⚠️ LP-495a — OC-1 is now `ratify-pending`, NOT calibrated. The ADR-336 exit condition is UNMET
    # and this still marks where the acceptance ends: the exit is a MEASURED accuracy against Priya
    # labels, and `measured_accuracy is None` says it has not happened. A self-consistency rate does
    # not discharge the acceptance — it is agreement, not correctness.
    assert bars["OC-1"].status == "ratify-pending"
    assert bars["OC-1"].measured_accuracy is None  # STILL unscored — the acceptance stands
    assert "occupancy.consistent_with_signals" in bars["OC-1"].load_bearing_ai_tags
    # no bar anywhere records a measured accuracy for the tag (it is genuinely unscored)
    for bar in bars.values():
        if "occupancy.consistent_with_signals" in bar.load_bearing_ai_tags:
            assert bar.measured_accuracy is None


def test_oc2_has_no_bar_it_is_a_base_rule_not_a_gated_candidate() -> None:
    # OC-2 is NOT in the bars file (which covers exactly the non-base candidates) — giving it a bar would require
    # re-architecting the base/gated split (LP-424 item 2, its own ticket) and would deactivate it (unscored tag
    # -> not-calibratable-yet -> ineligible). So it stays a base rule under this acceptance.
    assert "OC-2" not in load_activation_bars()


def test_no_behaviour_change() -> None:
    # LP-425 records a decision; it changes nothing. ACTIVE stays 31.
    assert len(ACTIVE_RULE_IDS) == EXPECTED_ACTIVE_RULE_COUNT
