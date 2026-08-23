"""bug-001 — capture the ACH originator id, so two debts to one institution can be told apart.

A payee name cannot separate them: a Chase card and a Chase auto loan are both "Chase", and grouping
FR-5's findings on the name alone would merge them into one obligation and UNDERSTATE the DTI — the
dangerous direction.

The statements print the id beside the payee, and we were dropping it:

    06/03  Chase Credit Crd Autopay   PPD ID: 4760039224   -107.07
    06/11  Chase Credit Crd Autopay   PPD ID: 4760039224     -8.75

On the real file it settled the opposite question. All four Chase payments carry the SAME originator,
so what looked like two accounts — two amounts, two days of the month — is ONE autopay charged twice
a month, reported four times.
"""

from __future__ import annotations

from app.verification.snapshot.documents_section import (
    _IDENTITY_EXCLUDED_TXN_FIELDS,
    _txn_content,
    transaction_field_sets,
)

_ROWS = {
    "transactions": [
        {
            "date": "2026-06-03",
            "description": "Chase Credit Crd Autopay PPD ID: 4760039224",
            "amount": "107.07",
            "transaction_type": "withdrawal",
            "originator_id": "4760039224",
        },
        {
            "date": "2026-06-11",
            "description": "Chase Credit Crd Autopay PPD ID: 4760039224",
            "amount": "8.75",
            "transaction_type": "withdrawal",
            "originator_id": "4760039224",
        },
    ]
}


def test_the_originator_reaches_the_snapshot() -> None:
    rows = transaction_field_sets(_ROWS, "bank_statement")
    assert rows is not None
    assert [r["originator_id"].value for r in rows] == ["4760039224", "4760039224"]


def test_a_line_with_no_originator_is_absent_not_empty() -> None:
    """A cheque, a card purchase and an in-branch transfer print no company id. Absent != empty."""
    rows = transaction_field_sets(
        {"transactions": [{"date": "2026-06-04", "description": "CHECK 1042", "amount": "50.00"}]},
        "bank_statement",
    )
    assert rows is not None and not rows[0]["originator_id"].is_present


def test_the_originator_is_NOT_part_of_a_transactions_identity() -> None:
    """THE COSTLY PART, and why it is excluded.

    A transaction's content id IS a finding's identity. Folding a new field into it re-keys every
    per-deposit finding on every file — they retire as `no_longer_applies` and mint again, stranding
    any sign-off a processor had made on the old copy. That happened once already in this ticket,
    when the borrower re-link changed six documents' ids and doubled the finding count on a real file.

    And it buys nothing: within one statement, date + amount + direction + description already
    separate every line. The originator says WHO the counterparty is, not WHICH ROW this is."""
    assert "originator_id" in _IDENTITY_EXCLUDED_TXN_FIELDS

    rows = transaction_field_sets(_ROWS, "bank_statement")
    without = transaction_field_sets(
        {
            "transactions": [
                {k: v for k, v in r.items() if k != "originator_id"} for r in _ROWS["transactions"]
            ]
        },
        "bank_statement",
    )
    assert rows is not None and without is not None
    # Same rows, one carrying the originator and one not → the SAME identity.
    assert _txn_content(rows[0]) == _txn_content(without[0])


def test_two_debts_to_one_institution_are_distinguishable() -> None:
    """What the field is for: the same payee name, two different creditors."""
    rows = transaction_field_sets(
        {
            "transactions": [
                {
                    "date": "2026-06-03",
                    "description": "Chase Credit Crd Autopay",
                    "amount": "107.07",
                    "originator_id": "4760039224",
                },
                {
                    "date": "2026-06-05",
                    "description": "Chase Auto Finance",
                    "amount": "612.00",
                    "originator_id": "9911223344",
                },
            ]
        },
        "bank_statement",
    )
    assert rows is not None
    assert rows[0]["originator_id"].value != rows[1]["originator_id"].value
