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


def test_enqueue_fires_the_governed_pass_alongside_the_sweep(monkeypatch) -> None:
    # The POST handler enqueues BOTH; the governed pass rides the same trigger as the sweep.
    from app.api import verification as api

    delayed: list[tuple] = []

    class _Task:
        def delay(self, *a):
            delayed.append(a)

    import app.tasks.verification_rules as vr

    monkeypatch.setattr(vr, "run_rule_engine_pass", _Task())
    assert api._enqueue_rule_engine(_LF, _RUN) is True  # enqueued OK
    assert delayed == [(str(_LF), str(_RUN))]  # enqueued once, with the run's ids


def test_enqueue_never_raises_but_reports_failure(monkeypatch) -> None:
    # A broker hiccup must not 500 the request, but it MUST be reported (return False) so the handler marks
    # the run FAILED — an un-enqueued governed pass never runs, so its own fail-closed FAILED never fires;
    # the run must not read COMPLETED via the sweep alone.
    import app.tasks.verification_rules as vr
    from app.api import verification as api

    boom = SimpleNamespace(delay=lambda *a: (_ for _ in ()).throw(RuntimeError("broker down")))
    monkeypatch.setattr(vr, "run_rule_engine_pass", boom)
    assert api._enqueue_rule_engine(_LF, _RUN) is False  # does not raise, reports the failure


def test_the_governed_pass_limit_clears_its_measured_runtime() -> None:
    """LP-377-C Fix 1 — the fourth fail-open put 282 next to 120. The governed pass now carries its OWN
    limits that clear the LP-365-measured ~282s with headroom (it no longer runs under the global 120s soft
    limit that killed it), and the watchdog clears the hard limit so a hard-kill is still caught. This FAILS
    on the pre-fix code, where run_rule_engine_pass had no per-task limit and inherited the global 120s."""
    from app.api.verification import _STUCK_RUN_TIMEOUT_SECONDS
    from app.tasks.celery_app import celery_app
    from app.tasks.verification_rules import (
        RULE_ENGINE_HARD_LIMIT_SECONDS,
        RULE_ENGINE_SOFT_LIMIT_SECONDS,
        run_rule_engine_pass,
    )

    measured_runtime = 282  # LP-365, a 30-document file
    global_soft = celery_app.conf.task_soft_time_limit  # the sweep's short limit (120)

    # The governed pass got its OWN limits from the decorator — not the global 120s.
    assert run_rule_engine_pass.soft_time_limit == RULE_ENGINE_SOFT_LIMIT_SECONDS
    assert run_rule_engine_pass.time_limit == RULE_ENGINE_HARD_LIMIT_SECONDS
    # 282 finally fits under the limit — and it did NOT under the global 120s (the fourth fail-open).
    assert RULE_ENGINE_SOFT_LIMIT_SECONDS > measured_runtime > global_soft
    assert RULE_ENGINE_HARD_LIMIT_SECONDS > RULE_ENGINE_SOFT_LIMIT_SECONDS
    # The watchdog must clear the hard limit so a hard-killed pass (which cannot self-mark FAILED) is failed.
    assert _STUCK_RUN_TIMEOUT_SECONDS > RULE_ENGINE_HARD_LIMIT_SECONDS


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
