"""DTI calculator service (LP-76) — auto-populate, override, couple to findings.

This is the DB-facing half of the DTI calculator. It:

1. **Auto-populates** the itemized inputs from the file's structured data — income
   from stated income, debts from stated liabilities, the housing payment from the
   loan terms (computed P&I) + extracted taxes / insurance / HOA. The calculator
   opens **already filled** with the file's real numbers (the "better than
   ChatGPT": no re-entry), reading the *same* structured data the rules engine
   evaluates.
2. Applies the processor's **overrides** (persisted, audited) on top — overrides
   take precedence; the auto values are a starting point, not a cage.
3. Computes the ratios via the pure deterministic engine (:mod:`app.verification.dti`).
4. Resolves the **effective program limit** side-by-side (LP-74's rule + any lender
   overlay).
5. **Couples to findings** (LP-75): the unresolved-findings alert queries open
   in-scope findings; and because the calculation reads the structured data live,
   applying a finding (which adds e.g. a liability) makes the next calculation
   recompute — LP-76 is a recompute consumer of the apply hook.

Pure math lives in :mod:`app.verification.dti`; this module only gathers data and
maps it onto the response. Money is ``Decimal``; tenant scoping is via the loan
file (the caller resolves it within the company first); no PII (no SSNs) is read.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.borrower import Borrower
from app.models.document import Document
from app.models.dti_override import DtiOverride
from app.models.extraction import Extraction
from app.models.helpers import only_active
from app.models.lender import Lender, LoanProgram
from app.models.loan_file import LoanFile
from app.models.stated_financials import StatedIncomeItem, StatedLiability
from app.schemas.dti import (
    DtiCalculation,
    DtiFindingsStatus,
    DtiLimit,
    DtiLineItem,
    DtiOverrideInput,
)
from app.services.activity_log import log_activity
from app.services.finding_blocking import open_in_scope_findings
from app.services.mi import compute_loan_mi
from app.verification.confidence import DEFAULT_CONFIDENCE_CUTOFF
from app.verification.dti import (
    BACK_END_FORMULA,
    FRONT_END_FORMULA,
    DtiLine,
    compute_dti,
    monthly_principal_interest,
)
from app.verification.registry import default_registry

# --- Stable field keys for the housing components (the PITI + MI + HOA lines) -
HOUSING_PRINCIPAL_INTEREST = "housing.principal_interest"
HOUSING_TAXES = "housing.taxes"
HOUSING_INSURANCE = "housing.insurance"
HOUSING_MORTGAGE_INSURANCE = "housing.mortgage_insurance"
HOUSING_HOA = "housing.hoa"

_BACK_END_RULE_IDS = {
    LoanProgram.CONVENTIONAL: "conv.dti.back_end_max",
    LoanProgram.FHA: "fha.dti.back_end_max",
}


# --------------------------------------------------------------------------- #
# Auto-population — the structured-data inputs (before overrides)
# --------------------------------------------------------------------------- #


class _AutoLine:
    """An auto-populated input line (key, label, auto amount, source) pre-override."""

    __slots__ = ("auto", "key", "label", "source")

    def __init__(self, key: str, label: str, auto: Decimal | None, source: str) -> None:
        self.key = key
        self.label = label
        self.auto = auto
        self.source = source


async def _auto_income_lines(db: AsyncSession, loan_file_id: UUID) -> list[_AutoLine]:
    """Stated income, itemized per income item (label by type + borrower first name)."""
    stmt = only_active(
        select(StatedIncomeItem, Borrower.first_name)
        .join(Borrower, StatedIncomeItem.borrower_id == Borrower.id)
        .where(Borrower.loan_file_id == loan_file_id),
        StatedIncomeItem,
    ).order_by(Borrower.borrower_position, StatedIncomeItem.created_at)
    lines: list[_AutoLine] = []
    for item, first_name in (await db.execute(stmt)).all():
        kind = (item.income_type or "Income").strip()
        who = (first_name or "Borrower").strip()
        lines.append(
            _AutoLine(f"income.{item.id}", f"{kind} — {who}", item.monthly_amount, "stated")
        )
    return lines


async def _auto_debt_lines(db: AsyncSession, loan_file_id: UUID) -> list[_AutoLine]:
    """Stated liabilities, itemized per liability (each monthly obligation)."""
    stmt = only_active(
        select(StatedLiability).where(StatedLiability.loan_file_id == loan_file_id),
        StatedLiability,
    ).order_by(StatedLiability.created_at)
    lines: list[_AutoLine] = []
    for liab in (await db.execute(stmt)).scalars().all():
        kind = (liab.liability_type or "Liability").strip()
        label = f"{kind} — {liab.holder_name}" if liab.holder_name else kind
        lines.append(_AutoLine(f"debt.{liab.id}", label, liab.monthly_payment, "stated"))
    return lines


async def _auto_housing_lines(
    db: AsyncSession,
    loan_file: LoanFile,
    confidence_cutoff: float = DEFAULT_CONFIDENCE_CUTOFF,
) -> list[_AutoLine]:
    """The housing payment components: PITI (computed P&I + extracted T&I) + MI + HOA.

    The mortgage-insurance line CONSUMES the LP-87 MI calculator's monthly premium (LP-91) —
    program-aware (FHA MIP always; Conventional PMI when LTV > 80%) and from the single shared
    source (:func:`app.services.mi.compute_loan_mi`), so PITI no longer omits mandatory MI.
    Only the *monthly* premium enters PITI; the FHA UFMIP is financed into the loan (not a
    monthly DTI item). The auto value is overrideable (a processor DtiOverride still wins).
    """
    pi = monthly_principal_interest(
        loan_file.note_amount or loan_file.loan_amount,
        loan_file.note_rate_percent,
        loan_file.amortization_months,
    )
    taxes = await _extracted_monthly(
        db, loan_file.id, "property_tax_bill", "annual_tax_amount", annual=True
    )
    insurance = await _extracted_monthly(
        db, loan_file.id, "homeowners_insurance", "annual_premium", annual=True
    )
    hoa = await _extracted_hoa_monthly(db, loan_file.id)
    mi = await compute_loan_mi(db, loan_file=loan_file, confidence_cutoff=confidence_cutoff)
    return [
        _AutoLine(HOUSING_PRINCIPAL_INTEREST, "Principal & interest", pi, "computed"),
        _AutoLine(HOUSING_TAXES, "Property taxes", taxes, "extracted"),
        _AutoLine(HOUSING_INSURANCE, "Homeowners insurance", insurance, "extracted"),
        # Consumed from the MI calculator (single source of truth) — "computed", no longer the
        # old manual/$0 line that silently omitted MI and understated the DTI.
        _AutoLine(
            HOUSING_MORTGAGE_INSURANCE,
            "Mortgage insurance (MI)",
            mi.result.monthly_premium,
            "computed",
        ),
        _AutoLine(HOUSING_HOA, "HOA dues", hoa, "extracted"),
    ]


async def _current_extracted_data(
    db: AsyncSession, loan_file_id: UUID, document_type: str
) -> dict[str, Any] | None:
    """The current extraction payload for the newest document of a type, or None."""
    stmt = (
        only_active(
            select(Extraction)
            .join(Document, Extraction.document_id == Document.id)
            .where(
                Document.loan_file_id == loan_file_id,
                Document.document_type == document_type,
                Extraction.is_current.is_(True),
            ),
            Document,
        )
        .order_by(Document.created_at.desc())
        .limit(1)
    )
    extraction = (await db.execute(stmt)).scalars().first()
    return extraction.extracted_data if extraction is not None else None


def _typed_value(data: dict[str, Any] | None, field: str) -> Decimal | None:
    """Read a typed-core ``{value}`` Decimal off an extraction payload."""
    if data is None:
        return None
    node = data.get(field)
    if not isinstance(node, dict):
        return None
    raw = node.get("value")
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (ArithmeticError, ValueError):
        return None


async def _extracted_monthly(
    db: AsyncSession, loan_file_id: UUID, document_type: str, field: str, *, annual: bool
) -> Decimal | None:
    """A monthly amount from an extracted (possibly annual) figure, or None."""
    value = _typed_value(await _current_extracted_data(db, loan_file_id, document_type), field)
    if value is None:
        return None
    return (value / Decimal(12)) if annual else value


async def _extracted_hoa_monthly(db: AsyncSession, loan_file_id: UUID) -> Decimal | None:
    """HOA dues normalized to monthly using the stated dues frequency."""
    data = await _current_extracted_data(db, loan_file_id, "hoa_statement")
    dues = _typed_value(data, "dues_amount")
    if dues is None:
        return None
    frequency = ""
    node = (data or {}).get("dues_frequency")
    if isinstance(node, dict) and isinstance(node.get("value"), str):
        frequency = node["value"].strip().lower()
    divisor = {
        "monthly": 1,
        "quarterly": 3,
        "semiannual": 6,
        "semi-annual": 6,
        "annual": 12,
        "annually": 12,
    }
    return dues / Decimal(divisor.get(frequency, 1))


# --------------------------------------------------------------------------- #
# The calculation — auto + overrides → ratios + limit + findings
# --------------------------------------------------------------------------- #


async def _active_overrides(db: AsyncSession, loan_file_id: UUID) -> dict[str, Decimal]:
    stmt = only_active(
        select(DtiOverride).where(DtiOverride.loan_file_id == loan_file_id), DtiOverride
    )
    return {row.field_key: row.value for row in (await db.execute(stmt)).scalars().all()}


def _to_items(
    autos: Sequence[_AutoLine], overrides: dict[str, Decimal]
) -> tuple[list[DtiLineItem], list[DtiLine]]:
    """Build response line items + the engine lines (effective = override ?? auto ?? 0)."""
    items: list[DtiLineItem] = []
    engine_lines: list[DtiLine] = []
    for auto in autos:
        override = overrides.get(auto.key)
        effective = override if override is not None else (auto.auto or Decimal(0))
        items.append(
            DtiLineItem(
                key=auto.key,
                label=auto.label,
                auto_amount=auto.auto,
                override_amount=override,
                amount=effective,
                source="override" if override is not None else auto.source,
                overridden=override is not None,
            )
        )
        engine_lines.append(DtiLine(key=auto.key, label=auto.label, amount=effective))
    return items, engine_lines


async def build_dti_calculation(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    confidence_cutoff: float = DEFAULT_CONFIDENCE_CUTOFF,
) -> DtiCalculation:
    """Assemble the full, transparent DTI calculation for one loan file.

    Auto-populates from the structured data, applies overrides, computes the
    ratios deterministically, resolves the effective limit, and attaches the
    unresolved-findings alert. Reads only — the caller has resolved the file
    within the company (tenant scoping).
    """
    income_auto = await _auto_income_lines(db, loan_file.id)
    housing_auto = await _auto_housing_lines(db, loan_file, confidence_cutoff)
    debt_auto = await _auto_debt_lines(db, loan_file.id)
    overrides = await _active_overrides(db, loan_file.id)

    income_items, income_lines = _to_items(income_auto, overrides)
    housing_items, housing_lines = _to_items(housing_auto, overrides)
    debt_items, debt_lines = _to_items(debt_auto, overrides)

    result = compute_dti(income_lines, housing_lines, debt_lines)

    lender_slug = await _lender_slug(db, loan_file)
    limit = _resolve_limit(loan_file.loan_program, lender_slug, result.back_end_pct)

    in_scope = await open_in_scope_findings(
        db, loan_file_id=loan_file.id, confidence_cutoff=confidence_cutoff
    )

    return DtiCalculation(
        front_end_dti=result.front_end_pct,
        back_end_dti=result.back_end_pct,
        gross_monthly_income=result.gross_monthly_income,
        housing_payment=result.housing_payment,
        monthly_debts=result.monthly_debts,
        total_monthly_obligations=result.total_monthly_obligations,
        income_items=income_items,
        housing_items=housing_items,
        debt_items=debt_items,
        front_end_formula=FRONT_END_FORMULA,
        back_end_formula=BACK_END_FORMULA,
        program=loan_file.loan_program.value if loan_file.loan_program else None,
        limit=limit,
        findings=DtiFindingsStatus(unresolved=len(in_scope) > 0, open_in_scope_count=len(in_scope)),
    )


def _resolve_limit(
    program: LoanProgram | None, lender_slug: str | None, back_end_pct: Decimal | None
) -> DtiLimit:
    """The effective back-end DTI cap (LP-74's rule + overlay), with pass/over status."""
    if program is None:
        return DtiLimit(
            back_end_max=None, source="unknown", lender_slug=None, rule_id=None, status="unknown"
        )
    rules = default_registry().resolve(program=program, lender_slug=lender_slug)
    rule_id = _BACK_END_RULE_IDS.get(program)
    rule = next((r for r in rules if r.rule_id == rule_id), None)
    if rule is None:
        return DtiLimit(
            back_end_max=None, source="unknown", lender_slug=None, rule_id=rule_id, status="unknown"
        )
    cap = rule.condition.value
    status = "unknown" if back_end_pct is None else "pass" if back_end_pct <= cap else "over"
    return DtiLimit(
        back_end_max=cap,
        source="overlay" if rule.overlay_applied else "program_default",
        lender_slug=rule.overlay_applied,
        rule_id=rule.rule_id,
        status=status,
    )


async def _lender_slug(db: AsyncSession, loan_file: LoanFile) -> str | None:
    if loan_file.lender_id is None:
        return None
    lender = await db.get(Lender, loan_file.lender_id)
    return lender.slug if lender is not None else None


# --------------------------------------------------------------------------- #
# Overrides — set / clear, persisted + audited
# --------------------------------------------------------------------------- #


class UnknownDtiFieldError(Exception):
    """The override field_key does not match any current calculator input."""


async def _auto_amount_for(db: AsyncSession, loan_file: LoanFile, field_key: str) -> Decimal | None:
    """The auto-populated value for one field_key (for the audit's prior value)."""
    autos = (
        await _auto_income_lines(db, loan_file.id)
        + await _auto_housing_lines(db, loan_file)
        + await _auto_debt_lines(db, loan_file.id)
    )
    for auto in autos:
        if auto.key == field_key:
            return auto.auto
    raise UnknownDtiFieldError(field_key)


async def set_dti_override(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    field_key: str,
    data: DtiOverrideInput,
    actor_user_id: UUID,
    confidence_cutoff: float = DEFAULT_CONFIDENCE_CUTOFF,
) -> DtiCalculation:
    """Set (or revive) an override on one DTI input field, audited; then recompute.

    Validates the field against the current inputs, records the prior value
    (override-or-auto) in the activity log, upserts the override row (precedence +
    persistence), and returns the recomputed calculation (at the caller's aggression
    cutoff, LP-79). Raises :class:`UnknownDtiFieldError` for an unknown field.
    """
    prior_auto = await _auto_amount_for(db, loan_file, field_key)  # also validates the key

    existing = await _get_override_row(db, loan_file.id, field_key)
    prior_value = existing.value if existing is not None and not existing.is_deleted else prior_auto
    if existing is not None:
        existing.value = data.amount
        existing.note = data.note
        existing.actor_user_id = actor_user_id
        existing.deleted_at = None
    else:
        db.add(
            DtiOverride(
                loan_file_id=loan_file.id,
                field_key=field_key,
                value=data.amount,
                note=data.note,
                actor_user_id=actor_user_id,
            )
        )
    await db.flush()
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.DTI_OVERRIDDEN,
        summary=f"DTI input overridden: {field_key}",
        actor_user_id=actor_user_id,
        detail={
            "field_key": field_key,
            "from": _money_str(prior_value),
            "to": _money_str(data.amount),
            "note": data.note,
        },
    )
    return await build_dti_calculation(db, loan_file=loan_file, confidence_cutoff=confidence_cutoff)


async def clear_dti_override(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    field_key: str,
    actor_user_id: UUID,
    confidence_cutoff: float = DEFAULT_CONFIDENCE_CUTOFF,
) -> DtiCalculation:
    """Clear an override (revert to the auto value), audited; then recompute."""
    existing = await _get_override_row(db, loan_file.id, field_key)
    if existing is None or existing.is_deleted:
        return await build_dti_calculation(
            db, loan_file=loan_file, confidence_cutoff=confidence_cutoff
        )
    prior = existing.value
    existing.deleted_at = utcnow()
    await db.flush()
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.DTI_OVERRIDDEN,
        summary=f"DTI override cleared: {field_key}",
        actor_user_id=actor_user_id,
        detail={"field_key": field_key, "from": _money_str(prior), "to": None, "cleared": True},
    )
    return await build_dti_calculation(db, loan_file=loan_file, confidence_cutoff=confidence_cutoff)


async def _get_override_row(
    db: AsyncSession, loan_file_id: UUID, field_key: str
) -> DtiOverride | None:
    """The override row for a (file, field_key), including a soft-deleted one."""
    stmt = select(DtiOverride).where(
        DtiOverride.loan_file_id == loan_file_id, DtiOverride.field_key == field_key
    )
    return (await db.execute(stmt)).scalars().first()


def _money_str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
