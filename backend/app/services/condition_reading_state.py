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

from app.models.condition import Condition, ConditionLenderStatus, ConditionReadingStatus
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
    """`ReadingStatePublic`'s data for a round: its reading's state and the file's unread count."""
    unread = await unread_count(db, loan_file_id=round_.loan_file_id)
    state, error = _state_of(round_.reading_run, now=_now())
    if state in (None, DONE) and unread:
        # Read once, then more arrived unread (or never queued at all): offer to read them.
        state = NOT_QUEUED
    if state is None:
        state = DONE
    return {"state": state, "unread": unread, "error": error if state == FAILED else None}


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
        )
    )
    return newest
