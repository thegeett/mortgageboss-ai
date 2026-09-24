"""Reading a lender's condition sheet with rules (LP-906).

PURE FUNCTIONS. No database, no network, no AI, no model call. A reader takes positioned lines and
returns a :class:`ParsedSheet`; everything that touches a row, a task or a session belongs to LP-905
and LP-909. That is what makes this ticket testable against a fixture with no Postgres — which, on
this branch, is the difference between verified and deferred.

THE ORDER OF EVENTS: bytes or text → :func:`lines_from_pdf` / :func:`lines_from_text` →
:func:`detect_format` → the matching reader → `ParsedSheet`. Only the last step knows which lender
it is reading.

WHY RULES FIRST AND AI SECOND (spec §4, ADR in the build plan §7.4): for a layout we know, a rule
gives the lender's words EXACTLY, every time, for nothing. AI is for the formats we do not know, and
even then it only SPLITS — it never interprets. A reader that returned approximately the right text
would defeat the entire point of storing the lender's wording verbatim.
"""

from collections.abc import Callable, Sequence

from app.conditions.readers.champions import read_champions
from app.conditions.readers.detect import detect_format, first_content_line
from app.conditions.readers.generic import read_generic
from app.conditions.readers.lines import (
    NON_BREAKING_SPACE,
    SOFT_HYPHEN,
    Line,
    Token,
    lines_from_pdf,
    lines_from_text,
    normalise,
)
from app.conditions.readers.model import (
    RULE_CONFIDENCE,
    UNCERTAIN_CONFIDENCE,
    ParsedRow,
    ParsedSheet,
    UnderwriterNote,
)
from app.conditions.readers.uwm import read_uwm
from app.models.condition_round import ConditionSheetFormat

#: ⚠️ THE READERS ARE VERSIONED BECAUSE A RE-PARSE MUST BE REPRODUCIBLE (spec §9.6). It is recorded
#: in `parse_report.reader_version`, so a round read months ago can be told apart from one read by a
#: reader that has since changed — without which "re-parse and compare" means nothing. Bump it when a
#: reader's OUTPUT changes for input it already handled, not when a comment moves.
READER_VERSION = "v1"


def reader_for(
    sheet_format: ConditionSheetFormat,
) -> tuple[str, Callable[[Sequence[Line]], ParsedSheet]]:
    """The reader for a detected format, with the name that goes in `parse_report.reader`.

    Lives with the readers rather than in the task: which function reads which layout is reader
    knowledge, and a second mapping maintained beside the first is how the two drift. The name is
    what the review screen renders — "Read by rules (uwm v1) — no AI" — so it is the reader's own
    short name, never a class path.
    """
    match sheet_format:
        case ConditionSheetFormat.UWM_APPROVAL_LETTER:
            return "uwm", read_uwm
        case ConditionSheetFormat.CHAMPIONS_CERTIFICATE:
            return "champions", read_champions
        case _:
            return "generic", read_generic


__all__ = [
    "NON_BREAKING_SPACE",
    "RULE_CONFIDENCE",
    "SOFT_HYPHEN",
    "UNCERTAIN_CONFIDENCE",
    "Line",
    "ParsedRow",
    "ParsedSheet",
    "Token",
    "UnderwriterNote",
    "detect_format",
    "first_content_line",
    "lines_from_pdf",
    "lines_from_text",
    "normalise",
    "read_champions",
    "read_generic",
    "read_uwm",
]
