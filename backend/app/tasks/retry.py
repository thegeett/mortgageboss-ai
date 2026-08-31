"""Bounded task retry policy (LP-73) — transient blips don't strand a file.

A Phase-2 footgun: a transient failure in a worker task (a DB/Redis blip, a momentary
AI timeout) left the file permanently in a non-terminal state with no auto-retry — the
"stuck pending" case. The fix is a **bounded retry with backoff**: retry a handful of
times, then — on exhaustion — set a **visible terminal-failed state** (never a silent
permanent pending). Tasks use :func:`retry_or_terminal` to wrap their body.
"""

from collections.abc import Callable

import structlog
from celery import Task
from celery.exceptions import MaxRetriesExceededError, Retry

logger = structlog.get_logger(__name__)

#: How many times a transient task failure is retried before it's terminal.
MAX_RETRIES = 3


def retry_countdown(retries: int) -> int:
    """Exponential backoff (5s, 10s, 20s, …) capped at 60s. Jitter is Celery's job."""
    return min(60, 5 * 2**retries)  # type: ignore[no-any-return]


def retry_or_terminal(
    task: Task,
    work: Callable[[], None],
    *,
    on_exhausted: Callable[[BaseException], None],
    event: str,
    terminal_on: tuple[type[BaseException], ...] = (),
) -> None:
    """Run ``work``; on a transient error retry with backoff, and on exhaustion run
    ``on_exhausted`` (the terminal-failed marker) before failing.

    ``task`` is the bound Celery task (``bind=True``). ``Retry`` propagates so Celery
    reschedules; once ``MAX_RETRIES`` is hit, ``on_exhausted`` records the visible
    terminal state and the original error re-raises (the task is marked FAILURE).

    ``on_exhausted`` RECEIVES THE EXCEPTION (LP-635). It used to take no arguments, so a marker
    could only write a generic string — and because this function calls it from BOTH branches, the
    rule engine's marker said "failed after retries" for `terminal_on` failures that are never
    retried. Worse, it threw away the only text that could tell a processor what to do: the AI
    breaker composes "the backend failed N calls in a row… re-run once it is reachable" and nothing
    could carry it to the run's user-visible ``error_detail``. Widening the signature is what lets a
    marker say something true and specific; a marker that does not care can ignore the argument.

    ``terminal_on`` exceptions are NOT transient and are NEVER retried — they mark terminal
    (``on_exhausted``) immediately and re-raise. A task TIME LIMIT belongs here: a retry re-runs the
    same expensive work and will time out again, and stacked retries can outlast the stuck-run watchdog
    (LP-377-C). Default ``()`` catches nothing — unchanged behaviour for callers that don't pass it.
    """
    try:
        work()
    except Retry:
        raise  # a retry we (or Celery) already scheduled — let it through
    except terminal_on as exc:
        logger.error(event, terminal=True)  # not transient — fail closed, no retry
        on_exhausted(exc)
        raise
    except Exception as exc:
        retries = task.request.retries or 0
        try:
            raise task.retry(exc=exc, countdown=retry_countdown(retries))
        except MaxRetriesExceededError:
            logger.error(event, retries=retries)
            on_exhausted(exc)
            raise exc from None
