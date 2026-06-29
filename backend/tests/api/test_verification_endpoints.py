"""Endpoint tests for verification (LP-78) — the manual trigger + the status read.

POST triggers the pass (creates a RUNNING run + enqueues the worker — the enqueue
is patched, no real Celery/AI). GET returns the staleness flag, the latest run, and
the cross-source findings. Cross-company → 404.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import (
    Company,
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingStatus,
    LoanFile,
    User,
    UserRole,
)
from app.models.base import utcnow
from app.models.verification import Verification, VerificationStatus, VerificationTrigger
from app.services.cross_source import assemble_cross_source_context, compute_input_fingerprint
from app.services.loan_files import create_loan_file
from app.services.verifications import mark_verification_stale
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

API = "/api/v1/loan-files"


async def _seed_completed_run(
    db: AsyncSession, loan_file: LoanFile, *, fingerprint: str
) -> Verification:
    """A prior COMPLETED cross-source run carrying a given input fingerprint."""
    run = Verification(
        loan_file_id=loan_file.id,
        status=VerificationStatus.COMPLETED,
        trigger=VerificationTrigger.MANUAL,
        started_at=utcnow(),
        completed_at=utcnow(),
        input_fingerprint=fingerprint,
    )
    db.add(run)
    await db.flush()
    return run


async def _current_fingerprint(db: AsyncSession, loan_file: LoanFile) -> str:
    return compute_input_fingerprint(await assemble_cross_source_context(db, loan_file))


@pytest_asyncio.fixture
async def db(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    connection = await test_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _user_and_token(db: AsyncSession, *, slug: str, email: str) -> tuple[Company, User, str]:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=email,
        hashed_password=hash_password("irrelevant"),
        first_name="Test",
        last_name="User",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return company, user, create_access_token(user.id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_post_run_triggers_pass(client: AsyncClient, db: AsyncSession, monkeypatch) -> None:
    """POST creates a RUNNING run and enqueues the worker (enqueue patched)."""
    enqueued: dict[str, tuple[str, str]] = {}

    def _fake_delay(loan_file_id: str, run_id: str) -> None:
        enqueued["args"] = (loan_file_id, run_id)

    monkeypatch.setattr(
        "app.tasks.cross_source.run_cross_source_pass.delay", _fake_delay, raising=True
    )

    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    await db.commit()

    resp = await client.post(f"{API}/{loan_file.display_id}/verification/run", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["trigger"] == "manual"
    assert enqueued["args"][0] == str(loan_file.id)


async def test_post_run_marks_failed_when_enqueue_fails(
    client: AsyncClient, db: AsyncSession, monkeypatch
) -> None:
    """A failed enqueue (broker down) surfaces as FAILED, not a stranded RUNNING run."""

    def _boom(loan_file_id: str, run_id: str) -> None:
        raise RuntimeError("broker unreachable")

    monkeypatch.setattr("app.tasks.cross_source.run_cross_source_pass.delay", _boom, raising=True)

    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    await db.commit()

    resp = await client.post(f"{API}/{loan_file.display_id}/verification/run", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"  # surfaced, not an infinite spinner


async def test_get_status_reports_staleness_and_findings(
    client: AsyncClient, db: AsyncSession
) -> None:
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    db.add(
        Finding(
            loan_file_id=loan_file.id,
            rule_id="cross_source.income_variance",
            origin=FindingOrigin.AI_CROSS_SOURCE,
            confidence=0.8,
            status=FindingStatus.YELLOW,
            category=FindingCategory.INCOME,
            message="Stated income exceeds documents.",
            source_page=1,
            source_snippet="Gross 3,775",
        )
    )
    await mark_verification_stale(db, loan_file_id=loan_file.id)
    await db.commit()

    resp = await client.get(f"{API}/{loan_file.display_id}/verification", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["stale"] is True
    assert len(body["findings"]) == 1
    f = body["findings"][0]
    assert f["origin"] == "ai_cross_source"
    assert f["resolution_status"] == "open"
    assert f["source_page"] == 1


async def test_verification_is_tenant_scoped(client: AsyncClient, db: AsyncSession) -> None:
    _company_a, _ua, token_a = await _user_and_token(db, slug="acme", email="a@acme.com")
    company_b, _ub, _tb = await _user_and_token(db, slug="other", email="b@other.com")
    theirs = await create_loan_file(db, company_id=company_b.id)
    await db.commit()

    resp = await client.get(f"{API}/{theirs.display_id}/verification", headers=_auth(token_a))
    assert resp.status_code == 404


# --- Caching by input fingerprint (LP-78.1) ----------------------------------


def _spy_delay(monkeypatch, calls: list) -> None:
    monkeypatch.setattr(
        "app.tasks.cross_source.run_cross_source_pass.delay",
        lambda *a: calls.append(a),
        raising=True,
    )


async def test_unchanged_rerun_returns_cached_without_calling_ai(
    client: AsyncClient, db: AsyncSession, monkeypatch
) -> None:
    """Matching fingerprint → the cached run is returned and the AI is NOT enqueued."""
    calls: list = []
    _spy_delay(monkeypatch, calls)
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    cached = await _seed_completed_run(
        db, loan_file, fingerprint=await _current_fingerprint(db, loan_file)
    )
    await db.commit()

    resp = await client.post(f"{API}/{loan_file.display_id}/verification/run", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"  # the existing cached run
    assert body["id"] == str(cached.id)
    assert calls == []  # the AI worker was NOT enqueued


async def test_changed_inputs_rerun_calls_the_ai(
    client: AsyncClient, db: AsyncSession, monkeypatch
) -> None:
    """A different fingerprint (inputs changed) → a fresh RUNNING run is enqueued."""
    calls: list = []
    _spy_delay(monkeypatch, calls)
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    await _seed_completed_run(db, loan_file, fingerprint="stale-fingerprint-from-old-inputs")
    await db.commit()

    resp = await client.post(f"{API}/{loan_file.display_id}/verification/run", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"  # a fresh pass
    assert len(calls) == 1  # the AI worker WAS enqueued


async def test_force_reruns_even_when_unchanged(
    client: AsyncClient, db: AsyncSession, monkeypatch
) -> None:
    """force=true bypasses the cache — re-run the AI even on a matching fingerprint."""
    calls: list = []
    _spy_delay(monkeypatch, calls)
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    await _seed_completed_run(db, loan_file, fingerprint=await _current_fingerprint(db, loan_file))
    await db.commit()

    resp = await client.post(
        f"{API}/{loan_file.display_id}/verification/run?force=true", headers=_auth(token)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"
    assert len(calls) == 1  # forced → the AI was enqueued despite the match


async def test_cached_return_reconciles_staleness(
    client: AsyncClient, db: AsyncSession, monkeypatch
) -> None:
    """A stale flag with matching inputs is cleared on the cached return (consistency)."""
    calls: list = []
    _spy_delay(monkeypatch, calls)
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    await _seed_completed_run(db, loan_file, fingerprint=await _current_fingerprint(db, loan_file))
    await mark_verification_stale(db, loan_file_id=loan_file.id)
    await db.commit()

    await client.post(f"{API}/{loan_file.display_id}/verification/run", headers=_auth(token))
    assert calls == []  # cached, no AI

    status = (
        await client.get(f"{API}/{loan_file.display_id}/verification", headers=_auth(token))
    ).json()
    assert status["stale"] is False  # reconciled — matching inputs means not stale
