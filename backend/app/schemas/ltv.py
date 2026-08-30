"""LTV calculator schemas (LP-77) — the transparent, itemized response.

Mirrors the DTI calculator's shape (LP-76), applied to the three LTV ratios. The
response carries the loan inputs and the property values itemized (the
**lesser-of** made visible), the three ratios, the explicit formulas, and the
effective limit (which varies by loan purpose) side-by-side. Money serialized as
``Decimal`` strings; no PII.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from app.services.finding_blocking import FindingBreakdown


class LtvLineItem(BaseModel):
    """One itemized input line — auto value, override (if any), and the effective."""

    key: str
    label: str
    auto_amount: Decimal | None
    override_amount: Decimal | None
    amount: Decimal
    source: str  # stated / computed / extracted / manual / override
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


class LtvLimit(BaseModel):
    """The effective LTV limit (varies by loan purpose) shown side-by-side."""

    ltv_max: Decimal | None
    source: str  # "program_default" / "overlay" / "unknown"
    lender_slug: str | None
    rule_id: str | None
    purpose_basis: str  # which limit applies (purchase / cash_out)
    status: str  # "pass" / "over" / "unknown" (LTV vs the cap)


class LtvFindingsStatus(BaseModel):
    """The findings coupling — the unresolved-findings alert (LP-75)."""

    unresolved: bool
    open_in_scope_count: int
    #: The same findings split by the system that produced them (LP-UI-021), so
    #: the alert's number reconciles with the verification screen instead of
    #: merging three generators into one figure a processor cannot place.
    breakdown: FindingBreakdown = FindingBreakdown()


class LtvCalculation(BaseModel):
    """The full LTV calculation for a loan file — transparent + itemized."""

    # The three ratios (percent, 2 dp; None when the value basis is unknown). These are the
    # EXACT figures — what the arithmetic produced, for display and for a FRACTIONAL cap
    # comparison (see `limit`, whose FHA purchase cap is 96.5%). LP-496 / ADR-383.
    ltv: Decimal | None
    cltv: Decimal | None
    hcltv: Decimal | None

    # LP-496 — the DELIVERED ratios per Fannie Mae Selling Guide B2-1.2-01 (06/01/2022):
    # truncated to two decimal places, then rounded up to the nearest whole percent. Shown
    # ALONGSIDE the exact figure so `80.95% -> 81%` stays visible and checkable, and consumed
    # by the whole-percent ELIGIBILITY thresholds (MI-1's 80%, the FHA MIP duration's 90%).
    # Deliberately NOT used for `limit`, which compares against program caps of mixed
    # authority — one of them fractional. See ADR-383.
    ltv_delivered: Decimal | None
    cltv_delivered: Decimal | None
    hcltv_delivered: Decimal | None

    # The denominator made visible (the lesser-of / appraised value).
    value_basis: Decimal | None
    value_basis_label: str
    # Which subject-property field the appraised-value basis was auto-populated from
    # (LP-90 transparency): "valuation_amount" (the MISMO valuation — the priority field)
    # or "estimated_value" (the fallback when valuation_amount is null), else None. The
    # logic is ``appraised = valuation_amount or estimated_value``.
    appraised_value_source: str | None

    # The itemized inputs.
    loan_items: list[LtvLineItem]  # first / second / HELOC drawn / HELOC limit
    value_items: list[LtvLineItem]  # purchase price / appraised value

    # The formulas, shown explicitly (LTV's is purpose-aware).
    ltv_formula: str
    cltv_formula: str
    hcltv_formula: str

    # The loan purpose + the program + the effective limit.
    purpose: str  # purchase / rate_term_refinance / cash_out_refinance
    program: str | None
    limit: LtvLimit

    findings: LtvFindingsStatus


class LtvOverrideInput(BaseModel):
    """A processor override of one LTV input field."""

    amount: Decimal = Field(ge=0)
    note: str | None = None
