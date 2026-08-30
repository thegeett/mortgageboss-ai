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

from app.services.finding_blocking import FindingBreakdown


class CalcLine(BaseModel):
    """One overrideable calculator input (auto/override/effective + provenance)."""

    key: str
    label: str
    auto_amount: Decimal | None  # auto-populated value (None if not derivable)
    override_amount: Decimal | None  # processor override (None if not set)
    amount: Decimal  # effective = override ?? auto ?? 0
    source: str  # "stated" / "computed" / "extracted" / "manual" / "override"
    overridden: bool
    #: Who set the override and why (LP-UI-021). Both `None` when the line is not
    #: overridden; `override_by` alone may be `None` for an override with no
    #: recorded actor, which is different from one nobody has looked at.
    override_by: str | None = None
    override_note: str | None = None
    # LP-568 — a line SHOWN in the breakdown but not summed into the totals. Only the DTI
    # back-end sets it today (an obligation that does not survive closing); it lives on the
    # shared line shape so the snapshot mapper's protocol holds for every calculator.
    excluded: bool = False
    excluded_reason: str | None = None


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
    #: The same findings split by the system that produced them, so the count is
    #: reconcilable with the verification screen rather than one merged figure.
    breakdown: FindingBreakdown = FindingBreakdown()


class CalculatorView(BaseModel):
    """The uniform transparent view for any LP-87 calculator."""

    calculator: str  # "mortgage_insurance" | "self_employed" | "reserves" | "max_loan"
    title: str
    # Did the calculator produce its result? False when a required input was missing
    # (e.g. reserves with no PITI divisor → months not computable). The structured
    # not-computed signal, so readers never have to string-match the ``headline``
    # placeholder. Defaults True — most views always produce a result.
    computed: bool = True
    headline: str | None  # the key number, pre-formatted (e.g. "$125.00 / mo")
    headline_label: str
    status: str | None  # "pass" / "over" / "required" / "not_required" / "sufficient" / ...
    program: str | None
    # LP-498 review — the STRUCTURED reserve months, for the same reason ``computed`` is structured:
    # a rule must never read a number out of ``headline``. AS-4 declares
    # ``months_available: {calc: [reserves, months_available]}``, and ``map_reserves`` had no such key
    # to project — it emitted headline/status/program only, so the operand resolved to None and AS-4
    # ``couldnt_check``ed on every real file while its tests hand-built the key. None on a view that
    # did not compute (no PITI divisor) or whose requirement is unknown.
    months_available: Decimal | None = None
    months_required: Decimal | None = None
    inputs: list[CalcLine]
    steps: list[CalcStep]
    formulas: list[str]
    methodology: MethodologyNote
    findings: CalcFindings


class CalcOverrideInput(BaseModel):
    """The override request body (an amount + an optional reason note)."""

    amount: Decimal = Field(ge=0)
    note: str | None = None
