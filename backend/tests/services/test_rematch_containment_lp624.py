"""LP-624 — the replay that had no memory of what it had already consumed.

`rematch_needs_for_file` runs on EVERY verification, so a defect here is not a one-off: it compounds
once per run. Both guards below exist because the original claim — "a document whose need is already
satisfied finds nothing open and is a no-op" — is only true when there is no OTHER open need of the
same type, and on a real file there usually is.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.core.security import hash_password
from app.documents.catalog import get_category
from app.models import Company, User, UserRole
from app.models.document import Document, DocumentStatus
from app.models.loan_file import LoanFile
from app.models.needs_item import NeedsItem, NeedsItemStatus
from app.services.loan_files import create_loan_file
from app.services.needs_engine import (
    apply_document_to_needs,
    canonical_need_type,
    category_for_need_type,
    rematch_needs_for_file,
)
from app.services.needs_items import create_needs_item
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _loan_file(db: AsyncSession) -> LoanFile:
    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    db.add(
        User(
            company_id=company.id,
            email=f"u-{uuid4().hex[:6]}@acme.com",
            hashed_password=hash_password("x"),
            first_name="T",
            last_name="U",
            role=UserRole.PROCESSOR,
            is_active=True,
        )
    )
    await db.flush()
    return await create_loan_file(db, company_id=company.id)


async def _document(
    db: AsyncSession, loan_file: LoanFile, *, document_type: str, status: DocumentStatus
) -> Document:
    doc = Document(
        id=uuid4(),
        loan_file_id=loan_file.id,
        original_filename=f"{uuid4().hex[:6]}.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path=f"{loan_file.company_id}/{loan_file.id}/x.pdf",
        document_type=document_type,
        category=get_category(document_type),
        status=status,
        upload_source="user_upload",
    )
    db.add(doc)
    await db.flush()
    return doc


async def _need(db: AsyncSession, loan_file: LoanFile, *, needs_type: str) -> NeedsItem:
    return await create_needs_item(
        db, loan_file_id=loan_file.id, title=f"Need: {needs_type}", needs_type=needs_type
    )


async def test_one_document_cannot_satisfy_a_second_need(db_session: AsyncSession) -> None:
    """One upload walked down the whole list of same-typed needs, one per verification.

    Nothing recorded which document had already satisfied which need, so a pay stub that answered
    need A was offered to need B on the next run — and marked `satisfied_by_document_id` on both.
    """
    loan_file = await _loan_file(db_session)
    need_a = await _need(db_session, loan_file, needs_type="pay_stub")
    need_b = await _need(db_session, loan_file, needs_type="pay_stub")
    doc = await _document(
        db_session, loan_file, document_type="pay_stub", status=DocumentStatus.COMPLETED
    )

    await apply_document_to_needs(db_session, doc)
    assert need_a.status is NeedsItemStatus.RECEIVED
    assert need_b.status is NeedsItemStatus.PENDING

    await rematch_needs_for_file(db_session, loan_file.id)

    assert need_b.status is NeedsItemStatus.PENDING, (
        "the one pay stub on file satisfied a second need it was never for"
    )
    assert need_b.satisfied_by_document_id is None


async def test_a_failed_document_does_not_reject_a_new_need(db_session: AsyncSession) -> None:
    """`_MATCH_PRIORITY` prefers a non-REJECTED need, so the freshest untouched one is exactly where
    an old unreadable document landed on replay.

    The processor was told a document they never received was illegible — about a document that was
    already accounted for on the need it really arrived for.
    """
    loan_file = await _loan_file(db_session)
    need_a = await _need(db_session, loan_file, needs_type="pay_stub")
    bad = await _document(
        db_session, loan_file, document_type="pay_stub", status=DocumentStatus.NEEDS_REVIEW
    )
    await apply_document_to_needs(db_session, bad)
    assert need_a.status is NeedsItemStatus.REJECTED

    # A need seeded afterwards — a co-borrower added, or a finding's request.
    need_b = await _need(db_session, loan_file, needs_type="pay_stub")

    await rematch_needs_for_file(db_session, loan_file.id)

    assert need_b.status is NeedsItemStatus.PENDING, (
        "a stale unreadable document rejected a need it was never for"
    )


async def test_the_replay_still_picks_up_a_document_a_rule_change_made_matchable(
    db_session: AsyncSession,
) -> None:
    """The guards must not cost the case the replay exists for (bug-001's alias)."""
    loan_file = await _loan_file(db_session)
    doc = await _document(
        db_session,
        loan_file,
        document_type="mortgage_statement",
        status=DocumentStatus.COMPLETED,
    )
    assert doc is not None
    need = await _need(db_session, loan_file, needs_type="existing_mortgage_statement")

    await rematch_needs_for_file(db_session, loan_file.id)

    # RECEIVED or VERIFIED — a simple-presence need auto-verifies on arrival. What matters is that
    # the replay reached it at all, and recorded WHICH document answered it.
    assert need.status is not NeedsItemStatus.PENDING
    assert need.satisfied_by_document_id == doc.id


async def test_an_umbrella_need_type_is_reachable_and_groupable() -> None:
    """`asset_statement` is answered by any ASSETS document, but had no catalog entry.

    So it was logged as `ai_need_without_matchable_type` — "a need the matcher can never reach" —
    when it matches fine, and got `category=None`, leaving it ungroupable in the list.
    """
    assert canonical_need_type("asset_statement") == "asset_statement"
    assert category_for_need_type("asset_statement") is not None
    assert canonical_need_type("government_id") == "government_id"
    assert canonical_need_type("not_a_real_type") is None
