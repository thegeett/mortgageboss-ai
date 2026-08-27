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
perfect out of the gate**. This is a real AI reasoning call (Opus, substantial
context — cost + latency + eval apply).

**PII.** The assembled context carries borrower PII; it is sent to the model but
**never logged** (metadata-only: counts).
"""

import json
from collections.abc import Sequence
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
from app.models.needs_item import (
    NeedsItem,
    NeedsItemDisposition,
    NeedsItemOrigin,
    NeedsItemStatus,
)
from app.models.stated_financials import (
    StatedAsset,
    StatedEmployer,
    StatedIncomeItem,
    StatedLiability,
)
from app.services.implications import suggest_needs_for_loan_file
from app.services.needs_coverage import apply_retraction
from app.services.needs_engine import canonical_need_type, category_for_need_type
from app.services.needs_items import create_needs_item

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "needs/needs_reasoning.txt"
# A reasoning call over a compact structured context — the proposals + reasoning are
# the output, so a moderate cap is plenty.
_MAX_TOKENS = 3072


# The fact kinds the AI may cite as a need's SOURCE (LP-110) — each maps to a real context record
# the model was shown, so the citation grounds to verifiable data (not more AI prose).
_TRIGGERED_BY_KINDS = frozenset(
    {"employer", "income", "asset", "liability", "finding", "mismo_field"}
)


class TriggeredByFact(BaseModel):
    """One fact the AI CITES as having triggered a need (LP-110) — its SOURCE, grounded.

    ``kind`` names which context record it came from (employer/income/asset/liability/finding/
    mismo_field); ``label`` is the specific fact ("self-employment income from Chhotala Realty LLC");
    ``ref`` links the underlying record where one exists (a finding id) so the processor can verify.
    """

    kind: str
    label: str
    ref: str | None = None


class ProposedNeed(BaseModel):
    """One AI-proposed need (LP-69) — ``reasoning`` is FILE-SPECIFIC (guardrail 1).

    ``triggered_by`` (LP-110) is the SOURCE: the specific FileContext fact(s) the model reasoned
    over, so its reasoning is FALSIFIABLE (the processor verifies the AI didn't misread). It may be
    empty (older/degraded responses) — a need is never dropped for lacking a source.
    """

    need_description: str
    need_type: str | None = None
    reasoning: str
    triggered_by: list[TriggeredByFact] = Field(default_factory=list)


class RetractedNeed(BaseModel):
    """LP-633 — a need the model now judges the file no longer needs.

    Keyed on the need's ``id``, not its type. The ticket first specified type, on the reasoning that
    ids are opaque to the model — but LP-110 already hands it finding ids and it refs them correctly,
    and keying on type would have excluded exactly the population this exists for: the six untyped
    needs on staging, the largest single bucket, and the only ones no document can EVER clear.

    ``document_id`` is optional. A retraction may rest on a document ("the credit report lists it") or
    on an argument ("the employment record states self_employed: false"); ``why`` is what makes it
    checkable either way, so that one is required.
    """

    need_id: str
    why: str
    document_id: str | None = None


class ReasonedNeeds(BaseModel):
    """One reasoning pass: what the model proposes, and what it withdraws (LP-633).

    Two keys because silence cannot carry the second one. The prompt ORDERS the model to stay quiet
    about anything in ``already_covered``, so an omitted need means "I was told not to restate it" —
    indistinguishable from "it is no longer needed". Reading omission as withdrawal would delete every
    correct need on every re-run.
    """

    proposals: list[ProposedNeed] = Field(default_factory=list)
    retractions: list[RetractedNeed] = Field(default_factory=list)
    # What the model proposed BEFORE reconciliation. Needed because `reconcile` drops a proposal whose
    # type is already covered — which is precisely the shape of a self-contradiction ("propose
    # tax_return" beside "retract the tax_return need"), so by the time `proposals` is built the signal
    # that the model still wants the ask has already been discarded.
    raw_proposals: list[ProposedNeed] = Field(default_factory=list)


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
    # LP-111: the needs ALREADY on the list (title + type), so the model doesn't RESTATE/REWORD an
    # existing free-form need each run — the accumulation that spawned duplicate LOEs. Reconciliation
    # at generation, complementing the deterministic dedup after.
    existing_needs: list[dict[str, Any]] = Field(default_factory=list)


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
        # LP-624 — THE WHOLE EMPLOYMENT RECORD. The model saw a name and a null `is_current` and had to
        # infer the rest, so on LF-ABRS it proposed two years of personal tax returns because
        # "contract-basis income must be qualified from tax history" — on a file whose application says
        # `SelfEmployedIndicator = false` three times — and described one current plus two previous jobs
        # as "three employers", which reads as three concurrent ones. Both inferences were reasonable
        # from what it was given, and both are answered outright by fields the import now carries.
        employers=[
            {
                "employer_name": e.employer_name,
                "is_current": e.is_current,
                "self_employed": e.self_employed,
                "classification": e.classification,
                "position": e.position,
                "start_date": e.start_date.isoformat() if e.start_date else None,
                "end_date": e.end_date.isoformat() if e.end_date else None,
                "monthly_income": str(e.monthly_income) if e.monthly_income is not None else None,
                "special_relationship": e.special_relationship,
            }
            for e in employers
        ],
        assets=[{"asset_type": a.asset_type} for a in assets],
        liabilities=[{"liability_type": liability.liability_type} for liability in liabilities],
        documents_present=[
            # LP-633: the id, so a retraction can CITE the document that answers the need and the
            # processor sees "checked against credit-report.pdf" rather than an unsourced assertion.
            {"id": str(d.id), "document_type": d.document_type, "status": d.status.value}
            for d in documents
        ],
        findings=[
            # LP-110: carry the finding id so the AI can REF a finding it cites as a need's source
            # (a linkable, verifiable record), not just restate the finding's text.
            {"id": str(f.id), "finding_type": f.finding_type.value, "description": f.description}
            for f in findings
        ],
        suggestions=[
            {"need_type": s.need_type, "need_description": s.need_description} for s in suggestions
        ],
        already_covered=sorted(c for c in covered if c),
        # LP-111: the needs already on the list, so the model doesn't reword them into duplicates.
        # LP-633 widens this from {needs_type, title}: a model cannot sensibly judge whether to
        # WITHDRAW a claim it cannot read, so it also gets the id (what a retraction names), the
        # reasoning (the argument it would be overturning), and origin/disposition (whose row it is —
        # a processor-confirmed need is not the model's to revisit, and it should not try).
        existing_needs=[
            {
                "id": str(n.id),
                "needs_type": n.needs_type,
                "title": n.title,
                "reasoning": (n.reasoning or "")[:400],
                "origin": n.origin.value,
                "disposition": n.disposition.value,
            }
            for n in needs
        ],
    )


# --------------------------------------------------------------------------- #
# The AI reasoning (Opus) — propose-with-reasoning
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
                triggered_by=_parse_triggered_by(row.get("triggered_by")),
            )
        )
    return proposals


def _parse_retractions(text: str) -> list[RetractedNeed]:
    """Parse the model's ``{"retract": [...]}`` into withdrawals. Never raises ([] on junk).

    Absence of the key is the overwhelmingly common case and means nothing was withdrawn — which is
    also what a model that ignores the instruction produces, so the failure mode of this whole
    feature is "behaves exactly as it did before LP-633".

    A retraction without a ``why`` is dropped, the mirror of guardrail 1 on the proposal side: an
    unexplained withdrawal cannot be checked, and this flag exists to be checked.
    """
    snippet = extract_json_object(text)
    if snippet is None:
        return []
    try:
        payload: Any = json.loads(snippet)
    except (json.JSONDecodeError, ValueError):
        return []
    rows = payload.get("retract") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    retractions: list[RetractedNeed] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        need_id = row.get("need_id")
        why = row.get("why")
        if not isinstance(need_id, str) or not need_id.strip():
            continue
        if not isinstance(why, str) or not why.strip():
            continue
        document_id = row.get("document_id")
        retractions.append(
            RetractedNeed(
                need_id=need_id.strip(),
                why=why.strip(),
                document_id=(
                    document_id.strip()
                    if isinstance(document_id, str) and document_id.strip()
                    else None
                ),
            )
        )
    return retractions


def _parse_triggered_by(raw: Any) -> list[TriggeredByFact]:
    """Parse a proposal's ``triggered_by`` (LP-110) defensively. Never raises ([] on junk).

    Keeps only facts with a known ``kind`` and a non-empty ``label`` — a garbled or hallucinated
    source shape is dropped, not admitted. A missing source is fine (the need still proposes); the
    absence just means no verifiable citation to click through.
    """
    if not isinstance(raw, list):
        return []
    facts: list[TriggeredByFact] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        label = entry.get("label")
        if not isinstance(kind, str) or kind.strip() not in _TRIGGERED_BY_KINDS:
            continue
        if not isinstance(label, str) or not label.strip():
            continue
        ref = entry.get("ref")
        facts.append(
            TriggeredByFact(
                kind=kind.strip(),
                label=label.strip(),
                ref=ref.strip() if isinstance(ref, str) and ref.strip() else None,
            )
        )
    return facts


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


async def propose_needs(db: AsyncSession, loan_file: LoanFile) -> ReasonedNeeds:
    """Reason over the whole file → what it still needs, and what it no longer does. Never raises.

    Assembles the context, calls the reasoner, parses defensively, and reconciles the PROPOSALS
    against what's already covered. Retractions (LP-633) are not reconciled — ``already_covered``
    exists to stop the model re-proposing, and a withdrawal is the opposite move. The assembled
    context (PII) and the raw response are never logged — only counts.
    """
    context = await assemble_file_context(db, loan_file)
    system_prompt = load_prompt(_PROMPT_PATH)
    user_content = (
        "Here is the loan file's context as JSON. Reason about what it still needs.\n\n"
        + context.model_dump_json()
    )
    try:
        result = await complete(
            model=settings.anthropic_model_reasoning,  # reasoning tier (Sonnet by default) — real reasoning over context
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
        return ReasonedNeeds()

    proposals = _parse_proposals(result.text)
    reconciled = reconcile(proposals, already_covered=set(context.already_covered))
    retractions = _parse_retractions(result.text)
    logger.info(
        "needs_reasoning_done",
        loan_file_id=str(loan_file.id),
        proposed=len(proposals),
        after_reconcile=len(reconciled),  # counts only — never the reasoning text (PII-adjacent)
        retracted=len(retractions),
    )
    return ReasonedNeeds(proposals=reconciled, retractions=retractions, raw_proposals=proposals)


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
    reasoned = await propose_needs(db, loan_file)
    proposals = reasoned.proposals
    existing = (
        await db.scalars(
            only_active(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file.id), NeedsItem)
        )
    ).all()
    # The RAW proposals, not the reconciled ones — see `ReasonedNeeds.raw_proposals`.
    await _apply_retractions(db, loan_file, reasoned.retractions, existing, reasoned.raw_proposals)
    existing_types = {n.needs_type for n in existing if n.needs_type}
    existing_descs = {n.title.strip().lower() for n in existing}

    created: list[NeedsItem] = []
    for p in proposals:
        if p.need_type and p.need_type in existing_types:
            # LP-625 — REFRESH THE REASONING RATHER THAN DISCARD IT. Skipping outright froze the
            # first explanation forever: LF-ABRS kept "two years of personal tax returns, because
            # contract-basis income must be qualified from tax history" — written when the model could
            # not see `self_employed: false` — long after the import started carrying it. The need is
            # right; the sentence beside it was not.
            #
            # Only where the processor has NOT acted: an untouched PROPOSED need is still the model's
            # to describe, and one they confirmed, dismissed or adjusted is theirs.
            # THROUGH `_unmatchable_note`, NOT RAW. The create path appends "No document type matches
            # this request, so uploading a file cannot clear it — close it by hand…" to a proposal with
            # no catalog type; assigning `p.reasoning` here stripped it back off on the very next run,
            # permanently. The mechanism is a loop: `existing_types` holds the RAW type (the create path
            # stores `needs_type or p.need_type`), so `_refreshable` matches it, and the appended note
            # is precisely what makes `stale.reasoning != p.reasoning` true — so the refresh fires every
            # time and every time removes it. That restores exactly the LF-ABRS state LP-625 fixed.
            refreshed = _unmatchable_note(
                p.reasoning, matchable=canonical_need_type(p.need_type) is not None
            )
            stale = _refreshable(existing, p.need_type)
            if stale is not None and stale.reasoning != refreshed:
                stale.reasoning = refreshed
                stale.source_facts = [f.model_dump() for f in p.triggered_by] or None
                logger.info(
                    "ai_need_reasoning_refreshed",
                    loan_file_id=str(loan_file.id),
                    needs_type=p.need_type,  # a document type, not PII
                )
            continue
        if p.need_description.strip().lower() in existing_descs:
            continue
        # LP-623 — a need the matcher can never reach, and a need with no place in the list.
        #
        # TYPE: satisfaction-matching keys on `needs_type`, so a proposal with none can never be
        # advanced by ANY upload — LF-ABRS carried two ("documentation for the 'Other' liability",
        # "for the unspecified asset") that would have sat PENDING forever. They are still real asks,
        # so they are KEPT rather than dropped; what changes is that the file records the fact, and
        # `needs_type` is normalised against the document catalog so a model that answered with a
        # near-miss ("verification_of_employment") still matches.
        #
        # CATEGORY: every floor need carried one and no AI need did, so more than half the list could
        # not be grouped. It is derivable from the type — the same catalog the documents use.
        needs_type = canonical_need_type(p.need_type)
        reasoning = p.reasoning
        if needs_type is None:
            logger.info(
                "ai_need_without_matchable_type",
                loan_file_id=str(loan_file.id),
                proposed_type=p.need_type,  # a type name, not PII
            )
        reasoning = _unmatchable_note(reasoning, matchable=needs_type is not None)
        need = await create_needs_item(
            db,
            loan_file_id=loan_file.id,
            title=p.need_description,
            needs_type=needs_type or p.need_type,
            category=category_for_need_type(needs_type),
            origin=NeedsItemOrigin.AI_REASONING,
            disposition=NeedsItemDisposition.PROPOSED,  # the processor confirms (LP-70)
            reasoning=reasoning,
            # LP-110: persist the AI's cited source facts (grounded, AI-identified) so the need's
            # reasoning is falsifiable. None (not []) when the model cited nothing, to leave the
            # column NULL for a genuinely source-less proposal.
            source_facts=[f.model_dump() for f in p.triggered_by] or None,
        )
        created.append(need)
        if p.need_type:
            existing_types.add(p.need_type)
        existing_descs.add(p.need_description.strip().lower())
    if created:
        logger.info("ai_needs_ingested", loan_file_id=str(loan_file.id), count=len(created))
    return created


async def _apply_retractions(
    db: AsyncSession,
    loan_file: LoanFile,
    retractions: Sequence[RetractedNeed],
    existing: Sequence[NeedsItem],
    proposals: Sequence[ProposedNeed],
) -> int:
    """LP-633 — land the model's withdrawals as LP-631 coverage flags. Returns how many stuck.

    A need the same response ALSO proposes is not retracted. The model can contradict itself in one
    answer — argue for the ask under ``needs`` and against it under ``retract`` — and the flag would
    then sit on a row the same run just argued for, telling the processor two opposite things at once.
    It resolves toward KEEPING the ask, the direction that cannot lose a document. Matched on type and
    on description, because an untyped need collides only by wording — and against the model's RAW
    proposals, because `reconcile` has already dropped any whose type the file covers, which is every
    re-proposal of a need that exists.

    A retraction naming an id that is not on this file, or a need a processor has touched, is dropped
    silently — the model is answering about a list it was given, and neither case is worth failing a
    needs update over. ``apply_retraction`` re-checks eligibility itself; this only resolves the ids.
    """
    if not retractions:
        return 0
    re_proposed_types = {p.need_type for p in proposals if p.need_type}
    re_proposed_descs = {p.need_description.strip().lower() for p in proposals}
    by_id = {str(need.id): need for need in existing}
    documents_on_file = {
        str(document_id)
        for document_id in (
            await db.scalars(
                only_active(
                    select(Document.id).where(Document.loan_file_id == loan_file.id), Document
                )
            )
        ).all()
    }
    applied = 0
    for retraction in retractions:
        need = by_id.get(retraction.need_id)
        if need is None:
            continue
        if need.needs_type in re_proposed_types or need.title.strip().lower() in re_proposed_descs:
            logger.info(
                "ai_need_retraction_contradicted",
                loan_file_id=str(loan_file.id),
                needs_type=need.needs_type,  # a document type, not PII
            )
            continue
        # Only a document actually on this file may be cited. The model is quoting an id back at us
        # and a wrong one would point the processor's "checked against" line at another file's
        # document — so an unrecognised id drops to None and the note stands on its own.
        document_id = (
            UUID(retraction.document_id)
            if retraction.document_id in documents_on_file and retraction.document_id
            else None
        )
        if await apply_retraction(db, need=need, why=retraction.why, document_id=document_id):
            applied += 1
            logger.info(
                "ai_need_retracted",
                loan_file_id=str(loan_file.id),
                needs_type=need.needs_type,  # a document type, not PII
            )
    return applied


def _unmatchable_note(reasoning: str, *, matchable: bool = False) -> str:
    """Say on the need that no upload can close it (LP-625).

    Satisfaction-matching keys on ``needs_type``, so a proposal with no catalog type can never be
    advanced by ANY document — LF-ABRS carried two ("documentation for the 'Other' liability", "for the
    unspecified asset") that would have sat PENDING forever, indistinguishable on the list from needs a
    document clears. The ask is real and is KEPT; what changes is that the row stops implying a file
    will close it.
    """
    if matchable:
        return reasoning
    return (
        f"{reasoning}\n\nNo document type matches this request, so uploading a file cannot clear "
        "it — close it by hand once the question is answered."
    ).strip()


def _refreshable(existing: Sequence[NeedsItem], need_type: str) -> NeedsItem | None:
    """The AI-proposed need of this type whose reasoning may still be rewritten (LP-625).

    Untouched means untouched: origin AI_REASONING, disposition still PROPOSED, and still open. A need
    a processor confirmed, dismissed or adjusted carries their judgment, and a later model run has no
    business editing the reason they acted on.
    """
    for need in existing:
        if (
            need.needs_type == need_type
            and need.origin is NeedsItemOrigin.AI_REASONING
            and need.disposition is NeedsItemDisposition.PROPOSED
            and need.status in (NeedsItemStatus.PENDING, NeedsItemStatus.REQUESTED)
        ):
            return need
    return None


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
