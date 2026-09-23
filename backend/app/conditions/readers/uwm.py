"""The UWM approval-letter reader (LP-906 section 2, spec §6 rules 1-8).

A pure function over positioned lines. No database, no network, no AI — which is what lets the whole
of it be checked against the §7.1-7.3 fixtures with no Postgres at all.

THE SHAPE OF A UWM SHEET, which is what every rule below is reading:

    LOAN APPROVAL CONDITIONS - <borrower> - <loan number>     <- title, and the format signal
      Prepared For: ...            Senior UW: ...             <- header, two label/value columns
    LOAN INFORMATION
      Borrower  <name>   Property  <address>  ...             <- loan facts, up to 3 pairs per line
    CONDITIONS
      UW - Prior To Final Approval (PTD)                      <- bucket heading
      1228   Appraisal   Final inspection is required ...     <- row: code, category, text
             <indented continuation>                          <- continuation, column ~44
    EXPIRATION DATES
      Close By   Appraisal   Asset   CPL  ...                 <- headers, POSITIONAL
      10/30/2026 11/23/2026  ...                              <- dates under (some of) them

⚠️ THE EXPIRY TABLE IS THE REASON LINES CARRY POSITIONS AT ALL. Empty columns (CPL, Other, Payoff,
Short Sale, Title, VOB are all blank on the real sheets) mean the Nth date is NOT the Nth header.
Matching by order would silently file the insurance date under `other`. Each date goes to the header
whose start column is NEAREST to it, and a distance over 8 gets a warning rather than a guess.

⚠️ NOTHING IS SILENTLY DROPPED (spec §9.2). Every non-blank line between `CONDITIONS` and
`EXPIRATION DATES` becomes part of a row, a bucket heading, a known artifact (the mortgagee clause,
which breaks into the list at a page boundary), or an entry in `unassigned_lines`. That invariant is
what the review screen depends on, and a reader that quietly discarded a line it did not understand
would lose a lender's demand with nothing on screen to say so.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.ai.extraction.parsing import coerce_date
from app.conditions.lender_codes.loader import LenderCodeSeedError, load_seed
from app.conditions.readers.lines import Line
from app.conditions.readers.model import (
    RULE_CONFIDENCE,
    ParsedRow,
    ParsedSheet,
    UnderwriterNote,
)
from app.models.condition import BucketKind, OwnerHint, OwnerHintSource
from app.models.condition_round import ConditionSheetFormat

#: The lender key whose code map supplies owner-hint defaults (rule 7, LP-910).
UWM_LENDER_KEY = "uwm"

#: Section markers, matched on the stripped line. `CONDITIONS` is deliberately an EQUALITY test: the
#: word appears inside condition text often enough that a `contains` would end the header early.
_LOAN_INFORMATION = "LOAN INFORMATION"
_CONDITIONS = "CONDITIONS"
_EXPIRATION_DATES = "EXPIRATION DATES"

#: Rule 3's row start: `1228         Appraisal                     Final inspection is required ...`
#: The category is non-greedy so a text beginning `TC:` is not swallowed into it — `6378 TC  TC: ...`
#: is the row that proves it, and it is in every fixture.
_ROW_START = re.compile(r"^\s{0,3}(\d{4})\s{2,}(\(PA\)\s+)?(.+?)\s{2,}(\S.*)$")

#: Rule 3's heading pattern, for a heading not in the table below.
_HEADING = re.compile(r"^[A-Z][A-Za-z ]+( - [A-Za-z ]+)?( \((PTD|PTF|PTC|PTA)\))?$")

#: Rule 4. `**8/28 Not in Upload` — two asterisks and a date. `***NOTE***` has three asterisks and no
#: date, and is LENDER text, not an underwriter note; the `\d` immediately after `\*\*\s*` is what
#: separates them. Champions' `**AM to pull SSN Verification.` (spec §7.4) fails it for the same
#: reason, which is why the rule is written as "asterisks THEN a date" rather than "asterisks".
_NOTE = re.compile(r"\*\*\s*(\d{1,2})/(\d{1,2})\s+(.*?)(?:\*\*|$)")

#: Rule 3's artifact: the mortgagee clause, which also appears in the footer and, on a two-page
#: letter, lands in the MIDDLE of the conditions list at a page boundary.
_MORTGAGEE = "Mortgagee Clause:"

#: Rule 3's heading table. The kind follows the PARENTHETICAL, not the words: "Prior To Final
#: Approval (PTD)" is PRIOR_TO_DOCS, and reading the words would file it under approval.
_HEADINGS: dict[str, BucketKind] = {
    "Master": BucketKind.MASTER,
    "UW - Prior To Final Approval (PTD)": BucketKind.PRIOR_TO_DOCS,
    "Compliance - Prior To Closing (PTD)": BucketKind.PRIOR_TO_DOCS,
    "Underwriter To Obtain And Clear": BucketKind.LENDER_TO_CLEAR,
    "Closing (PTF)": BucketKind.PRIOR_TO_FUNDING,
}

#: The fallback, by parenthetical.
_BY_PARENTHETICAL: dict[str, BucketKind] = {
    "PTD": BucketKind.PRIOR_TO_DOCS,
    "PTF": BucketKind.PRIOR_TO_FUNDING,
    "PTC": BucketKind.PRIOR_TO_CLOSING,
    "PTA": BucketKind.PRIOR_TO_APPROVAL,
}

#: Rule 8's keys, in the order the sheet prints them.
_EXPIRY_KEYS: dict[str, str] = {
    "Close By": "close_by",
    "Appraisal": "appraisal",
    "Asset": "asset",
    "CPL": "cpl",
    "Credit": "credit",
    "Income": "income",
    "Insurance": "insurance",
    "Other": "other",
    "Payoff": "payoff",
    "Short Sale": "short_sale",
    "Title": "title",
    "VOB": "vob",
}

#: Rule 8: a date further than this from any header is reported rather than assigned confidently.
_NEAREST_COLUMN_TOLERANCE = 8.0

#: Rule 2's known labels. Order matters only for the longest-match scan below — `Loan Amount
#: (Base/Total)` must be found before `Loan Amount` would be, so the scan sorts by length.
_LOAN_LABELS: tuple[str, ...] = (
    "Borrower",
    "Property Type",
    "Property",
    "Transaction Type",
    "Occupancy",
    "Loan Program",
    "Loan Amount (Base/Total)",
    "Status",
    "Appraised Value",
    "AUS",
    "Submission Date",
    "Purchase Price",
    "FICO",
    "Must Fund By",
    "LTV / CLTV",
    "Term",
    "Must Not Close Before",
    "Note Rate",
    "Compensation Type",
    "Rate Lock Exp",
    "Housing / Debt Ratios",
    "Esign",
    "Max Funds to Close",
    "Max PITI",
    "Verified Income",
    "Verified Assets",
    "Escrows",
    "Down Payment",
    "Earnest Money Deposit",
    "Non Borrowing Ind",
    "Debts to Be Paid",
    "Max Seller Concessions",
    "Mortgage Insurance",
)

#: ⚠️ RULE 2'S SCAN, ANCHORED — and an unanchored version of this was a real defect. A label counts
#: only at line start or after two or more spaces, AND only when two or more spaces (or the line end)
#: follow it. Without the anchors this was a free `str.find` over the whole line, so a label word
#: inside a VALUE matched: a borrower named "Termaine Willis" produced `{"Term": "aine Willis"}` and
#: LOST the `Borrower` key entirely; "118 Status Road" produced `{"Status": "Road"}`. Range-marking
#: could not fix it — that stops a shorter label overlapping a longer MATCH, and does nothing about a
#: label matching inside a value. This is the same `\s{2,}` shape `_split_header`'s pair regex uses,
#: which is exactly why the header never had this bug.
_LOAN_LABEL_SCAN = re.compile(
    r"(?:^\s*|\s{2,})("
    + "|".join(re.escape(label) for label in sorted(_LOAN_LABELS, key=len, reverse=True))
    + r")(?=\s{2,}|$)"
)

#: Rule 1: the lender's own team, which becomes `header["lender_team"]`.
_TEAM_LABELS: tuple[str, ...] = ("Senior UW", "UW II", "UW Team", "AE", "Closer")

#: Rule 1: the broker side, which becomes `header["broker_contact"]`.
_BROKER_LABELS: tuple[str, ...] = ("Prepared For", "Contact Name", "NMLS ID", "Email", "Phone")

_EXT = re.compile(r"\s*ext\.\s*(\d+)\s*$")


@dataclass
class _Row:
    """A row under construction — its text is still a list of lines to be joined."""

    code: str
    category: str
    processor_assist: bool
    heading: str
    kind: BucketKind
    parts: list[str]
    lines: list[int]


def _heading_kind(text: str) -> tuple[BucketKind, bool]:
    """Rule 3's heading table, then the parenthetical, then `Trailing`, then UNKNOWN + warning."""
    if text in _HEADINGS:
        return _HEADINGS[text], False
    parenthetical = re.search(r"\((PTD|PTF|PTC|PTA)\)", text)
    if parenthetical:
        return _BY_PARENTHETICAL[parenthetical.group(1)], False
    if "Trailing" in text:
        return BucketKind.TRAILING, False
    return BucketKind.UNKNOWN, True


def _is_heading(line: Line) -> bool:
    """A heading has <= 3 leading spaces, no leading 4-digit code, and matches the pattern.

    ⚠️ PDF INPUT RAISES RATHER THAN ANSWERING `False`, and answering `False` was a real defect.
    `indent` is None for every PDF-built line (section 1), so `indent is None or indent > 3` made
    this return False for EVERY line of every uploaded sheet — and the caller's next branch treats
    `indent is None` as a continuation, so each bucket heading was silently glued onto the preceding
    condition's text. The damage was invisible: row starts still matched, so the sheet produced the
    right number of rows, all filed under a stale bucket, one carrying words the lender never wrote.

    A points-based column threshold is what this needs, and it cannot be calibrated until section 3
    authors the first real PDF fixture. Until then the absence is loud.
    """
    indent = line.indent
    if indent is None:
        raise NotImplementedError(
            "UWM heading detection needs a column threshold in points for PDF-built lines; "
            "section 3 calibrates it against the first authored PDF fixture"
        )
    if indent > 3:
        return False
    text = line.text.strip()
    if not text or _ROW_START.match(line.text):
        return False
    return text in _HEADINGS or bool(_HEADING.match(text))


def _notes(text: str, reference: date | None) -> list[UnderwriterNote]:
    """Rule 4. The year comes from `date_printed`, or the year before if that would be the future.

    ⚠️ A NOTE DATED AFTER THE LETTER IT APPEARS ON IS IMPOSSIBLE. The sheet prints `8/28` with no
    year; on a letter printed 2026-01-05, `12/30` means the PRECEDING December, not eleven months
    hence. Without the rollback the note sorts after the sheet that carries it.
    """
    out: list[UnderwriterNote] = []
    for match in _NOTE.finditer(text):
        month, day, body = int(match.group(1)), int(match.group(2)), match.group(3).strip()
        resolved: date | None = None
        if reference is not None:
            try:
                resolved = date(reference.year, month, day)
            except ValueError:
                resolved = None
            else:
                if resolved > reference:
                    resolved = date(reference.year - 1, month, day)
        out.append(UnderwriterNote(date=resolved, text=body))
    return out


def _owner_hint(
    text: str, *, processor_assist: bool, kind: BucketKind, code: str
) -> tuple[OwnerHint, OwnerHintSource]:
    """Rule 7, in the spec's precedence order: the lender's own markers beat everything.

    The order is the point. A `TC:` prefix the lender typed is far stronger evidence than a default
    looked up from a code map, so it wins — and `owner_hint_source` records which it was, because a
    UI that showed them identically would invite trusting the weak one.
    """
    if text.startswith("TC:"):
        return OwnerHint.TITLE, OwnerHintSource.PREFIX
    if processor_assist:
        return OwnerHint.LENDER, OwnerHintSource.PREFIX
    if kind is BucketKind.LENDER_TO_CLEAR:
        return OwnerHint.LENDER, OwnerHintSource.BUCKET
    try:
        for row in load_seed(UWM_LENDER_KEY):
            if row.code == code and row.default_owner_hint is not None:
                return row.default_owner_hint, OwnerHintSource.CODE_MAP
    except LenderCodeSeedError:
        # A malformed shipped map must not take the reader down with it: the sheet still parses and
        # every row simply lacks a code-map hint. The seed step is where that error is fatal.
        return OwnerHint.UNKNOWN, OwnerHintSource.NONE
    return OwnerHint.UNKNOWN, OwnerHintSource.NONE


def _fingerprint_text(text: str) -> str:
    """The text with note spans removed, lower-cased, whitespace collapsed (rule 5's input).

    Used here only for DEDUPLICATION (rule 6). The stored `text_fingerprint` is computed at import.

    ⚠️ THIS DOES NOT MAKE AN ANNOTATED COPY EQUAL TO A CLEAN ONE, and an earlier version of this
    docstring claimed it did. Rule 6's key is "the same code, fingerprint AND notes", so the notes are
    compared as a third element and the stripping here is cancelled by it. That is the SPEC'S rule and
    it is kept deliberately: the alternative — dropping the notes from the key — would discard a copy
    the underwriter annotated in favour of one they did not, losing the annotation.

    The consequence, stated rather than hidden: a page-overlap duplicate whose two copies differ —
    annotated on one page only, or split mid-sentence so the text itself differs — SURVIVES as two
    rows. Both are visible to the processor on the review screen, which is the safe direction to
    fail; silently dropping a row the lender printed is not.
    """
    return " ".join(_NOTE.sub(" ", text).lower().split())


def _split_header(lines: Sequence[Line]) -> tuple[dict[str, object], date | None, list[str]]:
    """Rule 1: `Label:  value` pairs, up to two per line, from the title to `LOAN INFORMATION`."""
    team: list[dict[str, object]] = []
    broker: dict[str, str] = {}
    printed: date | None = None
    warnings: list[str] = []

    pairs = re.compile(r"([A-Za-z][A-Za-z /]*?):\s{2,}(.*?)(?=\s{2,}[A-Za-z][A-Za-z /]*?:|$)")
    # ⚠️ A ROLE PRINTED WITH NO VALUE IS STILL A ROLE. `Closer:` with nothing after it is the lender
    # asserting the role exists and is unfilled; the pair regex above cannot match it (it requires a
    # value), so it is picked up here. Omitting the entry would make "no closer assigned yet"
    # indistinguishable from "this letter has no closer field", and LP-909's UI cannot recover the
    # difference afterwards.
    empty_role = re.compile(r"([A-Za-z][A-Za-z /]*?):\s*$")
    for line in lines:
        if (unfilled := empty_role.search(line.text)) is not None:
            role = unfilled.group(1).strip()
            if role in _TEAM_LABELS:
                team.append({"role": role, "name": "", "phone_ext": None})
        for label, value in pairs.findall(line.text):
            label, value = label.strip(), value.strip()
            if label in _TEAM_LABELS:
                ext = _EXT.search(value)
                team.append(
                    {
                        "role": label,
                        "name": _EXT.sub("", value).strip(),
                        "phone_ext": ext.group(1) if ext else None,
                    }
                )
            elif label in _BROKER_LABELS:
                broker[label] = value
            elif label == "Date Printed":
                printed = coerce_date(value)
                if printed is None and value:
                    warnings.append(f"unparseable Date Printed: {value!r}")
            else:
                warnings.append(f"unknown header label: {label!r}")

    header: dict[str, object] = {"lender_team": team, "broker_contact": broker}
    return header, printed, warnings


def _split_loan_facts(lines: Sequence[Line]) -> tuple[dict[str, str], list[str]]:
    """Rule 2: find known labels in each line, take the text up to the next known label.

    Longest label first, so `Loan Amount (Base/Total)` is not truncated to `Loan Amount`, and
    `Property Type` is not read as `Property`.
    """
    facts: dict[str, str] = {}
    warnings: list[str] = []

    for line in lines:
        text = line.text
        if not text.strip():
            continue
        matches = list(_LOAN_LABEL_SCAN.finditer(text))
        if not matches:
            if text.strip().startswith("*"):
                continue  # the "* Note rate is subject to change" footnote — lender boilerplate
            # ⚠️ THE POSITION, NEVER THE LINE ITSELF. A loan-information line carries the borrower's
            # name, the property address and the figures — reproducing 60 characters of it put NPI
            # into `parse_report.warnings`, a column LP-904 declares NON-NPI and which is therefore
            # not excluded from the readonly layer the way `raw_text` and `unassigned_lines` are.
            # The line number identifies the problem for whoever is debugging; the content does not
            # need to travel with it. (The readonly view only ever exposes the warning COUNT, so
            # nothing escaped that way — but the value was still stored in a field declared clean.)
            warnings.append(f"unrecognised loan-information line at line {int(line.y)}")
            continue
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            value = text[match.end() : end].strip()
            if value:
                facts[match.group(1)] = value
    return facts, warnings


def _expiry(lines: Sequence[Line]) -> tuple[dict[str, date | None], list[str]]:
    """Rule 8, and the one place a mis-read is silent rather than loud.

    ⚠️ ASSIGNED BY NEAREST COLUMN, NEVER BY ORDER. Six of the twelve columns are blank on every real
    sheet, so the Nth date is not the Nth header; matching by order files the insurance date under
    `other` and nothing looks wrong. A date further than the tolerance from any header gets a
    warning instead of a confident wrong answer.
    """
    dates: dict[str, date | None] = dict.fromkeys(_EXPIRY_KEYS.values())
    warnings: list[str] = []

    header_line = next((line for line in lines if line.text.strip().startswith("Close By")), None)
    if header_line is None:
        return dates, ["expiry table: no `Close By` header row"]

    columns: list[tuple[float, str]] = []
    for printed, key in _EXPIRY_KEYS.items():
        first = printed.split()[0]
        token = next((t for t in header_line.tokens if t.text == first), None)
        if token is not None:
            columns.append((token.x0, key))

    value_line = next(
        (
            line
            for line in lines
            if line.y > header_line.y and not line.is_blank and "/" in line.text
        ),
        None,
    )
    if value_line is None:
        return dates, ["expiry table: header row but no dates"]

    for token in value_line.tokens:
        parsed = coerce_date(token.text)
        if parsed is None:
            continue
        nearest = min(columns, key=lambda c: abs(c[0] - token.x0), default=None)
        if nearest is None:
            continue
        distance = abs(nearest[0] - token.x0)
        if distance > _NEAREST_COLUMN_TOLERANCE:
            warnings.append(
                f"expiry date {token.text} is {distance:.0f} from the nearest column "
                f"({nearest[1]}); not assigned"
            )
            continue
        dates[nearest[1]] = parsed
    return dates, warnings


def read_uwm(lines: Sequence[Line]) -> ParsedSheet:
    """Read a UWM approval letter into a `ParsedSheet` (spec §6 rules 1-8)."""
    sheet = ParsedSheet(sheet_format=ConditionSheetFormat.UWM_APPROVAL_LETTER)

    # ⚠️ REFUSED LOUDLY ON PDF INPUT, because reading it quietly produced a plausible wrong answer.
    # Every rule below that separates a heading from a continuation measures `indent`, which is None
    # for PDF-built lines — so a PDF parsed to the right number of rows under the wrong buckets with
    # headings glued into the text. Section 3 authors the first PDF fixture and calibrates a
    # points-based threshold; LP-905, which is the first caller to hand this real PDFs, comes after
    # it in the spec's own order (§4), so nothing downstream depends on this gap being filled yet.
    if any(line.from_pdf for line in lines):
        raise NotImplementedError(
            "the UWM reader cannot yet read PDF-built lines: heading and continuation detection "
            "need a column threshold in points, which section 3 calibrates against a real PDF"
        )

    def index_of(marker: str) -> int | None:
        return next(
            (i for i, line in enumerate(lines) if line.text.strip() == marker),
            None,
        )

    loan_at, conditions_at, expiry_at = (
        index_of(_LOAN_INFORMATION),
        index_of(_CONDITIONS),
        index_of(_EXPIRATION_DATES),
    )

    if conditions_at is None:
        sheet.warnings.append("no CONDITIONS marker; nothing could be read")
        sheet.needs_ai = True
        return sheet

    # ⚠️ A MISSING HEADER IS A WARNING, NOT A FAILURE. The page-break fixture omits it entirely, and
    # the conditions are the part that matters — refusing the sheet because its letterhead is absent
    # would discard every condition on it.
    if loan_at is None:
        sheet.warnings.append("header not found")
    else:
        header, printed, header_warnings = _split_header(lines[1:loan_at])
        facts, fact_warnings = _split_loan_facts(lines[loan_at + 1 : conditions_at])
        header["loan_facts"] = facts
        sheet.header = header
        sheet.date_printed = printed
        sheet.warnings.extend(header_warnings)
        sheet.warnings.extend(fact_warnings)

    block_end = expiry_at if expiry_at is not None else len(lines)
    rows: list[_Row] = []
    current: _Row | None = None
    heading, kind = "", BucketKind.UNKNOWN

    for offset, line in enumerate(lines[conditions_at + 1 : block_end], start=conditions_at + 1):
        if line.is_blank:
            continue

        if _MORTGAGEE in line.text:
            if sheet.mortgagee_clause is None:
                sheet.mortgagee_clause = line.text.split(_MORTGAGEE, 1)[1].strip()
            current = None
            continue

        if (match := _ROW_START.match(line.text)) is not None:
            current = _Row(
                code=match.group(1),
                category=match.group(3).strip(),
                processor_assist=match.group(2) is not None,
                heading=heading,
                kind=kind,
                parts=[match.group(4).strip()],
                lines=[offset],
            )
            rows.append(current)
            continue

        if _is_heading(line):
            heading, unknown = line.text.strip(), False
            kind, unknown = _heading_kind(heading)
            if unknown:
                sheet.warnings.append(f"unrecognised bucket heading: {heading!r}")
            current = None
            continue

        indent = line.indent
        if current is not None and (indent is None or indent >= 20):
            current.parts.append(line.text.strip())
            current.lines.append(offset)
            continue

        sheet.unassigned_lines.append(line.text.strip())

    # Rule 6. Same code AND same note-stripped text AND same notes = a page-overlap artifact.
    # ⚠️ A REPEATED CODE WITH DIFFERENT TEXT IS NOT A DUPLICATE: UWM lists 0571 once per change of
    # circumstance, and three of them appear on the page-break fixture with three different amounts.
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for row in rows:
        text = " ".join(row.parts)
        notes = _notes(text, sheet.date_printed)
        key = (row.code, _fingerprint_text(text), tuple(n.text for n in notes))
        if key in seen:
            sheet.duplicates_dropped += 1
            sheet.warnings.append(f"dropped page-overlap duplicate of code {row.code}")
            continue
        seen.add(key)

        hint, source = _owner_hint(
            text, processor_assist=row.processor_assist, kind=row.kind, code=row.code
        )
        sheet.rows.append(
            ParsedRow(
                sequence=len(sheet.rows) + 1,
                lender_code=row.code,
                lender_category=row.category,
                bucket_heading=row.heading,
                bucket_kind=row.kind,
                verbatim_text=text,
                underwriter_notes=notes,
                owner_hint=hint,
                owner_hint_source=source,
                processor_assist=row.processor_assist,
                confidence=RULE_CONFIDENCE,
                source_line_numbers=row.lines,
            )
        )

    if expiry_at is not None:
        dates, expiry_warnings = _expiry(lines[expiry_at:])
        sheet.expiry_dates = dates
        sheet.warnings.extend(expiry_warnings)

    # ⚠️ THE CLAUSE IS USUALLY IN THE FOOTER, NOT IN THE LIST. The loop above only reaches it when a
    # page boundary breaks it INTO the conditions block (the page-break fixture). On an ordinary
    # one-page letter it sits below `EXPIRATION DATES`, outside the block entirely — so scanning the
    # block alone found it on the hard fixture and missed it on the easy one, which is the wrong way
    # round and is what the round-1 test caught. Captured once, first occurrence winning, because
    # the two-page letter prints it twice and both copies are identical.
    if sheet.mortgagee_clause is None:
        footer = next((line for line in lines if _MORTGAGEE in line.text), None)
        if footer is not None:
            sheet.mortgagee_clause = footer.text.split(_MORTGAGEE, 1)[1].strip()

    return sheet
