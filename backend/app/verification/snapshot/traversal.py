"""Shared read helpers over a built snapshot (LP-313/314).

Tiny, pure accessors the tag-production stages share so the traversal is defined once, not
copy-pasted per stage. No mutation, no DB, no AI.
"""

from __future__ import annotations

from app.verification.snapshot.fields import Field
from app.verification.snapshot.model import Snapshot, TransactionRecord


def field_value(field: Field) -> object:
    """A snapshot Field's present value, or ``None`` when the field is absent.

    The single "what a consumer/AI sees for this cell" rule: an absent field reads as ``None``,
    a present field (even present-but-null) reads as its value.
    """
    return field.value if field.is_present else None


def all_transactions(snapshot: Snapshot) -> list[TransactionRecord]:
    """Every surfaced transaction across the snapshot's documents, in deterministic order.

    Empty when the documents section is absent/failed or carries no transactions.
    """
    if snapshot.documents.absent:
        return []
    return [txn for entry in snapshot.documents.entries for txn in (entry.transactions or ())]
