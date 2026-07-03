"""Needs-item schemas (LP-34 read; LP-70 disposition writes).

The read schema (:class:`NeedsItemPublic`) is the dashboard's view of one need —
its arrival state, its human-confirmation disposition, the explainability "why"
(the LP-67/69 reasoning), and the satisfying document. The write schemas drive the
LP-70 disposition flow: **the AI proposes, the processor disposes** (the
human-in-the-loop guardrail) — confirm / adjust / dismiss / waive / add.

No raw PII: the response carries the need's own fields (titles / types / reasoning /
the satisfying document's filename), never borrower SSNs or document contents.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import Document, DocumentCategory
from app.models.needs_item import (
    NeedsItem,
    NeedsItemDisposition,
    NeedsItemOrigin,
    NeedsItemPriority,
    NeedsItemStatus,
)


class MatchedDocument(BaseModel):
    """One document matching a need (LP-109) — its id (for a link) + its display filename."""

    id: UUID
    filename: str


class NeedsItemPublic(BaseModel):
    """One needs-list item as shown on the dashboard (LP-70)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    category: DocumentCategory | None
    needs_type: str | None
    status: NeedsItemStatus
    priority: NeedsItemPriority
    origin: NeedsItemOrigin  # the source-agnostic provenance (floor/suggestion/ai_reasoning/…)
    disposition: NeedsItemDisposition  # the human-confirmation lifecycle (LP-68 → LP-69/70)
    reasoning: str | None  # the "why" (LP-67/69) — explainability made visible
    reason: str | None  # why a need was rejected (a doc failed) or waived
    borrower_id: UUID | None
    satisfied_by_document_id: UUID | None
    satisfied_by_document_filename: str | None  # the doc that fulfilled it, for display
    satisfied_at: datetime | None
    created_at: datetime
    # HONEST SATISFACTION (LP-108): True when the need is GRADED — a matched document is "attached,
    # confirm coverage" (RECEIVED), NOT auto-verified, because one document can't prove the full
    # requirement (all accounts / months / years). Drives the "confirm coverage" affordance.
    requires_coverage_confirmation: bool = False
    # LP-109 (derive-on-read): ALL completed documents matching the need's criteria (not just the
    # single stored trigger), so the processor sees the full evidence set to confirm coverage
    # against. Computed at read time; intentionally coarse for umbrella needs (see documents_matching_need).
    matching_documents: list[MatchedDocument] = Field(default_factory=list)

    @classmethod
    def from_model(
        cls, item: NeedsItem, *, matching_documents: list[Document] | None = None
    ) -> "NeedsItemPublic":
        """Build the public view. Expects ``satisfied_by_document`` eager-loaded.

        ``matching_documents`` (LP-109) is the derive-on-read full set of matching documents,
        supplied by the caller (which loads the file's documents once); ``None`` → empty.
        """
        from app.services.needs_engine import needs_coverage_confirmation

        doc = item.satisfied_by_document
        matches = [
            MatchedDocument(id=d.id, filename=d.original_filename)
            for d in (matching_documents or [])
        ]
        return cls(
            id=item.id,
            title=item.title,
            description=item.description,
            category=item.category,
            needs_type=item.needs_type,
            status=item.status,
            priority=item.priority,
            origin=item.origin,
            disposition=item.disposition,
            reasoning=item.reasoning,
            reason=item.reason,
            borrower_id=item.borrower_id,
            satisfied_by_document_id=item.satisfied_by_document_id,
            satisfied_by_document_filename=doc.original_filename if doc else None,
            satisfied_at=item.satisfied_at,
            created_at=item.created_at,
            requires_coverage_confirmation=needs_coverage_confirmation(item),
            matching_documents=matches,
        )


# --------------------------------------------------------------------------- #
# Write (disposition) request bodies — the LP-70 processor-disposes flow
# --------------------------------------------------------------------------- #


class NeedsItemAdjust(BaseModel):
    """Edit a need's content (LP-70 adjust) — a correction signal. All optional."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    needs_type: str | None = Field(default=None, max_length=64)
    priority: NeedsItemPriority | None = None


class NeedsItemReason(BaseModel):
    """A reason for dismissing or waiving a need (why it doesn't apply / isn't required)."""

    reason: str | None = Field(default=None, max_length=2000)


class NeedsItemCreate(BaseModel):
    """Add a need the AI missed (LP-70) — processor-authored, so a real (confirmed) need."""

    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    needs_type: str | None = Field(default=None, max_length=64)
    category: DocumentCategory | None = None
    priority: NeedsItemPriority = NeedsItemPriority.STANDARD
    borrower_id: UUID | None = None
