"""Human subject labels for governed rule findings (LP-377-B).

A governed finding's ``subject_key`` is a STABLE identity (LP-312 content-id / LP-322 reconciler key): a
document content-id (``doc…``), a transaction content-id (``txn…``), a borrower UUID, ``"loan"``, or an
account key. Legible to the engine, unreadable to a processor — *"a document could not be classified"* over
30 documents names none of them. This resolves a processor-facing LABEL per SUBJECT TYPE, dispatched on the
KEY'S SHAPE (never a rule-id branch — the sanctioned declared-key-resolved-by-registry pattern).

Read-time only, never persisted: the label is cosmetic; ``subject_key`` stays the reconciler's key (the LABEL
must never become the KEY, LP-322). The label is human vocabulary — a filename, an amount, a borrower's name,
"Loan-level" — and NEVER a content-id, a UUID, or a dotted tag id. An unresolvable subject (a document or
borrower gone from the file — a Tab-3 ``no_longer_applies`` finding's subject is gone BY DEFINITION) reads
honestly (*"a document no longer in this file"*), never the hash.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.verification.rule_engine.enumerators import LOAN_SUBJECT
from app.verification.snapshot.content_id import DOC_PREFIX, TXN_PREFIX

# An account subject key (LP-336) is ``account:<institution>:<masked>`` — display-safe by construction, but
# no ACTIVE rule enumerates per_account yet, so an honest generic suffices until one does.
_ACCOUNT_PREFIX = "account:"

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")

# The transaction tags a deposit label reads (parsed, always present on an AS-1 finding's provenance).
_AMOUNT_TAG = "txn.amount"
_DATE_TAG = "txn.date"


def _tag_value(load_bearing_tags: Sequence[Mapping[str, Any]], tag_id: str) -> str | None:
    """The value of a load-bearing tag by id (the finding carries them inline), or None if absent/empty."""
    for tag in load_bearing_tags:
        if tag.get("tag_id") == tag_id:
            value = tag.get("value")
            text = str(value).strip() if value is not None else ""
            return text or None
    return None


def _money(raw: str) -> str:
    """A raw amount string → a compact currency label (``"20000.00"`` → ``"$20,000"``; cents kept only when
    non-zero). Non-numeric input is returned as-is — still a value, never a hash."""
    try:
        amount = Decimal(raw)
    except (ArithmeticError, ValueError):
        return raw
    if amount == amount.to_integral_value():
        return f"${amount:,.0f}"
    return f"${amount:,.2f}"


def _short_date(raw: str) -> str:
    """An ISO date → ``M/D`` (parsed by parts, no timezone shift); the raw value verbatim if not ISO."""
    match = _ISO_DATE.match(raw)
    if match is None:
        return raw
    return f"{int(match.group(2))}/{int(match.group(3))}"


def _deposit_label(load_bearing_tags: Sequence[Mapping[str, Any]]) -> str:
    """A per-deposit subject label from its inline tags: *"Deposit of $20,000 on 3/27"* (generalising
    LP-376's amount chip). Degrades honestly — amount then amount-only then "a deposit" — never a hash."""
    amount = _tag_value(load_bearing_tags, _AMOUNT_TAG)
    if amount is None:
        return "a deposit"
    date = _tag_value(load_bearing_tags, _DATE_TAG)
    label = f"Deposit of {_money(amount)}"
    return f"{label} on {_short_date(date)}" if date is not None else label


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except (ValueError, TypeError):
        return False
    return True


def resolve_subject_label(
    subject_key: str | None,
    load_bearing_tags: Sequence[Mapping[str, Any]],
    *,
    borrower_names: Mapping[str, str] | None = None,
    document_filenames: Mapping[str, str] | None = None,
) -> str:
    """The processor-facing label for one governed finding's subject, dispatched on the key's SHAPE.

    ``borrower_names`` (borrower-id → name) and ``document_filenames`` (document content-id → filename) are
    the read path's DB-resolved maps (empty by default, so a maps-free caller still gets loan/deposit labels
    and an honest fallback for the rest). Every branch returns human vocabulary — never the raw key.
    """
    borrower_names = borrower_names or {}
    document_filenames = document_filenames or {}
    if not subject_key:
        return "this file"  # governed findings always carry a subject_key; a defensive floor
    if subject_key == LOAN_SUBJECT:
        return "Loan-level"
    if subject_key.startswith(TXN_PREFIX):
        return _deposit_label(load_bearing_tags)
    if subject_key.startswith(DOC_PREFIX):
        # A document content-id → its filename; absent (removed / re-extracted since the run) → honest.
        return document_filenames.get(subject_key) or "a document no longer in this file"
    if subject_key.startswith(_ACCOUNT_PREFIX):
        return "a bank account"
    if _is_uuid(subject_key):
        return borrower_names.get(subject_key) or "a borrower no longer on this file"
    return (
        "an item in this file"  # an unrecognised key shape — surfaced honestly, never the raw key
    )


__all__ = ["resolve_subject_label"]
