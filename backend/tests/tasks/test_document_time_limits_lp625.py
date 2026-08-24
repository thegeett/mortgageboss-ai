"""LP-625 — the document task could not finish inside the limit it inherited.

A test about a Celery decorator looks like testing the framework. It is not: the value is a
MEASUREMENT, the measurement was wrong, and being wrong did not raise — it killed a task that was
working correctly and restarted it until the retry budget ran out, then marked the document FAILED.
Nothing in the suite noticed, because every test document extracts in well under a second.
"""

from __future__ import annotations

from app.tasks.celery_app import celery_app
from app.tasks.document_processing import (
    DOCUMENT_HARD_LIMIT_SECONDS,
    DOCUMENT_SOFT_LIMIT_SECONDS,
    process_document,
    reprocess_document,
)

#: The worst path measured on staging (LF-AWBB, 2026-08-23): classification ~8s, extraction at
#: max_tokens=16384 65s, then the truncation retry at 32768 longer again. Rounded up.
_MEASURED_WORST_SECONDS = 220


def test_the_document_task_does_not_inherit_the_global_limit() -> None:
    """The global default is sized for a task that does NO AI work.

    Inheriting it is what broke this: `documents.process_document` was killed mid-truncation-retry,
    restarted from classification, and truncated again — 8 classifications and 7 soft-limit kills
    across 4 bank statements before MAX_RETRIES ran out.
    """
    default_soft = celery_app.conf.task_soft_time_limit

    assert process_document.soft_time_limit is not None, "the task must state its own limit"
    assert process_document.soft_time_limit != default_soft
    assert process_document.soft_time_limit == DOCUMENT_SOFT_LIMIT_SECONDS


def test_the_limit_clears_the_measured_worst_path() -> None:
    """Generously, the way RULE_ENGINE_SOFT_LIMIT_SECONDS clears its own measurement.

    The ceiling only has to be high enough that a legitimate document finishes; a task that genuinely
    hangs is caught by the hard limit, not by a tight soft one.
    """
    assert DOCUMENT_SOFT_LIMIT_SECONDS > _MEASURED_WORST_SECONDS * 2


def test_the_hard_limit_leaves_room_for_the_graceful_mark() -> None:
    """Soft raises inside the task so it can mark itself; hard is the SIGKILL ceiling above it."""
    assert DOCUMENT_HARD_LIMIT_SECONDS > DOCUMENT_SOFT_LIMIT_SECONDS


def test_reprocessing_gets_the_same_ceiling() -> None:
    """It runs the same extractor, so it meets the same truncation retry."""
    assert reprocess_document.soft_time_limit == DOCUMENT_SOFT_LIMIT_SECONDS
    assert reprocess_document.time_limit == DOCUMENT_HARD_LIMIT_SECONDS


def test_a_timeout_is_terminal_and_is_never_retried() -> None:
    """The half a raised ceiling does not fix — and the half that made it dangerous to raise alone.

    `SoftTimeLimitExceeded` fell into `retry_or_terminal`'s generic transient branch, so Celery re-ran
    the task FROM THE TOP: re-classify, re-extract, truncate, be killed, repeat. Retrying a timeout
    cannot work — nothing about the document changed, so the same work takes the same time and meets
    the same wall. It only multiplies the cost.

    And raising the ceiling WITHOUT this would have made the failure worse, not better: four attempts
    at 600s is forty minutes of a serial worker instead of eight, with every other document on the
    file queued behind it. `retry_or_terminal`'s own docstring says a task time limit belongs in
    `terminal_on`; `verification.run_rule_engine` has passed it since LP-377-C.
    """
    import inspect

    from app.tasks import document_processing

    source = inspect.getsource(document_processing)
    assert source.count("terminal_on=(SoftTimeLimitExceeded,)") == 2, (
        "both document tasks must treat a time limit as terminal"
    )
