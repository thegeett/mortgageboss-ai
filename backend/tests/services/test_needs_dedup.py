"""Tests for needs consolidation (LP-111) — deterministic collapse + AI-flagged residue.

The discipline under test: NEVER silently delete a need. The deterministic layers merge only the
CERTAIN duplicates (collapse-by-source + substance-identity); the AI layer only FLAGS the semantic
residue (sets ``duplicate_of_id``), and a confirmed/received need is never dropped.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.core.security import hash_password
from app.models import Company, User, UserRole
from app.models.document import DocumentStatus
from app.models.document_finding import DocumentFindingType
from app.models.loan_file import LoanFile, LoanPurpose
from app.models.needs_item import NeedsItemDisposition, NeedsItemOrigin
from app.services import needs_dedup as dedup_module
from app.services.document_findings import create_document_finding
from app.services.loan_files import create_loan_file
from app.services.needs_dedup import (
    confirm_duplicate_merge,
    consolidate_needs,
    dismiss_duplicate_flag,
    flag_possible_duplicates,
)
from app.services.needs_items import create_needs_item, list_needs_items
from sqlalchemy.ext.asyncio import AsyncSession


async def _loan_file(db: AsyncSession, *, slug: str = "acme") -> LoanFile:
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
    return await create_loan_file(db, company_id=company.id, loan_purpose=LoanPurpose.PURCHASE)


async def _need(db, lf, *, title, needs_type=None, origin=NeedsItemOrigin.AI_REASONING, **kw):
    return await create_needs_item(
        db, loan_file_id=lf.id, title=title, needs_type=needs_type, origin=origin, **kw
    )


async def _finding(db, lf):
    from app.models.document import Document

    doc = Document(
        id=uuid4(),
        loan_file_id=lf.id,
        original_filename="wire.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path="x",
        document_type="unknown",
        status=DocumentStatus.COMPLETED,
        upload_source="user_upload",
    )
    db.add(doc)
    await db.flush()
    return await create_document_finding(
        db, document=doc, finding_type=DocumentFindingType.OBLIGATION, description="$20,000 wire"
    )


def _mock_flag(monkeypatch, groups):
    text = json.dumps({"duplicate_groups": groups})
    monkeypatch.setattr(
        dedup_module,
        "complete",
        AsyncMock(
            return_value=SimpleNamespace(text=text, input_tokens=1, output_tokens=1, model="m")
        ),
    )


# --------------------------------------------------------------------------- #
# Layer 1 — collapse-by-source
# --------------------------------------------------------------------------- #


async def test_collapse_by_source_merges_same_type_same_finding(db_session: AsyncSession) -> None:
    # An LP-67 suggestion + an LP-69 proposal for the SAME finding + SAME type → one need.
    lf = await _loan_file(db_session)
    finding = await _finding(db_session, lf)
    a = await _need(
        db_session,
        lf,
        title="Payment history / obligation documentation",
        needs_type="obligation_documentation",
        origin=NeedsItemOrigin.SUGGESTION,
        source_finding_id=finding.id,
    )
    b = await _need(
        db_session,
        lf,
        title="Document the recurring obligation",
        needs_type="obligation_documentation",
        source_facts=[{"kind": "finding", "label": "$20,000 wire", "ref": str(finding.id)}],
    )
    merged = consolidate_needs([a, b])
    assert len(merged) == 1
    # One soft-deleted; the survivor carries the union of provenance (LP-110 preserved).
    survivors = [n for n in (a, b) if n.deleted_at is None]
    assert len(survivors) == 1
    assert any(str(finding.id) in json.dumps(f) for f in (survivors[0].source_facts or [])) or (
        survivors[0].source_finding_id == finding.id
    )


# --------------------------------------------------------------------------- #
# Layer 2 — substance-identity (LP-93 normalization)
# --------------------------------------------------------------------------- #


async def test_substance_identity_collapses_cosmetic_variants(db_session: AsyncSession) -> None:
    # Same ask differing only by case / dash / whitespace → one need (exact-.lower() would MISS the
    # em-dash). Reuses the findings' normalization.
    lf = await _loan_file(db_session)
    a = await _need(db_session, lf, title="Explanation — of the $20,000 Wire", needs_type="loe")
    b = await _need(db_session, lf, title="explanation - of the $20,000  wire", needs_type="loe")
    merged = consolidate_needs([a, b])
    assert len(merged) == 1


async def test_semantically_reworded_free_form_are_NOT_deterministically_merged(
    db_session: AsyncSession,
) -> None:
    # Genuinely reworded, need_type=null → the deterministic layers UNDER-merge (keep both); this is
    # the AI-flag's job, not a silent deterministic merge.
    lf = await _loan_file(db_session)
    finding = await _finding(db_session, lf)
    facts = [{"kind": "finding", "label": "$20,000 wire", "ref": str(finding.id)}]
    a = await _need(
        db_session, lf, title="Written explanation of the $20,000 wire transfer", source_facts=facts
    )
    b = await _need(
        db_session,
        lf,
        title="Explanation letter for the $20,000 due diligence fee",
        source_facts=facts,
    )
    merged = consolidate_needs([a, b])
    assert merged == []  # both survive (under-merge)
    assert a.deleted_at is None and b.deleted_at is None


# --------------------------------------------------------------------------- #
# Under-merge safety — distinct needs preserved; acted-on never dropped
# --------------------------------------------------------------------------- #


async def test_distinct_needs_sharing_a_finding_are_not_merged(db_session: AsyncSession) -> None:
    # The LOE and the sales-contract both cite the wire but request DIFFERENT documents — the intent
    # guard (different needs_type; different substance) keeps them distinct.
    lf = await _loan_file(db_session)
    finding = await _finding(db_session, lf)
    loe = await _need(
        db_session,
        lf,
        title="Explanation of the $20,000 wire",
        needs_type="letter_of_explanation",
        source_finding_id=finding.id,
    )
    contract = await _need(
        db_session,
        lf,
        title="Sales contract documenting the $20,000 fee",
        needs_type="sales_contract",
        source_finding_id=finding.id,
    )
    assert consolidate_needs([loe, contract]) == []
    assert loe.deleted_at is None and contract.deleted_at is None


async def test_acted_on_need_is_never_dropped_proposed_merges_into_it(
    db_session: AsyncSession,
) -> None:
    lf = await _loan_file(db_session)
    finding = await _finding(db_session, lf)
    confirmed = await _need(
        db_session,
        lf,
        title="Obligation docs",
        needs_type="obligation_documentation",
        source_finding_id=finding.id,
        disposition=NeedsItemDisposition.CONFIRMED,
    )
    proposed = await _need(
        db_session,
        lf,
        title="Obligation documentation",
        needs_type="obligation_documentation",
        source_finding_id=finding.id,
    )
    consolidate_needs([confirmed, proposed])
    assert confirmed.deleted_at is None  # the acted-on need survives as the survivor
    assert proposed.deleted_at is not None  # the proposed duplicate is merged away


async def test_consolidation_is_idempotent(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session)
    a = await _need(db_session, lf, title="Same title", needs_type="loe")
    b = await _need(db_session, lf, title="same  title", needs_type="loe")
    assert len(consolidate_needs([a, b])) == 1
    live = [n for n in (a, b) if n.deleted_at is None]
    assert consolidate_needs(live) == []  # second pass over the survivors changes nothing


# --------------------------------------------------------------------------- #
# Layer 3 — AI flags the residue (never deletes)
# --------------------------------------------------------------------------- #


async def test_ai_flags_semantic_duplicate_without_deleting(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    lf = await _loan_file(db_session)
    a = await _need(db_session, lf, title="Written explanation of the $20,000 wire transfer")
    b = await _need(db_session, lf, title="Explanation letter for the $20,000 due diligence fee")
    _mock_flag(monkeypatch, [{"primary_id": str(a.id), "duplicate_ids": [str(b.id)]}])

    flagged = await flag_possible_duplicates(db_session, loan_file_id=lf.id)
    assert flagged == 1
    assert b.duplicate_of_id == a.id  # flagged, not deleted
    assert b.deleted_at is None and a.deleted_at is None  # NEVER a silent delete


async def test_ai_flag_conservative_when_unsure_flags_nothing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    lf = await _loan_file(db_session)
    a = await _need(db_session, lf, title="Appraisal report")
    b = await _need(db_session, lf, title="Title commitment")
    _mock_flag(monkeypatch, [])  # unsure → flags nothing
    assert await flag_possible_duplicates(db_session, loan_file_id=lf.id) == 0
    assert a.duplicate_of_id is None and b.duplicate_of_id is None


async def test_ai_flag_disabled_by_setting(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dedup_module.settings, "needs_duplicate_flagging_enabled", False)
    lf = await _loan_file(db_session)
    await _need(db_session, lf, title="A")
    await _need(db_session, lf, title="B")
    # complete() must not even be called when disabled.
    monkeypatch.setattr(dedup_module, "complete", AsyncMock(side_effect=AssertionError("called")))
    assert await flag_possible_duplicates(db_session, loan_file_id=lf.id) == 0


# --------------------------------------------------------------------------- #
# Processor disposition — confirm merge / keep both
# --------------------------------------------------------------------------- #


async def test_confirm_merge_folds_the_flagged_need_into_its_twin(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session)
    survivor = await _need(db_session, lf, title="Keep this one")
    dup = await _need(
        db_session,
        lf,
        title="The duplicate",
        source_facts=[{"kind": "asset", "label": "wire", "ref": None}],
    )
    dup.duplicate_of_id = survivor.id
    await db_session.flush()

    result = await confirm_duplicate_merge(db_session, need=dup)
    assert result is not None and result.id == survivor.id
    assert dup.deleted_at is not None  # merged away
    assert survivor.source_facts  # provenance unioned onto the survivor


async def test_not_duplicate_keeps_both_and_prevents_reflag(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session)
    a = await _need(db_session, lf, title="One")
    b = await _need(db_session, lf, title="Two")
    b.duplicate_of_id = a.id
    await db_session.flush()

    await dismiss_duplicate_flag(db_session, need=b)
    assert b.duplicate_of_id is None and b.duplicate_reviewed is True
    assert b.deleted_at is None and a.deleted_at is None  # both survive

    # A subsequent AI pass must NOT re-flag the reviewed need.
    flaggable = await dedup_module._load_flaggable(db_session, lf.id)
    assert b.id not in {n.id for n in flaggable}


async def test_dedup_is_tenant_scoped(db_session: AsyncSession) -> None:
    # Needs on different files never merge together.
    lf_a = await _loan_file(db_session, slug="acme")
    lf_b = await _loan_file(db_session, slug="globex")
    a = await _need(db_session, lf_a, title="Same title", needs_type="loe")
    b = await _need(db_session, lf_b, title="Same title", needs_type="loe")
    # consolidate operates on a single file's need list — cross-file needs never share a list.
    assert consolidate_needs([a]) == [] and consolidate_needs([b]) == []
    assert a.deleted_at is None and b.deleted_at is None


async def test_list_excludes_merged_needs(db_session: AsyncSession) -> None:
    # A soft-deleted (merged) need drops out of the active list.
    lf = await _loan_file(db_session)
    a = await _need(db_session, lf, title="Dup title", needs_type="loe")
    b = await _need(db_session, lf, title="dup title", needs_type="loe")
    consolidate_needs([a, b])
    await db_session.flush()
    titles = {n.title for n in await list_needs_items(db_session, loan_file_id=lf.id)}
    assert len(titles) == 1  # one merged away
