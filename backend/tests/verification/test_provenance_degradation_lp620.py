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
    FindingResolutionStatus,
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


def test_a_loan_level_rule_links_the_documents_its_tags_named() -> None:
    """LP-647 §1 review — end to end, at the field a processor reads.

    AS-8's subject is the LOAN, so `_attach_document_provenance` has nothing to attach: its two paths
    are "what the rule carried" and "the subject's own document", and a loan is not a document. The
    fix runs the other way — the recipe names the two statements it compared, the tag carries them,
    and `deterministic._named_documents` puts them on `source_content_ids`, which is the ONLY field
    `_source_document_ids` reads.

    Asserting the tag alone would not have caught this. §1's first version did exactly that and the
    finding still rendered with no documents.
    """
    from app.verification.rule_engine.result import LoadBearingTag

    s1, s2 = uuid4(), uuid4()
    finding = _finding()
    result = RuleEvaluation(
        rule_id="AS-8",
        subject_id="loan",  # the case with no document of its own
        verdict=Verdict.FIRED,
        verdict_confidence=None,
        load_bearing_tags=(
            LoadBearingTag(
                "stmt.continuity", "broken", None, "does not chain", ("doc-s1", "doc-s2")
            ),
        ),
        threshold_used=None,
        priya_validated=True,
        gated_pending_signoff=False,
        reasoning="the statements do not chain",
        how_to_fix=None,
        source_content_ids=("doc-s1", "doc-s2"),
    )

    _update_finding(
        finding,
        verification_id=uuid4(),
        result=result,
        outcome=EvaluationOutcome.OPEN,
        severity=FindingStatus.YELLOW,
        message="the statements do not chain",
        category=FindingCategory.DOCUMENTATION,
        document_id_by_content_id={"doc-s1": s1, "doc-s2": s2},
    )

    assert finding.source_document_ids == [str(s1), str(s2)], (
        "a loan-level rule that named its statements must link them — this is the field the "
        "SourceDocuments component renders from"
    )


def test_a_named_id_that_is_not_a_current_document_is_dropped_not_linked() -> None:
    """THE SAFETY THE BRIDGE RESTS ON, asserted rather than assumed.

    `_named_documents` unions a tag's `source_facts` without filtering, which is only safe because
    this resolution keeps ids present in the document map and DROPS the rest. A loan-level rule whose
    tags fell back to the subject contributes the literal string "loan"; a per-deposit tag could
    contribute a `txn` id. Neither is a document, and writing either would send a processor to the
    wrong page with the system's confidence behind it — the failure the whole section is written
    against.
    """
    real = uuid4()
    finding = _finding()

    _update_finding(
        finding,
        verification_id=uuid4(),
        result=_result(subject_id="loan", content_ids=("loan", "txn-abc", "doc-real")),
        outcome=EvaluationOutcome.OPEN,
        severity=FindingStatus.YELLOW,
        message="m",
        category=FindingCategory.DOCUMENTATION,
        document_id_by_content_id={"doc-real": real},
    )

    assert finding.source_document_ids == [str(real)], "only the real document survives"


def test_a_loan_level_finding_with_no_document_says_why() -> None:
    """LP-647 — an empty document list and a missing document rendered identically.

    A loan-level rule computes from the file's STATED data — the 1003 / MISMO import — and from
    figures other rules derived, so `source_documents` is correctly empty. But empty rendered as
    nothing, and "no document states this" is the opposite instruction to "the document is missing":
    one says read the application, the other says go and get a document.

    A STATEMENT, NEVER A LINK, and that is forced rather than chosen. The MISMO import IS stored
    (`mismo_imports.raw_file_path`) but is not a `Document` — `UploadSource.MISMO_IMPORT` exists in
    the enum with no writer anywhere — so nothing could resolve a link and it would dangle.
    """
    from app.schemas.verification import RuleFindingPublic

    finding = _finding()
    finding.subject_key = "loan"
    finding.source_document_ids = None
    finding.evaluation_outcome = EvaluationOutcome.OPEN
    finding.resolution_status = FindingResolutionStatus.OPEN
    finding.confidence = 0.9
    finding.status = FindingStatus.YELLOW
    finding.id = uuid4()  # DB-assigned in production; the schema requires it

    public = RuleFindingPublic.from_model(finding, subject_label="the loan")

    assert public.source_documents == []
    assert public.source_statement is not None
    assert "computed from the loan file's stated data" in public.source_statement
    assert "MISMO" in public.source_statement


def test_a_finding_that_HAS_documents_makes_no_statement() -> None:
    """The statement explains an absence. With documents present there is nothing to explain, and a
    sentence beside a document list would be noise contradicting the list next to it."""
    from app.schemas.verification import RuleFindingPublic

    doc_id = uuid4()
    finding = _finding()
    finding.subject_key = "loan"
    finding.source_document_ids = [str(doc_id)]
    finding.evaluation_outcome = EvaluationOutcome.OPEN
    finding.resolution_status = FindingResolutionStatus.OPEN
    finding.confidence = 0.9
    finding.status = FindingStatus.YELLOW
    finding.id = uuid4()  # DB-assigned in production; the schema requires it

    public = RuleFindingPublic.from_model(
        finding, subject_label="the loan", document_names={doc_id: "1003.pdf"}
    )

    assert public.source_documents and public.source_statement is None


def test_a_document_subject_with_no_provenance_stays_SILENT() -> None:
    """THE CASE THAT MUST NOT GAIN A SENTENCE, and the reason the statement is scoped to loan
    subjects rather than to "no documents".

    A per-document or per-borrower rule with no provenance has a GAP — its subject IS or belongs to a
    document, so something should have named it. Explaining that absence away would paper over
    exactly the thing worth finding, which is how 449 findings across 57 rules went unnoticed until
    they were counted.
    """
    from app.schemas.verification import RuleFindingPublic

    finding = _finding()
    finding.subject_key = "doc-abc123"  # a document subject, not the loan
    finding.source_document_ids = None
    finding.evaluation_outcome = EvaluationOutcome.OPEN
    finding.resolution_status = FindingResolutionStatus.OPEN
    finding.confidence = 0.9
    finding.status = FindingStatus.YELLOW
    finding.id = uuid4()  # DB-assigned in production; the schema requires it

    public = RuleFindingPublic.from_model(finding, subject_label="a document")

    assert public.source_statement is None, "an unexplained gap must stay visible as one"


def test_an_AI_JUDGED_rule_gets_no_statement_because_the_model_read_the_documents() -> None:
    """LP-647 review — the defect the group C fix SHIPPED WITH, found by asking what group D is.

    `_source_statement` fired on any loan-subject finding with no documents. DT-7, OC-3 and the AI
    half of OC-1/OC-2 are all loan-subject and carry no provenance — so they were told "computed from
    the loan file's stated data (the application / MISMO import)".

    That is FALSE. Those verdicts come from a model that was handed the file's DOCUMENTS —
    `applies_to: all`, a cap of 60, 44 of them on LF-ZE9N — not from the 1003. And a false provenance
    sentence is worse than none: a processor cannot tell which of the true ones to trust, which is the
    exact reason the group C wording was kept vague enough to be true of all eleven rules.

    Silence is right here. "All 44 documents" is not provenance either; the only real answer is asking
    the model which drove the judgement, and that is group D — a prompt change, not something a
    read-layer sentence can stand in for.
    """
    from app.schemas.verification import RuleFindingPublic

    finding = _finding()
    finding.subject_key = "loan"
    finding.source_document_ids = None
    finding.evaluation_outcome = EvaluationOutcome.NEEDS_REVIEW
    finding.resolution_status = FindingResolutionStatus.OPEN
    finding.confidence = 0.9
    finding.status = FindingStatus.YELLOW
    finding.id = uuid4()
    # DT-7's shape: one load-bearing tag, declared `mode: ai`.
    finding.load_bearing_tags = [
        {
            "tag_id": "dti.atr_factors_documented",
            "value": "no",
            "reasoning": "r",
            "source_facts": [],
        }
    ]

    public = RuleFindingPublic.from_model(finding, subject_label="the loan")

    assert public.source_statement is None, (
        "an AI judgement over the file's documents must not claim to come from stated data — "
        f"got {public.source_statement!r}"
    )


def test_a_derived_loan_rule_still_gets_its_statement() -> None:
    """THE POSITIVE CONTROL. Excluding AI tags must not silence the eleven rules the statement was
    built for — and the check is on the TAG's declared mode, not the rule's `kind`, because OC-1 is
    `structural` and still reads an AI tag."""
    from app.schemas.verification import RuleFindingPublic

    finding = _finding()
    finding.subject_key = "loan"
    finding.source_document_ids = None
    finding.evaluation_outcome = EvaluationOutcome.OPEN
    finding.resolution_status = FindingResolutionStatus.OPEN
    finding.confidence = 0.9
    finding.status = FindingStatus.YELLOW
    finding.id = uuid4()
    finding.load_bearing_tags = [
        {"tag_id": "occupancy.stated", "value": "primary", "reasoning": "r", "source_facts": []}
    ]

    public = RuleFindingPublic.from_model(finding, subject_label="the loan")

    assert public.source_statement is not None
    assert "computed from the loan file's stated data" in public.source_statement
