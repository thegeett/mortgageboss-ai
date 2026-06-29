"""The deterministic mortgage-insurance calculation (LP-87) — PROGRAM-AWARE, no AI.

Mortgage insurance is program-specific, and the calculator shows the math transparently
(the LP-76/77 win, against ChatGPT's black box):

* **Conventional → PMI.** Required when LTV > 80%; automatically terminates at 78% LTV
  (the Homeowners Protection Act). The annual premium rate is credit-score / LTV-driven
  (a rate card) — the rate METHODOLOGY is a grounded-starter (validate with Priya); the
  arithmetic (premium = base loan x rate ÷ 12) is exact.
* **FHA → MIP.** CONSUMES LP-84's MIP rules (the service passes the rule-derived values
  in): upfront MIP (1.75% / 175 bps of the base loan amount, typically financed); annual
  MIP (the rate table — most 30-year borrowers 0.55%); and the DURATION rule — LTV ≤ 90%
  → 11 years; LTV > 90% → the life of the loan. This module does the arithmetic; the
  rates + the 90% duration threshold are passed in from the FHA rules (not duplicated).

Pure: numeric inputs → a transparent :class:`MiResult`. ``Decimal`` throughout; money
rounds half-up to cents, rates are basis points.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_CENTS = Decimal("0.01")
_PMI_REQUIRED_LTV = Decimal("80")  # PMI required above 80% LTV
_PMI_CANCEL_LTV = Decimal("78")  # PMI auto-terminates at 78% LTV (HPA)

CONVENTIONAL_PMI_FORMULA = "Monthly PMI = base loan amount x annual PMI rate ÷ 12"
FHA_UFMIP_FORMULA = "Upfront MIP = base loan amount x UFMIP rate (financed into the loan)"
FHA_ANNUAL_MIP_FORMULA = "Monthly MIP = base loan amount x annual MIP rate ÷ 12"


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class MiResult:
    """The computed mortgage insurance — program-aware, transparent. Pure output."""

    program: str  # "conventional" | "fha"
    base_loan_amount: Decimal
    ltv_pct: Decimal | None
    required: bool  # is MI required at this LTV?
    annual_rate_bps: Decimal | None  # the annual premium rate in basis points
    monthly_premium: Decimal | None  # the recurring monthly MI premium
    # Conventional-only:
    cancel_ltv: Decimal | None  # the LTV at which PMI terminates (78%)
    # FHA-only:
    upfront_premium: Decimal | None  # UFMIP (financed)
    upfront_rate_bps: Decimal | None  # UFMIP rate in bps (175)
    duration_label: str | None  # "11 years" | "life of loan"


def compute_conventional_pmi(
    *, base_loan_amount: Decimal, ltv_pct: Decimal | None, annual_rate_bps: Decimal
) -> MiResult:
    """Conventional PMI: required above 80% LTV, cancels at 78%; premium = loan x rate ÷ 12."""
    required = ltv_pct is not None and ltv_pct > _PMI_REQUIRED_LTV
    monthly = (
        _money(base_loan_amount * annual_rate_bps / Decimal(10000) / Decimal(12))
        if required
        else None
    )
    return MiResult(
        program="conventional",
        base_loan_amount=base_loan_amount,
        ltv_pct=ltv_pct,
        required=required,
        annual_rate_bps=annual_rate_bps if required else None,
        monthly_premium=monthly,
        cancel_ltv=_PMI_CANCEL_LTV,
        upfront_premium=None,
        upfront_rate_bps=None,
        duration_label=None,
    )


def compute_fha_mip(
    *,
    base_loan_amount: Decimal,
    ltv_pct: Decimal | None,
    upfront_rate_bps: Decimal,
    annual_rate_bps: Decimal,
    duration_threshold_ltv: Decimal,
) -> MiResult:
    """FHA MIP: UFMIP + annual MIP + the LTV-driven duration (consumes LP-84's values).

    ``upfront_rate_bps`` (175), ``annual_rate_bps`` (the table rate), and
    ``duration_threshold_ltv`` (90) are passed in from the FHA MIP rules — this does the
    arithmetic only. Duration: LTV ≤ threshold → 11 years; LTV > threshold → life of loan.
    """
    upfront = _money(base_loan_amount * upfront_rate_bps / Decimal(10000))
    monthly = _money(base_loan_amount * annual_rate_bps / Decimal(10000) / Decimal(12))
    duration_label: str | None = None
    if ltv_pct is not None:
        duration_label = "life of loan" if ltv_pct > duration_threshold_ltv else "11 years"
    return MiResult(
        program="fha",
        base_loan_amount=base_loan_amount,
        ltv_pct=ltv_pct,
        required=True,  # every FHA loan carries MIP
        annual_rate_bps=annual_rate_bps,
        monthly_premium=monthly,
        cancel_ltv=None,
        upfront_premium=upfront,
        upfront_rate_bps=upfront_rate_bps,
        duration_label=duration_label,
    )
