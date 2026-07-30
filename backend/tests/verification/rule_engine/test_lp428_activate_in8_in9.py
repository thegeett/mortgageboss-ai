"""LP-428 — activate IN-8 (VOE present) + IN-9 (offer letter present) on Priya's sign-off.

LP-426 scored income.voe_present + income.offer_letter_present at 100% (12/12, two-sided, 0 disagreements) and
PROPOSED 0.95 AUTO bars, validated:false, with the synthetic caveat recorded for Priya to weigh. LP-428 is her
sign-off: validated:true clears each calibratable-now gate (1.0 >= 0.95), so IN-8 + IN-9 go live (31 -> 33). These
tests pin the activation: exactly the two flip; IN-13 (the sibling) stays HELD; the income_docs group folds into
the required set so both tags are PRODUCED when the rules run (not the LP-384 missing-tag trap); both ship auto per
their structural kind; and the LP-389 invariant holds. The real-run verdicts (LF-6T3N + the labeling fixture) are
in docs/tickets/LP-428.md (a point-in-time run of the live reasoner — not re-run here).
"""

from __future__ import annotations

import pytest
from app.verification.eval.fire_path_scenarios import build_voe_offer_labeling_snapshot
from app.verification.eval.stubs import stub_materialization_reasoners
from app.verification.rule_engine.activation_bars import (
    eligible_rule_ids,
    is_eligible,
    load_activation_bars,
)
from app.verification.rule_engine.registry import _BASE_ACTIVE, ACTIVE_RULE_IDS
from app.verification.rules.specs import load_rule_spec
from app.verification.tag_materialization.producer import materialize_tags
from tests.expected_active import EXPECTED_ACTIVE_RULE_COUNT

pytestmark = pytest.mark.anyio


# ======================================================================= #
# Exactly IN-8 + IN-9 flip — validated, eligible, live; the sibling IN-13 does NOT ride along
# ======================================================================= #
def test_in8_in9_are_validated_and_eligible() -> None:
    bars = load_activation_bars()
    for rid in ("IN-8", "IN-9"):
        bar = bars[rid]
        assert bar.status == "calibratable-now"
        assert bar.threshold == 0.95 and bar.measured_accuracy == 1.0  # LP-426's score
        assert bar.validated  # LP-428 — Priya signed off
        assert is_eligible(bar)  # validated + 1.0 >= 0.95
        assert rid in ACTIVE_RULE_IDS


def test_in13_the_sibling_stays_held_no_ride_along() -> None:
    # IN-13 is the other-income-continuance sibling in this family. It has TWO open blockers (LP-423/LP-427):
    # the missing "has other income" scope gate (ADR-335) and income.type still unscored. Activating IN-8/IN-9
    # must NOT sweep it live.
    bar = load_activation_bars()["IN-13"]
    assert bar.status == "not-calibratable-yet"
    assert not bar.validated and not is_eligible(bar)
    assert "IN-13" not in ACTIVE_RULE_IDS


def test_lp428_flipped_exactly_in8_in9_not_as6() -> None:
    # LP-428 flipped ONLY IN-8 + IN-9 — never every calibratable-now-but-unsigned bar. AS-6 had the same
    # 0.95/1.0 shape but was unsigned at the LP-428 moment, so LP-428 left it held. (AS-6 was later activated on
    # its OWN sign-off in LP-429 — a separate ticket, a separate ruling; this pins that LP-428 did not sweep it.)
    from app.verification.rule_engine.registry import _LP428_ACTIVATED

    assert set(_LP428_ACTIVATED) == {"IN-8", "IN-9"}
    assert "AS-6" not in _LP428_ACTIVATED


# ======================================================================= #
# The count + the LP-389 invariant
# ======================================================================= #
def test_in8_in9_live_and_invariant_holds() -> None:
    # (The absolute count moved to 34 when LP-429 activated AS-6; the single-source count guard lives in
    # tests/expected_active.py, so this asserts the invariant + that IN-8/IN-9 are in the eligible set.)
    assert len(ACTIVE_RULE_IDS) == EXPECTED_ACTIVE_RULE_COUNT
    # a rule cannot enter the active set without passing the gate
    assert set(ACTIVE_RULE_IDS) - set(_BASE_ACTIVE) == set(eligible_rule_ids())
    assert {"IN-8", "IN-9"} <= set(eligible_rule_ids())
    assert len(set(ACTIVE_RULE_IDS)) == len(ACTIVE_RULE_IDS)  # no duplicates


def test_ship_mode_matches_the_kind_auto_for_structural() -> None:
    # IN-8/IN-9 are structural presence checks (deterministic) → ships auto per their bar (not ratify).
    bars = load_activation_bars()
    for rid in ("IN-8", "IN-9"):
        assert bars[rid].ships == "auto"
        assert (
            load_rule_spec(rid).deterministic is not None
        )  # deterministic → auto is the correct routing


# ======================================================================= #
# The income_docs fold-in — both tags are PRODUCED when the rules run (NOT the LP-384 missing-tag trap)
# ======================================================================= #
async def test_income_docs_folds_in_so_the_tags_are_produced() -> None:
    # Activating IN-8/IN-9 newly requires the income_docs group (only they read these tags). Materializing it on
    # the labeling fixture PRODUCES both tags at the document subjects — so at rule time the tags exist and a
    # couldnt_check (if any) is an honest DATA reason, never a missing-tag one (the LP-384 trap).
    from app.services.verification_run import _ai_groups_for_rules, _required_ai_groups

    assert _ai_groups_for_rules(("IN-8", "IN-9")) == frozenset({"income_docs"})
    assert (
        "income_docs" in _required_ai_groups()
    )  # folds into the LIVE required set now that they are active

    snap = build_voe_offer_labeling_snapshot()
    snap = await materialize_tags(
        snap, ai_reasoners=stub_materialization_reasoners(), only_groups=frozenset({"income_docs"})
    )
    produced = {
        tid
        for sub in snap.tags.by_subject.values()
        for tid in sub
        if tid in ("income.voe_present", "income.offer_letter_present")
    }
    assert produced == {"income.voe_present", "income.offer_letter_present"}
