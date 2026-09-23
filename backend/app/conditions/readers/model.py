"""What a reader returns (LP-906).

Plain dataclasses, not Pydantic and not ORM rows. A reader is a pure function over lines: it does not
know what a database is, and keeping its output a dataclass is what makes the whole of LP-906
testable against a fixture with no session, no migration and no network.

THE ENUMS COME FROM `app.models.condition*` RATHER THAN BEING REDECLARED. The spec's `ParsedSheet`
sketch names a type `SheetFormat`, which appears exactly once in the spec and nowhere in the code —
LP-904 already defined `ConditionSheetFormat` with the four values the readers produce. A second name
for one fact is the drift this codebase warns about repeatedly (`_ROW_RULE`, `str_enum`, the two
`activity_type` swaps), so the readers import the model's enums and the difference is recorded in the
ticket. Importing an enum from `models` costs nothing: it is a vocabulary, not a row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.models.condition import BucketKind, OwnerHint, OwnerHintSource
from app.models.condition_round import ConditionSheetFormat

#: A rule-read row is certain: the layout said so. LP-908's AI split uses 0.6, and the review screen
#: sorts anything under 0.8 first and demands the flagged-rows checkbox before import.
RULE_CONFIDENCE = 1.0
#: A row whose segment failed the Champions centre-rule check — read, but not trusted.
UNCERTAIN_CONFIDENCE = 0.5


@dataclass(frozen=True)
class UnderwriterNote:
    """A dated note the underwriter appended INSIDE the condition's text.

    `**8/28 Not in Upload` means the condition came back. The spec does not define this type and the
    `ParsedRow` sketch only says "date + text", so it is defined here.

    THE DATE IS RESOLVED, NOT RAW. The sheet prints `8/28` with no year, so the reader resolves it
    against the sheet's own printed date — and takes the PRECEDING year when that would otherwise put
    the note in the future, because a note dated after the letter it appears on is impossible.
    """

    date: date | None
    text: str


@dataclass
class ParsedRow:
    """One condition as the layout gave it up. Not yet a `Condition` — that is LP-909's import.

    `verbatim_text` KEEPS the underwriter notes: the lender wrote one string, and a UI that showed a
    note as ours would misattribute it. The fingerprint (computed at import) excludes them, so a
    condition that comes back with a new note still matches as the same condition.
    """

    sequence: int
    lender_code: str | None
    lender_category: str | None
    bucket_heading: str
    bucket_kind: BucketKind
    verbatim_text: str
    underwriter_notes: list[UnderwriterNote] = field(default_factory=list)
    owner_hint: OwnerHint = OwnerHint.UNKNOWN
    owner_hint_source: OwnerHintSource = OwnerHintSource.NONE
    processor_assist: bool = False
    confidence: float = RULE_CONFIDENCE
    #: Which input lines produced this row. Carried so a review screen can point at the source, and
    #: so a warning can name a position rather than a row number nobody can locate.
    source_line_numbers: list[int] = field(default_factory=list)
    #: Champions only: the row's text continued onto the next page and was reassembled.
    crossed_page: bool = False


@dataclass
class ParsedSheet:
    """Everything one read produced, including what it could not place.

    ⚠️ `unassigned_lines` IS THE INVARIANT THIS WHOLE TICKET TURNS ON (spec §9.2). Every non-blank
    line inside the conditions block becomes part of a row, a bucket heading, a known artifact, or an
    entry here. Nothing is silently dropped — the review screen shows these, and each gets "Add as a
    condition" or "Ignore this line". A reader that quietly discarded a line it did not understand
    would lose a lender's demand with nothing on screen to say so.
    """

    sheet_format: ConditionSheetFormat
    date_printed: date | None = None
    header: dict[str, object] = field(default_factory=dict)
    expiry_dates: dict[str, date | None] = field(default_factory=dict)
    mortgagee_clause: str | None = None
    rows: list[ParsedRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unassigned_lines: list[str] = field(default_factory=list)
    duplicates_dropped: int = 0
    #: True → the rules could not split this text and LP-908 must. Never set merely because a read
    #: was imperfect: a sheet with warnings is still a rule-read sheet.
    needs_ai: bool = False
