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
from app.ai.extraction.bank_statement import BankStatementExtraction, BankStatementExtractionResult
from app.ai.extraction.pay_stub import PayStubExtraction, PayStubExtractionResult
from app.ai.extraction.shape import TypedField
from app.ai.extraction.w2 import W2Extraction, W2ExtractionResult
from app.core.security import hash_password
from app.models import Company, User, UserRole
from app.models.document import Document, DocumentCategory, DocumentStatus, Tier
from app.models.document_finding import DocumentFindingType
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


def _patch_extract(
    monkeypatch: pytest.MonkeyPatch,
    result: PayStubExtractionResult,
    *,
    document_type: str = "pay_stub",
) -> AsyncMock:
    """Patch the registry's extractor for ``document_type`` with a canned result."""
    mock = AsyncMock(return_value=result)
    monkeypatch.setitem(pipeline.EXTRACTORS, document_type, mock)
    return mock


@pytest.fixture(autouse=True)
def _mock_needs_enqueue(monkeypatch: pytest.MonkeyPatch):
    """Stub the LP-68 per-file needs-update enqueue so pipeline tests never hit the broker."""
    from unittest.mock import MagicMock

    delay = MagicMock()
    monkeypatch.setattr(pipeline.update_needs_for_document, "delay", delay)
    return delay


def _patch_analyze(monkeypatch: pytest.MonkeyPatch, analysis) -> AsyncMock:
    """Patch the Tier 3 ``analyze_document`` call (no real AI) with a canned analysis."""
    mock = AsyncMock(return_value=analysis)
    monkeypatch.setattr(pipeline, "analyze_document", mock)
    return mock


async def _findings_for(db: AsyncSession, loan_file_id):
    from app.services.document_findings import list_findings_for_loan_file

    return await list_findings_for_loan_file(db, loan_file_id=loan_file_id)


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
    assert doc.tier == Tier.TIER_1  # catalog-driven, set during classification
    assert doc.classification_confidence == 0.95

    extraction = await _current_extraction(db_session, doc.id)
    assert extraction is not None
    assert extraction.extraction_status == ExtractionStatus.SUCCEEDED
    assert extraction.tokens_used == 390  # 300 + 90
    assert extraction.cost_estimate is not None and extraction.cost_estimate > 0
    # the pipeline records the model it ACTUALLY invoked — the active provider's resolved id, which is the
    # tier value under anthropic and the mapped Bedrock profile under bedrock. Asserting the behaviour
    # (records the invoked model) rather than the anthropic literal keeps this provider-agnostic.
    assert extraction.model_used == pipeline.resolve_model(
        pipeline.settings.anthropic_model_extraction
    )


# --------------------------------------------------------------------------- #
# Tier-aware routing (LP-58) — Tier 1 (no extractor yet) / Tier 2 / Tier 3
# --------------------------------------------------------------------------- #


async def test_tier1_without_extractor_falls_back_to_tier3(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """A Tier-1 type with no registered extractor → Tier-3 free extraction (LP-471).

    LP-441 promoted spec'd types to Tier-1 before their extractors are wired. LP-471 routes such a
    promoted-but-unwired type (and every Tier-2 type) to the SAME Tier-3 scoped free extraction so it
    yields UNTYPED data (not just a thin summary), never nothing. To exercise the branch we remove a
    built extractor from the registry.
    """
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    monkeypatch.delitem(pipeline.EXTRACTORS, "tax_return")  # simulate "no extractor yet"
    _patch_classify(
        monkeypatch,
        ClassificationResult(document_type="tax_return", confidence=0.9, reasoning="x"),
    )
    analyze = _patch_analyze(monkeypatch, _generic_analysis_with_finding())

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.COMPLETED  # terminal, never FAILED
    assert doc.document_type == "tax_return"
    assert doc.tier == Tier.TIER_1
    assert await _current_extraction(db_session, doc.id) is None  # no typed extractor ran
    assert analyze.call_count == 1  # LP-471: Tier-3 free extraction ran (not the old summary)
    assert doc.generic_analysis is not None  # untyped facts captured
    assert (
        doc.summary == "A civil judgment against the borrower."
    )  # the gist is still kept (from analysis)


async def test_tier2_falls_back_to_tier3_free_extraction(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """A Tier-2 type (e.g. collection_account_letter) → Tier-3 free extraction (LP-471): untyped
    facts + findings are captured and the gist kept, with NO typed extraction."""
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult(
            document_type="collection_account_letter", confidence=0.9, reasoning="x"
        ),
    )
    analyze = _patch_analyze(monkeypatch, _generic_analysis_with_finding())

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert analyze.call_count == 1  # LP-471: free extraction ran (not the old summarize)
    assert doc.status == DocumentStatus.COMPLETED  # terminal
    assert doc.document_type == "collection_account_letter"
    assert doc.tier == Tier.TIER_2
    assert doc.category == DocumentCategory.CREDIT
    assert (
        doc.generic_analysis is not None
    )  # untyped facts captured (surfaced in the untyped section)
    assert doc.summary == "A civil judgment against the borrower."  # the gist is kept
    assert await _current_extraction(db_session, doc.id) is None  # no typed extraction


@pytest.mark.parametrize(
    ("document_type", "category"),
    [
        # LP-441: credit_report / flood_certification / verification_of_deposit were promoted to Tier-1
        # by the merge (they have specs) — use spec-less types that stay Tier-2.
        ("collection_account_letter", DocumentCategory.CREDIT),
        ("warranty_deed", DocumentCategory.PROPERTY),
        # closing_disclosure was promoted Tier 2 -> Tier 1 (LP-470); truth_in_lending is a spec-less Tier-2
        # DISCLOSURES type.
        ("truth_in_lending", DocumentCategory.DISCLOSURES),
        ("money_market_statement", DocumentCategory.ASSETS),
    ],
)
async def test_tier2_one_shared_path_for_every_type(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    document_type: str,
    category: DocumentCategory,
) -> None:
    """Different Tier-2 types all go through the SAME path — no per-type branching (now Tier-3 free
    extraction, LP-471)."""
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult(document_type=document_type, confidence=0.9, reasoning="x"),
    )
    analyze = _patch_analyze(monkeypatch, _generic_analysis_with_finding())

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert (
        analyze.call_count == 1
    )  # one shared mechanism (Tier-3 free extraction), regardless of type
    assert doc.tier == Tier.TIER_2
    assert doc.category == category
    assert doc.status == DocumentStatus.COMPLETED
    assert doc.generic_analysis is not None
    assert await _current_extraction(db_session, doc.id) is None


async def test_tier2_free_extraction_failure_is_graceful(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """Tier-3 free extraction failing (analyze returns None) → the doc still reaches a terminal status,
    generic_analysis + summary null (LP-471 reuses the graceful _tier3_analyze path)."""
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult(
            document_type="collection_account_letter", confidence=0.9, reasoning="x"
        ),  # LP-441: a still-Tier-2 type (credit_report was promoted)
    )
    _patch_analyze(monkeypatch, None)  # free extraction "failed" (returns None)

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.COMPLETED  # terminal, not stuck / crashed
    assert doc.tier == Tier.TIER_2
    assert doc.generic_analysis is None  # recognized + categorized, no facts — forgiving


def _generic_analysis_with_finding():
    from app.ai.generic_analyzer import AnalyzedFinding, GenericAnalysis

    return GenericAnalysis(
        document_type_guess="civil court judgment",
        summary="A civil judgment against the borrower.",
        full_text="IN THE CIRCUIT COURT ... judgment entered ...",
        key_findings=[
            AnalyzedFinding(
                finding_type="obligation",
                description="Outstanding civil judgment",
                amount=Decimal("8200.00"),
                details={"creditor": "Acme Bank"},
            )
        ],
    )


async def test_tier3_analyzed_findings_recorded_and_text_indexed(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """A Tier-3 doc → the generic analyzer (LP-66): analysis + full text stored, the
    key_findings recorded as DocumentFindings, terminal status."""
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult(document_type="boat_registration", confidence=0.9, reasoning="x"),
    )
    analyze = _patch_analyze(monkeypatch, _generic_analysis_with_finding())

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert analyze.call_count == 1
    assert doc.status == DocumentStatus.COMPLETED  # terminal
    assert doc.tier == Tier.TIER_3
    assert doc.generic_analysis is not None  # structured analysis stored
    assert doc.generic_analysis["document_type_guess"] == "civil court judgment"
    assert "full_text" not in doc.generic_analysis  # full text lives in its own column
    assert doc.full_text and "CIRCUIT COURT" in doc.full_text  # indexed for search
    findings = await _findings_for(db_session, doc.loan_file_id)
    assert len(findings) == 1
    assert findings[0].finding_type is DocumentFindingType.OBLIGATION
    assert findings[0].amount == Decimal("8200.00")
    assert await _current_extraction(db_session, doc.id) is None  # not a Tier 1 extraction


# --------------------------------------------------------------------------- #
# LP-463 — decline / guard / free-extraction routing
# --------------------------------------------------------------------------- #


async def test_type_mismatch_not_applied_and_free_extracted_for_review(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """The T4→w2 harm: the model flags type_matches_document=False. The wrong label is NOT applied
    (stored as unknown), the document is still READ via Tier 3 free extraction, and it lands in
    NEEDS_REVIEW — never a silent wrong-schema extraction."""
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult(
            document_type="w2",  # the model's pick …
            confidence=0.85,
            reasoning="a Canadian T4",
            document_name="a Canadian T4 slip",
            type_matches_document=False,  # … which it admits does not fit
        ),
    )
    analyze = _patch_analyze(monkeypatch, _generic_analysis_with_finding())
    extract = _patch_extract(
        monkeypatch, _paystub_success()
    )  # w2 has no extractor, but prove none runs

    with structlog.testing.capture_logs() as logs:
        await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.NEEDS_REVIEW
    assert doc.document_type == "unknown"  # ⚠️ the wrong w2 label was NOT applied
    assert analyze.call_count == 1  # still read (free extraction)
    assert extract.call_count == 0
    assert doc.generic_analysis is not None
    review = [e for e in logs if e["event"] == "document_needs_review"]
    assert review and review[0]["reason"] == "type_mismatch"


async def test_low_confidence_free_extracted_for_review(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """A low-confidence document is now READ (free extraction) before NEEDS_REVIEW — not left unread."""
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult(document_type="pay_stub", confidence=0.3, reasoning="unsure"),
    )
    analyze = _patch_analyze(monkeypatch, _generic_analysis_with_finding())
    extract = _patch_extract(monkeypatch, _paystub_success())

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.NEEDS_REVIEW
    assert analyze.call_count == 1  # read via Tier 3
    assert extract.call_count == 0  # the dubious label's extractor did NOT run
    assert doc.generic_analysis is not None


async def test_confident_unknown_free_extracts_and_completes(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """A confident decline → Tier 3 free extraction → COMPLETED (declining is cheap, loses no data)."""
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult(
            document_type="unknown",
            confidence=0.9,
            reasoning="no known type",
            document_name="an HOA annual budget",
        ),
    )
    analyze = _patch_analyze(monkeypatch, _generic_analysis_with_finding())

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.COMPLETED  # not flagged — an honest, confident unknown
    assert analyze.call_count == 1
    assert doc.generic_analysis is not None


async def test_correct_classification_unaffected_no_free_extraction(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """The control: a confidently, self-consistently classified type takes its normal path — deep
    extraction, no free-extraction call. LP-463 must not touch the 79% happy path."""
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult(
            document_type="pay_stub",
            confidence=0.95,
            reasoning="earnings",
            document_name="a pay stub",
            type_matches_document=True,
        ),
    )
    analyze = _patch_analyze(monkeypatch, _generic_analysis_with_finding())
    extract = _patch_extract(monkeypatch, _paystub_success())

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.COMPLETED
    assert doc.document_type == "pay_stub"  # its type, unchanged
    assert extract.call_count == 1  # deep extraction ran
    assert analyze.call_count == 0  # free extraction did NOT run


@pytest.mark.parametrize("document_type", ["boat_registration", "unknown", "mystery_affidavit"])
async def test_tier3_one_shared_path_for_any_unknown(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, document_type: str
) -> None:
    """Different unrecognized docs all go through the SAME analyzer path (no branching)."""
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult(document_type=document_type, confidence=0.9, reasoning="x"),
    )
    analyze = _patch_analyze(monkeypatch, _generic_analysis_with_finding())

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert analyze.call_count == 1  # one shared mechanism, regardless of type
    assert doc.tier == Tier.TIER_3
    assert doc.status == DocumentStatus.COMPLETED


async def test_tier3_analyzer_failure_is_graceful(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """Analyzer failure → terminal status, no analysis, no findings (never stuck/crash)."""
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult(document_type="unknown", confidence=0.9, reasoning="not known"),
    )
    _patch_analyze(monkeypatch, None)  # analyzer "failed"

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.COMPLETED  # terminal, not stuck / crashed
    assert doc.tier == Tier.TIER_3
    assert doc.generic_analysis is None and doc.full_text is None
    assert await _findings_for(db_session, doc.loan_file_id) == []


async def test_divorce_decree_extraction_records_findings_via_pipeline(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """LP-63 loop closed (LP-66): a divorce-decree (Tier 1) extraction records its
    obligations as DocumentFindings via the SAME mechanism the Tier 3 analyzer uses."""
    from decimal import Decimal

    from app.ai.extraction.divorce_decree import (
        DivorceDecreeExtraction,
        DivorceDecreeExtractionResult,
        SupportObligation,
    )

    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult(document_type="divorce_decree", confidence=0.95, reasoning="x"),
    )
    result = DivorceDecreeExtractionResult(
        data=DivorceDecreeExtraction(
            party_1_name=TypedField(value="Jane Doe"),
            support_obligations=[
                SupportObligation(
                    obligation_type="child_support",
                    amount=Decimal("1200.00"),
                    frequency="monthly",
                    payer="John Doe",
                )
            ],
        ),
        status=ExtractionStatus.SUCCEEDED,
        confidence=0.9,
        input_tokens=10,
        output_tokens=5,
    )
    _patch_extract(monkeypatch, result, document_type="divorce_decree")

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.COMPLETED
    assert doc.tier == Tier.TIER_1  # the divorce decree is Tier 1 — findings come from extraction
    findings = await _findings_for(db_session, doc.loan_file_id)
    assert len(findings) == 1
    # Uniform with the Tier 3 analyzer's findings — same DocumentFinding shape.
    assert findings[0].finding_type is DocumentFindingType.OBLIGATION
    assert findings[0].amount == Decimal("1200.00") and findings[0].frequency == "monthly"
    assert findings[0].details["source"] == "divorce_decree"


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
    extract = _patch_extract(monkeypatch, _paystub_success())  # registered but should not run

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.NEEDS_REVIEW
    assert extract.call_count == 0  # gated before extraction
    assert await _current_extraction(db_session, doc.id) is None


# --------------------------------------------------------------------------- #
# LP-462 — an INFRASTRUCTURE failure → NEEDS_REVIEW, but recorded DISTINCTLY
# (a throttle must never read as a low-confidence judgment / coverage gap)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("infra", ["rate_limited", "oversized", "failed"])
async def test_infra_failure_needs_review_with_distinct_reason(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, infra: str
) -> None:
    import structlog

    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult.unknown("AI call failed", infra_failure=infra),
    )
    extract = _patch_extract(monkeypatch, _paystub_success())

    with structlog.testing.capture_logs() as logs:
        await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.NEEDS_REVIEW
    assert extract.call_count == 0
    review = [e for e in logs if e["event"] == "document_needs_review"]
    assert len(review) == 1
    # The reason is the infrastructure cause, NOT "low_confidence" — that is the whole point.
    assert review[0]["reason"] == infra
    assert review[0].get("infra_failure") is True


# --------------------------------------------------------------------------- #
# Extraction failure → NEEDS_REVIEW (a FAILED extraction version is recorded)
# --------------------------------------------------------------------------- #


async def test_extraction_failure_falls_back_to_tier3(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """LP-471: a FAILED (genuinely-empty) extraction falls back to Tier-3 free extraction — the FAILED
    version is KEPT (the error stays diagnosable) and untyped facts are captured; still NEEDS_REVIEW."""
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="pay_stub", confidence=0.9, reasoning="x")
    )
    _patch_extract(monkeypatch, PayStubExtractionResult.failed("AI call failed"))
    analyze = _patch_analyze(monkeypatch, _generic_analysis_with_finding())

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert (
        doc.status == DocumentStatus.NEEDS_REVIEW
    )  # typed extraction errored — a human still reviews
    assert analyze.call_count == 1  # fell back to Tier-3 free extraction
    assert doc.generic_analysis is not None  # untyped facts captured — the document is not empty
    # the FAILED version is NOT hidden, and the error TYPE is preserved (A2 — a fallback must not make a
    # failure look like a success).
    extraction = await _current_extraction(db_session, doc.id)
    assert extraction is not None and extraction.extraction_status == ExtractionStatus.FAILED
    # The reason lives in the FAILED version's error_detail (access-controlled); processing_error stays a
    # FIXED, PII-safe string (a model reasoning could quote document content — the module invariant).
    assert "AI call failed" in (extraction.error_detail or "")
    assert doc.processing_error == "extraction failed — fell back to Tier 3 free extraction"


async def test_low_confidence_extraction_does_not_fall_back(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """LP-471 A6: a LOW-confidence extraction that DID capture typed fields must NOT fall back — mixing
    typed + untyped data for one document invites conflation. It keeps its fields; a human reviews."""
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="pay_stub", confidence=0.9, reasoning="x")
    )
    low_conf = PayStubExtractionResult(
        data=PayStubExtraction(employer_name=TypedField(value="ACME Corp")),
        status=ExtractionStatus.SUCCEEDED,
        confidence=0.3,  # below _CONFIDENCE_THRESHOLD, but fields WERE captured
        reasoning="unsure",
    )
    _patch_extract(monkeypatch, low_conf)
    analyze = _patch_analyze(monkeypatch, _generic_analysis_with_finding())

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.NEEDS_REVIEW
    assert analyze.call_count == 0  # NO fallback — the typed fields are kept
    assert doc.generic_analysis is None
    extraction = await _current_extraction(db_session, doc.id)
    assert extraction is not None and extraction.extraction_status == ExtractionStatus.SUCCEEDED


async def test_extraction_failure_where_fallback_also_fails_stays_empty_but_diagnosable(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """LP-471 (069's shape): if the fallback ALSO fails (analyze returns None — e.g. an oversized payload
    that defeats both calls), the document ends NEEDS_REVIEW with the FAILED version + no untyped data —
    the fallback cannot save it, and that stays honest (it needs the LP-464 page cap)."""
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="pay_stub", confidence=0.9, reasoning="x")
    )
    _patch_extract(monkeypatch, PayStubExtractionResult.failed("oversized"))
    analyze = _patch_analyze(monkeypatch, None)  # the fallback also fails (graceful None)

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.NEEDS_REVIEW
    assert analyze.call_count == 1  # the fallback was ATTEMPTED
    assert doc.generic_analysis is None  # ...but produced nothing — honest, not hidden
    extraction = await _current_extraction(db_session, doc.id)
    assert extraction is not None and extraction.extraction_status == ExtractionStatus.FAILED
    # The reason is diagnosable in the FAILED version's error_detail; processing_error stays PII-safe fixed.
    assert "oversized" in (extraction.error_detail or "")
    assert doc.processing_error == "extraction failed — fell back to Tier 3 free extraction"


async def test_throttled_extraction_is_not_a_content_failure(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """LP-464: a rate-limited extraction (the marker rides ``reasoning``) is recorded as re-runnable
    INFRASTRUCTURE — NOT a FAILED extraction version — so a throttle never reads as a coverage gap."""
    from app.ai.client import INFRA_RATE_LIMITED

    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="pay_stub", confidence=0.9, reasoning="x")
    )
    _patch_extract(monkeypatch, PayStubExtractionResult.failed(INFRA_RATE_LIMITED))

    with structlog.testing.capture_logs() as logs:
        await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.NEEDS_REVIEW
    assert "throttled" in doc.processing_error and "re-runnable" in doc.processing_error
    # ⚠️ NO FAILED extraction version — the call never produced content, so none is recorded.
    assert await _current_extraction(db_session, doc.id) is None
    review = [e for e in logs if e["event"] == "document_needs_review"]
    assert review and review[0]["reason"] == "rate_limited" and review[0]["infra_failure"] is True


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
        status=NeedsItemStatus.PENDING,
    )
    db.add(need)
    await db.commit()
    return need


async def test_pay_stub_enqueues_per_file_needs_update(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, _mock_needs_enqueue
) -> None:
    """A processed document ENQUEUES the per-file-serialized needs update (LP-68) —
    the satisfaction-matching itself runs in that task (tested in needs_engine)."""
    doc = await _setup_document(db_session)
    await _add_income_need(db_session, doc.loan_file_id)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="pay_stub", confidence=0.95, reasoning="x")
    )
    _patch_extract(monkeypatch, _paystub_success())

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.COMPLETED
    # The needs update was enqueued for THIS file + document (serialized per file).
    _mock_needs_enqueue.assert_called_once_with(str(doc.loan_file_id), str(doc.id))


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

    # The need is untouched by the pipeline itself (satisfaction is the enqueued
    # per-file needs task's job; re-run safety is the engine's, tested separately).
    await db_session.refresh(need)
    assert need.status == NeedsItemStatus.PENDING


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


# --------------------------------------------------------------------------- #
# Registry routing (LP-39c) — all three types route; unregistered → classified-only
# --------------------------------------------------------------------------- #


def _w2_success() -> W2ExtractionResult:
    return W2ExtractionResult(
        data=W2Extraction(tax_year=TypedField(value=2024)),
        status=ExtractionStatus.SUCCEEDED,
        confidence=0.9,
        input_tokens=10,
        output_tokens=5,
    )


def _bank_success() -> BankStatementExtractionResult:
    return BankStatementExtractionResult(
        data=BankStatementExtraction(ending_balance=TypedField(value=Decimal("5230.18"))),
        status=ExtractionStatus.SUCCEEDED,
        confidence=0.9,
        input_tokens=10,
        output_tokens=5,
    )


@pytest.mark.parametrize(
    ("document_type", "result_factory"),
    [
        ("pay_stub", _paystub_success),
        ("w2", _w2_success),
        ("bank_statement", _bank_success),
    ],
)
async def test_registry_routes_each_type_to_its_extractor(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, document_type: str, result_factory
) -> None:
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult(document_type=document_type, confidence=0.95, reasoning="x"),
    )
    mock = _patch_extract(monkeypatch, result_factory(), document_type=document_type)

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert mock.call_count == 1  # the registered extractor ran
    assert doc.status == DocumentStatus.COMPLETED
    assert doc.document_type == document_type
    assert doc.tier == Tier.TIER_1  # all 3 existing types route as Tier 1 (no regression)
    extraction = await _current_extraction(db_session, doc.id)
    assert extraction is not None
    assert extraction.extraction_status == ExtractionStatus.SUCCEEDED


# --------------------------------------------------------------------------- #
# LP-60 — the income/employment Tier 1 cluster is now registered + routed
# --------------------------------------------------------------------------- #


def test_lp60_income_employment_extractors_registered() -> None:
    """The four LP-60 types map to their extractors in the registry."""
    from app.ai.extraction import EXTRACTORS
    from app.ai.extraction.form_1099 import extract_1099
    from app.ai.extraction.letter_of_explanation import extract_letter_of_explanation
    from app.ai.extraction.profit_and_loss import extract_profit_and_loss
    from app.ai.extraction.voe import extract_voe

    assert pipeline.EXTRACTORS is EXTRACTORS
    assert EXTRACTORS["1099"] is extract_1099
    assert EXTRACTORS["voe"] is extract_voe
    assert EXTRACTORS["profit_and_loss"] is extract_profit_and_loss
    assert EXTRACTORS["letter_of_explanation"] is extract_letter_of_explanation


@pytest.mark.parametrize(
    ("document_type", "category"),
    [
        ("1099", DocumentCategory.INCOME_EMPLOYMENT),
        ("voe", DocumentCategory.INCOME_EMPLOYMENT),
        ("profit_and_loss", DocumentCategory.INCOME_EMPLOYMENT),
        # LOE is filed under borrower_info in the catalog (it explains, broadly).
        ("letter_of_explanation", DocumentCategory.BORROWER_INFO),
    ],
)
async def test_lp60_types_route_to_their_extractor(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    document_type: str,
    category: DocumentCategory,
) -> None:
    """A Tier-1 LP-60 type now reaches its extractor — NOT the classified-only
    no-extractor fallback (the result data shape is irrelevant here; the pipeline
    is type-agnostic, so a canned success result suffices)."""
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult(document_type=document_type, confidence=0.95, reasoning="x"),
    )
    mock = _patch_extract(monkeypatch, _paystub_success(), document_type=document_type)

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert mock.call_count == 1  # routed to the registered extractor (Tier 1), not the fallback
    assert doc.status == DocumentStatus.COMPLETED
    assert doc.tier == Tier.TIER_1
    assert doc.category == category
    assert await _current_extraction(db_session, doc.id) is not None  # an extraction was persisted


# --------------------------------------------------------------------------- #
# LP-61 — the asset Tier 1 cluster is now registered + routed
# --------------------------------------------------------------------------- #


def test_lp61_asset_extractors_registered() -> None:
    """The three LP-61 asset types map to their extractors in the registry."""
    from app.ai.extraction import EXTRACTORS
    from app.ai.extraction.gift_letter import extract_gift_letter
    from app.ai.extraction.investment_account import extract_investment_account
    from app.ai.extraction.retirement_account import extract_retirement_account

    assert EXTRACTORS["investment_account"] is extract_investment_account
    assert EXTRACTORS["retirement_account"] is extract_retirement_account
    assert EXTRACTORS["gift_letter"] is extract_gift_letter


@pytest.mark.parametrize(
    "document_type", ["investment_account", "retirement_account", "gift_letter"]
)
async def test_lp61_types_route_to_their_extractor(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, document_type: str
) -> None:
    """A Tier-1 asset type now reaches its extractor — NOT the classified-only
    no-extractor fallback (the pipeline is type-agnostic, so a canned success
    result suffices)."""
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult(document_type=document_type, confidence=0.95, reasoning="x"),
    )
    mock = _patch_extract(monkeypatch, _paystub_success(), document_type=document_type)

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert mock.call_count == 1  # routed to the registered extractor (Tier 1), not the fallback
    assert doc.status == DocumentStatus.COMPLETED
    assert doc.tier == Tier.TIER_1
    assert doc.category == DocumentCategory.ASSETS
    assert await _current_extraction(db_session, doc.id) is not None  # an extraction was persisted


# --------------------------------------------------------------------------- #
# LP-62 — the property Tier 1 cluster is now registered + routed
# --------------------------------------------------------------------------- #


def test_lp62_property_extractors_registered() -> None:
    """The five LP-62 property types map to their extractors in the registry."""
    from app.ai.extraction import EXTRACTORS
    from app.ai.extraction.hoa_statement import extract_hoa_statement
    from app.ai.extraction.homeowners_insurance import extract_homeowners_insurance
    from app.ai.extraction.mortgage_statement import extract_mortgage_statement
    from app.ai.extraction.property_tax_bill import extract_property_tax_bill
    from app.ai.extraction.purchase_agreement import extract_purchase_agreement

    assert EXTRACTORS["purchase_agreement"] is extract_purchase_agreement
    assert EXTRACTORS["homeowners_insurance"] is extract_homeowners_insurance
    assert EXTRACTORS["mortgage_statement"] is extract_mortgage_statement
    assert EXTRACTORS["property_tax_bill"] is extract_property_tax_bill
    assert EXTRACTORS["hoa_statement"] is extract_hoa_statement


@pytest.mark.parametrize(
    "document_type",
    [
        "purchase_agreement",
        "homeowners_insurance",
        "mortgage_statement",
        "property_tax_bill",
        "hoa_statement",
    ],
)
async def test_lp62_types_route_to_their_extractor(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, document_type: str
) -> None:
    """A Tier-1 property type now reaches its extractor — NOT the classified-only
    no-extractor fallback (the pipeline is type-agnostic, so a canned success
    result suffices)."""
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult(document_type=document_type, confidence=0.95, reasoning="x"),
    )
    mock = _patch_extract(monkeypatch, _paystub_success(), document_type=document_type)

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert mock.call_count == 1  # routed to the registered extractor (Tier 1), not the fallback
    assert doc.status == DocumentStatus.COMPLETED
    assert doc.tier == Tier.TIER_1
    assert doc.category == DocumentCategory.PROPERTY
    assert await _current_extraction(db_session, doc.id) is not None  # an extraction was persisted


# --------------------------------------------------------------------------- #
# LP-63 — the borrower-info/legal Tier 1 cluster is registered + routed
# --------------------------------------------------------------------------- #


def test_lp63_borrower_info_extractors_registered() -> None:
    """drivers_license + divorce_decree map to their extractors; the LOE is reused."""
    from app.ai.extraction import EXTRACTORS
    from app.ai.extraction.divorce_decree import extract_divorce_decree
    from app.ai.extraction.drivers_license import extract_drivers_license
    from app.ai.extraction.letter_of_explanation import extract_letter_of_explanation

    assert EXTRACTORS["drivers_license"] is extract_drivers_license
    assert EXTRACTORS["divorce_decree"] is extract_divorce_decree
    # The general LOE is the LP-60 extractor, reused (not duplicated).
    assert EXTRACTORS["letter_of_explanation"] is extract_letter_of_explanation


@pytest.mark.parametrize(
    "document_type", ["drivers_license", "divorce_decree", "letter_of_explanation"]
)
async def test_lp63_types_route_to_their_extractor(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, document_type: str
) -> None:
    """A Tier-1 borrower-info/legal type reaches its extractor — NOT the
    classified-only no-extractor fallback (the pipeline is type-agnostic, so a
    canned success result suffices)."""
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult(document_type=document_type, confidence=0.95, reasoning="x"),
    )
    mock = _patch_extract(monkeypatch, _paystub_success(), document_type=document_type)

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert mock.call_count == 1  # routed to the registered extractor (Tier 1), not the fallback
    assert doc.status == DocumentStatus.COMPLETED
    assert doc.tier == Tier.TIER_1
    assert doc.category == DocumentCategory.BORROWER_INFO
    assert await _current_extraction(db_session, doc.id) is not None  # an extraction was persisted


# --------------------------------------------------------------------------- #
# LP-64 — tax returns: Tier 1 is now COMPLETE (every Tier-1 type has an extractor)
# --------------------------------------------------------------------------- #


def test_tax_return_registered() -> None:
    from app.ai.extraction import EXTRACTORS
    from app.ai.extraction.tax_return import extract_tax_return

    assert EXTRACTORS["tax_return"] is extract_tax_return


def test_every_registered_extractor_is_a_tier_1_type() -> None:
    """LP-441 (replaces 'every Tier-1 has an extractor'): the tier merge made Tier-1 mean 'this document
    DESERVES extraction' (it has a schema spec), NOT 'its extractor is built' — 18 Tier-1 types have no
    registered extractor until step 7 wires them, and route to classified-only (asserted below). The
    remaining invariant runs the OTHER direction: every REGISTERED extractor's type IS Tier-1, so a wired
    extractor is never dispatched on a Tier-2/Tier-3 document. That keeps extraction deliberate without
    requiring coverage to be complete."""
    from app.ai.extraction import EXTRACTORS
    from app.documents.catalog import CATALOG
    from app.models.document import Tier

    non_tier1 = sorted(
        dt for dt in EXTRACTORS if CATALOG.get(dt, (Tier.TIER_3, None))[0] is not Tier.TIER_1
    )
    assert non_tier1 == [], f"registered extractors whose type is not Tier-1: {non_tier1}"


async def test_a_newly_promoted_tier1_type_with_no_extractor_completes_cleanly(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """THE D3 SAFETY GATE (LP-441): a Tier-1 type with NO registered extractor must COMPLETE cleanly —
    never error, never FAILED. LP-471 routes it to Tier-3 free extraction (was the interim summary), so it
    yields untyped facts. SYNTHETIC since LP-443 Phase B wired credit_report: the test removes it from
    EXTRACTORS to simulate the unwired state, so the gate is proven independent of which types are wired."""
    from app.ai.extraction import EXTRACTORS

    monkeypatch.delitem(pipeline.EXTRACTORS, "credit_report", raising=False)  # simulate: not wired
    assert "credit_report" not in EXTRACTORS  # the D3 gate's precondition
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult(document_type="credit_report", confidence=0.9, reasoning="x"),
    )
    analyze = _patch_analyze(monkeypatch, _generic_analysis_with_finding())

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.COMPLETED  # clean terminal, NOT errored / FAILED
    assert doc.tier == Tier.TIER_1
    assert doc.document_type == "credit_report"
    assert await _current_extraction(db_session, doc.id) is None  # no typed extractor ran
    assert (
        analyze.call_count == 1 and doc.generic_analysis is not None
    )  # LP-471: free extraction ran


async def test_tax_return_routes_to_its_extractor(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """tax_return reaches its extractor (Tier 1) — not the classified-only fallback."""
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch,
        ClassificationResult(document_type="tax_return", confidence=0.95, reasoning="x"),
    )
    mock = _patch_extract(monkeypatch, _paystub_success(), document_type="tax_return")

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    assert mock.call_count == 1
    assert doc.status == DocumentStatus.COMPLETED
    assert doc.tier == Tier.TIER_1
    assert doc.category == DocumentCategory.INCOME_EMPLOYMENT
    assert await _current_extraction(db_session, doc.id) is not None


# --------------------------------------------------------------------------- #
# reprocess_document_extraction uses the SAME registry (LP-44 core)
# --------------------------------------------------------------------------- #


async def test_reprocess_uses_registry(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    # A document already classified as w2 → reprocess re-extracts via the registry.
    doc = await _setup_document(db_session)
    doc.document_type = "w2"
    doc.category = DocumentCategory.INCOME_EMPLOYMENT
    doc.status = DocumentStatus.CLASSIFIED
    await db_session.commit()
    _patch_storage(monkeypatch)
    mock = _patch_extract(monkeypatch, _w2_success(), document_type="w2")

    await pipeline.reprocess_document_extraction(db_session, doc)
    await db_session.refresh(doc)

    assert mock.call_count == 1
    assert doc.status == DocumentStatus.COMPLETED
    assert await _current_extraction(db_session, doc.id) is not None


async def test_reprocess_unregistered_type_is_classified_only(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    # SYNTHETIC (LP-443): credit_report is now wired, so remove it to simulate an unregistered type —
    # reprocess of a type with no extractor must complete classified-only, no matter what is wired.
    monkeypatch.delitem(pipeline.EXTRACTORS, "credit_report", raising=False)
    doc = await _setup_document(db_session)
    doc.document_type = "credit_report"  # no registered extractor (removed above)
    doc.status = DocumentStatus.CLASSIFIED
    await db_session.commit()
    _patch_storage(monkeypatch)

    await pipeline.reprocess_document_extraction(db_session, doc)
    await db_session.refresh(doc)

    assert doc.status == DocumentStatus.COMPLETED
    assert await _current_extraction(db_session, doc.id) is None


# --------------------------------------------------------------------------- #
# LP-474 — self-consistency accuracy flag (distinct from a coverage PARTIAL)
# --------------------------------------------------------------------------- #
def _w2_state_equals_federal() -> W2ExtractionResult:
    """The 088 shape: state income tax == federal withheld (fabricated TX tax)."""
    return W2ExtractionResult(
        data=W2Extraction(
            tax_year=TypedField(value=2023),
            employer_name=TypedField(value="EQUINIX LLC"),
            federal_income_tax_withheld=TypedField(value=Decimal("35312.86")),
            state_income_tax=TypedField(value=Decimal("35312.86")),
            state_code=TypedField(value="TX"),
        ),
        status=ExtractionStatus.SUCCEEDED,
        confidence=0.9,
        reasoning="x",
        input_tokens=100,
        output_tokens=50,
    )


async def test_consistency_flag_is_a_distinct_finding_not_a_coverage_partial(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="w2", confidence=0.95, reasoning="x")
    )
    _patch_extract(monkeypatch, _w2_state_equals_federal(), document_type="w2")

    await pipeline._process_document(db_session, str(doc.id))
    await db_session.refresh(doc)

    # Coverage status is UNTOUCHED — the extraction SUCCEEDED; the accuracy flag is NOT a coverage PARTIAL.
    assert doc.status == DocumentStatus.COMPLETED
    extraction = await _current_extraction(db_session, doc.id)
    assert extraction is not None
    assert extraction.extraction_status == ExtractionStatus.SUCCEEDED
    # A distinct CONSISTENCY finding surfaces the accuracy problem — visible + distinguishable.
    findings = await _findings_for(db_session, doc.loan_file_id)
    consistency = [f for f in findings if f.finding_type == DocumentFindingType.CONSISTENCY]
    assert len(consistency) == 1
    assert "federal income tax" in consistency[0].description.lower()
    # The value is NOT rewritten — the flag reports, it never repairs.
    assert extraction.extracted_data["state_income_tax"]["value"] == "35312.86"


async def test_clean_w2_raises_no_consistency_finding(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    doc = await _setup_document(db_session)
    _patch_storage(monkeypatch)
    _patch_classify(
        monkeypatch, ClassificationResult(document_type="w2", confidence=0.95, reasoning="x")
    )
    _patch_extract(
        monkeypatch,
        W2ExtractionResult(
            data=W2Extraction(
                tax_year=TypedField(value=2024),
                federal_income_tax_withheld=TypedField(value=Decimal("5627.60")),
                state_income_tax=TypedField(value=Decimal("1499.00")),
            ),
            status=ExtractionStatus.SUCCEEDED,
            confidence=0.95,
            reasoning="x",
            input_tokens=100,
            output_tokens=50,
        ),
        document_type="w2",
    )

    await pipeline._process_document(db_session, str(doc.id))
    findings = await _findings_for(db_session, doc.loan_file_id)
    assert [f for f in findings if f.finding_type == DocumentFindingType.CONSISTENCY] == []
