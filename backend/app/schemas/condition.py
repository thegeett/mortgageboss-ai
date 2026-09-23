"""Condition schemas (LP-904 shapes; LP-905/907/909 use them).

The read schemas are what the Conditions tab renders. Two rules shape them, both from Stage 0:

* **The lender's wording is carried verbatim and never paraphrased** (ADR-405, spec §9.1). It is
  rendered in serif because it is quoted from a document, and the API is the last place it could be
  quietly "tidied".
* **No status control exists in Stage 1** (ADR-404). `prep_status` and `lender_status` are
  deliberately ABSENT from `ConditionPublic`: they are created with defaults in LP-904 and nothing
  moves them, so exposing them would invite a UI that implies otherwise. They arrive in Stage 2 with
  the moves that earn them.

`draft_rows` is a parse result awaiting review, not a condition. It is modelled as its own schema
rather than reusing `ConditionPublic` because the two differ in the way that matters: a draft row has
a confidence and the source line numbers it came from, and no identity of its own until import.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.condition import (
    BucketKind,
    Condition,
    ConditionOrigin,
    OwnerHint,
    OwnerHintSource,
)
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
    ConditionSheetFormat,
    ConditionSourceKind,
)

#: The paste endpoint's ceiling (spec §LP-907). Enforced here so an oversized body is refused before
#: it reaches a reader, rather than after.
MAX_PASTE_CHARS = 100_000


class UnderwriterNotePublic(BaseModel):
    """A dated note the underwriter appended inside the condition's text.

    Carried as structure AND left inside `verbatim_text`, deliberately: the lender wrote one string,
    and a UI that showed the note as though it were ours would misattribute it. The structure is what
    lets the review screen render it as a dated chip beside the wording rather than inside it.
    """

    model_config = ConfigDict(from_attributes=True)

    date: date | None = None
    text: str
    first_seen_round_id: UUID | None = None


class ConditionSourcePublic(BaseModel):
    """One way a round arrived. A round has a list because a paste can be enriched by its PDF."""

    model_config = ConfigDict(from_attributes=True)

    kind: ConditionSourceKind
    at: datetime | None = None
    document_id: UUID | None = None
    inbound_attachment_id: UUID | None = None
    user_id: UUID | None = None


class ParseReportPublic(BaseModel):
    """What the reader did — the honest record of a parse, including what it could not place.

    `unassigned_lines` is the invariant spec §9.2 exists for: every non-blank line in the conditions
    block becomes a row, a heading, a known artifact, or an entry here. Nothing is silently dropped,
    and the review screen shows these so a processor can add or ignore each one.
    """

    model_config = ConfigDict(from_attributes=True)

    reader: str | None = None
    reader_version: str | None = None
    warnings: list[str] = Field(default_factory=list)
    unassigned_lines: list[str] = Field(default_factory=list)
    duplicates_dropped: int = 0
    ai_used: bool = False
    #: Set only on PARSE_FAILED — the typed reason, never a bare exception string (spec §9.8).
    failure_kind: str | None = None
    failure_detail: str | None = None


class DraftRowPublic(BaseModel):
    """One parsed row awaiting review. Not yet a condition — it has no identity until import."""

    model_config = ConfigDict(from_attributes=True)

    sequence: int
    lender_code: str | None = None
    lender_category: str | None = None
    bucket_heading: str
    bucket_kind: BucketKind
    verbatim_text: str
    underwriter_notes: list[UnderwriterNotePublic] = Field(default_factory=list)
    owner_hint: OwnerHint = OwnerHint.UNKNOWN
    owner_hint_source: OwnerHintSource = OwnerHintSource.NONE
    processor_assist: bool = False
    #: 1.0 for a row the rules read; 0.6 for an AI split (LP-908). The review screen sorts anything
    #: below 0.8 first and requires the flagged-rows checkbox before import.
    confidence: float = 1.0
    source_line_numbers: list[int] = Field(default_factory=list)


class ConditionPublic(BaseModel):
    """One imported condition, as the list renders it.

    NO STATUS FIELDS — see the module docstring. `round_numbers` is what drives the `R1 R2` chips:
    every round this condition appeared on, derived from its CONDITION_CREATED / CONDITION_SEEN_AGAIN
    events.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lender_code: str | None
    lender_category: str | None
    bucket_heading: str
    bucket_kind: BucketKind
    #: The lender's words. Rendered in serif; never paraphrased anywhere in the stack.
    verbatim_text: str
    underwriter_notes: list[UnderwriterNotePublic] = Field(default_factory=list)
    owner_hint: OwnerHint
    owner_hint_source: OwnerHintSource
    info_only: bool
    canonical_type_id: str | None
    origin: ConditionOrigin
    sequence: int
    first_round_id: UUID
    last_seen_round_id: UUID
    round_numbers: list[int] = Field(default_factory=list)
    created_at: datetime

    @classmethod
    def from_model(
        cls, condition: Condition, *, round_numbers: list[int] | None = None
    ) -> "ConditionPublic":
        """Build the public view. `round_numbers` is supplied by the caller, which reads the events
        for the whole list in one query rather than per row."""
        return cls(
            id=condition.id,
            lender_code=condition.lender_code,
            lender_category=condition.lender_category,
            bucket_heading=condition.bucket_heading,
            bucket_kind=condition.bucket_kind,
            verbatim_text=condition.verbatim_text,
            underwriter_notes=[
                UnderwriterNotePublic.model_validate(note)
                for note in (condition.underwriter_notes or [])
            ],
            owner_hint=condition.owner_hint,
            owner_hint_source=condition.owner_hint_source,
            info_only=condition.info_only,
            canonical_type_id=condition.canonical_type_id,
            origin=condition.origin,
            sequence=condition.sequence,
            first_round_id=condition.first_round_id,
            last_seen_round_id=condition.last_seen_round_id,
            round_numbers=round_numbers or [],
            created_at=condition.created_at,
        )


class ConditionRoundPublic(BaseModel):
    """One round, for the round strip and the review screen."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    round_number: int | None
    status: ConditionRoundStatus
    completeness: ConditionRoundCompleteness
    sheet_format: ConditionSheetFormat
    sources: list[ConditionSourcePublic] = Field(default_factory=list)
    date_printed: date | None
    round_date: date
    expiry_dates: dict[str, Any] | None = None
    #: Present on a DRAFT and cleared on import — the review screen's rows.
    draft_rows: list[DraftRowPublic] | None = None
    parse_report: ParseReportPublic = Field(default_factory=ParseReportPublic)
    #: The letter's own details, shown in the side panel and the round-details sheet. Absent for a
    #: paste, which has no letter — the panel then says so rather than rendering empty fields.
    header: dict[str, Any] | None = None
    condition_count: int = 0
    created_at: datetime

    @classmethod
    def from_model(
        cls, round_: ConditionRound, *, condition_count: int = 0
    ) -> "ConditionRoundPublic":
        return cls(
            id=round_.id,
            round_number=round_.round_number,
            status=round_.status,
            completeness=round_.completeness,
            sheet_format=round_.sheet_format,
            sources=[ConditionSourcePublic.model_validate(s) for s in (round_.sources or [])],
            date_printed=round_.date_printed,
            round_date=round_.round_date,
            expiry_dates=round_.expiry_dates,
            draft_rows=(
                [DraftRowPublic.model_validate(r) for r in round_.draft_rows]
                if round_.draft_rows is not None
                else None
            ),
            parse_report=ParseReportPublic.model_validate(round_.parse_report or {}),
            header=round_.header,
            condition_count=condition_count,
            created_at=round_.created_at,
        )


# --------------------------------------------------------------------------- #
# Write bodies
# --------------------------------------------------------------------------- #


class ConditionPasteRequest(BaseModel):
    """Paste conditions copied from a lender portal (LP-907).

    `completeness` is REQUIRED and has no default here on purpose. The UI defaults the control to
    "just some" — the answer that can never remove anything — but the API refusing to guess is what
    makes that a decision rather than a fallback (ADR-404).
    """

    text: str = Field(min_length=1, max_length=MAX_PASTE_CHARS)
    completeness: ConditionRoundCompleteness
    round_date: date | None = None


class ConditionDraftUpdate(BaseModel):
    """Replace a draft round's rows before import (LP-909).

    Optimistic concurrency: the caller sends the `updated_at` it read, and a mismatch is refused
    rather than silently overwriting another tab's edit.
    """

    draft_rows: list[DraftRowPublic]
    completeness: ConditionRoundCompleteness | None = None
    round_date: date | None = None
    expected_updated_at: datetime | None = None


class ConditionCreateRequest(BaseModel):
    """Add one condition by hand (LP-909, screen S1-12).

    The wording is required and is stored exactly as typed — the dialog's hint says "Type it exactly
    as the lender wrote it", and this is the boundary that honours it.
    """

    verbatim_text: str = Field(min_length=1, max_length=20_000)
    lender_code: str | None = Field(default=None, max_length=16)
    lender_category: str | None = Field(default=None, max_length=256)
    bucket_heading: str | None = Field(default=None, max_length=256)
    bucket_kind: BucketKind = BucketKind.UNKNOWN


class ConditionImportResult(BaseModel):
    """What an import did, for the toast and the timeline entry.

    `seen_again` never implies anything was closed: a condition missing from a new sheet is simply
    not touched in Stage 1.
    """

    round_id: UUID
    round_number: int
    created: int
    seen_again: int
    unmapped_codes: list[str] = Field(default_factory=list)
