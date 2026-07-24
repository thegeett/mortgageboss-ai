"""LP-401 — extend the owner-match fixture with the two missing cases (surname_differs n=0, co_holder yes n=1)
+ a discriminating control, then confirm the 3-tag worksheet covers them.

Keyless: the live probe (N7 -> surname_differs, N8 -> co_holder yes, N9 -> co_holder NO, the original 8
unperturbed by the roster change) is reported in docs/tickets/LP-401.md. These pin the FIXTURE shape: Sarah Chen
joins the roster without dropping the original two; N9 (both borrowers) is the discriminating control whose
co_holder is clear-cut `no` (joint != a problem); N2 is reclassified to ambiguous (3-run instability, not the
roster); and the worksheet carries the 3 new scenarios blind for all three tags.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from app.verification.eval.owner_match_scenarios import (
    AMBIGUOUS_CASES,
    CLEARCUT_CO_HOLDER,
    CLEARCUT_EXPECTATIONS,
    OWNER_MATCH_WORKSHEET_FILE,
    build_owner_match_scenario_snapshot,
)
from app.verification.snapshot.fields import Field
from app.verification.tag_materialization.subjects import loan_borrower_roster

_COMMITTED = Path(__file__).resolve().parents[4] / "docs/calibration" / OWNER_MATCH_WORKSHEET_FILE
_SNAP = build_owner_match_scenario_snapshot()
_HOLDERS = {
    e.content_id: f.value
    for e in _SNAP.documents.entries
    if isinstance(f := e.fields["account_holder_name"], Field)
}


def test_the_three_new_scenarios_exist_with_the_right_holders() -> None:
    assert _HOLDERS["own-n7"] == "Sarah Nguyen"  # surname_differs (vs borrower Sarah Chen)
    assert (
        _HOLDERS["own-n8"] == "ROBERT CHEN AND LINDA CHEN"
    )  # a spouse-shaped non-borrower co-holder
    assert _HOLDERS["own-n9"] == "JORDAN A RIVERA AND ROBERT CHEN"  # both borrowers (the control)
    assert len(_SNAP.documents.entries) == 11  # 8 original + 3 new


def test_the_roster_gained_sarah_without_dropping_the_original_two() -> None:
    # D1 — the original two must stay so the original 8 remain comparable; Sarah is appended for N7.
    assert loan_borrower_roster(_SNAP) == ["Jordan A Rivera", "Robert Chen", "Sarah Chen"]


def test_n9_is_the_discriminating_control_co_holder_clearcut_no() -> None:
    # THE control: a joint account of BOTH borrowers -> co_holder `no`. Without it the tag could pass by
    # answering "is this joint?" (yes) instead of "is a holder a non-borrower?" (no).
    assert CLEARCUT_CO_HOLDER["N9"] == "no"
    # the two `yes` cases (a non-borrower co-holder is present) — N5 unrelated, N8 spouse-shaped
    assert CLEARCUT_CO_HOLDER["N5"] == "yes" and CLEARCUT_CO_HOLDER["N8"] == "yes"
    # every single-holder statement is a clear `no`
    assert all(
        CLEARCUT_CO_HOLDER[k] == "no" for k in ("N1", "N2", "N3", "N4", "N6", "N7", "P1", "P2")
    )


def test_n2_is_reclassified_to_ambiguous() -> None:
    # 3 runs (LP-398 unknown / LP-400 no / LP-401 yes) prove Roberta-vs-Robert is genuinely ambiguous, not a
    # clear-cut `no`. It is NOT the roster's doing (it moved in LP-400 with no roster change).
    assert "N2" in AMBIGUOUS_CASES and "N2" not in CLEARCUT_EXPECTATIONS


def test_the_worksheet_carries_the_new_scenarios_blind_for_all_three_tags() -> None:
    rows = list(csv.DictReader(io.StringIO(_COMMITTED.read_text(encoding="utf-8"))))
    for new in ("own-n7", "own-n8", "own-n9"):
        tags = {r["tag_id"] for r in rows if r["subject_id"] == new}
        assert tags == {
            "stmt.owner_matches_borrower",
            "stmt.holder_name_variance",
            "stmt.non_borrower_co_holder",
        }  # all three tags present for each new scenario
        assert all(
            not (r["golden_label"] or "").strip() for r in rows if r["subject_id"] == new
        )  # blind — no encoded answer, not even for N9's clear-cut co_holder
