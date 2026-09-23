"""The line model, normalisation and format detection (LP-906, section 1).

No database and no PDF library round-trip except where one is the subject. These are the foundations
every reader stands on, and each assertion here is a property some later rule silently depends on.
"""

from __future__ import annotations

import pymupdf
import pytest
from app.conditions.readers import (
    NON_BREAKING_SPACE,
    SOFT_HYPHEN,
    Token,
    detect_format,
    lines_from_pdf,
    lines_from_text,
    normalise,
)
from app.models.condition_round import ConditionSheetFormat
from tests.conditions.fixture_helpers import (
    UWM_PAGEBREAK,
    UWM_ROUND_1,
    UWM_ROUND_2,
    sheet_lines,
    sheet_text,
)

# --------------------------------------------------------------------------- #
# Normalisation — three substitutions, and nothing else
# --------------------------------------------------------------------------- #


def test_the_soft_hyphen_becomes_a_real_hyphen() -> None:
    """⚠️ THE ONE THE WHOLE TICKET DEPENDS ON. UWM renders typed hyphens as U+00AD.

    Left alone: the bucket-heading regex stops matching `UW - Prior To Final Approval (PTD)`, the
    condition text carries an invisible character, and two texts a person would call identical
    fingerprint differently — so the same condition looks new on every round.
    """
    assert normalise(f"non{SOFT_HYPHEN}ownership") == "non-ownership"
    assert normalise(f"K{SOFT_HYPHEN}1") == "K-1"
    assert normalise(f"UW {SOFT_HYPHEN} Prior To Final Approval (PTD)") == (
        "UW - Prior To Final Approval (PTD)"
    )


def test_the_non_breaking_space_becomes_a_space() -> None:
    assert normalise(f"Total{NON_BREAKING_SPACE}funds") == "Total funds"


def test_trailing_space_goes_and_leading_space_stays() -> None:
    """⚠️ LEADING SPACES ARE LOAD-BEARING and a normaliser that stripped them would be wrong.

    Indentation is what separates a bucket heading (≤ 3 spaces) from a continuation line (≥ 20). A
    `.strip()` here would collapse the column structure the readers exist to read, and every row
    would run together.
    """
    assert normalise("   0006         Invoice   ") == "   0006         Invoice"
    assert normalise("  Master  ") == "  Master"


def test_nothing_else_is_changed() -> None:
    """Spec §9.1: the lender's words are stored verbatim. A normaliser that tidied anything would
    put a paraphrase into `verbatim_text` with no way back to what was printed."""
    original = "Provide the following for the earnest money deposit in the amount of $2,850.00:"

    assert normalise(original) == original
    assert normalise("***NOTE*** Please submit original") == "***NOTE*** Please submit original"
    assert normalise("(EXAMPLE REAL ESTATE- LAW FIRM)") == "(EXAMPLE REAL ESTATE- LAW FIRM)"


# --------------------------------------------------------------------------- #
# Lines from text
# --------------------------------------------------------------------------- #


def test_token_offsets_are_character_positions() -> None:
    """`x0` is what every positional rule measures against on text input."""
    (line,) = lines_from_text("  0006         Invoice")

    assert line.page == 1
    assert line.y == 0.0
    # 15, measured rather than counted: two leading spaces, four digits, nine spaces. An earlier
    # draft asserted 17 from a head-count and the test caught it — which is the argument for
    # asserting the exact tuple here instead of something looser like "two tokens, in order".
    assert line.tokens == (Token("0006", 2.0), Token("Invoice", 15.0))
    assert line.indent == 2


def test_blank_lines_are_kept_not_filtered() -> None:
    """⚠️ The Champions segmenter reasons about "the line above a row's top". A reader that never
    saw the blanks would compute a different line and mis-slice every row in the segment."""
    lines = lines_from_text("first\n\n\nfourth")

    assert len(lines) == 4
    assert [line.is_blank for line in lines] == [False, True, True, False]
    assert lines[3].y == 3.0


def test_the_line_index_is_the_y_coordinate() -> None:
    lines = lines_from_text("a\nb\nc")

    assert [line.y for line in lines] == [0.0, 1.0, 2.0]


# --------------------------------------------------------------------------- #
# Lines from a PDF — the same structure, different units
# --------------------------------------------------------------------------- #


def _pdf_with(words: list[tuple[float, float, str]]) -> bytes:
    """A one-page PDF with each word placed at (x, y) in points."""
    document = pymupdf.open()
    page = document.new_page()
    for x, y, text in words:
        page.insert_text((x, y), text, fontsize=9)
    return bytes(document.tobytes())


def test_words_at_the_same_height_become_one_line() -> None:
    """⚠️ GROUPED BY VERTICAL CENTRE, NOT BY THE PDF'S OWN BLOCK/LINE INDICES.

    UWM's header is two columns — `Contact Name:` on the left and `Senior UW:` on the right, at the
    same height and in different blocks. Grouping by block would split one visual line in two and the
    header parser would never pair a label with its value.
    """
    content = _pdf_with(
        [(72.0, 100.0, "Contact"), (300.0, 100.0, "Senior"), (72.0, 130.0, "Email")]
    )

    lines = lines_from_pdf(content)

    assert len(lines) == 2
    assert lines[0].text == "Contact Senior"
    assert lines[1].text == "Email"
    assert lines[0].tokens[0].x0 < lines[0].tokens[1].x0


def test_tokens_come_back_in_left_to_right_order() -> None:
    """Insertion order must not decide reading order — a PDF may emit the right column first."""
    content = _pdf_with([(300.0, 100.0, "second"), (72.0, 100.0, "first")])

    (line,) = lines_from_pdf(content)

    assert line.text == "first second"


def test_a_pdf_line_carries_its_page_number() -> None:
    document = pymupdf.open()
    for index in range(2):
        page = document.new_page()
        page.insert_text((72.0, 100.0), f"page{index + 1}", fontsize=9)
    lines = lines_from_pdf(bytes(document.tobytes()))

    assert [(line.page, line.text) for line in lines] == [(1, "page1"), (2, "page2")]


# --------------------------------------------------------------------------- #
# Format detection
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fixture", [UWM_ROUND_1, UWM_ROUND_2, UWM_PAGEBREAK])
def test_every_uwm_fixture_is_detected_as_uwm(fixture: str) -> None:
    assert detect_format(sheet_lines(fixture)) is ConditionSheetFormat.UWM_APPROVAL_LETTER


def test_the_uwm_test_is_a_CONTAINS_and_the_champions_test_is_an_EQUALS() -> None:
    """⚠️ THE TWO TESTS ARE DELIBERATELY DIFFERENT, per the spec.

    UWM's real title line carries the borrower and the loan number after it, so an equality test
    would never match. Champions' is exactly its title — and making THAT a `contains` would classify
    any pasted sentence mentioning a certificate as a Champions sheet.
    """
    uwm = lines_from_text("LOAN APPROVAL CONDITIONS - RIVERA - 1226500417")
    champions = lines_from_text("Conditional Approval Certificate")
    mentions_only = lines_from_text("Please see the Conditional Approval Certificate attached.")

    assert detect_format(uwm) is ConditionSheetFormat.UWM_APPROVAL_LETTER
    assert detect_format(champions) is ConditionSheetFormat.CHAMPIONS_CERTIFICATE
    assert detect_format(mentions_only) is ConditionSheetFormat.GENERIC


def test_leading_blank_lines_do_not_hide_the_title() -> None:
    assert (
        detect_format(lines_from_text("\n\n   LOAN APPROVAL CONDITIONS - X - 1\n"))
        is ConditionSheetFormat.UWM_APPROVAL_LETTER
    )


def test_an_empty_input_is_generic_rather_than_an_error() -> None:
    """GENERIC is not a failure — it routes to the generic reader, which sets `needs_ai` when it
    finds no structure. An exception here would turn an unreadable paste into a 500."""
    assert detect_format(lines_from_text("")) is ConditionSheetFormat.GENERIC
    assert detect_format(()) is ConditionSheetFormat.GENERIC


# --------------------------------------------------------------------------- #
# The fixtures themselves
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("fixture", "expected_shy"),
    [(UWM_ROUND_1, 6), (UWM_ROUND_2, 3), (UWM_PAGEBREAK, 6)],
)
def test_the_placeholder_is_substituted_and_the_count_is_pinned(
    fixture: str, expected_shy: int
) -> None:
    """⚠️ A real U+00AD is INVISIBLE in an editor and in a diff, which is why the committed file
    carries `{SHY}` instead and this asserts the count. A tool that stripped them from the file would
    otherwise change the fixture silently."""
    raw = sheet_text(fixture)

    assert raw.count(SOFT_HYPHEN) == expected_shy
    assert "{SHY}" not in raw


def test_the_fixtures_still_carry_their_column_structure() -> None:
    """The property the mechanical extraction exists to preserve.

    If a later edit reflows these files, the expiry table stops lining up and the nearest-column
    match silently assigns dates to the wrong headers — a wrong answer, not an error.
    """
    lines = sheet_lines(UWM_ROUND_1)
    header = next(line for line in lines if line.text.strip().startswith("Close By"))
    dates = next(
        line for line in lines if line.y > header.y and not line.is_blank and "/" in line.text
    )

    assert len(header.tokens) >= 12, "the expiry header lost its columns"
    assert dates.tokens[0].x0 == pytest.approx(header.tokens[0].x0, abs=2.0), (
        "the first expiry date no longer starts under 'Close By'"
    )
