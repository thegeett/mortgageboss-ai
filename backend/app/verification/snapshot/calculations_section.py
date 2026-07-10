"""Calculations section assembler (LP-207, ADR-244).

Calls the four existing calculators (DTI / LTV / MI / reserves) and maps each
native return shape into LP-204's uniform ``CalculationEntry {value, breakdown}``.
It **computes nothing** — the calculators are the single source of truth; this is a
pure invoke + map, preserving each breakdown line's own source tag verbatim.

* **Source tags pass through, never re-derived.** A line the calculator tagged
  ``stated`` / ``extracted`` / ``computed`` / ``manual`` / ``override`` keeps that
  tag. (``CalcBreakdownLine.source`` is a free string, so the calculator's
  ``override`` tag — a 5th value — survives losslessly; no enum coercion.)
* **Not-computed = ``None``, never a fabricated 0.0.** When a calculator can't
  produce its headline (DTI has no income → ratio ``None``; LTV has no value basis
  → ratio ``None``; reserves has no PITI divisor → ``months_available`` ``None``),
  that calculation is ``None`` (LP-204: ``CalculationEntry | None``). MI always
  determines ``required`` (a "not required" answer is computed, not missing), so it
  is always present.
* **Money is stringified exactly** (LP-204's ``value`` rejects raw ``Decimal`` to
  avoid a silent float; breakdown ``amount`` is likewise a string).
* **DTI uses STATED (MISMO) income by construction** — surfaced faithfully with the
  income line tagged ``stated``. Reconciling stated-vs-extracted income is a
  downstream finding, not this assembler's job; the source tag makes the input
  transparent.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.loan_file import LoanFile
from app.schemas.calculators import CalculatorView
from app.schemas.dti import DtiCalculation
from app.schemas.ltv import LtvCalculation
from app.services.calculators import build_reserves_view
from app.services.dti import build_dti_calculation
from app.services.ltv import build_ltv_calculation
from app.services.mi import MiComputation, compute_loan_mi
from app.verification.confidence import DEFAULT_CONFIDENCE_CUTOFF
from app.verification.snapshot.model import (
    CalcBreakdownLine,
    CalculationEntry,
    CalculationsSection,
)


class _CalcLineItem(Protocol):
    """The shape every calculator's line item shares (DtiLineItem / LtvLineItem / CalcLine)."""

    key: str
    label: str
    amount: Decimal
    source: str
    overridden: bool


def _money(value: Decimal | None) -> str | None:
    """Serialize a Decimal amount as an exact string (None stays None)."""
    return None if value is None else str(value)


def _line(item: _CalcLineItem) -> CalcBreakdownLine:
    """Map one calculator line item, passing its source tag through verbatim."""
    return CalcBreakdownLine(
        key=item.key,
        label=item.label,
        amount=_money(item.amount),
        source=item.source,  # verbatim — never re-derived
        overridden=item.overridden,
    )


def map_dti(dti: DtiCalculation) -> CalculationEntry | None:
    """DTI → CalculationEntry, or None when the back-end ratio isn't computable."""
    if dti.back_end_dti is None:  # no income → the ratio can't be computed
        return None
    return CalculationEntry(
        value={
            "front_end_dti": _money(dti.front_end_dti),
            "back_end_dti": _money(dti.back_end_dti),
            "gross_monthly_income": _money(dti.gross_monthly_income),
            "housing_payment": _money(dti.housing_payment),
            "monthly_debts": _money(dti.monthly_debts),
            "total_monthly_obligations": _money(dti.total_monthly_obligations),
        },
        breakdown=[_line(i) for i in (*dti.income_items, *dti.housing_items, *dti.debt_items)],
    )


def map_ltv(ltv: LtvCalculation) -> CalculationEntry | None:
    """LTV → CalculationEntry, or None when there is no value basis (ratio None)."""
    if ltv.ltv is None:  # no appraised/purchase value basis → ratio not computable
        return None
    return CalculationEntry(
        value={
            "ltv": _money(ltv.ltv),
            "cltv": _money(ltv.cltv),
            "hcltv": _money(ltv.hcltv),
            "value_basis": _money(ltv.value_basis),
            "value_basis_label": ltv.value_basis_label,
            "appraised_value_source": ltv.appraised_value_source,
            "purpose": ltv.purpose,
            "program": ltv.program,
        },
        breakdown=[_line(i) for i in (*ltv.loan_items, *ltv.value_items)],
    )


def map_mi(mi: MiComputation) -> CalculationEntry:
    """MI → CalculationEntry (always present — ``required`` is always determined)."""
    result = mi.result
    return CalculationEntry(
        value={
            "program": result.program,
            "required": result.required,
            "monthly_premium": _money(result.monthly_premium),
            "annual_rate_bps": _money(result.annual_rate_bps),
            "upfront_premium": _money(result.upfront_premium),
            "cancel_ltv": _money(result.cancel_ltv),
            "duration_label": result.duration_label,
        },
        breakdown=[_line(i) for i in mi.inputs],
    )


def map_reserves(view: CalculatorView) -> CalculationEntry | None:
    """Reserves ``CalculatorView`` → CalculationEntry, or None when not computable.

    Branches on the calculator's structured ``computed`` flag (False when there is no
    PITI divisor → months not computable) — NOT on the ``headline`` display placeholder,
    so a change to that presentation string can't turn a not-computed reserves into a
    fabricated present entry.
    """
    if not view.computed:
        return None
    return CalculationEntry(
        value={
            "headline": view.headline,
            "status": view.status,
            "program": view.program,
        },
        breakdown=[_line(i) for i in view.inputs],
    )


async def build_calculations_section(db: AsyncSession, loan_file: LoanFile) -> CalculationsSection:
    """Invoke the four calculators and map each result (or None) into the section.

    Pure invoke + map — no calculation math is reimplemented here.
    """
    cutoff = DEFAULT_CONFIDENCE_CUTOFF
    dti = await build_dti_calculation(db, loan_file=loan_file, confidence_cutoff=cutoff)
    ltv = await build_ltv_calculation(db, loan_file=loan_file, confidence_cutoff=cutoff)
    mi = await compute_loan_mi(db, loan_file=loan_file, confidence_cutoff=cutoff)
    reserves = await build_reserves_view(db, loan_file=loan_file, cutoff=cutoff)

    return CalculationsSection.present(
        dti=map_dti(dti),
        ltv=map_ltv(ltv),
        mi=map_mi(mi),
        reserves=map_reserves(reserves),
    )
