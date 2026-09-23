"""Which layout is this? (LP-906)

One function, keyed on the first non-blank line, because that is the only part of a condition sheet
whose wording the lender never varies — the title is boilerplate, while everything below it changes
per loan.

⚠️ THE TWO TESTS ARE DELIBERATELY DIFFERENT, and the spec is precise about it: UWM's title CONTAINS
`LOAN APPROVAL CONDITIONS` (the real line is `LOAN APPROVAL CONDITIONS - RIVERA - 1226500417`, with
the borrower and the loan number appended), while Champions' first line IS exactly
`Conditional Approval Certificate`. Making both `in` would match a pasted sentence that merely
mentions a certificate; making both `==` would never match UWM at all.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.conditions.readers.lines import Line
from app.models.condition_round import ConditionSheetFormat

_UWM_TITLE = "LOAN APPROVAL CONDITIONS"
_CHAMPIONS_TITLE = "Conditional Approval Certificate"


def first_content_line(lines: Sequence[Line]) -> Line | None:
    """The first line with anything on it, or ``None`` for an empty input."""
    return next((line for line in lines if not line.is_blank), None)


def detect_format(lines: Sequence[Line]) -> ConditionSheetFormat:
    """Identify the layout, falling back to GENERIC rather than guessing.

    GENERIC is not a failure. It routes to the generic reader, which finds what structure it can and
    sets `needs_ai` when there is none — so an unrecognised sheet degrades to "AI splits it" rather
    than to "nothing was read".
    """
    first = first_content_line(lines)
    if first is None:
        return ConditionSheetFormat.GENERIC

    text = first.text.strip()
    if _UWM_TITLE in text.upper():
        return ConditionSheetFormat.UWM_APPROVAL_LETTER
    if text == _CHAMPIONS_TITLE:
        return ConditionSheetFormat.CHAMPIONS_CERTIFICATE
    return ConditionSheetFormat.GENERIC
