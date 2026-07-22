"""LP-390-5a — re-score txn.apparent_category with Priya's free-text goldens MAPPED to the enum (the 24.5% in
LP-390-5 was a byte-compare artifact: free-text golden vs enum prediction). These pin the MECHANISM keyless
(the live model accuracy is a point-in-time snapshot in docs/tickets/LP-390-5a.md):

* the LP-379-F mapping is applied at SCORING TIME on the committed goldens — her free text is UNCHANGED;
* held rows (generic memo / uncertain / typo) are EXCLUDED from the confirmed subset, never scored wrong;
* a widened LP-379-E enum value (transfer_third_party_in / debt_payment) is scorable, not marked wrong.
"""

from __future__ import annotations

import csv
from pathlib import Path

from app.verification.eval.apparent_category_relabel import (
    _ENUM,
    map_apparent_category_goldens,
)
from app.verification.eval.live_calibration import ScoredTag, summarize

_JUDGMENT = Path(__file__).resolve().parents[4] / "docs/calibration/lf6t3n-labels-judgment.csv"


def _rows() -> list[dict[str, str]]:
    return list(csv.DictReader(_JUDGMENT.open(encoding="utf-8")))


def test_split_is_17_confirmed_33_held_on_the_committed_golden() -> None:
    confirmed, held = map_apparent_category_goldens(_rows())
    assert (
        len(confirmed) == 17
    )  # description-supported: payroll/interest/transfer_own/third_party_in
    assert len(held) == 33  # 30 generic memos + 2 uncertain + 1 typo
    # every confirmed value is a valid (widened) enum, never off-enum
    assert set(confirmed.values()) <= _ENUM
    # the widened value is represented and scorable (not the old 9-value enum)
    assert "transfer_third_party_in" in confirmed.values()
    # the 30 payee-less memos are held, not forced to a category
    assert sum(1 for h in held if h.description == "CARD PURCHASE / PAYMENT") == 30


def test_held_rows_are_not_in_the_confirmed_scoring_set() -> None:
    confirmed, held = map_apparent_category_goldens(_rows())
    held_keys = {h.subject_id for h in held}
    confirmed_subjects = {sid for (_tag, sid) in confirmed}
    assert held_keys.isdisjoint(confirmed_subjects)  # a row is scored OR held, never both
    # uncertainty is preserved as a held 'unknown', never a confident category
    assert any(h.enum == "unknown" for h in held)


def test_priyas_committed_free_text_is_unchanged() -> None:
    # the mapping is a scoring-time layer — her golden column still holds the verbatim free text
    goldens = {
        r["golden_label"].strip()
        for r in _rows()
        if r["tag_id"] == "txn.apparent_category" and (r.get("golden_label") or "").strip()
    }
    assert {"transfer to some one", "Credit card payment", "big paymrny out"} <= goldens


def test_a_widened_enum_prediction_scores_correct_not_wrong() -> None:
    # score_snapshot_against_golden compares the enum strings, so a correct debt_payment / third_party
    # prediction against a mapped debt_payment / third_party golden is CORRECT (the widening isn't penalized).
    scored = [
        ScoredTag(
            "txn1",
            "txn.apparent_category",
            "transfer_third_party_in",
            "transfer_third_party_in",
            1.0,
            "",
        ),
        ScoredTag("txn2", "txn.apparent_category", "debt_payment", "debt_payment", 0.9, ""),
    ]
    (dim,) = summarize(scored)
    assert dim.accuracy_when_concrete == 1.0
