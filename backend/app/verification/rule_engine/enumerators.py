"""Subject enumerators (LP-324) — resolve a spec's executable ``subject_enumeration`` key.

A rule's spec declares WHERE its subjects come from as a KEY (not prose); the generic evaluators
resolve the key to an enumerator that yields ``(subject_id, subject_tags)`` pairs from a tagged
snapshot. Adding a rule over an existing subject shape needs no new Python — it reuses a key.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from app.verification.snapshot.model import Snapshot
from app.verification.snapshot.tag import Tag
from app.verification.snapshot.traversal import all_transactions

# The loan-level subject key: loan-level tags (occupancy.*, id.*, …) live under this single subject
# in the tags layer (distinct from the per-transaction content_id subjects). Introduced by LP-319.
LOAN_SUBJECT = "loan"

Subject = tuple[str, Mapping[str, Tag]]
Enumerator = Callable[[Snapshot], list[Subject]]


def _per_deposit(snapshot: Snapshot) -> list[Subject]:
    """One subject per bank-statement transaction (its stable content_id + its tag map)."""
    if snapshot.tags.absent:
        return [(txn.content_id, {}) for txn in all_transactions(snapshot)]
    return [
        (txn.content_id, snapshot.tags.by_subject.get(txn.content_id, {}))
        for txn in all_transactions(snapshot)
    ]


def _loan(snapshot: Snapshot) -> list[Subject]:
    """The single loan-level subject (loan-level tags live under ``LOAN_SUBJECT``)."""
    tags = {} if snapshot.tags.absent else snapshot.tags.by_subject.get(LOAN_SUBJECT, {})
    return [(LOAN_SUBJECT, tags)]


def _per_borrower(snapshot: Snapshot) -> list[Subject]:
    """One subject per borrower on the loan (LP-325) — the cross-source consistency subject.

    Borrowers are the distinct ``belongs_to`` refs across the documents (the reliable
    borrower↔document resolution, LP-202), in first-seen order. The tag map is empty: a consistency
    rule does NOT read a single borrower tag map — it GATHERS its fact across the borrower's SOURCE
    documents (each keyed by its own ``content_id``), which the evaluator does from the snapshot.
    """
    if snapshot.documents.absent:
        return []
    seen: dict[str, None] = {}  # borrower_id -> None, preserving first-seen (deterministic) order
    for entry in snapshot.documents.entries:
        if entry.belongs_to is None:
            continue
        for ref in entry.belongs_to:
            seen.setdefault(str(ref.borrower_id), None)
    return [(borrower_id, {}) for borrower_id in seen]


_ENUMERATORS: dict[str, Enumerator] = {
    "per_deposit": _per_deposit,
    "loan": _loan,
    "per_borrower": _per_borrower,
}


def enumerate_subjects(key: str, snapshot: Snapshot) -> list[Subject]:
    """Resolve the spec's ``subject_enumeration`` key to its subjects (raises on an unknown key)."""
    enumerator = _ENUMERATORS.get(key)
    if enumerator is None:
        raise KeyError(f"unknown subject_enumeration key {key!r} (known: {sorted(_ENUMERATORS)})")
    return enumerator(snapshot)


def is_known_enumerator(key: str) -> bool:
    return key in _ENUMERATORS


__all__ = ["LOAN_SUBJECT", "enumerate_subjects", "is_known_enumerator"]
