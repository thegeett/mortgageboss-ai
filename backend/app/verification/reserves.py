"""The deterministic reserves calculation (LP-87) — transparent, no AI.

Reserves answer "after closing, how many months of the mortgage payment can the borrower
cover from liquid assets?" — a key risk + compensating-factor input. The calculation is
transparent (every asset source shown) and applies the program-specific treatment:

* **Eligible assets** = liquid funds remaining after the down payment + closing costs.
  Gifts and borrowed funds are EXCLUDED from reserves; vested retirement balances count at
  a haircut — for FHA, the **60% retirement haircut** from LP-84 (passed in by the service).
* **Months of reserves** = eligible assets ÷ the monthly housing payment (PITI).
* **Available vs required:** the required months come from :func:`required_reserve_months` — Fannie
  B3-4.1-01's occupancy x unit-count matrix — unless a lender overlay sets a higher figure. That
  function lives here so the reserves WORKSHEET and rule AS-4 read one source; they previously did
  not, and disagreed on the same file (LP-498 review).

Pure: numeric inputs → a transparent :class:`ReservesResult`. ``Decimal`` throughout.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_CENTS = Decimal("0.01")
_TENTH = Decimal("0.1")

# --------------------------------------------------------------------------- #
# The B3-4.1-01 minimum-reserve matrix — ONE source for both surfaces.
#
# LP-498 review — the calculator worksheet and AS-4 answered the same question with different numbers.
# `_resolve_required_reserve_months` returned a lender-registry value or an unsourced starter of 2
# months; AS-4's `reserves.required_months` recipe read this matrix. On an investment property with 3.0
# months available the worksheet said "3.0 months, sufficient" (starter 2) while AS-4 fired "6 months
# required, the file lacks adequate reserves" — two surfaces of one product contradicting each other on
# one file. Activating AS-4 is what made it visible; the divergence pre-dates it.
#
# The matrix is the researched side (tier P, read from Fannie's own page), so it is what both now read.
# A lender OVERLAY still wins where one is registered — an overlay is a real, sourced requirement; the
# starter 2 was not.
# --------------------------------------------------------------------------- #
_RESERVE_MONTHS_ONE_UNIT_PRIMARY = Decimal("0")
_RESERVE_MONTHS_SECOND_HOME = Decimal("2")
_RESERVE_MONTHS_MULTI_UNIT_PRIMARY = Decimal("6")
_RESERVE_MONTHS_INVESTMENT = Decimal("6")
MAX_RESIDENTIAL_UNITS = 4

_GUIDE = "Fannie B3-4.1-01, page dated 08/07/2024"


def required_reserve_months(
    occupancy: str | None, financed_unit_count: str | None
) -> tuple[Decimal | None, str]:
    """The reserve requirement in months of PITIA, per B3-4.1-01 — ``(months, reason)``.

    ``months is None`` means ABSTAIN, and the reason says why. Every abstain is deliberate: a guessed
    requirement is a silent, permanent error, and for the principal-residence cell the guess is between
    0 and 6 months — the difference between clearing a file and catching it.

    WHAT THIS DOES NOT MODEL, stated because a `satisfied` built on it means less than it appears to:
    B3-4.1-01 also requires reserves of 2% / 4% / 6% of the aggregate UPB when the borrower owns 1-4 /
    5-6 / 7-10 financed properties, and 6 months for a cash-out refinance with DTI over 45%. Neither
    the financed-property count nor the aggregate UPB reaches the snapshot, so neither overlay is
    applied here. Both can only RAISE the requirement, so this figure is a FLOOR.
    """
    if occupancy is None:
        return None, "occupancy is unknown — cannot select the reserve requirement"
    key = occupancy.casefold()

    if key == "investment":
        return _RESERVE_MONTHS_INVESTMENT, (
            f"reserve requirement for an investment property: {_RESERVE_MONTHS_INVESTMENT} months "
            f"({_GUIDE})"
        )
    if key == "second_home":
        return _RESERVE_MONTHS_SECOND_HOME, (
            f"reserve requirement for a second home: {_RESERVE_MONTHS_SECOND_HOME} months ({_GUIDE})"
        )
    if key != "primary_residence":
        return None, f"no encoded reserve requirement for occupancy {occupancy!r}"

    # The primary-residence cell splits on unit count, and the split is 0 vs 6 months.
    if financed_unit_count is None:
        return None, (
            "the file states a principal residence but not the financed unit count, and the reserve "
            "requirement turns on it — none for one unit, 6 months for two to four (Fannie "
            "B3-4.1-01). Abstaining rather than assuming one unit, which would report a 2-4 unit file "
            "as needing no reserves"
        )
    try:
        units = int(Decimal(financed_unit_count))
    except (InvalidOperation, ValueError):
        return None, (
            f"the financed unit count reads {financed_unit_count!r}, which is not a number — the "
            "reserve requirement for a principal residence turns on it"
        )
    if units <= 0:
        return None, f"the financed unit count reads {units}, which is not a unit count"
    if units == 1:
        return _RESERVE_MONTHS_ONE_UNIT_PRIMARY, (
            f"no minimum reserve requirement for a one-unit principal residence ({_GUIDE})"
        )
    if units <= MAX_RESIDENTIAL_UNITS:
        return _RESERVE_MONTHS_MULTI_UNIT_PRIMARY, (
            f"reserve requirement for a {units}-unit principal residence: "
            f"{_RESERVE_MONTHS_MULTI_UNIT_PRIMARY} months ({_GUIDE})"
        )
    return None, (
        f"the property is financed as {units} units, beyond the one- to four-unit residential table "
        "B3-4.1-01 covers — abstaining rather than applying a requirement the guide does not state"
    )


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
    months_required: (
        Decimal | None
    )  # the B3-4.1-01 cell, or a lender overlay; None = undeterminable
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
