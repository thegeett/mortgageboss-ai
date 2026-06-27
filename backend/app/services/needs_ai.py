"""AI needs reasoning (LP-69) — the brain of the needs list (the differentiator).

Where LP-68 is the deterministic ENGINE (states, matching, the thin floor) and
LP-67 maps *one finding → its implied need*, this is the **holistic, file-scoped**
intelligence: it looks at the WHOLE file — the stated MISMO data + the documents
present + the findings + LP-67's suggestions — and reasons *like a loan processor*
about what the file needs, **case by case**, each proposal carrying file-specific
reasoning. This handles the bulk that can't be enumerated ("self-employed across two
businesses → two years of tax returns + a P&L"; "a gift from a relative → a gift
letter + sourcing").

**The two guardrails (non-negotiable):**

  1. **Explainability** — every proposed need carries reasoning grounded in *this*
     file's data (not boilerplate), so a proposal is auditable.
  2. **Confirmation** — proposals are ingested as ``disposition=PROPOSED`` (NOT
     authoritative); the processor confirms/adjusts/dismisses (LP-70). The AI does
     the heavy lifting; the human disposes. The AI **never** self-confirms.

**Reconciliation.** LP-69 is the *culminating* reasoner: it considers what's already
covered (the floor, LP-67's suggestions, the documents present) and proposes what's
NOT already there — it does not duplicate the floor or re-propose covered needs.

**Triggers** (both through LP-68's per-file serialization — see :mod:`app.tasks.needs`):
at MISMO file creation (reason over the stated data → the initial proposed needs —
this absorbs the deferred "smart-needs-from-MISMO") and re-proposed as documents /
findings arrive (the picture changed).

**Honesty / refine with Priya — EMPHATIC.** This builds the *mechanism* on a
**sensible starter** prompt. The reasoning QUALITY — does it propose the RIGHT needs
for a situation? — is real loan-processing domain knowledge and is **the
highest-value Priya input**; it is refined with her ("walk me through a real file:
what do you chase + why?") and sharpened by the correction signal over time. V1
proposes *reasoned, explainable, improvable* needs the processor confirms — **not
perfect out of the gate**. This is a real AI reasoning call (Sonnet, substantial
context — cost + latency + eval apply).

**PII.** The assembled context carries borrower PII; it is sent to the model but
**never logged** (metadata-only: counts).
"""

import json
from typing import Any
from uuid import UUID

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import AIClientError, complete
from app.ai.parsing import extract_json_object
from app.ai.prompt_loader import load_prompt
from app.core.config import settings
from app.models.borrower import Borrower
from app.models.document import Document
from app.models.document_finding import DocumentFinding
from app.models.helpers import only_active
from app.models.loan_file import AiNeedsStatus, LoanFile
from app.models.needs_item import NeedsItem, NeedsItemDisposition, NeedsItemOrigin
from app.models.stated_financials import (
    StatedAsset,
    StatedEmployer,
    StatedIncomeItem,
    StatedLiability,
)
from app.services.implications import suggest_needs_for_loan_file
from app.services.needs_items import create_needs_item

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "needs/needs_reasoning.txt"
# A reasoning call over a compact structured context — the proposals + reasoning are
# the output, so a moderate cap is plenty.
_MAX_TOKENS = 3072


class ProposedNeed(BaseModel):
    """One AI-proposed need (LP-69) — ``reasoning`` is FILE-SPECIFIC (guardrail 1)."""

    need_description: str
    need_type: str | None = None
    reasoning: str


# --------------------------------------------------------------------------- #
# File-context assembly (the reasoning input — PII; never logged)
# --------------------------------------------------------------------------- #


class FileContext(BaseModel):
    """The whole-file picture the AI reasons over (assembled for the call; not logged)."""

    loan_purpose: str | None = None
    loan_program: str | None = None
    income: list[dict[str, Any]] = Field(default_factory=list)
    employers: list[dict[str, Any]] = Field(default_factory=list)
    assets: list[dict[str, Any]] = Field(default_factory=list)
    liabilities: list[dict[str, Any]] = Field(default_factory=list)
    documents_present: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    already_covered: list[str] = Field(
        default_factory=list
    )  # need types/doc types not to re-propose


async def assemble_file_context(db: AsyncSession, loan_file: LoanFile) -> FileContext:
    """Assemble the AI's reasoning context for a loan file (stated data + docs + findings).

    PII is gathered here for the AI call; callers must never log the result.
    """
    income = (
        await db.scalars(
            only_active(
                select(StatedIncomeItem)
                .join(Borrower, StatedIncomeItem.borrower_id == Borrower.id)
                .where(Borrower.loan_file_id == loan_file.id),
                StatedIncomeItem,
            )
        )
    ).all()
    employers = (
        await db.scalars(
            only_active(
                select(StatedEmployer)
                .join(Borrower, StatedEmployer.borrower_id == Borrower.id)
                .where(Borrower.loan_file_id == loan_file.id),
                StatedEmployer,
            )
        )
    ).all()
    assets = (
        await db.scalars(
            only_active(
                select(StatedAsset).where(StatedAsset.loan_file_id == loan_file.id), StatedAsset
            )
        )
    ).all()
    liabilities = (
        await db.scalars(
            only_active(
                select(StatedLiability).where(StatedLiability.loan_file_id == loan_file.id),
                StatedLiability,
            )
        )
    ).all()
    documents = (
        await db.scalars(
            only_active(select(Document).where(Document.loan_file_id == loan_file.id), Document)
        )
    ).all()
    findings = (
        await db.scalars(
            only_active(
                select(DocumentFinding)
                .join(Document, DocumentFinding.document_id == Document.id)
                .where(Document.loan_file_id == loan_file.id),
                DocumentFinding,
            )
        )
    ).all()
    needs = (
        await db.scalars(
            only_active(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file.id), NeedsItem)
        )
    ).all()
    suggestions = await suggest_needs_for_loan_file(db, loan_file_id=loan_file.id)

    # "already covered": needs that exist (any state — incl. dismissed/waived, so the
    # AI doesn't re-propose what a processor already removed) + document types present.
    covered = {n.needs_type for n in needs if n.needs_type}
    covered |= {d.document_type for d in documents if d.document_type}

    return FileContext(
        loan_purpose=loan_file.loan_purpose.value if loan_file.loan_purpose else None,
        loan_program=loan_file.loan_program.value if loan_file.loan_program else None,
        income=[
            {"income_type": i.income_type, "employment_income": i.employment_income} for i in income
        ],
        employers=[
            {"employer_name": e.employer_name, "is_current": e.is_current} for e in employers
        ],
        assets=[{"asset_type": a.asset_type} for a in assets],
        liabilities=[{"liability_type": liability.liability_type} for liability in liabilities],
        documents_present=[
            {"document_type": d.document_type, "status": d.status.value} for d in documents
        ],
        findings=[
            {"finding_type": f.finding_type.value, "description": f.description} for f in findings
        ],
        suggestions=[
            {"need_type": s.need_type, "need_description": s.need_description} for s in suggestions
        ],
        already_covered=sorted(c for c in covered if c),
    )


# --------------------------------------------------------------------------- #
# The AI reasoning (Sonnet) — propose-with-reasoning
# --------------------------------------------------------------------------- #


def _parse_proposals(text: str) -> list[ProposedNeed]:
    """Parse the model's ``{"needs": [...]}`` into proposals. Never raises ([] on junk).

    Drops entries missing a description or reasoning — guardrail 1 (no boilerplate /
    empty reasoning is admitted as a real proposal).
    """
    snippet = extract_json_object(text)
    if snippet is None:
        return []
    try:
        payload: Any = json.loads(snippet)
    except (json.JSONDecodeError, ValueError):
        return []
    rows = payload.get("needs") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    proposals: list[ProposedNeed] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        desc = row.get("need_description")
        reasoning = row.get("reasoning")
        if not isinstance(desc, str) or not desc.strip():
            continue
        if not isinstance(reasoning, str) or not reasoning.strip():
            continue  # GUARDRAIL 1: a need without file-specific reasoning is rejected
        nt = row.get("need_type")
        proposals.append(
            ProposedNeed(
                need_description=desc.strip(),
                need_type=nt.strip() if isinstance(nt, str) and nt.strip() else None,
                reasoning=reasoning.strip(),
            )
        )
    return proposals


def reconcile(proposals: list[ProposedNeed], *, already_covered: set[str]) -> list[ProposedNeed]:
    """Drop proposals already covered (the floor / LP-67 / documents present) + de-dupe.

    The reconciliation safety net behind the prompt (which is also told what's
    covered): LP-69 proposes what's NOT already there — no duplication of the floor.
    """
    out: list[ProposedNeed] = []
    seen_types: set[str] = set()
    seen_descs: set[str] = set()
    for p in proposals:
        if p.need_type and p.need_type in already_covered:
            continue  # covered by the floor / LP-67 / a present document
        if p.need_type and p.need_type in seen_types:
            continue
        key = p.need_description.strip().lower()
        if key in seen_descs:
            continue
        out.append(p)
        if p.need_type:
            seen_types.add(p.need_type)
        seen_descs.add(key)
    return out


async def propose_needs(db: AsyncSession, loan_file: LoanFile) -> list[ProposedNeed]:
    """Reason over the whole file → proposed needs with reasoning. Never raises ([] on failure).

    Assembles the context, calls the Sonnet reasoner, parses defensively, and
    reconciles against what's already covered. The assembled context (PII) and the
    raw response are never logged — only counts.
    """
    context = await assemble_file_context(db, loan_file)
    system_prompt = load_prompt(_PROMPT_PATH)
    user_content = (
        "Here is the loan file's context as JSON. Reason about what it still needs.\n\n"
        + context.model_dump_json()
    )
    try:
        result = await complete(
            model=settings.anthropic_model_extraction,  # Sonnet — real reasoning over context
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
            max_tokens=_MAX_TOKENS,
        )
    except AIClientError:
        # Don't fail silently (LP-71.5): record FAILED so a floor-only list after an AI
        # failure is distinguishable from a complete one. Never raises / blocks — the
        # floor is independent; the AI is additive.
        logger.warning("needs_reasoning_ai_failed", loan_file_id=str(loan_file.id))
        loan_file.ai_needs_status = AiNeedsStatus.FAILED
        await db.flush()
        return []

    proposals = _parse_proposals(result.text)
    reconciled = reconcile(proposals, already_covered=set(context.already_covered))
    logger.info(
        "needs_reasoning_done",
        loan_file_id=str(loan_file.id),
        proposed=len(proposals),
        after_reconcile=len(reconciled),  # counts only — never the reasoning text (PII-adjacent)
    )
    return reconciled


# --------------------------------------------------------------------------- #
# Ingestion into LP-68's engine (source=ai_reasoning, disposition=proposed)
# --------------------------------------------------------------------------- #


async def apply_ai_needs(db: AsyncSession, loan_file: LoanFile) -> list[NeedsItem]:
    """Propose + ingest AI-reasoned needs into LP-68's engine. Idempotent-ish.

    Each proposal becomes a ``NeedsItem`` with ``origin=AI_REASONING``,
    ``disposition=PROPOSED`` (GUARDRAIL 2 — never self-confirmed), and the
    file-specific reasoning. Skips a proposal whose type/description already exists on
    the file (so re-reasoning on document arrivals doesn't pile up duplicates). Runs
    inside LP-68's per-file lock (the caller in :mod:`app.tasks.needs` holds it).
    """
    proposals = await propose_needs(db, loan_file)
    existing = (
        await db.scalars(
            only_active(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file.id), NeedsItem)
        )
    ).all()
    existing_types = {n.needs_type for n in existing if n.needs_type}
    existing_descs = {n.title.strip().lower() for n in existing}

    created: list[NeedsItem] = []
    for p in proposals:
        if p.need_type and p.need_type in existing_types:
            continue
        if p.need_description.strip().lower() in existing_descs:
            continue
        need = await create_needs_item(
            db,
            loan_file_id=loan_file.id,
            title=p.need_description,
            needs_type=p.need_type,
            origin=NeedsItemOrigin.AI_REASONING,
            disposition=NeedsItemDisposition.PROPOSED,  # the processor confirms (LP-70)
            reasoning=p.reasoning,
        )
        created.append(need)
        if p.need_type:
            existing_types.add(p.need_type)
        existing_descs.add(p.need_description.strip().lower())
    if created:
        logger.info("ai_needs_ingested", loan_file_id=str(loan_file.id), count=len(created))
    return created


async def _load_loan_file(db: AsyncSession, loan_file_id: UUID) -> LoanFile | None:
    loan_file: LoanFile | None = await db.scalar(
        only_active(select(LoanFile).where(LoanFile.id == loan_file_id), LoanFile)
    )
    return loan_file


async def apply_ai_needs_for_file_id(db: AsyncSession, loan_file_id: UUID) -> list[NeedsItem]:
    """Load the file (active) and run :func:`apply_ai_needs` — the task entrypoint.

    Settles the AI-needs status (LP-71.5): the run flips ``PENDING`` → ``COMPLETED``,
    unless the reasoning marked it ``FAILED`` (a swallowed ``AIClientError``), which is
    left intact so the failure stays visible. Informational only — never blocks.
    """
    loan_file = await _load_loan_file(db, loan_file_id)
    if loan_file is None:
        return []
    created = await apply_ai_needs(db, loan_file)
    if loan_file.ai_needs_status is not AiNeedsStatus.FAILED:
        loan_file.ai_needs_status = AiNeedsStatus.COMPLETED
        await db.flush()
    return created
