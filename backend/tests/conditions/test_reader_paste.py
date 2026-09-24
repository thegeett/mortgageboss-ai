"""Reading a paste (LP-907 section 1, spec §LP-907).

⚠️ EVERY EXPECTATION HERE WAS MEASURED BEFORE IT WAS WRITTEN, and two of them contradict what
`detect_format` says on its own. The cases that matter are the ones where a plausible answer is the
wrong one, so each is pinned against the thing it would otherwise silently become.
"""

from __future__ import annotations

import pymupdf
import pytest
from app.conditions.readers import (
    read_champions,
    read_generic,
    read_pasted_text,
    read_uwm,
    uwm_block_start,
)
from app.conditions.readers.lines import lines_from_text
from app.conditions.readers.paste import CHAMPIONS_GEOMETRY_LOST
from app.conditions.readers.uwm import _heading_kind, _is_heading, _row_start, _shallow_threshold
from app.models.condition_round import ConditionSheetFormat
from tests.conditions import champions_fixture, uwm_pdf_fixture
from tests.conditions.fixture_helpers import (
    UWM_PAGEBREAK,
    UWM_ROUND_1,
    UWM_ROUND_2,
    portal_excerpt,
    sheet_text,
)

#: The round-2 codes, in sheet order (spec §7.2).
ROUND_2_CODES = ["1228", "1947", "1582", "0006", "0007", "6378"]


def clipboard(pdf: bytes) -> str:
    """Text copied out of a PDF viewer — the other way a paste is produced."""
    return "\n".join(page.get_text() for page in pymupdf.open(stream=pdf, filetype="pdf"))


def test_an_excerpt_with_no_title_and_no_marker_is_still_read_as_uwm() -> None:
    """⚠️ `detect_format` SAYS GENERIC HERE, AND IT IS RIGHT TO: it keys on the first content line,
    and a portal copy has no title. The row shapes are the only evidence left, and they are enough."""
    fmt, reader, sheet = read_pasted_text(portal_excerpt())

    assert fmt is ConditionSheetFormat.UWM_APPROVAL_LETTER
    assert reader == "uwm"
    assert [row.lender_code for row in sheet.rows] == ROUND_2_CODES
    assert sheet.needs_ai is False
    assert sheet.unassigned_lines == []
    # No "header not found": an excerpt has no letterhead by construction, and a warning that is
    # always present is one a processor learns to skip.
    assert sheet.warnings == []


def test_the_excerpt_reads_identically_to_the_same_sheet_read_whole() -> None:
    """THE PROPERTY THE IMPORT DEPENDS ON. Round 2 pasted and round 2 uploaded must produce the same
    conditions, or "seen again" silently becomes "new"."""
    _fmt, _reader, pasted = read_pasted_text(portal_excerpt())
    whole = read_uwm(lines_from_text(sheet_text(UWM_ROUND_2)))

    assert [r.verbatim_text for r in pasted.rows] == [r.verbatim_text for r in whole.rows]
    assert [r.lender_category for r in pasted.rows] == [r.lender_category for r in whole.rows]
    assert [r.bucket_kind for r in pasted.rows] == [r.bucket_kind for r in whole.rows]
    assert [r.bucket_heading for r in pasted.rows] == [r.bucket_heading for r in whole.rows]


def test_the_fallback_reader_would_have_duplicated_every_condition() -> None:
    """⚠️ THE DEFECT THIS WHOLE MODULE EXISTS TO PREVENT, EXECUTED RATHER THAN DESCRIBED.

    Without recognition the excerpt falls to `read_generic`, which does not fail — it returns SEVEN
    rows and reports success. The bucket heading becomes a row of its own, and every real row keeps
    its category glued to the front of its text. Since conditions are matched on a fingerprint of
    `verbatim_text`, not one of those six would match the condition already on the file: spec §8's
    "6 seen again, 0 new, still 11 conditions" becomes 7 new and 18 conditions.

    No error, no warning, no empty result — just six near-duplicates that look correct on the review
    screen. That is why S1-07's "the UWM layout was recognised in the pasted text" is load-bearing.
    """
    fallback = read_generic(lines_from_text(portal_excerpt()))
    _fmt, _reader, recognised = read_pasted_text(portal_excerpt())

    assert len(fallback.rows) == 7
    assert fallback.needs_ai is False, "it reports success, which is what makes it dangerous"
    assert fallback.rows[0].verbatim_text == "UW - Prior To Final Approval (PTD)"
    assert fallback.rows[4].verbatim_text.startswith("Invoice  ")

    assert len(recognised.rows) == 6
    assert recognised.rows[3].verbatim_text == "Provide copy of invoice for credit report."
    assert [r.verbatim_text for r in recognised.rows] != [
        r.verbatim_text for r in fallback.rows[1:]
    ]


def test_source_line_numbers_index_the_paste_the_processor_sent() -> None:
    """⚠️ WHY THE BLOCK START IS PASSED IN RATHER THAN A `CONDITIONS` LINE PREPENDED.

    Both produce identical rows — measured — so the only thing separating them is this: these numbers
    are what the review screen points at when it shows a row's source, and a synthetic line would
    shift every one of them by one against the text the processor actually pasted. Invisible until
    someone clicks a warning and lands on the wrong line.
    """
    text = portal_excerpt()
    _fmt, _reader, sheet = read_pasted_text(text)

    first = sheet.rows[0]
    assert first.source_line_numbers[0] == 1
    assert text.splitlines()[1].strip().startswith("1228")
    # And its continuations are the two lines that follow, not a renumbering of them.
    assert first.source_line_numbers == [1, 2, 3]


def test_a_whole_letter_pasted_keeps_its_header_and_printed_date() -> None:
    """A clipboard copy of a fixed-pitch letter keeps its columns, so the ordinary reader applies and
    nothing in the paste path needs to be clever."""
    fmt, reader, sheet = read_pasted_text(clipboard(uwm_pdf_fixture.render_uwm_pdf(UWM_ROUND_2)))

    assert fmt is ConditionSheetFormat.UWM_APPROVAL_LETTER
    assert reader == "uwm"
    assert [row.lender_code for row in sheet.rows] == ROUND_2_CODES
    assert sheet.date_printed is not None and sheet.date_printed.isoformat() == "2026-09-10"
    assert sheet.header


def test_a_pasted_champions_certificate_never_reaches_the_champions_reader() -> None:
    """⚠️ RECOGNISED, AND DELIBERATELY NOT READ BY ITS OWN READER.

    The title survives a copy so `detect_format` matches — but the reader is built on the row number
    sitting VERTICALLY CENTRED beside its text, and a clipboard copy linearises the table so the
    number lands on a line of its own. The geometry the algorithm needs is simply gone.

    Both halves are asserted, because the claim is comparative: the specialised reader produces
    nothing, so `PASTED_TEXT` with `needs_ai` is the honest result rather than a missing feature.
    """
    text = clipboard(champions_fixture.build_champions_pdf())

    direct = read_champions(lines_from_text(text))
    assert direct.rows == []
    assert len(direct.unassigned_lines) > 50

    fmt, reader, sheet = read_pasted_text(text)
    assert fmt is ConditionSheetFormat.PASTED_TEXT
    assert reader == "generic"
    # ⚠️ Overriding generic's own verdict. It returned `needs_ai=False` for a 28-condition
    # certificate it had split into four wrong rows; leaving that would present a guess as a
    # rule-read result and never ask LP-908 to do the job properly.
    assert sheet.needs_ai is True
    assert CHAMPIONS_GEOMETRY_LOST in sheet.warnings


def test_prose_is_not_mistaken_for_a_layout() -> None:
    fmt, _reader, sheet = read_pasted_text(
        "Please send whatever you have for this file when you can."
    )

    assert fmt is ConditionSheetFormat.PASTED_TEXT
    assert sheet.needs_ai is True


#: Fixed-pitch tables whose first column happens to be four digits — what a processor pastes
#: constantly. Every one of these was claimed as a UWM sheet before the heading test existed.
NOT_UWM_TABLES = {
    "tax years": (
        " 2026         Tax Return                    Provide signed 2026 federal returns\n"
        " 2025         Tax Return                    Provide signed 2025 federal returns"
    ),
    "amortisation": (
        " 1000         Principal                     Payment one of the schedule\n"
        " 1001         Interest                      Payment two of the schedule\n"
        " 1002         Escrow                        Payment three of the schedule"
    ),
    "invoice numbers": (
        " 4417         Appraisal Inc                 Invoice for the appraisal fee\n"
        " 4418         Title Co                      Invoice for the title search\n"
        " 4419         Title Co                      Invoice for the closing protection letter"
    ),
    "account endings": (
        " 8821         Checking                      Ending balance as of last statement\n"
        " 8822         Savings                       Ending balance as of last statement"
    ),
    # ⚠️ THIS ONE IS REAL UWM CONTENT — genuine codes, genuine categories, genuine wording — pasted
    # WITHOUT its bucket heading. It is refused anyway, and that is the deliberate false negative:
    # nothing in the text distinguishes it from the four tables above.
    "real rows, no heading": (
        " 0006         Invoice                       Provide copy of invoice for credit report.\n"
        " 0007         Invoice                       Provide copy of invoice for final inspection."
    ),
}


@pytest.mark.parametrize("name", sorted(NOT_UWM_TABLES))
def test_a_table_of_four_digit_numbers_is_not_a_uwm_sheet(name: str) -> None:
    """⚠️ THE BUG THIS TEST EXISTS FOR WAS SHIPPED AND CAUGHT IN REVIEW, and it was worse than the
    Champions case beside it.

    Counting row starts alone claimed all five of these as `uwm_approval_letter` with rows, confident
    lender codes, `needs_ai=False` and NOT ONE WARNING. Champions at least fails visibly — wrong
    rows, a warning, `needs_ai` set — so a processor sees that something went wrong. These looked
    entirely plausible, and their fingerprints would then have fed the import matcher: the same
    duplication failure the recognition was built to prevent, through the door opened to fix it.

    A table is refused; nothing is lost, because the text still becomes a `PASTED_TEXT` round and
    LP-908 splits it.
    """
    text = NOT_UWM_TABLES[name]
    fmt, reader, sheet = read_pasted_text(text)

    assert uwm_block_start(lines_from_text(text)) is None
    assert fmt is ConditionSheetFormat.PASTED_TEXT
    assert reader == "generic"
    # ⚠️ AND NO ROW CARRIES A UWM `lender_category`, which is the part that made these dangerous:
    # the generic reader has no category column at all, so nothing downstream can mistake a tax year
    # for a lender code sitting beside a lender's own vocabulary.
    assert all(row.lender_category is None for row in sheet.rows)


def test_the_discriminator_is_the_heading_and_not_the_codes() -> None:
    """⚠️ REJECTING YEAR-SHAPED CODES WOULD BE THE OBVIOUS FIX AND IT IS WRONG. The round-2 block's
    own codes include `1947`. The same rows are refused without their heading and accepted with it,
    so the heading is doing the work — and the codes are untouched by the rule."""
    rows = (
        " 0006         Invoice                       Provide copy of invoice for credit report.\n"
        " 0007         Invoice                       Provide copy of invoice for final inspection."
    )

    assert uwm_block_start(lines_from_text(rows)) is None
    assert uwm_block_start(lines_from_text(f"Closing (PTF)\n{rows}")) == 0

    fmt, _reader, sheet = read_pasted_text(f"Closing (PTF)\n{rows}")
    assert fmt is ConditionSheetFormat.UWM_APPROVAL_LETTER
    assert [r.lender_code for r in sheet.rows] == ["0006", "0007"]
    assert sheet.rows[0].bucket_heading == "Closing (PTF)"
    # A year-shaped code is read as a code, exactly as the real sheet needs.
    assert "1947" in [r.lender_code for r in read_pasted_text(portal_excerpt())[2].rows]


def test_a_heading_shaped_line_is_not_enough() -> None:
    """`_HEADING` matches any short title-cased line, so `Tax Returns` passes the SHAPE test. The
    rule requires a heading whose bucket this reader actually knows — `_HEADINGS`, a
    `(PTD|PTF|PTC|PTA)` parenthetical, or `Trailing`."""
    titled_table = (
        "Tax Returns\n"
        " 2026         Tax Return                    Provide signed 2026 federal returns\n"
        " 2025         Tax Return                    Provide signed 2025 federal returns"
    )

    assert uwm_block_start(lines_from_text(titled_table)) is None
    assert read_pasted_text(titled_table)[0] is ConditionSheetFormat.PASTED_TEXT


@pytest.mark.parametrize("fixture", [UWM_ROUND_1, UWM_ROUND_2, UWM_PAGEBREAK])
def test_every_real_conditions_block_carries_a_known_heading(fixture: str) -> None:
    """THE COST OF THE RULE ON REAL INPUT, MEASURED RATHER THAN ASSUMED — because `read_uwm` does
    warn about unrecognised headings, so unknown ones plainly can occur.

    Across every fixture, every heading in the conditions block maps to a known bucket: 3 of 3 in
    round 1, 2 of 2 in round 2, 5 of 5 in the page-break sheet. The rule refuses nothing real.
    """
    lines = lines_from_text(sheet_text(fixture))
    start = next(i for i, ln in enumerate(lines) if ln.text.strip() == "CONDITIONS") + 1
    end = next(
        (i for i, ln in enumerate(lines) if ln.text.strip() == "EXPIRATION DATES"), len(lines)
    )
    block = [ln for ln in lines[start:end] if not ln.is_blank]
    threshold = _shallow_threshold(block)

    headings = [
        ln.text.strip()
        for ln in block
        if _row_start(ln, threshold) is None and _is_heading(ln, threshold)
    ]

    assert headings, "a conditions block with no heading at all would defeat the paste rule"
    assert all(not _heading_kind(text)[1] for text in headings), headings


def test_an_empty_paste_degrades_rather_than_raising() -> None:
    fmt, _reader, sheet = read_pasted_text("   \n\n  ")

    assert fmt is ConditionSheetFormat.PASTED_TEXT
    assert sheet.rows == []
    assert sheet.needs_ai is True
