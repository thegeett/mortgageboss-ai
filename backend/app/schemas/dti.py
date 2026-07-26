"""DTI calculator schemas (LP-76) — the transparent, itemized response.

The response carries the *full breakdown* (every income / housing / debt line,
each with its auto-populated value and any override), the two ratios, the
explicit formula, and the effective program limit side-by-side — the
transparency that makes the DTI trustworthy. Money is serialized as ``Decimal``
(strings over the wire); no PII (no SSNs) is included.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class DtiLineItem(BaseModel):
    """One itemized input line — auto value, override (if any), and the effective."""

    key: str  # stable field_key (income.<id> / debt.<id> / housing.<component>)
    label: str
    auto_amount: Decimal | None  # the auto-populated value (None if not derivable)
    override_amount: Decimal | None  # the processor override, if set
    amount: Decimal  # the effective value used in the math (override ?? auto ?? 0)
    source: str  # stated / computed / extracted / manual / override
    overridden: bool
    # LP-375: a REQUIRED input (taxes/insurance) that could NOT be derived and was NOT overridden — i.e.
    # its ``amount`` of 0 is a FAIL-CLOSED placeholder, NOT an extracted $0.00 (absent≠0). The display must
    # render this as "unknown", never "$0.00 Extracted". False for a legitimately-zero input (HOA/MI).
    unknown: bool = False


class DtiLimit(BaseModel):
    """The effective program limit shown side-by-side with the computed DTI."""

    back_end_max: Decimal | None  # the effective back-end cap (percent)
    source: str  # "program_default" / "overlay" / "unknown"
    lender_slug: str | None  # set when an overlay tightened the limit
    rule_id: str | None
    status: str  # "pass" / "over" / "unknown" (back-end vs the cap)


class DtiFindingsStatus(BaseModel):
    """The findings coupling — the unresolved-findings alert (LP-75)."""

    unresolved: bool  # any open in-scope finding → the calc may be incomplete
    open_in_scope_count: int


class DtiCalculation(BaseModel):
    """The full DTI calculation for a loan file — transparent + itemized."""

    # The headline ratios (percent, 2 dp; None when income is zero OR the calc is GATED).
    front_end_dti: Decimal | None
    back_end_dti: Decimal | None

    # LP-375 — fail-closed GATING, catching the DISPLAY path up to the snapshot path (calculations_section):
    # when a REQUIRED housing input (taxes/insurance) is unknown, the ratios are NULLED (not a confident
    # number resting on a fabricated 0) and ``gate_reason`` names the unknown input(s). The snapshot path
    # already did this; the display path used to collapse the absent input to 0 and show a confident ratio.
    gated: bool = False
    gate_reason: str | None = None

    # The totals.
    gross_monthly_income: Decimal
    housing_payment: Decimal
    monthly_debts: Decimal
    total_monthly_obligations: Decimal

    # The full itemized breakdown (the transparency).
    income_items: list[DtiLineItem]
    housing_items: list[DtiLineItem]
    debt_items: list[DtiLineItem]

    # The formulas, shown explicitly.
    front_end_formula: str
    back_end_formula: str

    # The program + the effective limit side-by-side.
    program: str | None
    limit: DtiLimit

    # The findings coupling.
    findings: DtiFindingsStatus


class DtiOverrideInput(BaseModel):
    """A processor override of one DTI input field."""

    amount: Decimal = Field(ge=0)
    note: str | None = None
