"""Bounded concurrent dispatch for AI calls (LP-644 §2), generalising LP-635's Stage-B shape.

**The same questions, asked at the same time as each other rather than one after the next.** No
prompt, context or resolution logic changes, so a verdict cannot move — that argument is LP-644's
§0 and it is the whole reason §2 is safe. What makes it hold in practice is the split this module
enforces:

    PLAN the calls  ->  DISPATCH them concurrently  ->  APPLY the outcomes IN THE ORIGINAL ORDER

Only the middle step is concurrent. Outcomes come back in input order, so the caller's apply loop
sees exactly the sequence it saw when the calls were serial — which is what keeps the caches, the
token totals, the model attribution and the BREAKER deterministic. "Five consecutive failures" keeps
the meaning it was given rather than depending on which coroutine happened to finish first.

THE THREE DETAILS LP-635 PAID FOR, carried over rather than rediscovered:

1. **The gate stops DISPATCH, not just counting.** The breaker is fed in the caller's apply loop,
   which does not begin until every call has returned — so without a gate, an outage dispatches the
   whole stage before the first failure is counted, each call exhausting its retries with backoff.
   The gate closes after ``stop_after_failures`` consecutive failures and the remaining calls are
   never made. Calls already in flight are allowed to finish, so the bound on what an outage costs
   is the threshold plus one semaphore's worth — not the stage.
2. **An outcome is applied once per CALL, not once per subject sharing it.** This module returns one
   outcome per planned call; de-duplication of subjects onto calls is the caller's job and must
   happen BEFORE planning, or a shared judgement is counted twice.
3. **``gather`` collects before re-raising.** A bare ``gather`` propagates the first exception
   WITHOUT cancelling its siblings, leaving model calls running against a caller that has already
   unwound: billed, unawaited, and surfacing later as "Task exception was never retrieved".

An ``AIClientError`` is RETURNED, never raised, so one unreachable call cannot cancel the siblings
that were about to succeed. Any OTHER exception is a bug rather than an outage: it closes the gate
and propagates — but only after the siblings have been collected.

⚠️ NOT USED BY STAGE B, DELIBERATELY. ``tag_correlation._judge_concurrently`` is the original of this
pattern and is left alone: it is live, it was reviewed into its current shape by LP-635, and its
``_NotAttempted`` sentinel carries a processor-facing reason string this module has no business
knowing. Unifying them is a worthwhile follow-up and a bad thing to attempt in the same change that
introduces concurrency to three new places.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Generic, TypeVar

from app.ai.client import AIClientError

R = TypeVar("R")


@dataclass(frozen=True)
class CallOutcome(Generic[R]):
    """One dispatched call's result, in the caller's original order.

    Exactly one of ``result`` / ``error`` is set when ``attempted``; both are ``None`` when the
    dispatch gate closed before this call was made.
    """

    result: R | None
    error: AIClientError | None
    #: Wall time of THIS call alone. Measured inside the semaphore, so a coroutine's wait for a slot
    #: is not charged to the model — see `StageMetrics` for why that distinction matters (LP-644 §1).
    seconds: float
    #: False when the gate closed first. The caller decides what an unmade call means for its
    #: subjects; this module will not invent a verdict for one.
    attempted: bool

    @property
    def not_attempted(self) -> bool:
        return not self.attempted


async def dispatch_bounded(
    calls: Sequence[Callable[[], Awaitable[R]]],
    *,
    concurrency: int,
    stop_after_failures: int | None = None,
) -> list[CallOutcome[R]]:
    """Run ``calls`` concurrently under a bound, returning outcomes IN INPUT ORDER.

    ``calls`` are zero-argument coroutine factories, so nothing is started until this function
    decides to start it — which is what lets the gate skip a call rather than cancel one.

    ``stop_after_failures`` is opt-in because only a caller holding a breaker can act on a closed
    gate. With no gate the pass runs to completion and the caller resolves the failures its own way
    — cheaper than grinding, and silent, which is the worse half of the two failures a stage can
    have.
    """
    if not calls:
        return []
    # Never below 1: a zero or negative bound makes `Semaphore` block forever, so a misconfigured
    # value would hang the pass until the Celery soft limit rather than fail — and the wrong SHAPE of
    # failure is exactly what LP-635 was opened to diagnose. Degrading to sequential is slow and
    # correct.
    semaphore = asyncio.Semaphore(max(1, concurrency))
    consecutive_failures = 0
    gate_closed = False

    async def run(index: int) -> tuple[int, CallOutcome[R]]:
        nonlocal consecutive_failures, gate_closed
        # Checked before AND after acquiring: a coroutine can wait a long time for its slot, and the
        # gate may well have closed while it did.
        if gate_closed:
            return index, CallOutcome(None, None, 0.0, attempted=False)
        async with semaphore:
            if gate_closed:
                return index, CallOutcome(None, None, 0.0, attempted=False)
            started = perf_counter()
            try:
                result = await calls[index]()
            except AIClientError as err:
                consecutive_failures += 1
                if stop_after_failures is not None and consecutive_failures >= stop_after_failures:
                    gate_closed = True
                return index, CallOutcome(None, err, perf_counter() - started, attempted=True)
            except Exception:
                gate_closed = True  # a bug, not an outage — stop spending on a discarded result
                raise
            consecutive_failures = 0
            return index, CallOutcome(result, None, perf_counter() - started, attempted=True)

    collected = await asyncio.gather(*(run(i) for i in range(len(calls))), return_exceptions=True)
    outcomes: list[CallOutcome[R] | None] = [None] * len(calls)
    first_error: BaseException | None = None
    for item in collected:
        if isinstance(item, BaseException):
            # Collect them ALL before re-raising (detail 3): returning here would leave siblings
            # running against an unwound caller. The first is raised, matching a serial loop, which
            # would have stopped at the first too.
            if first_error is None:
                first_error = item
            continue
        index, outcome = item
        outcomes[index] = outcome
    if first_error is not None:
        raise first_error
    # Unreachable unless a coroutine both returned nothing and raised nothing.
    return [o if o is not None else CallOutcome(None, None, 0.0, attempted=False) for o in outcomes]


__all__ = ["CallOutcome", "dispatch_bounded"]
