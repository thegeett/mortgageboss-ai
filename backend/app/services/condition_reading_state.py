"""Where the reading of a file's conditions stands, and Read again (LP-952, trial items 4 and 5).

The reading (LP-919) was queued in one place, import, and recorded only when it ENDED
(`condition_rounds.reading_run`). So the screen could not tell "being read" from "never queued" (LF-DH8V's
round 1, imported before the reading existed) from "failed", and showed nothing in all three cases. Now:

- every door that queues a reading marks the round **queued** first (`mark_queued`), the task marks it
  **reading** when it starts and **done** when it ends, and a final failure marks it **failed**;
- `reading_state` reports that, plus how many of the file's conditions are still unread, and reports a
  queued or running reading older than `STALE_AFTER` as **failed** ("stalled"), so a lost task never
  leaves the screen waiting forever;
- `POST /condition-rounds/{id}/read` (the route) is "Read conditions" and "Read again": refused while a
  reading is queued or running, refused when nothing is unread. It never re-reads a read or confirmed
  condition, because `read_round` takes only `unread` ones.

`reading_run` keeps its shape: the end-of-run record (`RoundReading.as_run`) gains `state`; the earlier
states are small records `{state, at}` with an `error` when failed. A run written before LP-952 has no
`state` and reads as done.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.condition import (
    Condition,
    ConditionLenderStatus,
    ConditionReadingSource,
    ConditionReadingStatus,
)
from app.models.condition_round import ConditionRound
from app.models.helpers import only_active

QUEUED = "queued"
READING = "reading"
DONE = "done"
FAILED = "failed"
#: Unread conditions and nothing queued: the case the trial found (a sheet imported before the reading
#: existed, or a broker that refused the task). Offered "Read conditions".
NOT_QUEUED = "not_queued"

#: A queued or running reading older than this is reported failed. The task's hard limit is minutes; a
#: reading this old is a lost task, and "Read again" must be offered rather than a spinner for ever.
STALE_AFTER = timedelta(minutes=15)


def _now() -> datetime:
    return datetime.now(UTC)


def mark(round_: ConditionRound, state: str, *, error: str | None = None) -> None:
    """Record a state on the round. Flushes nothing; the caller commits."""
    record: dict[str, Any] = {"state": state, "at": _now().isoformat()}
    if error:
        record["error"] = error[:200]
    round_.reading_run = record


async def unread_count(db: AsyncSession, *, loan_file_id: Any) -> int:
    count = await db.scalar(
        only_active(
            select(func.count(Condition.id)).where(
                Condition.loan_file_id == loan_file_id,
                Condition.reading_status == ConditionReadingStatus.UNREAD,
                Condition.lender_status != ConditionLenderStatus.SUPERSEDED,
            ),
            Condition,
        )
    )
    return int(count or 0)


#: LP-973 — conditions read without the AI, and untouched since: offered "Read again".
WITHOUT_AI = "without_ai"


async def read_without_ai(db: AsyncSession, *, loan_file_id: Any) -> list[Condition]:
    """LP-973 — the file's conditions the AI did NOT read, that a fresh reading can safely replace.

    WHY THESE ARE NOT "UNREAD". When the model call fails (an expired AWS login, a timeout), `read_round`
    still reads every condition, from the library alone: `reading_source` LIBRARY, `NEEDS_CONFIRMATION`
    (`compose_reading` never passes the bar without the AI), and since LP-965 no type, so at most one
    generic task from the sheet's owner hint. The round is recorded as read, nothing is unread, and
    LP-952's Read again (which reads only `unread`) had nothing to offer.

    SAFE MEANS NOTHING OF HERS IS LOST. A condition qualifies only while it is exactly what the fallback
    left: not confirmed (her answer wins over any reading), every task OPEN and from the reading (none
    she added, none asked, answered or marked), no plan change of hers (`condition_plan_changed`, other
    than an earlier Read again's own), and NO DOCUMENT SHE HAS UNLINKED.

    THE UNLINK RULE IS THE ONE THE OTHER THREE DO NOT CATCH (LP-973 review). `condition_item_unlinks` is
    keyed `(item_id, document_id)`, and `clear_for_reading` soft-deletes the items, so a refusal of hers
    would be stranded on an id nothing reads while the fresh reading mints new ones — after which the
    arrival door re-links the document she removed. That is the LP-953 finding reached through this door.
    Nothing else here sees it: `unlink_document` deletes the evidence row, recomputes the task to OPEN
    when nothing else answers it, and records `condition_evidence_unlinked` rather than a plan change —
    so a condition she linked and then unlinked a document on satisfies every other rule. Her refusal is
    work, so the condition keeps its plan.
    """
    from app.models.condition_event import ConditionEvent, ConditionEventKind
    from app.models.condition_evidence import ConditionItemUnlink
    from app.models.condition_item import ConditionItem
    from app.models.condition_vocabulary import ConditionItemOrigin, ConditionItemStatus

    candidates = list(
        await db.scalars(
            only_active(
                select(Condition).where(
                    Condition.loan_file_id == loan_file_id,
                    Condition.reading_source == ConditionReadingSource.LIBRARY,
                    Condition.reading_status == ConditionReadingStatus.NEEDS_CONFIRMATION,
                    Condition.lender_status != ConditionLenderStatus.SUPERSEDED,
                ),
                Condition,
            ).order_by(Condition.sequence, Condition.created_at)
        )
    )
    if not candidates:
        return []
    ids = [condition.id for condition in candidates]
    worked: set[Any] = set()
    for item in await db.scalars(
        select(ConditionItem).where(
            ConditionItem.condition_id.in_(ids), ConditionItem.deleted_at.is_(None)
        )
    ):
        if (
            item.status is not ConditionItemStatus.OPEN
            or item.origin is not ConditionItemOrigin.READING
        ):
            worked.add(item.condition_id)
    for event in await db.scalars(
        select(ConditionEvent).where(
            ConditionEvent.condition_id.in_(ids),
            ConditionEvent.kind == ConditionEventKind.CONDITION_PLAN_CHANGED,
        )
    ):
        if (event.detail or {}).get("change") != READ_AGAIN_CHANGE:
            worked.add(event.condition_id)
    # A DOCUMENT SHE UNLINKED (LP-973 review). Joined through the items because the row is keyed on the
    # item, and soft-deleted items count: a refusal stranded by an earlier clear is still hers.
    for condition_id in await db.scalars(
        select(ConditionItem.condition_id)
        .join(ConditionItemUnlink, ConditionItemUnlink.item_id == ConditionItem.id)
        .where(ConditionItem.condition_id.in_(ids))
    ):
        worked.add(condition_id)
    return [condition for condition in candidates if condition.id not in worked]


#: The plan-change a Read again records; the one plan change that does not make a condition "worked".
READ_AGAIN_CHANGE = "read_again"


async def clear_for_reading(
    db: AsyncSession, *, conditions: list[Condition], actor_user_id: Any
) -> None:
    """LP-973 — put conditions read without the AI back to UNREAD, so `read_round` reads them again.

    Their reading and its plan go: the reading is replaced, and the fallback's generic task is soft-
    deleted, because `build_plan` plans only a condition with no task and no step (`_is_planned`) and
    would otherwise keep the guess. The drafts follow (`follow_drafts`), so a removed task leaves the
    email it was in. Each condition records a `condition_plan_changed` `read_again`. Flushes; the caller
    commits.
    """
    from app.models.condition_event import ConditionEvent, ConditionEventKind
    from app.models.condition_item import ConditionItem
    from app.services.condition_plan import follow_drafts

    now = _now()
    for condition in conditions:
        removed = 0
        for item in await db.scalars(
            select(ConditionItem).where(
                ConditionItem.condition_id == condition.id, ConditionItem.deleted_at.is_(None)
            )
        ):
            item.deleted_at = now
            removed += 1
        condition.next_step = None
        condition.reading = None
        condition.reading_source = None
        condition.reading_confidence = None
        condition.reading_status = ConditionReadingStatus.UNREAD
        db.add(
            ConditionEvent(
                company_id=condition.company_id,
                loan_file_id=condition.loan_file_id,
                condition_id=condition.id,
                round_id=condition.last_seen_round_id,
                kind=ConditionEventKind.CONDITION_PLAN_CHANGED,
                actor_user_id=actor_user_id,
                detail={"change": READ_AGAIN_CHANGE, "items_removed": removed},
            )
        )
        await db.flush()
        await follow_drafts(db, condition=condition, actor_user_id=actor_user_id)


def _state_of(run: dict[str, Any] | None, *, now: datetime) -> tuple[str | None, str | None]:
    """The recorded state and error, with a stale queued/running one reported as failed."""
    if not run:
        return None, None
    state = run.get("state")
    if state is None:
        # Written before LP-952: an end-of-run record.
        return DONE, run.get("error")
    if state in (QUEUED, READING):
        try:
            at = datetime.fromisoformat(str(run.get("at")))
        except ValueError:
            return FAILED, "stalled"
        if now - at > STALE_AFTER:
            return FAILED, "stalled"
    return str(state), run.get("error")


async def reading_state(db: AsyncSession, *, round_: ConditionRound) -> dict[str, Any]:
    """`ReadingStatePublic`'s data for a round's FILE: its reading's state and the unread count.

    THE FILE'S READING, NOT THIS ROUND'S RECORD (LP-952 review). A reading is file-wide (`read_round`
    reads every unread condition on the file), and it is recorded on the round a door queued it on. So
    the state reported is the file's running reading wherever it is recorded, else the newest imported
    round's record, which is the round every door now queues on. Read from the asked round alone, an
    older round imported after a newer draft said "not read" beside a running reading, and offered a
    second one.
    """
    unread = await unread_count(db, loan_file_id=round_.loan_file_id)
    without_ai = len(await read_without_ai(db, loan_file_id=round_.loan_file_id))
    source = (
        await running_round(db, loan_file_id=round_.loan_file_id)
        or await newest_imported_round(db, loan_file_id=round_.loan_file_id)
        or round_
    )
    state, error = _state_of(source.reading_run, now=_now())
    if state in (None, DONE) and unread:
        # Read once, then more arrived unread (or never queued at all): offer to read them.
        state = NOT_QUEUED
    if state == FAILED and not unread:
        # A failure with nothing left to read (another door read them since): "N still unread" would
        # be false, and its Read again would be refused as nothing_unread (LP-952 review).
        state = DONE
    if state is None:
        state = DONE
    if state == DONE and without_ai:
        # LP-973 — read, but some of it without the AI: offer to read those again.
        state = WITHOUT_AI
    return {
        "state": state,
        "unread": unread,
        "without_ai": without_ai,
        "error": error if state == FAILED else None,
    }


def is_running(round_: ConditionRound) -> bool:
    """A reading queued or running, and not stale: a second one must not start beside it."""
    state, _ = _state_of(round_.reading_run, now=_now())
    return state in (QUEUED, READING)


async def newest_imported_round(db: AsyncSession, *, loan_file_id: Any) -> ConditionRound | None:
    from app.models.condition_round import ConditionRoundStatus

    newest: ConditionRound | None = await db.scalar(
        only_active(
            select(ConditionRound)
            .where(
                ConditionRound.loan_file_id == loan_file_id,
                ConditionRound.status == ConditionRoundStatus.IMPORTED,
            )
            .order_by(ConditionRound.created_at.desc(), ConditionRound.id.desc())
            .limit(1),
            ConditionRound,
        ).execution_options(populate_existing=True)
    )
    return newest


async def running_round(db: AsyncSession, *, loan_file_id: Any) -> ConditionRound | None:
    """The file's round whose reading is queued or running (not stale), or None (LP-952 review).

    FILE-WIDE, because a reading is: a door that checked only its own round started a second reading
    beside one recorded on another round. `populate_existing` so a caller holding the file lock sees
    the committed record, not the session's cached one.
    """
    rounds = (
        await db.scalars(
            only_active(
                select(ConditionRound)
                .where(ConditionRound.loan_file_id == loan_file_id)
                .order_by(ConditionRound.created_at.desc(), ConditionRound.id.desc()),
                ConditionRound,
            ).execution_options(populate_existing=True)
        )
    ).all()
    return next((r for r in rounds if is_running(r)), None)
