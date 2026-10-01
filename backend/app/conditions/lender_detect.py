"""Which lender a condition sheet is from, read by code from the sheet itself (LP-949).

THREE SOURCES, STRONGEST FIRST:

1. **The reader that recognised the layout.** A UWM approval letter or a Champions certificate is a
   lender's own template, so recognising the layout is recognising the lender.
2. **The mortgagee clause** the header carries ("United Wholesale Mortgage ISAOA, ATIMA …"). The
   clause names the lender the policy must protect, which is the lender on the sheet.
3. **Anywhere else in the header** (the lender team, the loan facts).

A name is matched against the SHIPPED lenders' printed labels only (`lender_label` in each code map),
case- and spacing-insensitive. Nothing is guessed from a fragment: "Mortgage" alone names no lender.

THIS ONLY DETECTS. It never sets anything: the file's lender is set when she confirms it (ADR-417).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.conditions.lender_codes.loader import lender_label, seeded_lender_keys
from app.models.condition_round import ConditionSheetFormat

#: A recognised layout IS the lender. Generic and pasted text name no lender by their shape.
_READER_KEYS: dict[ConditionSheetFormat, str] = {
    ConditionSheetFormat.UWM_APPROVAL_LETTER: "uwm",
    ConditionSheetFormat.CHAMPIONS_CERTIFICATE: "champions",
}


@dataclass(frozen=True)
class DetectedLender:
    """The shipped lender a sheet names, and where the sheet named it."""

    key: str
    name: str
    #: `reader`, `mortgagee_clause` or `header` — shown to her, so she can weigh it.
    source: str


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _strings(value: Any) -> list[str]:
    """Every string inside a header value (dicts, lists and nested dicts of both)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


def _named_in(text: str) -> str | None:
    """The one shipped lender whose label appears in `text`, or None (none, or more than one)."""
    haystack = _normal(text)
    found = [key for key in seeded_lender_keys() if _normal(lender_label(key)) in haystack]
    return found[0] if len(found) == 1 else None


def detect_lender(
    sheet_format: ConditionSheetFormat | None, header: dict[str, Any] | None
) -> DetectedLender | None:
    """The lender this sheet is from, or None when the sheet does not say."""
    key = _READER_KEYS.get(sheet_format) if sheet_format is not None else None
    if key is not None:
        return DetectedLender(key=key, name=lender_label(key), source="reader")
    header = header or {}
    clause = header.get("mortgagee_clause")
    if isinstance(clause, str):
        key = _named_in(clause)
        if key is not None:
            return DetectedLender(key=key, name=lender_label(key), source="mortgagee_clause")
    rest = {name: value for name, value in header.items() if name != "mortgagee_clause"}
    key = _named_in(" \n ".join(_strings(rest)))
    if key is not None:
        return DetectedLender(key=key, name=lender_label(key), source="header")
    return None
