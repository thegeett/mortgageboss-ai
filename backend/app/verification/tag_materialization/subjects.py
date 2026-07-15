"""Production SUBJECTS (LP-326) — enumerate the things a tag is produced FOR, and read their raw
facts. Registry-resolved, one entry per subject TYPE (transaction / document / loan) — a new family
on an existing subject type needs no new entry here.

Each subject type provides three things the generic producers need:

* ``enumerate`` — the (subject_content_id, raw_object) pairs to produce a tag for.
* ``read_field`` — the raw ``Field`` / ``PiiField`` for a parsed declaration's field name (or None).
* ``build_context`` — the per-subject dict the AI producer sends (the perceiver's context).

The subject content_id is the STABLE key the tag is stored under in ``tags.by_subject`` — the LP-325
gather contract keys id.* facts under the DOCUMENT subject so a gather tag and its filter tag
co-locate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.verification.snapshot.fields import Field
from app.verification.snapshot.model import DocumentEntry, Snapshot, TransactionRecord
from app.verification.snapshot.pii import PiiField
from app.verification.snapshot.traversal import all_transactions

# The loan-level production subject key (a single subject, like the rule-engine LOAN_SUBJECT).
LOAN_SUBJECT = "loan"

RawField = Field | PiiField
Subject = tuple[str, object]  # (content_id, the raw object to read from)


@dataclass(frozen=True)
class SubjectType:
    """One subject type's production hooks."""

    enumerate: Callable[[Snapshot], list[Subject]]
    read_field: Callable[[object, str], RawField | None]
    build_context: Callable[[object], dict[str, object]]


# --------------------------------------------------------------------------- #
# transaction
# --------------------------------------------------------------------------- #
_TXN_FIELDS = {
    "date": "date",
    "amount": "amount",
    "direction": "direction",
    "description": "description",
}


def _txn_enumerate(snapshot: Snapshot) -> list[Subject]:
    return [(txn.content_id, txn) for txn in all_transactions(snapshot)]


def _txn_read_field(raw: object, field: str) -> RawField | None:
    assert isinstance(raw, TransactionRecord)
    attr = _TXN_FIELDS.get(field)
    return getattr(raw, attr) if attr is not None else None


def _txn_context(raw: object) -> dict[str, object]:
    assert isinstance(raw, TransactionRecord)
    return {
        "date": _field_value(raw.date),
        "amount": _field_value(raw.amount),
        "direction": _field_value(raw.direction),
        "description": _field_value(raw.description),
    }


# --------------------------------------------------------------------------- #
# document
# --------------------------------------------------------------------------- #
def _doc_enumerate(snapshot: Snapshot) -> list[Subject]:
    if snapshot.documents.absent:
        return []
    return [(entry.content_id, entry) for entry in snapshot.documents.entries]


def _doc_read_field(raw: object, field: str) -> RawField | None:
    assert isinstance(raw, DocumentEntry)
    return raw.fields.get(field)


def _doc_context(raw: object) -> dict[str, object]:
    assert isinstance(raw, DocumentEntry)
    # Send the document's present fields as {name: value/display} — PiiFields contribute only their
    # MASKED display (never a raw value), so nothing raw-PII leaves in the AI prompt.
    fields: dict[str, object] = {"document_type": raw.document_type}
    for name, field in raw.fields.items():
        if isinstance(field, PiiField):
            fields[name] = field.display if field.is_present else None
        elif field.is_present:
            fields[name] = field.value
    return fields


# --------------------------------------------------------------------------- #
# loan (a single subject) — reads MISMO facts
# --------------------------------------------------------------------------- #
def _loan_enumerate(snapshot: Snapshot) -> list[Subject]:
    return [(LOAN_SUBJECT, snapshot)]


def _loan_read_field(raw: object, field: str) -> RawField | None:
    assert isinstance(raw, Snapshot)
    if raw.mismo.absent:
        return None
    return raw.mismo.facts.get(field)


def _loan_context(raw: object) -> dict[str, object]:
    assert isinstance(raw, Snapshot)
    if raw.mismo.absent:
        return {}
    return {name: _field_value(field) for name, field in raw.mismo.facts.items()}


def _field_value(field: RawField) -> object:
    if isinstance(field, PiiField):
        return field.display if field.is_present else None
    return field.value if field.is_present else None


_SUBJECT_TYPES: dict[str, SubjectType] = {
    "transaction": SubjectType(_txn_enumerate, _txn_read_field, _txn_context),
    "document": SubjectType(_doc_enumerate, _doc_read_field, _doc_context),
    "loan": SubjectType(_loan_enumerate, _loan_read_field, _loan_context),
}

KNOWN_CONTEXT_BUILDERS = frozenset(_SUBJECT_TYPES)


def subject_type(key: str) -> SubjectType:
    """Resolve a subject-type key (raises on an unknown key)."""
    st = _SUBJECT_TYPES.get(key)
    if st is None:
        raise KeyError(f"unknown production subject {key!r} (known: {sorted(_SUBJECT_TYPES)})")
    return st


__all__ = [
    "KNOWN_CONTEXT_BUILDERS",
    "LOAN_SUBJECT",
    "RawField",
    "Subject",
    "SubjectType",
    "subject_type",
]
