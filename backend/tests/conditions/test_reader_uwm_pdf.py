"""The UWM reader on PDF input (LP-906 follow-up).

⚠️ THE PROPERTY IS EQUIVALENCE, NOT A SECOND SET OF EXPECTATIONS. Every expected value in
`test_reader_uwm.py` was transcribed from the spec's §7.1-7.3 tables. A PDF rendered from the same
text fixture must therefore produce the SAME rows — so these tests compare the two readings against
each other rather than restating the spec, and a drift in either direction fails.

That matters because the alternative is worse: a separately-authored PDF with its own expected
values could diverge from the text fixture and both could look correct.

WHAT THIS CLOSES. `read_uwm` refused PDF input outright, because heading-versus-continuation
measures `Line.indent`, which is None for PDF-built lines. LP-905's done-when — "uploading a PDF
built from `uwm_round1` produces a DRAFT round with 11 draft rows" — is unreachable while that
refusal stands.
"""

from __future__ import annotations

import pymupdf
import pytest
from app.conditions.readers import lines_from_pdf, lines_from_text, read_uwm
from app.conditions.readers.uwm import _shallow_threshold
from tests.conditions.fixture_helpers import (
    UWM_PAGEBREAK,
    UWM_ROUND_1,
    UWM_ROUND_2,
    sheet_text,
)
from tests.conditions.uwm_pdf_fixture import render_uwm_pdf

ALL_FIXTURES = [UWM_ROUND_1, UWM_ROUND_2, UWM_PAGEBREAK]


def _from_text(fixture: str):  # type: ignore[no-untyped-def]
    return read_uwm(lines_from_text(sheet_text(fixture)))


def _from_pdf(fixture: str):  # type: ignore[no-untyped-def]
    return read_uwm(lines_from_pdf(render_uwm_pdf(fixture)))


@pytest.mark.parametrize("fixture", ALL_FIXTURES)
def test_a_pdf_sheet_is_read_at_all(fixture: str) -> None:
    """It used to raise `NotImplementedError` for every PDF, which is what this replaces."""
    sheet = _from_pdf(fixture)

    assert sheet.rows, "a PDF-built sheet produced no rows"


@pytest.mark.parametrize("fixture", ALL_FIXTURES)
def test_the_same_codes_in_the_same_order_from_both_inputs(fixture: str) -> None:
    """The strongest assertion available: two inputs, one answer."""
    assert [row.lender_code for row in _from_pdf(fixture).rows] == [
        row.lender_code for row in _from_text(fixture).rows
    ]


@pytest.mark.parametrize("fixture", ALL_FIXTURES)
def test_the_buckets_survive_the_pdf_path(fixture: str) -> None:
    """⚠️ THE DEFECT THIS EXISTS FOR. When every line answered "not a heading", the row COUNT stayed
    right and every row was filed under a stale bucket — the failure was invisible in any assertion
    that counted rows. So the headings are compared explicitly."""
    from_pdf = [(r.lender_code, r.bucket_heading, r.bucket_kind) for r in _from_pdf(fixture).rows]
    from_text = [(r.lender_code, r.bucket_heading, r.bucket_kind) for r in _from_text(fixture).rows]

    assert from_pdf == from_text


@pytest.mark.parametrize("fixture", ALL_FIXTURES)
def test_the_condition_text_is_identical_from_both_inputs(fixture: str) -> None:
    """A heading glued onto a row would show up here as extra words the lender never wrote."""
    assert [row.verbatim_text for row in _from_pdf(fixture).rows] == [
        row.verbatim_text for row in _from_text(fixture).rows
    ]


@pytest.mark.parametrize("fixture", ALL_FIXTURES)
def test_nothing_is_left_unassigned_on_the_pdf_path(fixture: str) -> None:
    """§9.2 holds on both inputs, or the invariant is only about text."""
    sheet = _from_pdf(fixture)

    assert sheet.unassigned_lines == []
    assert sheet.needs_ai is False


@pytest.mark.parametrize("fixture", ALL_FIXTURES)
def test_the_header_and_its_date_survive_the_pdf_path(fixture: str) -> None:
    """⚠️ THE FIELDS THE EQUIVALENCE TESTS ORIGINALLY DID NOT COMPARE, WHICH IS HOW A DEFECT HID.

    The first version compared codes, order, buckets and verbatim text — and nothing else. So a PDF
    read that produced `date_printed=None` and **16 warnings** against the text path's 0 passed 20
    tests without complaint. `_split_header`'s pair regex required `:\\s{2,}`, and PDF text joins
    tokens with single spaces, so `Date Printed` was never matched — which then left every
    underwriter note dateless, because rule 4 resolves a note's year against it.

    A guard that compares four fields says nothing about the fifth.
    """
    from_pdf, from_text = _from_pdf(fixture), _from_text(fixture)

    assert from_pdf.date_printed == from_text.date_printed
    assert from_pdf.header == from_text.header
    assert from_pdf.warnings == from_text.warnings


@pytest.mark.parametrize("fixture", ALL_FIXTURES)
def test_the_underwriter_notes_resolve_identically_from_both_inputs(fixture: str) -> None:
    """Notes carry a resolved DATE, and the date comes from the header — so this fails the moment
    the header stops being read on either path."""

    def notes(sheet: object) -> list[tuple[str | None, str, str]]:
        return [
            (row.lender_code, note.text, str(note.date))
            for row in sheet.rows  # type: ignore[attr-defined]
            for note in row.underwriter_notes
        ]

    assert notes(_from_pdf(fixture)) == notes(_from_text(fixture))


def test_a_block_of_one_line_rows_still_parses_from_a_pdf() -> None:
    """⚠️ THE DEFECT MY OWN DOCSTRING TALKED ME PAST.

    A conditions block whose rows all fit on one line has no continuation column, so
    `_shallow_threshold` returns None — correctly. But `_row_start` also required a threshold, so
    **no row opened either**: two well-formed rows produced `rows: []` with both lines in
    `unassigned_lines`. §9.2 was technically honoured (nothing was dropped) while the processor got
    an empty round.

    The row's own token gaps answer the question the block-level threshold cannot.
    """
    document = pymupdf.open()
    page = document.new_page(width=900, height=400)
    for x, y, text in (
        (54.0, 60.0, "LOAN APPROVAL CONDITIONS - X - 1"),
        (54.0, 90.0, "CONDITIONS"),
        (54.0, 110.0, "Closing (PTF)"),
        (54.0, 130.0, "0006   Invoice   Provide copy of invoice for credit report."),
        (54.0, 146.0, "0007   Invoice   Provide copy of invoice for final inspection."),
        (54.0, 176.0, "EXPIRATION DATES"),
    ):
        page.insert_text((x, y), text, fontsize=8, fontname="cour")

    sheet = read_uwm(lines_from_pdf(bytes(document.tobytes())))

    assert [row.lender_code for row in sheet.rows] == ["0006", "0007"]
    assert sheet.rows[0].lender_category == "Invoice"
    assert sheet.rows[0].verbatim_text == "Provide copy of invoice for credit report."
    assert sheet.unassigned_lines == []


def test_round1_still_yields_the_spec_eleven_rows_from_a_pdf() -> None:
    """LP-905's done-when, stated directly rather than by equivalence."""
    sheet = _from_pdf(UWM_ROUND_1)

    assert len(sheet.rows) == 11
    assert sheet.duplicates_dropped == 0


def test_the_pagebreak_sheet_still_drops_its_two_duplicates_from_a_pdf() -> None:
    sheet = _from_pdf(UWM_PAGEBREAK)

    assert len(sheet.rows) == 16
    assert sheet.duplicates_dropped == 2


# --------------------------------------------------------------------------- #
# The threshold itself
# --------------------------------------------------------------------------- #


def test_the_threshold_is_derived_not_hardcoded() -> None:
    """⚠️ IT MUST FALL IN THE GAP, WHEREVER THE GAP IS. Measured on this fixture, headings and row
    starts land at {54.0, 58.8} and continuations at [260.4, 303.6] — but those are Courier-8pt
    metrics, not UWM's. The reader finds the largest gap; this asserts it landed between the two
    observed clusters rather than at any particular number."""
    lines = [line for line in lines_from_pdf(render_uwm_pdf(UWM_ROUND_1)) if line.tokens]
    threshold = _shallow_threshold(lines)

    assert threshold is not None
    starts = sorted({line.tokens[0].x0 for line in lines})
    below = [x for x in starts if x < threshold]
    above = [x for x in starts if x >= threshold]

    assert below and above, "the threshold put every line on one side"
    assert max(below) < threshold < min(above)


def test_a_block_with_no_continuations_gets_no_threshold() -> None:
    """⚠️ RETURNING A NUMBER HERE WOULD INVENT A COLUMN BREAK. Every row is a one-liner, so there is
    no text column — and a threshold would make the first slightly-indented line a continuation of
    nothing."""
    text = "\n".join(
        [
            " Closing (PTF)",
            " 0006         Invoice                       Provide copy of invoice.",
            " 0007         Invoice                       Provide copy of the final inspection.",
        ]
    )
    document_lines = [line for line in lines_from_text(text) if not line.is_blank]

    # On text input the threshold is unused (indent answers), so this is asserted on the
    # PDF-shaped question: positions that are all effectively one column.
    assert _shallow_threshold(document_lines) is None


def test_text_input_still_answers_from_indent_not_position() -> None:
    """The threshold must not change the text path at all — `indent` remains the answer there."""
    for fixture in ALL_FIXTURES:
        sheet = _from_text(fixture)
        assert sheet.unassigned_lines == []
        assert sheet.rows
