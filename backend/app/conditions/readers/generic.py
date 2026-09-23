"""The fallback reader for layouts nobody has taught us (LP-906 section 3, spec §6).

⚠️ `needs_ai = True` IS NOT A FAILURE, AND THAT DISTINCTION IS THE WHOLE POINT. It means the RULES
could not split this text and LP-908 must. A sheet with warnings is still a rule-read sheet; a sheet
with no structure at all is one the AI splits — and even then the AI only ever SPLITS, never
interprets, and every row it produces is checked to be a substring of the input (spec §9.3).

What counts as structure, in the spec's order: a numbered list (`1.` / `1)`), a lender-style leading
code (four digits, as UWM prints), or paragraphs separated by blank lines. Any of the three is enough
to return rows; none of them means the text goes to LP-908 with the lines intact.

THE LINES ARE ALWAYS CARRIED, whichever branch runs. Nothing is dropped, because §9.2 applies here
exactly as it does to a layout we know: every non-blank line ends up in a row or in
`unassigned_lines`, and the review screen shows both.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.conditions.readers.lines import Line
from app.conditions.readers.model import RULE_CONFIDENCE, ParsedRow, ParsedSheet
from app.models.condition import BucketKind, OwnerHint, OwnerHintSource
from app.models.condition_round import ConditionSheetFormat

#: A numbered list item: `1. text`, `12) text`.
_NUMBERED = re.compile(r"^\s*(\d{1,4})[.)]\s+(.+)$")

#: A lender-style leading code, the shape UWM prints: four digits then the text.
_CODED = re.compile(r"^\s*(\d{4})\s{2,}(\S.*)$")

#: A heading-shaped line: short, title-cased, no sentence-ending punctuation. Used only to carry a
#: `bucket_heading` through; the kind stays UNKNOWN because an unknown layout's words mean nothing.
_HEADING = re.compile(r"^[A-Z][A-Za-z ]{2,48}(\((PTD|PTF|PTC|PTA)\))?$")


def read_generic(lines: Sequence[Line]) -> ParsedSheet:
    """Find what structure there is; ask for AI only when there is none."""
    sheet = ParsedSheet(sheet_format=ConditionSheetFormat.GENERIC)
    content = [line for line in lines if not line.is_blank]
    if not content:
        sheet.needs_ai = True
        sheet.warnings.append("nothing to read")
        return sheet

    heading = ""
    current: list[str] | None = None
    current_code: str | None = None
    sources: list[int] = []

    def flush() -> None:
        nonlocal current, current_code, sources
        if current:
            sheet.rows.append(
                ParsedRow(
                    sequence=len(sheet.rows) + 1,
                    lender_code=current_code,
                    lender_category=None,
                    bucket_heading=heading,
                    bucket_kind=BucketKind.UNKNOWN,
                    verbatim_text=" ".join(current).strip(),
                    owner_hint=OwnerHint.UNKNOWN,
                    owner_hint_source=OwnerHintSource.NONE,
                    confidence=RULE_CONFIDENCE,
                    source_line_numbers=list(sources),
                )
            )
        current, current_code, sources = None, None, []

    for index, line in enumerate(lines):
        if line.is_blank:
            # A blank line ends a paragraph, which is the third structure signal the spec names.
            flush()
            continue

        text = line.text.strip()

        if (coded := _CODED.match(line.text)) is not None:
            flush()
            current, current_code, sources = [coded.group(2).strip()], coded.group(1), [index]
            continue

        if (numbered := _NUMBERED.match(line.text)) is not None:
            flush()
            current, current_code, sources = [numbered.group(2).strip()], numbered.group(1), [index]
            continue

        if current is None and _HEADING.match(text):
            heading = text
            continue

        if current is None:
            current, sources = [text], [index]
        else:
            current.append(text)
            sources.append(index)

    flush()

    # NO STRUCTURE SIGNAL AT ALL. Every row came from the paragraph fallback and none carried a
    # number or a code, so the rules have not actually split anything — LP-908 must.
    if not any(row.lender_code for row in sheet.rows):
        sheet.needs_ai = True
        sheet.warnings.append("no numbered list, lender code or paragraph structure was recognised")

    return sheet
