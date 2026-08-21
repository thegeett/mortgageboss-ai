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


async def test_the_composer_names_the_borrower_it_was_given(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LP-605 — the composition pass must resolve subjects with the SAME maps the list view uses.

    It passed `document_filenames` and not `borrower_names`, so a borrower subject fell to the
    resolver's fallback and the model was handed "a borrower no longer on this file". On LF-3CVT that
    produced eight findings — CR-4, CR-10, ID-2, IN-1, IN-7, IN-10, IN-11, IN-16 — instructing a
    processor to obtain documents for a borrower removed from an application that has exactly one
    borrower, still on it, whose two pay stubs had just linked to them at confidence 1.0.

    The composer's own docstring had said it "just has to use the same resolver, with the same maps,
    so a finding cannot read one way in the list and another in its text." It used half of them.
    """
    from app.models.borrower import Borrower

    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:6]}")
    db_session.add(company)
    await db_session.flush()
    loan_file = await create_loan_file(db_session, company_id=company.id)
    borrower = Borrower(loan_file_id=loan_file.id, first_name="Aditya", last_name="Talluri")
    db_session.add(borrower)
    await db_session.flush()

    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id="IN-16",
        origin=FindingOrigin.DETERMINISTIC_RULE,
        status=FindingStatus.YELLOW,
        category=FindingCategory.INCOME,
        evaluation_outcome=EvaluationOutcome.OPEN,
        subject_key=str(borrower.id),
        message="a W-2 could not be found for this borrower",
        details={},
        confidence=1.0,
    )
    db_session.add(finding)
    await db_session.flush()

    seen: dict[str, str] = {}

    async def _compose(summary, **_kw):
        seen["subject"] = summary.subject
        return Composition(action="Obtain a W-2", why="Two years of history are required.")

    monkeypatch.setattr("app.services.finding_prose.compose", _compose)

    await compose_findings(
        db_session, [finding], rule_names={"IN-16": "Two-year history"}, loan_file_id=loan_file.id
    )

    assert "no longer on this file" not in seen["subject"], (
        "the composer told the model the borrower had been removed"
    )
    assert seen["subject"] == "Aditya Talluri"


async def test_the_composer_is_told_which_document_kinds_are_on_the_file(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LP-609 — a COUNT cannot tell "no pay stub" from "pay stubs are here, something else is missing".

    IN-3 asked a processor to upload a pay stub on a file that already carried two. LP-597 gave the
    composer `documents_on_file`, which was enough to stop it inventing a corpus on an EMPTY file and
    useless for this: 2 documents says nothing about whether either is the one being asked for.
    """
    from app.models.document import Document, UploadSource

    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:6]}")
    db_session.add(company)
    await db_session.flush()
    loan_file = await create_loan_file(db_session, company_id=company.id)
    for doc_type in ("pay_stub", "pay_stub", "w2"):
        db_session.add(
            Document(
                loan_file_id=loan_file.id,
                document_type=doc_type,
                original_filename=f"{doc_type}.pdf",
                storage_path=f"s3://x/{uuid4().hex}",
                mime_type="application/pdf",
                file_size_bytes=1024,
                upload_source=UploadSource.USER_UPLOAD,
            )
        )
    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id="IN-3",
        origin=FindingOrigin.DETERMINISTIC_RULE,
        status=FindingStatus.YELLOW,
        category=FindingCategory.INCOME,
        evaluation_outcome=EvaluationOutcome.COULDNT_CHECK,
        subject_key="loan",
        message="the year-to-date figure could not be compared",
        details={},
        confidence=1.0,
    )
    db_session.add(finding)
    await db_session.flush()

    seen: dict[str, object] = {}

    async def _compose(summary, **_kw):
        seen["kinds"] = summary.document_kinds_on_file
        seen["count"] = summary.documents_on_file
        return Composition(action="Confirm the pay stubs are legible", why="They are in the file.")

    monkeypatch.setattr("app.services.finding_prose.compose", _compose)

    await compose_findings(
        db_session, [finding], rule_names={"IN-3": "Pay stub recency"}, loan_file_id=loan_file.id
    )

    assert seen["count"] == 3
    # DEDUPED and sorted — two pay stubs are one KIND, and a stable order keeps `cache_key` stable so
    # an unchanged file does not re-compose every finding on every run.
    assert seen["kinds"] == ("W-2", "pay stub")


async def test_a_deleted_document_is_not_reported_as_on_the_file(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The inverse of the bug: telling the model a document is present when it is not would license
    exactly the invention LP-597 closed."""
    from app.models.base import utcnow
    from app.models.document import Document, UploadSource

    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:6]}")
    db_session.add(company)
    await db_session.flush()
    loan_file = await create_loan_file(db_session, company_id=company.id)
    db_session.add(
        Document(
            loan_file_id=loan_file.id,
            document_type="pay_stub",
            original_filename="gone.pdf",
            storage_path=f"s3://x/{uuid4().hex}",
            mime_type="application/pdf",
            file_size_bytes=1024,
            upload_source=UploadSource.USER_UPLOAD,
            deleted_at=utcnow(),
        )
    )
    finding = Finding(
        loan_file_id=loan_file.id,
        rule_id="IN-3",
        origin=FindingOrigin.DETERMINISTIC_RULE,
        status=FindingStatus.YELLOW,
        category=FindingCategory.INCOME,
        evaluation_outcome=EvaluationOutcome.COULDNT_CHECK,
        subject_key="loan",
        message="the year-to-date figure could not be compared",
        details={},
        confidence=1.0,
    )
    db_session.add(finding)
    await db_session.flush()

    seen: dict[str, object] = {}

    async def _compose(summary, **_kw):
        seen["kinds"] = summary.document_kinds_on_file
        return Composition(action="Upload a pay stub", why="None is in the file.")

    monkeypatch.setattr("app.services.finding_prose.compose", _compose)

    await compose_findings(
        db_session, [finding], rule_names={"IN-3": "Pay stub recency"}, loan_file_id=loan_file.id
    )

    assert seen["kinds"] == ()
