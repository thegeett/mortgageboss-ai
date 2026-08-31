"""LP-73 bounded-retry policy — a transient blip retries; exhaustion is terminal-visible.

The Phase-2 "stuck pending" footgun: a transient task failure left a file permanently
non-terminal with no retry. These test ``retry_or_terminal`` against a fake Task that
models Celery's ``retry`` contract (raise ``Retry`` to reschedule until ``max_retries``,
then ``MaxRetriesExceededError``), driving it the way a worker would re-run the task.
The needs/document tasks' wiring to it (the visible terminal-failed marker) is covered
by the integration + endpoint tests.
"""

from types import SimpleNamespace

from app.tasks.retry import MAX_RETRIES, retry_countdown, retry_or_terminal
from celery.exceptions import MaxRetriesExceededError, Retry


class _FakeTask:
    """Models Celery's retry contract: reschedule (raise Retry) until exhausted."""

    def __init__(self, max_retries: int) -> None:
        self.max_retries = max_retries
        self.request = SimpleNamespace(retries=0)

    def retry(self, *, exc: BaseException, countdown: int) -> BaseException:
        if self.request.retries >= self.max_retries:
            raise MaxRetriesExceededError
        self.request.retries += 1
        raise Retry(exc=exc, when=countdown)


def _drive(task: _FakeTask, work, on_exhausted) -> str:
    """Re-run the task the way a worker would: loop while it reschedules (Retry)."""
    while True:
        try:
            retry_or_terminal(task, work, on_exhausted=on_exhausted, event="test")
            return "ok"
        except Retry:
            continue  # the worker would re-run with the incremented retry count
        except (TypeError, AttributeError, NameError):
            # LP-635 review — a HARNESS bug, not a task outcome, so it must not be reported as one.
            #
            # `except Exception` alone swallowed the TypeError from calling a zero-arg
            # `on_exhausted` with an argument and returned "terminal", which is a legitimate
            # result — so the suite failed as `assert 0 == 1`, pointing nowhere near a signature
            # mismatch. The tests caught the breakage; the message cost time it should not have.
            #
            # Narrow on purpose: every failure these tests deliberately raise is a RuntimeError or
            # the fake soft-timeout, so nothing legitimate is caught here. A production worker
            # rightly catches everything; a harness pretending to be one should still say when the
            # harness itself is wrong.
            raise
        except Exception:
            return "terminal"


def test_transient_failure_retries_then_succeeds() -> None:
    calls = {"work": 0, "terminal": 0}

    def work() -> None:
        calls["work"] += 1
        if calls["work"] < 2:  # fail once, then succeed
            raise RuntimeError("transient blip")

    result = _drive(_FakeTask(MAX_RETRIES), work, lambda _exc: calls.__setitem__("terminal", 1))

    assert result == "ok"
    assert calls["work"] == 2  # retried once, then succeeded
    assert calls["terminal"] == 0  # never reached the terminal-failed path


def test_exhausted_retries_set_terminal_failed() -> None:
    calls = {"work": 0, "terminal": 0}

    def work() -> None:
        calls["work"] += 1
        raise RuntimeError("persistent failure")

    result = _drive(
        _FakeTask(MAX_RETRIES),
        work,
        lambda _exc: calls.__setitem__("terminal", calls["terminal"] + 1),
    )

    assert result == "terminal"
    # The initial attempt + MAX_RETRIES re-runs, then the terminal-failed marker once.
    assert calls["work"] == MAX_RETRIES + 1
    assert calls["terminal"] == 1  # visible terminal-failed — NOT a silent permanent pending


def test_terminal_on_exception_fails_closed_without_retrying() -> None:
    # LP-377-C: a non-transient failure (e.g. a task SOFT time-limit) must NOT retry — retrying re-runs the
    # same expensive work, times out again, and stacked retries outlast the stuck-run watchdog. It marks
    # terminal ONCE and re-raises.
    class _SoftTimeout(Exception):
        pass

    calls = {"work": 0, "terminal": 0}

    def work() -> None:
        calls["work"] += 1
        raise _SoftTimeout("time limit exceeded")

    result = _drive_terminal(
        _FakeTask(MAX_RETRIES),
        work,
        lambda _exc: calls.__setitem__("terminal", calls["terminal"] + 1),
        terminal_on=(_SoftTimeout,),
    )

    assert result == "terminal"
    assert calls["work"] == 1  # NOT retried — one attempt only
    assert calls["terminal"] == 1  # failed closed immediately


def _drive_terminal(task, work, on_exhausted, *, terminal_on) -> str:
    """Like _drive, but exercises the terminal_on path (never reschedules)."""
    try:
        retry_or_terminal(
            task, work, on_exhausted=on_exhausted, event="test", terminal_on=terminal_on
        )
        return "ok"
    except Retry:  # pragma: no cover - a terminal exception must not reschedule
        return "retried"
    except Exception:
        return "terminal"


def test_a_scheduled_retry_passes_through_untouched() -> None:
    """A ``Retry`` raised inside the work (already scheduled) propagates, not double-handled."""
    task = _FakeTask(MAX_RETRIES)

    def work() -> None:
        raise Retry(exc=RuntimeError("already scheduling"))

    try:
        retry_or_terminal(task, work, on_exhausted=lambda _exc: None, event="test")
    except Retry:
        pass
    else:  # pragma: no cover
        raise AssertionError("Retry should propagate")
    assert task.request.retries == 0  # we did not call .retry() ourselves


def test_retry_countdown_is_bounded_exponential_backoff() -> None:
    assert retry_countdown(0) == 5
    assert retry_countdown(1) == 10
    assert retry_countdown(2) == 20
    assert retry_countdown(10) == 60  # capped
