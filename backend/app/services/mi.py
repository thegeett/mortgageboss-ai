"""Shared mortgage-insurance computation (LP-87 core; consumed by LP-91).

The program-aware monthly mortgage-insurance premium (Conventional PMI / FHA MIP) is
computed **once** here and consumed by **both**:

* the MI calculator view (:func:`app.services.calculators.build_mi_view`), and
* the DTI's PITI housing line (:func:`app.services.dti._auto_housing_lines`).

This is the **single source of truth** (LP-91). The DTI must INCLUDE mandatory MI — FHA MIP
(always) and Conventional PMI (when LTV > 80%) — and must not recompute it independently (a
divergence risk; the same lesson as the appraised-value binding bug). The previous DTI MI
line was manual-only / default $0, so it silently OMITTED MI and understated the front-end
DTI for every FHA file and every low-down Conventional file — biasing DTI low, the
qualifying (dangerous) direction.

Sources the LTV (LP-77, ``build_ltv_calculation``), the base loan amount, the persisted MI
overrides (the shared ``calculator_overrides`` table, ``mortgage_insurance`` namespace), and
LP-84's FHA UFMIP rule; dispatches to the pure arithmetic in
:mod:`app.verification.mortgage_insurance`. The **UFMIP is financed** into the loan and is
NOT a monthly DTI item — only ``monthly_premium`` flows into PITI.

**Grounded-starter (validate with Priya):** the Conventional PMI rate varies by credit / LTV
/ MI provider (a rate card, not a clean formula), so the computed PMI is a *starting point*
the processor overrides with the real quote — it is not authoritative. The FHA MIP rates come
from HUD via LP-84 (more deterministic). This lives next to the override mechanism precisely
so the auto value can be corrected.

This module imports neither :mod:`app.services.dti` nor :mod:`app.services.calculators`, so
both can consume it without an import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calculator_override import CalculatorOverride
from app.models.helpers import only_active
from app.models.lender import LoanProgram
from app.models.loan_file import LoanFile
from app.schemas.calculators import CalcLine
from app.services.ltv import build_ltv_calculation
from app.verification.confidence import DEFAULT_CONFIDENCE_CUTOFF
from app.verification.mortgage_insurance import (
    MiResult,
    compute_conventional_pmi,
    compute_fha_mip,
)
from app.verification.registry import default_registry

# The MI-calculator override namespace (the shared calculator_overrides table).
MI_CALCULATOR = "mortgage_insurance"

# Field keys for the MI calculator's overrideable inputs.
MI_BASE_LOAN_KEY = "mi.base_loan_amount"
MI_ANNUAL_MIP_RATE_KEY = "mi.annual_mip_rate_bps"
MI_PMI_RATE_KEY = "mi.pmi_rate_bps"

# Grounded-starter methodology constants (validate with Priya — domain judgment).
PMI_STARTER_RATE_BPS = Decimal("55")  # a starter PMI annual rate; real rate is a credit/LTV card
FHA_ANNUAL_MIP_STARTER_BPS = Decimal("55")  # most 30-year FHA borrowers; LP-84's rule is the cap
FHA_MIP_DURATION_LTV = Decimal("90")  # LP-84: LTV ≤ 90% → 11yr, > 90% → life


def fha_ufmip_rate_bps() -> Decimal:
    """The FHA UFMIP rate, CONSUMED from LP-84's ``fha.mip.ufmip_rate`` rule (175 bps)."""
    rules = default_registry().resolve(program=LoanProgram.FHA, lender_slug=None)
    rule = next((r for r in rules if r.rule_id == "fha.mip.ufmip_rate"), None)
    return rule.condition.value if rule is not None else Decimal("175")


async def _active_mi_overrides(db: AsyncSession, loan_file_id: UUID) -> dict[str, Decimal]:
    stmt = only_active(
        select(CalculatorOverride).where(
            CalculatorOverride.loan_file_id == loan_file_id,
            CalculatorOverride.calculator == MI_CALCULATOR,
        ),
        CalculatorOverride,
    )
    return {row.field_key: row.value for row in (await db.execute(stmt)).scalars().all()}


def _line(
    key: str, label: str, auto: Decimal | None, source: str, overrides: dict[str, Decimal]
) -> tuple[CalcLine, Decimal]:
    """One overrideable input line + its effective value (override ?? auto ?? 0)."""
    override = overrides.get(key)
    value = override if override is not None else (auto or Decimal(0))
    line = CalcLine(
        key=key,
        label=label,
        auto_amount=auto,
        override_amount=override,
        amount=value,
        source="override" if override is not None else source,
        overridden=override is not None,
    )
    return line, value


@dataclass(frozen=True)
class MiComputation:
    """The MI computation shared by the calculator view + the DTI (LP-91).

    ``result.monthly_premium`` is what the DTI's PITI consumes (None when MI is not required,
    e.g. Conventional at LTV ≤ 80%). ``inputs`` + ``ufmip_bps`` are what the calculator view
    needs to render its steps (the UFMIP is financed — not a monthly DTI item).
    """

    result: MiResult
    inputs: list[CalcLine]  # the overrideable input lines (for the calculator view)
    ufmip_bps: Decimal | None  # the FHA UFMIP rate (None for Conventional)


async def compute_loan_mi(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    confidence_cutoff: float = DEFAULT_CONFIDENCE_CUTOFF,
) -> MiComputation:
    """The program-aware MI — the single source the MI view + the DTI both consume.

    Conventional → PMI (required only when LTV > 80%); FHA → monthly annual-MIP (always).
    The LTV comes from LP-77; the base loan + rates are overrideable; the FHA UFMIP rate is
    consumed from LP-84. Reads only.
    """
    program = loan_file.loan_program
    base_default = loan_file.note_amount or loan_file.loan_amount
    ltv_calc = await build_ltv_calculation(
        db, loan_file=loan_file, confidence_cutoff=confidence_cutoff
    )
    ltv_pct = ltv_calc.ltv
    overrides = await _active_mi_overrides(db, loan_file.id)

    base_line, base_val = _line(
        MI_BASE_LOAN_KEY, "Base loan amount", base_default, "stated", overrides
    )

    if program is LoanProgram.FHA:
        rate_line, rate_val = _line(
            MI_ANNUAL_MIP_RATE_KEY,
            "Annual MIP rate (bps)",
            FHA_ANNUAL_MIP_STARTER_BPS,
            "manual",
            overrides,
        )
        ufmip_bps = fha_ufmip_rate_bps()
        result = compute_fha_mip(
            base_loan_amount=base_val,
            ltv_pct=ltv_pct,
            upfront_rate_bps=ufmip_bps,
            annual_rate_bps=rate_val,
            duration_threshold_ltv=FHA_MIP_DURATION_LTV,
        )
        return MiComputation(result=result, inputs=[base_line, rate_line], ufmip_bps=ufmip_bps)

    rate_line, rate_val = _line(
        MI_PMI_RATE_KEY, "Annual PMI rate (bps)", PMI_STARTER_RATE_BPS, "manual", overrides
    )
    result = compute_conventional_pmi(
        base_loan_amount=base_val, ltv_pct=ltv_pct, annual_rate_bps=rate_val
    )
    return MiComputation(result=result, inputs=[base_line, rate_line], ufmip_bps=None)
