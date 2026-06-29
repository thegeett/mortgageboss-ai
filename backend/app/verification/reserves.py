"""The deterministic reserves calculation (LP-87) — transparent, no AI.

Reserves answer "after closing, how many months of the mortgage payment can the borrower
cover from liquid assets?" — a key risk + compensating-factor input. The calculation is
transparent (every asset source shown) and applies the program-specific treatment:

* **Eligible assets** = liquid funds remaining after the down payment + closing costs.
  Gifts and borrowed funds are EXCLUDED from reserves; vested retirement balances count at
  a haircut — for FHA, the **60% retirement haircut** from LP-84 (passed in by the service).
* **Months of reserves** = eligible assets ÷ the monthly housing payment (PITI).
* **Available vs required:** the required months are DU / program / property / overlay-DRIVEN
  (threshold-as-data, marked starter) — passed in by the service from the asset rules.

Pure: numeric inputs → a transparent :class:`ReservesResult`. ``Decimal`` throughout.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_CENTS = Decimal("0.01")
_TENTH = Decimal("0.1")

ELIGIBLE_FORMULA = (
    "Eligible reserves = liquid assets + (vested retirement x retirement factor) "
    "- down payment - closing costs (gifts/borrowed excluded)"
)
MONTHS_FORMULA = "Months of reserves = eligible reserves ÷ monthly housing payment (PITI)"


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ReservesResult:
    """The computed reserves — eligible funds + months, available vs required. Pure output."""

    liquid_assets: Decimal
    retirement_assets: Decimal
    retirement_factor: Decimal  # 1.00 conventional, 0.60 FHA (the LP-84 haircut)
    retirement_counted: Decimal  # retirement_assets x factor
    excluded_funds: Decimal  # gifts / borrowed (shown, then excluded)
    down_payment: Decimal
    closing_costs: Decimal
    eligible_reserves: Decimal  # the funds available for reserves (never negative)
    monthly_housing_payment: Decimal | None  # PITI (the divisor)
    months_available: Decimal | None
    months_required: Decimal | None  # program/DU/overlay-driven (starter)
    sufficient: bool | None  # available ≥ required (None when required unknown)


def compute_reserves(
    *,
    liquid_assets: Decimal,
    retirement_assets: Decimal,
    retirement_factor: Decimal,
    excluded_funds: Decimal,
    down_payment: Decimal,
    closing_costs: Decimal,
    monthly_housing_payment: Decimal | None,
    months_required: Decimal | None,
) -> ReservesResult:
    """Eligible reserves → months available, compared to required. Pure, deterministic."""
    retirement_counted = _money(retirement_assets * retirement_factor)
    eligible_raw = liquid_assets + retirement_counted - down_payment - closing_costs
    eligible = _money(max(eligible_raw, Decimal(0)))  # reserves never go negative

    months_available: Decimal | None = None
    if monthly_housing_payment is not None and monthly_housing_payment > 0:
        months_available = (eligible / monthly_housing_payment).quantize(
            _TENTH, rounding=ROUND_HALF_UP
        )

    sufficient: bool | None = None
    if months_available is not None and months_required is not None:
        sufficient = months_available >= months_required

    return ReservesResult(
        liquid_assets=liquid_assets,
        retirement_assets=retirement_assets,
        retirement_factor=retirement_factor,
        retirement_counted=retirement_counted,
        excluded_funds=excluded_funds,
        down_payment=down_payment,
        closing_costs=closing_costs,
        eligible_reserves=eligible,
        monthly_housing_payment=monthly_housing_payment,
        months_available=months_available,
        months_required=months_required,
        sufficient=sufficient,
    )
