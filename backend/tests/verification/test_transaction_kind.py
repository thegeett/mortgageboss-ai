"""LP-125R FIX 1 — the deterministic transaction-kind classifier (the shared transaction primitive).

Pins the builder-level classification every transaction rule (AS-1/2/3/7/8/10) reads, so a large money-in
typed anything-but-literal-"deposit" is never silently skipped, and a genuinely unclassifiable line is
UNKNOWN (never mislabeled).
"""

from decimal import Decimal

import pytest
from app.verification.fact_namespace.snapshot import TransactionKind
from app.verification.fact_namespace.transaction_kind import classify_transaction_kind

_POS = Decimal("1000")
_NEG = Decimal("-1000")


@pytest.mark.parametrize(
    ("ttype", "amount", "expected"),
    [
        # Credits that must all resolve to DEPOSIT (the AS-1 candidate) — the false-green closers.
        ("deposit", _POS, TransactionKind.DEPOSIT),
        ("Deposit", _POS, TransactionKind.DEPOSIT),
        ("credit", _POS, TransactionKind.DEPOSIT),
        ("ACH credit", _POS, TransactionKind.DEPOSIT),
        ("mobile deposit", _POS, TransactionKind.DEPOSIT),
        ("DEP", _POS, TransactionKind.DEPOSIT),
        ("remote capture", _POS, TransactionKind.DEPOSIT),
        (
            "check deposit",
            _POS,
            TransactionKind.DEPOSIT,
        ),  # "check" (debit word) must not win over deposit
        # Specific credits split out of DEPOSIT.
        ("direct deposit", _POS, TransactionKind.PAYROLL),
        ("Payroll", _POS, TransactionKind.PAYROLL),
        ("interest", _POS, TransactionKind.INTEREST),
        ("transfer from savings", _POS, TransactionKind.TRANSFER_IN),
        # Debits — never a deposit.
        ("withdrawal", _NEG, TransactionKind.WITHDRAWAL),
        ("ATM withdrawal", _POS, TransactionKind.WITHDRAWAL),
        ("service charge", _POS, TransactionKind.FEE),
        ("transfer to brokerage", _POS, TransactionKind.TRANSFER_OUT),
        # No text signal → anchor on amount direction (conservative: unrecognized credit → deposit).
        ("wire", _POS, TransactionKind.DEPOSIT),
        ("zelle", _POS, TransactionKind.DEPOSIT),
        (None, _POS, TransactionKind.DEPOSIT),
        ("mystery", _NEG, TransactionKind.WITHDRAWAL),
        # Unclassifiable — unrecognized text AND no usable amount.
        ("balance forward", None, TransactionKind.UNKNOWN),
        (None, None, TransactionKind.UNKNOWN),
        (None, Decimal("0"), TransactionKind.UNKNOWN),
    ],
)
def test_classify_transaction_kind(ttype, amount, expected) -> None:
    assert classify_transaction_kind(ttype, amount) is expected


def test_word_boundary_dep_does_not_match_deposit_as_dep() -> None:
    # "dep" abbreviation matches "dep" but the "deposit" pattern is what matches "deposit" — both DEPOSIT,
    # but a substring like "depreciation" must NOT be read as a deposit.
    assert classify_transaction_kind("depreciation adj", None) is TransactionKind.UNKNOWN
