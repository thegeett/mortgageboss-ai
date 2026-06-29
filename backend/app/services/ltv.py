"""LTV calculator service (LP-77) — the DB-facing half, mirroring the DTI model.

Reuses LP-76's proven calculator pattern — auto-populate from the structured
data, apply persisted+audited overrides, compute deterministically, resolve the
effective limit, couple to findings — applied to the three LTV ratios. The new
substance is LTV-specific: the **lesser-of** value basis, the **HELOC credit
limit** (not balance) in HCLTV, and **refinance-awareness** (the loan purpose
drives the denominator + the limit).

The appraised value auto-populates from the MISMO valuation where present and is
**override-able** where not (the appraisal isn't a Tier-1 extraction yet — the
override is the graceful fallback). Pure math lives in
:mod:`app.verification.ltv`. Money is ``Decimal``; tenant scoping is via the loan
file; no PII.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.helpers import only_active
from app.models.lender import Lender, LoanProgram
from app.models.loan_file import LoanFile, LoanPurpose, RefinanceType
from app.models.ltv_override import LtvOverride
from app.models.property import Property
from app.schemas.ltv import (
    LtvCalculation,
    LtvFindingsStatus,
    LtvLimit,
    LtvLineItem,
    LtvOverrideInput,
)
from app.services.activity_log import log_activity
from app.services.finding_blocking import open_in_scope_findings
from app.verification.confidence import DEFAULT_CONFIDENCE_CUTOFF
from app.verification.ltv import (
    CLTV_FORMULA,
    HCLTV_FORMULA,
    LtvInputs,
    LtvPurpose,
    compute_ltv,
    ltv_formula,
)
from app.verification.registry import default_registry

# --- Stable field keys for the LTV inputs ------------------------------------
LTV_FIRST_LOAN = "ltv.first_loan"
LTV_SECOND_LOAN = "ltv.second_loan"
LTV_HELOC_DRAWN = "ltv.heloc_drawn"
LTV_HELOC_LIMIT = "ltv.heloc_credit_limit"
LTV_PURCHASE_PRICE = "ltv.purchase_price"
LTV_APPRAISED_VALUE = "ltv.appraised_value"

_PURCHASE_RULE_IDS = {
    LoanProgram.CONVENTIONAL: "conv.ltv.purchase_max",
    LoanProgram.FHA: "fha.ltv.purchase_max",
}
_CASH_OUT_RULE_IDS = {
    LoanProgram.CONVENTIONAL: "conv.ltv.cash_out_max",
    LoanProgram.FHA: "fha.ltv.cash_out_max",
}


class _AutoLine:
    """An auto-populated input line (key, label, auto amount, source) pre-override."""

    __slots__ = ("auto", "key", "label", "source")

    def __init__(self, key: str, label: str, auto: Decimal | None, source: str) -> None:
        self.key = key
        self.label = label
        self.auto = auto
        self.source = source


def ltv_purpose_for(loan_file: LoanFile) -> LtvPurpose:
    """The LTV purpose driving the denominator + limit, from the loan terms."""
    if loan_file.loan_purpose is LoanPurpose.REFINANCE:
        if loan_file.refinance_type is RefinanceType.CASH_OUT:
            return LtvPurpose.CASH_OUT_REFINANCE
        return LtvPurpose.RATE_TERM_REFINANCE
    return LtvPurpose.PURCHASE


def _auto_loan_lines(loan_file: LoanFile) -> list[_AutoLine]:
    """The loan inputs — first lien (auto), plus override-able second / HELOC lines."""
    first = loan_file.loan_amount or loan_file.note_amount
    return [
        _AutoLine(LTV_FIRST_LOAN, "First mortgage", first, "stated"),
        _AutoLine(LTV_SECOND_LOAN, "Second mortgage", None, "manual"),
        _AutoLine(LTV_HELOC_DRAWN, "HELOC drawn balance", None, "manual"),
        _AutoLine(LTV_HELOC_LIMIT, "HELOC credit limit", None, "manual"),
    ]


async def _auto_value_lines(db: AsyncSession, loan_file_id: UUID) -> list[_AutoLine]:
    """The property values — purchase price + appraised value (the lesser-of basis)."""
    prop = await _property(db, loan_file_id)
    purchase_price = prop.purchase_price if prop else None
    # The appraised value: MISMO valuation, else the estimated value. Override-able
    # where neither is present (the appraisal isn't a Tier-1 extraction yet).
    appraised = (prop.valuation_amount or prop.estimated_value) if prop else None
    return [
        _AutoLine(
            LTV_PURCHASE_PRICE,
            "Purchase price",
            purchase_price,
            "stated" if purchase_price is not None else "manual",
        ),
        _AutoLine(
            LTV_APPRAISED_VALUE,
            "Appraised value",
            appraised,
            "stated" if appraised is not None else "manual",
        ),
    ]


async def _property(db: AsyncSession, loan_file_id: UUID) -> Property | None:
    stmt = only_active(select(Property).where(Property.loan_file_id == loan_file_id), Property)
    return (await db.execute(stmt)).scalars().first()


async def _active_overrides(db: AsyncSession, loan_file_id: UUID) -> dict[str, Decimal]:
    stmt = only_active(
        select(LtvOverride).where(LtvOverride.loan_file_id == loan_file_id), LtvOverride
    )
    return {row.field_key: row.value for row in (await db.execute(stmt)).scalars().all()}


def _to_items(
    autos: Sequence[_AutoLine], overrides: dict[str, Decimal]
) -> tuple[list[LtvLineItem], dict[str, Decimal]]:
    """Build response line items + an effective-amount map (override ?? auto ?? 0)."""
    items: list[LtvLineItem] = []
    effective: dict[str, Decimal] = {}
    for auto in autos:
        override = overrides.get(auto.key)
        value = override if override is not None else (auto.auto or Decimal(0))
        effective[auto.key] = value
        items.append(
            LtvLineItem(
                key=auto.key,
                label=auto.label,
                auto_amount=auto.auto,
                override_amount=override,
                amount=value,
                source="override" if override is not None else auto.source,
                overridden=override is not None,
            )
        )
    return items, effective


async def build_ltv_calculation(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    confidence_cutoff: float = DEFAULT_CONFIDENCE_CUTOFF,
) -> LtvCalculation:
    """Assemble the full, transparent LTV calculation for one loan file.

    Auto-populates the loan + property inputs, applies overrides, computes the
    three ratios (refinance-aware), resolves the purpose-varying effective limit,
    and attaches the unresolved-findings alert. Reads only.
    """
    purpose = ltv_purpose_for(loan_file)
    loan_auto = _auto_loan_lines(loan_file)
    value_auto = await _auto_value_lines(db, loan_file.id)
    overrides = await _active_overrides(db, loan_file.id)

    loan_items, loan_eff = _to_items(loan_auto, overrides)
    value_items, value_eff = _to_items(value_auto, overrides)

    inputs = LtvInputs(
        first_loan=loan_eff[LTV_FIRST_LOAN],
        second_loan=loan_eff[LTV_SECOND_LOAN],
        heloc_drawn=loan_eff[LTV_HELOC_DRAWN],
        heloc_limit=loan_eff[LTV_HELOC_LIMIT],
        purchase_price=value_eff[LTV_PURCHASE_PRICE],
        appraised_value=value_eff[LTV_APPRAISED_VALUE],
    )
    result = compute_ltv(inputs, purpose)

    lender_slug = await _lender_slug(db, loan_file)
    limit = _resolve_limit(loan_file.loan_program, purpose, lender_slug, result.ltv_pct)

    in_scope = await open_in_scope_findings(
        db, loan_file_id=loan_file.id, confidence_cutoff=confidence_cutoff
    )

    return LtvCalculation(
        ltv=result.ltv_pct,
        cltv=result.cltv_pct,
        hcltv=result.hcltv_pct,
        value_basis=result.value_basis,
        value_basis_label=result.value_basis_label,
        loan_items=loan_items,
        value_items=value_items,
        ltv_formula=ltv_formula(purpose),
        cltv_formula=CLTV_FORMULA,
        hcltv_formula=HCLTV_FORMULA,
        purpose=purpose.value,
        program=loan_file.loan_program.value if loan_file.loan_program else None,
        limit=limit,
        findings=LtvFindingsStatus(unresolved=len(in_scope) > 0, open_in_scope_count=len(in_scope)),
    )


def _resolve_limit(
    program: LoanProgram | None,
    purpose: LtvPurpose,
    lender_slug: str | None,
    ltv_pct: Decimal | None,
) -> LtvLimit:
    """The effective LTV cap for the program + purpose (LP-74 rule + overlay)."""
    purpose_basis = "cash_out" if purpose is LtvPurpose.CASH_OUT_REFINANCE else "purchase"
    if program is None:
        return LtvLimit(
            ltv_max=None,
            source="unknown",
            lender_slug=None,
            rule_id=None,
            purpose_basis=purpose_basis,
            status="unknown",
        )
    table = _CASH_OUT_RULE_IDS if purpose is LtvPurpose.CASH_OUT_REFINANCE else _PURCHASE_RULE_IDS
    rule_id = table.get(program)
    rules = default_registry().resolve(program=program, lender_slug=lender_slug)
    rule = next((r for r in rules if r.rule_id == rule_id), None)
    if rule is None:
        return LtvLimit(
            ltv_max=None,
            source="unknown",
            lender_slug=None,
            rule_id=rule_id,
            purpose_basis=purpose_basis,
            status="unknown",
        )
    cap = rule.condition.value
    status = "unknown" if ltv_pct is None else "pass" if ltv_pct <= cap else "over"
    return LtvLimit(
        ltv_max=cap,
        source="overlay" if rule.overlay_applied else "program_default",
        lender_slug=rule.overlay_applied,
        rule_id=rule.rule_id,
        purpose_basis=purpose_basis,
        status=status,
    )


async def _lender_slug(db: AsyncSession, loan_file: LoanFile) -> str | None:
    if loan_file.lender_id is None:
        return None
    lender = await db.get(Lender, loan_file.lender_id)
    return lender.slug if lender is not None else None


# --------------------------------------------------------------------------- #
# Overrides — set / clear, persisted + audited (mirrors the DTI flow)
# --------------------------------------------------------------------------- #


class UnknownLtvFieldError(Exception):
    """The override field_key does not match any current LTV input."""


async def _auto_amount_for(db: AsyncSession, loan_file: LoanFile, field_key: str) -> Decimal | None:
    autos = _auto_loan_lines(loan_file) + await _auto_value_lines(db, loan_file.id)
    for auto in autos:
        if auto.key == field_key:
            return auto.auto
    raise UnknownLtvFieldError(field_key)


async def set_ltv_override(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    field_key: str,
    data: LtvOverrideInput,
    actor_user_id: UUID,
    confidence_cutoff: float = DEFAULT_CONFIDENCE_CUTOFF,
) -> LtvCalculation:
    """Set (or revive) an override on one LTV input, audited; then recompute.

    Recomputes at the caller's aggression cutoff (LP-79).
    """
    prior_auto = await _auto_amount_for(db, loan_file, field_key)  # validates the key

    existing = await _get_override_row(db, loan_file.id, field_key)
    prior_value = existing.value if existing is not None and not existing.is_deleted else prior_auto
    if existing is not None:
        existing.value = data.amount
        existing.note = data.note
        existing.actor_user_id = actor_user_id
        existing.deleted_at = None
    else:
        db.add(
            LtvOverride(
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
        activity_type=ActivityType.LTV_OVERRIDDEN,
        summary=f"LTV input overridden: {field_key}",
        actor_user_id=actor_user_id,
        detail={
            "field_key": field_key,
            "from": _money_str(prior_value),
            "to": _money_str(data.amount),
            "note": data.note,
        },
    )
    return await build_ltv_calculation(db, loan_file=loan_file, confidence_cutoff=confidence_cutoff)


async def clear_ltv_override(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    field_key: str,
    actor_user_id: UUID,
    confidence_cutoff: float = DEFAULT_CONFIDENCE_CUTOFF,
) -> LtvCalculation:
    """Clear an override (revert to the auto value), audited; then recompute."""
    existing = await _get_override_row(db, loan_file.id, field_key)
    if existing is None or existing.is_deleted:
        return await build_ltv_calculation(
            db, loan_file=loan_file, confidence_cutoff=confidence_cutoff
        )
    prior = existing.value
    existing.deleted_at = utcnow()
    await db.flush()
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.LTV_OVERRIDDEN,
        summary=f"LTV override cleared: {field_key}",
        actor_user_id=actor_user_id,
        detail={"field_key": field_key, "from": _money_str(prior), "to": None, "cleared": True},
    )
    return await build_ltv_calculation(db, loan_file=loan_file, confidence_cutoff=confidence_cutoff)


async def _get_override_row(
    db: AsyncSession, loan_file_id: UUID, field_key: str
) -> LtvOverride | None:
    stmt = select(LtvOverride).where(
        LtvOverride.loan_file_id == loan_file_id, LtvOverride.field_key == field_key
    )
    return (await db.execute(stmt)).scalars().first()


def _money_str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
