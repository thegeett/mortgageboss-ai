"""The deterministic max-loan calculation (LP-87) — invert the constraints, no AI.

The max-loan answer is "what is the largest loan this borrower qualifies for?" — and the
transparent, trustworthy way to compute it is to work BACKWARD from each binding
constraint and take the LOWEST (the binding one), showing all three:

1. **DTI ceiling** — given income + existing debts + the max back-end DTI, the maximum
   housing payment is (income x max-DTI - other debts - taxes/insurance/MI); invert the
   amortization to a maximum loan principal at the note rate + term.
2. **LTV limit** — given the property value + the max LTV, max loan = value x max-LTV.
3. **Loan limit** — the FHFA conforming limit (Conventional) / the FHA loan limit (a
   grounded-starter value, validate with Priya — the limits change annually + are county-
   specific).

The BINDING (lowest) constraint wins and is named. This module CONSUMES the DTI ceiling
(LP-76) + the LTV limit (LP-77) + the loan limit — it inverts them; it does not redefine
them. Pure: numeric inputs → a transparent :class:`MaxLoanResult`. ``Decimal`` throughout.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

_CENTS = Decimal("0.01")

DTI_CONSTRAINT_FORMULA = (
    "Max payment = gross income x max DTI - other monthly debts - taxes/insurance/MI; "
    "max loan = the principal whose P&I equals the remaining payment"
)
LTV_CONSTRAINT_FORMULA = "Max loan (LTV) = property value x max LTV"
LOAN_LIMIT_FORMULA = "Max loan (program limit) = the FHFA conforming / FHA loan limit"


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def max_principal_for_payment(
    payment: Decimal, annual_rate_percent: Decimal | None, term_months: int | None
) -> Decimal | None:
    """Invert the amortization: the largest principal whose monthly P&I ≤ ``payment``.

    ``P = M · ((1+r)^n - 1) / (r·(1+r)^n)`` where ``r`` is the monthly rate, ``n`` the
    term. A zero rate degrades to ``P = M · n``. Returns ``None`` on insufficient inputs.
    """
    if payment <= 0 or term_months is None or term_months <= 0 or annual_rate_percent is None:
        return None
    monthly_rate = annual_rate_percent / Decimal(100) / Decimal(12)
    if monthly_rate == 0:
        return _money(payment * Decimal(term_months))
    growth = (Decimal(1) + monthly_rate) ** term_months
    principal = payment * (growth - Decimal(1)) / (monthly_rate * growth)
    return _money(principal)


@dataclass(frozen=True)
class MaxLoanConstraint:
    """One constraint's computed max loan (or None when its inputs are absent)."""

    key: str  # "dti" | "ltv" | "loan_limit"
    label: str
    max_loan: Decimal | None
    detail: str  # a short human note (the binding figure / why None)


@dataclass(frozen=True)
class MaxLoanResult:
    """The computed max loan — each constraint + the binding (lowest) one. Pure output."""

    constraints: tuple[MaxLoanConstraint, ...]
    max_loan: Decimal | None  # the binding (minimum) across the present constraints
    binding_key: str | None  # which constraint binds


def compute_max_loan(
    *,
    gross_monthly_income: Decimal | None,
    max_back_end_dti_pct: Decimal | None,
    other_monthly_debts: Decimal,
    monthly_non_pi_housing: Decimal,
    annual_rate_percent: Decimal | None,
    term_months: int | None,
    property_value: Decimal | None,
    max_ltv_pct: Decimal | None,
    loan_limit: Decimal | None,
) -> MaxLoanResult:
    """Compute each constraint's max loan; the lowest present one binds. Pure, deterministic."""
    constraints: list[MaxLoanConstraint] = []

    # 1) DTI ceiling → max payment → invert amortization.
    dti_max: Decimal | None = None
    if gross_monthly_income is not None and max_back_end_dti_pct is not None:
        max_total_payment = gross_monthly_income * max_back_end_dti_pct / Decimal(100)
        max_pi = max_total_payment - other_monthly_debts - monthly_non_pi_housing
        dti_max = max_principal_for_payment(max_pi, annual_rate_percent, term_months)
        detail = (
            f"max P&I {_money(max_pi)}/mo at {max_back_end_dti_pct}% DTI"
            if max_pi > 0
            else "income fully consumed by existing debts"
        )
    else:
        detail = "needs income + the max-DTI ceiling"
    constraints.append(MaxLoanConstraint("dti", "DTI ceiling", dti_max, detail))

    # 2) LTV limit → value x max-LTV.
    ltv_max: Decimal | None = None
    if property_value is not None and max_ltv_pct is not None:
        ltv_max = _money(property_value * max_ltv_pct / Decimal(100))
        ltv_detail = f"{max_ltv_pct}% of {_money(property_value)}"
    else:
        ltv_detail = "needs property value + the max-LTV limit"
    constraints.append(MaxLoanConstraint("ltv", "LTV limit", ltv_max, ltv_detail))

    # 3) Program loan limit (starter).
    limit_detail = "FHFA conforming / FHA limit (starter)" if loan_limit else "limit not set"
    constraints.append(
        MaxLoanConstraint("loan_limit", "Program loan limit", loan_limit, limit_detail)
    )

    present = [(c.key, c.max_loan) for c in constraints if c.max_loan is not None]
    if not present:
        return MaxLoanResult(constraints=tuple(constraints), max_loan=None, binding_key=None)
    binding_key, binding_value = min(present, key=lambda kv: kv[1])
    return MaxLoanResult(
        constraints=tuple(constraints),
        max_loan=binding_value.quantize(_CENTS, rounding=ROUND_DOWN),
        binding_key=binding_key,
    )
