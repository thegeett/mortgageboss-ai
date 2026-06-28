"""Cross-source verification service (LP-78) — assemble, run, emit, complete the loop.

The DB-facing half of the AI cross-source layer. It:

1. **Assembles the two sides** — the stated MISMO data and the verified document
   extractions (with page + snippet source locations) — into one structured
   context.
2. **Runs the one general AI pass** (:mod:`app.ai.cross_source`), which surfaces
   discrepancies as structured findings.
3. **Emits** them into LP-75's shared Finding model (``origin=ai_cross_source``,
   confidence, source-location, uniform shape) — *generator two* of "two
   generators, one findings model". The findings are **for human review**, not
   decisions: they land OPEN, never auto-applied.
4. For recognized remediable types it attaches an **apply spec** so that, when a
   human applies the finding (LP-75's hook), the structured data changes and the
   DTI/LTV calculators (LP-76/77) recompute — **the APPLY→recompute loop**.

The pass runs on a **manual trigger** (it compares two sides — meaningful only
when both are assembled — and is an AI cost); a **staleness flag** marks it out of
date on document change. PII flows through the AI call but is **never logged**
(counts/tokens only). Tenant scoping is via the loan file (the caller resolves it
within the company first).
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.client import AIClientError
from app.ai.cost import estimate_cost
from app.ai.cross_source import CrossSourceRawFinding, CrossSourceResult, reason_cross_source
from app.core.logging import get_logger
from app.models.base import utcnow
from app.models.borrower import Borrower
from app.models.document import Document
from app.models.finding import (
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingResolutionStatus,
    FindingStatus,
)
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.stated_financials import StatedAsset, StatedLiability
from app.models.verification import Verification, VerificationStatus
from app.services.verifications import mark_verification_current

logger = get_logger(__name__)

# Reasoner type — injected so tests can supply a deterministic stub (no real key).
Reasoner = Callable[[str], Awaitable[CrossSourceResult]]

# The finding category is DERIVED from the canonical type (the AI no longer
# returns a category) so it is stable and consistent. Unknown / "other" types fall
# back to CROSS_SOURCE.
_TYPE_CATEGORY = {
    "income_variance": FindingCategory.INCOME,
    "employer_mismatch": FindingCategory.INCOME,
    "gift_discrepancy": FindingCategory.ASSETS,
    "asset_discrepancy": FindingCategory.ASSETS,
    "liability_discrepancy": FindingCategory.CREDIT,
    "property_address_discrepancy": FindingCategory.PROPERTY,
    "co_borrower_discrepancy": FindingCategory.CROSS_SOURCE,
    "identity_discrepancy": FindingCategory.CROSS_SOURCE,
    "other": FindingCategory.CROSS_SOURCE,
}


async def run_cross_source(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    run: Verification,
    actor_user_id: UUID | None = None,
    reason_fn: Reasoner = reason_cross_source,
) -> Verification:
    """Run one cross-source pass into an existing run; emit findings; clear staleness.

    Assembles the stated-vs-verified context, runs the AI pass, emits the structured
    findings into the shared model (attached to ``run``), records the AI cost, and
    marks the run COMPLETED + verification current. On an AI failure the run is
    marked FAILED (the findings path degrades gracefully — nothing is invented).
    ``flush`` only; the caller owns the transaction.

    Re-running **replaces** the file's previous *open* cross-source findings with
    this fresh pass (so re-runs reflect the current state, not an accumulating pile
    of duplicates that would also inflate blocking + the calculator alerts).
    **Resolved** findings (applied / overridden) are preserved — the human's
    decisions persist across runs (ADR-061).
    """
    context = await assemble_cross_source_context(db, loan_file)
    try:
        result = await reason_fn(json.dumps(context))
    except AIClientError:
        logger.warning("cross_source_ai_failed", loan_file_id=str(loan_file.id))
        run.status = VerificationStatus.FAILED
        run.completed_at = utcnow()
        run.error_detail = "AI cross-source pass failed"
        await db.flush()
        return run

    # The AI succeeded → supersede the prior pass's open cross-source findings
    # before emitting the fresh set (only now, so a failed pass leaves them intact).
    superseded = await _supersede_open_cross_source_findings(db, loan_file.id)

    income_target = _resolve_income_target(context)
    red = yellow = 0
    for raw in result.findings:
        finding = _to_finding(
            raw, loan_file_id=loan_file.id, run_id=run.id, income_target=income_target
        )
        db.add(finding)
        if finding.status is FindingStatus.RED:
            red += 1
        else:
            yellow += 1

    run.status = VerificationStatus.COMPLETED
    run.completed_at = utcnow()
    run.red_count = red
    run.yellow_count = yellow
    run.green_count = 0
    run.total_tokens_used = result.input_tokens + result.output_tokens
    run.total_cost_estimate = estimate_cost(
        model=result.model, input_tokens=result.input_tokens, output_tokens=result.output_tokens
    )
    await mark_verification_current(db, loan_file_id=loan_file.id)
    await db.flush()
    logger.info(
        "cross_source_pass_done",
        loan_file_id=str(loan_file.id),
        findings=red + yellow,  # counts only — never the findings' content (PII)
        red=red,
        yellow=yellow,
        superseded=superseded,  # prior open findings replaced by this pass
    )
    return run


async def _supersede_open_cross_source_findings(db: AsyncSession, loan_file_id: UUID) -> int:
    """Soft-delete the file's OPEN cross-source findings (a re-run replaces them).

    Only ``ai_cross_source`` findings that are still OPEN are superseded — resolved
    ones (applied / overridden) are preserved so the human's decisions persist
    across runs. Returns how many were superseded. Scoped to the one file.
    """
    result = await db.execute(
        update(Finding)
        .where(
            Finding.loan_file_id == loan_file_id,
            Finding.origin == FindingOrigin.AI_CROSS_SOURCE,
            Finding.resolution_status == FindingResolutionStatus.OPEN,
            Finding.deleted_at.is_(None),
        )
        .values(deleted_at=utcnow())
    )
    await db.flush()
    return cast("CursorResult[Any]", result).rowcount or 0


# --------------------------------------------------------------------------- #
# Emit — map a raw AI finding onto LP-75's uniform model (+ the apply spec)
# --------------------------------------------------------------------------- #


def _to_finding(
    raw: CrossSourceRawFinding,
    *,
    loan_file_id: UUID,
    run_id: UUID,
    income_target: str | None,
) -> Finding:
    """Map one AI discrepancy onto a Finding (origin=ai_cross_source, uniform shape).

    Recognized remediable types get an **apply spec** in ``details["apply"]`` so the
    APPLY→recompute loop can fire when a human applies the finding; novel findings
    are surfaced without one (handled manually). The finding lands **OPEN** — the AI
    surfaces, it does not decide. The category is DERIVED from the type; severity
    defaults to YELLOW (cross-source findings are advisory — the deterministic rules
    produce the blocking red findings).
    """
    category = _TYPE_CATEGORY.get(raw.type, FindingCategory.CROSS_SOURCE)
    details: dict[str, Any] = {
        "type": raw.type,
        "stated_value": raw.stated_value,
        "document_value": raw.document_value,
        "source_document": raw.source_document,
        "reasoning": raw.reasoning,
    }
    apply_spec = _build_apply_spec(raw, income_target=income_target)
    if apply_spec is not None:
        details["apply"] = apply_spec

    return Finding(
        loan_file_id=loan_file_id,
        verification_id=run_id,
        rule_id=f"cross_source.{raw.type}",
        origin=FindingOrigin.AI_CROSS_SOURCE,
        confidence=raw.confidence,
        status=FindingStatus.YELLOW,
        category=category,
        message=raw.description,
        details=details,
        source_page=raw.page,
        source_snippet=raw.snippet,
    )


def _build_apply_spec(
    raw: CrossSourceRawFinding, *, income_target: str | None
) -> dict[str, Any] | None:
    """The structured remediation an apply would perform, for recognized types.

    * ``liability_discrepancy`` → add the documented obligation to liabilities
      (LP-75's ``add_liability``) → the DTI recomputes higher.
    * ``income_variance`` → correct the stated income to the verified figure
      (``correct_income``) → lower income → the DTI recomputes higher.

    The numeric amount is parsed from the (free-text) ``document_value`` — the AI no
    longer returns a dedicated amount field. Returns ``None`` for types without a
    deterministic remediation (the AI's perception is still surfaced; a human
    handles it).
    """
    if raw.type == "liability_discrepancy":
        amount = _first_amount(raw.document_value)
        if amount is not None:
            return {
                "action": "add_liability",
                "liability_type": "Installment",
                "monthly_payment": amount,
                "holder_name": raw.source_document,
            }
    if raw.type == "income_variance" and income_target is not None:
        amount = _first_amount(raw.document_value)
        if amount is not None:
            return {
                "action": "correct_income",
                "income_item_id": income_target,
                "monthly_amount": amount,
            }
    return None


def _first_amount(value: str | None) -> str | None:
    """The first numeric amount in a free-text value (e.g. ``"$7,000/mo"`` → ``"7000"``).

    The AI's ``document_value`` is human text, not a clean number, so a remediation
    that needs a money figure parses one out. Returns ``None`` if there is none.
    """
    if value is None:
        return None
    match = re.search(r"\d[\d,]*(?:\.\d+)?", value)
    if match is None:
        return None
    return match.group(0).replace(",", "")


def _resolve_income_target(context: dict[str, Any]) -> str | None:
    """The stated income item an income-variance correction should target.

    Picks the largest employment-income item across borrowers (the primary income)
    — a deterministic default; the rich UI (LP-81) will let a processor choose.
    """
    best_id: str | None = None
    best_amount = Decimal(-1)
    for borrower in context.get("stated", {}).get("borrowers", []):
        for item in borrower.get("income_items", []):
            if not item.get("employment_income"):
                continue
            amount = _to_decimal(item.get("monthly_amount"))
            if amount is not None and amount > best_amount:
                best_amount = amount
                best_id = item.get("id")
    return best_id


# --------------------------------------------------------------------------- #
# Assemble the two sides — stated MISMO vs. verified document extractions
# --------------------------------------------------------------------------- #


async def assemble_cross_source_context(db: AsyncSession, loan_file: LoanFile) -> dict[str, Any]:
    """Build the structured stated-vs-verified context the AI compares.

    Contains borrower PII (names, amounts) — it is the AI call's input and is
    **never logged**. Money is stringified for JSON.
    """
    return {
        "loan": {
            "amount": _money(loan_file.loan_amount or loan_file.note_amount),
            "purpose": loan_file.loan_purpose.value if loan_file.loan_purpose else None,
            "program": loan_file.loan_program.value if loan_file.loan_program else None,
        },
        "stated": {
            "borrowers": await _stated_borrowers(db, loan_file.id),
            "liabilities": await _stated_liabilities(db, loan_file.id),
            "assets": await _stated_assets(db, loan_file.id),
        },
        "verified_documents": await _verified_documents(db, loan_file.id),
    }


async def _stated_borrowers(db: AsyncSession, loan_file_id: UUID) -> list[dict[str, Any]]:
    stmt = only_active(
        select(Borrower)
        .where(Borrower.loan_file_id == loan_file_id)
        .options(
            selectinload(Borrower.stated_income_items), selectinload(Borrower.stated_employers)
        )
        .order_by(Borrower.borrower_position),
        Borrower,
    )
    borrowers = (await db.execute(stmt)).scalars().all()
    return [
        {
            "name": f"{b.first_name} {b.last_name}".strip(),
            "income_items": [
                {
                    "id": str(item.id),
                    "monthly_amount": _money(item.monthly_amount),
                    "income_type": item.income_type,
                    "employment_income": item.employment_income,
                }
                for item in b.stated_income_items
                if item.deleted_at is None
            ],
            "employers": [
                {"name": e.employer_name, "is_current": e.is_current}
                for e in b.stated_employers
                if e.deleted_at is None
            ],
        }
        for b in borrowers
    ]


async def _stated_liabilities(db: AsyncSession, loan_file_id: UUID) -> list[dict[str, Any]]:
    # Deterministic order (LP-78): the AI must see identical input every run, so
    # an unordered query can't reshuffle the context and nudge the output.
    stmt = only_active(
        select(StatedLiability).where(StatedLiability.loan_file_id == loan_file_id),
        StatedLiability,
    ).order_by(StatedLiability.created_at, StatedLiability.id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "liability_type": r.liability_type,
            "monthly_payment": _money(r.monthly_payment),
            "holder_name": r.holder_name,
        }
        for r in rows
    ]


async def _stated_assets(db: AsyncSession, loan_file_id: UUID) -> list[dict[str, Any]]:
    stmt = only_active(
        select(StatedAsset).where(StatedAsset.loan_file_id == loan_file_id), StatedAsset
    ).order_by(StatedAsset.created_at, StatedAsset.id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {"asset_type": r.asset_type, "value": _money(r.value), "holder_name": r.holder_name}
        for r in rows
    ]


async def _verified_documents(db: AsyncSession, loan_file_id: UUID) -> list[dict[str, Any]]:
    """Each document's current extraction typed-core fields (value + page + snippet)."""
    stmt = only_active(
        select(Document)
        .where(Document.loan_file_id == loan_file_id)
        .options(selectinload(Document.extractions)),
        Document,
    ).order_by(Document.created_at, Document.id)
    documents = (await db.execute(stmt)).scalars().all()
    out: list[dict[str, Any]] = []
    for doc in documents:
        extraction = doc.current_extraction
        if extraction is None:
            continue
        fields = _typed_fields(extraction.extracted_data)
        if not fields:
            continue
        out.append({"document_type": doc.document_type, "fields": fields})
    return out


def _typed_fields(extracted_data: dict[str, Any]) -> dict[str, Any]:
    """The ``{value, source}`` typed-core fields of an extraction (skip catch-all)."""
    fields: dict[str, Any] = {}
    for key, node in extracted_data.items():
        if not isinstance(node, dict) or "value" not in node:
            continue
        value = node.get("value")
        if value is None:
            continue
        raw_source = node.get("source")
        source: dict[str, Any] = raw_source if isinstance(raw_source, dict) else {}
        fields[key] = {
            "value": str(value),
            "page": source.get("page"),
            "snippet": source.get("snippet"),
        }
    return fields


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None
