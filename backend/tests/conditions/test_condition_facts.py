"""What code reads from a condition's own words (LP-919): pure functions, no model, no database."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.conditions import facts
from tests.conditions.fixture_helpers import sheet_text

_7086 = (
    "Short funds to close and/or reserves. Document sufficient funds for the closing of this "
    "transaction. Total funds required are $38,210.40 (Includes $38,210.40 in funds to close and $0.00 "
    "in reserves plus any unverified POC items). This must be verified by most recent 2 months bank "
    "statement. $11,062.18 currently verified."
)
_6178 = (
    "Provide updated homeowners insurance declarations page reflecting: the HOI policy provided is not "
    "effective until 09/30/2026. If closing is prior to this date, the current HOI policy must be "
    "provided reflecting current coverage."
)


def test_7086_shortfall_is_computed_from_the_lenders_two_figures() -> None:
    shortfall = facts.shortfall_in(_7086)
    assert shortfall is not None
    assert (shortfall.required, shortfall.verified) == (Decimal("38210.40"), Decimal("11062.18"))
    assert shortfall.amount == Decimal("27148.22")


def test_no_shortfall_is_invented_when_a_figure_is_missing() -> None:
    assert facts.shortfall_in("Total funds required are $38,210.40.") is None


def test_6178_may_not_apply_when_closing_cannot_precede_the_policy() -> None:
    push_back = facts.date_push_back(_6178, date(2026, 9, 30))
    assert push_back is not None and push_back.policy_starts == date(2026, 9, 30)
    # A policy starting AFTER the earliest closing date does apply: closing could be earlier.
    assert facts.date_push_back(_6178, date(2026, 9, 15)) is None
    assert facts.date_push_back(_6178, None) is None


def test_amounts_and_last_four_come_from_the_text() -> None:
    assert facts.money_is_in("$2,850.00", "earnest money deposit in the amount of $2,850.00")
    assert facts.money_is_in("$2,850", "earnest money deposit in the amount of $2,850.00")
    assert not facts.money_is_in("$27,148.22", _7086)
    assert facts.last4_in("statement from Capital One® #9912. A total") == "9912"
    assert facts.bank_in("statement from Capital One® #9912") == "Capital One"


def test_an_underwriter_note_is_given_its_meaning() -> None:
    assert facts.note_meaning("Not in Upload") == (
        "The lender did not find it in the last upload — asked again below."
    )
    assert facts.note_meaning("see prior") is None


def test_business_days_skip_the_weekend() -> None:
    # 08/28/2026 is a Friday; four business days later is Thursday 09/03 (S3-04).
    assert facts.business_days_after(date(2026, 8, 28), 4) == date(2026, 9, 3)


def test_the_fixture_still_says_what_these_tests_assume() -> None:
    text = " ".join(sheet_text("uwm_round1_2026-08-28.txt").split())
    assert "$11,062.18 currently verified" in text and "not effective until 09/30/2026" in text
