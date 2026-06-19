"""Tests for the needs item service (LP-19).

Covers the create/request/satisfy lifecycle helpers (status + timestamps) and the
SET NULL behaviour: hard-deleting the satisfying document nulls
``satisfied_by_document_id`` and preserves the durable needs item (ADR-069).

Uses the transaction-rollback ``db_session`` fixture from LP-10.
"""

from app.models import (
    Company,
    Document,
    DocumentCategory,
    LoanFile,
    NeedsItem,
    NeedsItemOrigin,
    NeedsItemPriority,
    NeedsItemStatus,
    UploadSource,
)
from app.services.loan_files import create_loan_file
from app.services.needs_items import (
    create_needs_item,
    request_needs_item,
    satisfy_needs_item,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_loan_file(db_session: AsyncSession, slug: str) -> LoanFile:
    company = Company(name=slug.title(), slug=slug)
    db_session.add(company)
    await db_session.flush()
    return await create_loan_file(db_session, company_id=company.id)


async def _make_document(db_session: AsyncSession, loan_file: LoanFile) -> Document:
    document = Document(
        loan_file_id=loan_file.id,
        original_filename="w2.pdf",
        mime_type="application/pdf",
        file_size_bytes=1024,
        storage_path="acme/lf/w2.pdf",
        upload_source=UploadSource.USER_UPLOAD,
    )
    db_session.add(document)
    await db_session.flush()
    return document


async def test_create_needs_item_is_outstanding(db_session: AsyncSession) -> None:
    """create_needs_item makes a PENDING item with the given fields."""
    loan_file = await _make_loan_file(db_session, "acme")

    item = await create_needs_item(
        db_session,
        loan_file_id=loan_file.id,
        title="2023 W-2",
        category=DocumentCategory.INCOME_EMPLOYMENT,
        needs_type="w2",
        priority=NeedsItemPriority.BLOCKING,
        description="Need the 2023 W-2.",
    )

    assert item.status is NeedsItemStatus.PENDING
    assert item.origin is NeedsItemOrigin.MANUAL
    assert item.title == "2023 W-2"
    assert item.category is DocumentCategory.INCOME_EMPLOYMENT
    assert item.needs_type == "w2"
    assert item.priority is NeedsItemPriority.BLOCKING


async def test_request_needs_item_sets_requested(db_session: AsyncSession) -> None:
    """request_needs_item sets REQUESTED and a timezone-aware requested_at."""
    loan_file = await _make_loan_file(db_session, "acme")
    item = await create_needs_item(db_session, loan_file_id=loan_file.id, title="W-2")

    requested = await request_needs_item(db_session, needs_item=item)

    assert requested.status is NeedsItemStatus.REQUESTED
    assert requested.requested_at is not None
    assert requested.requested_at.tzinfo is not None
    assert requested.requested_at.utcoffset() is not None


async def test_satisfy_needs_item_links_document(db_session: AsyncSession) -> None:
    """satisfy_needs_item sets RECEIVED, links the document, stamps satisfied_at."""
    loan_file = await _make_loan_file(db_session, "acme")
    document = await _make_document(db_session, loan_file)
    item = await create_needs_item(db_session, loan_file_id=loan_file.id, title="W-2")

    satisfied = await satisfy_needs_item(db_session, needs_item=item, document_id=document.id)

    assert satisfied.status is NeedsItemStatus.RECEIVED
    assert satisfied.satisfied_by_document_id == document.id
    assert satisfied.satisfied_at is not None
    assert satisfied.satisfied_at.tzinfo is not None


async def test_deleting_satisfying_document_nulls_link_and_keeps_item(
    db_session: AsyncSession,
) -> None:
    """SET NULL: hard-deleting the satisfying document nulls the link, keeps the item.

    The needs item is durable workflow state owned by the loan file (ADR-069), so
    removing the document it pointed at must not delete it — only null the link.
    """
    loan_file = await _make_loan_file(db_session, "acme")
    document = await _make_document(db_session, loan_file)
    item = await create_needs_item(db_session, loan_file_id=loan_file.id, title="W-2")
    await satisfy_needs_item(db_session, needs_item=item, document_id=document.id)
    item_id = item.id

    # Hard-delete the satisfying document.
    await db_session.delete(document)
    await db_session.flush()
    db_session.expire_all()

    surviving = await db_session.scalar(select(NeedsItem).where(NeedsItem.id == item_id))
    assert surviving is not None  # the item still exists
    assert surviving.satisfied_by_document_id is None  # link nulled
    # Status is unchanged in V1 (re-opening is a later-phase concern).
    assert surviving.status is NeedsItemStatus.RECEIVED
