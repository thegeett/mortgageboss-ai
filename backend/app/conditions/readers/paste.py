"""Reading a paste (LP-907 section 1, spec §LP-907).

⚠️ `detect_format` ALONE IS WRONG IN BOTH DIRECTIONS ON PASTED TEXT, and each direction was measured
rather than reasoned about. It keys on the first content line, which is the one thing a paste usually
does not have — and when it does match, it can route to a reader the input cannot support.

**A UWM paste usually has no title and no `CONDITIONS` marker.** A processor copies the headings and
the rows out of the portal, not the word above them. Measured on the round-2 fixture's own condition
block:

    read_uwm  on the marker-less paste -> 0 rows, needs_ai, "no CONDITIONS marker"
    read_generic on the same paste     -> 7 rows

Seven, not six: the bucket heading became a ROW, and every row kept its category glued to the front
of its text (`'Invoice                       Provide copy of invoice for credit report.'`). That is
not a cosmetic difference. The import matches conditions on a fingerprint of `verbatim_text`, so not
one of those rows would fingerprint equal to the same condition read from the PDF — and spec §8's
"6 seen again, 0 new, still 11 conditions" becomes 7 new and 18 conditions. It is not an error, a
warning or an empty result: it is six near-duplicates that look right on the review screen, and the
processor's only clue is that the list doubled. Recognising the layout is the difference between a
merge and a duplication, which is why screen S1-07 says the UWM layout was recognised IN THE PASTED
TEXT.

**A pasted Champions certificate must NOT go to its own reader.** `detect_format` does match it — the
title survives a copy — but the reader is built on the row number being VERTICALLY CENTRED beside its
text, and a clipboard copy linearises the two-column table so the number lands on a line of its own.
Measured on our own Champions fixture, copied out of the rendered PDF:

    detect_format  -> champions_certificate
    read_champions -> 0 rows, 97 unassigned lines
    read_generic   -> 4 rows, needs_ai FALSE  (for a 28-condition certificate)

Generic's four is the worse answer of the two, because it reports success: three of them are the same
repeated page-footer line and the fourth starts mid-sentence. So the format is recognised, the
geometry is gone, and the honest result is `PASTED_TEXT` with `needs_ai` — the text goes to LP-908 to
be split, which is exactly what `needs_ai` means.

**Order matters, because generic claims success either way.** `read_generic` returned
`needs_ai=False` for BOTH bad cases above, so it can never be used to decide whether a better reader
should have run. The UWM row-shape test is therefore tried FIRST and generic is only ever the
fallback.
"""

from __future__ import annotations

from app.conditions.readers.detect import detect_format
from app.conditions.readers.generic import read_generic
from app.conditions.readers.lines import lines_from_text
from app.conditions.readers.model import ParsedSheet
from app.conditions.readers.uwm import read_uwm, uwm_block_start
from app.models.condition_round import ConditionSheetFormat

#: What a pasted Champions certificate gets instead of a reader that cannot work on it.
CHAMPIONS_GEOMETRY_LOST = (
    "this looks like a Champions certificate, but a pasted copy loses the column positions its "
    "reader needs; the wording was kept and must be split by AI"
)


def read_pasted_text(raw: str) -> tuple[ConditionSheetFormat, str, ParsedSheet]:
    """Read a processor's paste, returning the format, the reader's name and what it read.

    The name is what `parse_report.reader` records and what the review screen renders ("Read by
    rules (uwm v1)"), so it is the reader's own short name — the same vocabulary `reader_for` uses.
    """
    lines = lines_from_text(raw)
    detected = detect_format(lines)

    # A paste of the WHOLE letter: title and marker both present, so the ordinary reader applies and
    # nothing here needs to be clever. Measured: a clipboard copy of a fixed-pitch letter keeps its
    # columns, and this path reads 6 rows with no warnings and nothing unassigned.
    if detected is ConditionSheetFormat.UWM_APPROVAL_LETTER:
        sheet = read_uwm(lines)
        if sheet.rows:
            return ConditionSheetFormat.UWM_APPROVAL_LETTER, "uwm", sheet

    # A paste of the ROWS ALONE. The block start is established from the row shapes themselves and
    # handed to the reader, rather than by prepending a synthetic `CONDITIONS` line: both produce
    # identical rows (measured), but a fake line shifts every row's `source_line_numbers` by one
    # against the text the processor pasted, and those numbers are what the review screen points at.
    if detected is not ConditionSheetFormat.CHAMPIONS_CERTIFICATE:
        start = uwm_block_start(lines)
        if start is not None:
            sheet = read_uwm(lines, conditions_from=start)
            if sheet.rows:
                return ConditionSheetFormat.UWM_APPROVAL_LETTER, "uwm", sheet

    # Everything else. `read_generic` still runs so that every non-blank line is carried into a row
    # or into `unassigned_lines` (§9.2) — nothing is dropped just because the layout is unknown.
    sheet = read_generic(lines)
    sheet.sheet_format = ConditionSheetFormat.PASTED_TEXT

    if detected is ConditionSheetFormat.CHAMPIONS_CERTIFICATE:
        # ⚠️ OVERRIDING generic's own verdict, which is the point. It returned `needs_ai=False` for a
        # 28-condition certificate it had split into four wrong rows; leaving that alone would
        # present the guess as a rule-read result and never ask LP-908 to do the job properly.
        sheet.needs_ai = True
        sheet.warnings.append(CHAMPIONS_GEOMETRY_LOST)

    return ConditionSheetFormat.PASTED_TEXT, "generic", sheet


__all__ = ["CHAMPIONS_GEOMETRY_LOST", "read_pasted_text"]
