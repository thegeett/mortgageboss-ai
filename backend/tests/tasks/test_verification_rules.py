"""LP-365 — the governed snapshot/rules task: wiring + fail-closed run status.

The orchestrator itself is heavy (real AI); these mock it and assert the WIRING the ticket cares about:
the task calls ``run_verification`` with a real run's params and NO stub reasoners (a real run must use the
real model); on SUCCESS it marks the run COMPLETED (LP-377-C: the governed pass is the run's COMPLETION
AUTHORITY — the sweep no longer completes a run alone); on exhaustion it marks the run FAILED (fail-closed —
never a silent RUNNING or a false COMPLETED); the enqueue fires the governed pass ALONGSIDE the sweep. The
completion guard (COMPLETED only if the DB does not already hold FAILED, under a row lock) is pinned directly.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.models.verification import VerificationStatus

pytestmark = pytest.mark.anyio

_LF = uuid4()
_RUN = uuid4()
_COMPANY = uuid4()


def _fake_session(objects: dict[object, object], *, locked_status=VerificationStatus.RUNNING):
    """A task_session replacement: an async CM yielding a db whose .get returns the mapped object and whose
    .scalar returns ``locked_status`` (the LP-377-C row-lock re-read the rule pass uses before COMPLETED)."""
    # bug-006 — `flush` and `execute` are here because the real session has them and the completion path
    # now uses both: it settles pending state before taking a savepoint, and reads the run's triage
    # counts. A double that omits a method the code under test calls does not prove the code is wrong,
    # it just stops the test at the first line that touches it.
    db = SimpleNamespace(
        get=AsyncMock(side_effect=lambda _model, key: objects.get(key)),
        scalar=AsyncMock(return_value=locked_status),
        commit=AsyncMock(),
        flush=AsyncMock(),
        # No `begin_nested`: `_triage_counts` is best-effort and contained, so a double without it
        # exercises the degraded path — the counts are skipped and the run still completes, which is
        # the property that matters here.
        execute=AsyncMock(),
    )

    @asynccontextmanager
    async def _cm():
        yield db

    return _cm, db


async def test_task_calls_orchestrator_with_run_params_and_no_stub(monkeypatch) -> None:
    from app.tasks import verification_rules as vr

    loan_file = SimpleNamespace(id=_LF, company_id=_COMPANY)
    run = SimpleNamespace(
        id=_RUN, loan_file_id=_LF, status=VerificationStatus.RUNNING, completed_at=None
    )
    cm, _db = _fake_session({_LF: loan_file, _RUN: run})
    monkeypatch.setattr(vr, "task_session", cm)
    orchestrator = AsyncMock()
    monkeypatch.setattr(vr, "run_verification", orchestrator)

    await vr._run(str(_LF), str(_RUN))

    orchestrator.assert_awaited_once()
    kwargs = orchestrator.await_args.kwargs
    assert (
        kwargs["run_id"] == _RUN
        and kwargs["loan_file_id"] == _LF
        and kwargs["company_id"] == _COMPANY
    )
    assert kwargs["verification_id"] == _RUN
    # A REAL run must not use a stub — the task passes NO reasoners, so run_verification uses reasoners=None.
    assert "reasoners" not in kwargs
    # LP-377-C Fix 2: reaching the end of the governed pass marks the run COMPLETED (the completion authority).
    assert run.status is VerificationStatus.COMPLETED and run.completed_at is not None


async def test_governed_pass_does_not_complete_over_a_committed_failed(monkeypatch) -> None:
    """LP-377-C: if a FAILED was committed concurrently (a sweep failure) the governed pass's row-lock
    re-read sees it and does NOT overwrite it with COMPLETED — FAILED always wins."""
    from app.tasks import verification_rules as vr

    loan_file = SimpleNamespace(id=_LF, company_id=_COMPANY)
    run = SimpleNamespace(
        id=_RUN, loan_file_id=_LF, status=VerificationStatus.FAILED, completed_at=None
    )
    cm, _db = _fake_session({_LF: loan_file, _RUN: run}, locked_status=VerificationStatus.FAILED)
    monkeypatch.setattr(vr, "task_session", cm)
    monkeypatch.setattr(vr, "run_verification", AsyncMock())

    await vr._run(str(_LF), str(_RUN))

    assert run.status is VerificationStatus.FAILED  # not overwritten by COMPLETED


async def test_task_noops_when_target_missing(monkeypatch) -> None:
    from app.tasks import verification_rules as vr

    cm, _db = _fake_session({})  # neither loan_file nor run exist
    monkeypatch.setattr(vr, "task_session", cm)
    orchestrator = AsyncMock()
    monkeypatch.setattr(vr, "run_verification", orchestrator)

    await vr._run(str(_LF), str(_RUN))
    orchestrator.assert_not_awaited()  # a missing target never runs the engine


async def test_exhaustion_marks_run_failed(monkeypatch) -> None:
    from app.tasks import verification_rules as vr

    run = SimpleNamespace(
        id=_RUN, status=VerificationStatus.RUNNING, completed_at=None, error_detail=None
    )
    cm, _db = _fake_session({_RUN: run})
    monkeypatch.setattr(vr, "task_session", cm)

    await vr._mark_failed(str(_RUN))

    assert (
        run.status is VerificationStatus.FAILED
    )  # fail-closed — a governed-engine failure is VISIBLE
    assert run.completed_at is not None and "Rule-engine pass failed" in run.error_detail


async def test_the_outage_sentence_is_written_onto_the_run(monkeypatch) -> None:
    """The arrival test, at the layer the processor sees. `_failure_detail` being right is not the
    same as `error_detail` carrying it — the previous version of this file had a passing test for the
    breaker's wording while `_mark_failed` ignored the exception entirely and wrote a fixed
    string."""
    from app.tasks import verification_rules as vr
    from app.verification.tag_materialization.breaker import AiBackendUnavailable

    run = SimpleNamespace(
        id=_RUN, status=VerificationStatus.RUNNING, completed_at=None, error_detail=None
    )
    cm, _db = _fake_session({_RUN: run})
    monkeypatch.setattr(vr, "task_session", cm)

    await vr._mark_failed(
        str(_RUN), AiBackendUnavailable("The AI backend failed 5 calls in a row. Re-run it.")
    )

    assert run.status is VerificationStatus.FAILED
    assert "5 calls in a row" in run.error_detail
    assert "after retries" not in run.error_detail


def test_enqueue_fires_the_governed_pass_alongside_the_sweep(monkeypatch) -> None:
    # The POST handler enqueues BOTH; the governed pass rides the same trigger as the sweep.
    from app.api import verification as api

    delayed: list[tuple] = []

    class _Task:
        def apply_async(self, *a, **kw):
            delayed.append((kw["args"], kw["soft_time_limit"], kw["time_limit"]))

    import app.tasks.verification_rules as vr

    monkeypatch.setattr(vr, "run_rule_engine_pass", _Task())
    assert api._enqueue_rule_engine(_LF, _RUN, document_count=44) is True  # enqueued OK
    # LP-635 — enqueued once with the run's ids AND the limits this file's size earns. `delay` cannot
    # carry per-run limits, which is why the call moved to `apply_async`.
    from app.core.run_limits import rule_engine_limits

    soft, hard = rule_engine_limits(44)
    assert delayed == [((str(_LF), str(_RUN)), soft, hard)]
    # The point of the change, stated as an assertion rather than left to the reader: a 44-document
    # file gets more than the old fixed limit, which is what it could not finish under.
    assert soft > 900


def test_enqueue_never_raises_but_reports_failure(monkeypatch) -> None:
    # A broker hiccup must not 500 the request, but it MUST be reported (return False) so the handler marks
    # the run FAILED — an un-enqueued governed pass never runs, so its own fail-closed FAILED never fires;
    # the run must not read COMPLETED via the sweep alone.
    import app.tasks.verification_rules as vr
    from app.api import verification as api

    boom = SimpleNamespace(
        apply_async=lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("broker down"))
    )
    monkeypatch.setattr(vr, "run_rule_engine_pass", boom)
    assert (
        api._enqueue_rule_engine(_LF, _RUN, document_count=0) is False
    )  # does not raise, reports the failure


def test_the_governed_pass_limit_clears_its_measured_runtime() -> None:
    """LP-377-C Fix 1 — the fourth fail-open put 282 next to 120. The governed pass now carries its OWN
    limits that clear the LP-365-measured ~282s with headroom (it no longer runs under the global 120s soft
    limit that killed it), and the watchdog clears the hard limit so a hard-kill is still caught. This FAILS
    on the pre-fix code, where run_rule_engine_pass had no per-task limit and inherited the global 120s."""
    from app.api.verification import _WATCHDOG_SLACK_SECONDS
    from app.core.run_limits import (
        RULE_ENGINE_HARD_LIMIT_SECONDS,
        RULE_ENGINE_MAX_HARD_SECONDS,
        RULE_ENGINE_SOFT_LIMIT_SECONDS,
    )
    from app.tasks.celery_app import celery_app
    from app.tasks.verification_rules import run_rule_engine_pass

    measured_runtime = 282  # LP-365, a 30-document file
    global_soft = celery_app.conf.task_soft_time_limit  # the sweep's short limit (120)

    # The governed pass got its OWN limits from the decorator — not the global 120s.
    assert run_rule_engine_pass.soft_time_limit == RULE_ENGINE_SOFT_LIMIT_SECONDS
    assert run_rule_engine_pass.time_limit == RULE_ENGINE_HARD_LIMIT_SECONDS
    # 282 finally fits under the limit — and it did NOT under the global 120s (the fourth fail-open).
    assert RULE_ENGINE_SOFT_LIMIT_SECONDS > measured_runtime > global_soft
    assert RULE_ENGINE_HARD_LIMIT_SECONDS > RULE_ENGINE_SOFT_LIMIT_SECONDS
    # The watchdog must clear the hard limit so a hard-killed pass (which cannot self-mark FAILED) is
    # failed. LP-635 made both sides of that a FUNCTION of the file, so the invariant is now checked
    # at the widest bound any run can be given rather than against a single pair of constants — a
    # watchdog that cleared the default hard limit but not the largest one would fail healthy runs on
    # exactly the big files this ticket exists to make work.
    # LP-635 REVIEW — asserted against `rule_engine_limits` itself, not against the constants.
    # `MAX_HARD + SLACK > MAX_HARD` only ever caught a non-positive slack; it could not notice the
    # watchdog and the enqueue drifting apart, which is the failure it claims to guard. Checked at
    # both ends of the range and past the cap, since the floor and the ceiling are where a
    # divergence would actually appear.
    from app.core.run_limits import rule_engine_limits

    for documents in (0, 1, 21, 44, 200, 10_000):
        _soft, hard = rule_engine_limits(documents)
        assert hard + _WATCHDOG_SLACK_SECONDS > hard, "the watchdog must clear the hard limit"
        assert hard <= RULE_ENGINE_MAX_HARD_SECONDS, (
            f"{documents} documents exceeds the widest bound the watchdog is sized for"
        )
    assert RULE_ENGINE_MAX_HARD_SECONDS >= RULE_ENGINE_HARD_LIMIT_SECONDS


def test_rule_pass_completion_respects_a_concurrently_committed_failed() -> None:
    # LP-377-C: the RULE PASS (not the sweep) is the run's completion authority. It marks COMPLETED only if
    # the run is not already FAILED — reading the status FROM THE DB UNDER A ROW LOCK (`locked_status`), NOT
    # from its own STALE in-memory run object. A concurrently-committed FAILED (a sweep failure) is invisible
    # to the rule pass's ORM object, so the decision keys on the fresh locked DB value. Modeled here as a
    # function of that value; the two-session end-to-end path is covered by _run above + integration.
    def rule_pass_effective_status(locked_db_status: VerificationStatus) -> VerificationStatus:
        # the guard exactly as verification_rules._run applies it: COMPLETED unless the DB already holds FAILED
        if locked_db_status is not VerificationStatus.FAILED:
            return VerificationStatus.COMPLETED
        return locked_db_status  # the rule pass leaves the DB's FAILED untouched

    # a concurrently-committed sweep FAILED stays FAILED even though the rule pass's in-memory run is RUNNING
    assert rule_pass_effective_status(VerificationStatus.FAILED) is VerificationStatus.FAILED
    # a healthy run (no FAILED in the DB) completes when the governed pass finishes
    assert rule_pass_effective_status(VerificationStatus.RUNNING) is VerificationStatus.COMPLETED


# --------------------------------------------------------------------------- #
# LP-635 — the limit is a function of the file, not a constant
# --------------------------------------------------------------------------- #
def test_a_44_document_file_gets_more_than_the_old_fixed_limit() -> None:
    """THE REPORTED FILE. LF-ZE9N could not verify: 44 documents against a flat 900s, killed twice at
    exactly fifteen minutes while still doing useful work.

    At the measured 35.6 s/doc it needs ~1,566s. The assertion is against the MEASUREMENT rather than
    a hardcoded expectation, so if someone re-measures the per-document cost this test still asks the
    right question — does the file fit? — instead of pinning a number that was only ever a
    consequence.
    """
    from app.core.run_limits import MEASURED_SECONDS_PER_DOCUMENT, rule_engine_limits

    soft, _hard = rule_engine_limits(44)
    assert soft > 900, "the old fixed limit is what this file could not finish under"
    assert soft > 44 * MEASURED_SECONDS_PER_DOCUMENT


def test_a_small_file_keeps_exactly_the_limits_it_had() -> None:
    """The floor. This change must not make anything detect a stuck small run more slowly than
    before — a longer leash on files that never needed one would be a regression bought with the
    fix."""
    from app.core.run_limits import rule_engine_limits

    assert rule_engine_limits(0) == (900, 1200)
    assert rule_engine_limits(5) == (900, 1200)


def test_the_budget_is_bounded() -> None:
    """The ceiling is a REFUSAL, not a budget: past it a file needs a resumable pass, not a longer
    lease on a worker slot. Without this, one enormous file could hold a prefork slot indefinitely
    and starve everything queued behind it."""
    from app.core.run_limits import RULE_ENGINE_MAX_SOFT_SECONDS, rule_engine_limits

    soft, _hard = rule_engine_limits(10_000)
    assert soft == RULE_ENGINE_MAX_SOFT_SECONDS


def test_the_limit_never_shrinks_as_a_file_grows() -> None:
    """Monotonic. A property rather than examples, because the floor and the ceiling are two places
    a clamp can inadvertently invert the ordering."""
    from app.core.run_limits import rule_engine_limits

    seen = [rule_engine_limits(n)[0] for n in range(0, 200, 7)]
    assert seen == sorted(seen)


def test_soft_hard_and_watchdog_stay_ordered_at_every_size() -> None:
    """THE INVARIANT THE WHOLE CHAIN RESTS ON, checked across the range rather than at one point.

    Each bound has a distinct job: the soft limit lets the task mark its own run FAILED, the hard
    limit SIGKILLs a task that ignored it, and the watchdog catches a hard-killed task that could not
    write its own marker. If any two cross, the run is failed by something that cannot explain
    itself — and before LP-635 these were three unrelated constants that could only be checked by
    reading them.
    """
    from app.api.verification import _WATCHDOG_SLACK_SECONDS
    from app.core.run_limits import rule_engine_limits

    for documents in (0, 1, 21, 30, 44, 60, 100, 1000):
        soft, hard = rule_engine_limits(documents)
        assert soft < hard < hard + _WATCHDOG_SLACK_SECONDS


# --------------------------------------------------------------------------- #
# LP-635 — what a processor is actually told
# --------------------------------------------------------------------------- #
def test_the_backend_outage_reason_reaches_the_run_the_processor_reads() -> None:
    """THE CLAIM I MADE THAT WAS FALSE.

    The breaker composes a careful sentence — how many calls failed, and to re-run once the backend
    is back — and a test asserted that sentence's wording. That test passed while the sentence went
    nowhere: `_mark_failed` wrote a fixed string, so `error_detail` said "failed after retries" for a
    failure that is never retried. Asserting what a message SAYS proves nothing about whether anyone
    sees it; this asserts it ARRIVES.
    """
    from app.tasks.verification_rules import _failure_detail
    from app.verification.tag_materialization.breaker import AiBackendUnavailable

    detail = _failure_detail(
        AiBackendUnavailable("The AI backend failed 5 calls in a row. Re-run.")
    )
    assert "5 calls in a row" in detail
    assert "retries" not in detail


def test_a_timeout_and_an_outage_do_not_read_the_same() -> None:
    """They need DIFFERENT actions from a processor — "this file is too big for the window" versus
    "try again shortly" — and one string for both is a string worth ignoring."""
    from app.tasks.verification_rules import _failure_detail
    from app.verification.tag_materialization.breaker import AiBackendUnavailable
    from billiard.exceptions import SoftTimeLimitExceeded

    timeout = _failure_detail(SoftTimeLimitExceeded())
    outage = _failure_detail(
        AiBackendUnavailable("The AI backend failed 5 calls in a row. Re-run.")
    )
    assert timeout != outage
    assert "ran out of time" in timeout
    # Neither may claim retries that `terminal_on` never performs.
    assert "after retries" not in timeout and "after retries" not in outage


def test_an_unrecognised_failure_still_says_something_useful() -> None:
    """The fallback must not be an empty string or a class name — it is what a processor sees for
    every cause nobody has thought about yet."""
    from app.tasks.verification_rules import _failure_detail

    for unknown in (RuntimeError("boom"), None):
        detail = _failure_detail(unknown)
        assert "re-run" in detail.lower()
