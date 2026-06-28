"""The deterministic LTV calculation (LP-77) — pure arithmetic, no AI.

Where DTI answers "can the borrower afford the payment?", LTV answers "how much
equity is in the deal?" — the lender's risk exposure. Like DTI, the value is
doing it **transparently** and **correctly**; the two non-obvious subtleties are
the trust mechanism (and exactly what ChatGPT fumbles):

* **LTV uses the LESSER OF** purchase price and appraised value (for a purchase) —
  the lender will not lend against a price above the appraisal.
* **HCLTV uses the HELOC's CREDIT LIMIT, not its drawn balance** — a HELOC at $0
  today with a $100k line could be drawn tomorrow, so the most conservative
  measure counts the full line.

It is also **refinance-aware**: the loan purpose drives the denominator — a
purchase uses the lesser-of; a refinance (rate/term or cash-out) has no purchase
price and uses the appraised value.

This module is pure: it takes resolved numeric inputs and returns the three
ratios. ``Decimal`` throughout; ratios round half-up to two decimals.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

_CENTS = Decimal("0.01")


class LtvPurpose(StrEnum):
    """The purpose dimension that drives the LTV denominator + limit (LP-77)."""

    PURCHASE = "purchase"
    RATE_TERM_REFINANCE = "rate_term_refinance"
    CASH_OUT_REFINANCE = "cash_out_refinance"

    @property
    def is_refinance(self) -> bool:
        return self is not LtvPurpose.PURCHASE


# The formulas, shown verbatim in the UI (the transparency).
def ltv_formula(purpose: LtvPurpose) -> str:
    if purpose.is_refinance:
        return "LTV = first loan ÷ appraised value (refinance)"
    return "LTV = first loan ÷ lesser of (purchase price, appraised value)"


CLTV_FORMULA = "CLTV = (first loan + second loan + HELOC drawn balance) ÷ property value"
HCLTV_FORMULA = "HCLTV = (first loan + second loan + HELOC credit limit) ÷ property value"


def value_basis(
    purpose: LtvPurpose, purchase_price: Decimal | None, appraised_value: Decimal | None
) -> tuple[Decimal | None, str]:
    """The denominator + a human label, per the loan purpose.

    Purchase → the **lesser of** purchase price and appraised value (whichever are
    present). Refinance → the appraised value (no purchase price). Returns
    ``(None, label)`` when the inputs can't form a positive basis (the appraisal
    may not be extracted yet — the caller surfaces it as override-able).
    """
    if purpose.is_refinance:
        if appraised_value is not None and appraised_value > 0:
            return appraised_value, "appraised value"
        return None, "appraised value"

    candidates = [v for v in (purchase_price, appraised_value) if v is not None and v > 0]
    if not candidates:
        return None, "lesser of (purchase price, appraised value)"
    return min(candidates), "lesser of (purchase price, appraised value)"


@dataclass(frozen=True)
class LtvInputs:
    """The resolved numeric inputs (auto-populated values with overrides applied)."""

    first_loan: Decimal
    second_loan: Decimal  # a closed-end second lien's balance
    heloc_drawn: Decimal  # the HELOC's current drawn balance (counts in CLTV)
    heloc_limit: Decimal  # the HELOC's full credit line (counts in HCLTV)
    purchase_price: Decimal | None
    appraised_value: Decimal | None


@dataclass(frozen=True)
class LtvResult:
    """The computed LTV — the three ratios + the numerators + the value basis."""

    value_basis: Decimal | None
    value_basis_label: str
    ltv_pct: Decimal | None
    cltv_pct: Decimal | None
    hcltv_pct: Decimal | None
    cltv_numerator: Decimal  # first + second + HELOC drawn
    hcltv_numerator: Decimal  # first + second + HELOC credit limit


def _ratio(numerator: Decimal, basis: Decimal | None) -> Decimal | None:
    if basis is None or basis <= 0:
        return None
    return (numerator / basis * Decimal(100)).quantize(_CENTS, rounding=ROUND_HALF_UP)


def compute_ltv(inputs: LtvInputs, purpose: LtvPurpose) -> LtvResult:
    """Compute LTV / CLTV / HCLTV. Pure, deterministic, with the subtleties baked in.

    * LTV = first loan ÷ value basis (the **lesser-of** for a purchase).
    * CLTV = (first + second + HELOC **drawn balance**) ÷ value basis.
    * HCLTV = (first + second + HELOC **credit limit**) ÷ value basis — the most
      conservative measure (the full line, not the balance).
    """
    basis, label = value_basis(purpose, inputs.purchase_price, inputs.appraised_value)
    cltv_num = inputs.first_loan + inputs.second_loan + inputs.heloc_drawn
    hcltv_num = inputs.first_loan + inputs.second_loan + inputs.heloc_limit
    return LtvResult(
        value_basis=basis,
        value_basis_label=label,
        ltv_pct=_ratio(inputs.first_loan, basis),
        cltv_pct=_ratio(cltv_num, basis),
        hcltv_pct=_ratio(hcltv_num, basis),
        cltv_numerator=cltv_num,
        hcltv_numerator=hcltv_num,
    )
