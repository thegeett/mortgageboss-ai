"""The deterministic LTV math (LP-77) — pure, the subtleties correct.

The two trust-critical subtleties: LTV uses the **lesser of** price and appraised
value (tested both directions), and HCLTV uses the HELOC **credit limit**, not its
drawn balance (a $0-balance / $40k-line HELOC pushes HCLTV above CLTV). Plus
refinance-aware denominators.
"""

from decimal import Decimal

from app.verification.ltv import (
    LtvInputs,
    LtvPurpose,
    compute_ltv,
    ltv_formula,
    value_basis,
)


def _inputs(
    *,
    first_loan: Decimal = Decimal("0"),
    second_loan: Decimal = Decimal("0"),
    heloc_drawn: Decimal = Decimal("0"),
    heloc_limit: Decimal = Decimal("0"),
    purchase_price: Decimal = Decimal("0"),
    appraised_value: Decimal = Decimal("0"),
) -> LtvInputs:
    return LtvInputs(
        first_loan=first_loan,
        second_loan=second_loan,
        heloc_drawn=heloc_drawn,
        heloc_limit=heloc_limit,
        purchase_price=purchase_price,
        appraised_value=appraised_value,
    )


def test_ltv_uses_lesser_of_when_price_below_appraised() -> None:
    """price 190k < appraised 200k → basis is 190k."""
    result = compute_ltv(
        _inputs(
            first_loan=Decimal("180000"),
            purchase_price=Decimal("190000"),
            appraised_value=Decimal("200000"),
        ),
        LtvPurpose.PURCHASE,
    )
    assert result.value_basis == Decimal("190000")
    assert result.ltv_pct == Decimal("94.74")  # 180000 / 190000


def test_ltv_uses_lesser_of_when_appraised_below_price() -> None:
    """appraised 185k < price 200k → basis is 185k (the lender won't lend on price)."""
    result = compute_ltv(
        _inputs(
            first_loan=Decimal("180000"),
            purchase_price=Decimal("200000"),
            appraised_value=Decimal("185000"),
        ),
        LtvPurpose.PURCHASE,
    )
    assert result.value_basis == Decimal("185000")
    assert result.ltv_pct == Decimal("97.30")  # 180000 / 185000


def test_cltv_combines_first_and_second() -> None:
    """CLTV = (first + second + HELOC drawn) / value."""
    result = compute_ltv(
        _inputs(
            first_loan=Decimal("160000"),
            second_loan=Decimal("20000"),
            purchase_price=Decimal("200000"),
            appraised_value=Decimal("200000"),
        ),
        LtvPurpose.PURCHASE,
    )
    assert result.ltv_pct == Decimal("80.00")  # 160000 / 200000
    assert result.cltv_pct == Decimal("90.00")  # 180000 / 200000


def test_hcltv_uses_heloc_credit_limit_not_balance() -> None:
    """A $0-balance HELOC with a $40k line pushes HCLTV above CLTV (the subtlety)."""
    result = compute_ltv(
        _inputs(
            first_loan=Decimal("160000"),
            heloc_drawn=Decimal("0"),  # nothing drawn today
            heloc_limit=Decimal("40000"),  # but a $40k line could be drawn tomorrow
            appraised_value=Decimal("200000"),
            purchase_price=Decimal("200000"),
        ),
        LtvPurpose.PURCHASE,
    )
    assert result.cltv_pct == Decimal("80.00")  # 160000 / 200000 (drawn balance 0)
    assert result.hcltv_pct == Decimal("100.00")  # (160000 + 40000) / 200000 (full line)
    assert result.hcltv_pct > result.cltv_pct


def test_refinance_uses_appraised_value_not_purchase_price() -> None:
    """A rate-term refi has no purchase price → the basis is the appraised value."""
    result = compute_ltv(
        _inputs(
            first_loan=Decimal("150000"),
            purchase_price=Decimal("999999"),  # ignored for a refinance
            appraised_value=Decimal("200000"),
        ),
        LtvPurpose.RATE_TERM_REFINANCE,
    )
    assert result.value_basis == Decimal("200000")
    assert result.ltv_pct == Decimal("75.00")  # 150000 / 200000


def test_cash_out_refinance_also_uses_appraised_value() -> None:
    result = compute_ltv(
        _inputs(first_loan=Decimal("100000"), appraised_value=Decimal("200000")),
        LtvPurpose.CASH_OUT_REFINANCE,
    )
    assert result.value_basis == Decimal("200000")
    assert result.ltv_pct == Decimal("50.00")


def test_missing_value_basis_yields_none_ratios() -> None:
    """No usable value → undefined ratios (graceful; the appraisal may be missing)."""
    result = compute_ltv(_inputs(first_loan=Decimal("150000")), LtvPurpose.PURCHASE)
    assert result.value_basis is None
    assert result.ltv_pct is None
    assert result.cltv_pct is None
    assert result.hcltv_pct is None


def test_value_basis_label_and_formula_are_purpose_aware() -> None:
    basis, label = value_basis(LtvPurpose.PURCHASE, Decimal("190000"), Decimal("200000"))
    assert basis == Decimal("190000")
    assert "lesser of" in label
    assert "lesser of" in ltv_formula(LtvPurpose.PURCHASE)
    assert "appraised value" in ltv_formula(LtvPurpose.CASH_OUT_REFINANCE)
