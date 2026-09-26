"""When is an underwriter note NEW? Stage 1 decides it, and Stage 2's "came back" (A1) will act on it.

LP-912 wires A1 to Stage 1's own decision: a seen-again condition that gains a note it did not have
sets the lender status to *Came back* and moves our status back to *To do*. The Stage 2 survey (§5.2)
first said that decision was reliable, so the spec's STOP AND ASK did not apply. Review measured
otherwise, on the fixtures, and this file holds both halves:

- what the decision gets right (same date and text → not new; same text, new date → new), and
- the case it gets wrong: a note first saved from a PASTE has no date, because a paste has no
  `date_printed` to resolve the year against. When a later PDF carries the same note, dated, the key
  `(date, text)` differs and the note is judged new, so A1 would mark a condition *Came back* on a
  note the lender wrote weeks earlier.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.conditions.readers.model import ParsedSheet
from app.conditions.readers.paste import read_pasted_text
from app.conditions.readers.uwm import read_uwm
from app.services.condition_import import _new_notes
from tests.conditions.fixture_helpers import sheet_lines, sheet_text

_ROUND_1 = "uwm_round1_2026-08-28.txt"


def _saved(sheet: ParsedSheet, code: str) -> list[dict[str, Any]]:
    """A row's notes in the shape `condition_import` saves them, for the fields `_note_key` reads."""
    row = next(r for r in sheet.rows if r.lender_code == code)
    return [
        {"date": note.date.isoformat() if note.date else None, "text": note.text}
        for note in row.underwriter_notes
    ]


def _pasted_round_1() -> ParsedSheet:
    """Round 1's conditions block as a processor would paste it: no header, so no date printed."""
    lines = sheet_text(_ROUND_1).splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "CONDITIONS") + 1
    end = next(i for i, line in enumerate(lines) if "EXPIRATION DATES" in line)
    _fmt, _reader, sheet = read_pasted_text("\n".join(lines[start:end]))
    return sheet


def test_the_paste_carries_the_note_undated_and_the_pdf_dated() -> None:
    """The precondition for the defect below, measured rather than assumed."""
    pasted, pdf = _pasted_round_1(), read_uwm(sheet_lines(_ROUND_1))
    assert pasted.date_printed is None
    assert _saved(pasted, "6132") == [{"date": None, "text": "Not in Upload"}]
    assert _saved(pdf, "6132") == [{"date": "2026-08-28", "text": "Not in Upload"}]


def test_the_same_dated_note_again_is_not_new() -> None:
    pdf = _saved(read_uwm(sheet_lines(_ROUND_1)), "6132")
    assert _new_notes(pdf, pdf) == []


def test_the_same_text_under_a_new_date_is_new() -> None:
    old = [{"date": "2026-08-28", "text": "Not in Upload"}]
    new = [{"date": "2026-09-10", "text": "Not in Upload"}]
    assert _new_notes(old, new) == new


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Stage 2 survey §5.2 (review): an undated saved note is judged different from the same "
        "note dated, so A1 would set Came back on an old note. LP-912 must decide this (the spec's "
        "STOP AND ASK) and either fix `_new_notes` or move this assertion onto its came-back rule."
    ),
)
def test_a_note_first_saved_from_a_paste_is_not_new_when_the_pdf_carries_it() -> None:
    saved_from_paste = _saved(_pasted_round_1(), "6132")
    on_the_pdf = _saved(read_uwm(sheet_lines(_ROUND_1)), "6132")
    assert _new_notes(saved_from_paste, on_the_pdf) == []
