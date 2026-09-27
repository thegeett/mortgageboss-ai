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

from datetime import date
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from app.conditions.readers.model import ParsedSheet
from app.conditions.readers.paste import read_pasted_text
from app.conditions.readers.uwm import read_uwm
from app.models.condition import Condition
from app.services.condition_import import _new_notes, _resolve_notes
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


def test_the_raw_rule_still_calls_the_redated_note_new() -> None:
    """THE GAP THIS FILE WAS WRITTEN TO MEASURE, now asserted as a fact rather than as an xfail.

    `_new_notes` compares `(date, text)` exactly, so the paste's undated note and the PDF's dated one
    are two notes to it. That is TRUE and it is not a bug in that function: it has no access to the
    file's rounds and therefore cannot know whether the undated one could possibly predate the dated
    one. Pinned here so the raw rule's limit stays visible — and so that anything which starts making
    A1 decisions from `_new_notes` alone fails a test that says why it must not.
    """
    saved_from_paste = _saved(_pasted_round_1(), "6132")
    on_the_pdf = _saved(read_uwm(sheet_lines(_ROUND_1)), "6132")

    assert _new_notes(saved_from_paste, on_the_pdf) == on_the_pdf


def _condition_with(notes: list[dict[str, Any]], *, first_round_id: UUID) -> Condition:
    """A condition holding `notes`, in memory. `_resolve_notes` is pure, so no database is needed."""
    return Condition(
        id=uuid4(),
        company_id=uuid4(),
        loan_file_id=uuid4(),
        first_round_id=first_round_id,
        last_seen_round_id=first_round_id,
        sequence=1,
        lender_code="6132",
        bucket_heading="UW - Prior To Final Approval (PTD)",
        verbatim_text="Provide an additional consecutive month bank statement.",
        text_fingerprint="f" * 64,
        underwriter_notes=notes,
    )


def test_the_same_note_arriving_dated_fills_the_date_and_reopens_nothing() -> None:
    """A1's guard, and the case the strict xfail above used to describe (survey §5.2, R9/R10).

    Round 1 is PASTED, so `6132`'s note saves undated. The PDF for that same round then carries it with
    the sheet's date, which is ON OR BEFORE the round's own `round_date` — so it cannot be a later
    statement by the lender. It is the same note: its date is filled, the fill is reported for the
    seen-again event, and **nothing is reopened**.

    This is the assertion the review's xfail said to move here, and it is stronger than the one it
    replaces: it pins the outcome A1 acts on rather than the raw comparison underneath it.
    """
    round_id = uuid4()
    pasted_notes = [
        {**note, "first_seen_round_id": str(round_id)} for note in _saved(_pasted_round_1(), "6132")
    ]
    condition = _condition_with(pasted_notes, first_round_id=round_id)
    row = {"underwriter_notes": _saved(read_uwm(sheet_lines(_ROUND_1)), "6132")}

    outcome = _resolve_notes(
        condition,
        row,
        round_=SimpleNamespace(id=round_id),  # type: ignore[arg-type]
        round_dates={round_id: date(2026, 8, 29)},
    )

    assert outcome.reopened_by is None, "the same note, now dated, must not reopen the condition"
    assert outcome.added == 0
    assert outcome.dated == ["not in upload"]
    assert outcome.notes[0]["date"] == "2026-08-28", "the saved note gained the sheet's date"


def test_a_note_dated_after_the_bound_is_a_re_issue_and_reopens() -> None:
    """The other half, without which the guard above would simply never fire A1 (R9).

    The same normalised text arriving with a date AFTER the round it was first seen on cannot be that
    same note — the lender wrote it later. That is a re-issue, and it is exactly the case A1 exists for:
    round 1 pasted, then a later sheet carrying "9/10 Not in Upload".
    """
    round_id = uuid4()
    pasted_notes = [
        {**note, "first_seen_round_id": str(round_id)} for note in _saved(_pasted_round_1(), "6132")
    ]
    condition = _condition_with(pasted_notes, first_round_id=round_id)
    row = {"underwriter_notes": [{"date": "2026-09-10", "text": "Not in Upload"}]}

    outcome = _resolve_notes(
        condition,
        row,
        round_=SimpleNamespace(id=uuid4()),  # type: ignore[arg-type]
        round_dates={round_id: date(2026, 8, 29)},
    )

    assert outcome.reopened_by is not None
    assert outcome.reopened_by["date"] == "2026-09-10"
    assert outcome.added == 1
    assert outcome.dated == []


def test_inner_whitespace_does_not_make_it_a_different_note() -> None:
    """R8: the reader keeps whatever spacing arrives, and a browser copy need not match the PDF.

    Raw equality fires a false *Came back* here, which reopens a condition on the lender's behalf —
    the worst direction for this to be wrong in.
    """
    round_id = uuid4()
    condition = _condition_with(
        [{"date": None, "text": "Not in  Upload", "first_seen_round_id": str(round_id)}],
        first_round_id=round_id,
    )
    row = {"underwriter_notes": [{"date": "2026-08-28", "text": "Not in Upload"}]}

    outcome = _resolve_notes(
        condition,
        row,
        round_=SimpleNamespace(id=round_id),  # type: ignore[arg-type]
        round_dates={round_id: date(2026, 8, 29)},
    )

    assert outcome.reopened_by is None, "a double space must not read as a new note"
    assert outcome.dated == ["not in upload"]
