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
