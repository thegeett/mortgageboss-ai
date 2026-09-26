"""Reading a file's rounds and conditions (LP-909 section 1; the filters, sorts and summary are LP-911).

TWO FIELDS HERE HAVE EXISTED SINCE LP-904 WITH NOTHING TO FILL THEM, which is the same shape as
`text_fingerprint` — a column declared, documented, indexed and never written, green because nothing
executed it. `ConditionRoundPublic.condition_count` defaults to 0 and `ConditionPublic.round_numbers`
to `[]`, and until this module the only producer of either was the default. A round strip rendering
`0 on sheet` and `R1 R2` chips that never appear would have looked like a UI bug for as long as
anyone cared to look.

AND THEY ARE THE SAME JOIN, READ IN OPPOSITE DIRECTIONS. A condition "appeared on" a round exactly
when the round's import wrote a `CONDITION_CREATED` or `CONDITION_SEEN_AGAIN` event naming both. Ask
it per condition and you get the `R1 R2` chips; ask it per round and you get the round card's count.
So ONE query answers both, which is the point: the alternative is a query per row, and this repo has
a named precedent for refusing that (`_completed_documents`, loaded once, "LP-109, no N+1").

WHY EVENTS RATHER THAN A JOIN TABLE. The spec offers either — "from its `CONDITION_CREATED` /
`CONDITION_SEEN_AGAIN` events, or from a join table if the survey finds one is simpler". The events
already exist, are append-only, and are written by the import as its audit record; a join table would
be a second statement of the same fact, maintained beside it, free to disagree. The event IS the
record that a condition was on a sheet.

LP-911 ADDED THE FILTERS, THE FIVE SORTS AND THE SUMMARY, and with them this module became the place
that DEFINES three words the rest of the stack only uses. `is_open`, `effective_owner` and the day
count each have exactly one statement here, and the schema is deliberately unable to compute them —
`ConditionPublic.from_model` takes them as required arguments — so that a row can never disagree with
the filter that selected it. A list filtered on `owner=borrower` rendering a row whose owner reads
otherwise is the kind of split nothing fails on, and it is prevented by there being nowhere else to
answer the question.

THE SAME RULE HAS A SQL TWIN, AND THAT PAIR IS THE ONE FRAGILE THING IN HERE.
`_effective_owner_column` is `effective_owner` expressed for the database, because a filter runs in SQL
and a rendered field runs in Python. LP-912 makes both of them `coalesce(owner_override, owner_hint)`;
changing one alone leaves the two disagreeing, with both answers individually valid. They sit next to
each other for that reason.

`latest_imported_round` MOVED HERE FROM `condition_import` (LP-911). This module owns reading rounds,
and the summary needs the same answer the import does for the file rail's "from round 2, printed
09/10" — one question asked in two modules is how the two come to answer differently.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, cast
from uuid import UUID

from sqlalchemy import ColumnElement, Select, case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.models.condition import (
    BucketKind,
    Condition,
    ConditionLenderStatus,
    ConditionOrigin,
    ConditionPrepStatus,
    OwnerHint,
    OwnerHintSource,
)
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import ConditionRound, ConditionRoundStatus
from app.models.helpers import only_active
from app.schemas.condition import ConditionSort

#: The two events that mean "this condition was on this sheet". `CONDITION_NOTE_ADDED` and
#: `CONDITION_EDITED` are deliberately absent: a note appended or a wording corrected says the
#: condition CHANGED, not that it appeared on another round, and counting them would put a round
#: number on a chip for a sheet the condition was never printed on.
APPEARED_ON = (ConditionEventKind.CONDITION_CREATED, ConditionEventKind.CONDITION_SEEN_AGAIN)


async def list_rounds(db: AsyncSession, *, loan_file_id: UUID) -> list[ConditionRound]:
    """The file's active rounds, newest first.

    DISCARDED ROUNDS ARE INCLUDED, and that is deliberate rather than an oversight. A processor
    who threw a draft away should see that they did — the round strip is a history, and a discarded
    round silently vanishing reads as data loss. `status` is what the UI filters on; soft-deleted
    rows are what `only_active` removes, and those are a different thing entirely.
    """
    stmt = select(ConditionRound).where(ConditionRound.loan_file_id == loan_file_id)
    stmt = only_active(stmt, ConditionRound)
    # Newest first, with `round_number` as the tiebreak so two rounds created in the same instant
    # (an upload and a paste) order deterministically rather than by whatever the planner returns.
    stmt = stmt.order_by(ConditionRound.created_at.desc(), ConditionRound.round_number.desc())
    return list((await db.execute(stmt)).scalars().all())


async def list_conditions(db: AsyncSession, *, loan_file_id: UUID) -> list[Condition]:
    """The file's active conditions, in the order the lender printed them on the newest sheet.

    `sequence` is "its order on the latest sheet it appeared on" (LP-904), so ordering by it is what
    makes the list read in SHEET order — which is the order the processor sees in the lender's
    portal, and the whole reason the column exists rather than sorting by creation time.
    """
    stmt = select(Condition).where(Condition.loan_file_id == loan_file_id)
    stmt = only_active(stmt, Condition)
    stmt = stmt.order_by(Condition.sequence, Condition.created_at)
    return list((await db.execute(stmt)).scalars().all())


async def _appearances(
    db: AsyncSession, *, loan_file_id: UUID
) -> list[tuple[UUID, UUID, int | None]]:
    """Every (condition, round, round_number) a `CONDITION_CREATED`/`SEEN_AGAIN` event records.

    ONE QUERY FOR THE WHOLE FILE. Joined to `condition_rounds` because the event carries a round ID
    and the chip needs its NUMBER — and a round that is still a draft has none, which is why the
    third element is nullable and the callers below drop those rather than rendering `R`.
    """
    stmt = (
        select(ConditionEvent.condition_id, ConditionEvent.round_id, ConditionRound.round_number)
        .join(ConditionRound, ConditionEvent.round_id == ConditionRound.id)
        .where(
            ConditionEvent.loan_file_id == loan_file_id,
            ConditionEvent.kind.in_(APPEARED_ON),
            ConditionEvent.condition_id.is_not(None),
        )
    )
    return [
        (condition_id, round_id, number)
        for condition_id, round_id, number in (await db.execute(stmt)).all()
        if condition_id is not None and round_id is not None
    ]


async def appearances_for_file(
    db: AsyncSession, *, loan_file_id: UUID
) -> tuple[dict[UUID, list[int]], dict[UUID, int]]:
    """Both derived views, from one query: rounds-per-condition and conditions-per-round.

    Returned together rather than as two functions, because computing them separately would run the
    same query twice — and because a caller that fetched only one of them would quietly serve the
    other as its default, which is exactly how these two fields came to have no producer at all.
    """
    rows = await _appearances(db, loan_file_id=loan_file_id)

    numbers: dict[UUID, set[int]] = defaultdict(set)
    per_round: dict[UUID, set[UUID]] = defaultdict(set)
    for condition_id, round_id, number in rows:
        # DEFENCE, NOT A DESCRIBED CASE — and an earlier comment here claimed otherwise, saying a
        # numberless round "still counts toward that round's own total". That state cannot be
        # reached: appearance events are written only by paths that operate on an IMPORTED round
        # (import itself, and `_merge_conditions`), and `rows_on_sheet` reads these counts only for
        # an IMPORTED round. A round with appearances therefore always has a number.
        #
        # The guard stays because a NULL would otherwise put `None` in a list typed `list[int]`, and
        # a comment claiming to describe behaviour is worse than one admitting it is a belt.
        if number is not None:
            numbers[condition_id].add(number)
        per_round[round_id].add(condition_id)

    return (
        {condition_id: sorted(found) for condition_id, found in numbers.items()},
        {round_id: len(found) for round_id, found in per_round.items()},
    )


async def events_for_round(db: AsyncSession, *, round_id: UUID) -> list[ConditionEvent]:
    """One round's history, oldest first — the history on screen S1-09.

    THE FIRST READER `ix_condition_events_round_occurred` HAS EVER HAD, AND THAT IS THE POINT.
    LP-904 declared that index with the comment "One round's history in time order — the shape the
    round-details sheet reads (S1-09)", and no such reader was ever written. So the index paid a
    write on every event insert — per created condition, per seen-again, per note, per round
    transition — to serve a query nobody made. `(round_id, occurred_at)` is exactly this ordering, so
    this function is what finally makes that cost buy something.

    ITS SIBLING STILL HAS NO READER. `ix_condition_events_condition_occurred` is
    `(condition_id, occurred_at)` — a single CONDITION's history in time order, which is a different
    question from a round's and which nothing in this codebase asks. It does not get this function's
    justification, and it is named here so the next person to look does not assume it did.

    NEWEST FIRST, BECAUSE THE DESIGN DECIDED IT. The first version was oldest-first, argued from
    first principles: "a history is read downwards as a sequence". But S1-09's mock runs
    `4:31 → 4:22 → 4:20`, and its *May differ* covers only the sheet width and whether times show —
    so the order is a Must-match, and reasoning my way to the other answer was re-deciding something
    the design pack had already settled. Raised in review; as built the Visual check would have failed.

    ROUND-LEVEL EVENTS ONLY — `condition_id IS NULL`. Without this a 30-row import renders thirty
    "A condition was added" lines and the panel the README calls "a SHORT history" is anything but:
    measured on a real paste → import → paste → import flow, round 2 came back with NINE lines, six of
    them detail-less `CONDITION_SEEN_AGAIN`.

    The cost, stated rather than hidden: a condition typed by hand into an existing imported round
    writes only `CONDITION_CREATED`, so it leaves no round-level trace and does not appear here. That
    is the right trade for a panel about the ROUND, and it is recorded in LP-909 rather than left for
    someone to discover.

    The index still serves this: `(round_id, occurred_at)` is used as a prefix, with the null check as
    a filter.

    NO COMPANY FILTER HERE, AND THAT IS NOT AN OMISSION. The caller resolves the round through
    `get_scoped_round`, which filters `company_id` INSIDE its statement — so an id that reaches this
    function has already been proven to belong to the caller. Adding a second filter would read as
    the gate rather than as a belt, and the gate is the one that must not be forgotten.
    """
    result = await db.execute(
        select(ConditionEvent)
        .where(ConditionEvent.round_id == round_id, ConditionEvent.condition_id.is_(None))
        .order_by(ConditionEvent.occurred_at.desc(), ConditionEvent.id.desc())
    )
    return list(result.scalars().all())


async def events_for_condition(db: AsyncSession, *, condition_id: UUID) -> list[ConditionEvent]:
    """One condition's history, newest first — the detail sheet's History (S2-03).

    THE READER `ix_condition_events_condition_occurred` HAS BEEN WAITING FOR SINCE LP-904, AND THIS
    CLOSES A QUESTION RATHER THAN ADDING ONE. That index is `(condition_id, occurred_at)`; LP-909 said
    plainly that nothing in this codebase asked that question, so it paid a write on every event
    insert to serve a query which did not exist — "either something reads it, or it should go in a
    follow-up migration". This is that something. The open note in `events_for_round`'s docstring and
    in the events route is now answered, and no migration is needed.

    NEWEST FIRST, matching `events_for_round` and the design's own ordering, with `id` as the tiebreak
    so two events written in one transaction order deterministically rather than by whatever the
    planner returns.

    UNLIKE `events_for_round` THIS DOES NOT FILTER `condition_id IS NULL` — it is the opposite
    question. A round's history excludes per-condition noise because a 30-row import would render
    thirty lines; a condition's history is exactly those lines, and the round-level events it shares
    with every other condition on the sheet would be the noise here.

    NO COMPANY FILTER, AND THAT IS NOT AN OMISSION. The caller resolves the condition through
    `get_scoped_condition`, which filters `company_id` inside its own statement, so an id that reaches
    this function has already been proven to belong to the caller. A second filter here would read as
    the gate, and the gate is the one that must not be forgotten.
    """
    result = await db.execute(
        select(ConditionEvent)
        .where(ConditionEvent.condition_id == condition_id)
        .order_by(ConditionEvent.occurred_at.desc(), ConditionEvent.id.desc())
    )
    return list(result.scalars().all())


def rows_on_sheet(round_: ConditionRound, imported_counts: dict[UUID, int]) -> int:
    """How many conditions this round carried — "11 on sheet" on the round card.

    THE ANSWER COMES FROM A DIFFERENT PLACE DEPENDING ON STATUS, and conflating them would make a
    draft look empty. Before import the rows live in `draft_rows` and no `Condition` exists yet;
    after import the rows ARE conditions and `draft_rows` is cleared. So a draft counts its rows and
    an imported round counts its appearances.
    """
    if round_.status is ConditionRoundStatus.IMPORTED:
        return imported_counts.get(round_.id, 0)
    return len(round_.draft_rows or [])


async def import_counts_for_file(
    db: AsyncSession, *, loan_file_id: UUID
) -> dict[UUID, tuple[int, int]]:
    """What each import recorded — `(created, seen_again)`, keyed by round id.

    ONE QUERY FOR THE WHOLE FILE, the rule `appearances_for_file` states: the round strip draws every
    card at once, so a per-card query is the N+1 that helper exists to avoid.

    THE NUMBERS LIVE IN AN EVENT, NOT ON THE ROW. `condition_rounds` stores neither count.
    `condition_import.py` writes them into the `ROUND_IMPORTED` detail and returns them to whoever
    called the import — and that response is gone by the next page load, which is why the card could
    not show them. The event is the only durable record of what an import did.

    NEWEST WINS, DELIBERATELY. `condition_events` is APPEND-ONLY, so a round imported twice has
    two `ROUND_IMPORTED` rows and the later one describes the file as it stands. `occurred_at DESC,
    id DESC` is the same tie-break `events_for_round` uses, and keeping the first row seen per round
    is what makes "newest" the answer rather than "whichever the planner returned".

    A DETAIL THAT CANNOT ANSWER IS SKIPPED, NOT ZEROED. Recording a malformed or partial detail as
    `(0, 0)` would put a confident wrong number on the card — precisely the failure
    `condition_count`'s own default produced. Absent here becomes `None` on the wire.
    """
    stmt = (
        select(ConditionEvent.round_id, ConditionEvent.detail)
        .where(
            ConditionEvent.loan_file_id == loan_file_id,
            ConditionEvent.kind == ConditionEventKind.ROUND_IMPORTED,
            ConditionEvent.round_id.is_not(None),
        )
        .order_by(ConditionEvent.occurred_at.desc(), ConditionEvent.id.desc())
    )

    def _count(value: object) -> int | None:
        # `bool` is an `int` in Python, so a writer that stored `True` would otherwise read as 1.
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    counts: dict[UUID, tuple[int, int]] = {}
    for round_id, detail in (await db.execute(stmt)).all():
        if round_id is None or round_id in counts:
            continue
        created = _count((detail or {}).get("created"))
        seen_again = _count((detail or {}).get("seen_again"))
        if created is not None and seen_again is not None:
            counts[round_id] = (created, seen_again)
    return counts


def import_counts(
    round_: ConditionRound, counts: dict[UUID, tuple[int, int]]
) -> tuple[int | None, int | None]:
    """The `(created, seen_again)` this round's card should show, or `(None, None)`.

    ONLY AN IMPORTED ROUND HAS AN ANSWER — the same status-dependence `rows_on_sheet` documents
    one function above, and for the same reason. A draft has never been imported, so "0 new" would
    be a statement about an event that never happened rather than a count of nothing.
    """
    if round_.status is not ConditionRoundStatus.IMPORTED:
        return (None, None)
    return counts.get(round_.id, (None, None))


# --------------------------------------------------------------------------- #
# Filters, sorts and the summary (LP-911)
# --------------------------------------------------------------------------- #

#: The read cap (spec §LP-911). A file carries roughly 5 to 60 conditions, so 500 is far above
#: anything real — and the response SAYS when it was hit rather than truncating in silence, because a
#: list that quietly stops is indistinguishable from a file with nothing more to show.
MAX_CONDITIONS = 500

#: The lender statuses that mean the condition is still outstanding. `NOT_CLEARED` is open because the
#: lender answered and the answer was no, so the work is back with us. `SUPERSEDED` is absent
#: deliberately: a replaced condition is not open, it is a historical row its successor carries on
#: from.
OPEN_LENDER_STATUSES = (ConditionLenderStatus.OPEN, ConditionLenderStatus.NOT_CLEARED)


def effective_owner(condition: Condition) -> OwnerHint:
    """Who the list groups and filters on.

    ONE PLACE, BECAUSE LP-912 CHANGES IT. That ticket adds `owner_override`, set by hand, which wins
    over the hint — A2's point that "the code map and prefixes are a good first guess, not the truth".
    Until the column exists the hint IS the effective owner, and this function is what LP-912 edits
    rather than every caller.
    """
    return condition.owner_hint


def effective_owner_source(condition: Condition) -> OwnerHintSource:
    """Where the effective owner came from, so the screen can weigh it.

    LP-912 returns `MANUAL` here once an override is set. The pair travels together because a source
    without its owner says nothing, and a UI that rendered a code-map guess and a processor's decision
    identically would invite trusting the weaker one — which is the argument `OwnerHintSource`'s own
    docstring makes for carrying the field at all.
    """
    return condition.owner_hint_source


def is_open(condition: Condition) -> bool:
    """Whether the lender still owes an answer on this condition.

    INFO-ONLY AND SUPERSEDED ARE NEVER OPEN (spec §LP-911). An information line asks for nothing, so
    counting it as outstanding would inflate every number on the summary bar; a superseded condition
    was replaced, and its successor carries the work.

    THE SUMMARY AND THE ROW BOTH READ THIS FUNCTION. A dozen `count(*)` queries would each be a
    chance to disagree with the row about what "open" means, and that disagreement shows up as a
    summary bar which does not add up to the list underneath it.
    """
    if condition.info_only:
        return False
    return condition.lender_status in OPEN_LENDER_STATUSES


def condition_days_open(condition: Condition, *, today: date | None = None) -> int:
    """Days since this file first recorded the condition.

    FROM `created_at`, NOT FROM THE SHEET'S PRINTED DATE, and the difference is real. The printed date
    is when the LENDER wrote the demand; `created_at` is when it became this file's record. A sheet
    imported a week late would otherwise report a condition as having been open for longer than anyone
    here has known about it.

    Never negative: a clock skewed backwards reports 0 rather than a number that reads as the future.
    `today` is a parameter so a test states the date it means instead of depending on when it runs.
    """
    reference = today or datetime.now(UTC).date()
    return max((reference - condition.created_at.date()).days, 0)


@dataclass(frozen=True)
class ConditionFilters:
    """The list's filters (spec §LP-911): AND across fields, OR within a multi-valued one.

    A DATACLASS RATHER THAN TEN PARAMETERS, because the list endpoint and the summary read the same
    set, and two signatures carrying the same ten things is how they come to differ by one.

    `q` IS THE FIELD THAT MUST NEVER BE LOGGED. It searches `verbatim_text`, which is the lender's
    words and therefore NPI (ADR-405). `names()` exists so a log line can say WHICH filters ran
    without saying what was searched for.
    """

    round_number: int | None = None
    lender_status: tuple[ConditionLenderStatus, ...] = ()
    prep_status: tuple[ConditionPrepStatus, ...] = ()
    owner: tuple[OwnerHint, ...] = ()
    bucket_kind: tuple[BucketKind, ...] = ()
    lender_code: str | None = None
    category: str | None = None
    info_only: bool | None = None
    origin: ConditionOrigin | None = None
    q: str | None = None

    def names(self) -> list[str]:
        """Which filters are set. Safe to log; their values are not.

        Written as explicit `is not None` / `bool(...)` tests rather than a truthiness sweep, because
        `info_only=False` IS a filter — a sweep would drop it and the log line would understate what
        ran.
        """
        present = {
            "round": self.round_number is not None,
            "lender_status": bool(self.lender_status),
            "prep_status": bool(self.prep_status),
            "owner": bool(self.owner),
            "bucket_kind": bool(self.bucket_kind),
            "lender_code": self.lender_code is not None,
            "category": self.category is not None,
            "info_only": self.info_only is not None,
            "origin": self.origin is not None,
            "q": self.q is not None,
        }
        return sorted(name for name, was_set in present.items() if was_set)


def _effective_owner_column() -> ColumnElement[OwnerHint]:
    """The SQL twin of :func:`effective_owner`, for filtering and ordering in the database.

    TWO STATEMENTS OF ONE RULE, AND THEY MUST CHANGE TOGETHER. LP-912 makes both of them
    `coalesce(owner_override, owner_hint)`. Changing only one would leave the filter selecting rows by
    a different owner than the row displays — a split that nothing fails on, because both answers are
    individually valid.
    """
    # CAST RATHER THAN A NARROWER ANNOTATION, AND LP-912 IS THE REASON. `Condition.owner_hint` is an
    # `InstrumentedAttribute`, which IS a `ColumnElement` at runtime but which mypy will not accept
    # against the wider declared type. Annotating the narrow type would type-check today and break the
    # moment LP-912 makes this `func.coalesce(owner_override, owner_hint)` — a `ColumnElement` and not
    # an attribute — which would defeat the point of having one function to edit. So the signature
    # states the type that will still be true then, and the cast carries today's value to it.
    # `models/helpers.py::scope_to_company` casts for exactly this reason and says so.
    return cast("ColumnElement[OwnerHint]", Condition.owner_hint)


def _apply_filters(
    stmt: Select[tuple[Condition]], filters: ConditionFilters
) -> Select[tuple[Condition]]:
    """Every filter that SQL can answer. The round filter cannot — see `list_conditions_filtered`."""
    if filters.lender_status:
        stmt = stmt.where(Condition.lender_status.in_(filters.lender_status))
    if filters.prep_status:
        stmt = stmt.where(Condition.prep_status.in_(filters.prep_status))
    if filters.owner:
        stmt = stmt.where(_effective_owner_column().in_(filters.owner))
    if filters.bucket_kind:
        stmt = stmt.where(Condition.bucket_kind.in_(filters.bucket_kind))
    if filters.lender_code is not None:
        # EXACT, AND AS PRINTED. A code is an identifier with its leading zeros intact (ADR-407), so
        # "0006" must not match "6" and a prefix match would make `006` find three different codes.
        stmt = stmt.where(Condition.lender_code == filters.lender_code)
    if filters.category is not None:
        stmt = stmt.where(Condition.lender_category == filters.category)
    if filters.info_only is not None:
        stmt = stmt.where(Condition.info_only.is_(filters.info_only))
    if filters.origin is not None:
        stmt = stmt.where(Condition.origin == filters.origin)
    if filters.q:
        # AUTOESCAPED, so a processor searching for "50%" or "_" gets those characters rather than
        # wildcards. The value is never logged (ADR-405); `ConditionFilters.names()` is what a log
        # line may say.
        #
        # CASE-INSENSITIVE (LP-911 review). `contains` compiles to `LIKE`, which is case-sensitive in
        # Postgres, so "earnest money" found `6637` only because the sheet happens to print it in
        # lower case; "Earnest Money", as the letter's own header prints it, found nothing.
        stmt = stmt.where(
            or_(
                Condition.verbatim_text.icontains(filters.q, autoescape=True),
                Condition.lender_code.icontains(filters.q, autoescape=True),
            )
        )
    return stmt


#: The `status` sort's order: WORK FIRST (LP-911 review). The first version ordered by the columns'
#: stored strings, which is alphabetical — `cleared` before `open`, and `ready` before `to_do` —
#: an order nobody asked for. Came back leads because the lender has sent the work back; answered
#: conditions trail; the two A4 reserves sit where they would mean something if they are ever used.
_LENDER_STATUS_ORDER = (
    ConditionLenderStatus.NOT_CLEARED,
    ConditionLenderStatus.OPEN,
    ConditionLenderStatus.PENDING_REVIEW,
    ConditionLenderStatus.CLEARED,
    ConditionLenderStatus.WAIVED,
    ConditionLenderStatus.SUPERSEDED,
)
_PREP_STATUS_ORDER = (
    ConditionPrepStatus.TO_DO,
    ConditionPrepStatus.WAITING,
    ConditionPrepStatus.REVIEW,
    ConditionPrepStatus.READY,
    ConditionPrepStatus.WITH_UNDERWRITER,
)


def _rank(column: InstrumentedAttribute[Any], order: tuple[StrEnum, ...]) -> ColumnElement[int]:
    """`column`'s position in `order`, so a sort follows the workflow rather than the alphabet."""
    return case({value: index for index, value in enumerate(order)}, value=column, else_=len(order))


def _apply_sort(stmt: Select[tuple[Condition]], sort: ConditionSort) -> Select[tuple[Condition]]:
    """The five orders (spec §LP-911), each with a deterministic tiebreak.

    EVERY ONE ENDS IN A TIEBREAK, because a sort on a column with duplicates otherwise returns
    whatever the planner gives and the list reorders itself between two identical requests. LP-909
    already had to fix a strip that ordered non-deterministically for exactly this reason.
    """
    if sort is ConditionSort.CODE:
        # NULLS LAST: a condition with no code is not "before 0006", it is unordered against the
        # codes, and putting it first would push hand-typed rows to the top of every list.
        return stmt.order_by(Condition.lender_code.asc().nulls_last(), Condition.sequence)
    if sort is ConditionSort.STATUS:
        return stmt.order_by(
            _rank(Condition.lender_status, _LENDER_STATUS_ORDER),
            _rank(Condition.prep_status, _PREP_STATUS_ORDER),
            Condition.sequence,
        )
    if sort is ConditionSort.OWNER:
        return stmt.order_by(_effective_owner_column(), Condition.sequence)
    if sort is ConditionSort.UPDATED:
        return stmt.order_by(Condition.updated_at.desc(), Condition.id.desc())
    return stmt.order_by(Condition.sequence, Condition.created_at)


async def list_conditions_filtered(
    db: AsyncSession,
    *,
    loan_file_id: UUID,
    filters: ConditionFilters | None = None,
    sort: ConditionSort = ConditionSort.SHEET,
    round_numbers: dict[UUID, list[int]] | None = None,
    limit: int = MAX_CONDITIONS,
) -> tuple[list[Condition], bool]:
    """The file's conditions, filtered and sorted. Returns `(rows, capped)`.

    THE ROUND FILTER IS ANSWERED FROM EVENTS, WHICH IS WHY IT IS APPLIED IN PYTHON. "On the sheet of
    round N" is exactly the question `appearances_for_file` answers, and `first_round_id` /
    `last_seen_round_id` cannot express "on R1 and R3 but not R2" — the whole reason the chips are
    event-derived (LP-909 §1). The caller already holds that map for the chips, so it is passed in
    rather than queried a second time.

    ONE EXTRA ROW IS FETCHED, AND THAT IS HOW THE CAP CAN BE REPORTED AT ALL. Asking for `limit` rows
    and receiving `limit` cannot distinguish "exactly that many" from "more, silently dropped", so the
    query asks for one more than it will return.
    """
    stmt = only_active(select(Condition).where(Condition.loan_file_id == loan_file_id), Condition)
    stmt = _apply_filters(stmt, filters or ConditionFilters())
    stmt = _apply_sort(stmt, sort)

    wanted = filters.round_number if filters is not None else None
    if wanted is None:
        found = list((await db.execute(stmt.limit(limit + 1))).scalars().all())
        return found[:limit], len(found) > limit

    numbers = round_numbers or {}
    matched = [
        condition
        for condition in (await db.execute(stmt)).scalars().all()
        if wanted in numbers.get(condition.id, [])
    ]
    return matched[:limit], len(matched) > limit


@dataclass(frozen=True)
class ConditionSummary:
    """Counts for the summary bar and the file rail (spec §LP-911, screens S2-01 / S2-02).

    Every field is required: a summary with a defaulted count is how `condition_count` came to read
    "0 on sheet" for as long as anyone looked (LP-909 §1). A caller that cannot compute one of these
    has a bug, not a default.
    """

    total: int
    open: int
    cleared: int
    waived: int
    not_cleared: int
    superseded: int
    info_only: int
    by_prep_status: dict[str, int]
    by_owner: dict[str, int]
    by_bucket_kind: dict[str, int]
    open_prior_to_docs: int
    open_prior_to_funding: int
    pending_suggestions: int


def summarise_conditions(conditions: list[Condition]) -> ConditionSummary:
    """Count one file's conditions. Pure, so a test can state the rows and read the numbers.

    THE THREE BREAKDOWNS COUNT **OPEN** CONDITIONS ONLY, and that is a decision rather than an
    oversight. The summary bar exists to say what is still outstanding: S2-02 prints "Prior to docs
    open 1", which is a different number from "how many prior-to-docs conditions this file has ever
    had". Info-only rows are in none of them, because `is_open` is never true for one — so
    `by_prep_status` needs no exclusion of its own (an earlier version carried one, which could not
    change any number).

    The two headline bucket numbers are LOOKUPS INTO `by_bucket_kind`, never separate counts, so they
    cannot drift from the breakdown the filter row reads.
    """
    open_conditions = [condition for condition in conditions if is_open(condition)]

    by_prep_status: dict[str, int] = defaultdict(int)
    by_owner: dict[str, int] = defaultdict(int)
    by_bucket_kind: dict[str, int] = defaultdict(int)
    for condition in open_conditions:
        by_prep_status[condition.prep_status.value] += 1
        by_owner[effective_owner(condition).value] += 1
        by_bucket_kind[condition.bucket_kind.value] += 1

    def lender_status_count(status: ConditionLenderStatus) -> int:
        return sum(1 for condition in conditions if condition.lender_status is status)

    return ConditionSummary(
        total=len(conditions),
        open=len(open_conditions),
        cleared=lender_status_count(ConditionLenderStatus.CLEARED),
        waived=lender_status_count(ConditionLenderStatus.WAIVED),
        not_cleared=lender_status_count(ConditionLenderStatus.NOT_CLEARED),
        superseded=lender_status_count(ConditionLenderStatus.SUPERSEDED),
        info_only=sum(1 for condition in conditions if condition.info_only),
        by_prep_status=dict(by_prep_status),
        by_owner=dict(by_owner),
        by_bucket_kind=dict(by_bucket_kind),
        open_prior_to_docs=by_bucket_kind.get(BucketKind.PRIOR_TO_DOCS.value, 0),
        open_prior_to_funding=by_bucket_kind.get(BucketKind.PRIOR_TO_FUNDING.value, 0),
        # 0 UNTIL LP-915 WRITES ONE. Named with its producer rather than left to look measured: that
        # ticket's comparison is the only thing that may propose "probably cleared", and until it
        # lands this number is honestly nothing rather than possibly something.
        pending_suggestions=0,
    )


async def condition_summary(db: AsyncSession, *, loan_file_id: UUID) -> ConditionSummary:
    """The file's counts, from one query.

    COUNTED IN PYTHON OVER THE WHOLE SET rather than as a dozen aggregates. A file carries 5 to 60
    conditions and the cap is 500, so loading them is cheap — and every aggregate would be another
    place for "open" to be spelled differently from :func:`is_open`, which is the one definition the
    row and the bar must share.
    """
    return summarise_conditions(await list_conditions(db, loan_file_id=loan_file_id))


async def imported_rounds_oldest_first(
    db: AsyncSession, *, loan_file_id: UUID
) -> list[ConditionRound]:
    """The file's IMPORTED rounds, by round number — a condition's own story reads forwards (S2-03).

    NOT `list_rounds`, and the difference is the defect LP-911's review found. `list_rounds` returns
    every round the strip shows — drafts, failed parses and discarded sheets included, newest
    CREATED first. The detail sheet reversed it and listed them all, so a draft still under review
    rendered as a round this condition was "not on", and a round imported out of creation order sat in
    the wrong place. Spec §LP-916: "one line per imported round".
    """
    stmt = select(ConditionRound).where(
        ConditionRound.loan_file_id == loan_file_id,
        ConditionRound.status == ConditionRoundStatus.IMPORTED,
    )
    stmt = only_active(stmt, ConditionRound).order_by(ConditionRound.round_number.asc())
    return list((await db.execute(stmt)).scalars().all())


async def latest_imported_round(db: AsyncSession, *, loan_file_id: UUID) -> ConditionRound | None:
    """The file's highest-numbered imported round, or None if no sheet has ever been imported.

    MOVED HERE FROM `condition_import._latest_imported_round` (LP-911), which now imports it from
    this module. One question asked in two places is how the two come to answer differently, and this
    module is the one that owns reading rounds — the same argument that moved `ENQUEUE_FAILED_DETAIL`
    into a service once both `tasks` and `api` needed it.

    It feeds the summary's `latest_round` (the rail's "from round 2, printed 09/10") and, in
    `condition_import`, the round a hand-typed condition is filed into.
    """
    stmt = select(ConditionRound).where(
        ConditionRound.loan_file_id == loan_file_id,
        ConditionRound.status == ConditionRoundStatus.IMPORTED,
    )
    stmt = only_active(stmt, ConditionRound).order_by(ConditionRound.round_number.desc())
    # Annotated rather than returned straight: `db.scalar` degrades to `Any` once the select has been
    # chained, and returning that from a function declared `ConditionRound | None` is what mypy's
    # `no-any-return` exists for.
    latest: ConditionRound | None = await db.scalar(stmt)
    return latest


__all__ = [
    "APPEARED_ON",
    "MAX_CONDITIONS",
    "OPEN_LENDER_STATUSES",
    "ConditionFilters",
    "ConditionSummary",
    "appearances_for_file",
    "condition_days_open",
    "condition_summary",
    "effective_owner",
    "effective_owner_source",
    "events_for_condition",
    "import_counts",
    "import_counts_for_file",
    "imported_rounds_oldest_first",
    "is_open",
    "latest_imported_round",
    "list_conditions",
    "list_conditions_filtered",
    "list_rounds",
    "rows_on_sheet",
    "summarise_conditions",
]
