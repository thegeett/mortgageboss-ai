"""The reconciliation read model's comparison rules (LP-UI-017, ADR-391).

These are the rules a processor's judgement rests on: whether two numbers agree,
and whether an employer written two ways is one employer. They are pure, so they
are tested directly rather than through the endpoint.
"""

from decimal import Decimal

import pytest
from app.services.reconciliation import (
    Agreement,
    income_agreement,
    money_agreement,
    name_agreement,
)


class TestMoneyAgreement:
    """Exact to the cent — a valuation is copied, not estimated."""

    def test_identical_amounts_match(self) -> None:
        assert money_agreement(Decimal("720000"), Decimal("720000")) is Agreement.MATCH

    def test_a_single_cent_differs(self) -> None:
        # No tolerance on purpose: if these differ at all, someone transcribed one.
        assert money_agreement(Decimal("720000.00"), Decimal("720000.01")) is Agreement.DIFFERS

    def test_stated_with_nothing_found_is_missing(self) -> None:
        assert money_agreement(Decimal("720000"), None) is Agreement.MISSING

    def test_found_with_nothing_stated_is_not_stated(self) -> None:
        # The direction matters: this is a disclosure problem, not a gap to chase.
        assert money_agreement(None, Decimal("31845.19")) is Agreement.NOT_STATED


class TestIncomeAgreement:
    """The engine's 10% variance, not a second tolerance."""

    @pytest.mark.parametrize("found", [Decimal("10000"), Decimal("10900"), Decimal("9100")])
    def test_within_ten_percent_matches(self, found: Decimal) -> None:
        assert income_agreement(Decimal("10000"), found) is Agreement.MATCH

    def test_exactly_ten_percent_still_matches(self) -> None:
        # `<=`, matching the engine's Operator.LE — a boundary that disagreed
        # with the rule would put the ledger and the finding at odds.
        assert income_agreement(Decimal("11000"), Decimal("10000")) is Agreement.MATCH

    def test_beyond_ten_percent_differs(self) -> None:
        assert income_agreement(Decimal("11001"), Decimal("10000")) is Agreement.DIFFERS

    def test_zero_documented_income_does_not_divide_by_zero(self) -> None:
        assert income_agreement(Decimal("500"), Decimal("0")) is Agreement.DIFFERS
        assert income_agreement(Decimal("0"), Decimal("0")) is Agreement.MATCH


class TestNameAgreement:
    """Employer identity survives how each system chose to spell it."""

    @pytest.mark.parametrize(
        ("stated", "found"),
        [
            ("Cascade Robotics Inc.", "Cascade Robotics"),
            ("Ambio, Inc.", "Ambio, DBA Ambio, Inc"),
            ("ACME Co", "Acme Company"),
        ],
    )
    def test_the_same_employer_spelled_differently_matches(self, stated: str, found: str) -> None:
        assert name_agreement(stated, found) is Agreement.MATCH

    def test_genuinely_different_employers_differ(self) -> None:
        # The row that made this rule necessary: the seed file states Bank of
        # America and the W-2 says Wells Fargo. That must stay a disagreement.
        assert name_agreement("Bank of America", "Wells Fargo Bank, N. A.") is Agreement.DIFFERS

    def test_names_that_are_only_legal_form_do_not_match_from_emptiness(self) -> None:
        # Both reduce to no identifying tokens; agreeing here would be agreeing
        # that two unknowns are the same company.
        assert name_agreement("Inc.", "LLC") is Agreement.DIFFERS

    def test_direction_is_preserved(self) -> None:
        assert name_agreement("Ambio", None) is Agreement.MISSING
        assert name_agreement(None, "Ambio") is Agreement.NOT_STATED
