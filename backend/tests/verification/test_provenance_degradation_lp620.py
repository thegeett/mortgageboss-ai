"""LP-620 — provenance is a nicety; the findings are not.

LP-617 gave a finding the document ids it is about, resolved at the END of a run from live DB state.
Three of the four defects here are the same mistake in different places: treating that resolution as
though it cannot fail, when the run it sits at the end of has already spent minutes proving otherwise.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from app.models.finding import (
    EvaluationOutcome,
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingStatus,
)
from app.services.finding_source_matching import populate_finding_source_documents
from app.services.rule_findings import _update_finding
from app.verification.rule_engine.result import RuleEvaluation, Verdict

_DOC_A = str(uuid4())
_DOC_B = str(uuid4())


def _result(subject_id: str = "doc-1", content_ids: tuple[str, ...] = ()) -> RuleEvaluation:
    return RuleEvaluation(
        rule_id="ID-4",
        subject_id=subject_id,
        verdict=Verdict.COULDNT_CHECK,
        verdict_confidence=None,
        load_bearing_tags=(),
        threshold_used=None,
        priya_validated=True,
        gated_pending_signoff=False,
        reasoning="only 1 document(s) in the file state the current address",
        how_to_fix=None,
        source_content_ids=content_ids,
    )


def _finding(**over: object) -> Finding:
    base: dict[str, object] = {
        "loan_file_id": uuid4(),
        "rule_id": "ID-4",
        "origin": FindingOrigin.DETERMINISTIC_RULE,
        "status": FindingStatus.YELLOW,
        "category": FindingCategory.DOCUMENTATION,
        "message": "an earlier message",
        # THE discriminator (LP-375): `origin` alone spans the retired xsrc findings too.
        "evaluation_outcome": EvaluationOutcome.OPEN,
        "source_document_ids": [_DOC_A, _DOC_B],
        "source_document_id": UUID(_DOC_A),
    }
    base.update(over)
    return Finding(**base)  # type: ignore[arg-type]


def test_a_run_that_resolved_no_documents_keeps_the_links_it_had() -> None:
    """Refreshing is right; refreshing to NOTHING on a run that admits it could not look is not.

    The documents section degrades, ID-4 still enumerates its borrower subjects (they come from the
    borrowers section), gathers nothing, returns couldnt_check, is re-detected — and its stored links
    were erased with the documents untouched on the file. The same now happens whenever the
    end-of-run provenance lookup degrades, which it can by design.
    """
    finding = _finding()

    _update_finding(
        finding,
        verification_id=uuid4(),
        result=_result(),
        outcome=EvaluationOutcome.COULDNT_CHECK,
        severity=FindingStatus.YELLOW,
        message="a fresh message",
        category=FindingCategory.DOCUMENTATION,
        document_id_by_content_id={},  # the run resolved nothing
    )

    assert finding.source_document_ids == [_DOC_A, _DOC_B]
    assert finding.source_document_id == UUID(_DOC_A)
    assert finding.message == "a fresh message", "everything else must still refresh"


def test_a_run_that_resolved_documents_replaces_the_links() -> None:
    """The other direction: a link must still follow a superseded document to its replacement."""
    new_doc = uuid4()
    finding = _finding()

    _update_finding(
        finding,
        verification_id=uuid4(),
        result=_result(content_ids=("doc-new",)),
        outcome=EvaluationOutcome.OPEN,
        severity=FindingStatus.YELLOW,
        message="m",
        category=FindingCategory.DOCUMENTATION,
        document_id_by_content_id={"doc-new": new_doc},
    )

    assert finding.source_document_ids == [str(new_doc)]
    assert finding.source_document_id == new_doc


@pytest.mark.asyncio
async def test_the_value_matcher_leaves_governed_findings_alone(db_session) -> None:  # type: ignore[no-untyped-def]
    """For a governed finding this populator TRUNCATES rather than enriches.

    `distinctive_values` returns [] for one (no `details["document_value"]`, no `source_snippet`), so
    `matched` is empty; LP-617 then made `source_document_id` non-null, so the primary is inserted at
    index 0 and the set is rewritten to that ONE id — a two-document ID-4 provenance collapsing to
    one. Both callers are dead today, so this pins the guard for whoever re-enables either.
    """
    from app.models.company import Company
    from app.models.document import Document, DocumentStatus
    from app.services.loan_files import create_loan_file

    company = Company(name="acme", slug=f"acme-{uuid4().hex[:8]}", is_active=True)
    db_session.add(company)
    await db_session.flush()
    loan_file = await create_loan_file(db_session, company_id=company.id)
    await db_session.flush()

    docs = []
    for name in ("paystub.pdf", "w2.pdf"):
        doc = Document(
            id=uuid4(),
            loan_file_id=loan_file.id,
            original_filename=name,
            mime_type="application/pdf",
            file_size_bytes=10,
            storage_path=f"{company.id}/{loan_file.id}/{name}",
            document_type="pay_stub",
            status=DocumentStatus.COMPLETED,
            upload_source="user_upload",
        )
        db_session.add(doc)
        docs.append(doc)
    await db_session.flush()

    finding = _finding(
        loan_file_id=loan_file.id,
        source_document_ids=[str(d.id) for d in docs],
        source_document_id=docs[0].id,
    )
    db_session.add(finding)
    await db_session.flush()

    await populate_finding_source_documents(db_session, loan_file_id=loan_file.id)

    assert finding.source_document_ids == [str(d.id) for d in docs], (
        "the governed finding's two-document provenance was truncated to its primary"
    )


@pytest.mark.asyncio
async def test_the_value_matcher_still_serves_a_retired_xsrc_finding(db_session) -> None:  # type: ignore[no-untyped-def]
    """The guard must key on `evaluation_outcome`, not `origin`.

    LP-375's discriminator exists because `deterministic_rule` spans BOTH the governed engine AND the
    retired xsrc findings — and the xsrc ones are exactly what this populator is for. A first cut of
    this guard keyed on origin, skipped them too, and broke the provenance it exists to build. Four
    existing tests caught it.
    """
    from app.models.company import Company
    from app.models.document import Document, DocumentStatus
    from app.models.extraction import ExtractionStatus
    from app.services.extractions import create_extraction_version
    from app.services.loan_files import create_loan_file

    company = Company(name="acme", slug=f"acme-{uuid4().hex[:8]}", is_active=True)
    db_session.add(company)
    await db_session.flush()
    loan_file = await create_loan_file(db_session, company_id=company.id)
    await db_session.flush()

    doc = Document(
        id=uuid4(),
        loan_file_id=loan_file.id,
        original_filename="paystub.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path=f"{company.id}/{loan_file.id}/paystub.pdf",
        document_type="pay_stub",
        status=DocumentStatus.COMPLETED,
        upload_source="user_upload",
    )
    db_session.add(doc)
    await db_session.flush()
    await create_extraction_version(
        db_session,
        document_id=doc.id,
        extracted_data={"employer": "SUMITOMO PHARMA AMERICAS INC"},
        extraction_status=ExtractionStatus.SUCCEEDED,
    )

    xsrc = _finding(
        loan_file_id=loan_file.id,
        rule_id="xsrc.income.employer_name_consistency",
        category=FindingCategory.CROSS_SOURCE,
        evaluation_outcome=None,  # a retired xsrc finding carries none — the discriminator
        details={"document_value": "SUMITOMO PHARMA AMERICAS INC"},
        source_document_ids=None,
        source_document_id=None,
    )
    db_session.add(xsrc)
    await db_session.flush()

    await populate_finding_source_documents(db_session, loan_file_id=loan_file.id)

    assert xsrc.source_document_ids == [str(doc.id)], "the xsrc finding lost its provenance"
