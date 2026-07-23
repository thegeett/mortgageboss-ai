"""LP-393-4b — the FRESH-golden state Priya's blind re-label produced, and the split it feeds.

LP-393-2a blanked the 7 stale `same_line_of_work` cells (the "No occupation given" data gaps) and Priya
re-labeled them blind on the occupation-PRESENT sheet. These pin (keyless — the live 100% accuracy is
non-deterministic and lives in docs/tickets/LP-393-4b.md):

- the re-label RESOLVED the data gap: every `same_line_of_work` cell now carries a concrete golden (no blank,
  no remaining `unknown`) — a remaining `unknown` here would have been a real finding, and there is none;
- the re-label round did NOT disturb the other three tags' goldens, nor the same_line rows she left alone
  (B7/B11/B14/B15); it DID revise two cells she'd labeled on the occupation-less sheet — B5 `no`->`yes`,
  B8 `yes`->`no` — both her fresh judgment, reported, not reverted;
- the clear-cut same_line checks (B7 nurse->nurse=`yes`, B8 warehouse->office=`no`) hold with occupation shown;
- ``split_scored`` still keeps clear-cut apart from ambiguous and counts an ``unknown`` as a valid label.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from app.verification.eval.income_scenario_scoring import scenario_of, split_scored
from app.verification.eval.live_calibration import ScoredTag

_CSV = Path(__file__).resolve().parents[4] / "docs/calibration/income-scenario-labels.csv"
_B = (
    "93000000-0000-4000-8000-0000000000"  # borrower id prefix; append the two-digit scenario number
)

# the same_line clear-cut expectations (occupation now present, so they are answerable)
_CLEARCUT = {7: {"income.same_line_of_work": "yes"}, 8: {"income.same_line_of_work": "no"}}
_RELABELED = (3, 4, 6, 9, 10, 12, 13)  # LP-393-2a blanked these 7; Priya re-labeled them blind
_UNTOUCHED_SAME_LINE = (
    7,
    11,
    14,
    15,
)  # decisive rows she left alone (B5/B8 she revised — see below)


def _goldens() -> dict[tuple[str, str], str]:
    return {
        (r["tag_id"], r["subject_id"]): (r["golden_label"] or "").strip()
        for r in csv.DictReader(io.StringIO(_CSV.read_text(encoding="utf-8")))
    }


def _notes() -> dict[tuple[str, str], str]:
    return {
        (r["tag_id"], r["subject_id"]): (r["Note"] or "")
        for r in csv.DictReader(io.StringIO(_CSV.read_text(encoding="utf-8")))
    }


def test_same_line_data_gap_is_resolved_no_blank_no_unknown() -> None:
    g = _goldens()
    same = {sid: v for (tag, sid), v in g.items() if tag == "income.same_line_of_work"}
    assert len(same) == 13  # all 13 borrower scenarios
    assert all(v for v in same.values()), "a same_line cell is still blank — not re-labeled"
    # with occupation present she reached a concrete call on EVERY row — no residual `unknown` (a finding
    # would have been a remaining `unknown` here; there is none). Distribution: 12 yes / 1 no (B8).
    assert sorted(same.values()) == ["no"] + ["yes"] * 12
    assert same[_B + "08"] == "no"  # the one `no` is B8 (career change)


def test_the_seven_relabeled_cells_are_now_filled_and_keep_their_evidence() -> None:
    g, notes = _goldens(), _notes()
    for n in _RELABELED:
        sid = _B + f"{n:02d}"
        assert g[("income.same_line_of_work", sid)]  # filled (blank was blanked in LP-393-2a)
        note = notes[("income.same_line_of_work", sid)]
        assert "No occupation given" in note and "RE-LABEL" in note  # the evidence chain kept


def test_clearcut_same_line_checks_hold_with_occupation_shown() -> None:
    g = _goldens()
    assert g[("income.same_line_of_work", _B + "07")] == "yes"  # nurse -> nurse (same line)
    assert (
        g[("income.same_line_of_work", _B + "08")] == "no"
    )  # warehouse -> office (different line)


def test_untouched_same_line_rows_unchanged_and_two_were_revised() -> None:
    g = _goldens()
    # rows she left alone across the re-label round
    for n in _UNTOUCHED_SAME_LINE:
        assert g[("income.same_line_of_work", _B + f"{n:02d}")] == "yes"
    # the two she REVISED on the occupation-present sheet (her fresh judgment — reported, not reverted):
    assert (
        g[("income.same_line_of_work", _B + "05")] == "yes"
    )  # single-employer -> her "one employer=yes"
    assert (
        g[("income.same_line_of_work", _B + "08")] == "no"
    )  # occupation revealed the career change


def test_other_three_tags_goldens_untouched_by_the_relabel() -> None:
    g = _goldens()
    # has_2yr_history — the two divergence rows (the open framing item + her pay-stub nuance) as she wrote them
    assert (
        g[("income.has_2yr_history", _B + "14")] == "no"
    )  # B14 framing question — left `no`, unsettled
    assert (
        g[("income.has_2yr_history", _B + "12")] == "unknown"
    )  # pay-stub-only, her documentation standard
    assert g[("income.has_2yr_history", _B + "05")] == "no"  # single year
    # is_declining — the two LP-393-4a corrections stand
    assert g[("income.is_declining", _B + "09")] == "yes"
    assert g[("income.is_declining", _B + "15")] == "no"
    # asset.liquidation_terms — LP-393-4a's precedence corrections stand (carried, asset_facts not re-run)
    assert g[("asset.liquidation_terms", "inc-asset-4")] == "restricted"
    assert g[("asset.liquidation_terms", "inc-asset-5")] == "restricted"
    assert g[("asset.liquidation_terms", "inc-asset-6")] == "restricted"
    assert g[("asset.liquidation_terms", "inc-asset-1")] == "fully_liquid"
    assert g[("asset.liquidation_terms", "inc-asset-3")] == "vested_usable"


def test_split_keeps_clearcut_apart_and_counts_unknown_as_valid() -> None:
    # a same_line clear-cut pair that agrees + an ambiguous row + a both-`unknown` (valid label, not a skip)
    scored = [
        ScoredTag(_B + "07", "income.same_line_of_work", "yes", "yes", 0.9, "nurse->nurse"),
        ScoredTag(_B + "08", "income.same_line_of_work", "no", "no", 0.9, "warehouse->office"),
        ScoredTag(_B + "09", "income.same_line_of_work", "yes", "yes", 0.9, "no change"),
        ScoredTag(_B + "10", "income.has_2yr_history", "unknown", "unknown", 0.5, "abstain"),
    ]
    by_tag = split_scored(scored, _CLEARCUT)
    sl = by_tag["income.same_line_of_work"]
    assert {c.scenario for c in sl.clearcut} == {7, 8}  # only the clear-cut expectations
    assert {c.scenario for c in sl.ambiguous} == {9}  # B9 has no clear-cut expected answer
    assert sl.agreement_rate(sl.cells) == 1.0
    h2 = by_tag["income.has_2yr_history"]
    (unk,) = h2.cells
    assert unk.priya_unknown and unk.ai_agrees_priya  # both-unknown counts, never dropped
    assert scenario_of(_B + "07") == 7 and scenario_of("inc-asset-4") is None
