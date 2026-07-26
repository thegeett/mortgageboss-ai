"""LP-393-6 — re-score has_2yr_history under Priya's ruling, then validate + activate the four bars.

Priya settled the open items: a TERMINATED job's two years DOES count as HISTORY (has_2yr_history is about
history only), and the W-2/1099/offer-letter documentation standard is a SEPARATE check. Under that ruling B12
and B14's has_2yr_history goldens became `yes` (their originals preserved in the worksheet Note as the record),
and the tag was RE-SCORED (not hand-edited) — so IN-11's measured accuracy CHANGED BY MEASUREMENT, never by
asserting 0.85 -> 1.0. She signed off the four heights and chose AUTO, knowingly overriding the ratify-only
recommendation on a synthetic-only basis.

These pin (keyless; the live re-score number lives in docs/tickets/LP-393-6.md, not asserted): the two goldens
changed exactly and her originals are preserved; the four bars are validated at her heights; IN-11 now clears
its own gate (measured >= threshold); validating activated the four (ACTIVE 24, the gate invariant intact); and
⚠️ IN-7 ships RATIFY despite the AUTO sign-off — a judgment rule never auto-ships (LP-376-B), reported not
forced.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from app.verification.rule_engine.activation_bars import (
    activation_mode,
    is_eligible,
    load_activation_bars,
)
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS

_CSV = Path(__file__).resolve().parents[4] / "docs/calibration/income-scenario-labels.csv"
_B12 = "93000000-0000-4000-8000-000000000012"
_B14 = "93000000-0000-4000-8000-000000000014"
_FOUR = ("IN-7", "IN-10", "IN-11", "AS-11")


def _rows() -> dict[tuple[str, str], dict[str, str]]:
    return {
        (r["tag_id"], r["subject_id"]): r
        for r in csv.DictReader(io.StringIO(_CSV.read_text(encoding="utf-8")))
    }


def test_b12_b14_goldens_became_yes_originals_preserved() -> None:
    rows = _rows()
    for sid, original in ((_B12, "unknown"), (_B14, "no")):
        row = rows[("income.has_2yr_history", sid)]
        assert row["golden_label"].strip() == "yes"  # per Priya's ruling: history exists in both
        note = row["Note"]
        assert (
            "LP-393-6" in note and f"Original label: {original}" in note
        )  # the record of the change
        assert "SEPARATE" in note  # the documentation standard is a separate rule, not this tag


def test_the_four_bars_are_validated_at_priyas_heights() -> None:
    bars = load_activation_bars()
    heights = {"IN-7": 0.90, "IN-10": 0.95, "IN-11": 0.90, "AS-11": 0.90}
    for rid, h in heights.items():
        b = bars[rid]
        assert b.validated is True, rid
        assert b.threshold == h, rid


def test_in11_now_clears_its_own_gate_after_the_rescore() -> None:
    # the whole point: under the ruling has_2yr_history re-scored high enough that IN-11 passes its bar. If the
    # re-score had NOT delivered (measured < threshold), this would fail — a finding, not a forced number.
    b = load_activation_bars()["IN-11"]
    assert b.measured_accuracy is not None and b.measured_accuracy >= b.threshold
    assert is_eligible(b)


def test_validating_activated_the_four() -> None:
    # validating a bar (validated + measured >= threshold) makes it eligible, and in this system eligibility ==
    # active (the LP-389 invariant). So the four are now live; ACTIVE went 20 -> 24.
    bars = load_activation_bars()
    for rid in _FOUR:
        assert is_eligible(bars[rid]), rid
        assert rid in ACTIVE_RULE_IDS, rid
    assert len(ACTIVE_RULE_IDS) == 25  # +AS-8 (LP-406-2b)


def test_in7_ships_ratify_despite_the_auto_signoff() -> None:
    # ⚠️ the reported conflict: Priya asked AUTO, but IN-7 is JUDGMENTAL — LP-376-B forbids a judgment rule from
    # auto-shipping. ships STAYS ratify; activation_mode routes it to ratify even at measured 1.0 >= bar. Truly
    # auto would need a kind reclassification (ADR-316) — NOT silently forced here.
    bars = load_activation_bars()
    in7 = bars["IN-7"]
    assert in7.ships == "ratify"  # not flipped to auto despite her request
    assert activation_mode(in7, in7.measured_accuracy) == "ratify"  # a human ratifies every verdict
    # the three calculative rules DO ship auto (their kind matches her AUTO call — no armor conflict)
    for rid in ("IN-10", "IN-11", "AS-11"):
        b = bars[rid]
        assert b.ships == "auto"
        assert activation_mode(b, b.measured_accuracy) == "auto"
