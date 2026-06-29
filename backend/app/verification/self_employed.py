"""The deterministic self-employed-income calculation (LP-87) — transparent, no AI.

Self-employment income is THE high-value calculation a processor wants checked: it is
error-prone, methodology-heavy, and ChatGPT fumbles it. This computes QUALIFYING monthly
self-employment income TRANSPARENTLY — every add-back shown, the 2-year average derived
line by line — grounded in **Fannie Mae's Cash Flow Analysis (Form 1084)** methodology.

The METHODOLOGY is a grounded-starter (validate with Priya): the canonical pattern is
net profit PLUS non-cash / non-recurring add-backs (depreciation, depletion, amortization,
casualty loss, business-use-of-home) MINUS non-deductible items, then AVERAGED across the
two-year history (and a declining trend is a flag, not a silent average). The exact
add-back set + averaging vs most-recent-year judgment is domain expertise — the MECHANISM
(transparent, overrideable, deterministic) is real; the methodology is marked starter.

This module is pure: numeric inputs per year → a transparent :class:`SelfEmployedResult`
whose qualifying monthly figure FEEDS the DTI calculator's income side. ``Decimal``
throughout; money rounds half-up to cents.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_CENTS = Decimal("0.01")

QUALIFYING_INCOME_FORMULA = (
    "Qualifying monthly income = (Σ per-year adjusted income ÷ number of years) ÷ 12"
)
ADJUSTED_YEAR_FORMULA = "Adjusted year income = net profit + add-backs (depreciation, depletion, …)"

# The Form-1084-style add-back keys (non-cash / non-recurring items added back to net profit).
ADD_BACK_KEYS: tuple[str, ...] = (
    "depreciation",
    "depletion",
    "amortization_casualty",
    "business_use_of_home",
)


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class SelfEmployedYear:
    """One tax year's inputs — net profit + the add-backs (each a transparent line)."""

    year: int
    net_profit: Decimal
    add_backs: dict[str, Decimal]  # keyed by ADD_BACK_KEYS

    @property
    def add_back_total(self) -> Decimal:
        return sum(self.add_backs.values(), Decimal(0))

    @property
    def adjusted(self) -> Decimal:
        return self.net_profit + self.add_back_total


@dataclass(frozen=True)
class SelfEmployedResult:
    """The computed qualifying self-employment income — transparent. Pure output."""

    years: tuple[SelfEmployedYear, ...]
    annual_adjusted_total: Decimal  # Σ adjusted across years
    year_count: int
    average_annual: Decimal | None  # the 2-year (or n-year) average
    qualifying_monthly: Decimal | None  # the figure that feeds DTI
    declining: bool  # most-recent year < prior year → a flag (income may not be usable as-is)


def compute_self_employed_income(years: Sequence[SelfEmployedYear]) -> SelfEmployedResult:
    """Average the per-year adjusted income → qualifying monthly. Pure, deterministic.

    Each year's adjusted income = net profit + the non-cash add-backs (shown). The
    qualifying monthly figure is the multi-year average ÷ 12. A declining trend
    (most-recent < prior) is flagged — it does NOT silently lower the average; the human
    decides whether to use the lower most-recent year (domain judgment).
    """
    ordered = tuple(sorted(years, key=lambda y: y.year))
    year_count = len(ordered)
    if year_count == 0:
        return SelfEmployedResult(
            years=(),
            annual_adjusted_total=Decimal(0),
            year_count=0,
            average_annual=None,
            qualifying_monthly=None,
            declining=False,
        )
    total = sum((y.adjusted for y in ordered), Decimal(0))
    average = _money(total / Decimal(year_count))
    qualifying = _money(average / Decimal(12))
    declining = year_count >= 2 and ordered[-1].adjusted < ordered[-2].adjusted
    return SelfEmployedResult(
        years=ordered,
        annual_adjusted_total=_money(total),
        year_count=year_count,
        average_annual=average,
        qualifying_monthly=qualifying,
        declining=declining,
    )
