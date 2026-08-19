"""LP-567 — the extraction pipeline must attribute a document to its borrower(s).

THE DEFECT. ``assign_document_borrower_links`` has existed and been tested since LP-202, and the
snapshot's ``belongs_to`` has read ``document_borrower_links`` since LP-206 — but nothing in the
running system ever CALLED the producer. Its only caller outside tests was
``app/scripts/stage1_artifact.py``, a developer script. Staging proved the consequence on
2026-08-19: a real run's snapshot held 16 documents and **0** with a borrower link, so every
per-borrower rule saw a file whose pay stubs, W-2s and bank statements belonged to nobody.

The service was never the problem, so this is a wiring test, not a matching test — the matcher
keeps its own suite in ``tests/services/test_document_borrower_links.py``. What is asserted here is
the thing that was missing: that running the PIPELINE produces links at all.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.ai.classification import ClassificationResult
from app.ai.extraction.pay_stub import PayStubExtraction, PayStubExtractionResult
from app.ai.extraction.shape import TypedField
from app.models.borrower import Borrower
from app.models.document import DocumentStatus
from app.models.document_borrower_link import DocumentBorrowerLink
from app.models.extraction import Extraction, ExtractionStatus
from app.tasks import document_processing as pipeline
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.tasks.test_document_processing import (
    _patch_classify,
    _patch_extract,
    _patch_storage,
    _setup_document,
)


def _paystub_for(name: str) -> PayStubExtractionResult:
    """A pay stub asserting ``employee_name`` — the field `BORROWER_NAME_FIELDS` matches on."""
    return PayStubExtractionResult(
        data=PayStubExtraction(
            employee_name=TypedField(value=name),
            employer_name=TypedField(value="ACME Corp"),
            gross_pay=TypedField(value=Decimal("4200.00")),
        ),
        status=ExtractionStatus.SUCCEEDED,
        confidence=0.95,
        reasoning="clear",
        input_tokens=300,
        output_tokens=90,
    )


async def _links(db: AsyncSession, document_id) -> list[DocumentBorrowerLink]:
    rows = await db.execute(
        select(DocumentBorrowerLink).where(DocumentBorrowerLink.document_id == document_id)
    )
    return list(rows.scalars().all())


async def _add_borrower(db: AsyncSession, loan_file_id, first: str, last: str) -> Borrower:
    borrower = Borrower(
        loan_file_id=loan_file_id, first_name=first, last_name=last, is_primary=True
    )
    db.add(borrower)
    await db.commit()
    return borrower


async def test_the_pipeline_links_the_document_to_its_borrower(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """THE HEADLINE. Before LP-567 this returned zero rows on every real run."""
    doc = await _setup_document(db_session)
    borrower = await _add_borrower(db_session, doc.loan_file_id, "Jordan", "Reyes")
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="pay_stub", confidence=0.95, reasoning="x")
    )
    _patch_extract(monkeypatch, _paystub_for("Jordan Reyes"))

    await pipeline._process_document(db_session, str(doc.id))

    links = await _links(db_session, doc.id)
    assert [link.borrower_id for link in links] == [borrower.id]


async def test_a_name_matching_nobody_links_nothing_and_still_completes(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """Zero links is a legitimate outcome, not a failure. §8's absent-is-not-unknown applies to
    attribution too: a document naming someone who is not on the file must produce NO row rather
    than a wrong one, and must not hold up the document."""
    doc = await _setup_document(db_session)
    await _add_borrower(db_session, doc.loan_file_id, "Jordan", "Reyes")
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="pay_stub", confidence=0.95, reasoning="x")
    )
    _patch_extract(monkeypatch, _paystub_for("Wei Zhang"))

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert await _links(db_session, doc.id) == []
    assert doc.status == DocumentStatus.COMPLETED


async def test_a_linker_failure_never_costs_the_document_its_extraction(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """WHY THE SAVEPOINT EXISTS. Linking is additive metadata; the extraction is the expensive,
    already-paid-for result of an AI call. A DB error while attributing must not take it down, so
    the call runs inside ``begin_nested()`` and the failure is swallowed with a log.

    Without the savepoint this is not merely unhandled — the failed statement poisons the session,
    and the pipeline's own ``commit`` further down would raise in turn.
    """
    doc = await _setup_document(db_session)
    await _add_borrower(db_session, doc.loan_file_id, "Jordan", "Reyes")
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="pay_stub", confidence=0.95, reasoning="x")
    )
    _patch_extract(monkeypatch, _paystub_for("Jordan Reyes"))

    async def _boom(db: AsyncSession, document) -> list[DocumentBorrowerLink]:
        # A REAL DB error, not a bare `raise`. Postgres aborts the transaction on a failed
        # statement, and every later statement on it errors with "current transaction is
        # aborted" — which is the failure mode the savepoint exists to contain. A test that
        # merely raised a Python exception would pass with or without `begin_nested()` and
        # would prove nothing (checked: it did).
        await db.execute(text("select 1 / 0"))
        raise RuntimeError("unreachable — the statement above raises")

    monkeypatch.setattr(pipeline, "assign_document_borrower_links", _boom)

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.COMPLETED
    extraction = await db_session.scalar(
        select(Extraction).where(Extraction.document_id == doc.id, Extraction.is_current.is_(True))
    )
    assert extraction is not None
    assert extraction.extraction_status == ExtractionStatus.SUCCEEDED
    assert await _links(db_session, doc.id) == []


async def test_a_re_extraction_replaces_the_links_rather_than_accumulating(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """A type override or reprocess re-runs ``_extract_branch``, so the links recompute. The linker
    is idempotent by wiping first; this asserts the WIRING preserves that, since calling it on every
    extraction version would otherwise be how duplicate attribution enters the file."""
    doc = await _setup_document(db_session)
    first = await _add_borrower(db_session, doc.loan_file_id, "Jordan", "Reyes")
    second = Borrower(
        loan_file_id=doc.loan_file_id,
        first_name="Wei",
        last_name="Zhang",
        borrower_position=2,
    )
    db_session.add(second)
    await db_session.commit()
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="pay_stub", confidence=0.95, reasoning="x")
    )

    _patch_extract(monkeypatch, _paystub_for("Jordan Reyes"))
    await pipeline._process_document(db_session, str(doc.id))
    assert [link.borrower_id for link in await _links(db_session, doc.id)] == [first.id]

    # The correction: the stub was actually the co-borrower's.
    _patch_extract(monkeypatch, _paystub_for("Wei Zhang"))
    await pipeline.reprocess_document_extraction(db_session, doc)

    assert [link.borrower_id for link in await _links(db_session, doc.id)] == [second.id]
