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
ratios — each in TWO forms (LP-496, see below). ``Decimal`` throughout.

TWO ROUNDINGS, AND THE SPLIT IS DELIBERATE (LP-496 / ADR-383).

Fannie Mae Selling Guide **B2-1.2-01** (page dated 06/01/2022) requires the ratio a lender
DELIVERS to be *"truncated (shortened) to two decimal places, then rounded up to the nearest
whole percent"*, and adds that *"lenders' systems must contain rounding methodology that
results in the same or a higher LTV ratio."* Its own worked examples are
**94.01% -> 95%** and **80.001% -> 80%** — the second is the one that surprises: truncation
discards the ``.001``, leaving exactly ``80.00``, which is already whole, so the round-up
moves nothing.

The same page states *"The rounding rules noted above **also apply to the CLTV and HCLTV**
ratio calculations."* (B2-1.2-02, 12/04/2018, and B2-1.2-03, 02/23/2016, state their formulas
and are silent on rounding.) So ONE rounding rule covers all three ratios — which is why the
shared ``_ratio`` / ``_delivered`` helpers are correct rather than an over-generalisation.

BUT A SINGLE ROUNDED VALUE CANNOT SERVE EVERY CONSUMER, and that is the whole reason this
module returns both. The delivered whole percent is right for a Fannie ELIGIBILITY threshold
(MI-1's "MI required above 80%", the FHA MIP duration's 90%). It is WRONG for a program cap
that is itself fractional: ``fha.ltv.purchase_max`` is **96.5%**, and rounding 96.01 up to 97
before comparing it to 96.5 turns a passing FHA purchase into a failing one. 96.5% is FHA's
actual maximum, so that is exactly where real FHA purchase files sit.

So: ``*_pct`` is the EXACT two-decimal figure (display, and any fractional-cap comparison);
``*_pct_delivered`` is the guideline whole percent (eligibility thresholds, and the value a
rule reports). Both are computed HERE, once — never re-rounded at a call site, which is the
inconsistency LP-496 exists to remove.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP, Decimal
from enum import StrEnum

_CENTS = Decimal("0.01")
_WHOLE = Decimal("1")


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
    """The computed LTV — the three ratios (in BOTH forms) + the numerators + the value basis.

    ``*_pct`` is the EXACT two-decimal figure. ``*_pct_delivered`` is B2-1.2-01's whole
    percent. See the module docstring for which consumer takes which, and why one value
    cannot serve both (ADR-383).
    """

    value_basis: Decimal | None
    value_basis_label: str
    ltv_pct: Decimal | None
    cltv_pct: Decimal | None
    hcltv_pct: Decimal | None
    # LP-496 — the DELIVERED ratios (B2-1.2-01): truncated to two decimals, then rounded up
    # to the nearest whole percent. ``None`` exactly when the matching ``*_pct`` is None.
    ltv_pct_delivered: Decimal | None
    cltv_pct_delivered: Decimal | None
    hcltv_pct_delivered: Decimal | None
    cltv_numerator: Decimal  # first + second + HELOC drawn
    hcltv_numerator: Decimal  # first + second + HELOC credit limit


def _raw_ratio(numerator: Decimal, basis: Decimal | None) -> Decimal | None:
    """The UNROUNDED quotient as a percent — "the result of these calculations".

    Both roundings are taken from THIS value. B2-1.2-01 says to truncate "the result of these
    calculations", which is the quotient itself, not a figure already rounded to two decimals.
    Deriving the delivered percent from the half-up figure instead would turn a raw 80.005 into
    80.01 -> 81, where truncating the quotient gives 80.00 -> 80.
    """
    if basis is None or basis <= 0:
        return None
    return numerator / basis * Decimal(100)


def _ratio(numerator: Decimal, basis: Decimal | None) -> Decimal | None:
    """The EXACT ratio, to two decimal places (half-up).

    This is the DISPLAY / fractional-cap figure, NOT the delivered one — see
    :func:`delivered_percent` and the module docstring. It is deliberately unchanged by
    LP-496: the defect was never that this value existed, it was that it was the ONLY value
    and was therefore used where B2-1.2-01's whole percent was required.
    """
    raw = _raw_ratio(numerator, basis)
    return None if raw is None else raw.quantize(_CENTS, rounding=ROUND_HALF_UP)


def delivered_percent(raw_pct: Decimal | None) -> Decimal | None:
    """B2-1.2-01's DELIVERED ratio: truncate to two decimals, then round up to a whole percent.

    TWO OPERATIONS, IN ORDER, AND THE ORDER IS THE WHOLE POINT. Truncation is not "round
    down at the second decimal"; it DISCARDS everything past two decimals. Only then is the
    ceiling of the whole percent taken. That is why the guide's own second example holds:
    ``80.001`` truncates to ``80.00``, which is already a whole percent, so it is delivered as
    **80** — not 81.

    Verified against both examples the guide prints: ``94.01 -> 95`` and ``80.001 -> 80``.

    Takes the RAW quotient, not the half-up two-decimal figure. Feeding it the rounded value
    would apply half-up before the truncation and deliver a raw 80.005 as 81 instead of 80 —
    a second rounding smuggled in ahead of the one the guide specifies.
    """
    if raw_pct is None:
        return None
    truncated = raw_pct.quantize(_CENTS, rounding=ROUND_DOWN)
    return truncated.quantize(_WHOLE, rounding=ROUND_CEILING)


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
    # Both roundings are taken from the SAME raw quotient — see _raw_ratio.
    ltv_raw = _raw_ratio(inputs.first_loan, basis)
    cltv_raw = _raw_ratio(cltv_num, basis)
    hcltv_raw = _raw_ratio(hcltv_num, basis)
    return LtvResult(
        value_basis=basis,
        value_basis_label=label,
        ltv_pct=_ratio(inputs.first_loan, basis),
        cltv_pct=_ratio(cltv_num, basis),
        hcltv_pct=_ratio(hcltv_num, basis),
        # LP-496 — computed ONCE, here. A caller that needs the delivered percent reads it
        # rather than re-rounding the exact figure itself; rounding applied inconsistently
        # across call sites is the defect this ticket removes.
        ltv_pct_delivered=delivered_percent(ltv_raw),
        cltv_pct_delivered=delivered_percent(cltv_raw),
        hcltv_pct_delivered=delivered_percent(hcltv_raw),
        cltv_numerator=cltv_num,
        hcltv_numerator=hcltv_num,
    )
