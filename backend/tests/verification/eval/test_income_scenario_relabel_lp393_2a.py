"""LP-393-2a — regenerate the scenario worksheet after the fixture fix (occupation added) for a BLIND re-label.

LP-393-4a's occupation fix STALED the same_line_of_work labels Priya made on the occupation-less sheet (her 7
`unknown`s were "No occupation given", a data gap, not a judgment). These pin (keyless): the regeneration
PRESERVES every still-valid label + note, BLANKS only the stale same_line_of_work cells (her original note kept
as evidence), renders `occupation` into the context so she can now judge, and leaks NO prediction/expected
answer (anti-anchoring — LP-393-4a published the AI's new answers, they must not reach the sheet).
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from app.verification.eval.income_scenarios import (
    SCENARIO_WORKSHEET_FILE,
    regenerate_income_scenario_worksheet,
)

_COLS = [
    "tag_id",
    "subject_id",
    "subject_kind",
    "document_type",
    "source_document",
    "scoring",
    "allowed_values",
    "consuming_rules",
    "rule_status",
    "context",
    "golden_label",
    "labeler_note",
    "Note",
]
_B3 = "93000000-0000-4000-8000-000000000003"
_B7 = "93000000-0000-4000-8000-000000000007"


def _seed(out_dir: Path) -> None:
    # a stale same_line cell (data gap), a DECISIVE same_line cell, and an is_declining cell (unaffected)
    rows = [
        {
            "tag_id": "income.same_line_of_work",
            "subject_id": _B3,
            "golden_label": "unknown",
            "Note": "No occupation given.",
            "context": "[w2] employer_name=Acme | q?",
        },
        {
            "tag_id": "income.same_line_of_work",
            "subject_id": _B7,
            "golden_label": "yes",
            "Note": "",
            "context": "[w2] employer_name=Hospital | q?",
        },
        {
            "tag_id": "income.is_declining",
            "subject_id": _B3,
            "golden_label": "no",
            "Note": "her domain note",
            "context": "[w2] wages=80000 | q?",
        },
    ]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_COLS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in _COLS})
    (out_dir / SCENARIO_WORKSHEET_FILE).write_text(buf.getvalue(), encoding="utf-8")


def _rows(out_dir: Path) -> dict[tuple[str, str], dict[str, str]]:
    text = (out_dir / SCENARIO_WORKSHEET_FILE).read_text(encoding="utf-8")
    return {(r["tag_id"], r["subject_id"]): r for r in csv.DictReader(io.StringIO(text))}


def test_stale_cell_is_blanked_valid_cells_preserved(tmp_path: Path) -> None:
    _seed(tmp_path)
    result = regenerate_income_scenario_worksheet(tmp_path)
    assert result == {
        "preserved": 2,
        "blanked": 1,
    }  # is_declining + decisive same_line kept; 1 stale blanked
    rows = _rows(tmp_path)
    stale = rows[("income.same_line_of_work", _B3)]
    assert stale["golden_label"] == ""  # the data-gap cell is blanked for a fresh judgment
    assert (
        "No occupation given" in stale["Note"] and "RE-LABEL" in stale["Note"]
    )  # her evidence KEPT
    # a decisively-answered same_line cell survives; is_declining (occupation doesn't drive it) survives whole
    assert rows[("income.same_line_of_work", _B7)]["golden_label"] == "yes"
    assert rows[("income.is_declining", _B3)]["golden_label"] == "no"
    assert rows[("income.is_declining", _B3)]["Note"] == "her domain note"


def test_occupation_renders_into_the_regenerated_context(tmp_path: Path) -> None:
    _seed(tmp_path)
    regenerate_income_scenario_worksheet(tmp_path)
    rows = _rows(tmp_path)
    # the whole point: the blanked cell's context now SHOWS occupation, so Priya can actually judge it
    assert "occupation=" in rows[("income.same_line_of_work", _B3)]["context"]


def test_no_prediction_or_expected_answer_leaks(tmp_path: Path) -> None:
    _seed(tmp_path)
    regenerate_income_scenario_worksheet(tmp_path)
    rows = _rows(tmp_path)
    # the blanked golden is EMPTY (no AI answer supplied); the context carries only facts + the neutral prompt,
    # never LP-393-4a's published AI reasoning ("no job change occurred", "same occupation")
    ctx = rows[("income.same_line_of_work", _B3)]["context"].lower()
    for ai_phrase in ("no job change", "same occupation", "occurred"):
        assert ai_phrase not in ctx


def test_regeneration_is_deterministic(tmp_path: Path) -> None:
    _seed(tmp_path)
    r1 = regenerate_income_scenario_worksheet(tmp_path)
    first = (tmp_path / SCENARIO_WORKSHEET_FILE).read_text(encoding="utf-8")
    r2 = regenerate_income_scenario_worksheet(
        tmp_path
    )  # idempotent — a second run keeps the same state
    assert r1["blanked"] == 1 and r2["blanked"] == 1  # the marker guards against re-appending
    assert (tmp_path / SCENARIO_WORKSHEET_FILE).read_text(encoding="utf-8") == first
