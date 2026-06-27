"""Tests for the AI needs reasoning (LP-69) — the AI is MOCKED.

Covers: file-context assembly, the two guardrails (1: file-specific reasoning, no
boilerplate; 2: proposals ingest as PROPOSED — never self-confirmed), reconciliation
(no duplication of the floor / covered needs), idempotent re-reasoning, graceful AI
failure, the correction-capture, and tenant scoping.

The mock returns representative proposals — the reasoning QUALITY is the AI's job +
the highest-value Priya refinement (validated against real files over time), NOT
asserted here. These verify the MECHANISM + the guardrails.
"""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.core.security import hash_password
from app.models import Company, User, UserRole
from app.models.borrower import Borrower
from app.models.document import Document, DocumentStatus
from app.models.document_finding import DocumentFindingType
from app.models.loan_file import AiNeedsStatus, LoanFile, LoanPurpose
from app.models.needs_item import NeedsItemDisposition, NeedsItemOrigin, NeedsItemStatus
from app.models.stated_financials import StatedAsset, StatedIncomeItem, StatedLiability
from app.services import needs_ai as needs_ai_module
from app.services.document_findings import create_document_finding
from app.services.loan_files import create_loan_file
from app.services.needs_ai import (
    apply_ai_needs,
    apply_ai_needs_for_file_id,
    assemble_file_context,
    propose_needs,
)
from app.services.needs_engine import record_need_correction, seed_floor_needs
from app.services.needs_items import create_needs_item
from sqlalchemy.ext.asyncio import AsyncSession

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _loan_file(
    db: AsyncSession, *, slug: str = "acme", purpose: LoanPurpose | None = LoanPurpose.PURCHASE
) -> LoanFile:
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
    return await create_loan_file(db, company_id=company.id, loan_purpose=purpose)


async def _self_employed_file(db: AsyncSession, *, slug: str = "acme") -> LoanFile:
    """A purchase file with self-employment income + a business — the canonical case."""
    lf = await _loan_file(db, slug=slug, purpose=LoanPurpose.PURCHASE)
    borrower = Borrower(loan_file_id=lf.id, first_name="Mahesh", last_name="Chhotala")
    db.add(borrower)
    await db.flush()
    db.add(
        StatedIncomeItem(
            borrower_id=borrower.id, income_type="SelfEmployment", employment_income=True
        )
    )
    db.add(StatedAsset(loan_file_id=lf.id, asset_type="GiftOfCash", value=Decimal("56000")))
    db.add(StatedLiability(loan_file_id=lf.id, liability_type="MortgageLoan", holder_name="Bank"))
    await db.flush()
    return lf


def _mock_ai(monkeypatch: pytest.MonkeyPatch, needs: list[dict]) -> AsyncMock:
    text = json.dumps({"needs": needs})
    mock = AsyncMock(
        return_value=SimpleNamespace(text=text, input_tokens=500, output_tokens=200, model="m")
    )
    monkeypatch.setattr(needs_ai_module, "complete", mock)
    return mock


# --------------------------------------------------------------------------- #
# File-context assembly
# --------------------------------------------------------------------------- #


async def test_assemble_file_context_gathers_the_whole_picture(db_session: AsyncSession) -> None:
    lf = await _self_employed_file(db_session)
    doc = Document(
        id=uuid4(),
        loan_file_id=lf.id,
        original_filename="x.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path="x",
        document_type="bank_statement",
        status=DocumentStatus.COMPLETED,
        upload_source="user_upload",
    )
    db_session.add(doc)
    await db_session.flush()
    await create_document_finding(
        db_session,
        document=doc,
        finding_type=DocumentFindingType.OBLIGATION,
        description="child support obligation",
    )
    await create_needs_item(
        db_session, loan_file_id=lf.id, title="Pay stubs", needs_type="pay_stub"
    )

    ctx = await assemble_file_context(db_session, lf)
    assert ctx.loan_purpose == "purchase"
    assert any(i["employment_income"] for i in ctx.income)
    assert ctx.assets and ctx.documents_present and ctx.findings
    # "already covered" folds in existing-need types + present document types.
    assert "pay_stub" in ctx.already_covered  # the existing need
    assert "bank_statement" in ctx.already_covered  # the present document


# --------------------------------------------------------------------------- #
# The reasoning + GUARDRAIL 1 (file-specific reasoning)
# --------------------------------------------------------------------------- #


async def test_propose_needs_returns_proposals_with_reasoning(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    lf = await _self_employed_file(db_session)
    _mock_ai(
        monkeypatch,
        [
            {
                "need_description": "Two years of tax returns",
                "need_type": "tax_return",
                "reasoning": "Self-employment income from the borrower's business is qualified "
                "from tax returns, not pay stubs.",
            },
            {
                "need_description": "Gift letter + donor sourcing",
                "need_type": "gift_letter",
                "reasoning": "A $56,000 gift of cash is stated — it must be documented as a "
                "genuine gift and sourced.",
            },
        ],
    )
    proposals = await propose_needs(db_session, lf)

    assert {p.need_type for p in proposals} == {"tax_return", "gift_letter"}
    # GUARDRAIL 1: every proposal carries non-empty, file-grounded reasoning.
    assert all(p.reasoning.strip() for p in proposals)
    assert any("tax returns" in p.reasoning for p in proposals)


async def test_proposal_without_reasoning_is_rejected(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GUARDRAIL 1: a need the model returns without reasoning is dropped (no boilerplate)."""
    lf = await _self_employed_file(db_session)
    _mock_ai(
        monkeypatch,
        [
            {"need_description": "Some doc", "need_type": "x", "reasoning": ""},  # dropped
            {"need_description": "Tax returns", "need_type": "tax_return", "reasoning": "self-emp"},
        ],
    )
    proposals = await propose_needs(db_session, lf)
    assert [p.need_type for p in proposals] == ["tax_return"]


async def test_ai_failure_is_graceful_and_records_failed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LP-71.5: a swallowed AI failure records FAILED (not silent) and never raises."""
    from app.ai.client import AIClientError

    lf = await _self_employed_file(db_session)
    monkeypatch.setattr(needs_ai_module, "complete", AsyncMock(side_effect=AIClientError("boom")))
    assert await propose_needs(db_session, lf) == []  # never raises
    assert lf.ai_needs_status is AiNeedsStatus.FAILED  # the failure is visible, not silent


async def test_apply_ai_needs_for_file_id_marks_completed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LP-71.5: a successful reasoning run flips the file's AI-needs status to COMPLETED."""
    lf = await _self_employed_file(db_session)
    lf.ai_needs_status = AiNeedsStatus.PENDING  # as the import leaves it
    await db_session.flush()
    _mock_ai(
        monkeypatch,
        [{"need_description": "Tax returns", "need_type": "tax_return", "reasoning": "self-emp"}],
    )
    await apply_ai_needs_for_file_id(db_session, lf.id)
    assert lf.ai_needs_status is AiNeedsStatus.COMPLETED


async def test_apply_ai_needs_for_file_id_keeps_failed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LP-71.5: an AI failure during the task leaves the status FAILED (not COMPLETED)."""
    from app.ai.client import AIClientError

    lf = await _self_employed_file(db_session)
    lf.ai_needs_status = AiNeedsStatus.PENDING
    await db_session.flush()
    monkeypatch.setattr(needs_ai_module, "complete", AsyncMock(side_effect=AIClientError("boom")))
    created = await apply_ai_needs_for_file_id(db_session, lf.id)
    assert created == []
    assert lf.ai_needs_status is AiNeedsStatus.FAILED


# --------------------------------------------------------------------------- #
# GUARDRAIL 2 (proposed, never self-confirmed) + reconciliation + ingestion
# --------------------------------------------------------------------------- #


async def test_apply_ai_needs_ingests_as_proposed_with_reasoning(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    lf = await _self_employed_file(db_session)
    _mock_ai(
        monkeypatch,
        [
            {
                "need_description": "Two years of tax returns",
                "need_type": "tax_return",
                "reasoning": "Self-employment income requires tax returns.",
            }
        ],
    )
    created = await apply_ai_needs(db_session, lf)

    assert len(created) == 1
    need = created[0]
    assert need.origin is NeedsItemOrigin.AI_REASONING  # source-agnostic provenance
    assert need.disposition is NeedsItemDisposition.PROPOSED  # GUARDRAIL 2 — never self-confirmed
    assert need.status is NeedsItemStatus.PENDING
    assert need.reasoning and "Self-employment" in need.reasoning  # explainability carried through


async def test_reconciliation_does_not_duplicate_the_floor(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LP-69 considers the floor (LP-68) + does NOT re-propose a covered need."""
    lf = await _self_employed_file(db_session)
    floor = await seed_floor_needs(db_session, lf)  # pay_stub + w2 + purchase_agreement + bank_stmt
    assert {n.needs_type for n in floor} >= {"pay_stub", "purchase_agreement"}

    _mock_ai(
        monkeypatch,
        [
            {
                "need_description": "Pay stubs",
                "need_type": "pay_stub",
                "reasoning": "income",
            },  # covered
            {"need_description": "Tax returns", "need_type": "tax_return", "reasoning": "self-emp"},
        ],
    )
    created = await apply_ai_needs(db_session, lf)

    types = {n.needs_type for n in created}
    assert "pay_stub" not in types  # NOT duplicated — the floor already has it
    assert types == {"tax_return"}  # only what's not covered


async def test_apply_ai_needs_is_idempotent(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    lf = await _self_employed_file(db_session)
    _mock_ai(
        monkeypatch,
        [{"need_description": "Tax returns", "need_type": "tax_return", "reasoning": "x"}],
    )
    first = await apply_ai_needs(db_session, lf)
    second = await apply_ai_needs(db_session, lf)  # re-reason (e.g. a document arrived)
    assert len(first) == 1
    assert second == []  # the tax_return need already exists — no duplicate


# --------------------------------------------------------------------------- #
# Correction-capture (improves from corrections — the V1 capture + simple use)
# --------------------------------------------------------------------------- #


async def test_correction_capture_dismiss_then_not_re_proposed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    lf = await _self_employed_file(db_session)
    # An AI proposal exists; the processor dismisses it (the capture).
    need = await create_needs_item(
        db_session,
        loan_file_id=lf.id,
        title="Tax returns",
        needs_type="tax_return",
        origin=NeedsItemOrigin.AI_REASONING,
        disposition=NeedsItemDisposition.PROPOSED,
    )
    await record_need_correction(db_session, need=need, action="dismiss", note="W-2 employee only.")
    assert need.disposition is NeedsItemDisposition.DISMISSED  # captured signal
    assert need.status is NeedsItemStatus.WAIVED

    # Simple use: the dismissed type is "already covered" → the AI won't re-propose it.
    ctx = await assemble_file_context(db_session, lf)
    assert "tax_return" in ctx.already_covered

    _mock_ai(
        monkeypatch,
        [{"need_description": "Tax returns", "need_type": "tax_return", "reasoning": "x"}],
    )
    created = await apply_ai_needs(db_session, lf)
    assert created == []  # the dismissed proposal is not resurrected


async def test_correction_capture_confirm(db_session: AsyncSession) -> None:
    lf = await _self_employed_file(db_session)
    need = await create_needs_item(
        db_session,
        loan_file_id=lf.id,
        title="Tax returns",
        needs_type="tax_return",
        origin=NeedsItemOrigin.AI_REASONING,
    )
    await record_need_correction(db_session, need=need, action="confirm")
    assert need.disposition is NeedsItemDisposition.CONFIRMED  # a real need
    assert need.status is NeedsItemStatus.PENDING  # still awaiting the document


# --------------------------------------------------------------------------- #
# Tenant scoping — context derives only from the file's own data
# --------------------------------------------------------------------------- #


async def test_context_is_scoped_to_the_file(db_session: AsyncSession) -> None:
    await _self_employed_file(db_session, slug="acme")  # company A's data
    lf_b = await _loan_file(db_session, slug="globex", purpose=LoanPurpose.REFINANCE)
    ctx_b = await assemble_file_context(db_session, lf_b)
    # File B has no borrowers/income/assets of its own — A's data does not leak in.
    assert ctx_b.income == [] and ctx_b.assets == [] and ctx_b.documents_present == []
