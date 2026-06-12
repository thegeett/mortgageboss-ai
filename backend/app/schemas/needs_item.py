"""Needs-item response schema (LP-34).

A read-only public view of a loan file's needs-list items, for the overview tab.
The needs list is currently generated from a **provisional** template (LP-30,
pending domain refinement) — these items are shown as-is, not as authoritative.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.document import DocumentCategory
from app.models.needs_item import NeedsItemOrigin, NeedsItemPriority, NeedsItemStatus


class NeedsItemPublic(BaseModel):
    """One needs-list item as shown on the overview."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    category: DocumentCategory | None
    needs_type: str | None
    status: NeedsItemStatus
    priority: NeedsItemPriority
    origin: NeedsItemOrigin
    borrower_id: UUID | None
    satisfied_by_document_id: UUID | None
    created_at: datetime
