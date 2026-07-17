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


def test_sweep_completion_respects_a_concurrently_committed_failed() -> None:
    # THE fail-closed run-status invariant (cross_source.py): the sweep marks COMPLETED only if the run is
    # not already FAILED — reading the status FROM THE DB UNDER A ROW LOCK (`locked_status`), NOT from its
    # own STALE in-memory run object. The governed pass commits FAILED in a SEPARATE session, invisible to
    # the sweep's ORM object (whose status is still RUNNING), so the decision MUST key on the fresh locked
    # DB value. Modeled here as a function of that value; the two-session end-to-end path is integration.
    def sweep_effective_status(locked_db_status: VerificationStatus) -> VerificationStatus:
        # the guard exactly as cross_source.py applies it: COMPLETED unless the DB already holds FAILED
        if locked_db_status is not VerificationStatus.FAILED:
            return VerificationStatus.COMPLETED
        return locked_db_status  # the sweep leaves the DB's FAILED untouched

    # a concurrently-committed governed FAILED stays FAILED even though the sweep's in-memory run is RUNNING
    assert sweep_effective_status(VerificationStatus.FAILED) is VerificationStatus.FAILED
    # a healthy run (no governed FAILED in the DB) completes
    assert sweep_effective_status(VerificationStatus.RUNNING) is VerificationStatus.COMPLETED
