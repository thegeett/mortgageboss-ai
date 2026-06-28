"""The deterministic DTI math (LP-76) — pure, no DB, correct by construction.

Amortization (incl. the zero-rate degenerate case), the two ratios, the breakdown
sums, and the income-zero (undefined) case. Decimal throughout.
"""

from decimal import Decimal

from app.verification.dti import (
    DtiLine,
    compute_dti,
    monthly_principal_interest,
)


def _line(key: str, amount: str) -> DtiLine:
    return DtiLine(key=key, label=key, amount=Decimal(amount))


def test_amortization_textbook_value() -> None:
    """$100,000 at 6% for 360 months → $599.55/mo (standard amortization)."""
    pi = monthly_principal_interest(Decimal("100000"), Decimal("6"), 360)
    assert pi == Decimal("599.55")


def test_amortization_zero_rate_is_principal_over_term() -> None:
    """A zero rate degrades to principal / term."""
    pi = monthly_principal_interest(Decimal("360000"), Decimal("0"), 360)
    assert pi == Decimal("1000.00")


def test_amortization_missing_inputs_return_none() -> None:
    """Insufficient inputs → None (overridable, not guessed)."""
    assert monthly_principal_interest(None, Decimal("6"), 360) is None
    assert monthly_principal_interest(Decimal("100000"), None, 360) is None
    assert monthly_principal_interest(Decimal("100000"), Decimal("6"), None) is None
    assert monthly_principal_interest(Decimal("100000"), Decimal("6"), 0) is None


def test_front_and_back_end_ratios() -> None:
    """front = housing/income; back = (housing + debts)/income."""
    result = compute_dti(
        income_lines=[_line("income.a", "8000"), _line("income.b", "2000")],  # 10000
        housing_lines=[_line("housing.pi", "1500"), _line("housing.taxes", "500")],  # 2000
        debt_lines=[_line("debt.a", "600"), _line("debt.b", "400")],  # 1000
    )
    assert result.gross_monthly_income == Decimal("10000")
    assert result.housing_payment == Decimal("2000")
    assert result.monthly_debts == Decimal("1000")
    assert result.total_monthly_obligations == Decimal("3000")
    assert result.front_end_pct == Decimal("20.00")  # 2000 / 10000
    assert result.back_end_pct == Decimal("30.00")  # 3000 / 10000


def test_ratio_rounds_half_up_two_dp() -> None:
    """Ratios round half-up to two decimals."""
    result = compute_dti(
        income_lines=[_line("income.a", "9000")],
        housing_lines=[_line("housing.pi", "2000")],
        debt_lines=[_line("debt.a", "1000")],
    )
    # 3000 / 9000 = 33.333... → 33.33
    assert result.back_end_pct == Decimal("33.33")


def test_zero_income_yields_none_ratios() -> None:
    """Income of zero → undefined ratios (no division by zero)."""
    result = compute_dti(
        income_lines=[],
        housing_lines=[_line("housing.pi", "2000")],
        debt_lines=[_line("debt.a", "500")],
    )
    assert result.gross_monthly_income == Decimal("0")
    assert result.front_end_pct is None
    assert result.back_end_pct is None
