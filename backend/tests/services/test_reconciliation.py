"""The reconciliation read model's comparison rules (LP-UI-017, ADR-391).

These are the rules a processor's judgement rests on: whether two numbers agree,
and whether an employer written two ways is one employer. They are pure, so they
are tested directly rather than through the endpoint.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.models.stated_financials import StatedAsset
from app.services.reconciliation import (
    INCOME_VARIANCE_PERCENT,
    Agreement,
    RowSource,
    RowUnit,
    _assets_row,
    _employer_row,
    _FoundField,
    _income_row,
    income_agreement,
    money_agreement,
    name_agreement,
)
from app.verification.cross_source.rules import XSRC_INCOME_STATED_VS_DOCUMENTED


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
        assert income_agreement(Decimal("11100"), Decimal("10000")) is Agreement.DIFFERS

    def test_a_variance_the_engine_rounds_down_matches_here_too(self) -> None:
        """11001 vs 10000 is 10.01%, which the engine QUANTIZES to 10.0 and passes.

        This case previously asserted `DIFFERS`, which pinned a real disagreement
        rather than a property: the engine emits no finding for these two numbers
        and the ledger called them a discrepancy. Updated deliberately — the
        load-bearing property is "the ledger and the finding agree about the same
        two numbers", and the old expectation was the one violating it.
        """
        assert income_agreement(Decimal("11001"), Decimal("10000")) is Agreement.MATCH

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


class TestTheAssetsRow:
    """The stated side must be the quantity the label names.

    The first version summed EVERY StatedAsset — checking, savings, retirement,
    gift funds — and compared the total to one bank statement's ending balance.
    For any borrower with more than one account that differs by construction, and
    the row reported it as a discrepancy on a compliance screen. Same shape as
    the income defect ADR-328 forbids: two numbers that are not about the same
    thing, subtracted confidently.
    """

    @staticmethod
    def _asset(asset_type: str | None, value: str | None) -> StatedAsset:
        return StatedAsset(asset_type=asset_type, value=value)

    @staticmethod
    def _statement(balance: str) -> dict[str, list[_FoundField]]:
        return {
            "ending_balance": [
                _FoundField(
                    value=balance,
                    source=RowSource(document_id=uuid4(), filename="statement.pdf"),
                )
            ]
        }

    def test_one_checking_account_is_compared(self) -> None:
        row = _assets_row([self._asset("CheckingAccount", "5000.00")], self._statement("5000.00"))
        assert row.agreement is Agreement.MATCH

    def test_a_retirement_fund_is_not_added_to_the_checking_balance(self) -> None:
        # $5,000 checking + $80,000 401(k) against a $5,000 statement is a MATCH.
        # Summing them reported an $80,000 discrepancy that does not exist.
        row = _assets_row(
            [self._asset("CheckingAccount", "5000.00"), self._asset("RetirementFund", "80000.00")],
            self._statement("5000.00"),
        )
        assert row.agreement is Agreement.MATCH

    def test_two_depository_accounts_are_not_compared_at_all(self) -> None:
        # Which account the one statement belongs to is not recorded, so any
        # comparison would be a guess presented as a finding.
        row = _assets_row(
            [self._asset("CheckingAccount", "5000.00"), self._asset("SavingsAccount", "9000.00")],
            self._statement("5000.00"),
        )
        assert row.agreement is Agreement.MISSING
        assert "not comparable" in (row.source_note or "")
        assert row.stated_value == "14000.00", "the total is still shown, just not compared"

    def test_assets_a_statement_cannot_evidence_say_so(self) -> None:
        # A gift of cash is a real asset. "No stated value" would read as an
        # omission on the application, which it is not.
        row = _assets_row([self._asset("GiftOfCash", "12000.00")], {})
        assert row.stated_value is None
        assert "depository" in (row.source_note or "")

    def test_a_genuine_disagreement_still_reads_as_one(self) -> None:
        row = _assets_row([self._asset("CheckingAccount", "5000.00")], self._statement("1200.00"))
        assert row.agreement is Agreement.DIFFERS


class TestTheVarianceThresholdIsTheEngines:
    def test_it_is_read_off_the_rule_not_restated(self) -> None:
        """A copied constant agrees with its source only until someone edits one.

        The module previously declared `Decimal("10")` under a comment saying it
        was imported — the drift it was written to prevent, wearing the label of
        the fix.
        """
        threshold = XSRC_INCOME_STATED_VS_DOCUMENTED.threshold
        assert threshold is not None
        assert threshold.value == INCOME_VARIANCE_PERCENT

    def test_income_agreement_uses_it(self) -> None:
        # Both sides divide by the DOCUMENTED figure, so the offsets are built
        # from `found`. Getting this backwards is easy and gives a passing test
        # of the wrong arithmetic.
        found = Decimal("10000")
        inside = found * (1 + (INCOME_VARIANCE_PERCENT - 1) / 100)
        outside = found * (1 + (INCOME_VARIANCE_PERCENT + 1) / 100)
        assert income_agreement(inside, found) is Agreement.MATCH
        assert income_agreement(outside, found) is Agreement.DIFFERS

    def test_it_rounds_the_variance_the_way_the_engine_does(self) -> None:
        """A variance of 10.04% is `satisfied` to the engine, which rounds to 10.0.

        With a raw comparison this row called it `differs` — the same two
        numbers, one screen, two answers. Importing the threshold was not enough
        on its own; the rounding is part of the rule.
        """
        found = Decimal("10000")
        stated = Decimal("11004")  # 10.04% variance
        engine_variance = (abs(stated - found) / found * Decimal(100)).quantize(Decimal("0.1"))
        assert engine_variance == Decimal("10.0")
        assert income_agreement(stated, found) is Agreement.MATCH


class TestAPartialYearW2:
    """A W-2 is annual BY DEFINITION only when the borrower worked the whole year.

    For a mid-year hire, box 1 covers part of one and `/12` understates monthly
    income — the same unit error the row exists to avoid, one level down. It
    would report `differs` against a correctly stated income and send a processor
    after a discrepancy that is an artefact of the division.
    """

    @staticmethod
    def _found(wages: str, tax_year: str) -> dict[str, list[_FoundField]]:
        source = RowSource(document_id=uuid4(), filename="w2.pdf")
        return {
            "wages_tips_other_comp": [_FoundField(value=wages, source=source)],
            "tax_year": [_FoundField(value=tax_year, source=source)],
        }

    @staticmethod
    def _borrower(start: date | None) -> object:
        income = SimpleNamespace(employment_income=True, monthly_amount="10000.00")
        return SimpleNamespace(
            stated_income_items=[income],
            stated_employers=[SimpleNamespace(start_date=start)],
        )

    def test_a_full_year_w2_is_divided_by_twelve(self) -> None:
        row = _income_row([self._borrower(date(2019, 3, 1))], self._found("120000", "2025"))
        assert row.found_value is not None
        assert row.found_value == "10000.00"

    def test_employment_starting_in_the_w2_year_is_not_divided(self) -> None:
        row = _income_row([self._borrower(date(2025, 7, 1))], self._found("60000", "2025"))
        assert row.agreement is Agreement.MISSING
        assert row.found_value is None
        assert "partial year" in (row.source_note or "")

    def test_no_start_date_does_not_empty_the_row(self) -> None:
        # Absence of evidence is not evidence. Flagging every W-2 as uncheckable
        # because the application omitted a start date would delete the row.
        row = _income_row([self._borrower(None)], self._found("120000", "2025"))
        assert row.found_value is not None


class TestTheRowUnit:
    """Money rows must send a number the frontend's money formatter can read.

    `formatMoneyPrecise` (frontend/lib/format.ts) is the app's single money
    formatter and it falls back to printing its input verbatim when `Number()`
    cannot parse it. So a comma in these two columns does not raise anything —
    it silently drops the currency symbol from one screen and leaves the ledger
    the only place in the product showing bare amounts. The unit flag and the
    parseability are asserted together because they are one promise.

    Scope note: the insurance row passes an extractor's own string through
    untouched, so it carries the MONEY unit for alignment but cannot promise
    parseability. Only rows this module computes from `Decimal`s are covered.
    """

    @staticmethod
    def _parses(value: str | None) -> bool:
        """Parseable by JS `Number()` — no thousands separators, no symbol."""
        if value is None:
            return True
        try:
            Decimal(value)
        except InvalidOperation:
            return False
        return True

    def test_a_computed_income_row_is_money_and_parses(self) -> None:
        row = _income_row(
            [TestAPartialYearW2._borrower(date(2019, 3, 1))],
            TestAPartialYearW2._found("120000", "2025"),
        )
        assert row.unit is RowUnit.MONEY
        assert self._parses(row.stated_value)
        assert self._parses(row.found_value)

    def test_the_uncomparable_assets_row_is_money_and_parses(self) -> None:
        # The branch that builds its own ReconciliationRow rather than going
        # through `_row` — the one most likely to be missed when the unit moves.
        row = _assets_row(
            [
                TestTheAssetsRow._asset("CheckingAccount", "5000.00"),
                TestTheAssetsRow._asset("SavingsAccount", "9000.00"),
            ],
            TestTheAssetsRow._statement("5000.00"),
        )
        assert row.unit is RowUnit.MONEY
        assert self._parses(row.stated_value)
        assert self._parses(row.found_value)

    def test_the_prose_note_still_reads_as_a_sentence(self) -> None:
        # The columns went raw; the NOTE did not. A sentence saying "totalling
        # 14000.00" is the regression this guards.
        row = _assets_row(
            [
                TestTheAssetsRow._asset("CheckingAccount", "5000.00"),
                TestTheAssetsRow._asset("SavingsAccount", "9000.00"),
            ],
            TestTheAssetsRow._statement("5000.00"),
        )
        assert "14,000.00" in (row.source_note or "")

    def test_an_employer_is_not_money(self) -> None:
        assert _employer_row([], {}).unit is RowUnit.TEXT
