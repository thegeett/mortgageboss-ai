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
from app.verification.rule_engine.reasons import document_label
from app.verification.snapshot.content_id import DOC_PREFIX, LIABILITY_PREFIX, TXN_PREFIX

# An account subject key (LP-336) is ``account:<institution>:<masked>`` — display-safe by construction, but
# no ACTIVE rule enumerates per_account yet, so an honest generic suffices until one does.
_ACCOUNT_PREFIX = "account:"

# LP-330's missing-EXPECTED-document subject: ``missing:<document type>``. The subject IS the absent
# document, so its type is the whole identity and reads better than any generic — IN-8 and ID-7 shipped
# as "an item in this file" when the file could have named the VOE and the title commitment outright.
_MISSING_PREFIX = "missing:"

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")

# The transaction tags a deposit label reads (parsed, always present on an AS-1 finding's provenance).
_AMOUNT_TAG = "txn.amount"
_DATE_TAG = "txn.date"
_DIRECTION_TAG = "txn.is_money_in"
_CREDITOR_TAG = "liab.creditor_name"


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
    """A per-transaction subject label from its inline tags: *"Deposit of $20,000 on 3/27"* (generalising
    LP-376's amount chip). Degrades honestly — amount then amount-only then a generic — never a hash.

    DIRECTION-AWARE, AND IT WAS NOT. Every transaction subject was labelled a DEPOSIT, which was true
    while only money-IN rules enumerated them (AS-1, AS-2, AS-12 all scope `txn.is_money_in eq in`).
    FR-5 is the first rule that reads money OUT, and it would have called a $3,286.21 mortgage payment
    "Deposit of $3,286.21" — a label that contradicts the finding printed beside it.

    An UNKNOWN or absent direction reads "a transaction", not "a deposit": guessing the direction of a
    subject is exactly the fabrication the label layer exists to avoid.
    """
    direction = _tag_value(load_bearing_tags, _DIRECTION_TAG)
    amount = _tag_value(load_bearing_tags, _AMOUNT_TAG)
    if amount is None:
        return {"in": "a deposit", "out": "a payment"}.get(direction or "", "a transaction")
    # THE AMOUNT AND DATE IDENTIFY THE SUBJECT; THE NOUN ONLY DRESSES IT. A first version required
    # the direction before it would print either, and AS-12's findings do not carry
    # `txn.is_money_in` — their inline tags come from `reasoned_over`, which excludes the applicability
    # predicate on purpose (LP-509-A1: it has already filtered the subjects, so it carries no signal).
    # So every AS-12 subject collapsed to "a transaction", nine deposits became nine identical rows, and
    # four passes and five reviews read as if they were the same item in two places at once. Losing the
    # noun costs a word; losing the amount costs the reader the ability to tell one finding from another.
    noun = {"in": "Deposit of ", "out": "Payment of "}.get(direction or "", "")
    label = f"{noun}{_money(amount)}"
    date = _tag_value(load_bearing_tags, _DATE_TAG)
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
        # LP-583 — "Whole file", not "Loan-level". This label sits in a set beside filenames, dollar
        # amounts and creditor names, and "Loan-level" was the engine's subject-enumeration
        # vocabulary showing through: it names the SCOPE of the check rather than telling a
        # processor what the finding is about.
        return "Whole file"
    if subject_key.startswith(TXN_PREFIX):
        return _deposit_label(load_bearing_tags)
    if subject_key.startswith(DOC_PREFIX):
        # A document content-id → its filename; absent (removed / re-extracted since the run) → honest.
        return document_filenames.get(subject_key) or "a document no longer in this file"
    if subject_key.startswith(_MISSING_PREFIX):
        return f"{document_label(subject_key[len(_MISSING_PREFIX) :])} (not in the file)"
    if subject_key.startswith(LIABILITY_PREFIX):
        # LP-556 — the creditor, carried inline like a transaction's amount. CR-6 shipped four findings
        # reading "a debt on this file", which told a processor neither which account each concerned nor
        # that they were four different accounts. Degrades to the generic when the liability names no
        # holder (a MISMO row with no holder_name is a real case the enumerator already flags).
        if (creditor := _tag_value(load_bearing_tags, _CREDITOR_TAG)) is not None:
            return creditor
        # LP-531 — NOT the creditor's name, because no caller can reach it yet. A liability's holder
        # lives in the snapshot's tradeline / MISMO rows, and the read path builds no equivalent of
        # `document_filenames_by_content_id` for them. Naming the TYPE of thing is still strictly better
        # than the generic below: CR-6 shipped four findings reading "an item in this file", which tells
        # a processor neither what the item is nor that the four are different debts.
        return "a debt on this file"
    if subject_key.startswith(_ACCOUNT_PREFIX):
        return "a bank account"
    if _is_uuid(subject_key):
        return borrower_names.get(subject_key) or "a borrower no longer on this file"
    return (
        "an item in this file"  # an unrecognised key shape — surfaced honestly, never the raw key
    )


__all__ = ["resolve_subject_label"]
