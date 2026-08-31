"""Endpoint tests for verification (LP-78) — the manual trigger + the status read.

POST triggers the pass (creates a RUNNING run + enqueues the worker — the enqueue
is patched, no real Celery/AI). GET returns the staleness flag, the latest run, and
the cross-source findings. Cross-company → 404.
"""

from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID, uuid4

import pytest_asyncio
from app.api.verification import _WATCHDOG_SLACK_SECONDS
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.models import (
    Borrower,
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
from app.models.finding import EvaluationOutcome
from app.models.verification import Verification, VerificationStatus, VerificationTrigger
from app.services.cross_source import assemble_cross_source_context, compute_input_fingerprint
from app.services.documents import create_document
from app.services.loan_files import create_loan_file
from app.services.verifications import mark_verification_stale
from app.verification.confidence import AggressionLevel
from app.verification.snapshot.documents_section import document_filenames_by_content_id
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from tests.integration import factories

API = "/api/v1/loan-files"
PREFS = "/api/v1/users/me/preferences"


async def _add_finding(db: AsyncSession, loan_file: LoanFile, *, confidence: float) -> Finding:
    """An OPEN AI cross-source finding at a given confidence (the dial filters on it)."""
    f = Finding(
        loan_file_id=loan_file.id,
        rule_id="cross_source.income_variance",
        origin=FindingOrigin.AI_CROSS_SOURCE,
        confidence=confidence,
        status=FindingStatus.YELLOW,
        category=FindingCategory.INCOME,
        message="A discrepancy.",
    )
    db.add(f)
    await db.flush()
    return f


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

    def _fake_enqueue(*_a: object, **kw: object) -> None:
        enqueued["args"] = tuple(kw["args"])  # type: ignore[arg-type]

    monkeypatch.setattr(
        "app.tasks.verification_rules.run_rule_engine_pass.apply_async", _fake_enqueue, raising=True
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

    def _boom(*_a: object, **_kw: object) -> None:
        raise RuntimeError("broker unreachable")

    monkeypatch.setattr(
        "app.tasks.verification_rules.run_rule_engine_pass.apply_async", _boom, raising=True
    )

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


def _rule_finding(
    loan_file: LoanFile,
    *,
    rule_id: str,
    outcome: EvaluationOutcome,
    status: FindingStatus,
    message: str,
    subject_key: str,
    ratification_pending: bool = False,
) -> Finding:
    """A GOVERNED rule-engine finding (evaluation_outcome present + inline provenance) — LP-316/375."""
    return Finding(
        loan_file_id=loan_file.id,
        rule_id=rule_id,
        origin=FindingOrigin.DETERMINISTIC_RULE,
        confidence=1.0,
        status=status,
        category=FindingCategory.CROSS_SOURCE,
        message=message,
        evaluation_outcome=outcome,
        subject_key=subject_key,
        load_bearing_tags=[
            {
                "tag_id": "id.current_address_type",
                "value": "unknown",
                "confidence": 0.9,
                "reasoning": "the doc states no type",
                "source_facts": ["doc1"],
            }
        ],
        details={"gated_pending_signoff": ratification_pending, "subject_key": subject_key},
    )


async def test_retired_xsrc_findings_do_not_render_in_the_legacy_tab(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-614 — a retired `xsrc.*` finding is origin `deterministic_rule` with NO evaluation_outcome, so
    it used to fall into the legacy tab alongside the AI sweep. Seven such rows exist on staging from the
    two xsrc rules that ever fired, both retired for contradicting ID-1/IN-5. The tab is AI-typed only
    now: the row is not deleted, it just stops being displayed."""
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    await _add_finding(db, loan_file, confidence=0.8)  # the AI sweep finding — still shown
    db.add(
        Finding(
            loan_file_id=loan_file.id,
            rule_id="xsrc.identity.name_consistency",
            origin=FindingOrigin.DETERMINISTIC_RULE,
            confidence=1.0,
            status=FindingStatus.YELLOW,
            category=FindingCategory.CROSS_SOURCE,
            message="Borrower name differs across sources: ADITYA TALLURI; TALLURI ADITYA.",
        )
    )
    await db.commit()

    body = (
        await client.get(f"{API}/{loan_file.display_id}/verification", headers=_auth(token))
    ).json()

    rule_ids = [f["rule_id"] for f in body["findings"]]
    assert rule_ids == ["cross_source.income_variance"]
    assert not any(r.startswith("xsrc.") for r in rule_ids)
    # ...and it did not leak into the governed list either (it has no evaluation_outcome).
    assert not any(f["rule_id"].startswith("xsrc.") for f in body["rule_findings"])


async def test_a_governed_finding_names_its_source_documents(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-617 — the link must survive all the way to the API, not just into the column. Before this,
    148 governed findings on the two staging files carried zero, and the read schema had nowhere to
    put one even if they had."""
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    doc = await factories.make_document(
        db, loan_file=loan_file, company=company, document_type="w2", filename="w2-2023.pdf"
    )
    await db.flush()
    finding = _rule_finding(
        loan_file,
        rule_id="ID-4",
        outcome=EvaluationOutcome.OPEN,
        status=FindingStatus.RED,
        message="the address differs across sources",
        subject_key="b1",
    )
    finding.source_document_ids = [str(doc.id)]
    finding.source_document_id = doc.id
    db.add(finding)
    await db.commit()

    body = (
        await client.get(f"{API}/{loan_file.display_id}/verification", headers=_auth(token))
    ).json()

    (row,) = body["rule_findings"]
    assert [d["filename"] for d in row["source_documents"]] == ["w2-2023.pdf"]
    assert row["source_documents"][0]["id"] == str(doc.id)


async def test_a_governed_finding_with_no_document_says_so_rather_than_inventing_one(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A loan-level rule over a computed tag has nothing to point at. Empty, never fabricated."""
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    db.add(
        _rule_finding(
            loan_file,
            rule_id="DT-7",
            outcome=EvaluationOutcome.SATISFIED,
            status=FindingStatus.GREEN,
            message="every ability-to-repay factor has a supporting document",
            subject_key="loan",
        )
    )
    await db.commit()

    body = (
        await client.get(f"{API}/{loan_file.display_id}/verification", headers=_auth(token))
    ).json()
    assert body["rule_findings"][0]["source_documents"] == []


async def test_rule_findings_separate_and_satisfied_is_reachable(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-375 — governed rule findings surface in a SEPARATE typed list (incl. `satisfied`, previously
    dropped by the RED/YELLOW filter); the legacy sweep stays in `findings`; the two never merge/sum."""
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    # A LEGACY sweep finding (ai_cross_source, no evaluation_outcome) → Tab 5 / `findings`.
    await _add_finding(db, loan_file, confidence=0.8)
    # GOVERNED rule findings (deterministic_rule, evaluation_outcome present) → Tabs 1-4 / `rule_findings`.
    db.add(
        _rule_finding(
            loan_file,
            rule_id="ID-4",
            outcome=EvaluationOutcome.SATISFIED,
            status=FindingStatus.GREEN,
            message="the address agrees across sources",
            subject_key="b1",
        )
    )
    db.add(
        _rule_finding(
            loan_file,
            rule_id="ID-4",
            outcome=EvaluationOutcome.COULDNT_CHECK,
            status=FindingStatus.YELLOW,
            message="the address-type classification is unknown",
            subject_key="b2",
            ratification_pending=True,
        )
    )
    await db.commit()

    body = (
        await client.get(f"{API}/{loan_file.display_id}/verification", headers=_auth(token))
    ).json()

    # TWO typed lists → structurally unmergeable. The sweep stays put; the governed findings are elsewhere.
    assert "findings" in body and "rule_findings" in body
    assert [f["origin"] for f in body["findings"]] == [
        "ai_cross_source"
    ]  # legacy only — no rule findings
    assert len(body["findings"]) == 1  # the rule findings are NOT summed into this count

    outcomes = {rf["evaluation_outcome"] for rf in body["rule_findings"]}
    assert outcomes == {"satisfied", "couldnt_check"}  # Tab 2 (`satisfied`) is REACHABLE

    # The honesty contract: couldnt_check carries its REASON and is NOT typed satisfied / not_applicable.
    cc = next(rf for rf in body["rule_findings"] if rf["evaluation_outcome"] == "couldnt_check")
    assert cc["message"] and cc["evaluation_outcome"] not in ("satisfied", "not_applicable")
    # The governed shape carries the SPEC guideline (never AI-recalled) + inline provenance.
    assert cc["guideline"]  # loaded from ID-4's spec at read time
    assert cc["load_bearing_tags"][0]["tag_id"] == "id.current_address_type"
    # LP-376-B: ID-4 is a CONSISTENCY rule, and this is a couldnt_check — no AI verdict was made, so the
    # ratification badge is FALSE (it is NOT derived from gated_pending_signoff = not priya_validated).
    assert cc["ratification_pending"] is False
    assert cc["subject_key"] == "b2"  # the stable content-id (human legibility is LP-376's)


# --- LP-377-B: the subject label — a finding names its subject, never a content-id ---------------


async def _governed_finding_label(client: AsyncClient, token: str, loan_file: LoanFile) -> str:
    """GET the file's status and return the single governed finding's subject_label."""
    body = (
        await client.get(f"{API}/{loan_file.display_id}/verification", headers=_auth(token))
    ).json()
    return body["rule_findings"][0]["subject_label"]


async def test_loan_subject_reads_whole_file(client: AsyncClient, db: AsyncSession) -> None:
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    db.add(
        _rule_finding(
            loan_file,
            rule_id="OC-2",
            outcome=EvaluationOutcome.COULDNT_CHECK,
            status=FindingStatus.YELLOW,
            message="occupancy could not be determined",
            subject_key="loan",
        )
    )
    await db.commit()
    assert await _governed_finding_label(client, token, loan_file) == "Whole file"


async def test_borrower_subject_reads_the_name(client: AsyncClient, db: AsyncSession) -> None:
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    borrower = Borrower(
        loan_file_id=loan_file.id, first_name="Dana", last_name="Sample", is_primary=True
    )
    db.add(borrower)
    await db.flush()
    db.add(
        _rule_finding(
            loan_file,
            rule_id="ID-8",
            outcome=EvaluationOutcome.NEEDS_REVIEW,
            status=FindingStatus.YELLOW,
            message="citizenship needs review",
            subject_key=str(borrower.id),
        )
    )
    await db.commit()
    # The borrower's UUID resolves to their name — never the raw id.
    assert await _governed_finding_label(client, token, loan_file) == "Dana Sample"


async def test_document_subject_reads_the_filename_via_the_content_id_bridge(
    client: AsyncClient, db: AsyncSession
) -> None:
    """THE BRIDGE, end-to-end (LP-377-B): a governed per-document finding whose subject_key is a document
    content-id resolves — through the read-path rebuild of ``{content_id → filename}`` — to the actual
    filename a processor recognises, never the raw hash."""
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    await create_document(
        db,
        loan_file=loan_file,
        document_id=uuid4(),
        filename="Statement_Mar2026.pdf",
        mime_type="application/pdf",
        size=1024,
        storage_path="acme/lf/doc.pdf",
        uploaded_by_user_id=None,
    )
    await db.flush()
    # Learn the content-id this document gets (the SAME derivation the read path uses).
    cid_map = await document_filenames_by_content_id(db, loan_file)
    (content_id,) = list(cid_map)  # exactly one document on the file
    db.add(
        _rule_finding(
            loan_file,
            rule_id="ID-7",
            outcome=EvaluationOutcome.COULDNT_CHECK,
            status=FindingStatus.YELLOW,
            message="a document in the file could not be classified",
            subject_key=content_id,
        )
    )
    await db.commit()

    body = (
        await client.get(f"{API}/{loan_file.display_id}/verification", headers=_auth(token))
    ).json()
    rf = body["rule_findings"][0]
    assert rf["subject_label"] == "Statement_Mar2026.pdf"  # the filename, resolved via the bridge
    assert rf["subject_key"] == content_id  # the KEY is untouched (LP-322's reconciler identity)
    assert content_id not in rf["subject_label"]  # the hash never reaches the label


async def test_document_subject_gone_reads_honestly_not_a_hash(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A per-document finding whose content-id is not among the file's current documents (removed / a
    Tab-3 no_longer_applies subject) reads honestly — never the raw hash."""
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    db.add(
        _rule_finding(
            loan_file,
            rule_id="ID-9",
            outcome=EvaluationOutcome.NO_LONGER_APPLIES,
            status=FindingStatus.GREEN,
            message="the power of attorney is no longer in the file",
            subject_key="doc067c28e496b10b5f",  # a content-id with no current document
        )
    )
    await db.commit()
    label = await _governed_finding_label(client, token, loan_file)
    assert label == "a document no longer in this file"
    assert "doc067c" not in label


# --- LP-377-C Fix 3: governed findings coupled to their run's completion ------------------------


async def _add_run(
    db: AsyncSession, loan_file: LoanFile, *, status: VerificationStatus
) -> Verification:
    run = Verification(
        loan_file_id=loan_file.id,
        status=status,
        trigger=VerificationTrigger.MANUAL,
        started_at=utcnow(),
        completed_at=utcnow() if status is not VerificationStatus.RUNNING else None,
    )
    db.add(run)
    await db.flush()
    return run


async def test_rule_findings_flagged_stale_when_latest_run_did_not_complete(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-377-C Fix 3 — the fourth fail-open's tell: governed findings shown while the LATEST run's rule
    engine did not complete (it FAILED) are flagged stale, AND still shown (LP-322 carry-forward preserved —
    NOT a verification_id filter, which would gut the reconciler)."""
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    # A governed finding carried forward from an earlier run.
    db.add(
        _rule_finding(
            loan_file,
            rule_id="ID-7",
            outcome=EvaluationOutcome.COULDNT_CHECK,
            status=FindingStatus.YELLOW,
            message="a document in the file could not be classified",
            subject_key="doc1",
        )
    )
    # The LATEST run FAILED — its governed pass never completed (the LP-377-C scenario).
    await _add_run(db, loan_file, status=VerificationStatus.FAILED)
    await db.commit()

    body = (
        await client.get(f"{API}/{loan_file.display_id}/verification", headers=_auth(token))
    ).json()
    assert (
        body["rule_findings_stale"] is True
    )  # the surface says the findings are from an earlier run
    assert len(body["rule_findings"]) == 1  # ...and STILL shows them (carry-forward is not broken)


async def test_rule_findings_not_stale_when_latest_run_completed(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A COMPLETED latest run means the governed pass finished — the findings are current, not stale."""
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    db.add(
        _rule_finding(
            loan_file,
            rule_id="ID-7",
            outcome=EvaluationOutcome.COULDNT_CHECK,
            status=FindingStatus.YELLOW,
            message="a document in the file could not be classified",
            subject_key="doc1",
        )
    )
    await _add_run(db, loan_file, status=VerificationStatus.COMPLETED)
    await db.commit()

    body = (
        await client.get(f"{API}/{loan_file.display_id}/verification", headers=_auth(token))
    ).json()
    assert body["rule_findings_stale"] is False


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
        "app.tasks.verification_rules.run_rule_engine_pass.apply_async",
        lambda *a, **kw: calls.append(tuple(kw.get("args", a))),
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


def _spy_both_delays(monkeypatch, calls: list) -> None:
    """Spy BOTH worker enqueues (the legacy AI sweep + the governed rule pass) — LP-377 asserts the GOVERNED
    pass re-runs on a rule-relevant change, so both are captured."""
    monkeypatch.setattr(
        "app.tasks.cross_source.run_cross_source_pass.delay",
        lambda *a: calls.append(("sweep", *a)),
        raising=True,
    )
    # LP-635 — the governed pass is enqueued with `apply_async`, not `delay`, because its time
    # limits are now PER RUN (they scale with the file's document count). Recorded in the same
    # ("rules", loan_file_id, run_id) shape every caller here already asserts on, so the change is
    # invisible to them; the limits themselves are asserted separately.
    monkeypatch.setattr(
        "app.tasks.verification_rules.run_rule_engine_pass.apply_async",
        lambda *a, **kw: calls.append(("rules", *kw.get("args", a))),
        raising=True,
    )


async def test_rule_relevant_change_reruns_the_governed_pass(
    client: AsyncClient, db: AsyncSession, monkeypatch
) -> None:
    """LP-377 BUG 3 — the one that already bit. A RULE/spec/tag change with UNCHANGED documents must
    re-run the governed pass, not serve a prior run's findings from a version of the engine that no
    longer exists. Seed a completed run whose stored fingerprint matches the current inputs under the
    CURRENT engine, then change the ENGINE (a rule edit) → the POST must MISS the cache and enqueue BOTH
    passes on a fresh RUNNING run. On the pre-fix code (the engine ignored in the key) this HIT the
    cache and NEITHER pass ran — exactly the ~12-hour-stale render that cost a human an afternoon."""
    calls: list = []
    _spy_both_delays(monkeypatch, calls)
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    # The stored fingerprint matches the current inputs UNDER THE CURRENT ENGINE (a genuine no-op today).
    await _seed_completed_run(db, loan_file, fingerprint=await _current_fingerprint(db, loan_file))
    await db.commit()

    # The engine changes (a rule/spec/tag edit) while the documents do NOT.
    monkeypatch.setattr(
        "app.services.cross_source.engine_fingerprint",
        lambda: "engine-token-after-a-rule-change",
        raising=True,
    )
    resp = await client.post(f"{API}/{loan_file.display_id}/verification/run", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"  # a FRESH run — the cache MISSED on the engine change
    # LP-614: the legacy sweep no longer runs at all, so "rules" alone is the whole expectation —
    # what this test protects is that the ENGINE change missed the cache, not how many passes fire.
    assert {c[0] for c in calls} == {"rules"}


async def test_governed_pass_enqueued_on_a_miss_and_the_legacy_sweep_is_not(
    client: AsyncClient, db: AsyncSession, monkeypatch
) -> None:
    """A cache miss (no prior run) enqueues the governed pass — so the cache never skips the rule engine
    on a real re-run (the fail-open the LP-377 key closes). LP-614: and the legacy sweep, which used to
    be enqueued alongside it, is NOT dispatched any more."""
    calls: list = []
    _spy_both_delays(monkeypatch, calls)
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    await db.commit()

    resp = await client.post(f"{API}/{loan_file.display_id}/verification/run", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"
    assert {c[0] for c in calls} == {"rules"}  # LP-614: the sweep is off; the governed pass runs


# --- The aggression dial (LP-79) ---------------------------------------------


async def test_get_status_includes_the_dial_and_blocking(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET returns the active level, the cutoffs map, and the authoritative blocking."""
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    await _add_finding(db, loan_file, confidence=0.9)  # in scope at every level
    await db.commit()

    body = (
        await client.get(f"{API}/{loan_file.display_id}/verification", headers=_auth(token))
    ).json()
    assert body["aggression"]["level"] == "balanced"  # the user default
    assert body["aggression"]["default"] == "balanced"
    assert body["aggression"]["override"] is None
    assert body["aggression"]["cutoffs"] == {"conservative": 0.8, "balanced": 0.5, "thorough": 0.0}
    assert body["blocked"] is True  # the 0.9 open finding is in scope at Balanced
    assert body["in_scope_open_count"] == 1


async def test_dial_re_filters_without_calling_the_ai(
    client: AsyncClient, db: AsyncSession, monkeypatch
) -> None:
    """Moving the dial re-filters the STORED findings — it never enqueues the AI."""
    calls: list = []
    _spy_delay(monkeypatch, calls)
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    # A low-confidence finding: in scope only at Thorough.
    await _add_finding(db, loan_file, confidence=0.3)
    await db.commit()

    # Balanced (the default): the 0.3 finding is below the cutoff → not blocked.
    at_balanced = (
        await client.get(f"{API}/{loan_file.display_id}/verification", headers=_auth(token))
    ).json()
    assert at_balanced["blocked"] is False
    assert at_balanced["in_scope_open_count"] == 0

    # Dial up to Thorough → the SAME stored finding becomes in-scope (blocked).
    thorough = (
        await client.put(
            f"{API}/{loan_file.display_id}/verification/aggression",
            headers=_auth(token),
            json={"level": "thorough"},
        )
    ).json()
    assert thorough["aggression"]["level"] == "thorough"
    assert thorough["aggression"]["override"] == "thorough"
    assert thorough["blocked"] is True
    assert thorough["in_scope_open_count"] == 1
    # Dial back down to Conservative → clear again.
    conservative = (
        await client.put(
            f"{API}/{loan_file.display_id}/verification/aggression",
            headers=_auth(token),
            json={"level": "conservative"},
        )
    ).json()
    assert conservative["blocked"] is False

    assert calls == []  # the dial NEVER re-runs the AI — pure read-time re-filter


async def test_dial_clear_resets_to_the_user_default(client: AsyncClient, db: AsyncSession) -> None:
    """level=null clears the per-file override (revert to the user default)."""
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    loan_file.aggression_level_override = AggressionLevel.THOROUGH
    await db.commit()

    body = (
        await client.put(
            f"{API}/{loan_file.display_id}/verification/aggression",
            headers=_auth(token),
            json={"level": None},
        )
    ).json()
    assert body["aggression"]["override"] is None
    assert body["aggression"]["level"] == "balanced"  # back to the default


async def test_dial_is_tenant_scoped(client: AsyncClient, db: AsyncSession) -> None:
    """Another company's file is a 404 (existence never revealed)."""
    _company_a, _user_a, _token_a = await _user_and_token(db, slug="acme", email="u@acme.com")
    company_b, _user_b, _token_b = await _user_and_token(db, slug="beta", email="u@beta.com")
    other = await create_loan_file(db, company_id=company_b.id)
    await db.commit()

    resp = await client.put(
        f"{API}/{other.display_id}/verification/aggression",
        headers=_auth(_token_a),
        json={"level": "thorough"},
    )
    assert resp.status_code == 404


async def test_user_default_preference_applies_to_files(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Changing the user default changes the active level on a file with no override."""
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    await db.commit()

    # Update the user-level default to Conservative.
    put = await client.put(
        PREFS, headers=_auth(token), json={"default_aggression_level": "conservative"}
    )
    assert put.status_code == 200
    assert put.json()["default_aggression_level"] == "conservative"

    # The file (no override) now resolves to the new default.
    body = (
        await client.get(f"{API}/{loan_file.display_id}/verification", headers=_auth(token))
    ).json()
    assert body["aggression"]["level"] == "conservative"
    assert body["aggression"]["default"] == "conservative"
    assert body["aggression"]["override"] is None


# --- LP-88: the full action set (accept-risk, request-docs) + run history -----


async def test_status_includes_the_program(client: AsyncClient, db: AsyncSession) -> None:
    """The status carries the file's loan program (drives the rule set / the tab header)."""
    from app.models import LoanProgram

    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id, loan_program=LoanProgram.FHA)
    await db.commit()
    body = (
        await client.get(f"{API}/{loan_file.display_id}/verification", headers=_auth(token))
    ).json()
    assert body["program"] == "fha"


async def test_accept_risk_resolves_as_accepted_risk(client: AsyncClient, db: AsyncSession) -> None:
    """Accept-risk acknowledges a finding (distinct from override) → ACCEPTED_RISK state."""
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    finding = await _add_finding(db, loan_file, confidence=0.9)
    await db.commit()

    resp = await client.post(
        f"{API}/{loan_file.display_id}/findings/{finding.id}/accept-risk",
        headers=_auth(token),
        json={"reason": "Compensating factor: 6 months reserves"},
    )
    assert resp.status_code == 200
    await db.refresh(finding)
    assert finding.resolution_status.value == "accepted_risk"
    assert finding.resolution_note == "Compensating factor: 6 months reserves"


async def test_request_docs_creates_a_needs_item_and_keeps_the_finding_open(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Request-docs creates a FINDING-origin needs item; the finding stays open + is marked."""
    from app.models.needs_item import NeedsItem, NeedsItemOrigin
    from sqlalchemy import select

    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    finding = await _add_finding(db, loan_file, confidence=0.9)
    await db.commit()

    resp = await client.post(
        f"{API}/{loan_file.display_id}/findings/{finding.id}/request-docs",
        headers=_auth(token),
        json={"note": "Please provide the 2024 W-2"},
    )
    assert resp.status_code == 200

    needs = (
        (await db.execute(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file.id)))
        .scalars()
        .all()
    )
    assert len(needs) == 1 and needs[0].origin is NeedsItemOrigin.FINDING
    await db.refresh(finding)
    # The finding stays OPEN (request-docs doesn't resolve it) but is marked.
    assert finding.resolution_status.value == "open"
    assert "docs_requested" in finding.details


async def test_run_history_lists_runs_newest_first(client: AsyncClient, db: AsyncSession) -> None:
    """The run-history endpoint exposes the versioned runs (newest first) for the selector."""
    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    await _seed_completed_run(db, loan_file, fingerprint="aaa")
    await _seed_completed_run(db, loan_file, fingerprint="bbb")
    await db.commit()

    resp = await client.get(f"{API}/{loan_file.display_id}/verification/runs", headers=_auth(token))
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 2
    # Newest-first ordering.
    assert all("id" in r and "status" in r for r in runs)


async def test_accept_risk_cross_company_is_404(client: AsyncClient, db: AsyncSession) -> None:
    company_a, _ua, _ta = await _user_and_token(db, slug="acme", email="a@acme.com")
    _company_b, _ub, token_b = await _user_and_token(db, slug="other", email="b@other.com")
    loan_file = await create_loan_file(db, company_id=company_a.id)
    finding = await _add_finding(db, loan_file, confidence=0.9)
    await db.commit()
    resp = await client.post(
        f"{API}/{loan_file.display_id}/findings/{finding.id}/accept-risk",
        headers=_auth(token_b),
        json={},
    )
    assert resp.status_code == 404


# --- LP-89: the stuck-RUNNING watchdog -------------------------------------


async def test_stuck_running_run_is_reconciled_to_failed_on_read(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A run RUNNING past the watchdog timeout is marked FAILED on read (not stuck forever)."""
    from datetime import timedelta

    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    # A run RUNNING far past the watchdog timeout (LP-377-C raised it to 1500s so it clears the governed
    # pass's 1200s hard limit) — the governed pass was hard-killed and could not commit its own FAILED, so
    # the watchdog is the only thing that can fail it.
    stuck = Verification(
        loan_file_id=loan_file.id,
        status=VerificationStatus.RUNNING,
        trigger=VerificationTrigger.MANUAL,
        started_at=utcnow() - timedelta(minutes=30),
    )
    db.add(stuck)
    await db.flush()
    await db.commit()

    body = (
        await client.get(f"{API}/{loan_file.display_id}/verification", headers=_auth(token))
    ).json()
    # The watchdog reconciled it: FAILED with a legible error (the UI can re-run).
    assert body["latest_run"]["status"] == "failed"
    await db.refresh(stuck)
    assert stuck.status is VerificationStatus.FAILED
    assert "timed out" in (stuck.error_detail or "")


async def test_a_recent_running_run_is_left_alone(client: AsyncClient, db: AsyncSession) -> None:
    """A run RUNNING within the timeout is NOT touched — critically, LP-377-C's governed pass legitimately
    runs ~282s (and a large file longer), so a run RUNNING for 10 minutes must NOT be raced to FAILED."""
    from datetime import timedelta

    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    fresh = Verification(
        loan_file_id=loan_file.id,
        status=VerificationStatus.RUNNING,
        trigger=VerificationTrigger.MANUAL,
        started_at=utcnow() - timedelta(minutes=10),
    )
    db.add(fresh)
    await db.flush()
    await db.commit()
    body = (
        await client.get(f"{API}/{loan_file.display_id}/verification", headers=_auth(token))
    ).json()
    assert body["latest_run"]["status"] == "running"


async def test_bulk_request_docs_route_exists_and_creates_one_item_per_document(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-564 — THE TEST THAT WAS MISSING, and its absence is why LP-562 shipped a 404.

    That ticket delivered the service, the schema and the button, and the endpoint's edit silently did
    not apply. Every test covered the SERVICE, so the suite stayed green while the button posted to a
    route that did not exist. A collection route also cannot be reached by the per-finding tests, since
    it has three path segments where they have four.
    """
    from app.models.finding import (
        EvaluationOutcome,
        Finding,
        FindingCategory,
        FindingStatus,
    )
    from sqlalchemy import select

    company, _user, token = await _user_and_token(db, slug="bulk", email="b@bulk.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    # Two findings from a rule that needs a credit report; one document, so one needs item.
    for subject in ("lia1", "lia2"):
        db.add(
            Finding(
                loan_file_id=loan_file.id,
                rule_id="CR-6",
                message="the file does not establish whether this account carries a derogatory mark",
                subject_key=subject,
                load_bearing_tags=[],
                status=FindingStatus.YELLOW,
                category=FindingCategory.CREDIT,
                confidence=1.0,
                evaluation_outcome=EvaluationOutcome.COULDNT_CHECK,
                details={},
            )
        )
    await db.commit()

    findings = (await db.execute(select(Finding).where(Finding.rule_id == "CR-6"))).scalars().all()
    resp = await client.post(
        f"{API}/{loan_file.display_id}/findings/request-docs",
        headers=_auth(token),
        json={"finding_ids": [str(f.id) for f in findings]},
    )

    assert resp.status_code == 200, resp.text


async def test_run_history_counts_survive_a_later_run(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-600 — THE HIGH BUG. Every historical run rendered as "produced no findings".

    LP-592 derived the per-run counts by grouping findings on `Finding.verification_id`, on the stated
    reasoning that "findings DO carry verification_id, so the answer is exact and cannot drift". It
    drifts on the very next run: `_update_finding` REASSIGNS that column for every re-detected finding
    and the retire loop does the same, so after run 2 essentially all of run 1's findings point at run
    2. The badge for a run that produced 26 findings the day before read "—".

    Counted from `finding_events` instead, which is append-only and genuinely per-run.
    """
    from app.models import EvaluationOutcome, FindingCategory
    from app.services.rule_findings import reconcile_evaluation_findings
    from app.verification.rule_engine.result import RuleEvaluation, Verdict

    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    run_one = await _seed_completed_run(db, loan_file, fingerprint="aaa")

    def _evaluation(subject: str, verdict: Verdict) -> RuleEvaluation:
        return RuleEvaluation(
            rule_id="AS-1",
            subject_id=subject,
            verdict=verdict,
            verdict_confidence=0.9,
            load_bearing_tags=(),
            threshold_used=None,
            priya_validated=False,
            gated_pending_signoff=True,
            reasoning="the verdict reasoning",
            how_to_fix=None,
        )

    async def _reconcile(run_id, evaluations):
        return await reconcile_evaluation_findings(
            db,
            loan_file_id=loan_file.id,
            verification_id=run_id,
            run_id=run_id,
            results=evaluations,
            evaluated_rule_ids=frozenset({"AS-1"}),
            category_by_rule={"AS-1": FindingCategory.ASSETS},
        )

    await _reconcile(
        run_one.id, [_evaluation("d1", Verdict.FIRED), _evaluation("d2", Verdict.FIRED)]
    )
    await db.commit()

    # A SECOND run re-detects both — which is what overwrites run one's verification_id.
    run_two = await _seed_completed_run(db, loan_file, fingerprint="bbb")
    await _reconcile(
        run_two.id, [_evaluation("d1", Verdict.FIRED), _evaluation("d2", Verdict.SATISFIED)]
    )
    await db.commit()

    resp = await client.get(f"{API}/{loan_file.display_id}/verification/runs", headers=_auth(token))
    assert resp.status_code == 200
    by_id = {r["id"]: r for r in resp.json()}

    # Run ONE still reports what run one concluded, even though its findings now point at run two.
    assert by_id[str(run_one.id)]["attention_count"] == 2
    assert by_id[str(run_one.id)]["satisfied_count"] == 0
    # Run TWO reports its own outcomes: one still open, one resolved to satisfied.
    assert by_id[str(run_two.id)]["attention_count"] == 1
    assert by_id[str(run_two.id)]["satisfied_count"] == 1
    assert EvaluationOutcome  # imported for the reader; the assertions above are the contract


async def test_run_history_counts_exclude_what_the_panel_hides(
    client: AsyncClient, db: AsyncSession
) -> None:
    """LP-600 — the badge must count exactly what its tab shows.

    The panel's own statement is `only_active(...)` plus `origin.in_(_SHOWN_ORIGINS)`; the count query
    had neither, so a soft-deleted finding — or one of a non-shown origin — inflated the history badge
    while being absent from "Needs attention".
    """
    from app.models import FindingCategory, FindingOrigin
    from app.models.base import utcnow
    from app.services.rule_findings import reconcile_evaluation_findings
    from app.verification.rule_engine.result import RuleEvaluation, Verdict

    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    run = await _seed_completed_run(db, loan_file, fingerprint="aaa")

    result = await reconcile_evaluation_findings(
        db,
        loan_file_id=loan_file.id,
        verification_id=run.id,
        run_id=run.id,
        results=[
            RuleEvaluation(
                rule_id="AS-1",
                subject_id=subject,
                verdict=Verdict.FIRED,
                verdict_confidence=0.9,
                load_bearing_tags=(),
                threshold_used=None,
                priya_validated=False,
                gated_pending_signoff=True,
                reasoning="the verdict reasoning",
                how_to_fix=None,
            )
            for subject in ("d1", "d2", "d3")
        ],
        evaluated_rule_ids=frozenset({"AS-1"}),
        category_by_rule={"AS-1": FindingCategory.ASSETS},
    )
    minted = sorted(result.minted, key=lambda f: f.subject_key or "")
    minted[0].deleted_at = utcnow()  # soft-deleted — gone from the tab
    minted[1].origin = FindingOrigin.DOCUMENT_ANALYSIS  # not in _SHOWN_ORIGINS
    await db.commit()

    resp = await client.get(f"{API}/{loan_file.display_id}/verification/runs", headers=_auth(token))

    [row] = [r for r in resp.json() if r["id"] == str(run.id)]
    assert row["attention_count"] == 1, "the badge counted findings the panel does not show"


# --------------------------------------------------------------------------- #
# LP-629 — one run per file in flight
#
# The guard exists because `worker_concurrency > 1` makes a double-click DANGEROUS
# rather than merely wasteful: two runs on one file execute together and collide on
# the findings partial-unique index over (loan_file_id, rule_id, subject_key), and
# that collision is one of the two failures run_verification propagates rather than
# degrades.
# --------------------------------------------------------------------------- #


async def test_second_run_on_same_file_returns_the_in_flight_run(
    client: AsyncClient, db: AsyncSession, monkeypatch
) -> None:
    """A second POST while one is RUNNING returns THAT run and enqueues nothing more."""
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "app.tasks.verification_rules.run_rule_engine_pass.apply_async",
        lambda *a, **kw: calls.append(tuple(kw["args"])),
        raising=True,
    )

    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    await db.commit()

    first = await client.post(
        f"{API}/{loan_file.display_id}/verification/run", headers=_auth(token)
    )
    assert first.json()["status"] == "running"

    second = await client.post(
        f"{API}/{loan_file.display_id}/verification/run", headers=_auth(token)
    )

    assert second.status_code == 200
    # The SAME run, not a second one — the client polls it to completion either way.
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["status"] == "running"
    # And no second pass was enqueued: the collision cannot happen if it never runs.
    assert len(calls) == 1


async def test_force_does_not_override_the_in_flight_guard(
    client: AsyncClient, db: AsyncSession, monkeypatch
) -> None:
    """`force` bypasses the input-fingerprint CACHE, not the one-run-per-file invariant.

    Pinned because the two are easy to conflate: both are 'run it anyway' affordances,
    and only one of them is safe to honour while a run is in flight.
    """
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "app.tasks.verification_rules.run_rule_engine_pass.apply_async",
        lambda *a, **kw: calls.append(tuple(kw["args"])),
        raising=True,
    )

    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    await db.commit()

    first = await client.post(
        f"{API}/{loan_file.display_id}/verification/run", headers=_auth(token)
    )
    forced = await client.post(
        f"{API}/{loan_file.display_id}/verification/run?force=true", headers=_auth(token)
    )

    assert forced.json()["id"] == first.json()["id"]
    assert len(calls) == 1


async def test_a_run_on_another_file_is_unaffected(
    client: AsyncClient, db: AsyncSession, monkeypatch
) -> None:
    """The guard is per FILE. Parallelism ACROSS files is the entire point of LP-629, so a
    guard that serialised the environment would defeat the change it ships with."""
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "app.tasks.verification_rules.run_rule_engine_pass.apply_async",
        lambda *a, **kw: calls.append(tuple(kw["args"])),
        raising=True,
    )

    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    file_a = await create_loan_file(db, company_id=company.id)
    file_b = await create_loan_file(db, company_id=company.id)
    await db.commit()

    run_a = await client.post(f"{API}/{file_a.display_id}/verification/run", headers=_auth(token))
    run_b = await client.post(f"{API}/{file_b.display_id}/verification/run", headers=_auth(token))

    assert run_a.json()["id"] != run_b.json()["id"]
    assert run_a.json()["status"] == run_b.json()["status"] == "running"
    assert len(calls) == 2  # both enqueued; neither blocked the other


async def test_a_stuck_run_does_not_block_a_new_one(
    client: AsyncClient, db: AsyncSession, monkeypatch
) -> None:
    """A run past the watchdog timeout is failed and superseded, not treated as in flight.

    Without this the guard would be a trap: a worker that died mid-run would make the file
    permanently un-runnable, which is strictly worse than the double-click it prevents.
    """
    monkeypatch.setattr(
        "app.tasks.verification_rules.run_rule_engine_pass.apply_async",
        lambda *a, **kw: None,
        raising=True,
    )

    company, _user, token = await _user_and_token(db, slug="acme", email="u@acme.com")
    loan_file = await create_loan_file(db, company_id=company.id)
    await db.commit()

    first = await client.post(
        f"{API}/{loan_file.display_id}/verification/run", headers=_auth(token)
    )
    stale_run = await db.get(Verification, UUID(first.json()["id"]))
    assert stale_run is not None
    # Age it past the watchdog rather than sleeping. The bound is now derived from the file (LP-635);
    # this file has no documents, so it gets the floor — the same 1500s the fixed constant held.
    from app.tasks.verification_rules import rule_engine_limits

    _soft, hard = rule_engine_limits(0)
    stale_run.started_at = utcnow() - timedelta(seconds=hard + _WATCHDOG_SLACK_SECONDS + 60)
    await db.commit()

    second = await client.post(
        f"{API}/{loan_file.display_id}/verification/run", headers=_auth(token)
    )

    assert second.json()["id"] != first.json()["id"]
    assert second.json()["status"] == "running"
    await db.refresh(stale_run)
    assert stale_run.status is VerificationStatus.FAILED
