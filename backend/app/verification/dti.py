"""The deterministic DTI calculation (LP-76) — pure arithmetic, no AI.

DTI (debt-to-income) is THE mortgage-qualification number. The calculation is
simple arithmetic; the *value* is **transparency** — every input is itemized and
the formula is explicit, so a processor can trust it (unlike a ChatGPT black
box). This module is the pure core: it computes the monthly principal+interest
from the loan terms and the two ratios from itemized lines. **No AI** — the AI's
role is upstream (extracting the values) and adjacent (findings that correct the
inputs); the math here is deterministic and correct by construction.

Money is ``Decimal`` throughout, never float; ratios round half-up to two
decimal places.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

# The formula, shown verbatim in the UI (the transparency — the feature).
FRONT_END_FORMULA = "Front-end DTI = housing payment ÷ gross monthly income"
BACK_END_FORMULA = "Back-end DTI = (housing payment + monthly debts) ÷ gross monthly income"

_CENTS = Decimal("0.01")


def monthly_principal_interest(
    principal: Decimal | None,
    annual_rate_percent: Decimal | None,
    term_months: int | None,
) -> Decimal | None:
    """The monthly principal+interest payment from the loan terms (amortization).

    Standard amortization: ``M = P*r(1+r)^n / ((1+r)^n - 1)`` where ``r`` is the
    monthly rate and ``n`` the term in months. A zero rate degrades to ``P/n``.
    Returns ``None`` if the inputs are insufficient (so the line is overridable
    rather than guessed). Not stored anywhere — always computed here.
    """
    if principal is None or term_months is None or term_months <= 0:
        return None
    if annual_rate_percent is None:
        return None
    if principal <= 0:
        return Decimal("0").quantize(_CENTS)

    monthly_rate = annual_rate_percent / Decimal(100) / Decimal(12)
    if monthly_rate == 0:
        return (principal / Decimal(term_months)).quantize(_CENTS, rounding=ROUND_HALF_UP)

    growth = (Decimal(1) + monthly_rate) ** term_months
    payment = principal * monthly_rate * growth / (growth - Decimal(1))
    return payment.quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class DtiLine:
    """One itemized line with its effective monthly amount (post-override)."""

    key: str
    label: str
    amount: Decimal


@dataclass(frozen=True)
class DtiResult:
    """The computed DTI — the totals + the two ratios. Pure output."""

    gross_monthly_income: Decimal
    housing_payment: Decimal
    monthly_debts: Decimal  # non-housing monthly obligations
    total_monthly_obligations: Decimal  # housing + debts (the back-end numerator)
    front_end_pct: Decimal | None
    back_end_pct: Decimal | None


def _ratio(numerator: Decimal, income: Decimal) -> Decimal | None:
    """A DTI percentage, or ``None`` when income is zero (undefined)."""
    if income <= 0:
        return None
    return (numerator / income * Decimal(100)).quantize(_CENTS, rounding=ROUND_HALF_UP)


def compute_dti(
    income_lines: Sequence[DtiLine],
    housing_lines: Sequence[DtiLine],
    debt_lines: Sequence[DtiLine],
) -> DtiResult:
    """Compute front-end + back-end DTI from itemized lines. Pure, deterministic.

    Front-end = housing ÷ income; back-end = (housing + other debts) ÷ income.
    The caller assembles the lines (auto-populated values with overrides applied);
    this just sums and divides.
    """
    income = sum((line.amount for line in income_lines), Decimal(0))
    housing = sum((line.amount for line in housing_lines), Decimal(0))
    debts = sum((line.amount for line in debt_lines), Decimal(0))
    total = housing + debts
    return DtiResult(
        gross_monthly_income=income,
        housing_payment=housing,
        monthly_debts=debts,
        total_monthly_obligations=total,
        front_end_pct=_ratio(housing, income),
        back_end_pct=_ratio(total, income),
    )
