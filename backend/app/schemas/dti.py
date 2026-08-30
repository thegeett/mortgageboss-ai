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

from app.services.finding_blocking import FindingBreakdown


class DtiLineItem(BaseModel):
    """One itemized input line — auto value, override (if any), and the effective."""

    key: str  # stable field_key (income.<id> / debt.<id> / housing.<component>)
    label: str
    auto_amount: Decimal | None  # the auto-populated value (None if not derivable)
    override_amount: Decimal | None  # the processor override, if set
    amount: Decimal  # the effective value used in the math (override ?? auto ?? 0)
    source: str  # stated / computed / extracted / manual / override
    overridden: bool
    #: Who set the override and why (LP-UI-021). Both `None` when the line is not
    #: overridden; `override_by` alone may be `None` for an override with no
    #: recorded actor, which is different from one nobody has looked at.
    override_by: str | None = None
    override_note: str | None = None
    # LP-375: a REQUIRED input (taxes/insurance) that could NOT be derived and was NOT overridden — i.e.
    # its ``amount`` of 0 is a FAIL-CLOSED placeholder, NOT an extracted $0.00 (absent≠0). The display must
    # render this as "unknown", never "$0.00 Extracted". False for a legitimately-zero input (HOA/MI).
    unknown: bool = False
    # LP-568: shown in the breakdown but NOT summed into monthly_debts — an obligation that does
    # not survive closing (a refinanced mortgage, a departing residence, a debt cleared to
    # qualify). Distinct from ``unknown``: the amount is known, it just stops existing. The
    # display must render it struck-through with the reason, never omit the row.
    excluded: bool = False
    excluded_reason: str | None = None
    # LP-621 review — the arithmetic behind a COMPUTED line, carried with it. The net rental figure is
    # the first line whose amount a processor cannot check by reading a document: it is 75% of a gross
    # rent, less a PITIA that is itself a sum of five other lines. `rental_treatment` composed exactly
    # that sentence and nothing consumed it, so the ticket's promise that the processor would see the
    # working was computed and thrown away. None for every line whose label already explains it.
    derivation: str | None = None


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
    #: The same findings split by the system that produced them (LP-UI-021), so
    #: the alert's number reconciles with the verification screen instead of
    #: merging three generators into one figure a processor cannot place.
    breakdown: FindingBreakdown = FindingBreakdown()


class UnverifiedInput(BaseModel):
    """A figure the FILE STATES for a gated DTI input, which is not acceptable verification.

    bug-001. A real submission gated on "Property taxes is unknown" while two of its documents stated
    the annual tax outright ($5,579). Both were automated valuations over county assessor data, so
    GATING IS RIGHT — an estimator's figure must not silently set a DTI. But a processor told the
    number is missing goes looking, finds it twice, and concludes the system cannot read its own file.

    STRUCTURED, not just prose, so the card can offer it as a one-click override: `field_key` and
    `monthly_amount` are exactly what `DtiOverrideInput` needs. Accepting it is then a DECISION on the
    record — an override carrying the processor's id and a note naming the source — rather than an
    estimate the calculator promoted quietly.

    `sentence` is the same text both gate-reason producers render, carried here so the card, the /dti
    reason and the snapshot's reason cannot word it differently.
    """

    model_config = {"frozen": True}

    field_key: str  # the override target, e.g. "housing.taxes"
    label: str  # "Property taxes"
    monthly_amount: Decimal  # what an override would set
    annual_amount: Decimal  # what the document actually states
    source_label: str  # "the home value estimate"
    sentence: str  # the prose both gate reasons use


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
    #: bug-001 — a figure the FILE STATES for a gated input, which is not acceptable verification.
    #:
    #: A real submission gated on "Property taxes is unknown" while two documents in it stated the
    #: annual tax outright ($5,579, on a UWM dashboard and a Property Explorer report). Both are
    #: automated-valuation output over county assessor data, so GATING IS RIGHT — an estimator's
    #: figure must not set a DTI. But a processor told the number is missing goes looking and finds
    #: it twice, and concludes the system is broken when it is being careful.
    #:
    #: Carried STRUCTURALLY rather than folded into `gate_reason` by each producer, because there are
    #: two gate-reason producers (this card's, and the snapshot's in `calculations_section`, which is
    #: what the AI cross-check reads) and they would otherwise drift.
    unverified_inputs: tuple[UnverifiedInput, ...] = ()

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
