"""LP-574 — a recurring payment is not a debt payment just because it recurs.

WHAT HAPPENED. On LF-WCHG, FR-5 (recurring undisclosed debit) raised a finding on a $116.43 monthly
payment to GEICO. FR-5 was correct: its applicability is `txn.is_money_in == out` AND
`txn.apparent_category == debt_payment` AND `txn.is_recurring == yes`, and all three held. The
finding existed only because an insurance premium had been tagged `debt_payment`.

THE PROMPT, NOT JUST THE MODEL. The two candidate definitions were "a payment to an apparent
CREDITOR ... identified from a lender-like payee" and "an ordinary purchase / merchant". An insurance
premium is neither — it is not a creditor, and a monthly premium does not read as an ordinary
purchase. Insurance had no home, so the model reached for the nearest bucket and said so in its own
reasoning: "While insurance is not a traditional debt, premium payments to insurers can be considered
recurring obligations similar to debt payments." It returned 0.70 confidence, which was it telling us
it was uncomfortable.

The same gap swallows utilities, subscriptions and memberships — every recurring NON-CREDIT
obligation. These tests pin the distinction the prompt now draws, because the fix is a handful of
words in a shared prompt and nothing else would notice if they were edited away.

⚠️ SHARED INPUT: `txn.apparent_category` also feeds AS-1, AS-2, AS-5, AS-12 and IN-1. Narrowing
`debt_payment` to BORROWED MONEY is the right direction for all of them, but it is a change to five
live rules' inputs, not just FR-5's.
"""

from __future__ import annotations

from app.ai import tag_production
from app.ai.tag_production import APPARENT_CATEGORY_VALUES


def _prompt() -> str:
    """The single converged Stage-A prompt text, as the model receives it."""
    import inspect

    return inspect.getsource(tag_production)


def test_debt_payment_is_defined_as_borrowed_money() -> None:
    """The category must name what it IS, not what it looks like. "A payment to a creditor" alone
    let a recurring premium in; "borrowed money being repaid" does not."""
    text = _prompt()

    assert "BORROWED MONEY BEING REPAID" in text


def test_the_prompt_names_the_recurring_non_debt_cases_explicitly() -> None:
    """Naming them is the fix. A definition that merely implies the boundary is what produced the
    GEICO finding — the model had to infer, and inferred wrong at 0.70."""
    text = _prompt()

    for case in ("insurance premium", "utility", "subscription"):
        assert case in text.lower(), f"the prompt no longer names {case!r} as a non-debt recurrence"


def test_vendor_covers_recurring_payments_not_only_purchases() -> None:
    """`vendor` was "an ordinary purchase / merchant", which does not read as covering a monthly
    premium. If it narrows back to a one-off purchase, insurance is homeless again."""
    text = _prompt()

    assert "INCLUDING a recurring one" in text


def test_the_enum_itself_is_unchanged() -> None:
    """A DEFINITION change, not a vocabulary change. Adding an `insurance` value would have been the
    tempting fix and the wrong one: it re-keys nothing, but every rule reading the enum would need to
    learn it, and `vendor` already means "paid for goods or services"."""
    assert "vendor" in APPARENT_CATEGORY_VALUES
    assert "debt_payment" in APPARENT_CATEGORY_VALUES
    assert "insurance" not in APPARENT_CATEGORY_VALUES


def test_the_lender_like_payee_guard_survives() -> None:
    """The risk of the other direction: a real auto or personal loan to an unfamiliar lender landing
    in `vendor`. The payee test is what keeps that from happening, so it must not be lost while
    narrowing the category."""
    text = _prompt()

    assert "lender-like payee" in text
