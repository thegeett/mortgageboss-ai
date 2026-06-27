"""LP-73 real-stack integration — exercise the SEAMS (real storage / DB / pipeline).

The phase's four bugs (a flush-timing bug, a Redis per-loop crash, a silent AI-failure
swallow, a host/worker storage split) ALL passed unit tests and broke on the real
stack — in the seams between components. These tests exercise the REAL assembled pieces:
the real storage backend (an actual write THEN read — the storage-split catcher), the
real DB, the real pipeline orchestration, and the real needs-satisfaction matching.
ONLY the AI model boundary is mocked (classify / extract / summarize / analyze) — never
the storage/DB/pipeline seams the unit tests mocked.

Tier 1 (extracted fields) / Tier 2 (summary) / Tier 3 (generic analysis) each go through
real storage; a missing file degrades to a graceful FAILED (not a crash).
"""

from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.ai.classification import ClassificationResult
from app.ai.extraction.pay_stub import PayStubExtraction, PayStubExtractionResult
from app.ai.extraction.shape import TypedField
from app.ai.generic_analyzer import AnalyzedFinding, GenericAnalysis
from app.core.config import settings
from app.core.security import hash_password
from app.models import Company, User, UserRole
from app.models.document import Document, DocumentStatus
from app.models.extraction import Extraction, ExtractionStatus
from app.models.needs_item import NeedsItemStatus
from app.services.loan_files import create_loan_file
from app.services.needs_engine import apply_document_to_needs
from app.services.needs_items import create_needs_item
from app.storage import get_storage_backend
from app.tasks import document_processing as pipeline
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

PDF_BYTES = b"%PDF-1.7\n%synthetic pay stub\n"


@pytest.fixture(autouse=True)
def _real_storage_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A REAL local storage backend at a tmp dir (not a mocked backend) — so the pipeline
    actually writes then reads the file, exercising the storage seam."""
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path / "storage"))
    get_storage_backend.cache_clear()
    yield
    get_storage_backend.cache_clear()


@pytest.fixture(autouse=True)
def _mock_needs_enqueue(monkeypatch: pytest.MonkeyPatch):
    """Stub the per-file needs-update enqueue so the pipeline doesn't hit the broker; the
    needs-satisfaction seam is exercised directly via ``apply_document_to_needs``."""
    monkeypatch.setattr(pipeline.update_needs_for_document, "delay", MagicMock())


async def _loan_file(db: AsyncSession, slug: str = "acme"):
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    db.add(
        User(
            company_id=company.id,
            email=f"u@{slug}.com",
            hashed_password=hash_password("x"),
            first_name="T",
            last_name="U",
            role=UserRole.PROCESSOR,
            is_active=True,
        )
    )
    await db.flush()
    return company, await create_loan_file(db, company_id=company.id)


async def _stage_real_file(db: AsyncSession, company, loan_file, *, content: bytes = PDF_BYTES):
    """Save real bytes through the real backend, then create the PENDING document for them."""
    doc_id = uuid4()
    storage = get_storage_backend()
    path = await storage.save(
        company_id=company.id,
        file_id=loan_file.id,
        document_id=doc_id,
        filename="upload.pdf",
        content=content,
    )
    doc = Document(
        id=doc_id,
        loan_file_id=loan_file.id,
        original_filename="upload.pdf",
        mime_type="application/pdf",
        file_size_bytes=len(content),
        storage_path=path,
        status=DocumentStatus.PENDING,
        upload_source="user_upload",
    )
    db.add(doc)
    await db.commit()
    return doc


async def _current_extraction(db: AsyncSession, document_id) -> Extraction | None:
    return await db.scalar(
        select(Extraction).where(
            Extraction.document_id == document_id, Extraction.is_current.is_(True)
        )
    )


# --------------------------------------------------------------------------- #
# Tier 1 — real storage read → classify → extract → satisfies the matching need
# --------------------------------------------------------------------------- #


async def test_tier1_real_upload_processes_and_satisfies_need(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    company, lf = await _loan_file(db_session)
    need = await create_needs_item(
        db_session, loan_file_id=lf.id, title="Pay stubs", needs_type="pay_stub"
    )
    doc = await _stage_real_file(db_session, company, lf)

    # Mock ONLY the AI boundary — classify + the registered extractor.
    monkeypatch.setattr(
        pipeline,
        "classify_document",
        AsyncMock(
            return_value=ClassificationResult(
                document_type="pay_stub", confidence=0.95, reasoning="x"
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

    # The REAL pipeline reads the REAL stored file (the storage-split catcher).
    await pipeline._process_document(db_session, str(doc.id))

    await db_session.refresh(doc)
    assert doc.status is DocumentStatus.COMPLETED  # NOT failed (the file was readable)
    assert doc.document_type == "pay_stub"
    extraction = await _current_extraction(db_session, doc.id)
    assert extraction is not None and extraction.extraction_status is ExtractionStatus.SUCCEEDED

    # The needs-satisfaction seam: the matching need verifies against the document.
    matched = await apply_document_to_needs(db_session, doc)
    assert matched is not None and matched.id == need.id
    assert need.status is NeedsItemStatus.VERIFIED
    assert need.satisfied_by_document_id == doc.id


# --------------------------------------------------------------------------- #
# Tier 2 — real storage read → recognize + summarize
# --------------------------------------------------------------------------- #


async def test_tier2_real_upload_summarizes(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    company, lf = await _loan_file(db_session)
    doc = await _stage_real_file(db_session, company, lf)
    monkeypatch.setattr(
        pipeline,
        "classify_document",
        AsyncMock(
            return_value=ClassificationResult(
                document_type="passport", confidence=0.95, reasoning="x"
            )
        ),
    )
    monkeypatch.setattr(pipeline, "summarize_document", AsyncMock(return_value="A US passport."))

    await pipeline._process_document(db_session, str(doc.id))

    await db_session.refresh(doc)
    assert doc.status is DocumentStatus.COMPLETED
    assert doc.tier is not None and doc.tier.value == "tier_2"
    assert doc.summary == "A US passport."


# --------------------------------------------------------------------------- #
# Tier 3 — real storage read → generic analysis
# --------------------------------------------------------------------------- #


async def test_tier3_real_upload_analyzes(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    company, lf = await _loan_file(db_session)
    doc = await _stage_real_file(db_session, company, lf)
    # A high-confidence type NOT in the catalog → Tier 3 (generic analyzer).
    monkeypatch.setattr(
        pipeline,
        "classify_document",
        AsyncMock(
            return_value=ClassificationResult(
                document_type="trust_agreement", confidence=0.95, reasoning="x"
            )
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "analyze_document",
        AsyncMock(
            return_value=GenericAnalysis(
                key_findings=[
                    AnalyzedFinding(finding_type="other", description="A revocable trust.")
                ],
                summary="A revocable living trust.",
            )
        ),
    )

    await pipeline._process_document(db_session, str(doc.id))

    await db_session.refresh(doc)
    assert doc.status is DocumentStatus.COMPLETED
    assert doc.tier is not None and doc.tier.value == "tier_3"
    assert doc.generic_analysis is not None


# --------------------------------------------------------------------------- #
# The storage-split regression — a missing file degrades to FAILED, not a crash
# --------------------------------------------------------------------------- #


async def test_missing_stored_file_fails_gracefully(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    company, lf = await _loan_file(db_session)
    doc = await _stage_real_file(db_session, company, lf)
    # Delete the stored bytes — simulate the worker not seeing the file (the split).
    get_storage_backend.cache_clear()
    Path(settings.storage_local_path).joinpath(doc.storage_path).unlink()

    await pipeline._process_document(db_session, str(doc.id))  # must not raise

    await db_session.refresh(doc)
    assert doc.status is DocumentStatus.FAILED  # graceful terminal, never a crash
    assert doc.processing_error is not None


# --------------------------------------------------------------------------- #
# MISMO import → needs list (floor + AI reasoning) — the differentiator's seam
# --------------------------------------------------------------------------- #


async def test_mismo_import_floor_then_ai_reasoning_coexist(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The needs seam end-to-end: the deterministic floor + the AI-reasoned needs both
    land on a real imported file (AI mocked at the model boundary)."""
    import json

    from app.mismo.import_service import create_loan_file_from_mismo
    from app.mismo.schema import ParsedBorrower, ParsedIncomeItem, ParsedLoan, ParsedMismo
    from app.models.needs_item import NeedsItem, NeedsItemOrigin
    from app.services import needs_ai
    from app.services.needs_ai import apply_ai_needs_for_file_id

    company = Company(name="Acme", slug="acme")
    db_session.add(company)
    await db_session.flush()

    parsed = ParsedMismo(
        loan=ParsedLoan(loan_purpose="Purchase", mortgage_type="Conventional"),
        borrowers=[
            ParsedBorrower(
                first_name="Mahesh",
                last_name="Chhotala",
                classification="Primary",
                income_items=[ParsedIncomeItem(income_type="Base", employment_income=True)],
            )
        ],
    )
    lf = await create_loan_file_from_mismo(
        db_session, parsed=parsed, company_id=company.id, raw_content=b"<MISMO/>"
    )
    await db_session.commit()

    # The deterministic floor seeded synchronously (real, no AI).
    floor = (
        await db_session.scalars(
            select(NeedsItem).where(
                NeedsItem.loan_file_id == lf.id, NeedsItem.origin == NeedsItemOrigin.FLOOR
            )
        )
    ).all()
    assert {n.needs_type for n in floor} >= {"pay_stub", "w2", "purchase_agreement"}

    # The AI reasoning (mocked at the model boundary) ingests proposed needs alongside.
    monkeypatch.setattr(
        needs_ai,
        "complete",
        AsyncMock(
            return_value=type(
                "R",
                (),
                {
                    "text": json.dumps(
                        {
                            "needs": [
                                {
                                    "need_description": "Two years of tax returns",
                                    "need_type": "tax_return",
                                    "reasoning": "Self-employment income.",
                                }
                            ]
                        }
                    ),
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "model": "m",
                },
            )()
        ),
    )
    await apply_ai_needs_for_file_id(db_session, lf.id)

    ai_needs = (
        await db_session.scalars(
            select(NeedsItem).where(
                NeedsItem.loan_file_id == lf.id, NeedsItem.origin == NeedsItemOrigin.AI_REASONING
            )
        )
    ).all()
    assert any(n.needs_type == "tax_return" for n in ai_needs)  # AI + floor coexist
