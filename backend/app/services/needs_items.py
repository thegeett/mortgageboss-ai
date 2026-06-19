"""Needs item service — creation and lifecycle transitions (LP-19).

Lifecycle moves (request, satisfy) touch a status plus a timestamp, so they are
done through these helpers rather than mutating fields directly — that keeps the
status and its trail consistent. Communication (actually sending a request) and
auto-matching a document to a need are later phases; these helpers just record
the state.
"""

from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.document import DocumentCategory
from app.models.helpers import only_active
from app.models.needs_item import (
    NeedsItem,
    NeedsItemDisposition,
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
    disposition: NeedsItemDisposition = NeedsItemDisposition.PROPOSED,
    reasoning: str | None = None,
    source_finding_id: UUID | None = None,
) -> NeedsItem:
    """Create a ``PENDING`` needs item on a loan file (LP-68).

    ``origin`` is the source-agnostic provenance (floor / suggestion / ai_reasoning /
    manual); ``disposition`` is the human-confirmation lifecycle (default PROPOSED;
    the floor passes CONFIRMED); ``reasoning`` + ``source_finding_id`` carry the
    explainability for a suggestion-derived need. Uses ``flush`` so the caller
    controls the transaction.
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
        status=NeedsItemStatus.PENDING,
        disposition=disposition,
        reasoning=reasoning,
        source_finding_id=source_finding_id,
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


# Priority order for display: blocking items first, then standard, then low.
_PRIORITY_ORDER = case(
    (NeedsItem.priority == NeedsItemPriority.BLOCKING, 0),
    (NeedsItem.priority == NeedsItemPriority.STANDARD, 1),
    (NeedsItem.priority == NeedsItemPriority.LOW, 2),
    else_=3,
)


async def list_needs_items(db: AsyncSession, *, loan_file_id: UUID) -> list[NeedsItem]:
    """The file's active needs items (LP-34), ordered blocking-first then oldest.

    Takes an already scope-checked ``loan_file_id`` (the endpoint resolves the
    parent file with the caller's company first). Excludes soft-deleted rows.
    """
    stmt = select(NeedsItem).where(NeedsItem.loan_file_id == loan_file_id)
    stmt = only_active(stmt, NeedsItem)
    stmt = stmt.order_by(_PRIORITY_ORDER, NeedsItem.created_at)
    result = await db.execute(stmt)
    return list(result.scalars().all())
