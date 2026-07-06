"""The four LP-87 calculators — pure deterministic math (no DB, no AI).

Covers: MI program-awareness (PMI required>80%/cancel 78%; FHA MIP upfront 1.75% + the
LTV-90% 11yr-vs-life duration consuming LP-84's values); the self-employed Form-1084
derivation (add-backs + 2-year averaging + the declining flag); reserves (the 60% FHA
retirement haircut, available vs required); and max-loan (inverts DTI/LTV/loan-limit, the
binding/lowest constraint wins).
"""

from decimal import Decimal

from app.verification.max_loan import compute_max_loan, max_principal_for_payment
from app.verification.mortgage_insurance import compute_conventional_pmi, compute_fha_mip
from app.verification.reserves import compute_reserves
from app.verification.self_employed import SelfEmployedYear, compute_self_employed_income

# --- Mortgage insurance (program-aware) --------------------------------------


def test_conventional_pmi_required_above_80_and_cancels_at_78() -> None:
    high = compute_conventional_pmi(
        base_loan_amount=Decimal("300000"), ltv_pct=Decimal("95"), annual_rate_bps=Decimal("50")
    )
    assert high.required is True
    assert high.monthly_premium == Decimal("125.00")  # 300000 * 0.005 / 12
    assert high.cancel_ltv == Decimal("78")
    low = compute_conventional_pmi(
        base_loan_amount=Decimal("300000"), ltv_pct=Decimal("75"), annual_rate_bps=Decimal("50")
    )
    assert low.required is False and low.monthly_premium is None


def test_fha_mip_consumes_lp84_values_and_the_ltv90_duration() -> None:
    high = compute_fha_mip(
        base_loan_amount=Decimal("300000"),
        ltv_pct=Decimal("96.5"),
        upfront_rate_bps=Decimal("175"),
        annual_rate_bps=Decimal("55"),
        duration_threshold_ltv=Decimal("90"),
    )
    assert high.upfront_premium == Decimal("5250.00")  # 1.75% of 300k
    assert high.monthly_premium == Decimal("137.50")
    assert high.duration_label == "life of loan"  # LTV > 90%
    low = compute_fha_mip(
        base_loan_amount=Decimal("300000"),
        ltv_pct=Decimal("85"),
        upfront_rate_bps=Decimal("175"),
        annual_rate_bps=Decimal("55"),
        duration_threshold_ltv=Decimal("90"),
    )
    assert low.duration_label == "11 years"  # LTV <= 90%


# --- Self-employed income (Form 1084) ----------------------------------------


def test_self_employed_adds_back_and_averages_two_years() -> None:
    result = compute_self_employed_income(
        [
            SelfEmployedYear(2024, Decimal("80000"), {"depreciation": Decimal("12000")}),
            SelfEmployedYear(2025, Decimal("90000"), {"depreciation": Decimal("14000")}),
        ]
    )
    # adjusted: 2024 = 92000, 2025 = 104000; avg = 98000; monthly = 8166.67
    assert result.average_annual == Decimal("98000.00")
    assert result.qualifying_monthly == Decimal("8166.67")
    assert result.declining is False


def test_self_employed_flags_a_declining_trend() -> None:
    result = compute_self_employed_income(
        [
            SelfEmployedYear(2024, Decimal("120000"), {}),
            SelfEmployedYear(2025, Decimal("90000"), {}),
        ]
    )
    assert result.declining is True  # most-recent < prior → a flag, not a silent average


def test_self_employed_empty_is_graceful() -> None:
    result = compute_self_employed_income([])
    assert result.qualifying_monthly is None and result.year_count == 0


# --- Reserves (FHA 60% haircut) ----------------------------------------------


def test_reserves_apply_60pct_retirement_haircut_and_compare() -> None:
    result = compute_reserves(
        liquid_assets=Decimal("40000"),
        retirement_assets=Decimal("100000"),
        retirement_factor=Decimal("0.60"),
        excluded_funds=Decimal("10000"),
        down_payment=Decimal("25000"),
        closing_costs=Decimal("8000"),
        monthly_housing_payment=Decimal("2500"),
        months_required=Decimal("2"),
    )
    assert result.retirement_counted == Decimal("60000.00")  # 60% of 100k
    # eligible = 40000 + 60000 - 25000 - 8000 = 67000
    assert result.eligible_reserves == Decimal("67000.00")
    assert result.months_available == Decimal("26.8")  # 67000 / 2500
    assert result.sufficient is True


def test_reserves_never_negative() -> None:
    result = compute_reserves(
        liquid_assets=Decimal("5000"),
        retirement_assets=Decimal("0"),
        retirement_factor=Decimal("1.00"),
        excluded_funds=Decimal("0"),
        down_payment=Decimal("20000"),
        closing_costs=Decimal("8000"),
        monthly_housing_payment=Decimal("2000"),
        months_required=Decimal("2"),
    )
    assert result.eligible_reserves == Decimal("0.00")  # clamped, not negative
    assert result.sufficient is False


# --- Max loan (invert constraints; binding wins) -----------------------------


def test_max_loan_binding_constraint_wins() -> None:
    result = compute_max_loan(
        gross_monthly_income=Decimal("12000"),
        max_back_end_dti_pct=Decimal("45"),
        other_monthly_debts=Decimal("800"),
        monthly_non_pi_housing=Decimal("600"),
        annual_rate_percent=Decimal("6.5"),
        term_months=360,
        property_value=Decimal("500000"),
        max_ltv_pct=Decimal("97"),
        loan_limit=Decimal("806500"),
    )
    # LTV binds: 97% of 500k = 485000, below the DTI-derived (~632k) and the limit.
    assert result.binding_key == "ltv"
    assert result.max_loan == Decimal("485000.00")
    keys = {c.key for c in result.constraints}
    assert keys == {"dti", "ltv", "loan_limit"}


def test_max_principal_inverts_amortization() -> None:
    # A 1264.14/mo payment at 6.5%/360 ≈ 200k principal (round-trip of the DTI calc's P&I).
    principal = max_principal_for_payment(Decimal("1264.14"), Decimal("6.5"), 360)
    assert principal is not None and Decimal("199950") <= principal <= Decimal("200050")


def test_max_loan_none_when_no_constraint_present() -> None:
    result = compute_max_loan(
        gross_monthly_income=None,
        max_back_end_dti_pct=None,
        other_monthly_debts=Decimal("0"),
        monthly_non_pi_housing=Decimal("0"),
        annual_rate_percent=None,
        term_months=None,
        property_value=None,
        max_ltv_pct=None,
        loan_limit=None,
    )
    assert result.max_loan is None and result.binding_key is None
