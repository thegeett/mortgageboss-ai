"""Document-level extraction confidence persistence (LP-201) — round-trip tests.

``create_extraction_version`` now accepts the model's document-level self-reported
confidence and stores it on the row (previously computed then dropped). These
tests prove it persists + reads back, that omitting it stores NULL — never a
fabricated default — and that the honest-provenance rule
(:func:`document_confidence_provenance`) never tags a defaulted 0.0 as a genuine
model rating.
"""

from uuid import UUID

import pytest
from app.ai.extraction.parsing import document_confidence_provenance
from app.models import (
    Company,
    Document,
    ExtractionStatus,
    UploadSource,
)
from app.models.extraction import ConfidenceSource, Extraction
from app.services.extractions import create_extraction_version
from app.services.loan_files import create_loan_file
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_document(db_session: AsyncSession, slug: str) -> Document:
    company = Company(name=slug.title(), slug=slug)
    db_session.add(company)
    await db_session.flush()
    loan_file = await create_loan_file(db_session, company_id=company.id)
    document = Document(
        loan_file_id=loan_file.id,
        original_filename="paystub.pdf",
        mime_type="application/pdf",
        file_size_bytes=1024,
        storage_path=f"{slug}/lf/paystub.pdf",
        upload_source=UploadSource.USER_UPLOAD,
    )
    db_session.add(document)
    await db_session.flush()
    return document


async def _reload(db_session: AsyncSession, extraction_id: UUID) -> Extraction:
    db_session.expire_all()
    return (
        await db_session.scalars(select(Extraction).where(Extraction.id == extraction_id))
    ).one()


@pytest.mark.parametrize(
    ("confidence", "expected_value", "expected_source"),
    [
        (0.83, 0.83, ConfidenceSource.MODEL_SELF_REPORTED),  # genuine positive rating
        (0.0, None, ConfidenceSource.NOT_PROVIDED),  # failed/defaulted 0.0 — NOT model rating
    ],
)
def test_document_confidence_provenance_is_honest(
    confidence: float, expected_value: float | None, expected_source: ConfidenceSource
) -> None:
    """A defaulted 0.0 is never tagged model_self_reported (the LP-201 invariant)."""
    assert document_confidence_provenance(confidence) == (expected_value, expected_source)


async def test_document_confidence_persists_and_reads_back(db_session: AsyncSession) -> None:
    document = await _make_document(db_session, "conf-yes")
    extraction = await create_extraction_version(
        db_session,
        document_id=document.id,
        extracted_data={"gross_pay": {"value": "5000.00"}},
        extraction_status=ExtractionStatus.SUCCEEDED,
        confidence=0.83,
        confidence_source=ConfidenceSource.MODEL_SELF_REPORTED,
    )
    reloaded = await _reload(db_session, extraction.id)
    assert reloaded.confidence == 0.83
    assert reloaded.confidence_source == ConfidenceSource.MODEL_SELF_REPORTED


async def test_not_provided_source_persists(db_session: AsyncSession) -> None:
    """A failed/defaulted extraction stores NULL confidence + not_provided (honest)."""
    document = await _make_document(db_session, "conf-notprov")
    extraction = await create_extraction_version(
        db_session,
        document_id=document.id,
        extracted_data={},
        extraction_status=ExtractionStatus.FAILED,
        confidence=None,
        confidence_source=ConfidenceSource.NOT_PROVIDED,
    )
    reloaded = await _reload(db_session, extraction.id)
    assert reloaded.confidence is None
    assert reloaded.confidence_source == ConfidenceSource.NOT_PROVIDED


async def test_omitted_confidence_stores_null_not_a_default(db_session: AsyncSession) -> None:
    """A caller that passes no confidence stores NULL — not 0.0 / 1.0."""
    document = await _make_document(db_session, "conf-no")
    extraction = await create_extraction_version(
        db_session,
        document_id=document.id,
        extracted_data={"gross_pay": {"value": "5000.00"}},
        extraction_status=ExtractionStatus.SUCCEEDED,
    )
    reloaded = await _reload(db_session, extraction.id)
    assert reloaded.confidence is None
    assert reloaded.confidence_source is None


async def test_per_field_confidence_survives_in_extracted_data(db_session: AsyncSession) -> None:
    """Per-field confidence (the number only) rides inside extracted_data, round-trip.

    The provenance tag is NOT stored beside the number — a reader derives it from
    the confidence via ``ConfidenceSource.for_confidence``.
    """
    document = await _make_document(db_session, "conf-field")
    data = {
        "gross_pay": {"value": "5000.00", "source": None, "confidence": 0.9},
        "employer_name": {"value": "ACME", "source": None, "confidence": None},
    }
    extraction = await create_extraction_version(
        db_session,
        document_id=document.id,
        extracted_data=data,
        extraction_status=ExtractionStatus.SUCCEEDED,
    )
    reloaded = await _reload(db_session, extraction.id)
    gross = reloaded.extracted_data["gross_pay"]
    employer = reloaded.extracted_data["employer_name"]
    assert gross["confidence"] == 0.9
    assert "confidence_source" not in gross  # derived, not stored
    assert (
        ConfidenceSource.for_confidence(gross["confidence"]) == ConfidenceSource.MODEL_SELF_REPORTED
    )
    assert employer["confidence"] is None
    assert ConfidenceSource.for_confidence(employer["confidence"]) == ConfidenceSource.NOT_PROVIDED
