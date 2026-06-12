"""Pipeline smoke (LP-45) — the processing core over the real DB, AI mocked.

The full lifecycle matrix (classified-only, needs-review, extraction-failure,
unexpected→failed, registry routing for all three types) is covered
exhaustively in ``tests/tasks/test_document_processing.py``. This is a single
integration smoke proving the pipeline runs end-to-end against a document
created the integration way (real stored bytes), with **only** classification +
the extractor mocked — completing a pay stub and persisting a current
Extraction.
"""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from app.ai.classification import ClassificationResult
from app.ai.extraction.pay_stub import PayStubExtraction, PayStubExtractionResult
from app.ai.extraction.shape import TypedField
from app.models import Company, User
from app.models.document import DocumentCategory, DocumentStatus
from app.models.extraction import Extraction, ExtractionStatus
from app.tasks import document_processing as pipeline
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories


async def test_pipeline_completes_paystub_with_extraction(
    db: AsyncSession, company_a: Company, user_a: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    lf = await factories.make_loan_file(db, company=company_a)
    doc = await factories.make_document(db, loan_file=lf, company=company_a, uploaded_by=user_a)

    monkeypatch.setattr(
        pipeline,
        "classify_document",
        AsyncMock(
            return_value=ClassificationResult(
                document_type="pay_stub", confidence=0.95, reasoning="clear"
            )
        ),
    )
    monkeypatch.setitem(
        pipeline.EXTRACTORS,
        "pay_stub",
        AsyncMock(
            return_value=PayStubExtractionResult(
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
        ),
    )

    await pipeline._process_document(db, str(doc.id))
    await db.refresh(doc)

    assert doc.status == DocumentStatus.COMPLETED
    assert doc.document_type == "pay_stub"
    assert doc.category == DocumentCategory.INCOME_EMPLOYMENT

    extraction = await db.scalar(
        select(Extraction).where(Extraction.document_id == doc.id, Extraction.is_current.is_(True))
    )
    assert extraction is not None
    assert extraction.extraction_status == ExtractionStatus.SUCCEEDED
