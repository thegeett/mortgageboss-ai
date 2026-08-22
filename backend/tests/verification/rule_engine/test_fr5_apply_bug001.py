"""bug-001 — FR-5 can now add the liability its own fix text asks for.

FR-5 says "obtain the account details and add it — an undisclosed monthly obligation understates the
debt-to-income ratio". Until now the only way to do that was to leave the finding, open the overview
tab's stated-financials editor, click Add under Liabilities, and re-type a payee and an amount the
system had already extracted.

Two things had to exist first: `txn.counterparty` (the payee, which no group produced), and an apply
slot on a JUDGMENT rule (only DeterministicEval had one, because DT-6 — the first Apply — happens to
be deterministic).
"""

from __future__ import annotations

from app.verification.rules.specs import load_rule_spec


def test_fr5_declares_the_add_its_fix_text_asks_for() -> None:
    apply = load_rule_spec("FR-5").judgment.apply

    assert apply is not None and apply.action == "add_liability"
    # WHO it is owed to and WHAT the DTI reads. Missing either resolves to no apply at all rather
    # than a debt with no payment, or a payment owed to nobody.
    assert apply.fields["holder_name"].tag == "txn.counterparty"
    assert apply.fields["monthly_payment"].tag == "txn.amount"


def test_the_liability_type_is_other_rather_than_a_guess() -> None:
    """`add_liability` defaults to "Installment", which for a credit-card autopay is simply wrong. A
    transaction cannot tell revolving from installment — `apparent_category` says `debt_payment` and
    stops there — so "Other" is the only kind FR-5 can state truthfully, and it is a value the data
    already uses."""
    apply = load_rule_spec("FR-5").judgment.apply
    assert apply is not None
    assert apply.fields["liability_type"].literal == "Other"


def test_no_unpaid_balance_is_declared() -> None:
    """A statement line shows a PAYMENT, never a balance. Declaring it would resolve to nothing on
    every subject and silently remove the button; leaving it out adds the row without one, which is
    why the fix text still asks for the account details."""
    apply = load_rule_spec("FR-5").judgment.apply
    assert apply is not None and "unpaid_balance" not in apply.fields


def test_the_exemption_is_what_makes_a_duplicate_add_unreachable() -> None:
    """THE SAFETY, and it is structural rather than a second guard that could drift.

    `exempt_when` clears a payment whose payee matched the 1003 `exact` or `probable`, so a FINDING
    only exists where the match is `none` or `unknown` — FR-5 cannot offer to add a debt the
    application already states. That is the LP-564 trap: CR-1 offering an Apply on its abstention
    would have inserted a liability that may already be there, duplicating the debt and inflating the
    very ratio the apply exists to correct."""
    judgment = load_rule_spec("FR-5").judgment
    exemptions = judgment.exempt_when
    values = {c.value for c in (exemptions if isinstance(exemptions, tuple) else (exemptions,))}

    assert values == {"exact", "probable"}
    assert all(c.tag_id == "txn.stated_liability_match" for c in exemptions)
