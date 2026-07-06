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
from typing import Literal
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


# How much to trust a need's source (LP-110) — the HONEST-ATTRIBUTION discipline: a deterministic
# rule (certain) must read differently from the AI's reading (verify). Same discipline as findings.
NeedSourceAttribution = Literal["deterministic", "ai_identified", "finding", "manual"]


class NeedSourceFact(BaseModel):
    """One fact that TRIGGERED a need (LP-110) — grounds the reasoning to verifiable data.

    ``label`` is the human-readable fact ("Employment income is stated", "Gift from a relative");
    ``ref`` / ``document_id`` link to the underlying record (a finding, its document) where one
    exists, so the processor can click through and confirm the AI didn't misread.
    """

    kind: str  # employer / income / asset / liability / finding / mismo_field / rule / borrower
    label: str
    ref: str | None = None  # reference to the underlying record (e.g. a finding id)
    document_id: UUID | None = None  # a linkable source document (e.g. the finding's document)
    document_filename: str | None = None


class NeedSource(BaseModel):
    """The SOURCE of a need (LP-110) — the specific data that triggered it, HONESTLY ATTRIBUTED.

    ``attribution`` says how much to trust it: ``deterministic`` (a floor rule fired on stated data
    — certain), ``ai_identified`` (the AI cited these facts — verify), ``finding`` (triggered by a
    finding on a document — linked), ``manual`` (processor-authored). This makes a need's reasoning
    FALSIFIABLE: the processor can verify the triggering data, not just trust the argument.
    """

    attribution: NeedSourceAttribution
    facts: list[NeedSourceFact] = Field(default_factory=list)


def _facts_from_stored(item: NeedsItem) -> list[NeedSourceFact]:
    """The need's stored ``source_facts`` (floor-derived or AI-cited) as typed facts (LP-110)."""
    facts: list[NeedSourceFact] = []
    for raw in item.source_facts or []:
        label = raw.get("label")
        if not isinstance(label, str) or not label.strip():
            continue
        ref = raw.get("ref")
        facts.append(
            NeedSourceFact(
                kind=str(raw.get("kind") or "").strip() or "fact",
                label=label.strip(),
                ref=ref if isinstance(ref, str) and ref.strip() else None,
            )
        )
    return facts


def build_need_source(item: NeedsItem) -> NeedSource | None:
    """Assemble a need's source per origin (LP-110), or ``None`` when none is captured.

    FLOOR → deterministic (the rule's derived fact[s]); AI_REASONING → ai_identified (the model's
    cited FileContext facts); SUGGESTION → the finding chain (its description + source document,
    linked); MANUAL / other origins → ``None`` (the origin tag already says "Added"). Expects
    ``source_finding`` (+ its document) eager-loaded for a suggestion need.
    """
    origin = item.origin
    if origin is NeedsItemOrigin.FLOOR:
        facts = _facts_from_stored(item)
        return NeedSource(attribution="deterministic", facts=facts) if facts else None
    if origin is NeedsItemOrigin.AI_REASONING:
        facts = _facts_from_stored(item)
        return NeedSource(attribution="ai_identified", facts=facts) if facts else None
    if origin is NeedsItemOrigin.SUGGESTION:
        finding = item.source_finding
        if finding is not None:
            doc = finding.document
            return NeedSource(
                attribution="finding",
                facts=[
                    NeedSourceFact(
                        kind="finding",
                        label=finding.description,
                        ref=str(finding.id),
                        document_id=doc.id if doc is not None else None,
                        document_filename=doc.original_filename if doc is not None else None,
                    )
                ],
            )
        facts = _facts_from_stored(item)
        return NeedSource(attribution="finding", facts=facts) if facts else None
    return None


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
    # LP-110: the SOURCE — the specific data that TRIGGERED the need, honestly attributed by origin
    # (deterministic rule / AI-identified / finding), so the reasoning is FALSIFIABLE. None when the
    # origin carries no structured source (e.g. a processor-added manual need).
    source: NeedSource | None = None
    # LP-111: set when the AI FLAGGED this proposed need as a POSSIBLE duplicate of another (by id) —
    # a "possible duplicate of …" indicator the processor confirms (merge) or dismisses (keep both).
    # Never a silent merge; the deterministic-certain duplicates were already merged before this.
    possible_duplicate_of: UUID | None = None

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
            source=build_need_source(item),
            possible_duplicate_of=item.duplicate_of_id,
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
