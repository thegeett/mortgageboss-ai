"""The Champions reader against the §7.4 synthetic PDF (LP-906 section 3).

⚠️ WHAT THESE ASSERTIONS ARE WORTH, STATED HONESTLY. §7.4 supplies full prose for only rows 71 and
268 (they appear in the §6 centre-rule example); the other 26 texts are authored in
`champions_fixture.py`. So an assertion comparing a row's text to the fixture's text compares
authored prose with itself and proves only that the centre rule reassembled SOMETHING.

The assertions that carry weight are STRUCTURAL, and they are the ones §7.4 actually specifies:
28 rows in the table's order, the right section per row, 206 reassembled across the page break, no
page furniture inside a row, no unassigned lines, 171 not read as a note, both expiry dates. Those
are checked against `all_rows()` — the fixture's own mapping of §7.4's table — so a reviewer can
diff that table against the fixture without reading a line of reader code.

Real PDF input throughout: Champions rows carry no start marker, only geometry, so a text fixture
would exercise a different path from the one that runs in production.
"""

from __future__ import annotations

from datetime import date

import pytest
from app.conditions.readers import lines_from_pdf, read_champions
from app.models.condition import BucketKind
from app.models.condition_round import ConditionSheetFormat
from tests.conditions.champions_fixture import (
    EXPECTED_EXPIRY,
    EXPECTED_TEAM,
    FOOTER_RIGHT,
    TITLE,
    all_rows,
    build_champions_pdf,
)


@pytest.fixture(scope="module")
def sheet():  # type: ignore[no-untyped-def]
    """Parsed once — building the PDF and reading it is the expensive part, and it is pure."""
    return read_champions(lines_from_pdf(build_champions_pdf()))


def test_the_format_is_champions(sheet) -> None:  # type: ignore[no-untyped-def]
    assert sheet.sheet_format is ConditionSheetFormat.CHAMPIONS_CERTIFICATE


def test_twenty_eight_rows_in_the_spec_table_order(sheet) -> None:  # type: ignore[no-untyped-def]
    """§7.4: 28 rows in that order. The ORDER is the assertion — it is what proves the centre rule
    walked the segments correctly, since a row misplaced by one lands in the wrong section."""
    assert [row.lender_code for row in sheet.rows] == [n for _, n, _ in all_rows()]
    assert len(sheet.rows) == 28


def test_every_row_lands_in_its_own_section(sheet) -> None:  # type: ignore[no-untyped-def]
    """The 13 sections of §7.4's table, row by row."""
    expected = all_rows()
    for row, (heading, number, _) in zip(sheet.rows, expected, strict=True):
        assert row.lender_code == number
        assert row.bucket_heading == heading, number
        # Rule 4: the category is the text after the dash, kept as the lender printed it.
        assert row.lender_category == heading.split(" - ", 1)[1], number


def test_the_bucket_kind_comes_from_the_stage(sheet) -> None:  # type: ignore[no-untyped-def]
    """Rule 4: `Prior to Docs` → PRIOR_TO_DOCS, `Prior to Funding` → PRIOR_TO_FUNDING."""
    for row in sheet.rows:
        stage = row.bucket_heading.split(" - ")[0]
        expected = (
            BucketKind.PRIOR_TO_DOCS if stage == "Prior to Docs" else BucketKind.PRIOR_TO_FUNDING
        )
        assert row.bucket_kind is expected, row.lender_code


def test_the_single_line_sections_survive(sheet) -> None:  # type: ignore[no-untyped-def]
    """⚠️ REGRESSION GUARD — THESE TWO ROWS WERE SILENTLY DELETED.

    133 and 286 are each the only row in their section AND wrap to one line, so the number's centre
    falls on that line's own baseline and the two MERGE into a single line. The body-text column was
    measured per segment, so in a one-line segment the median first-token position WAS the merged
    line — the number failed its own "left of the body text" test, the segment fell through to
    `unassigned_lines`, and the sheet still reported no warnings. 26 rows where 28 were required.
    """
    codes = [row.lender_code for row in sheet.rows]

    assert "133" in codes
    assert "286" in codes
    assert sheet.rows[codes.index("133")].bucket_heading == "Prior to Docs - Compliance"
    assert sheet.rows[codes.index("286")].bucket_heading == "Prior to Docs - Identification"


def test_row_206_is_reassembled_across_the_page_break(sheet) -> None:  # type: ignore[no-untyped-def]
    """⚠️ THE CASE THE WHOLE CENTRE RULE EXISTS FOR (§7.4 requires it).

    206's text begins on one page and ends on the next. The tail arrives as a run of lines at the top
    of a segment that does NOT open with a heading — which is rule 5's signal that those lines belong
    to the previous page's last row rather than starting a new one.
    """
    row = next(r for r in sheet.rows if r.lender_code == "206")

    assert row.crossed_page is True
    assert row.verbatim_text.startswith(
        "Provide an updated homeowner's insurance declarations page"
    )
    assert row.verbatim_text.endswith("premium paid in full at or before settlement.")
    # The join must not lose or duplicate the words at the seam.
    assert "closing date. The deductible may not exceed" in row.verbatim_text
    assert row.verbatim_text.count("The deductible may not") == 1

    assert [r.crossed_page for r in sheet.rows].count(True) == 1


def test_no_page_furniture_reaches_a_row(sheet) -> None:  # type: ignore[no-untyped-def]
    """Rule 1. The title, loan line and both footers repeat on all three pages, so a reader that
    failed to drop them would put them inside the row nearest each page boundary."""
    for row in sheet.rows:
        assert TITLE not in row.verbatim_text, row.lender_code
        assert "Loan #" not in row.verbatim_text, row.lender_code
        assert "NMLS #" not in row.verbatim_text, row.lender_code
        assert FOOTER_RIGHT not in row.verbatim_text, row.lender_code


def test_nothing_is_left_unassigned(sheet) -> None:  # type: ignore[no-untyped-def]
    """§9.2, and §7.4 states it directly: no unassigned lines. Every non-blank body line became part
    of a row or was dropped as known furniture."""
    assert sheet.unassigned_lines == []
    assert sheet.warnings == []
    assert sheet.needs_ai is False
    assert all(row.confidence == 1.0 for row in sheet.rows)


def test_171_is_not_read_as_an_underwriter_note(sheet) -> None:  # type: ignore[no-untyped-def]
    """⚠️ §7.4 calls this out explicitly. Row 171 starts `**AM to pull SSN Verification.` — two
    asterisks, the exact marker the note regex looks for. It survives only because the regex requires
    a DATE after them, which is the distinction pinned directly on the regex in the UWM tests."""
    row = next(r for r in sheet.rows if r.lender_code == "171")

    assert row.underwriter_notes == []
    assert row.verbatim_text.startswith("**AM to pull SSN Verification.")


def test_the_expiry_table(sheet) -> None:  # type: ignore[no-untyped-def]
    """Rule 3, including `title_commitment` — whose label WRAPS across two lines in the fixture
    (`Title Commitment Exp` / `Date:`), which is the case rule 2 names and which a reader that did
    not join them would lose entirely."""
    for key, iso in EXPECTED_EXPIRY.items():
        assert sheet.expiry_dates[key] == date.fromisoformat(iso), key

    assert sheet.expiry_dates["approval"] == date(2027, 1, 7)
    assert sheet.expiry_dates["credit"] == date(2027, 1, 7)


def test_the_three_contacts(sheet) -> None:  # type: ignore[no-untyped-def]
    """Rule 2. ⚠️ Each value must stop where the next label begins: PDF text joins columns with a
    SINGLE space, so a pair rule ending a value at two spaces never fires and `Name` came back as
    `'Omar Example Phone: (555) 010-0144'` — the next column swallowed whole."""
    team = {entry["role"]: entry for entry in sheet.header["lender_team"]}

    assert [(t["role"], t["name"]) for t in sheet.header["lender_team"]] == list(EXPECTED_TEAM)
    assert team["Account Executive"]["phone"] == "(555) 010-0144"
    assert team["Account Executive"]["email"] == "omar.example@example-funding.test"
    assert team["Underwriter"]["phone"] == "(555) 010-0155"
    assert team["Account Manager"]["email"] == "ada.manager@example-funding.test"


@pytest.mark.parametrize(
    ("number", "fragment"),
    [
        ("55", "Subject to Condo Approval."),
        ("261", "flood zone determination"),
        ("133", "Affiliated Business Arrangement"),
        ("286", "government-issued photo identification"),
    ],
)
def test_the_one_line_rows_are_exactly_one_line(sheet, number: str, fragment: str) -> None:  # type: ignore[no-untyped-def]
    """§7.4 marks these as one-liners. A row that absorbed its neighbour would still contain the
    fragment, so the length is asserted too."""
    row = next(r for r in sheet.rows if r.lender_code == number)

    assert fragment in row.verbatim_text
    assert len(row.verbatim_text) < 120, row.verbatim_text


def test_the_structural_shapes_the_spec_names(sheet) -> None:  # type: ignore[no-untyped-def]
    """The per-row properties §7.4 specifies, which are checkable even though the prose is authored."""
    rows = {r.lender_code: r.verbatim_text for r in sheet.rows}

    # 71: two numbered parts joined by -AND-
    assert "-AND-" in rows["71"]
    assert "(1)" in rows["71"] and "(2)" in rows["71"]
    # 268: the assets figure
    assert "$115,367.50" in rows["268"]
    # 34: the counselling fee
    assert "$75" in rows["34"]
    # 245: the long one — ~9 wrapped lines of ~100 characters
    assert len(rows["245"]) > 700
    # 38 and 284: numbered lists
    assert "1 " in rows["38"] and "2." in rows["38"]
    assert all(f"{n}." in rows["284"] for n in (1, 2, 3, 4, 5))
    # 66: the expiry string
    assert "Credit Report: 01/07/2027" in rows["66"]
