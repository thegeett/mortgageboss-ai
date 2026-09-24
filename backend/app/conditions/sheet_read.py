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
sheet. It is written into `parse_report.failure_detail`, which the readonly layer scrubs for
identifier SHAPES only — a digit run is redacted, a borrower's name is not.
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


def sheet_from_bytes(content: bytes) -> tuple[str, ParsedSheet]:
    """Read PDF bytes into a `ParsedSheet`, with the reader's name for `parse_report.reader`.

    Raises `SheetUnreadable` rather than letting a library exception escape: an unreadable upload
    must reach the processor as a refusal naming the reason, not as a 500.
    """
    try:
        lines = lines_from_pdf(content)
    except (pymupdf.EmptyFileError, pymupdf.FileDataError) as exc:
        # Measured: empty bytes raise EmptyFileError, garbage and truncated files FileDataError.
        raise SheetUnreadable(
            "This PDF could not be opened. It may be damaged — ask the lender to send it again."
        ) from exc

    name, read = reader_for(detect_format(lines))
    return name, read(lines)


__all__ = [
    "ConditionParseError",
    "SheetBytesUnavailable",
    "SheetUnreadable",
    "sheet_from_bytes",
]
