"""Tests for the document processing pipeline (LP-42) — AI + storage MOCKED.

The async core ``_process_document`` is called directly with the test session
(committing setup first so the worker-style commits/rollbacks compose with the
savepoint-mode session). ``classify_document`` and ``extract_pay_stub`` are
patched (no real AI, no key), and ``get_storage_backend`` is patched to return
bytes. The focus is the **resilience** (every path → a terminal status; an
unexpected error → FAILED, never crashing), the classify→extract **routing**, the
**status transitions**, **retry-safety**, needs-satisfaction, and **no values
logged**.
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import structlog
from app.ai.classification import ClassificationResult
from app.ai.extraction.pay_stub import PayStubExtraction, PayStubExtractionResult
from app.ai.extraction.shape import TypedField
from app.core.security import hash_password
from app.models import Company, User, UserRole
from app.models.document import Document, DocumentCategory, DocumentStatus
from app.models.extraction import Extraction, ExtractionStatus
from app.models.needs_item import (
    NeedsItem,
    NeedsItemOrigin,
    NeedsItemPriority,
    NeedsItemStatus,
)
from app.services.loan_files import create_loan_file
from app.tasks import document_processing as pipeline
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

PDF_BYTES = b"%PDF-1.7 dummy"


async def _setup_document(db: AsyncSession, *, slug: str = "acme") -> Document:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"u@{slug}.com",
        hashed_password=hash_password("x"),
        first_name="T",
        last_name="U",
        role=UserRole.PROCESSOR,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    loan_file = await create_loan_file(db, company_id=company.id)
    doc_id = uuid4()
    document = Document(
        id=doc_id,
        loan_file_id=loan_file.id,
        original_filename="paystub.pdf",
        mime_type="application/pdf",
        file_size_bytes=len(PDF_BYTES),
        storage_path=f"{company.id}/{loan_file.id}/{doc_id}.pdf",
        status=DocumentStatus.PENDING,
        upload_source="user_upload",
        uploaded_by_user_id=user.id,
    )
    db.add(document)
    await db.commit()  # commit setup so pipeline commits/rollbacks compose cleanly
    return document


def _patch_storage(
    monkeypatch: pytest.MonkeyPatch, *, content: bytes | Exception = PDF_BYTES
) -> None:
    read = (
        AsyncMock(side_effect=content)
        if isinstance(content, Exception)
        else AsyncMock(return_value=content)
    )
    backend = SimpleNamespace(read=read)
    monkeypatch.setattr(pipeline, "get_storage_backend", lambda: backend)


def _patch_classify(monkeypatch: pytest.MonkeyPatch, result: ClassificationResult) -> None:
    monkeypatch.setattr(pipeline, "classify_document", AsyncMock(return_value=result))


def _patch_extract(monkeypatch: pytest.MonkeyPatch, result: PayStubExtractionResult) -> None:
    monkeypatch.setattr(pipeline, "extract_pay_stub", AsyncMock(return_value=result))


def _paystub_success() -> PayStubExtractionResult:
    return PayStubExtractionResult(
        data=PayStubExtraction(
            employer_name=TypedField(value="ACME Corp"),
            gross_pay=TypedField(value=Decimal("4200.00")),
        ),
        status=ExtractionStatus.SUCCEEDED,
        confidence=0.95,
        reasoning="clear",
        input_tokens=300,
        output_tokens=90,
    )


async def _current_extraction(db: AsyncSession, document_id) -> Extraction | None:
    stmt = select(Extraction).where(
        Extraction.document_id == document_id, Extraction.is_current.is_(True)
    )
    return await db.scalar(stmt)


# --------------------------------------------------------------------------- #
# Happy path — pay stub
# --------------------------------------------------------------------------- #


async def test_happy_path_pay_stub(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="pay_stub", confidence=0.95, reasoning="x")
    )
    _patch_extract(monkeypatch, _paystub_success())

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.COMPLETED
    assert doc.document_type == "pay_stub"
    assert doc.category == DocumentCategory.INCOME_EMPLOYMENT
    assert doc.classification_confidence == 0.95

    extraction = await _current_extraction(db_session, doc.id)
    assert extraction is not None
    assert extraction.extraction_status == ExtractionStatus.SUCCEEDED
    assert extraction.tokens_used == 390  # 300 + 90
    assert extraction.cost_estimate is not None and extraction.cost_estimate > 0
    assert extraction.model_used == pipeline.settings.anthropic_model_extraction


# --------------------------------------------------------------------------- #
# Classified-only (non-pay-stub) — expected V1
# --------------------------------------------------------------------------- #


async def test_classified_only_non_pay_stub(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="w2", confidence=0.9, reasoning="x")
    )
    extract = AsyncMock()
    monkeypatch.setattr(pipeline, "extract_pay_stub", extract)

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.COMPLETED
    assert doc.document_type == "w2"
    assert doc.category == DocumentCategory.INCOME_EMPLOYMENT
    assert extract.call_count == 0  # no extractor for w2 in Phase 1
    assert await _current_extraction(db_session, doc.id) is None  # no extraction created


# --------------------------------------------------------------------------- #
# Low-confidence / unknown → NEEDS_REVIEW (no extraction)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "classification",
    [
        ClassificationResult(document_type="unknown", confidence=0.0, reasoning="x"),
        ClassificationResult(document_type="pay_stub", confidence=0.2, reasoning="x"),
    ],
)
async def test_low_confidence_or_unknown_needs_review(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, classification: ClassificationResult
) -> None:
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(monkeypatch, classification)
    extract = AsyncMock()
    monkeypatch.setattr(pipeline, "extract_pay_stub", extract)

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.NEEDS_REVIEW
    assert extract.call_count == 0  # gated before extraction
    assert await _current_extraction(db_session, doc.id) is None


# --------------------------------------------------------------------------- #
# Extraction failure → NEEDS_REVIEW (a FAILED extraction version is recorded)
# --------------------------------------------------------------------------- #


async def test_extraction_failure_needs_review(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="pay_stub", confidence=0.9, reasoning="x")
    )
    _patch_extract(monkeypatch, PayStubExtractionResult.failed("AI call failed"))

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.NEEDS_REVIEW
    assert doc.processing_error == "extraction failed or low confidence"
    extraction = await _current_extraction(db_session, doc.id)
    assert extraction is not None
    assert extraction.extraction_status == ExtractionStatus.FAILED


# --------------------------------------------------------------------------- #
# Unexpected error → FAILED (safe message), never crashes
# --------------------------------------------------------------------------- #


async def test_unexpected_error_marks_failed(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch, content=OSError("disk gone"))  # storage.read raises
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="pay_stub", confidence=0.9, reasoning="x")
    )

    # Must NOT raise out of the pipeline.
    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.FAILED
    assert doc.processing_error == "processing error"  # safe, no PII
    assert "disk gone" not in (doc.processing_error or "")


async def test_missing_document_is_a_noop(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    _patch_storage(monkeypatch)
    # A random id → no document; must return quietly without raising.
    await pipeline._process_document(db_session, str(uuid4()))


# --------------------------------------------------------------------------- #
# Needs satisfaction (provisional rule)
# --------------------------------------------------------------------------- #


async def _add_income_need(db: AsyncSession, loan_file_id) -> NeedsItem:
    need = NeedsItem(
        loan_file_id=loan_file_id,
        title="Most recent pay stubs",
        category=DocumentCategory.INCOME_EMPLOYMENT,
        needs_type="pay_stub",
        origin=NeedsItemOrigin.TEMPLATE,
        priority=NeedsItemPriority.STANDARD,
        status=NeedsItemStatus.OUTSTANDING,
    )
    db.add(need)
    await db.commit()
    return need


async def test_pay_stub_satisfies_outstanding_income_need(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    doc = await _setup_document(db_session)
    need = await _add_income_need(db_session, doc.loan_file_id)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="pay_stub", confidence=0.95, reasoning="x")
    )
    _patch_extract(monkeypatch, _paystub_success())

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(need)

    assert need.status == NeedsItemStatus.RECEIVED
    assert need.satisfied_by_document_id == doc.id
    assert need.satisfied_at is not None


async def test_no_matching_need_is_a_noop(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    # No income need present → completion still happens, no error.
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="pay_stub", confidence=0.95, reasoning="x")
    )
    _patch_extract(monkeypatch, _paystub_success())

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)
    assert doc.status == DocumentStatus.COMPLETED


# --------------------------------------------------------------------------- #
# Retry-safety
# --------------------------------------------------------------------------- #


async def test_retry_safe_versions_and_no_double_satisfy(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    doc = await _setup_document(db_session)
    need = await _add_income_need(db_session, doc.loan_file_id)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="pay_stub", confidence=0.95, reasoning="x")
    )
    _patch_extract(monkeypatch, _paystub_success())

    await pipeline._process_document(db_session, str(doc.id))
    await pipeline._process_document(db_session, str(doc.id))  # re-run

    # A second extraction VERSION exists; exactly one is current.
    all_versions = (
        (await db_session.execute(select(Extraction).where(Extraction.document_id == doc.id)))
        .scalars()
        .all()
    )
    assert len(all_versions) == 2
    assert sum(1 for e in all_versions if e.is_current) == 1
    assert {e.version for e in all_versions} == {1, 2}

    # The need was satisfied once and not re-satisfied by the second run.
    await db_session.refresh(need)
    assert need.status == NeedsItemStatus.RECEIVED
    assert need.satisfied_by_document_id == doc.id


# --------------------------------------------------------------------------- #
# Privacy — no extracted values logged
# --------------------------------------------------------------------------- #


async def test_no_extracted_values_logged(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="pay_stub", confidence=0.95, reasoning="x")
    )
    _patch_extract(
        monkeypatch,
        PayStubExtractionResult(
            data=PayStubExtraction(
                employer_name=TypedField(value="SECRETCORP"),
                gross_pay=TypedField(value=Decimal("9999.99")),
            ),
            status=ExtractionStatus.SUCCEEDED,
            confidence=0.95,
            input_tokens=10,
            output_tokens=5,
        ),
    )

    with structlog.testing.capture_logs() as logs:
        await pipeline._process_document(db_session, str(doc.id))

    blob = " ".join(repr(e) for e in logs)
    assert "SECRETCORP" not in blob
    assert "9999.99" not in blob
