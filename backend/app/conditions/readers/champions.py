"""The Champions certificate reader (LP-906 section 3, spec §6 rules 1-5).

⚠️ THE HARD ONE, AND THE REASON LINES CARRY POSITIONS AT ALL. Champions prints each condition's
number VERTICALLY CENTRED on its row, so the number lands on the row's first line, a middle line, or
a line of its own depending only on how many lines the text wrapped to:

                 Earnest money deposit verification in the amount of $3,000 is required ...
     71          settlement agent. (1) Provide copy of check/ACH with bank statement ...
                 -AND- (2) proof of receipt from escrow.
                 Provide most recent bank statements with all pages to meet reserves ...
     268
                 estimated assets of $115,367.50 (cash to close $100,390.72 ...).

There is no marker saying where a row starts. The only thing that says so is the geometry: if a
number sits at a row's centre, then `top = 2 * number.y - bottom`. Walking the numbers BOTTOM-UP,
each row's bottom is known (the segment's last line, or the line above the row below it), so each
row's top follows. A reader working top-down cannot do this — it would not know where the first row
ends until it knew where the second began.

⚠️ THIS READER NEVER TOUCHES `Line.indent`. It is None for PDF input, which is the only input that
carries the geometry this algorithm needs. Everything here keys on `x0` in points and on `y` order,
both of which are real on a PDF and on text alike.
"""

from __future__ import annotations

import itertools
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from app.ai.extraction.parsing import coerce_date
from app.conditions.readers.lines import Line
from app.conditions.readers.model import (
    RULE_CONFIDENCE,
    UNCERTAIN_CONFIDENCE,
    ParsedRow,
    ParsedSheet,
)
from app.conditions.readers.uwm import _notes
from app.models.condition import BucketKind, OwnerHint, OwnerHintSource
from app.models.condition_round import ConditionSheetFormat

#: Rule 4. On a PDF there are no leading spaces, so the spec's `^\s{1,3}` becomes a match on the
#: stripped text; the heading's own column is checked separately via `x0`.
_SECTION = re.compile(r"^Prior to (Docs|Funding|Closing|Approval)\s*-\s*(.+)$")

_STAGE: dict[str, BucketKind] = {
    "Approval": BucketKind.PRIOR_TO_APPROVAL,
    "Docs": BucketKind.PRIOR_TO_DOCS,
    "Closing": BucketKind.PRIOR_TO_CLOSING,
    "Funding": BucketKind.PRIOR_TO_FUNDING,
}

#: Rule 1's footer patterns. `NMLS #` and a wall-clock timestamp are both unmistakable and neither
#: can appear inside a condition.
_FOOTER = re.compile(r"NMLS #|\d{1,2}:\d{2}:\d{2}\s*[AP]M")

#: ⚠️ THE LOAN LINE IS MATCHED AS `Date: … Loan #:` TOGETHER, NEVER ON `Date:` ALONE. Rule 2's
#: wrapped label puts a bare `Date: 12/15/2026` in the HEADER — the continuation of
#: `Title Commitment Exp` — and a furniture rule keyed on `Date:` would silently eat it, losing an
#: expiry date with nothing to show for it.
_LOAN_LINE = re.compile(r"^Date:\s.*\bLoan #:")

#: Rule 3's expiry labels, mapped to the keys `ParsedSheet.expiry_dates` uses.
_EXPIRY_LABELS: dict[str, str] = {
    "Approval Exp Date": "approval",
    "Rate Lock Exp": "rate_lock",
    "Appraisal Exp Date": "appraisal",
    "Asset Exp Date": "asset",
    "Credit Exp Date": "credit",
    "Title Exp Date": "title",
    "Title Commitment Exp Date": "title_commitment",
    "CPL Exp Date": "cpl",
}

#: Rule 2's contact blocks, each introduced by its own title line.
_CONTACT_TITLES: tuple[str, ...] = ("Account Executive", "Underwriter", "Account Manager")

#: ⚠️ ANCHORED ON THE KNOWN LABELS, BECAUSE PDF TEXT HAS NO DOUBLE SPACES. `Line.text` for a
#: PDF-built line is `" ".join(tokens)`, so every run of whitespace is exactly one space — and a
#: pair regex that ended a value at `\s{2,}` (the shape the UWM header uses on text input) never
#: fires. Measured before this fix: `Credit Exp Date` came back as
#: `'01/07/2027 Appraisal Exp Date: 12/27/2026'`, swallowing the next column whole, and every expiry
#: date parsed as None. Matching a CLOSED SET of labels is what bounds each value instead — the same
#: repair as the UWM reader's loan-fact scan, for the same underlying reason.
_HEADER_LABELS: tuple[str, ...] = (*_EXPIRY_LABELS, "Name", "Phone", "Email")
_HEADER_SCAN = re.compile(
    r"(?:^|\s)("
    + "|".join(re.escape(label) for label in sorted(_HEADER_LABELS, key=len, reverse=True))
    + r"):"
)

#: A row number is a short run of digits in the leftmost column. The threshold is relative to the
#: page's own text column rather than an absolute point value, so it holds at any font size.
_NUMBER = re.compile(r"^\d{1,4}$")


@dataclass
class _Segment:
    """One page's worth of lines under one heading — the unit the centre rule works within."""

    page: int
    heading: str
    kind: BucketKind
    category: str
    lines: list[Line] = field(default_factory=list)
    #: False when the segment opens a page without its heading above it, which is what makes a
    #: leftover run at the top a continuation of the previous page's last row.
    starts_with_heading: bool = False


def _is_furniture(line: Line, repeated: frozenset[str]) -> bool:
    """Rule 1: the header repeated at the top of every page, and the two footer lines."""
    text = line.text.strip()
    return text in repeated or bool(_FOOTER.search(text)) or bool(_LOAN_LINE.match(text))


def _median_line_height(lines: Sequence[Line]) -> float:
    """The page's own line pitch, measured rather than assumed.

    Every tolerance below is expressed in these units, so the reader does not carry a font size or a
    fixture's geometry baked into a constant.
    """
    gaps = [round(b.y - a.y, 2) for a, b in itertools.pairwise(lines) if 0.0 < b.y - a.y < 40.0]
    return statistics.median(gaps) if gaps else 12.0


def _header(lines: Sequence[Line]) -> tuple[dict[str, object], dict[str, date | None], list[str]]:
    """Rules 2 and 3: the label/value blocks, the three contacts, and the expiry table."""
    warnings: list[str] = []
    expiry: dict[str, date | None] = dict.fromkeys(_EXPIRY_LABELS.values())
    team: list[dict[str, object]] = []
    facts: dict[str, str] = {}

    # ⚠️ RULE 2'S WRAPPED LABEL, JOINED BEFORE ANYTHING IS PARSED. The spec names the case exactly:
    # `Title Commitment Exp` ends one line and `Date:` begins the next. Joining first means the
    # scan below sees one label it knows, rather than a line with no label and a line whose label
    # (`Date`) is indistinguishable from the furniture header's `Date: … Loan #:`.
    joined: list[str] = []
    texts = [line.text.strip() for line in lines if line.text.strip()]
    skip_next = False
    for index, text in enumerate(texts):
        if skip_next:
            skip_next = False
            continue
        nxt = texts[index + 1] if index + 1 < len(texts) else ""
        if ":" not in text and text not in _CONTACT_TITLES and ":" in nxt:
            joined.append(f"{text} {nxt}")
            skip_next = True
        else:
            joined.append(text)

    current_contact: str | None = None

    for text in joined:
        if text in _CONTACT_TITLES:
            current_contact = text
            team.append({"role": text, "name": "", "phone": "", "email": ""})
            continue

        matches = list(_HEADER_SCAN.finditer(text))
        if not matches:
            continue

        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            label = match.group(1)
            value = text[match.end() : end].strip()

            if label in _EXPIRY_LABELS:
                parsed = coerce_date(value)
                if parsed is None and value:
                    warnings.append(f"unparseable {label}: {value!r}")
                expiry[_EXPIRY_LABELS[label]] = parsed
            elif current_contact and label in {"Name", "Phone", "Email"} and team:
                team[-1][label.lower()] = value
            elif value:
                facts[label] = value

    header: dict[str, object] = {"lender_team": team, "loan_facts": facts}
    return header, expiry, warnings


def _segments(lines: Sequence[Line], repeated: frozenset[str]) -> tuple[list[_Segment], list[Line]]:
    """Split the body into (page, heading) segments, returning the header lines separately."""
    head: list[Line] = []
    out: list[_Segment] = []
    heading, kind, category = "", BucketKind.UNKNOWN, ""
    seen_first_heading = False

    for line in lines:
        if line.is_blank or _is_furniture(line, repeated):
            continue

        match = _SECTION.match(line.text.strip())
        if match is not None:
            seen_first_heading = True
            heading = line.text.strip()
            kind = _STAGE[match.group(1)]
            category = match.group(2).strip()
            out.append(_Segment(line.page, heading, kind, category, starts_with_heading=True))
            continue

        if not seen_first_heading:
            head.append(line)
            continue

        # A page break inside one heading opens a NEW segment that does NOT start with a heading —
        # which is precisely the condition rule 5 uses to recognise a row split across pages.
        if not out or out[-1].page != line.page:
            out.append(_Segment(line.page, heading, kind, category, starts_with_heading=False))
        out[-1].lines.append(line)

    return [s for s in out if s.lines], head


def _text_column(lines: Sequence[Line]) -> float:
    """Where body text begins, measured across the WHOLE sheet rather than within one segment.

    ⚠️ MEASURING THIS PER SEGMENT WAS A REAL DEFECT, and it deleted two conditions. A row whose text
    wraps to a single line has its number centred on that line's own baseline, so the two merge and
    the line's first token IS the number. In a section holding exactly one such row — §7.4's `133`
    and `286` — the segment's median first-token position was therefore the number's own column, the
    number failed its own "left of the body text" test, and the entire segment fell through to
    `unassigned_lines`. Two rows vanished and the sheet still looked clean.

    Measured across the sheet the body column is unambiguous: most lines are wrapped text, so the
    mode is the text column and a merged line's leading number sits plainly left of it.
    """
    starts = [line.tokens[0].x0 for line in lines if line.tokens]
    return statistics.mode(starts) if starts else 0.0


def _rows_in(
    segment: _Segment, pitch: float, text_column: float
) -> tuple[list[tuple[str, list[Line]]], list[Line], bool]:
    """The centre rule, bottom-up. Returns `(rows, leftover lines above the first row, ok)`.

    Each row's bottom is known before its top: the last row ends at the segment's last line, and
    every row above ends on the line above the row below it. `top = 2 * number.y - bottom` then
    places the top, because the number sits at the row's centre.
    """
    lines = sorted(segment.lines, key=lambda line: line.y)
    numbered: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        first = line.tokens[0] if line.tokens else None
        if first is not None and _NUMBER.match(first.text) and first.x0 < text_column - 1.0:
            numbered.append((index, first.text))

    if not numbered:
        return [], lines, True

    rows: list[tuple[str, list[Line]]] = []
    bottom = len(lines) - 1
    ok = True

    for index, number in reversed(numbered):
        top_y = 2.0 * lines[index].y - lines[bottom].y
        top = next(
            (i for i, line in enumerate(lines) if line.y >= top_y - pitch / 2.0),
            0,
        )
        if not top <= index <= bottom:
            # The number fell outside the row its own centre implies — the geometry disagrees with
            # itself, so the segment is read but not trusted (rule 5's check).
            ok = False
            top = min(top, index)
        rows.append((number, lines[top : bottom + 1]))
        bottom = top - 1
        if bottom < 0:
            break

    rows.reverse()
    leftover = lines[: bottom + 1] if bottom >= 0 else []
    return rows, leftover, ok


def read_champions(lines: Sequence[Line]) -> ParsedSheet:
    """Read a Champions conditional approval certificate (spec §6 rules 1-5)."""
    sheet = ParsedSheet(sheet_format=ConditionSheetFormat.CHAMPIONS_CERTIFICATE)
    if not lines:
        sheet.needs_ai = True
        sheet.warnings.append("empty sheet")
        return sheet

    first_page = [line for line in lines if line.page == 1 and not line.is_blank]
    repeated = frozenset(line.text.strip() for line in first_page[:2])

    segments, header_lines = _segments(lines, repeated)
    header, expiry, header_warnings = _header(header_lines)
    sheet.header = header
    sheet.expiry_dates = expiry
    sheet.warnings.extend(header_warnings)
    sheet.date_printed = None

    pitch = _median_line_height([line for line in lines if not line.is_blank])
    text_column = _text_column([line for segment in segments for line in segment.lines])
    failed_segments = 0

    for segment in segments:
        rows, leftover, ok = _rows_in(segment, pitch, text_column)
        if not ok:
            failed_segments += 1
            sheet.warnings.append(
                f"centre rule disagreed with itself in {segment.heading!r} on page {segment.page}"
            )

        if leftover:
            # ⚠️ LINES ABOVE THE FIRST ROW OF A SEGMENT THAT DID NOT OPEN WITH A HEADING are the
            # tail of the PREVIOUS page's last row — a condition split across the page break.
            if not segment.starts_with_heading and sheet.rows:
                previous = sheet.rows[-1]
                previous.verbatim_text = " ".join(
                    [previous.verbatim_text, *(line.text.strip() for line in leftover)]
                )
                previous.crossed_page = True
                previous.source_line_numbers.extend(range(len(leftover)))
            else:
                sheet.unassigned_lines.extend(line.text.strip() for line in leftover)

        for number, row_lines in rows:
            text = " ".join(
                _without_number(line, number) for line in row_lines if _without_number(line, number)
            )
            sheet.rows.append(
                ParsedRow(
                    sequence=len(sheet.rows) + 1,
                    lender_code=number,
                    lender_category=segment.category,
                    bucket_heading=segment.heading,
                    bucket_kind=segment.kind,
                    verbatim_text=text,
                    underwriter_notes=_notes(text, sheet.date_printed),
                    owner_hint=OwnerHint.UNKNOWN,
                    owner_hint_source=OwnerHintSource.NONE,
                    confidence=RULE_CONFIDENCE if ok else UNCERTAIN_CONFIDENCE,
                    source_line_numbers=[int(line.y) for line in row_lines],
                )
            )

    if segments and failed_segments == len(segments):
        # Every segment disagreed with itself — the layout is not the one this reader knows, so the
        # honest move is to hand it to LP-908 rather than return rows nobody should trust.
        sheet.needs_ai = True
    return sheet


def _without_number(line: Line, number: str) -> str:
    """The line's text with a leading row number removed; a number-only line contributes nothing."""
    tokens = list(line.tokens)
    if tokens and tokens[0].text == number:
        tokens = tokens[1:]
    return " ".join(token.text for token in tokens).strip()
