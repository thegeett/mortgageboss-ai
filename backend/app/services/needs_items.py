"""Needs item service — creation and lifecycle transitions (LP-19).

Lifecycle moves (request, satisfy) touch a status plus a timestamp, so they are
done through these helpers rather than mutating fields directly — that keeps the
status and its trail consistent. Communication (actually sending a request) and
auto-matching a document to a need are later phases; these helpers just record
the state.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.document import DocumentCategory
from app.models.needs_item import (
    NeedsItem,
    NeedsItemOrigin,
    NeedsItemPriority,
    NeedsItemStatus,
)


async def create_needs_item(
    db: AsyncSession,
    *,
    loan_file_id: UUID,
    title: str,
    category: DocumentCategory | None = None,
    needs_type: str | None = None,
    borrower_id: UUID | None = None,
    origin: NeedsItemOrigin = NeedsItemOrigin.MANUAL,
    priority: NeedsItemPriority = NeedsItemPriority.STANDARD,
    description: str | None = None,
) -> NeedsItem:
    """Create an ``OUTSTANDING`` needs item on a loan file.

    Uses ``flush`` rather than ``commit`` so the caller controls the transaction.
    """
    item = NeedsItem(
        loan_file_id=loan_file_id,
        title=title,
        category=category,
        needs_type=needs_type,
        borrower_id=borrower_id,
        origin=origin,
        priority=priority,
        description=description,
        status=NeedsItemStatus.OUTSTANDING,
    )
    db.add(item)
    await db.flush()
    return item


async def request_needs_item(db: AsyncSession, *, needs_item: NeedsItem) -> NeedsItem:
    """Mark a needs item as ``REQUESTED`` and stamp ``requested_at``.

    Records that the item was asked of the borrower; actually sending the request
    (email/SMS) is Phase 4. Uses ``flush``.
    """
    needs_item.status = NeedsItemStatus.REQUESTED
    needs_item.requested_at = utcnow()
    await db.flush()
    return needs_item


async def satisfy_needs_item(
    db: AsyncSession, *, needs_item: NeedsItem, document_id: UUID
) -> NeedsItem:
    """Mark a needs item as ``RECEIVED``, satisfied by a document.

    Links ``satisfied_by_document_id`` and stamps ``satisfied_at``. Uses ``flush``.
    """
    needs_item.status = NeedsItemStatus.RECEIVED
    needs_item.satisfied_by_document_id = document_id
    needs_item.satisfied_at = utcnow()
    await db.flush()
    return needs_item
