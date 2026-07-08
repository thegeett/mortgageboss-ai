"""Deterministic transaction-kind classification (LP-125R FIX 1).

The deposit / not-deposit decision determines whether a FINANCIAL finding fires (AS-1 large-deposit,
and AS-2/3/7/8/10 later), so it must be DETERMINISTIC and inspectable — never an AI call. The AI already
did its job (it extracted the amount + the free-text ``transaction_type``); classifying that text into a
normalized *kind* is pure deterministic logic layered on top.

The classifier is materialized ONCE by the builder onto ``TransactionFacts.transaction_kind`` (the
document-field pattern), so every transaction rule reads the same typed kind instead of re-matching raw
free-text (which is how the AS-1 exact-``"deposit"`` false-green happened: a large wire typed ``"credit"``
/ ``"ACH credit"`` / ``"mobile deposit"`` / ``"DEP"`` was silently skipped).

Method (amount-direction-anchored, pattern-refined, conservative):
1. **Pattern list, word-boundary matched** (most-specific credit/debit kinds first) — inspectable, editable.
2. **No text signal → anchor on amount direction:** ``amount < 0`` → withdrawal (money out); ``amount > 0``
   → DEPOSIT (the CONSERVATIVE default — an unrecognized credit counts as a deposit, never silently
   skipped; a novel phrasing like "remote capture credit" still gets assessed).
3. **Genuinely unclassifiable** (unrecognized text AND no usable amount) → ``UNKNOWN`` — the evaluator
   decides how to route it (AS-1: a deposit-candidate with no amount is couldn't-check, never a silent
   pass).
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.verification.fact_namespace.canonicalize import normalize_text
from app.verification.fact_namespace.snapshot import TransactionKind

# Ordered (kind, keywords) — FIRST match wins, so credits are checked before debits (e.g. "check
# deposit" is a DEPOSIT, not a check/withdrawal) and specific credits before the generic deposit
# ("direct deposit" is PAYROLL, "interest credit" is INTEREST). Keywords are word-boundary matched, so
# "dep" matches "dep" but not "deposit", and an employer/word substring can't misfire.
_ORDERED_PATTERNS: tuple[tuple[TransactionKind, tuple[str, ...]], ...] = (
    (TransactionKind.PAYROLL, ("payroll", "direct deposit", "dir dep", "salary", "wages")),
    (TransactionKind.INTEREST, ("interest", "int pd", "dividend")),
    (
        TransactionKind.TRANSFER_IN,
        ("transfer from", "xfer from", "transfer in", "incoming wire", "wire in", "zelle from"),
    ),
    (
        TransactionKind.TRANSFER_OUT,
        ("transfer to", "xfer to", "transfer out", "outgoing wire", "wire out", "zelle to"),
    ),
    (
        TransactionKind.DEPOSIT,
        (
            "deposit",
            "dep",
            "credit",
            "mobile deposit",
            "remote deposit",
            "remote capture",
            "ach credit",
            "atm deposit",
        ),
    ),
    (TransactionKind.FEE, ("fee", "service charge", "overdraft", "nsf", "charge")),
    (
        TransactionKind.WITHDRAWAL,
        (
            "withdrawal",
            "withdraw",
            "atm",
            "debit",
            "check",
            "chk",
            "purchase",
            "pos",
            "bill pay",
            "payment",
            "ach debit",
        ),
    ),
)


def classify_transaction_kind(
    transaction_type: str | None, amount: Decimal | None
) -> TransactionKind:
    """Deterministically classify one transaction into a normalized :class:`TransactionKind`.

    See the module docstring for the method. Pure function — no I/O, no AI.
    """
    text = normalize_text(transaction_type)
    if text:
        for kind, keywords in _ORDERED_PATTERNS:
            if any(re.search(rf"\b{re.escape(kw)}\b", text) for kw in keywords):
                return kind
    # No recognizable text — anchor on amount direction (conservative: unrecognized credit → deposit).
    if amount is not None:
        if amount < 0:
            return TransactionKind.WITHDRAWAL
        if amount > 0:
            return TransactionKind.DEPOSIT
    return TransactionKind.UNKNOWN
