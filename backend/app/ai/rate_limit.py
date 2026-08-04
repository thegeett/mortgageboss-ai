"""Client-side request pacing for model calls (B1).

Retrying a 429 works, but a rejected request still counts against the quota — so a burst
against a low ceiling spends most of its allowance on rejections. This paces requests
BEFORE they are sent instead. A fresh Bedrock account is at **10 RPM**, where burst
extraction throttles continuously, so this is the common path there, not an edge case.

**Spacing, not a bucket.** The limiter enforces a minimum interval between call STARTS
(``60 / rpm`` seconds). A token bucket would allow a burst up to the bucket size and then
stall — which is precisely the shape that trips a per-minute server-side quota. Even
spacing keeps the instantaneous rate under the ceiling at every instant, which is what the
provider actually measures.

⚠️ **PROCESS-LOCAL.** This paces one process. Under N Celery worker tasks the effective
rate is **N x the setting**. The deployed value must therefore be *the account quota
divided by the task count*, never the quota itself — two tasks each pacing at 8 against a
10 RPM account still throttle, and it looks like a broken limiter. There is no shared
state here by design: a distributed limiter needs Redis coordination on the hot path of
every model call, which is a different (and much heavier) decision.

A wait is logged at INFO with its duration, so pacing is visible as pacing rather than
looking like a hang.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)

_SECONDS_PER_MINUTE = 60.0


class RateLimiter:
    """Enforces a minimum interval between acquisitions. Process-local, async-safe.

    The clock and sleep are injectable so the behaviour can be tested against a fake
    clock — a test that genuinely slept to prove a 10 RPM limiter would take minutes.
    """

    def __init__(
        self,
        requests_per_minute: int | None,
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._rpm = requests_per_minute
        # time.monotonic, NOT loop.time(): the Celery bridge runs a fresh event loop per
        # task (app/tasks/base.py:41-43) and loop.time() restarts with it, which would let
        # each new task fire immediately and defeat the pacing across a burst of tasks.
        self._clock = clock or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._next_allowed_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def interval_seconds(self) -> float:
        """Minimum spacing between calls; ``0.0`` when unlimited."""
        if not self._rpm or self._rpm <= 0:
            return 0.0
        return _SECONDS_PER_MINUTE / float(self._rpm)

    async def acquire(self, *, label: str = "ai_call") -> float:
        """Wait until the next call is permitted. Returns the seconds actually waited.

        ``None``/non-positive RPM is unlimited and returns immediately, so the default
        configuration imposes no delay and no lock contention beyond one uncontended
        acquire.
        """
        interval = self.interval_seconds
        if interval <= 0.0:
            return 0.0

        async with self._lock:
            now = self._clock()
            wait = self._next_allowed_at - now
            if wait > 0:
                # INFO, not debug: at a low ceiling this is the dominant latency term, and
                # an operator staring at a slow run needs to see pacing rather than guess.
                logger.info("ai_rate_limit_wait", label=label, wait_seconds=round(wait, 3))
                await self._sleep(wait)
                start = self._next_allowed_at
            else:
                wait = 0.0
                start = now
            self._next_allowed_at = start + interval
            return wait


# The process-wide limiter, rebuilt when the resolved RPM changes (a settings monkeypatch
# in tests, or a provider flip). Keyed on the value so a flip cannot keep pacing at the
# other provider's ceiling.
_limiter: RateLimiter | None = None
_limiter_rpm: int | None = None


def get_rate_limiter() -> RateLimiter:
    """The process-local limiter for the ACTIVE provider (see ``resolve_requests_per_minute``)."""
    global _limiter, _limiter_rpm
    from app.core.config import resolve_requests_per_minute

    rpm = resolve_requests_per_minute()
    if _limiter is None or rpm != _limiter_rpm:
        _limiter = RateLimiter(rpm)
        _limiter_rpm = rpm
    return _limiter


def reset_rate_limiter() -> None:
    """Drop the cached limiter (tests, and any settings change)."""
    global _limiter, _limiter_rpm
    _limiter = None
    _limiter_rpm = None


__all__ = ["RateLimiter", "get_rate_limiter", "reset_rate_limiter"]
