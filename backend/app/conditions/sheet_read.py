"""Turning condition-sheet bytes into a `ParsedSheet` (LP-907; moved out of the Celery task).

⚠️ IT LIVES HERE BECAUSE TWO CALLERS NOW NEED IT AND THEY CANNOT SHARE IT WHERE IT WAS. The parse
task owned both the typed failures and the read; LP-907's enrich merge is a SERVICE, and
`tasks → services` is the one direction this repo's imports run — `forward_attachment_as_sheet`'s
docstring turns down a design for exactly that reason. A service importing from `app.tasks` would
invert it, so the shared half moves down to `app/conditions/`, which is pure: no session, no Celery,
no storage.

⚠️ THE HALVES ARE SPLIT BY WHO HAS THE BYTES. The task reads a round whose PDF is in storage, so it
fetches first; `attach-pdf` already holds the upload in memory and has nothing to fetch. Keeping one
function that did both would mean the endpoint writing bytes to storage purely to read them back, or
passing `None` for a path it does not have. `sheet_from_bytes` is the half they share.

NO NPI IN A FAILURE DETAIL (spec §9.5, §9.8): every `detail` below is COMPOSED, never quoted from the
sheet.

⚠️ AND THE REASON IS NOT THE ONE THIS DOCSTRING USED TO GIVE. It said `parse_report.failure_detail`
"reaches the readonly layer, which scrubs identifier SHAPES only". It does not reach it at all:
`parse_report` is in the EXCLUDED set (`tests/test_readonly_query.py`) and the migration drops it
whole — the view projects `reader`, `reader_version`, `ai_used`, `duplicates_dropped`,
`warning_count` and `unassigned_count`, all derived. The scrub-shapes argument belongs to columns
that ARE exposed, and this is not one. `models/condition_round.py` has always said so correctly;
the wrong version was copied from here into three other files.

The reason that does hold is stronger. `parse_report` is excluded precisely BECAUSE
`unassigned_lines` inside it carries verbatim sheet text, so quoting a borrower's name into
`failure_detail` puts NPI at rest in a field nobody can inspect to find it — and the derived scalars
are all an analyst ever gets. Same shape as the loan-information warning fixed earlier in this
stage: nothing escaped, and it was still wrong to store.
"""

from __future__ import annotations

import pymupdf

from app.conditions.readers import detect_format, lines_from_pdf, reader_for
from app.conditions.readers.model import ParsedSheet


class ConditionParseError(Exception):
    """A parse that cannot proceed, carrying a TYPED reason and a sentence for the processor.

    ⚠️ NEVER A BARE `except Exception` (spec §9.8). "The file is no longer in storage", "this PDF
    cannot be opened" and "the sheet is empty" lead a processor to three different next actions, and
    collapsing them into one message makes a failed round a dead end. `failure_kind` is what code
    and dashboards read; `detail` is what a person reads.
    """

    failure_kind = "parse_failed"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class SheetBytesUnavailable(ConditionParseError):
    """The stored PDF could not be fetched — the round exists but its bytes do not."""

    failure_kind = "bytes_unavailable"


class SheetUnreadable(ConditionParseError):
    """The bytes are not a PDF this library can open."""

    failure_kind = "unreadable"


def sheet_from_bytes(content: bytes) -> tuple[str, ParsedSheet, str]:
    """Read PDF bytes into a `ParsedSheet`: the reader's name, the sheet, and the SOURCE TEXT.

    Raises `SheetUnreadable` rather than letting a library exception escape: an unreadable upload
    must reach the processor as a refusal naming the reason, not as a 500.

    ⚠️ THE THIRD VALUE EXISTS SO A PDF CAN BE AI-SPLIT AT ALL (LP-908 review). `split_round` reads
    `round_.raw_text`, which only the paste door ever wrote — so chaining the split for an uploaded
    or forwarded sheet hit its `if not text:` branch and settled the round `PARSE_FAILED` with
    "This round has no text to read. Paste the conditions again.", telling a processor to paste a
    letter they had just uploaded. Persisting the text is what makes the upload and forward doors
    splittable.

    ⚠️ IT IS THE LINES THE READER ITSELF SAW, joined, rather than a second extraction. `Line.text`
    for PDF input is the word-box tokens joined by single spaces (`lines.py`), and those boxes come
    through `page_ocr.words_for`, which decides per PAGE between a text layer and OCR. So a scanned
    sheet yields text here exactly as it does to the readers. A separate `page.get_text()` call would
    be a second answer to "what does this page say" — and §9.3's substring check, which is what makes
    "AI only splits" enforceable rather than requested, must run against the same string the model
    was given.

    ⚠️ NPI (ADR-405). The returned text is the lender's page verbatim, so it belongs only in
    `raw_text` — already classified NPI and dropped whole from the readonly views — and never in a
    log line, an event detail or a failure message.
    """
    try:
        lines = lines_from_pdf(content)
    except (pymupdf.EmptyFileError, pymupdf.FileDataError) as exc:
        # Measured: empty bytes raise EmptyFileError, garbage and truncated files FileDataError.
        raise SheetUnreadable(
            "This PDF could not be opened. It may be damaged — ask the lender to send it again."
        ) from exc

    name, read = reader_for(detect_format(lines))
    return name, read(lines), "\n".join(line.text for line in lines)


__all__ = [
    "ConditionParseError",
    "SheetBytesUnavailable",
    "SheetUnreadable",
    "sheet_from_bytes",
]
