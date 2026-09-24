"""The UWM fixtures, rendered as real PDFs (LP-906 follow-up).

⚠️ WHY THIS EXISTS. §7.1-7.3 are TEXT, and `read_uwm` refused PDF input entirely because the
heading-versus-continuation test measures `Line.indent`, which is None for PDF-built lines. That was
the honest state while no UWM PDF existed to calibrate against. LP-905's own done-when is
"uploading a PDF built from `uwm_round1` produces a DRAFT round with 11 draft rows", so the refusal
has to end here or that acceptance is unreachable.

THE SAME BYTES, TWO WAYS IN. Rendering the existing text fixture rather than authoring a new sheet
keeps one source of truth: every expected value in `test_reader_uwm.py` was transcribed from the
spec, and a PDF built from the same text must produce the same rows. A separately-authored PDF could
drift from the text fixture and nothing would notice.

MONOSPACED, DELIBERATELY. A fixed-pitch font maps a character column linearly onto an x position —
measured on round 1: `x0 = 54.0 + indent * 4.8` exactly — which is how the real letter's fixed-pitch
layout behaves. That linearity is what makes the reader's derived threshold checkable: headings and
row starts land at {54.0, 58.8} and continuations at [260.4, 303.6], two clusters ~200 points apart.

⚠️ THE READER MUST NOT LEARN THOSE NUMBERS. They are this fixture's font metrics, not UWM's. The
reader derives its threshold from the document it is given; this module exists to give it a document
whose geometry is known, so a wrong derivation is visible.
"""

from __future__ import annotations

import pymupdf
from tests.conditions.fixture_helpers import sheet_text

#: Courier at 8pt: an advance of 4.8 points per character. The page is deliberately wide so no line
#: wraps — a wrap would split a row's text and the fixture would stop being the same sheet.
FONT = "cour"
FONT_SIZE = 8.0
LEFT_MARGIN = 54.0
TOP_MARGIN = 60.0
LINE_PITCH = 12.0
PAGE_WIDTH = 1224.0
PAGE_HEIGHT = 1584.0
BODY_BOTTOM = 1520.0


def render_uwm_pdf(fixture: str) -> bytes:
    """Render one of the §7 text fixtures as a PDF with its column structure preserved.

    Blank lines advance the cursor without emitting a text run, so vertical spacing survives while no
    empty word boxes are produced — `lines_from_pdf` would otherwise have nothing to group and the
    blank would simply vanish, which is fine here because the UWM reader skips blanks anyway.
    """
    document = pymupdf.open()
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    y = TOP_MARGIN

    for raw in sheet_text(fixture).splitlines():
        if raw.strip():
            page.insert_text((LEFT_MARGIN, y), raw, fontsize=FONT_SIZE, fontname=FONT)
        y += LINE_PITCH
        if y > BODY_BOTTOM:
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            y = TOP_MARGIN

    return bytes(document.tobytes())
