"""Reading a file's rounds and conditions (LP-909 section 1, spec §LP-909).

⚠️ TWO FIELDS HERE HAVE EXISTED SINCE LP-904 WITH NOTHING TO FILL THEM, which is the same shape as
`text_fingerprint` — a column declared, documented, indexed and never written, green because nothing
executed it. `ConditionRoundPublic.condition_count` defaults to 0 and `ConditionPublic.round_numbers`
to `[]`, and until this module the only producer of either was the default. A round strip rendering
`0 on sheet` and `R1 R2` chips that never appear would have looked like a UI bug for as long as
anyone cared to look.

⚠️ AND THEY ARE THE SAME JOIN, READ IN OPPOSITE DIRECTIONS. A condition "appeared on" a round exactly
when the round's import wrote a `CONDITION_CREATED` or `CONDITION_SEEN_AGAIN` event naming both. Ask
it per condition and you get the `R1 R2` chips; ask it per round and you get the round card's count.
So ONE query answers both, which is the point: the alternative is a query per row, and this repo has
a named precedent for refusing that (`_completed_documents`, loaded once, "LP-109, no N+1").

WHY EVENTS RATHER THAN A JOIN TABLE. The spec offers either — "from its `CONDITION_CREATED` /
`CONDITION_SEEN_AGAIN` events, or from a join table if the survey finds one is simpler". The events
already exist, are append-only, and are written by the import as its audit record; a join table would
be a second statement of the same fact, maintained beside it, free to disagree. The event IS the
record that a condition was on a sheet.
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.condition import Condition
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import ConditionRound, ConditionRoundStatus
from app.models.helpers import only_active

#: The two events that mean "this condition was on this sheet". `CONDITION_NOTE_ADDED` and
#: `CONDITION_EDITED` are deliberately absent: a note appended or a wording corrected says the
#: condition CHANGED, not that it appeared on another round, and counting them would put a round
#: number on a chip for a sheet the condition was never printed on.
APPEARED_ON = (ConditionEventKind.CONDITION_CREATED, ConditionEventKind.CONDITION_SEEN_AGAIN)


async def list_rounds(db: AsyncSession, *, loan_file_id: UUID) -> list[ConditionRound]:
    """The file's active rounds, newest first.

    ⚠️ DISCARDED ROUNDS ARE INCLUDED, and that is deliberate rather than an oversight. A processor
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
        # ⚠️ DEFENCE, NOT A DESCRIBED CASE — and an earlier comment here claimed otherwise, saying a
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

    ⚠️ THE FIRST READER `ix_condition_events_round_occurred` HAS EVER HAD, AND THAT IS THE POINT.
    LP-904 declared that index with the comment "One round's history in time order — the shape the
    round-details sheet reads (S1-09)", and no such reader was ever written. So the index paid a
    write on every event insert — per created condition, per seen-again, per note, per round
    transition — to serve a query nobody made. `(round_id, occurred_at)` is exactly this ordering, so
    this function is what finally makes that cost buy something.

    ⚠️ ITS SIBLING STILL HAS NO READER. `ix_condition_events_condition_occurred` is
    `(condition_id, occurred_at)` — a single CONDITION's history in time order, which is a different
    question from a round's and which nothing in this codebase asks. It does not get this function's
    justification, and it is named here so the next person to look does not assume it did.

    ⚠️ NEWEST FIRST, BECAUSE THE DESIGN DECIDED IT. The first version was oldest-first, argued from
    first principles: "a history is read downwards as a sequence". But S1-09's mock runs
    `4:31 → 4:22 → 4:20`, and its *May differ* covers only the sheet width and whether times show —
    so the order is a Must-match, and reasoning my way to the other answer was re-deciding something
    the design pack had already settled. Raised in review; as built the Visual check would have failed.

    ⚠️ ROUND-LEVEL EVENTS ONLY — `condition_id IS NULL`. Without this a 30-row import renders thirty
    "A condition was added" lines and the panel the README calls "a SHORT history" is anything but:
    measured on a real paste → import → paste → import flow, round 2 came back with NINE lines, six of
    them detail-less `CONDITION_SEEN_AGAIN`.

    The cost, stated rather than hidden: a condition typed by hand into an existing imported round
    writes only `CONDITION_CREATED`, so it leaves no round-level trace and does not appear here. That
    is the right trade for a panel about the ROUND, and it is recorded in LP-909 rather than left for
    someone to discover.

    The index still serves this: `(round_id, occurred_at)` is used as a prefix, with the null check as
    a filter.

    ⚠️ NO COMPANY FILTER HERE, AND THAT IS NOT AN OMISSION. The caller resolves the round through
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


def rows_on_sheet(round_: ConditionRound, imported_counts: dict[UUID, int]) -> int:
    """How many conditions this round carried — "11 on sheet" on the round card.

    ⚠️ THE ANSWER COMES FROM A DIFFERENT PLACE DEPENDING ON STATUS, and conflating them would make a
    draft look empty. Before import the rows live in `draft_rows` and no `Condition` exists yet;
    after import the rows ARE conditions and `draft_rows` is cleared. So a draft counts its rows and
    an imported round counts its appearances.
    """
    if round_.status is ConditionRoundStatus.IMPORTED:
        return imported_counts.get(round_.id, 0)
    return len(round_.draft_rows or [])


__all__ = [
    "APPEARED_ON",
    "appearances_for_file",
    "list_conditions",
    "list_rounds",
    "rows_on_sheet",
]
