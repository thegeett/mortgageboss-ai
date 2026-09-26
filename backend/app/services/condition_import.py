"""Turning a reviewed draft round into conditions (LP-909 section 2, spec §LP-909).

⚠️ THIS IS THE MOMENT A PARSE BECOMES THE FILE'S RECORD. Before it, `draft_rows` is a reading of a
sheet that a processor may edit or throw away; after it, each row is a `Condition` the rest of the
product reasons about. LP-904 kept the two apart for exactly this reason: "an unreviewed parse must
not be indistinguishable from the lender's confirmed list".

WHAT IMPORT MAY NOT DO (ADR-404, spec §LP-909 step 3). It never changes `prep_status` or
`lender_status`, never deletes, never clears. A condition missing from a new sheet is simply NOT
TOUCHED — Stage 2 compares rounds and proposes "probably cleared"; Stage 1 has no opinion. The event
vocabulary enforces this by omission: `ConditionEventKind` has no `CONDITION_CLEARED` and no
`CONDITION_REMOVED`, because "an enum member nothing writes is an invitation".

THE TWO-PASS MATCH IS THE ORDER LP-904 INDEXED FOR. `(loan_file_id, lender_id, lender_code)` then
`(loan_file_id, text_fingerprint)` — the model's own comment calls them "the two lookups import does,
in the order it does them". Code first because a lender's code is the strongest identity it gives us;
fingerprint second because a re-worded row keeps its code while a re-coded row keeps its words.

⚠️ EVERY WRITER OF A `Condition` EMITS `CONDITION_CREATED`. That rule is stated here because this is
one of the three writers, and because breaking it is not hypothetical: `condition_enrich.py` created
conditions and emitted nothing, so those conditions had no round chips while their own NOT NULL
`first_round_id` pointed straight at the round that made them. A read side deriving a fact from
events is only as good as its enumeration of the writers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.conditions.fingerprint import fingerprint
from app.conditions.lender_codes.status import resolved_status
from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.condition import BucketKind, Condition, ConditionOrigin, OwnerHint, OwnerHintSource
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import (
    ConditionRound,
    ConditionRoundCompleteness,
    ConditionRoundStatus,
    ConditionSourceKind,
)
from app.models.helpers import only_active
from app.models.lender_condition_code import LenderCodeStatus, LenderConditionCode
from app.models.loan_file import LoanFile
from app.schemas.condition import ConditionCreateRequest, DraftRowPublic
from app.services.activity_log import log_activity

logger = structlog.get_logger(__name__)

#: ⚠️ A BOUND, NOT "UNTIL IT WORKS". `max + 1` recomputed under contention can lose twice, so a
#: bare loop is unbounded in principle — and it would be holding a Redis lock that auto-expires at
#: 30 seconds anyway, so "keep trying" is a promise the surrounding machinery cannot keep. Three
#: attempts, then a typed failure a processor can act on.
MAX_NUMBER_ATTEMPTS = 3

#: The index that actually enforces one round number per file (LP-904). Named because a retry that
#: caught every `IntegrityError` would silently swallow a NOT NULL violation or a foreign key and
#: retry a write that can never succeed.
_ROUND_NUMBER_INDEX = "uq_condition_rounds_file_number"

#: The one status a round may be imported from. DRAFT is "read, awaiting the processor's review".
_IMPORTABLE = ConditionRoundStatus.DRAFT


class RoundNotImportable(Exception):
    """The round cannot be imported, with the reason a processor can act on."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class ImportOutcome:
    """What the import did — the toast, the timeline entry, and `ConditionImportResult`."""

    round_number: int
    created: int = 0
    seen_again: int = 0
    #: `(lender, code)` pairs this sheet carried that the map has no meaning for. Recorded as
    #: `OBSERVED_UNMAPPED` so the backlog grows from what lenders actually send.
    unmapped_codes: list[str] = field(default_factory=list)


async def _next_round_number(db: AsyncSession, *, loan_file_id: UUID) -> int:
    """One past the highest number this file has used.

    ⚠️ READS ACROSS SOFT-DELETED AND DISCARDED ROUNDS ALIKE, deliberately, because the unique index
    does not: it is `WHERE round_number IS NOT NULL AND deleted_at IS NULL`. Taking `max` over only
    the rows the index constrains would hand back a number a soft-deleted round still displays in
    an append-only `ROUND_IMPORTED` event — two different sheets both recorded as "round 2", which
    is precisely what LP-904's migration argues against when it keeps DISCARDED rounds in the index.
    """
    highest = await db.scalar(
        select(func.max(ConditionRound.round_number)).where(
            ConditionRound.loan_file_id == loan_file_id
        )
    )
    return int(highest or 0) + 1


def _row_fingerprint(row: dict[str, Any]) -> str:
    text = row.get("verbatim_text")
    return fingerprint(text if isinstance(text, str) else "")


async def _existing_conditions(db: AsyncSession, *, loan_file_id: UUID) -> list[Condition]:
    """Every live condition on the file, oldest first.

    ⚠️ THE ORDER IS LOAD-BEARING AND THERE WAS NONE. Two conditions can legitimately share
    `(lender_id, lender_code)` — that is exactly what `possible_match` exists for, since a
    same-code/different-wording row creates a second condition under the same code. The lookup below
    keeps the FIRST of them, so without an `ORDER BY` "which one" was whatever the planner happened
    to return, and `possible_match` pointed at a different condition from run to run. Oldest first
    makes it the original, which is the one Stage 2's comparison wants to be told about.

    NOT filtered by lender, deliberately: a condition recorded before the file's lender was known
    carries `lender_id = None` and must still be reachable — see `_lender_compatible`.
    """
    stmt = select(Condition).where(Condition.loan_file_id == loan_file_id)
    stmt = only_active(stmt, Condition).order_by(Condition.created_at, Condition.id)
    return list((await db.execute(stmt)).scalars().all())


def _lender_compatible(condition: Condition, lender_id: UUID | None) -> bool:
    """Whether this condition and this round could belong to the same lender.

    ⚠️ `None` MEANS "NOT KNOWN YET", NEVER "A DIFFERENT LENDER", and collapsing those two is what
    made the wording pass wrong. `loan_file.lender_id` is nullable and mutable, and a round takes the
    FILE's lender, so a file legitimately accumulates conditions under `None` and later gains one.
    Refusing to match across `None` would duplicate the same demand the moment the lender was set —
    the exact failure the fingerprint pass exists to prevent.

    Two DIFFERENT known lenders are a different matter and do not match. Spec §LP-909 step 2 scopes
    the search to "the same file **and lender**", and that clause governs both passes.
    """
    return condition.lender_id is None or lender_id is None or condition.lender_id == lender_id


def _first_compatible(
    candidates: list[Condition] | None, lender_id: UUID | None
) -> Condition | None:
    """The oldest condition with this wording that could belong to this lender."""
    for candidate in candidates or []:
        if _lender_compatible(candidate, lender_id):
            return candidate
    return None


def _match(
    row: dict[str, Any],
    *,
    by_code: dict[tuple[UUID | None, str], Condition],
    by_text: dict[str, list[Condition]],
    lender_id: UUID | None,
) -> tuple[Condition | None, Condition | None]:
    """The spec's two passes. Returns `(match, possible_match)`.

    ⚠️ BOTH PASSES ARE LENDER-SCOPED, AND THE SECOND ONE WAS NOT. `by_code` is keyed
    `(lender_id, code)` so pass 1 was scoped by construction; `by_text` was keyed on the fingerprint
    alone, so a condition belonging to lender A matched a sheet from lender B whenever the wording
    was identical — silently, with no warning, recording lender A's condition as having appeared on
    lender B's round. Measured on two lenders sharing one file (review): `created=0 seen_again=1`.

    Worse, the same import disagreed with itself three ways: the code map recorded `(lender B, code)`
    as a brand-new OBSERVED_UNMAPPED entry in the very transaction where this pass declared the
    condition identical. Pass 1 lender-specific, code map lender-specific, pass 2 lender-agnostic.

    ⚠️ `possible_match` IS AN ID FOR STAGE 2, NOT A DECISION HERE. A condition with the SAME code and
    a DIFFERENT fingerprint is either a re-worded demand or a different demand the lender happened to
    file under one template — and Stage 1 cannot tell which. Recording the id in the event detail
    lets Stage 2's comparison decide "reworded"; guessing now would either merge two real conditions
    or duplicate one, silently.
    """
    code = row.get("lender_code")
    text_print = _row_fingerprint(row)
    by_wording = _first_compatible(by_text.get(text_print), lender_id)

    if isinstance(code, str) and code:
        exact = by_code.get((lender_id, code))
        if exact is not None and exact.text_fingerprint == text_print:
            return exact, None
        # Same code, different words: not a match, but worth naming.
        if exact is not None:
            return by_wording, exact

    return by_wording, None


# --------------------------------------------------------------------------- #
# Underwriter notes
# --------------------------------------------------------------------------- #


def _note_key(note: dict[str, Any]) -> tuple[str | None, str]:
    """A note's identity: the date it carries and its text.

    Not the whole dict, because `first_seen_round_id` is OURS — stamped when we first saw the note —
    so comparing it would make every note look new on the round after the one that recorded it.
    """
    raw_date = note.get("date")
    return (raw_date if isinstance(raw_date, str) else None, str(note.get("text") or ""))


def _notes_from_row(row: dict[str, Any], *, round_id: UUID) -> list[dict[str, Any]]:
    """The row's notes, each stamped with the round it was first seen on."""
    notes: list[dict[str, Any]] = []
    for raw in row.get("underwriter_notes") or []:
        if not isinstance(raw, dict):
            continue
        note = dict(raw)
        if not note.get("first_seen_round_id"):
            note["first_seen_round_id"] = str(round_id)
        notes.append(note)
    return notes


def _new_notes(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    seen = {_note_key(note) for note in existing if isinstance(note, dict)}
    return [note for note in incoming if _note_key(note) not in seen]


# --------------------------------------------------------------------------- #
# The lender code map (spec step 4)
# --------------------------------------------------------------------------- #


def _codes_on_sheet(rows: list[dict[str, Any]]) -> list[str]:
    """Distinct codes, in sheet order. Order matters only so the upsert is deterministic."""
    ordered: list[str] = []
    for row in rows:
        code = row.get("lender_code")
        if isinstance(code, str) and code and code not in ordered:
            ordered.append(code)
    return ordered


async def _load_code_map(
    db: AsyncSession, *, lender_id: UUID, codes: list[str]
) -> dict[str, LenderConditionCode]:
    if not codes:
        return {}
    rows = await db.scalars(
        select(LenderConditionCode).where(
            LenderConditionCode.lender_id == lender_id,
            LenderConditionCode.code.in_(codes),
        )
    )
    return {row.code: row for row in rows}


async def _record_codes(
    db: AsyncSession,
    *,
    lender_id: UUID,
    codes: list[str],
    code_map: dict[str, LenderConditionCode],
) -> list[str]:
    """Bump what we know about each code this sheet carried. Returns the ones with no meaning.

    ⚠️ "BUMP THE COUNTERS, NEVER RESET THE MEANING". `status` goes through `resolved_status`, which
    is the single statement of "raised, never lowered" — shared with `seed_lender_codes.py` rather
    than restated here, because two independently shaped versions of one rule is how they drift. A
    sheet mentioning a code a person has already MAPPED must not demote it.
    """
    unmapped: list[str] = []
    now = utcnow()

    for code in codes:
        existing = code_map.get(code)
        if existing is None:
            # ⚠️ THE LABEL IS THE CODE ITSELF, AND THAT IS A DECISION THE SPEC DOES NOT MAKE.
            # `label` is NOT NULL (spec lists it without the `?` that marks the optional columns),
            # but an unknown code has no meaning by definition — that is what OBSERVED_UNMAPPED
            # says. The alternatives were worse: the row's `lender_category` is the lender's
            # category for the CONDITION, not a meaning for the CODE, and storing it here would
            # read as a mapping somebody made; an empty string reads as missing data rather than
            # as absent meaning. The code is at least true, and `status` is what the review queue
            # reads to know nobody has looked.
            created = LenderConditionCode(
                lender_id=lender_id,
                code=code,
                label=code,
                status=LenderCodeStatus.OBSERVED_UNMAPPED,
                times_seen=1,
                first_seen_at=now,
                last_seen_at=now,
            )
            db.add(created)
            code_map[code] = created
            unmapped.append(code)
            continue

        existing.times_seen += 1
        existing.last_seen_at = now
        existing.status = resolved_status(existing.status, LenderCodeStatus.OBSERVED_UNMAPPED)
        if existing.status is LenderCodeStatus.OBSERVED_UNMAPPED:
            unmapped.append(code)

    await db.flush()
    return unmapped


def _apply_code_defaults(
    row: dict[str, Any],
    *,
    code_row: LenderConditionCode | None,
    owner_hint: OwnerHint,
    owner_hint_source: OwnerHintSource,
) -> tuple[OwnerHint, OwnerHintSource, bool, str | None]:
    """The code map's contribution to a NEW condition (spec step 4).

    ⚠️ THE OWNER HINT IS APPLIED ONLY WHERE THE SHEET GAVE NONE. The spec's wording is "apply the
    owner hint when no prefix/bucket hint was found", and the reason is in `OwnerHintSource`'s own
    docstring: the hints are not equally good. A `TC:` the lender typed is far stronger evidence
    than a default looked up from the map, and overwriting the first with the second would destroy
    the better answer while leaving the field looking just as populated.

    ⚠️ `default_bucket_kind` IS DELIBERATELY NOT APPLIED. Spec step 4 lists three things — info_only,
    canonical_type_id and the owner hint — and the bucket is not among them. The heading printed on
    the sheet is the lender's own statement of when this condition is due; a default from the code
    map would override the specific with the general.
    """
    if code_row is None:
        return owner_hint, owner_hint_source, False, None

    if owner_hint_source is OwnerHintSource.NONE and code_row.default_owner_hint is not None:
        owner_hint = code_row.default_owner_hint
        owner_hint_source = OwnerHintSource.CODE_MAP

    return owner_hint, owner_hint_source, bool(code_row.info_only), code_row.canonical_type_id


# --------------------------------------------------------------------------- #
# Row handling
# --------------------------------------------------------------------------- #


def _enum_from(row: dict[str, Any], key: str, enum: Any, default: Any) -> Any:
    """A draft row's enum field, which is a STRING — `draft_rows` is JSONB written through
    `DraftRowPublic.model_dump(mode="json")`, so nothing in it is an enum instance."""
    raw = row.get(key)
    if raw is None:
        return default
    try:
        return enum(raw)
    except ValueError:
        return default


def _create_condition(
    row: dict[str, Any],
    *,
    round_: ConditionRound,
    code_row: LenderConditionCode | None,
    origin: ConditionOrigin = ConditionOrigin.SHEET,
) -> Condition:
    owner_hint = _enum_from(row, "owner_hint", OwnerHint, OwnerHint.UNKNOWN)
    owner_hint_source = _enum_from(row, "owner_hint_source", OwnerHintSource, OwnerHintSource.NONE)
    owner_hint, owner_hint_source, info_only, canonical_type_id = _apply_code_defaults(
        row, code_row=code_row, owner_hint=owner_hint, owner_hint_source=owner_hint_source
    )
    code = row.get("lender_code")

    return Condition(
        company_id=round_.company_id,
        loan_file_id=round_.loan_file_id,
        lender_id=round_.lender_id,
        first_round_id=round_.id,
        last_seen_round_id=round_.id,
        sequence=int(row.get("sequence") or 0),
        lender_code=code if isinstance(code, str) and code else None,
        lender_category=row.get("lender_category") or None,
        bucket_heading=str(row.get("bucket_heading") or ""),
        bucket_kind=_enum_from(row, "bucket_kind", BucketKind, BucketKind.UNKNOWN),
        # ⚠️ THE LENDER'S WORDS, UNTOUCHED — and this is the last place they could be tidied. What
        # the processor edited on the review screen is what imports (spec §8), so the fingerprint is
        # of what is IMPORTED, not of what was read.
        verbatim_text=str(row.get("verbatim_text") or ""),
        text_fingerprint=_row_fingerprint(row),
        underwriter_notes=_notes_from_row(row, round_id=round_.id),
        owner_hint=owner_hint,
        owner_hint_source=owner_hint_source,
        info_only=info_only,
        canonical_type_id=canonical_type_id,
        # ⚠️ THE CALLER NAMES THE DOOR, AND THERE IS ONLY ONE CONSTRUCTOR ON PURPOSE. Import passes
        # SHEET; the manual door passes MANUAL. This module's docstring states the rule every writer
        # of a `Condition` must honour — emit `CONDITION_CREATED` — and a second constructor is
        # precisely how a third writer comes to stop honouring it, which is what happened in
        # `condition_enrich.py`. The distinction itself is what lets the chips say a condition was
        # never printed on a sheet.
        origin=origin,
        # `prep_status` and `lender_status` take their defaults and are never moved in Stage 1.
    )


def _update_seen_again(
    condition: Condition, row: dict[str, Any], *, round_: ConditionRound
) -> dict[str, Any]:
    """Update a condition the sheet carried again. Returns what changed, for the event detail.

    ⚠️ NOTHING HERE TOUCHES `prep_status`, `lender_status`, `verbatim_text` OR `first_round_id`.
    The first two are ADR-404. The wording is not re-written because the condition already holds the
    lender's words for this demand and a later sheet re-printing them is not a correction — and
    `first_round_id` is the historical fact that it was first seen elsewhere.
    """
    changed: dict[str, Any] = {}

    condition.last_seen_round_id = round_.id

    # ⚠️ ONLY A FULL LIST MOVES A CONDITION'S PLACE, THOUGH THE SPEC SAYS "UPDATE `sequence`" PLAINLY.
    # `sequence` is "order on the latest sheet it appeared on" (spec §3), and a PARTIAL round is not
    # a sheet in that sense: it is a fragment, and its row numbers count from the top of what the
    # processor happened to paste. Writing those numbers over a full list's gave round 2's six
    # conditions the positions 1-6 while the five it did not carry kept 2, 3, 4, 5 and 6 — so the
    # file's list, ordered by `sequence`, interleaved two sheets and broke every heading into
    # fragments (S1-08, measured in LP-909 §5's Visual check: "UW PTD (2)", "Closing (1)",
    # "UW PTD (1)", … where the design keeps 5 / 1 / 5). A full list renumbers every row it carries
    # from one numbering, so its positions do mean "the lender's current order".
    #
    # This departs from the spec's literal step 2 for partial rounds, which §9.10 makes a STOP AND
    # ASK; it was resolved with the option that keeps both the spec's meaning and the design, and is
    # recorded in LP-909 §5. The heading and kind below still update on any round: a partial paste
    # that shows a condition under a new heading is evidence the lender moved it.
    sequence = int(row.get("sequence") or 0)
    if (
        round_.completeness is ConditionRoundCompleteness.FULL
        and sequence
        and sequence != condition.sequence
    ):
        changed["sequence"] = sequence
        condition.sequence = sequence

    heading = str(row.get("bucket_heading") or "")
    if heading and heading != condition.bucket_heading:
        changed["bucket_heading"] = heading
        condition.bucket_heading = heading

    kind = _enum_from(row, "bucket_kind", BucketKind, condition.bucket_kind)
    if kind is not condition.bucket_kind:
        changed["bucket_kind"] = kind.value
        condition.bucket_kind = kind

    category = row.get("lender_category")
    if isinstance(category, str) and category and category != condition.lender_category:
        changed["lender_category"] = category
        condition.lender_category = category

    return changed


# --------------------------------------------------------------------------- #
# The number, and the race the lock does not prevent
# --------------------------------------------------------------------------- #


def _is_duplicate_round_number(error: IntegrityError) -> bool:
    """Whether this violation is two rounds claiming one number, and not something else.

    ⚠️ THE CONSTRAINT NAME IS NOT WHERE IT LOOKS LIKE IT IS — measured against the database, not
    assumed. `error.orig` is SQLAlchemy's asyncpg `IntegrityError` wrapper and carries NO
    `constraint_name`; the name lives on its `__cause__`, the underlying
    `asyncpg.UniqueViolationError`. Reading the obvious attribute returns `None`, the comparison is
    quietly always False, and the retry would never fire while reading as though it did.

    Narrow on purpose. A retry that caught every `IntegrityError` would swallow a NOT NULL violation
    or a foreign key and then retry a write that cannot ever succeed, burning its attempts and
    reporting the wrong reason.
    """
    cause = getattr(error.orig, "__cause__", None)
    return getattr(cause, "constraint_name", None) == _ROUND_NUMBER_INDEX


async def _assign_round_number(db: AsyncSession, *, round_: ConditionRound) -> int:
    """Claim the next free number for this file, settling the round as IMPORTED.

    ⚠️ THE LOCK DOES NOT PREVENT THIS RACE; THE INDEX DOES. `loan_file_needs_lock` is advisory — it
    yields `bool(acquired)`, every existing call site binds nothing and proceeds either way, and its
    `timeout=30` auto-expires a HELD lock, so a long import loses it mid-transaction while still
    working. Two imports can therefore compute the same `max + 1`, and
    `uq_condition_rounds_file_number` is what actually refuses the second.

    ⚠️ THE SAVEPOINT WRAPS ONLY THE WRITE THAT CAN VIOLATE. Everything else is flushed before this
    is called, because a rollback discards whatever was left unsettled inside the window — the
    lesson `verification_rules.py` records as "a savepoint added to protect the commit being the one
    thing that could destroy it".

    ⚠️ AND THE ROLLBACK EXPIRES `round_`, WHICH IS THE HALF THAT BITES. In async SQLAlchemy an
    expired attribute is a lazy sync load, so reading one after the rollback raises `MissingGreenlet`
    rather than reloading — a greenlet error that looks nothing like a unique violation, a line away
    from the code you were thinking about. `await db.refresh()` is the cure, and it is why the
    recompute below is a QUERY rather than anything read off this object. `finding_impact.py:141`
    is the shape: the explicit `begin_nested()` / `savepoint.rollback()` form, because the context
    manager rolls back AND re-raises, and a retry needs to roll back and carry on.
    """
    number = await _next_round_number(db, loan_file_id=round_.loan_file_id)

    for attempt in range(1, MAX_NUMBER_ATTEMPTS + 1):
        if attempt > 1:
            # ⚠️ RECOMPUTED AT THE TOP OF A RETRY, NOT AFTER THE FAILURE THAT CAUSED IT. Those look
            # equivalent and are not: recomputing in the `except` branch meant the LAST failed
            # attempt also issued a query, for a number nobody would ever use, while holding a lock
            # that auto-expires at 30 seconds — the exact resource this bound exists to protect.
            #
            # It also made "attempts" and "computations" differ by one, which is how a test counting
            # the latter while claiming to pin the former read as correct: `len(calls) == 4` against
            # `MAX_NUMBER_ATTEMPTS == 3`. Here the two counts are the same number, so the test can
            # assert the property directly instead of an off-by-one restatement of it.
            number = await _next_round_number(db, loan_file_id=round_.loan_file_id)

        savepoint = await db.begin_nested()
        round_.round_number = number
        round_.status = ConditionRoundStatus.IMPORTED
        # The rows ARE conditions now. Leaving them would make a draft and an imported round
        # indistinguishable on the review screen, which is the distinction LP-904 built.
        round_.draft_rows = None
        try:
            await db.flush()
        except IntegrityError as error:
            if not _is_duplicate_round_number(error):
                raise
            await savepoint.rollback()
            # Reload before touching `round_` again — see the docstring.
            await db.refresh(round_)
            logger.info(
                "condition_round_number_retry",
                round_id=str(round_.id),
                attempt=attempt,
                # The number that was REFUSED. It used to log the freshly recomputed one under the
                # same name, so the line read as though the retry had already succeeded.
                claimed_number=number,
            )
            continue
        await savepoint.commit()
        return number

    # ⚠️ NEVER A SILENT GIVE-UP AND NEVER AN UNBOUNDED LOOP. `max + 1` recomputed under contention
    # can lose twice, so "retry until it works" is not a bound — and an unbounded retry would
    # outlive the 30-second lock it is holding, which is the very failure it exists to prevent.
    raise RoundNotImportable(
        "Another import claimed this round number while this one was running. Try again."
    )


def _refuse_unless_importable(round_: ConditionRound) -> None:
    """Only a DRAFT may be imported, and the refusal says which state it is actually in.

    ⚠️ THIS IS A GUARD, NOT MUTUAL EXCLUSION. Two concurrent imports can both read DRAFT and both
    proceed; what stops them producing two numbered rounds is the unique index, and what stops them
    producing duplicate conditions is the match — the second import finds every row already present
    and records them as seen again rather than creating them twice.
    """
    if round_.status is _IMPORTABLE:
        return
    reasons = {
        ConditionRoundStatus.PARSING: "This round is still being read. Wait for it to finish.",
        ConditionRoundStatus.PARSE_FAILED: "This round could not be read, so there is nothing to "
        "import.",
        ConditionRoundStatus.IMPORTED: "This round has already been imported.",
        ConditionRoundStatus.DISCARDED: "This round was discarded.",
    }
    raise RoundNotImportable(reasons.get(round_.status, "This round cannot be imported."))


# --------------------------------------------------------------------------- #
# The import
# --------------------------------------------------------------------------- #


async def import_round(
    db: AsyncSession,
    *,
    round_: ConditionRound,
    actor_user_id: UUID | None = None,
) -> ImportOutcome:
    """Turn a reviewed draft's rows into this file's conditions (spec §LP-909, steps 1-5).

    Flushes; the caller commits. The caller also holds `loan_file_needs_lock` and has already
    company-scoped this round — every query below is per `loan_file_id` taken from it.
    """
    _refuse_unless_importable(round_)

    rows: list[dict[str, Any]] = [r for r in (round_.draft_rows or []) if isinstance(r, dict)]
    if not rows:
        # Importing nothing would consume a round number and produce a round that claims to be the
        # lender's list while holding none of it. Throwing the draft away is the operation the
        # processor actually wants, and it has its own endpoint and its own event.
        raise RoundNotImportable("This round has no rows to import. Discard it instead.")

    existing = await _existing_conditions(db, loan_file_id=round_.loan_file_id)
    # ⚠️ FIRST WINS, NOT LAST, AND BOTH LOOKUPS HOLD EVERY CANDIDATE RATHER THAN ONE. Two conditions
    # can share `(lender_id, lender_code)` by design — a same-code/different-wording row creates a
    # second one, which is what `possible_match` is for. A dict comprehension silently kept whichever
    # came last out of an unordered query; `setdefault` over the oldest-first list keeps the
    # original. And the wording index keeps a LIST because the right candidate now depends on the
    # lender, so picking one up front would pick it before the question was asked.
    by_code: dict[tuple[UUID | None, str], Condition] = {}
    by_text: dict[str, list[Condition]] = {}
    for condition in existing:
        if condition.lender_code:
            by_code.setdefault((condition.lender_id, condition.lender_code), condition)
        by_text.setdefault(condition.text_fingerprint, []).append(condition)

    # ⚠️ `lender_id` IS NULLABLE AND A FILE WITH NO LENDER MUST STILL IMPORT. `(lender, code)` is
    # meaningless without the lender (ADR-407), so the code-map step is SKIPPED rather than guessed
    # at — the conditions still land, carrying their codes as printed. LP-905 already treats a
    # lender-less file as a real state rather than an error.
    codes = _codes_on_sheet(rows)
    code_map: dict[str, LenderConditionCode] = {}
    if round_.lender_id is not None:
        code_map = await _load_code_map(db, lender_id=round_.lender_id, codes=codes)

    created_count = 0
    seen_again_count = 0

    for row in rows:
        match, possible = _match(row, by_code=by_code, by_text=by_text, lender_id=round_.lender_id)
        code = row.get("lender_code")
        code_row = code_map.get(code) if isinstance(code, str) and code else None

        if match is None:
            condition = _create_condition(row, round_=round_, code_row=code_row)
            db.add(condition)
            # `flush` first: the event needs the condition's id, and `db.add` alone does not assign
            # one — `UUIDMixin`'s default is Python-side and applied at flush.
            await db.flush()

            detail: dict[str, Any] = {"source": "import", "lender_code": condition.lender_code}
            if possible is not None:
                # An id for Stage 2 to interpret, never a decision here: same code, different
                # words is either a rewording or a different demand under one template, and Stage 1
                # cannot tell which.
                detail["possible_match"] = str(possible.id)
            db.add(
                ConditionEvent(
                    company_id=round_.company_id,
                    loan_file_id=round_.loan_file_id,
                    round_id=round_.id,
                    condition_id=condition.id,
                    kind=ConditionEventKind.CONDITION_CREATED,
                    actor_user_id=actor_user_id,
                    detail=detail,
                )
            )
            created_count += 1

            # So a sheet listing the same condition twice matches the first one rather than
            # creating a second.
            by_text.setdefault(condition.text_fingerprint, []).append(condition)
            if condition.lender_code:
                by_code.setdefault((condition.lender_id, condition.lender_code), condition)
            continue

        changed = _update_seen_again(match, row, round_=round_)
        if match.lender_id is None and round_.lender_id is not None:
            # ⚠️ ADOPTION, AND WITHOUT IT THE BENIGN CASE QUIETLY DEGRADES. A condition recorded
            # before the file had a lender matched this round by wording — but leaving it at `None`
            # means pass 1 can never find it by `(lender, code)` again, so it depends on identical
            # wording forever and drifts apart the first time the lender rephrases. Measured before
            # the fix: a lender-less round then a lender round left `lender_id=None` permanently.
            match.lender_id = round_.lender_id
            changed["lender_adopted"] = True
        db.add(
            ConditionEvent(
                company_id=round_.company_id,
                loan_file_id=round_.loan_file_id,
                round_id=round_.id,
                condition_id=match.id,
                kind=ConditionEventKind.CONDITION_SEEN_AGAIN,
                actor_user_id=actor_user_id,
                # ⚠️ WHAT CHANGED, NOT THE WORDING. `ConditionEvent.detail` is classified NPI and
                # dropped from the readonly views, so text here would be *permitted* — but the
                # sibling writer (`condition_enrich.py`) keeps these details to counts, codes and
                # names, and one table written two ways is how a rule stops being a rule.
                detail={"lender_code": match.lender_code, "changed": changed},
            )
        )
        seen_again_count += 1

        incoming = _notes_from_row(row, round_id=round_.id)
        fresh = _new_notes(list(match.underwriter_notes or []), incoming)
        if fresh:
            # Reassigned rather than appended in place: JSONB tracks by identity, and mutating the
            # list would not mark the attribute dirty.
            match.underwriter_notes = [*(match.underwriter_notes or []), *fresh]
            db.add(
                ConditionEvent(
                    company_id=round_.company_id,
                    loan_file_id=round_.loan_file_id,
                    round_id=round_.id,
                    condition_id=match.id,
                    kind=ConditionEventKind.CONDITION_NOTE_ADDED,
                    actor_user_id=actor_user_id,
                    detail={"notes_added": len(fresh), "lender_code": match.lender_code},
                )
            )

    unmapped: list[str] = []
    if round_.lender_id is not None:
        unmapped = await _record_codes(
            db, lender_id=round_.lender_id, codes=codes, code_map=code_map
        )

    # ⚠️ EVERYTHING SETTLED BEFORE THE SAVEPOINT. A rollback inside `_assign_round_number` discards
    # whatever is still unflushed in its window; the conditions and events above must not be in it.
    await db.flush()

    number = await _assign_round_number(db, round_=round_)

    db.add(
        ConditionEvent(
            company_id=round_.company_id,
            loan_file_id=round_.loan_file_id,
            round_id=round_.id,
            kind=ConditionEventKind.ROUND_IMPORTED,
            actor_user_id=actor_user_id,
            detail={
                "round_number": number,
                "rows": len(rows),
                "created": created_count,
                "seen_again": seen_again_count,
                "unmapped_codes": unmapped,
            },
        )
    )

    await log_activity(
        db,
        loan_file_id=round_.loan_file_id,
        activity_type=ActivityType.CONDITION_IMPORTED,
        # Spec step 5's own words.
        summary=f"Conditions imported: {created_count} new, {seen_again_count} seen again",
        actor_user_id=actor_user_id,
        detail={
            "round_id": str(round_.id),
            "round_number": number,
            "created": created_count,
            "seen_again": seen_again_count,
            "unmapped_codes": unmapped,
        },
    )

    await db.flush()

    # ⚠️ IDS, COUNTS AND CODES ONLY — never a condition's wording, never a borrower fact (spec §9.5).
    logger.info(
        "condition_round_imported",
        round_id=str(round_.id),
        round_number=number,
        rows=len(rows),
        created=created_count,
        seen_again=seen_again_count,
        unmapped_codes=len(unmapped),
    )

    return ImportOutcome(
        round_number=number,
        created=created_count,
        seen_again=seen_again_count,
        unmapped_codes=unmapped,
    )


# --------------------------------------------------------------------------- #
# The third door: one condition, typed by hand (spec §LP-909, screen S1-12)
# --------------------------------------------------------------------------- #


async def _latest_imported_round(db: AsyncSession, *, loan_file_id: UUID) -> ConditionRound | None:
    """The file's highest-numbered imported round, or None if no sheet has ever been imported."""
    stmt = select(ConditionRound).where(
        ConditionRound.loan_file_id == loan_file_id,
        ConditionRound.status == ConditionRoundStatus.IMPORTED,
    )
    stmt = only_active(stmt, ConditionRound).order_by(ConditionRound.round_number.desc())
    # Annotated rather than returned straight: `db.scalar` degrades to `Any` once the select has
    # been chained through `only_active` and `order_by`, and returning that from a function declared
    # `ConditionRound | None` is exactly what mypy's `no-any-return` is for. Widening the signature
    # to match the inference would hide the looseness instead of naming it.
    latest: ConditionRound | None = await db.scalar(stmt)
    return latest


async def _next_sequence(db: AsyncSession, *, loan_file_id: UUID) -> int:
    """One past the file's highest sequence, so a hand-typed condition sorts after the sheet's."""
    highest = await db.scalar(
        select(func.max(Condition.sequence)).where(Condition.loan_file_id == loan_file_id)
    )
    return int(highest or 0) + 1


async def _manual_round(
    db: AsyncSession, *, loan_file: LoanFile, actor_user_id: UUID | None
) -> ConditionRound:
    """Round 1 for a file where a processor typed a condition before any sheet arrived.

    ⚠️ ALWAYS `PARTIAL`, AND THIS IS THE ONE THAT WOULD BITE SILENTLY. ADR-404 lets only a FULL
    round's absences mean anything: a `FULL` round is a claim that the lender's list is complete, and
    Stage 2's comparison is entitled to propose "probably cleared" for anything missing from one. A
    round holding whatever a processor happened to type by hand is not that claim, and marking it
    FULL would let a later comparison conclude that every condition nobody typed had been cleared.

    It takes a number immediately through `_assign_round_number`, which is also what makes it
    IMPORTED — a manual round has nothing to review, so there is no draft state for it to sit in.
    """
    now = utcnow()
    source: dict[str, Any] = {"kind": ConditionSourceKind.MANUAL.value, "at": now.isoformat()}
    if actor_user_id is not None:
        source["user_id"] = str(actor_user_id)

    round_ = ConditionRound(
        company_id=loan_file.company_id,
        loan_file_id=loan_file.id,
        lender_id=loan_file.lender_id,
        completeness=ConditionRoundCompleteness.PARTIAL,
        sources=[source],
        round_date=now.date(),
        created_by_user_id=actor_user_id,
    )
    db.add(round_)
    await db.flush()

    db.add(
        ConditionEvent(
            company_id=loan_file.company_id,
            loan_file_id=loan_file.id,
            round_id=round_.id,
            kind=ConditionEventKind.ROUND_RECEIVED,
            actor_user_id=actor_user_id,
            detail={"source_kind": ConditionSourceKind.MANUAL.value},
        )
    )
    # Settled before the savepoint `_assign_round_number` takes — a rollback there discards whatever
    # is still unflushed inside its window.
    await db.flush()
    await _assign_round_number(db, round_=round_)
    return round_


async def create_manual_condition(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    payload: ConditionCreateRequest,
    actor_user_id: UUID | None = None,
) -> Condition:
    """Add one condition by hand. Flushes; the caller commits.

    ⚠️ THE THIRD WRITER OF A `Condition`, AND IT EMITS `CONDITION_CREATED` LIKE THE OTHER TWO. The
    rule is in this module's docstring because breaking it already happened once: `condition_enrich`
    created conditions silently and they carried no round chips. This goes through the SAME
    `_create_condition` as the import rather than constructing a second one — a separate constructor
    is how the next writer comes to forget.

    ⚠️ IT GOES INTO A REAL ROUND, AND THE CHIP IS TRUTHFUL BECAUSE OF THAT. Spec §LP-909 puts a
    hand-typed condition into the latest imported round, or creates round 1 with source `MANUAL` if
    the file has none — so the round genuinely is its home and `R1` is not a claim that it was
    printed on a sheet. `origin` carries that distinction: `SHEET` for a row read off a letter,
    `MANUAL` for this. Emitting nothing instead would reproduce the enrich bug exactly.

    ⚠️ THE CODE MAP'S DEFAULTS ARE APPLIED; ITS COUNTERS ARE NOT. `times_seen` is what orders the
    unmapped backlog, and it is supposed to answer "how often do lenders actually send this code" —
    a processor typing one is not the lender sending it, so counting it would inflate the queue with
    our own keystrokes. Looking the code up to fill `info_only`, `canonical_type_id` and an owner
    hint costs nothing and is the same meaning the import would have applied.
    """
    round_ = await _latest_imported_round(db, loan_file_id=loan_file.id)
    if round_ is None:
        round_ = await _manual_round(db, loan_file=loan_file, actor_user_id=actor_user_id)

    code_row: LenderConditionCode | None = None
    if round_.lender_id is not None and payload.lender_code:
        found = await _load_code_map(db, lender_id=round_.lender_id, codes=[payload.lender_code])
        code_row = found.get(payload.lender_code)

    # Through `DraftRowPublic` like every other row in this domain, so a hand-typed condition and a
    # parsed one are the same shape by construction rather than by agreement.
    row = DraftRowPublic(
        sequence=await _next_sequence(db, loan_file_id=loan_file.id),
        lender_code=payload.lender_code,
        lender_category=payload.lender_category,
        # ⚠️ NOT AN INVENTED LABEL. The heading is the LENDER's vocabulary — "Prior To Docs (PTD)",
        # "Underwriter To Obtain And Clear" — and manufacturing one here would put words in their
        # mouth on a row they never wrote. Empty means the processor filed it under no heading, and
        # the list can say so.
        bucket_heading=payload.bucket_heading or "",
        bucket_kind=payload.bucket_kind,
        # Stored exactly as typed: the dialog's hint says "Type it exactly as the lender wrote it",
        # and this is the boundary that honours it.
        verbatim_text=payload.verbatim_text,
    ).model_dump(mode="json")

    condition = _create_condition(
        row, round_=round_, code_row=code_row, origin=ConditionOrigin.MANUAL
    )
    db.add(condition)
    # `flush` first: the event needs the condition's id, and `db.add` alone does not assign one.
    await db.flush()

    db.add(
        ConditionEvent(
            company_id=round_.company_id,
            loan_file_id=round_.loan_file_id,
            round_id=round_.id,
            condition_id=condition.id,
            kind=ConditionEventKind.CONDITION_CREATED,
            actor_user_id=actor_user_id,
            detail={"source": "manual", "lender_code": condition.lender_code},
        )
    )
    await db.flush()

    # Ids and codes only — never the wording (spec §9.5).
    logger.info(
        "condition_added_by_hand",
        loan_file_id=str(loan_file.id),
        round_id=str(round_.id),
        condition_id=str(condition.id),
        lender_code=condition.lender_code,
    )
    return condition


__all__ = [
    "MAX_NUMBER_ATTEMPTS",
    "ImportOutcome",
    "RoundNotImportable",
    "create_manual_condition",
    "import_round",
]
