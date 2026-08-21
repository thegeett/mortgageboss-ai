"""LP-607 — comparing a per-period pay figure to a monthly one, and calling the gap a conflict.

FROM THE RUN. After the pay stubs landed on LF-3CVT the AI cross-source pass reported:

    "Stated monthly income of $13,166.67 conflicts with documented biweekly pay stubs showing gross
     pay of approximately $6,028-$6,063 per period (annualizes to ~$156,728-$157,634 or
     ~$13,061-$13,136/month)"

$13,166.67 against $13,061-$13,136 is a difference of 0.2%-0.8%. The deterministic rule that owns this
question uses a 10% threshold. The income AGREES, and the finding's own sentence carries the
arithmetic that says so — it annualised correctly in prose after comparing wrongly.

WHY THE DETERMINISTIC RULE DID NOT COVER IT. `_check_income_variance` compares
`stated_income_monthly` to `documented_income_monthly` and is correct. It ABSTAINED here, because no
documented monthly figure had been computed — and the AI layer deliberately fills a type the
deterministic pass was silent on (see OWNED_CANONICAL_TYPES' comment). That design is not changed
here; what is fixed is the arithmetic error it made while filling the gap.
"""

from __future__ import annotations

from decimal import Decimal

from app.ai.cross_source import CROSS_SOURCE_SYSTEM_PROMPT


def test_the_prompt_requires_conversion_before_calling_it_a_conflict() -> None:
    assert "COMPARE LIKE WITH LIKE" in CROSS_SOURCE_SYSTEM_PROMPT
    assert "biweekly x 26 / 12" in CROSS_SOURCE_SYSTEM_PROMPT
    assert "semi-monthly x 24 / 12" in CROSS_SOURCE_SYSTEM_PROMPT


def test_the_prompt_carries_the_real_numbers_that_caught_it() -> None:
    """Anchored to the observed failure rather than stated abstractly — a rule written from a real
    case is harder to edit away by accident."""
    assert "$6,028 biweekly" in CROSS_SOURCE_SYSTEM_PROMPT
    assert "$13,166.67 per month" in CROSS_SOURCE_SYSTEM_PROMPT


def test_the_prompt_says_a_vanishing_difference_is_not_a_finding() -> None:
    assert "A difference that vanishes once converted is NOT a conflict" in (
        CROSS_SOURCE_SYSTEM_PROMPT
    )


def test_the_arithmetic_the_prompt_asserts_is_actually_right() -> None:
    """The conversion in the prompt is a factual claim, so it is checked rather than trusted: if
    biweekly $6,028 did NOT come to about $13,061 a month, the guidance would be teaching an error."""
    monthly = Decimal("6028") * 26 / 12

    assert Decimal("13050") < monthly < Decimal("13075")
    stated = Decimal("13166.67")
    variance = abs(stated - monthly) / monthly * 100
    assert variance < Decimal("1"), "the figures agree to within one percent"


def test_the_deterministic_rule_it_defers_to_is_unchanged() -> None:
    """The fix is to the AI's arithmetic, NOT to the deterministic rule, which compares monthly to
    monthly and was right to abstain when no monthly figure existed."""
    from app.verification.cross_source.facts import CrossSourceFacts
    from app.verification.cross_source.rules import _check_income_variance

    agreeing = CrossSourceFacts(
        stated_income_monthly=Decimal("13166.67"),
        documented_income_monthly=Decimal("13061"),
    )
    assert _check_income_variance(agreeing, None) == []

    conflicting = CrossSourceFacts(
        stated_income_monthly=Decimal("13166.67"),
        documented_income_monthly=Decimal("6028"),  # the per-period figure, unconverted
    )
    assert len(_check_income_variance(conflicting, None)) == 1


# --------------------------------------------------------------------------- #
# LP-611 — converting correctly and still calling it a conflict
# --------------------------------------------------------------------------- #


def test_the_prompt_says_a_small_converted_difference_is_not_a_conflict() -> None:
    """LP-607 fixed the ARITHMETIC and not the conclusion. The next run produced:

        "Stated monthly income of $13,166.67 conflicts with documented biweekly gross pay which
         converts to approximately $13,136 per month"

    The conversion is now right. Two tenths of one percent is still described as a conflict. Income
    documents never match a stated figure to the dollar — a stub covers a different period, a bonus
    lands in one month — so a small difference is the normal state of a correct file.
    """
    assert "more than TEN PERCENT" in CROSS_SOURCE_SYSTEM_PROMPT
    assert "converts to approximately $13,136 per month" in CROSS_SOURCE_SYSTEM_PROMPT


def test_the_threshold_matches_the_deterministic_rule_that_owns_this() -> None:
    """Ten percent is not invented for the prompt — it is the bar `_check_income_variance` already
    uses, so the AI filling that rule's gap applies the same standard rather than a stricter one."""
    from app.verification.cross_source.rules import XSRC_INCOME_STATED_VS_DOCUMENTED

    threshold = XSRC_INCOME_STATED_VS_DOCUMENTED.threshold
    assert threshold is not None
    assert str(threshold.value) == "10"


def test_the_prompt_forbids_comparing_two_different_accounts() -> None:
    """From the same run: "Stated Bank of America checking account with $10,000, but documented Wells
    Fargo account shows only $6,526.74". Two accounts at two banks — that their balances differ is
    not a discrepancy. The honest observation is that the stated account is undocumented."""
    assert "compares two accounts at two banks" in CROSS_SOURCE_SYSTEM_PROMPT
    assert "the honest observation is that it is undocumented" in CROSS_SOURCE_SYSTEM_PROMPT
