"""LP-601 — a guard that only runs on a cache MISS never sees prose already stored.

WHAT SHIPPED. LP-599 banned "correctly" from composed text, because DT-8's spec had been rewritten to
stop claiming a lien is CORRECTLY excluded — a claim that requires knowing the lien sits on the subject
property, which nothing established. The guard was added, tested, deployed. The next staging run still
read:

    "The existing mortgage with UNITED WHSLE MORT is correctly excluded from the debt-to-income ratio."

Because `compose_findings` calls `compose` only for cache MISSES
(`misses = [fid for fid, key in keys.items() if key not in cache]`), and that sentence was already in
`finding_prose` from the run before. Every guard added after a composition is stored is invisible to
it — the fix was right and unreachable, for the third time in this sequence of tickets.

A cached composition is now re-checked against the CURRENT rules on the way out of the cache, so any
future guard heals stored prose instead of applying only to findings nobody had composed yet.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from app.ai.finding_prose import Composition
from app.models import Company, EvaluationOutcome, FindingCategory, FindingStatus
from app.models.finding import Finding, FindingOrigin
from app.services.finding_prose import _store, compose_findings, summarize
from app.services.loan_files import create_loan_file
from sqlalchemy.ext.asyncio import AsyncSession

_BAD = Composition(
    action="The existing mortgage is correctly excluded from the debt-to-income ratio",
    why="The application marks it paid off at closing.",
)
_GOOD = Composition(
    action="The application marks this mortgage as paid off at closing",
    why="It is excluded from the debt ratio.",
)


async def _finding(db: AsyncSession) -> tuple[Finding, UUID]:
    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    loan_file = await create_loan_file(db, company_id=company.id)
    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id="DT-8",
        origin=FindingOrigin.DETERMINISTIC_RULE,
        status=FindingStatus.GREEN,
        category=FindingCategory.CREDIT,
        evaluation_outcome=EvaluationOutcome.SATISFIED,
        subject_key="lia1",
        message="the application marks this mortgage as paid off at closing",
        details={},
        confidence=1.0,
    )
    db.add(finding)
    await db.flush()
    return finding, loan_file.id


async def test_a_cached_composition_that_breaks_a_newer_guard_is_recomposed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE BUG, end to end. The offending sentence is already in the cache; the pass must not serve
    it, and must not simply fall back to the template either — it recomposes."""
    finding, loan_file_id = await _finding(db_session)
    summary = summarize(finding, rule_name="Refinanced lien still counted in DTI")
    await _store(db_session, summary.cache_key(), _BAD)
    await db_session.flush()

    calls = {"n": 0}

    async def _compose(_summary, **_kw):
        calls["n"] += 1
        return _GOOD

    monkeypatch.setattr("app.services.finding_prose.compose", _compose)

    changed = await compose_findings(
        db_session,
        [finding],
        rule_names={"DT-8": "Refinanced lien still counted in DTI"},
        loan_file_id=loan_file_id,
    )

    assert changed == 1
    assert "correctly" not in finding.message
    assert calls["n"] == 1, "the rejected cache entry must become a MISS, not a silent fallback"


async def test_an_acceptable_cached_composition_is_still_reused(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE LINE THIS MUST NOT CROSS. The cache exists so identical facts do not pay for a second model
    call; re-checking must not turn every hit into a miss."""
    finding, loan_file_id = await _finding(db_session)
    summary = summarize(finding, rule_name="Refinanced lien still counted in DTI")
    await _store(db_session, summary.cache_key(), _GOOD)
    await db_session.flush()

    calls = {"n": 0}

    async def _compose(_summary, **_kw):
        calls["n"] += 1
        return _GOOD

    monkeypatch.setattr("app.services.finding_prose.compose", _compose)

    await compose_findings(
        db_session,
        [finding],
        rule_names={"DT-8": "Refinanced lien still counted in DTI"},
        loan_file_id=loan_file_id,
    )

    assert calls["n"] == 0, "an acceptable cached composition was needlessly recomposed"
    assert "paid off at closing" in finding.message
