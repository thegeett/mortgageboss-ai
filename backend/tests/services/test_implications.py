"""Tests for the implications engine (LP-67) — findings → suggested needs.

Covers the findings-scoped mapping (each finding type → a sensible suggested need
with reasoning), the LOCKED constraint (SURFACE + SUGGEST, never act — no financial
mutation, no needs-list item created), explainability + traceability (reasoning +
source-finding → document link), the divorce-decree end-to-end, and tenant scoping.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from app.ai.extraction.divorce_decree import DivorceDecreeExtraction, SupportObligation
from app.core.security import hash_password
from app.models import Company, User, UserRole
from app.models.document import Document, DocumentStatus
from app.models.document_finding import DocumentFinding, DocumentFindingStatus, DocumentFindingType
from app.models.needs_item import NeedsItem
from app.services.document_findings import (
    create_document_finding,
    list_findings_for_loan_file,
    record_findings_from_extraction,
)
from app.services.implications import (
    SuggestedNeed,
    suggest_needs_for_finding,
    suggest_needs_for_loan_file,
)
from app.services.loan_files import create_loan_file
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_document(db: AsyncSession, *, slug: str = "acme") -> Document:
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
    doc = Document(
        id=uuid4(),
        loan_file_id=loan_file.id,
        original_filename="x.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path=f"{company.id}/{loan_file.id}/x.pdf",
        status=DocumentStatus.COMPLETED,
        upload_source="user_upload",
    )
    db.add(doc)
    await db.flush()
    return doc


def _finding(
    finding_type: DocumentFindingType,
    *,
    amount: Decimal | None = None,
    frequency: str | None = None,
) -> DocumentFinding:
    """A detached finding for the pure-mapping tests (no DB needed)."""
    f = DocumentFinding(
        finding_type=finding_type,
        description=f"{finding_type.value} observed in the document",
        amount=amount,
        frequency=frequency,
        details={},
    )
    f.id = uuid4()
    f.document_id = uuid4()
    return f


# --------------------------------------------------------------------------- #
# The findings-scoped mapping
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("finding_type", "need_type"),
    [
        (DocumentFindingType.OBLIGATION, "obligation_documentation"),
        (DocumentFindingType.INCOME_RELATED, "income_verification"),
        (DocumentFindingType.PROPERTY_INTEREST, "property_documentation"),
        (DocumentFindingType.DISCREPANCY_CANDIDATE, "discrepancy_review"),
    ],
)
def test_each_finding_type_maps_to_a_sensible_need(
    finding_type: DocumentFindingType, need_type: str
) -> None:
    suggestions = suggest_needs_for_finding(_finding(finding_type))
    assert len(suggestions) == 1
    assert suggestions[0].need_type == need_type
    assert suggestions[0].need_description  # a non-empty human description


def test_other_finding_suggests_nothing() -> None:
    """An unmappable 'other' finding surfaces no suggestion (sensible none, not noise)."""
    assert suggest_needs_for_finding(_finding(DocumentFindingType.OTHER)) == []


def test_suggestion_is_explainable_and_traceable() -> None:
    """Every suggestion carries reasoning + the source-finding → document link."""
    finding = _finding(
        DocumentFindingType.OBLIGATION, amount=Decimal("500.00"), frequency="monthly"
    )
    suggestion = suggest_needs_for_finding(finding)[0]
    assert suggestion.reasoning.startswith("Because")  # the WHY
    assert str(finding.document_id) in suggestion.reasoning  # traces to the document
    assert "$500.00/monthly" in suggestion.reasoning  # the obligation amount is surfaced
    # The machine-traceable chain: suggestion → finding → document.
    assert suggestion.source_finding_id == finding.id
    assert suggestion.source_document_id == finding.document_id


# --------------------------------------------------------------------------- #
# THE LOCKED CONSTRAINT — surface + suggest, do NOT act
# --------------------------------------------------------------------------- #


async def test_surface_not_act_no_financial_mutation(db_session: AsyncSession) -> None:
    """The engine produces suggestions only — it creates NO needs-list item and
    mutates NO finding / financial data (the critical constraint)."""
    doc = await _make_document(db_session)
    finding = await create_document_finding(
        db_session,
        document=doc,
        finding_type=DocumentFindingType.OBLIGATION,
        description="child support obligation",
        amount=Decimal("500.00"),
        frequency="monthly",
    )
    await db_session.commit()

    needs_before = await db_session.scalar(select(func.count()).select_from(NeedsItem))

    suggestions = await suggest_needs_for_loan_file(db_session, loan_file_id=doc.loan_file_id)

    # It SUGGESTED — but acted on nothing.
    assert len(suggestions) == 1 and isinstance(suggestions[0], SuggestedNeed)
    needs_after = await db_session.scalar(select(func.count()).select_from(NeedsItem))
    assert needs_after == needs_before  # NO needs-list item was created
    await db_session.refresh(finding)
    assert finding.status is DocumentFindingStatus.OPEN  # the finding is unchanged
    assert finding.amount == Decimal("500.00")


# --------------------------------------------------------------------------- #
# End-to-end: a divorce decree's obligation finding → a suggested need
# --------------------------------------------------------------------------- #


async def test_divorce_decree_finding_to_suggested_need_end_to_end(
    db_session: AsyncSession,
) -> None:
    """divorce decree (LP-63) → obligation finding (LP-66) → suggested need (LP-67)."""
    doc = await _make_document(db_session)
    doc.document_type = "divorce_decree"
    # LP-66 records the obligation as a finding via the same shared mechanism.
    await record_findings_from_extraction(
        db_session,
        doc,
        DivorceDecreeExtraction(
            support_obligations=[
                SupportObligation(
                    obligation_type="child_support",
                    amount=Decimal("500.00"),
                    frequency="monthly",
                    payer="John Doe",
                )
            ]
        ),
    )
    await db_session.commit()

    suggestions = await suggest_needs_for_loan_file(db_session, loan_file_id=doc.loan_file_id)
    assert len(suggestions) == 1
    s = suggestions[0]
    assert s.need_type == "obligation_documentation"
    assert "$500.00/monthly" in s.reasoning  # the decree's obligation, surfaced + explained
    # Traceable back to the finding the divorce decree produced.
    findings = await list_findings_for_loan_file(db_session, loan_file_id=doc.loan_file_id)
    assert s.source_finding_id == findings[0].id


# --------------------------------------------------------------------------- #
# Tenant scoping — suggestions derive from the file's OWN findings
# --------------------------------------------------------------------------- #


async def test_suggestions_are_scoped_to_the_files_own_findings(db_session: AsyncSession) -> None:
    doc_a = await _make_document(db_session, slug="acme")
    doc_b = await _make_document(db_session, slug="globex")
    await create_document_finding(
        db_session,
        document=doc_a,
        finding_type=DocumentFindingType.OBLIGATION,
        description="A-only obligation",
    )
    await db_session.commit()

    a_suggestions = await suggest_needs_for_loan_file(db_session, loan_file_id=doc_a.loan_file_id)
    b_suggestions = await suggest_needs_for_loan_file(db_session, loan_file_id=doc_b.loan_file_id)
    assert len(a_suggestions) == 1  # derived from A's finding
    assert b_suggestions == []  # B's file has no findings → no suggestions from A's
