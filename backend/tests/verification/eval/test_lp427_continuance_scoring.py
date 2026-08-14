"""LP-427 — score income.continuance_3yr against Priya's six blind labels.

The live scoring RESULT (5/6; the one miss is child_support, the AI honestly hedges to `unknown` on the child-age
arithmetic Priya computes to `yes`) is in docs/tickets/LP-427.md and ADR-337 — a point-in-time run of the REAL
reasoner (a key + non-deterministic), so it is NOT re-run in the suite. These KEYLESS tests pin the deterministic
scaffolding the result rests on: the labels join by (tag_id, subject_id) with nothing dropped; the value
distribution is 5 yes / 1 no (thin + skewed — the negative rests on ONE row, an AS-6 caveat, NOT the one-sided
trap); the three CONDITIONAL labels were normalized to `yes` for scoring while Priya's original wording is
PRESERVED verbatim in the CSV (LP-393-4a — not silently rewritten); her values are within the enum.

LP-495b review — WHERE THE 5/6 ENDED UP. LP-427 concluded "no bar proposed, IN-13 stays held"; LP-495b then activated
IN-13 on a scenario-fixture self-consistency rate with `measured_accuracy` left null, so this score lived only
in prose while the field the activation gate reads stayed empty. It is now recorded on the bar alongside a
written `measured_accuracy_override`, and the tests below pin BOTH — the live activation and the fact that
removing the written justification holds the rule again.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest
from app.verification.eval.fire_path_scenarios import build_other_income_continuance_snapshot
from app.verification.eval.live_calibration import score_snapshot_against_golden
from app.verification.eval.stubs import stub_materialization_reasoners
from app.verification.eval.worksheet import load_golden
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.tag_materialization.producer import materialize_tags
from tests.expected_active import EXPECTED_ACTIVE_RULE_COUNT

pytestmark = pytest.mark.anyio

_CSV_PATH = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "calibration"
    / "income-continuance-3yr-labels.csv"
)
_CSV_TEXT = _CSV_PATH.read_text(encoding="utf-8")
_GOLDEN = load_golden(_CSV_TEXT)

_ENUM = {"yes", "no", "unknown"}


# ======================================================================= #
# The join — by (tag_id, subject_id), nothing dropped
# ======================================================================= #
def test_labels_load_and_cover_the_one_tag() -> None:
    assert len(_GOLDEN) == 6  # six borrowers, all labeled (no blanks)
    assert {t for (t, _s) in _GOLDEN} == {"income.continuance_3yr"}


async def test_every_label_joins_to_a_produced_tag_none_dropped() -> None:
    # score_snapshot_against_golden joins by (tag_id, subject_id); an unjoinable label is REPORTED in
    # `unmatched`, never dropped. A stub materialization (deterministic, keyless) still produces the tag at the
    # right subjects, so the join is complete (the ACCURACY needs the live model — that run is in the doc).
    mat = await materialize_tags(
        build_other_income_continuance_snapshot(),
        ai_reasoners=stub_materialization_reasoners(),
        only_groups=frozenset({"income_stability"}),
    )
    scored, unmatched = score_snapshot_against_golden(mat, _GOLDEN)
    assert unmatched == []  # every one of her 6 labels joined to a produced tag
    assert len(scored) == 6
    assert {s.tag_id for s in scored} == {"income.continuance_3yr"}


# ======================================================================= #
# D3 — the distribution is 5 yes / 1 no (thin + skewed, the negative on ONE row) — BEFORE the accuracy number
# ======================================================================= #
def test_distribution_is_five_yes_one_no_thin_and_skewed() -> None:
    values = Counter(v for v in _GOLDEN.values())
    assert values == {"yes": 5, "no": 1}
    # two-sided (a `no` exists — not the AS-6 one-sided trap), but the negative rests on the SINGLE
    # note_receivable row: a single mislabel there would swing the negative direction entirely. The accuracy
    # number (in the doc) is read in the light of this n, never before it.


def test_her_values_are_within_the_enum_no_scoring_artifact() -> None:
    # The LP-390-5a lesson: score against the enum the producer emits. After normalization every golden is a bare
    # yes/no/unknown — no free-text-vs-enum mismatch would masquerade as a disagreement.
    assert set(_GOLDEN.values()) <= _ENUM


# ======================================================================= #
# LP-393-4a — the three CONDITIONAL labels normalized to `yes`, Priya's originals PRESERVED (not silently rewritten)
# ======================================================================= #
def test_conditional_labels_normalized_to_yes_with_originals_preserved() -> None:
    rows = {r["subject_id"]: r for r in _dict_rows(_CSV_TEXT)}
    # the three borrowers Priya labeled "yes - Read note ... for condition"
    conditional = {
        "95000000-0000-4000-8000-000000000101",  # pension
        "95000000-0000-4000-8000-000000000103",  # child support
        "95000000-0000-4000-8000-000000000105",  # social security
    }
    for sid in conditional:
        row = rows[sid]
        assert row["golden_label"] == "yes"  # normalized — scores as yes
        # her ORIGINAL conditional wording is preserved verbatim in the note (the record of why it changed),
        # NOT dropped — and the note records that Geet confirmed the normalization.
        assert "Read note" in row["labeler_note"]
        assert "Geet confirmed" in row["labeler_note"]
        # her documentation CONDITION survives in the Note column she added (untouched)
        assert row["Note"].strip() != ""
    # the non-conditional rows carry no note (bare labels)
    assert rows["95000000-0000-4000-8000-000000000106"]["golden_label"] == "no"  # note_receivable
    assert rows["95000000-0000-4000-8000-000000000104"]["golden_label"] == "yes"  # disability
    assert rows["95000000-0000-4000-8000-000000000102"]["golden_label"] == "yes"  # alimony


# ======================================================================= #
# IN-13 is LIVE on ratify-pending, and LP-427's 5/6 is DECLARED as an override on its bar
# ======================================================================= #
def test_in13_is_live_with_lp427s_score_declared_as_an_override() -> None:
    # LP-427's own conclusion was that 5/6 clears no bar and IN-13 stays held. LP-495b activated it anyway,
    # on a scenario-fixture self-consistency rate (ADR-378) — and left `measured_accuracy` null, which is
    # what let it past the ratify-pending guard that exists to hold a MEASURED-and-failing rule.
    # LP-495b review puts the number back on the bar and makes the activation cost a written justification. This
    # test pins the whole shape, because the tension between the two numbers is the point: a measured 0.833
    # and a self-consistency 1.0 sitting together, with prose saying which one the decision rests on.
    bar = load_activation_bars()["IN-13"]
    assert bar.status == "ratify-pending"
    assert bar.threshold is None
    assert not bar.validated
    assert bar.measured_accuracy == pytest.approx(0.833)  # LP-427's 5/6, no longer omitted
    assert bar.self_consistency_rate == 1.0  # the model agreeing with itself, NOT an accuracy
    assert (
        bar.measured_accuracy_override
    )  # and the reasoning that chose between them is written down
    assert is_eligible(bar)
    assert "IN-13" in ACTIVE_RULE_IDS
    # continuance_3yr is still one of its two load-bearing tags, alongside the unscored income.type
    assert "income.continuance_3yr" in bar.load_bearing_ai_tags
    assert "income.type" in bar.load_bearing_ai_tags


def test_in13_would_be_held_if_the_override_were_removed() -> None:
    # The guard is still the guard: strip the written override and the same bar is NOT eligible. This is
    # what stops LP-495b review from being a blanket loosening — an unmeasured rule activates on a rate as before,
    # a measured-and-failing one activates only with prose attached.
    bar = load_activation_bars()["IN-13"]
    assert not is_eligible(replace(bar, measured_accuracy_override=None))


def test_no_rule_activation_changed() -> None:
    assert (
        len(ACTIVE_RULE_IDS) == EXPECTED_ACTIVE_RULE_COUNT
    )  # 31 — a score with no bar proposed activates nothing


# ----------------------------------------------------------------------- #
def _dict_rows(text: str) -> list[dict[str, str]]:
    import csv
    import io

    return list(csv.DictReader(io.StringIO(text)))
