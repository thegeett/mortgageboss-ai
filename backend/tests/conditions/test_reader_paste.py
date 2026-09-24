"""Reading a paste (LP-907 section 1, spec §LP-907).

⚠️ EVERY EXPECTATION HERE WAS MEASURED BEFORE IT WAS WRITTEN, and two of them contradict what
`detect_format` says on its own. The cases that matter are the ones where a plausible answer is the
wrong one, so each is pinned against the thing it would otherwise silently become.
"""

from __future__ import annotations

import pymupdf
from app.conditions.readers import (
    read_champions,
    read_generic,
    read_pasted_text,
    read_uwm,
    uwm_block_start,
)
from app.conditions.readers.lines import lines_from_text
from app.conditions.readers.paste import CHAMPIONS_GEOMETRY_LOST
from app.models.condition_round import ConditionSheetFormat
from tests.conditions import champions_fixture, uwm_pdf_fixture
from tests.conditions.fixture_helpers import UWM_ROUND_2, portal_excerpt, sheet_text

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


def test_one_coded_line_is_not_a_list() -> None:
    """⚠️ TWO ROW STARTS, NOT ONE. A single four-digit number followed by two columns happens in
    ordinary prose — a year, an amount, a figure inside somebody else's sentence, all of which this
    reader has already been caught by once. Two on separate lines is a list."""
    text = (
        "Appraised value came in at 2026 figures.\n"
        " 0006         Invoice                       Provide copy of invoice for credit report."
    )
    fmt, _reader, _sheet = read_pasted_text(text)

    assert fmt is ConditionSheetFormat.PASTED_TEXT
    assert uwm_block_start(lines_from_text(text)) is None


def test_two_coded_lines_are_a_list() -> None:
    """The other side of the same threshold, so it is pinned from both directions."""
    text = (
        " 0006         Invoice                       Provide copy of invoice for credit report.\n"
        " 0007         Invoice                       Provide copy of invoice for final inspection."
    )
    fmt, _reader, sheet = read_pasted_text(text)

    assert fmt is ConditionSheetFormat.UWM_APPROVAL_LETTER
    assert uwm_block_start(lines_from_text(text)) == 0
    assert [r.lender_code for r in sheet.rows] == ["0006", "0007"]
    assert sheet.rows[0].lender_category == "Invoice"


def test_an_empty_paste_degrades_rather_than_raising() -> None:
    fmt, _reader, sheet = read_pasted_text("   \n\n  ")

    assert fmt is ConditionSheetFormat.PASTED_TEXT
    assert sheet.rows == []
    assert sheet.needs_ai is True
