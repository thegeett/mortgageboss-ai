"""Implications engine (LP-67) — the first CONSUMER of findings.

Findings (LP-66) are *passive* observations: "this document asserts a $500/mo child
support obligation." The implications engine turns each into an *active*
**suggestion** for the processor: "→ consider a need to document this obligation
(payment history)." It is the bridge from findings (what documents say) to the
needs list (what the file still requires).

**The locked constraint: SURFACE + SUGGEST, do NOT ACT.** This engine produces
:class:`SuggestedNeed`\\ s the processor disposes of — it **never** mutates the
financial picture (no silent debt-adding, no DTI change), never persists anything,
never creates a needs-list item. Acting on findings is Phase 3 (human-confirmed);
disposing of suggestions is the LP-68/70 needs flow. Here we only read findings and
return suggestions — the functions are pure (``suggest_needs_for_finding``) or
read-only (``suggest_needs_for_loan_file`` does a single ``SELECT``).

**Findings-scoped, NOT file-scoped.** LP-67 maps *one finding → its implied
need(s)* — a bounded, explainable mapping. The holistic, whole-file reasoning (the
complete needs list from stated data + documents + findings + these suggestions) is
**LP-69**, which *consumes* these suggestions among everything else. LP-67 does not
duplicate that; it feeds it.

**The seam to LP-68/69.** :class:`SuggestedNeed` is a clean **intermediate**,
produced **on-demand** (a pure projection over the persisted findings — no table,
no migration, recomputed when needed). LP-68 (the needs engine) and LP-69 (the AI
needs reasoning) ingest these suggestions as ONE input source and decide how/whether
each becomes a real needs-list item. Every suggestion is **traceable**:
``SuggestedNeed -> source_finding_id -> source_document_id`` (and the ``reasoning``
text says the *why*).
"""

from uuid import UUID

import structlog
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_finding import DocumentFinding, DocumentFindingType
from app.services.document_findings import list_findings_for_loan_file

logger = structlog.get_logger(__name__)


class SuggestedNeed(BaseModel):
    """One finding-derived suggestion for the processor to consider (LP-67).

    A SURFACED suggestion, not an acted-upon need. ``need_type`` is a sensible
    provisional category (the real needs model is LP-68); ``reasoning`` is the
    human-readable *why*; ``source_finding_id`` / ``source_document_id`` make the
    chain traceable (suggestion → finding → document). Produced on-demand and
    consumed by LP-68/69 — never persisted here.
    """

    need_description: str
    need_type: str | None = None
    reasoning: str
    source_finding_id: UUID
    source_document_id: UUID


def _amount_phrase(finding: DocumentFinding) -> str:
    """A short '($1,200.00/monthly)' phrase for the reasoning, if the finding has one."""
    if finding.amount is None:
        return ""
    amount = f"${finding.amount:,.2f}"
    if finding.frequency:
        amount = f"{amount}/{finding.frequency}"
    return f" ({amount})"


# What each finding type implies — the bounded, explainable mapping. Each entry is
# (need_description, need_type, implication clause). OTHER intentionally has no
# entry (no suggestion — a sensible "none" rather than a noisy generic one).
_MAPPING: dict[DocumentFindingType, tuple[str, str, str]] = {
    DocumentFindingType.OBLIGATION: (
        "Payment history / obligation documentation",
        "obligation_documentation",
        "the file should document this recurring obligation (e.g. request payment history)",
    ),
    DocumentFindingType.INCOME_RELATED: (
        "Verification of Employment / income explanation",
        "income_verification",
        "the income it references should be verified or explained (e.g. a VOE or a letter)",
    ),
    DocumentFindingType.PROPERTY_INTEREST: (
        "Property documentation review",
        "property_documentation",
        "the property interest it references should be reviewed and documented",
    ),
    DocumentFindingType.DISCREPANCY_CANDIDATE: (
        "Review / explanation of the possible discrepancy",
        "discrepancy_review",
        "a processor should review it (Phase 3 does the cross-source check)",
    ),
}


def suggest_needs_for_finding(finding: DocumentFinding) -> list[SuggestedNeed]:
    """Given ONE finding, the need(s) it implies — SURFACE + SUGGEST, never act.

    A pure function: no DB, no mutation, no side effects. Returns zero-or-more
    :class:`SuggestedNeed`\\ s, each with explainable reasoning traceable to the
    finding (and through it, the document). An unmappable type (``other``) yields no
    suggestion (a sensible "none").
    """
    entry = _MAPPING.get(finding.finding_type)
    if entry is None:
        return []  # OTHER / unmapped — surface nothing rather than a noisy generic
    description, need_type, implication = entry
    reasoning = (
        f"Because document {finding.document_id} asserts "
        f"{finding.description}{_amount_phrase(finding)}, {implication}."
    )
    return [
        SuggestedNeed(
            need_description=description,
            need_type=need_type,
            reasoning=reasoning,
            source_finding_id=finding.id,
            source_document_id=finding.document_id,
        )
    ]


async def suggest_needs_for_loan_file(
    db: AsyncSession, *, loan_file_id: UUID
) -> list[SuggestedNeed]:
    """All finding-derived suggestions for a loan file — READY for LP-68/69 to ingest.

    READ-ONLY: reads the file's findings (LP-66, tenant-scoped — the caller resolves
    the loan file scoped to the company first) and maps each. Mutates nothing; the
    suggestions are a pure projection over the persisted findings.
    """
    findings = await list_findings_for_loan_file(db, loan_file_id=loan_file_id)
    suggestions = [s for finding in findings for s in suggest_needs_for_finding(finding)]
    logger.info(
        "implications_suggested",
        loan_file_id=str(loan_file_id),
        finding_count=len(findings),
        suggestion_count=len(suggestions),  # counts only — never the reasoning text (PII)
    )
    return suggestions
