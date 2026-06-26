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
        except Exception:
            return "terminal"


def test_transient_failure_retries_then_succeeds() -> None:
    calls = {"work": 0, "terminal": 0}

    def work() -> None:
        calls["work"] += 1
        if calls["work"] < 2:  # fail once, then succeed
            raise RuntimeError("transient blip")

    result = _drive(_FakeTask(MAX_RETRIES), work, lambda: calls.__setitem__("terminal", 1))

    assert result == "ok"
    assert calls["work"] == 2  # retried once, then succeeded
    assert calls["terminal"] == 0  # never reached the terminal-failed path


def test_exhausted_retries_set_terminal_failed() -> None:
    calls = {"work": 0, "terminal": 0}

    def work() -> None:
        calls["work"] += 1
        raise RuntimeError("persistent failure")

    result = _drive(
        _FakeTask(MAX_RETRIES), work, lambda: calls.__setitem__("terminal", calls["terminal"] + 1)
    )

    assert result == "terminal"
    # The initial attempt + MAX_RETRIES re-runs, then the terminal-failed marker once.
    assert calls["work"] == MAX_RETRIES + 1
    assert calls["terminal"] == 1  # visible terminal-failed — NOT a silent permanent pending


def test_a_scheduled_retry_passes_through_untouched() -> None:
    """A ``Retry`` raised inside the work (already scheduled) propagates, not double-handled."""
    task = _FakeTask(MAX_RETRIES)

    def work() -> None:
        raise Retry(exc=RuntimeError("already scheduling"))

    try:
        retry_or_terminal(task, work, on_exhausted=lambda: None, event="test")
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
