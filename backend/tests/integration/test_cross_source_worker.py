"""Real-stack worker integration (LP-89) — the cross-source pass THROUGH the task.

The worker-seam bugs (task-not-registered, the profile-gate, the Redis-loop) ALL passed unit
tests but failed in the real stack. This exercises the actual Celery task entrypoint the worker
calls (``app.tasks.cross_source._run``) end-to-end: the run is picked up, the pass runs (the AI
is stubbed — no key needed), the findings persist, and the run stays RUNNING (LP-377-C: the sweep no longer
completes a run alone — the governed rule pass is the completion authority).
Paired with the task-registration guard (tests/tasks/test_task_registration.py), this closes the
worker-seam lesson: the registered task body works when invoked as the worker invokes it.
"""

import pathlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from app.ai.cross_source import CrossSourceResult
from app.models import Finding, FindingOrigin
from app.models.verification import VerificationStatus, VerificationTrigger
from app.services.loan_files import create_loan_file
from app.services.verifications import create_verification_run
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories


async def test_cross_source_task_makes_no_ai_call_and_leaves_the_run_alone(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LP-614: the legacy pass is off. It must not call the model, must not write findings, and must
    NOT complete the run — the governed rule pass shares this run and owns completion (LP-377-C)."""
    company = await factories.make_company(db, slug="acme")
    loan_file = await create_loan_file(db, company_id=company.id)
    await factories.make_borrower(db, loan_file=loan_file)
    run = await create_verification_run(
        db, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
    )
    await db.commit()

    @asynccontextmanager
    async def _fake_task_session() -> AsyncIterator[AsyncSession]:
        yield db

    async def _explode(_context_json: str) -> CrossSourceResult:
        raise AssertionError("LP-614: the legacy cross-source pass must make no AI call")

    monkeypatch.setattr("app.tasks.cross_source.task_session", _fake_task_session)
    monkeypatch.setattr("app.services.cross_source.reason_cross_source", _explode)

    from app.tasks.cross_source import _run

    await _run(str(loan_file.id), str(run.id))

    await db.refresh(run)
    assert run.status is VerificationStatus.RUNNING, (
        "completion belongs to the rule pass, not this one"
    )
    assert run.completed_at is None
    findings = (
        (
            await db.execute(
                select(Finding).where(
                    Finding.loan_file_id == loan_file.id,
                    Finding.origin == FindingOrigin.AI_CROSS_SOURCE,
                )
            )
        )
        .scalars()
        .all()
    )
    assert findings == []


async def test_creating_a_run_does_not_enqueue_the_legacy_cross_source_pass() -> None:
    """LP-614: the endpoint stopped enqueueing it, so the task is never dispatched for a new run."""
    import app.api.verification as verification_api

    assert not hasattr(verification_api, "_enqueue_cross_source")
    assert "_enqueue_cross_source" not in pathlib.Path(verification_api.__file__).read_text()


def test_the_cross_source_task_is_registered_on_the_worker() -> None:
    """The task must be registered or the worker silently drops enqueued messages (the seam bug)."""
    for module in (
        "app.tasks.health",
        "app.tasks.document_processing",
        "app.tasks.needs",
        "app.tasks.cross_source",
    ):
        __import__(module)
    from app.tasks.celery_app import celery_app

    assert "verification.run_cross_source" in celery_app.tasks
