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
whose start column is NEAREST to it, and one too far from any column gets a warning rather than a
guess — "too far" being a fraction of the sheet's own column spacing, because the spec's "8" means
characters on a pasted sheet and points on an uploaded one.

⚠️ NOTHING IS SILENTLY DROPPED (spec §9.2). Every non-blank line between `CONDITIONS` and
`EXPIRATION DATES` becomes part of a row, a bucket heading, a known artifact (the mortgagee clause,
which breaks into the list at a page boundary), or an entry in `unassigned_lines`. That invariant is
what the review screen depends on, and a reader that quietly discarded a line it did not understand
would lose a lender's demand with nothing on screen to say so.
"""

from __future__ import annotations

import itertools
import re
import statistics
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

#: The code alone, for the positional matcher below — a PDF line has no runs of spaces to anchor on.
_CODE = re.compile(r"^\d{4}$")

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

#: Rule 8: how far a date may sit from its column header before it is reported rather than assigned.
#:
#: ⚠️ A FRACTION OF THE COLUMN SPACING, NOT A CONSTANT, because the two inputs are in different
#: units and a single number silently means different things in each. The spec's "8" is eight
#: CHARACTERS; on a PDF the same eight is eight POINTS — under two characters at 8pt Courier — and
#: three of round 1's six dates were rejected as "19 from the nearest column" when 19 points is
#: about four characters. That is the same units confusion as an `indent` that was always None and a
#: `\s{2,}` scan that matched nothing: a text-calibrated constant applied to positions.
#:
#: Derived from the gap between the expiry headers themselves, it is unitless: a date belongs to a
#: column when it is nearer to it than to its neighbour, with a margin.
_NEAREST_COLUMN_FRACTION = 0.4

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
#: The known labels, longest first so `Loan Amount (Base/Total)` is not truncated to `Loan Amount`
#: and `Property Type` is not read as `Property`.
#:
#: ⚠️ MATCHED AT A CELL START, NOT ACROSS ARBITRARY WHITESPACE, and getting this wrong twice is why
#: it is spelled out. The first version searched the whole line, so `Property  118 Status Road` gave
#: `{'Property': '118', 'Status': 'Road'}` — a street name eating the field that owned the line. The
#: second required `\s{2,}` around the label, which fixed text and broke PDFs, where
#: `lines_from_pdf` joins tokens with SINGLE spaces and the scan matched nothing at all (16
#: `unrecognised loan-information line` warnings against the text path's zero).
#:
#: Relaxing it to `\s+` brought the street name straight back. The width of the gap was never the
#: real signal — being at the start of a COLUMN was, and `_cells` recovers that from two spaces on
#: text and from token gaps on a PDF, so one rule now serves both units.
_LOAN_LABEL_PREFIX = re.compile(
    r"^("
    + "|".join(re.escape(label) for label in sorted(_LOAN_LABELS, key=len, reverse=True))
    + r")(?=\s|$)"
)

#: The same closed set, found ANYWHERE in a cell — used only to bound a value that has already been
#: opened by a label, never to open one.
#:
#: ⚠️ THIS IS WHAT REPLACED A GAP-WIDTH RULE, AFTER THREE OF THEM FAILED. A PDF's gaps form a
#: HIERARCHY — measured on round 1's loan-information lines: words 9.6-52.8 points, label-to-value
#: ~77-100, column-pair ~130-158 — so any single threshold picks one level and merges the others.
#: A constant of 24 split every word; a median multiple and a largest-gap split each merged whole
#: column pairs, leaving `AUS` holding `Desktop Underwriter Submission Date 07/17/2026`. 18 of 26
#: lines were wrong, and the premise ("one gap rule recovers the columns") was what was wrong.
#:
#: The label set needs no gap at all: a value ends where the next KNOWN label begins. And it cannot
#: bring back the street-name defect, because a cell is only scanned when it STARTS with a label —
#: `118 Status Road` never does, so `Status` inside it is never consulted.
_LOAN_LABEL_ANYWHERE = re.compile(
    r"(?:(?<=\s)|^)("
    + "|".join(re.escape(label) for label in sorted(_LOAN_LABELS, key=len, reverse=True))
    + r")(?=\s|$)"
)


def _pairs_in_cell(cell: str) -> list[tuple[str, str]]:
    """Every `label value` pair inside one cell, or nothing if it does not open with a label.

    ⚠️ WHAT ACTUALLY PROTECTS A VALUE CONTAINING A LABEL WORD, because it is not what it looks like.
    Two different mechanisms, and only one of them is this function's:

    * `Terman`, `Statuses` — rejected by `_LOAN_LABEL_ANYWHERE`'s boundary guards, so a label that is
      merely a prefix or suffix of a longer word is not a label. That part is here.
    * `Loan Program | Conforming Fixed Term` — survives because `_cells` split on the column gutter
      BEFORE this ran, so the label word and the next real label were never in the same cell. **The
      protection is the cell boundary, not the label set**, and it would move if cell-splitting
      changed.

    THE RESIDUAL, STATED EXACTLY. A label word mid-value with no column break after it, all in ONE
    cell, does split — measured:

        cells : ['Loan Program Conforming Fixed Term Loan']
        pairs : [('Loan Program', 'Conforming Fixed'), ('Term', 'Loan')]

    On text that cannot arise: `\\s{2,}` always puts the value in its own cell. It needs a PDF whose
    gutter detection merged a column pair, and a lender printing a label word mid-value. Left as is
    deliberately — the failure is LOUD (`Term` as a key is obviously wrong, and the review screen
    shows the header) rather than silent, and this file has been badly served by fixes aimed at
    cases nobody has seen. Three gap rules were already tried and each picked one level of a
    hierarchy; a fourth is not the answer.
    """
    out: list[tuple[str, str]] = []
    rest = cell.strip()
    while rest:
        opening = _LOAN_LABEL_PREFIX.match(rest)
        if opening is None:
            break
        label = opening.group(1)
        tail = rest[opening.end() :].strip()
        following = _LOAN_LABEL_ANYWHERE.search(tail)
        if following is None:
            out.append((label, tail))
            break
        out.append((label, tail[: following.start()].strip()))
        rest = tail[following.start() :]
    return out


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


#: Below this, a block's first-token positions are one column and nothing is a continuation.
#: Expressed in points and compared against the block's OWN spread, so it carries no font metric.
_MIN_COLUMN_SEPARATION_POINTS = 24.0

#: How much wider than a line's typical word gap a gap must be to count as a COLUMN GUTTER.
#: A multiple rather than a distance, so it means the same at any font size — measured on a UWM
#: loan-information line at 8pt Courier, word gaps cluster at ~48 points and gutters start at ~77,
#: so anything from about 1.3 upward separates them; 1.6 leaves margin on both sides.
_GUTTER_MULTIPLE = 1.6


def _shallow_threshold(lines: Sequence[Line]) -> float | None:
    """The x below which a PDF line starts at the margin rather than in the text column.

    ⚠️ DERIVED FROM THE SHEET, NEVER HARDCODED. On text input indentation IS the answer; on a PDF
    there are no leading spaces, only positions, and the positions depend on the lender's font. The
    structure that survives both is that a UWM conditions block has exactly TWO first-token columns —
    headings and row codes at the margin, continuations at the text column — so the split is the
    largest gap between consecutive first-token positions.

    Measured on `uwm_round1` rendered at Courier 8pt: headings and row starts at {54.0, 58.8},
    continuations at [260.4, 303.6]. The reader must not learn those numbers; it must find the gap.

    Returns None when there is no gap worth calling a column break — a block whose rows are all
    one-liners has no continuations, and inventing a threshold there would make the first slightly
    indented line a continuation of nothing.
    """
    starts = sorted({line.tokens[0].x0 for line in lines if line.tokens})
    if len(starts) < 2:
        return None

    gap, lower = max(((b - a, a) for a, b in itertools.pairwise(starts)), key=lambda pair: pair[0])
    if gap < _MIN_COLUMN_SEPARATION_POINTS:
        return None
    return lower + gap / 2.0


def _is_shallow(line: Line, threshold: float | None) -> bool:
    """Is this line at the margin (a heading or a row start) rather than a continuation?

    The one question both callers ask, answered from `indent` on text and from `x0` on a PDF, so the
    two inputs share a single rule instead of two that can drift.
    """
    indent = line.indent
    if indent is not None:
        return indent <= 3
    if not line.tokens:
        return False
    # No column break in this block means no continuations, so every line is at the margin.
    return threshold is None or line.tokens[0].x0 < threshold


def _is_continuation(line: Line, threshold: float | None) -> bool:
    """Does this line continue the row above it?

    ⚠️ THREE-WAY ON TEXT, NOT TWO, AND COLLAPSING IT WAS A REAL REGRESSION. The spec gives a heading
    at <= 3 spaces and a continuation at >= 20 — and the BAND BETWEEN THEM is neither, so it lands in
    `unassigned_lines`. That band is the §9.2 invariant's whole subject. An earlier version of this
    change answered both questions with one predicate (`not _is_shallow`), so a line at indent 10 was
    swallowed as a continuation and `test_unassigned_lines_are_collected_never_dropped` lost one of
    its two expected lines — the invariant quietly weakened by a refactor meant to extend it.

    On a PDF there is no middle band to preserve: a line either starts in the text column or it does
    not, because `lines_from_pdf` reports positions rather than leading spaces.
    """
    indent = line.indent
    if indent is not None:
        return indent >= 20
    return threshold is not None and bool(line.tokens) and line.tokens[0].x0 >= threshold


@dataclass(frozen=True)
class _RowStart:
    """A row's opening line, however it was recognised."""

    code: str
    category: str
    processor_assist: bool
    text: str


def _row_start(line: Line, threshold: float | None) -> _RowStart | None:
    """A row's opening line, read from spacing on text and from POSITIONS on a PDF.

    ⚠️ THE TEXT REGEX CANNOT BE USED ON A PDF, AND USING IT RETURNED AN EMPTY SHEET. `_ROW_START`
    requires `\\s{2,}` between the code, the category and the text; a PDF-built line is
    `" ".join(tokens)` and contains no run of two spaces anywhere. Measured on the same row:

        text:  ' 0006         Invoice                       Provide copy of invoice for credit...'
        pdf :  '0006 Invoice Provide copy of invoice for credit report.'

    The first matches, the second does not, so every row fell through to `unassigned_lines` and the
    sheet parsed to zero rows. This is the THIRD defect from one cause — the Champions header pairs
    and the UWM loan-fact scan were the others — so the rule is worth stating once, plainly:
    **on PDF input whitespace carries no information; only positions do.**

    The positional split needs no invented characters: the column threshold already separates the
    code and category (at the margin) from the text, which is the only boundary that matters.
    """
    if line.indent is not None:
        match = _ROW_START.match(line.text)
        if match is None:
            return None
        return _RowStart(
            code=match.group(1),
            category=match.group(3).strip(),
            processor_assist=match.group(2) is not None,
            text=match.group(4).strip(),
        )

    tokens = line.tokens
    if not tokens or not _CODE.match(tokens[0].text):
        return None

    # ⚠️ THE CODE MUST BE AT THE MARGIN, AND DROPPING THIS SPLIT A ROW IN TWO. `_ROW_START` anchors
    # at `^\s{0,3}`, so on text a four-digit number deep inside a wrapped line can never open a row.
    # Translating to positions lost that anchor, and `4235`'s continuation — which begins
    # `2026 and 2025 for Jordan Ellis...` — was read as a row start: a YEAR in the text column, four
    # digits long. The page-break sheet returned 17 rows instead of 16 with `4235` truncated to its
    # first line. The margin test is what `^\s{0,3}` means in a world of columns.
    if not _is_shallow(line, threshold):
        return None

    rest = list(tokens[1:])
    processor_assist = bool(rest) and rest[0].text == "(PA)"
    if processor_assist:
        rest = rest[1:]
    if len(rest) < 2:
        return None

    # ⚠️ TWO DIFFERENT QUESTIONS, AND CONFLATING THEM LOST EVERY ROW ON A SHEET WITH NO WRAPPED
    # TEXT. The block threshold answers "where does a CONTINUATION start" — a property of FIRST
    # tokens across the block. This needs "where does the TEXT start inside THIS row" — a property
    # of the tokens within one line. A block whose rows all fit on one line has no answer to the
    # first and a perfectly good answer to the second, and returning None when `threshold is None`
    # meant two well-formed rows parsed to nothing: `rows: []`, both lines in `unassigned_lines`.
    #
    # So the boundary falls back to the widest gap inside the row. For
    # `0006 Invoice Provide copy of invoice...` the gaps are ~47 (code→category), ~72
    # (category→text) and ~10-30 (between words), so it lands on `Provide` and the category is
    # `Invoice`. Computed inline rather than as a helper, to avoid importing `Token` for one
    # annotation — three missing imports today came from exactly that habit.
    boundary = threshold
    if boundary is None:
        widest, at = max(
            ((b.x0 - a.x0, b.x0) for a, b in itertools.pairwise(rest)),
            key=lambda pair: pair[0],
        )
        boundary = at if widest >= _MIN_COLUMN_SEPARATION_POINTS else None

    if boundary is None:
        return None
    text = [token for token in rest if token.x0 >= boundary]
    if not text:
        # A four-digit token with nothing in the text column is not a row start — it is a figure
        # inside somebody else's sentence.
        return None
    return _RowStart(
        code=tokens[0].text,
        category=" ".join(token.text for token in rest if token.x0 < boundary),
        processor_assist=processor_assist,
        text=" ".join(token.text for token in text),
    )


def _is_heading(line: Line, threshold: float | None = None) -> bool:
    """A heading sits at the margin, carries no leading 4-digit code, and matches the pattern.

    ⚠️ ANSWERING `False` FOR EVERY PDF LINE WAS A REAL DEFECT, and it is what this replaced. `indent`
    is None for PDF-built lines, so `indent is None or indent > 3` made this False for every line of
    every uploaded sheet — and the caller's next branch treats "not shallow" as a continuation, so
    each bucket heading was silently glued onto the preceding condition's text. Row starts still
    matched, so the sheet produced the right NUMBER of rows, all filed under a stale bucket, one
    carrying words the lender never wrote.
    """
    if not _is_shallow(line, threshold):
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


def _cells(line: Line) -> list[str]:
    """One line split into its printed COLUMNS, from whichever signal the input carries.

    ⚠️ THE ONE PLACE THE TWO INPUTS' UNITS ARE RECONCILED. A UWM header or loan-information line is a
    row of cells: `Note Rate | 6.374% | Compensation Type | Lender Paid`. On text the gutter is a run
    of spaces; on a PDF it is a horizontal gap in points, and `" ".join(tokens)` has destroyed the
    run of spaces entirely. Every defect in this file's history has come from applying one unit's
    constant to the other's input — a `\\s{2,}` scan that matched nothing on a PDF, an `indent`
    that was always None, a tolerance of "8" that meant characters here and points there.

    So the gutter is detected per input and everything downstream works on cells, which have no
    units at all.
    """
    if line.indent is not None:
        return [cell for cell in re.split(r"\s{2,}", line.text.strip()) if cell]

    gaps = [b.x0 - a.x0 for a, b in itertools.pairwise(line.tokens)]
    if not gaps:
        return [line.text.strip()] if line.text.strip() else []

    # ⚠️ THE GUTTER IS DERIVED FROM THIS LINE, NOT FROM A CONSTANT, and a constant got it wrong in
    # exactly the way this file keeps getting things wrong. `_MIN_COLUMN_SEPARATION_POINTS` (24.0)
    # is calibrated for the gap between a row CODE and its TEXT; inside a loan-information line at
    # 8pt Courier, ordinary word gaps measure 38-53 points, so every word became its own cell and
    # `AUS: Desktop Underwriter` came back as `AUS: Desktop`.
    #
    # Measured on that line: word gaps 38.4-52.8 (median 48.0), gutters 76.8-158.4. Two clean
    # populations, ~24 points apart, and the boundary between them is a property of the line's own
    # typesetting. A multiple of the median splits them at any font size — which is what the text
    # path gets for free, because there a gutter IS two-or-more spaces.
    typical = statistics.median(gaps)
    gutter = typical * _GUTTER_MULTIPLE

    out: list[list[str]] = [[line.tokens[0].text]]
    for gap, token in zip(gaps, line.tokens[1:], strict=True):
        if gap >= gutter:
            out.append([token.text])
        else:
            out[-1].append(token.text)
    return [" ".join(cell) for cell in out]


def _split_header(lines: Sequence[Line]) -> tuple[dict[str, object], date | None, list[str]]:
    """Rule 1: `Label:  value` pairs, up to two per line, from the title to `LOAN INFORMATION`."""
    team: list[dict[str, object]] = []
    broker: dict[str, str] = {}
    printed: date | None = None
    warnings: list[str] = []

    # ⚠️ A CLOSED-SET SCAN, NOT A GENERIC `Label:` PATTERN. The generic form needed `:\s{2,}` to know
    # where a value ended, and PDF text joins tokens with SINGLE spaces — so on an uploaded sheet it
    # matched nothing and `Date Printed` was lost, which in turn left every underwriter note
    # dateless, because rule 4 resolves a note's year against `date_printed`.
    #
    # Relaxing the generic pattern to `\s+` would be ambiguous: with single spaces, "Contact Name:
    # Priya Raman Senior UW: Dana Okafor" gives no way to tell where the first value stops. Matching
    # a KNOWN label instead bounds each value by the start of the next one, which is what the
    # Champions header already does for the same reason.
    pairs = re.compile(
        r"("
        + "|".join(
            re.escape(label)
            for label in sorted(
                (*_TEAM_LABELS, *_BROKER_LABELS, "Date Printed"), key=len, reverse=True
            )
        )
        + r"):"
    )
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
        # ⚠️ SLICED BETWEEN MATCHES, NOT `findall` PAIRS. The scan above captures the LABEL only, so
        # a value runs from the end of its own label to the start of the next one — which is what
        # bounds it now that a single space no longer separates columns.
        matches = list(pairs.finditer(line.text))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(line.text)
            label = match.group(1).strip()
            value = line.text[match.end() : end].strip()
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

        # ⚠️ A LABEL COUNTS ONLY AT THE START OF A CELL. `Property  118 Status Road` is two cells,
        # and `Status` sits mid-cell in the second — so it is a street name, not a field. Scanning
        # the whole line instead lost the `Property` key entirely to a word inside its own value.
        cells = _cells(line)
        labelled: list[tuple[str, str]] = []
        for index, cell in enumerate(cells):
            pairs = _pairs_in_cell(cell)
            if not pairs:
                continue
            for label, value in pairs[:-1]:
                if value:
                    labelled.append((label, value))
            # A label whose value is empty takes the NEXT cell, which is how the wide two-column
            # rows print: `Note Rate | 6.374%`. Only the LAST pair in a cell can be open-ended.
            label, value = pairs[-1]
            if not value and index + 1 < len(cells) and not _pairs_in_cell(cells[index + 1]):
                value = cells[index + 1].strip()
            if value:
                labelled.append((label, value))

        if not labelled:
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
        for label, value in labelled:
            if value:
                facts[label] = value
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

    # ⚠️ DERIVED FROM THIS SHEET'S OWN COLUMN SPACING, so it carries no unit. The spec's "8" is
    # eight CHARACTERS; the same 8 applied to a PDF is eight POINTS — under two characters at 8pt —
    # and three of round 1's six dates were rejected as "19 from the nearest column" when 19 points
    # is about four characters. A fraction of the narrowest gap between adjacent headers means the
    # same thing in both units: nearer to this column than to its neighbour, with a margin.
    ordered = sorted(x for x, _ in columns)
    spacing = min((b - a for a, b in itertools.pairwise(ordered)), default=0.0)
    tolerance = spacing * _NEAREST_COLUMN_FRACTION if spacing else 8.0

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
        if distance > tolerance:
            warnings.append(
                f"expiry date {token.text} is {distance:.0f} from the nearest column "
                f"({nearest[1]}); not assigned"
            )
            continue
        dates[nearest[1]] = parsed
    return dates, warnings


#: How many row starts a marker-less paste must carry before it is read as a UWM excerpt. Two,
#: because ONE four-digit number followed by two columns occurs in ordinary prose — a year, an
#: amount, a figure inside somebody else's sentence, all of which this reader has already been
#: caught by once. Two of them on separate lines is a list. Measured on the round-2 conditions
#: block: 6 row starts in 15 lines.
_MIN_PASTED_ROW_STARTS = 2


def uwm_block_start(lines: Sequence[Line]) -> int | None:
    """Where the conditions block begins in text carrying no `CONDITIONS` marker, or ``None``.

    ⚠️ A PROCESSOR COPYING FROM THE PORTAL COPIES THE ROWS, NOT THE WORD ABOVE THEM — so the marker
    `read_uwm` bounds its block with is precisely what a paste loses. This answers the same question
    from the rows themselves, and LP-907's paste reader hands the answer back as `conditions_from`.

    THE TEST IS THIS READER'S OWN ROW RULE, not a looser "does that look like a code" regex. What
    `_row_start` accepts is what the block will actually parse into rows, so a paste can never be
    recognised as UWM and then read as nothing — the two decisions cannot disagree because they are
    the same decision.
    """
    content = [line for line in lines if not line.is_blank]
    if not content:
        return None
    threshold = _shallow_threshold(content)
    starts = sum(1 for line in content if _row_start(line, threshold) is not None)
    # Zero, because the block IS the whole paste: anything above the first row — a heading the
    # processor copied with it, a stray portal line — is read by the same rules and ends up as a
    # bucket heading or in `unassigned_lines`. Nothing is dropped for having been copied too (§9.2).
    return 0 if starts >= _MIN_PASTED_ROW_STARTS else None


def read_uwm(lines: Sequence[Line], *, conditions_from: int | None = None) -> ParsedSheet:
    """Read a UWM approval letter into a `ParsedSheet` (spec §6 rules 1-8).

    `conditions_from` is for text that has NO `CONDITIONS` marker — a paste of the rows alone. It
    says where the conditions block starts and is ignored when the marker is present. Only LP-907's
    paste reader passes it, and only once `uwm_block_start` has established that the rows are there;
    a caller that guessed would simply get the marker-less refusal below.
    """
    sheet = ParsedSheet(sheet_format=ConditionSheetFormat.UWM_APPROVAL_LETTER)

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

    if conditions_at is not None:
        block_start = conditions_at + 1
    elif conditions_from is not None:
        block_start = conditions_from
    else:
        sheet.warnings.append("no CONDITIONS marker; nothing could be read")
        sheet.needs_ai = True
        return sheet

    # ⚠️ A MISSING HEADER IS A WARNING, NOT A FAILURE. The page-break fixture omits it entirely, and
    # the conditions are the part that matters — refusing the sheet because its letterhead is absent
    # would discard every condition on it.
    #
    # ⚠️ BUT AN EXCERPT IS NOT WARNED ABOUT, because there the absence is the input's shape rather
    # than a finding. A paste of the rows alone HAS no letterhead, and warning would put "header not
    # found" on every pasted round — a warning that is always present is one a processor learns to
    # skip, including on the sheet where it means something.
    if loan_at is not None and conditions_at is not None:
        header, printed, header_warnings = _split_header(lines[1:loan_at])
        facts, fact_warnings = _split_loan_facts(lines[loan_at + 1 : conditions_at])
        header["loan_facts"] = facts
        sheet.header = header
        sheet.date_printed = printed
        sheet.warnings.extend(header_warnings)
        sheet.warnings.extend(fact_warnings)
    elif conditions_at is not None:
        sheet.warnings.append("header not found")

    block_end = expiry_at if expiry_at is not None else len(lines)
    # Computed over the CONDITIONS BLOCK ONLY. The header and the loan-information table have their
    # own column structure — a two-column header would contribute a gap of its own and move the
    # split — so the threshold is derived from the lines it will actually be applied to.
    threshold = _shallow_threshold(
        [line for line in lines[block_start:block_end] if not line.is_blank]
    )
    rows: list[_Row] = []
    current: _Row | None = None
    heading, kind = "", BucketKind.UNKNOWN

    for offset, line in enumerate(lines[block_start:block_end], start=block_start):
        if line.is_blank:
            continue

        if _MORTGAGEE in line.text:
            if sheet.mortgagee_clause is None:
                sheet.mortgagee_clause = line.text.split(_MORTGAGEE, 1)[1].strip()
            current = None
            continue

        if (start := _row_start(line, threshold)) is not None:
            current = _Row(
                code=start.code,
                category=start.category,
                processor_assist=start.processor_assist,
                heading=heading,
                kind=kind,
                parts=[start.text],
                lines=[offset],
            )
            rows.append(current)
            continue

        if _is_heading(line, threshold):
            heading, unknown = line.text.strip(), False
            kind, unknown = _heading_kind(heading)
            if unknown:
                sheet.warnings.append(f"unrecognised bucket heading: {heading!r}")
            current = None
            continue

        # Not a row start, not a heading, not an artifact. A continuation is a POSITIVE test — a
        # deep indent on text, the text column on a PDF — never "whatever is left", because the
        # band between a heading and a continuation belongs in `unassigned_lines`.
        if current is not None and _is_continuation(line, threshold):
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
