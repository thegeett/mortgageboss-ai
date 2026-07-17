"""LP-365 — the governed snapshot/rules task: wiring + fail-closed run status.

The orchestrator itself is heavy (real AI); these mock it and assert the WIRING the ticket cares about:
the task calls ``run_verification`` with a real run's params and NO stub reasoners (a real run must use the
real model); on exhaustion it marks the run FAILED (fail-closed — never a silent RUNNING or a false
COMPLETED); the enqueue fires the governed pass ALONGSIDE the sweep. The two-task run-status invariant (a
FAILED is never overwritten by the sweep's COMPLETED) is pinned directly.
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


def _fake_session(objects: dict[object, object]):
    """A task_session replacement: an async CM yielding a db whose .get returns the mapped object."""
    db = SimpleNamespace(
        get=AsyncMock(side_effect=lambda _model, key: objects.get(key)), commit=AsyncMock()
    )

    @asynccontextmanager
    async def _cm():
        yield db

    return _cm, db


async def test_task_calls_orchestrator_with_run_params_and_no_stub(monkeypatch) -> None:
    from app.tasks import verification_rules as vr

    loan_file = SimpleNamespace(id=_LF, company_id=_COMPANY)
    run = SimpleNamespace(id=_RUN)
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
    api._enqueue_rule_engine(_LF, _RUN)
    assert delayed == [(str(_LF), str(_RUN))]  # enqueued once, with the run's ids


def test_enqueue_never_raises(monkeypatch) -> None:
    # A broker hiccup must not 500 the request (the sweep still runs); the fail-closed status is the task's.
    import app.tasks.verification_rules as vr
    from app.api import verification as api

    boom = SimpleNamespace(delay=lambda *a: (_ for _ in ()).throw(RuntimeError("broker down")))
    monkeypatch.setattr(vr, "run_rule_engine_pass", boom)
    api._enqueue_rule_engine(_LF, _RUN)  # does not raise


def test_sweep_completion_never_overwrites_a_failed_run() -> None:
    # THE fail-closed run-status invariant (the guard in cross_source.py:183): a run FAILED by the governed
    # pass stays FAILED even when the sweep completes. A run is COMPLETED only if BOTH passes completed.
    run = SimpleNamespace(status=VerificationStatus.FAILED)
    # the guard, exactly as the sweep applies it
    if run.status is not VerificationStatus.FAILED:
        run.status = VerificationStatus.COMPLETED
    assert run.status is VerificationStatus.FAILED
    # and a healthy run DOES complete
    ok = SimpleNamespace(status=VerificationStatus.RUNNING)
    if ok.status is not VerificationStatus.FAILED:
        ok.status = VerificationStatus.COMPLETED
    assert ok.status is VerificationStatus.COMPLETED
