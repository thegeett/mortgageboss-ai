"""LP-496 — B2-1.2-01's DELIVERED rounding, and why it does NOT reach every consumer (ADR-383).

Fannie Mae Selling Guide B2-1.2-01, page dated 06/01/2022 (re-verified against the live guide):

    "The result of these calculations must be truncated (shortened) to two decimal places, then
     rounded up to the nearest whole percent."
    "94.01% will be delivered as 95%, and 80.001% will be delivered as 80%."
    "Lenders' systems must contain rounding methodology that results in the same or a higher LTV ratio."

The same page: "The rounding rules noted above also apply to the CLTV and HCLTV ratio calculations."

These prove the arithmetic BY VALUE (not by verdict), and then prove the one place the delivered
value must NOT be used: the FHA purchase cap is 96.5%, a FRACTIONAL limit, and a whole-percent ratio
compared against it flips a passing loan to failing.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import pytest
from app.models.lender import LoanProgram
from app.services.ltv import _resolve_limit
from app.verification.ltv import (
    LtvInputs,
    LtvPurpose,
    compute_ltv,
    delivered_percent,
)


def _inputs(first_loan: Decimal, appraised_value: Decimal) -> LtvInputs:
    return LtvInputs(
        first_loan=first_loan,
        second_loan=Decimal(0),
        heloc_drawn=Decimal(0),
        heloc_limit=Decimal(0),
        purchase_price=None,
        appraised_value=appraised_value,
    )


# --------------------------------------------------------------------------- #
# The arithmetic, by value
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "exact,expected",
    [
        # THE GUIDE'S OWN TWO WORKED EXAMPLES — the authority for this implementation.
        (Decimal("94.01"), Decimal("95")),
        (Decimal("80.001"), Decimal("80")),
        # The ticket's list, CORRECTED. 80.001 and 80.004 were stated as 81; both are 80, because
        # truncation discards everything past two decimals and 80.00 is already a whole percent.
        (Decimal("80.00"), Decimal("80")),
        (Decimal("80.004"), Decimal("80")),
        (Decimal("80.499"), Decimal("81")),
        (Decimal("79.999"), Decimal("80")),
        # A ratio that is already a whole number stays put.
        (Decimal("75.00"), Decimal("75")),
        (Decimal("100.00"), Decimal("100")),
        # The first cent past a whole percent is what moves it.
        (Decimal("80.01"), Decimal("81")),
    ],
)
def test_delivered_percent_matches_the_guideline(exact: Decimal, expected: Decimal) -> None:
    assert delivered_percent(exact) == expected


def test_truncation_is_not_rounding_down_then_ceiling_the_whole() -> None:
    """The two operations, in ORDER — the thing the ticket's worked example got backwards.

    Truncation DISCARDS everything past two decimals; it is not "round down at the second decimal
    and then round the whole up". If it were the latter, 80.001 would deliver as 81. The guide says
    80. A naive `ceil(80.001)` gives 81 and is what this pins against."""
    assert delivered_percent(Decimal("80.001")) == Decimal("80")
    assert Decimal("80.001").to_integral_value(rounding="ROUND_CEILING") == Decimal("81")


def test_delivered_is_none_exactly_when_the_exact_ratio_is_none() -> None:
    assert delivered_percent(None) is None
    result = compute_ltv(_inputs(Decimal("100000"), Decimal(0)), LtvPurpose.PURCHASE)
    assert result.ltv_pct is None and result.ltv_pct_delivered is None


def test_all_three_ratios_get_the_delivered_rounding() -> None:
    """B2-1.2-01: "The rounding rules noted above also apply to the CLTV and HCLTV ratio
    calculations." B2-1.2-02 (12/04/2018) and B2-1.2-03 (02/23/2016) state their formulas and are
    silent on rounding, so this page carries all three — which is why one shared helper is correct."""
    result = compute_ltv(
        LtvInputs(
            first_loan=Decimal("180000"),
            second_loan=Decimal("10000"),
            heloc_drawn=Decimal(0),
            heloc_limit=Decimal("20000"),
            purchase_price=None,
            appraised_value=Decimal("190000"),
        ),
        LtvPurpose.RATE_TERM_REFINANCE,
    )
    assert (result.ltv_pct, result.ltv_pct_delivered) == (Decimal("94.74"), Decimal("95"))
    assert (result.cltv_pct, result.cltv_pct_delivered) == (Decimal("100.00"), Decimal("100"))
    assert (result.hcltv_pct, result.hcltv_pct_delivered) == (Decimal("110.53"), Decimal("111"))


def test_the_exact_ratio_is_unchanged_by_lp496() -> None:
    """The defect was never that the exact figure existed — it was that it was the ONLY figure.
    `_ratio` is deliberately untouched, so every existing exact-value assertion still holds."""
    result = compute_ltv(
        _inputs(Decimal("180000"), Decimal("190000")), LtvPurpose.RATE_TERM_REFINANCE
    )
    assert result.ltv_pct == Decimal("94.74")


def test_the_lesser_of_selection_is_untouched() -> None:
    """This ticket changes ROUNDING ONLY — the denominator policy is not in scope."""
    result = compute_ltv(
        LtvInputs(
            first_loan=Decimal("180000"),
            second_loan=Decimal(0),
            heloc_drawn=Decimal(0),
            heloc_limit=Decimal(0),
            purchase_price=Decimal("200000"),
            appraised_value=Decimal("185000"),
        ),
        LtvPurpose.PURCHASE,
    )
    assert result.value_basis == Decimal("185000")  # the lower of the two, unchanged


# --------------------------------------------------------------------------- #
# THE DIVERGENCE BAND — where the fix actually changes an MI-1 answer, and which way
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "exact,current_says_mi,delivered_says_mi",
    [
        (Decimal("80.00"), False, False),
        (Decimal("80.004"), False, False),
        # THE ONLY BAND WHERE THE ANSWER MOVES, and it moves the way the ticket did not expect:
        # the OLD half-up behaviour required MI and the guideline does not. The fix RELAXES MI-1
        # here. (B2-1.2-01 permits the old value — it was "the same or a higher" ratio.)
        (Decimal("80.005"), True, False),
        (Decimal("80.009"), True, False),
        (Decimal("80.01"), True, True),
        (Decimal("80.49"), True, True),
    ],
)
def test_the_mi1_divergence_band(
    exact: Decimal, current_says_mi: bool, delivered_says_mi: bool
) -> None:
    """MI-1 asks `ltv > 80`. Pinned by VALUE so the direction of the change is recorded, not inferred.

    `exact` is the RAW quotient; the old behaviour rounded it half-up to two decimals."""
    threshold = Decimal("80")
    old_value = exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert (old_value > threshold) is current_says_mi
    assert (delivered_percent(exact) > threshold) is delivered_says_mi


def test_delivered_truncates_the_RAW_quotient_not_the_half_up_figure() -> None:
    """The bug this file caught in LP-496's own first implementation.

    `delivered_percent` originally took the already-half-up two-decimal figure. For a raw 80.005
    that is 80.01, which ceils to 81 — but truncating the RAW quotient gives 80.00, which is
    already whole and delivers as 80. B2-1.2-01 says to truncate "the result of these
    calculations", i.e. the quotient, so half-up must not run first."""
    raw = Decimal("80.005")
    assert delivered_percent(raw) == Decimal("80")
    smuggled = raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert delivered_percent(smuggled) == Decimal("81")  # what the wrong order would have produced


# --------------------------------------------------------------------------- #
# THE FHA 96.5% BAND — proven with constructed values, because no corpus file sits here
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("exact", [Decimal("96.01"), Decimal("96.25"), Decimal("96.50")])
def test_fha_purchase_cap_must_use_the_exact_ratio_not_the_delivered_one(exact: Decimal) -> None:
    """The reason ADR-383 exists, proven directly.

    `fha.ltv.purchase_max` is 96.5% — a FRACTIONAL cap, and FHA's actual maximum, so real FHA
    purchase files cluster in exactly this band. Comparing B2-1.2-01's delivered whole percent
    against it rounds 96.01 up to 97 and fails a loan that is inside the limit.

    No file in the corpus sits here, so this is proven on CONSTRUCTED values rather than left as a
    hypothetical — it is a latent defect, not an absent one."""
    delivered = delivered_percent(exact)
    assert delivered == Decimal("97")

    # What the code does now: the EXACT ratio is passed, and the loan passes.
    limit = _resolve_limit(LoanProgram.FHA, LtvPurpose.PURCHASE, None, exact)
    assert limit.ltv_max == Decimal("96.5"), (
        "the FHA purchase cap is fractional — that is the point"
    )
    assert limit.status == "pass"

    # What passing the delivered percent would have done: the same loan fails.
    would_be = _resolve_limit(LoanProgram.FHA, LtvPurpose.PURCHASE, None, delivered)
    assert would_be.status == "over", (
        "if this ever reads 'pass', the delivered value has been wired into the cap comparison and "
        "the FHA (96.00, 96.50] band is silently failing"
    )


def test_fha_purchase_at_or_below_96_00_is_unaffected() -> None:
    """The band boundary, from the other side: at 96.00 both values agree and nothing moves."""
    exact = Decimal("96.00")
    assert delivered_percent(exact) == Decimal("96")
    assert _resolve_limit(LoanProgram.FHA, LtvPurpose.PURCHASE, None, exact).status == "pass"
    assert (
        _resolve_limit(LoanProgram.FHA, LtvPurpose.PURCHASE, None, delivered_percent(exact)).status
        == "pass"
    )


@pytest.mark.parametrize(
    "program,purpose,cap",
    [
        (LoanProgram.CONVENTIONAL, LtvPurpose.PURCHASE, Decimal("97")),
        (LoanProgram.CONVENTIONAL, LtvPurpose.CASH_OUT_REFINANCE, Decimal("80")),
        (LoanProgram.FHA, LtvPurpose.CASH_OUT_REFINANCE, Decimal("80")),
    ],
)
def test_the_other_caps_are_whole_and_the_fha_purchase_one_is_the_exception(
    program: LoanProgram, purpose: LtvPurpose, cap: Decimal
) -> None:
    """Three of the four caps are whole percents; only FHA purchase (96.5) is fractional. Recorded so
    the exception is known to be a single one rather than assumed to be."""
    limit = _resolve_limit(program, purpose, None, Decimal("50.00"))
    assert limit.ltv_max == cap
    assert cap == cap.to_integral_value(), (
        "this cap is whole — the FHA purchase 96.5 is the outlier"
    )
