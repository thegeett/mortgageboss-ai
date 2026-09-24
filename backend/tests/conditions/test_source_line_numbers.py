"""`source_line_numbers` means indices into the input — for every reader (LP-909 review).

⚠️ THE PROPERTY WAS DEMONSTRATED IN THE READER THAT GOT IT RIGHT AND ASSUMED IN THE ONE THAT DID NOT.
Before this file, three assertions of the field existed suite-wide and all three were on the paste
path. `test_reader_champions.py` pins `crossed_page` and never the numbers — so Champions stored
`int(line.y)` (a coordinate in POINTS) for a row's lines and `range(len(leftover))` (ordinals from
zero) for a page-crossing tail, putting TWO different scales in one row's list, and nothing failed.

It was latent because the only consumer is the public schema field. It stops being latent in LP-909:
the review screen renders a row's source from exactly this, and the recorded plan for the AI-split
screen draws each row's span off it. A Champions round would have mis-located every one.

So the assertion here is the field's own docstring, executed against all three readers rather than
one: "which input lines produced this row" — meaning valid indices into the sequence the reader was
handed, and lines that actually contain the row's words.
"""

from __future__ import annotations

import pytest
from app.conditions.readers import lines_from_pdf, lines_from_text, read_champions, read_uwm
from app.conditions.readers.generic import read_generic
from app.conditions.readers.lines import Line
from app.conditions.readers.model import ParsedSheet
from tests.conditions.champions_fixture import build_champions_pdf
from tests.conditions.fixture_helpers import (
    UWM_PAGEBREAK,
    UWM_ROUND_1,
    UWM_ROUND_2,
    sheet_lines,
)


def _assert_indices(sheet: ParsedSheet, lines: tuple[Line, ...], *, reader: str) -> None:
    """Every number is a usable index into the input this reader was given."""
    for row in sheet.rows:
        assert row.source_line_numbers, f"{reader}: {row.lender_code} carries no source lines"
        for number in row.source_line_numbers:
            assert isinstance(number, int), f"{reader}: {number!r} is not an index"
            assert 0 <= number < len(lines), (
                f"{reader}: row {row.lender_code} points at line {number}, "
                f"outside the {len(lines)} lines the reader was given"
            )


@pytest.mark.parametrize("fixture", [UWM_ROUND_1, UWM_ROUND_2, UWM_PAGEBREAK])
def test_uwm_source_lines_are_indices(fixture: str) -> None:
    lines = sheet_lines(fixture)
    _assert_indices(read_uwm(lines), lines, reader="uwm")


def test_generic_source_lines_are_indices() -> None:
    lines = lines_from_text("1. Provide the settlement statement.\n2. Provide the signed note.")
    _assert_indices(read_generic(lines), lines, reader="generic")


def test_champions_source_lines_are_indices() -> None:
    """⚠️ THE ONE THAT WAS WRONG. `int(line.y)` is a y-coordinate: on the §7.4 certificate those run
    into the hundreds while the sheet has far fewer lines, so most rows pointed outside the input
    entirely — and the value is not even unique, because y repeats on every page."""
    lines = lines_from_pdf(build_champions_pdf())
    _assert_indices(read_champions(lines), lines, reader="champions")


def test_champions_source_lines_point_at_the_rows_own_words() -> None:
    """An index inside the range is not enough: it has to be the RIGHT line.

    Checked against the text rather than the position, because that is the property a review screen
    actually depends on — click a row's source and land on the words it was built from.
    """
    lines = lines_from_pdf(build_champions_pdf())
    sheet = read_champions(lines)

    row = next(r for r in sheet.rows if r.lender_code == "55")
    cited = " ".join(lines[n].text for n in row.source_line_numbers)

    assert "Subject to Condo Approval." in cited


def test_a_page_crossing_row_cites_both_pages() -> None:
    """⚠️ THE MIXED-SCALE BUG, PINNED. The tail used `range(len(leftover))` — ordinals from zero —
    appended onto a list of y-values, so one row held two scales and the tail pointed at the first
    lines of the document. Correct indices put the tail AFTER the head and on a later page."""
    lines = lines_from_pdf(build_champions_pdf())
    sheet = read_champions(lines)

    row = next(r for r in sheet.rows if r.lender_code == "206")
    assert row.crossed_page is True

    numbers = row.source_line_numbers
    assert numbers == sorted(numbers), "a row's lines are cited in reading order"
    assert len({lines[n].page for n in numbers}) == 2, "206 spans exactly two pages"

    cited = " ".join(lines[n].text for n in numbers)
    assert "premium paid in full at or before settlement." in cited
