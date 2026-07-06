"""Real-stack worker integration (LP-89) — the cross-source pass THROUGH the task.

The worker-seam bugs (task-not-registered, the profile-gate, the Redis-loop) ALL passed unit
tests but failed in the real stack. This exercises the actual Celery task entrypoint the worker
calls (``app.tasks.cross_source._run``) end-to-end: the run is picked up, the pass runs (the AI
is stubbed — no key needed), the findings persist, and the run transitions RUNNING → COMPLETED.
Paired with the task-registration guard (tests/tasks/test_task_registration.py), this closes the
worker-seam lesson: the registered task body works when invoked as the worker invokes it.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from app.ai.cross_source import CrossSourceRawFinding, CrossSourceResult
from app.models import Finding, FindingOrigin
from app.models.verification import VerificationStatus, VerificationTrigger
from app.services.loan_files import create_loan_file
from app.services.verifications import create_verification_run
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories


def _stub_result() -> CrossSourceResult:
    return CrossSourceResult(
        findings=[
            CrossSourceRawFinding(
                type="income_variance",
                description="Stated income exceeds the documents",
                stated_value="16400",
                document_value="15100",
                source_document="pay_stub",
                page=1,
                snippet="Gross 3,775.00 biweekly",
                confidence=0.82,
                reasoning="docs show less",
            )
        ],
        input_tokens=10,
        output_tokens=5,
        model="claude-test",
    )


async def test_cross_source_task_runs_end_to_end_and_persists_findings(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    company = await factories.make_company(db, slug="acme")
    loan_file = await create_loan_file(db, company_id=company.id)
    borrower = await factories.make_borrower(db, loan_file=loan_file)
    run = await create_verification_run(
        db, loan_file_id=loan_file.id, trigger=VerificationTrigger.MANUAL
    )
    await db.commit()

    # The task body opens its own session via task_session() + calls the default reasoner.
    # Point both at the test session + a deterministic stub (no broker, no AI key).
    @asynccontextmanager
    async def _fake_task_session() -> AsyncIterator[AsyncSession]:
        yield db

    async def _fake_reasoner(_context_json: str) -> CrossSourceResult:
        return _stub_result()

    monkeypatch.setattr("app.tasks.cross_source.task_session", _fake_task_session)
    monkeypatch.setattr("app.services.cross_source.reason_cross_source", _fake_reasoner)

    # Invoke the task body exactly as the worker would (enqueue → worker → _run).
    from app.tasks.cross_source import _run

    await _run(str(loan_file.id), str(run.id))

    # The run completed and the finding persisted (visible to the status endpoint).
    await db.refresh(run)
    assert run.status is VerificationStatus.COMPLETED
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
    assert any(f.rule_id == "cross_source.income_variance" for f in findings)
    assert borrower is not None  # the file had a borrower (a realistic fixture)


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
