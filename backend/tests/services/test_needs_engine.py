"""Tests for the needs-list engine (LP-68) — deterministic, stateful, concurrent.

Covers: the five-state transitions (valid + invalid guarded), type-level
satisfaction-matching (Received → Verified | Rejected; no false match), the thin
deterministic floor (from the stated MISMO data), LP-67 suggestion ingestion, and
— the critical piece — PER-FILE SERIALIZATION (the Redis lock serializes the same
file + parallelizes different files; the matching is correct under serialized
order: no lost update / double-satisfy).
"""

from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from app.core.config import settings
from app.core.security import hash_password
from app.models import Company, User, UserRole
from app.models.borrower import Borrower
from app.models.document import Document, DocumentStatus
from app.models.document_finding import DocumentFindingType
from app.models.loan_file import LoanFile, LoanPurpose
from app.models.needs_item import (
    NeedsItem,
    NeedsItemDisposition,
    NeedsItemOrigin,
    NeedsItemStatus,
)
from app.models.stated_financials import StatedAsset, StatedIncomeItem
from app.services import needs_engine
from app.services.document_findings import create_document_finding
from app.services.implications import SuggestedNeed
from app.services.loan_files import create_loan_file
from app.services.needs_engine import (
    InvalidNeedTransition,
    apply_document_to_needs,
    ingest_suggested_need,
    loan_file_needs_lock,
    seed_floor_needs,
    transition_need,
    waive_need,
)
from app.services.needs_items import create_needs_item
from sqlalchemy.ext.asyncio import AsyncSession

# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


async def _loan_file(
    db: AsyncSession, *, slug: str = "acme", purpose: LoanPurpose | None = None
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


async def _document(
    db: AsyncSession, loan_file: LoanFile, *, document_type: str, status: DocumentStatus
) -> Document:
    doc = Document(
        id=uuid4(),
        loan_file_id=loan_file.id,
        original_filename="x.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path=f"{loan_file.company_id}/{loan_file.id}/x.pdf",
        document_type=document_type,
        status=status,
        upload_source="user_upload",
    )
    db.add(doc)
    await db.flush()
    return doc


async def _pending_need(db: AsyncSession, loan_file: LoanFile, *, needs_type: str) -> NeedsItem:
    return await create_needs_item(
        db, loan_file_id=loan_file.id, title=f"Need: {needs_type}", needs_type=needs_type
    )


# --------------------------------------------------------------------------- #
# State transitions (guarded)
# --------------------------------------------------------------------------- #


async def test_valid_transition_sequence(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session)
    need = await _pending_need(db_session, lf, needs_type="pay_stub")
    doc = await _document(db_session, lf, document_type="pay_stub", status=DocumentStatus.COMPLETED)
    await transition_need(
        db_session, need=need, to_state=NeedsItemStatus.RECEIVED, document_id=doc.id
    )
    assert need.status is NeedsItemStatus.RECEIVED
    assert need.satisfied_by_document_id == doc.id
    await transition_need(db_session, need=need, to_state=NeedsItemStatus.VERIFIED)
    assert need.status is NeedsItemStatus.VERIFIED
    assert need.satisfied_at is not None


async def test_invalid_transition_is_guarded(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session)
    need = await _pending_need(db_session, lf, needs_type="pay_stub")
    # PENDING -> VERIFIED skips RECEIVED — not allowed.
    with pytest.raises(InvalidNeedTransition):
        await transition_need(db_session, need=need, to_state=NeedsItemStatus.VERIFIED)


async def test_waive_from_any_state(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session)
    need = await _pending_need(db_session, lf, needs_type="pay_stub")
    await waive_need(db_session, need=need, reason="Borrower is retired — N/A.")
    assert need.status is NeedsItemStatus.WAIVED
    assert need.disposition is NeedsItemDisposition.WAIVED
    assert need.reason == "Borrower is retired — N/A."


# --------------------------------------------------------------------------- #
# Satisfaction-matching (deterministic, type-level)
# --------------------------------------------------------------------------- #


async def test_passing_document_verifies_matching_need(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session)
    need = await _pending_need(db_session, lf, needs_type="pay_stub")
    doc = await _document(db_session, lf, document_type="pay_stub", status=DocumentStatus.COMPLETED)

    matched = await apply_document_to_needs(db_session, doc)
    assert matched is not None and matched.id == need.id
    assert need.status is NeedsItemStatus.VERIFIED
    assert need.satisfied_by_document_id == doc.id


async def test_failed_document_rejects_matching_need(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session)
    need = await _pending_need(db_session, lf, needs_type="pay_stub")
    doc = await _document(
        db_session, lf, document_type="pay_stub", status=DocumentStatus.NEEDS_REVIEW
    )

    await apply_document_to_needs(db_session, doc)
    assert need.status is NeedsItemStatus.REJECTED  # arrived but failed — still open
    assert need.reason is not None


async def test_non_matching_type_is_no_false_satisfaction(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session)
    need = await _pending_need(db_session, lf, needs_type="pay_stub")
    # A W-2 arrives — it must NOT satisfy the pay_stub need.
    doc = await _document(db_session, lf, document_type="w2", status=DocumentStatus.COMPLETED)

    matched = await apply_document_to_needs(db_session, doc)
    assert matched is None
    assert need.status is NeedsItemStatus.PENDING  # untouched


async def test_untyped_document_is_a_noop(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session)
    await _pending_need(db_session, lf, needs_type="pay_stub")
    doc = Document(
        id=uuid4(),
        loan_file_id=lf.id,
        original_filename="x.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path="x",
        document_type=None,  # unclassified
        status=DocumentStatus.NEEDS_REVIEW,
        upload_source="user_upload",
    )
    db_session.add(doc)
    await db_session.flush()
    assert await apply_document_to_needs(db_session, doc) is None


# --------------------------------------------------------------------------- #
# The thin deterministic floor (from the stated MISMO data)
# --------------------------------------------------------------------------- #


async def test_floor_from_stated_employment_and_purchase(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session, purpose=LoanPurpose.PURCHASE)
    borrower = Borrower(loan_file_id=lf.id, first_name="Jane", last_name="Doe")
    db_session.add(borrower)
    await db_session.flush()
    db_session.add(
        StatedIncomeItem(
            borrower_id=borrower.id, monthly_amount=Decimal("6000"), employment_income=True
        )
    )
    db_session.add(StatedAsset(loan_file_id=lf.id, asset_type="Checking", value=Decimal("20000")))
    await db_session.flush()

    created = await seed_floor_needs(db_session, lf)
    types = {n.needs_type for n in created}
    # employment income → pay_stub + w2; purchase → purchase_agreement; assets → bank_statement
    assert types == {"pay_stub", "w2", "purchase_agreement", "bank_statement"}
    assert all(n.origin is NeedsItemOrigin.FLOOR for n in created)
    assert all(n.disposition is NeedsItemDisposition.CONFIRMED for n in created)  # near-certain


async def test_floor_is_idempotent(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session, purpose=LoanPurpose.PURCHASE)
    first = await seed_floor_needs(db_session, lf)
    assert len(first) == 1  # purchase_agreement only (no stated income/assets)
    second = await seed_floor_needs(db_session, lf)
    assert second == []  # already seeded — no duplicates


async def test_floor_thin_when_no_stated_data(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session, purpose=LoanPurpose.REFINANCE)  # no income/assets/purchase
    assert await seed_floor_needs(db_session, lf) == []


# --------------------------------------------------------------------------- #
# Source-agnostic ingestion of LP-67 suggestions
# --------------------------------------------------------------------------- #


async def test_ingest_suggested_need_carries_reasoning_and_source(db_session: AsyncSession) -> None:
    lf = await _loan_file(db_session)
    doc = await _document(
        db_session, lf, document_type="divorce_decree", status=DocumentStatus.COMPLETED
    )
    finding = await create_document_finding(
        db_session,
        document=doc,
        finding_type=DocumentFindingType.OBLIGATION,
        description="child support obligation",
    )
    suggested = SuggestedNeed(
        need_description="Payment history / obligation documentation",
        need_type="obligation_documentation",
        reasoning="Because document X asserts a $500/mo obligation, document it.",
        source_finding_id=finding.id,
        source_document_id=doc.id,
    )

    need = await ingest_suggested_need(db_session, loan_file_id=lf.id, suggested=suggested)
    assert need is not None
    assert need.origin is NeedsItemOrigin.SUGGESTION
    assert need.disposition is NeedsItemDisposition.PROPOSED  # awaits processor confirmation
    assert need.reasoning == suggested.reasoning  # explainability carried through
    assert need.source_finding_id == finding.id  # traceable to the finding

    # Idempotent per source finding — re-ingesting is a no-op.
    assert await ingest_suggested_need(db_session, loan_file_id=lf.id, suggested=suggested) is None


# --------------------------------------------------------------------------- #
# PER-FILE SERIALIZATION — the race fix (the critical proof)
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def _loop_bound_redis(monkeypatch: pytest.MonkeyPatch):
    """A fresh Redis client bound to this test's event loop (avoids singleton/loop issues)."""
    client = aioredis.from_url(str(settings.redis_url), decode_responses=True)
    monkeypatch.setattr(needs_engine, "get_redis_client", lambda: client)
    yield client
    await client.aclose()


async def test_per_file_lock_serializes_same_file_parallelizes_different(
    _loop_bound_redis,
) -> None:
    """SAME file → the lock is exclusive (a second acquire fails while held); DIFFERENT
    files → independent locks acquire in parallel. The serialization primitive."""
    file_a = uuid4()
    file_b = uuid4()
    async with loan_file_needs_lock(file_a, timeout=5, blocking_timeout=0) as a:
        assert a is True
        # Same file: another worker cannot acquire while A holds it (serialized).
        async with loan_file_needs_lock(file_a, timeout=5, blocking_timeout=0) as a2:
            assert a2 is False
        # Different file: an independent lock acquires freely (parallel).
        async with loan_file_needs_lock(file_b, timeout=5, blocking_timeout=0) as b:
            assert b is True
    # After release, the same file's lock is acquirable again.
    async with loan_file_needs_lock(file_a, timeout=5, blocking_timeout=0) as a3:
        assert a3 is True


async def test_serialized_application_no_double_satisfy(db_session: AsyncSession) -> None:
    """Under serialized order (what the lock guarantees), two matching documents do
    not double-satisfy / clobber: the first verifies the need; the second no-ops."""
    lf = await _loan_file(db_session)
    need = await _pending_need(db_session, lf, needs_type="pay_stub")
    doc1 = await _document(
        db_session, lf, document_type="pay_stub", status=DocumentStatus.COMPLETED
    )
    doc2 = await _document(
        db_session, lf, document_type="pay_stub", status=DocumentStatus.COMPLETED
    )

    first = await apply_document_to_needs(db_session, doc1)  # serialized: applies first
    second = await apply_document_to_needs(db_session, doc2)  # then this one

    assert first is not None and first.id == need.id
    assert second is None  # no open pay_stub need left — no double-satisfy / lost update
    assert need.status is NeedsItemStatus.VERIFIED
    assert need.satisfied_by_document_id == doc1.id  # the first document, not clobbered


# --------------------------------------------------------------------------- #
# Tenant scoping — matching only touches the document's own file's needs
# --------------------------------------------------------------------------- #


async def test_matching_is_scoped_to_the_documents_file(db_session: AsyncSession) -> None:
    lf_a = await _loan_file(db_session, slug="acme")
    lf_b = await _loan_file(db_session, slug="globex")
    need_b = await _pending_need(db_session, lf_b, needs_type="pay_stub")
    # A pay_stub doc on file A must not touch file B's need.
    doc_a = await _document(
        db_session, lf_a, document_type="pay_stub", status=DocumentStatus.COMPLETED
    )

    await apply_document_to_needs(db_session, doc_a)
    assert need_b.status is NeedsItemStatus.PENDING  # file B's need untouched
