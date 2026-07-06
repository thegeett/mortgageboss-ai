"""Calculator response schemas (LP-87) — one transparent view for the four calculators.

The four LP-87 calculators (mortgage insurance, self-employed income, reserves, max loan)
reuse the LP-76/77 transparent/auto-populated/overrideable/findings-coupled shape. Rather
than four bespoke response models + four frontend components, they share ONE generic
:class:`CalculatorView`: a headline number, the overrideable input lines
(:class:`CalcLine` — auto/override/effective + source, exactly like the DTI/LTV line item),
the read-only derivation steps (:class:`CalcStep` — the transparent math, shown not hidden),
the formula(s), a methodology note (the grounded-starter marker), and the findings alert.
One shape → one frontend component renders all four.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class CalcLine(BaseModel):
    """One overrideable calculator input (auto/override/effective + provenance)."""

    key: str
    label: str
    auto_amount: Decimal | None  # auto-populated value (None if not derivable)
    override_amount: Decimal | None  # processor override (None if not set)
    amount: Decimal  # effective = override ?? auto ?? 0
    source: str  # "stated" / "computed" / "extracted" / "manual" / "override"
    overridden: bool


class CalcStep(BaseModel):
    """One read-only derivation line — the transparent math (a label + a formatted value)."""

    label: str
    value: str  # pre-formatted (money / months / percent / text) for the UI
    emphasis: bool = False  # the headline/total lines


class MethodologyNote(BaseModel):
    """The grounded-starter marker: is the calculation methodology domain-judgment?"""

    starter: bool
    text: str


class CalcFindings(BaseModel):
    """The unresolved-findings coupling (same as DTI/LTV)."""

    unresolved: bool
    open_in_scope_count: int


class CalculatorView(BaseModel):
    """The uniform transparent view for any LP-87 calculator."""

    calculator: str  # "mortgage_insurance" | "self_employed" | "reserves" | "max_loan"
    title: str
    headline: str | None  # the key number, pre-formatted (e.g. "$125.00 / mo")
    headline_label: str
    status: str | None  # "pass" / "over" / "required" / "not_required" / "sufficient" / ...
    program: str | None
    inputs: list[CalcLine]
    steps: list[CalcStep]
    formulas: list[str]
    methodology: MethodologyNote
    findings: CalcFindings


class CalcOverrideInput(BaseModel):
    """The override request body (an amount + an optional reason note)."""

    amount: Decimal = Field(ge=0)
    note: str | None = None
