"""LP-426 — score income.voe_present + income.offer_letter_present against Priya's blind labels.

The live scoring RESULT (both tags 100%, 12/12, two-sided, 0 disagreements) is in docs/tickets/LP-426.md — it is
a point-in-time run of the REAL reasoner (a key + non-deterministic), so it is NOT re-run in the suite. These
KEYLESS tests pin the deterministic scaffolding the result rests on: the labels join by (tag_id, subject_id) with
nothing dropped; the value distribution is TWO-SIDED per tag (the AS-6 one-sided trap avoided); an explicit
`unknown` is a valid label, not a skipped blank; and the PROPOSED bars are validated:false so they activate
nothing (ACTIVE stays 31 — Priya's sign-off is the activation).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from app.verification.eval.fire_path_scenarios import build_voe_offer_labeling_snapshot
from app.verification.eval.live_calibration import score_snapshot_against_golden
from app.verification.eval.stubs import stub_materialization_reasoners
from app.verification.eval.worksheet import load_golden
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.tag_materialization.producer import materialize_tags
from tests.expected_active import EXPECTED_ACTIVE_RULE_COUNT

pytestmark = pytest.mark.anyio

_CSV = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "calibration"
    / "income-docs-voe-offer-labels.csv"
)
_GOLDEN = load_golden(_CSV.read_text(encoding="utf-8"))


# ======================================================================= #
# The join — by (tag_id, subject_id), nothing dropped
# ======================================================================= #
def test_labels_load_and_cover_both_tags() -> None:
    assert len(_GOLDEN) == 24  # 12 voe_present + 12 offer_letter_present, all labeled (no blanks)
    tags = Counter(t for (t, _s) in _GOLDEN)
    assert tags == {"income.voe_present": 12, "income.offer_letter_present": 12}


async def test_every_label_joins_to_a_produced_tag_none_dropped() -> None:
    # score_snapshot_against_golden joins by (tag_id, subject_id); an unjoinable label is REPORTED in
    # `unmatched`, never dropped. A stub materialization (deterministic, keyless) still produces the tags at the
    # right subjects, so the join is complete (the ACCURACY needs the live model — that is in the doc).
    mat = await materialize_tags(
        build_voe_offer_labeling_snapshot(),
        ai_reasoners=stub_materialization_reasoners(),
        only_groups=frozenset({"income_docs"}),
    )
    scored, unmatched = score_snapshot_against_golden(mat, _GOLDEN)
    assert unmatched == []  # every one of her 24 labels joined to a produced tag
    assert len(scored) == 24
    assert {s.tag_id for s in scored} == {"income.voe_present", "income.offer_letter_present"}


# ======================================================================= #
# D1 — the value distribution is TWO-SIDED (the AS-6 one-sided trap avoided)
# ======================================================================= #
def test_both_tags_are_two_sided_not_one_sided() -> None:
    for tag in ("income.voe_present", "income.offer_letter_present"):
        values = Counter(v for (t, _s), v in _GOLDEN.items() if t == tag)
        assert values["yes"] >= 1 and values["no"] >= 1, (tag, values)
        # this fixture: exactly 6 yes / 6 no per tag — offer_letter_present has the real positive class LP-395
        # could not measure (its n=0 empty class before LP-418).
        assert values["yes"] == 6 and values["no"] == 6


def test_unknown_is_a_valid_label_not_a_skipped_blank() -> None:
    # load_golden keeps an explicit `unknown` (informative — she couldn't tell) but skips a BLANK (she didn't
    # reach the row). The LP-393-4 discipline — the two are distinct.
    csv = (
        "tag_id,subject_id,golden_label\n"
        "income.voe_present,a,unknown\n"  # a valid label — kept
        "income.voe_present,b,\n"  # a blank — skipped
    )
    loaded = load_golden(csv)
    assert loaded == {("income.voe_present", "a"): "unknown"}  # unknown kept, blank dropped


# ======================================================================= #
# The bars — proposed at 0.95 here, SIGNED OFF by Priya in LP-428 (which activated IN-8 + IN-9, 31 -> 33)
# ======================================================================= #
def test_bars_signed_off_by_lp428_and_rules_are_active() -> None:
    # LP-426 PROPOSED these bars validated:false (nothing activated). LP-428 is Priya's sign-off — she approved
    # 0.95 for both, weighing the synthetic caveat, so the bars are now validated:true and IN-8/IN-9 are live.
    bars = load_activation_bars()
    for rid in ("IN-8", "IN-9"):
        bar = bars[rid]
        assert bar.status == "calibratable-now"
        assert (
            bar.threshold == 0.95 and bar.measured_accuracy == 1.0
        )  # LP-426's 100% two-sided score
        assert bar.validated  # LP-428 — Priya signed off (the proposal became the activation)
        assert is_eligible(bar)  # validated:true + 1.0 >= 0.95 -> eligible
        assert rid in ACTIVE_RULE_IDS


def test_active_count_reflects_the_two_activations() -> None:
    assert (
        len(ACTIVE_RULE_IDS) == EXPECTED_ACTIVE_RULE_COUNT
    )  # 33 — LP-428 activated IN-8 + IN-9 on Priya's sign-off
