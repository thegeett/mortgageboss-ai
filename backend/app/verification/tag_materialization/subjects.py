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

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.verification.snapshot.fields import Field
from app.verification.snapshot.model import DocumentEntry, Snapshot, TransactionRecord
from app.verification.snapshot.pii import PiiField
from app.verification.snapshot.traversal import all_transactions

# The loan-level production subject key (a single subject, like the rule-engine LOAN_SUBJECT).
LOAN_SUBJECT = "loan"

# The classifier's unclassified document-type value (str form; a document may also be None-typed). The
# doc-type filters (here + LP-377-D's dispatcher gate) FAIL OPEN on it — an abstained classification is
# never used to drop a document.
_UNKNOWN_DOC_TYPE = "unknown"

RawField = Field | PiiField
Subject = tuple[str, object]  # (content_id, the raw object to read from)


@dataclass(frozen=True)
class SubjectType:
    """One subject type's production hooks."""

    enumerate: Callable[[Snapshot], list[Subject]]
    read_field: Callable[[object, str], RawField | None]
    # ``applies_to`` (LP-385) = the group's declared document types (or None = all). Only a context that
    # GATHERS documents (the borrower context) uses it — to filter the gathered set to the group's relevant
    # doc-types; every other subject ignores it.
    build_context: Callable[[object, frozenset[str] | None], dict[str, object]]


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


def _txn_context(raw: object, _applies_to: frozenset[str] | None) -> dict[str, object]:
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


def _doc_context(raw: object, _applies_to: frozenset[str] | None) -> dict[str, object]:
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


def _loan_context(raw: object, _applies_to: frozenset[str] | None) -> dict[str, object]:
    assert isinstance(raw, Snapshot)
    if raw.mismo.absent:
        return {}
    return {name: _field_value(field) for name, field in raw.mismo.facts.items()}


def _field_value(field: RawField) -> object:
    if isinstance(field, PiiField):
        return field.display if field.is_present else None
    return field.value if field.is_present else None


# --------------------------------------------------------------------------- #
# borrower (LP-332) — one subject per borrower, keyed by borrower_id, reading MISMO borrower.{n}.*
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BorrowerSubject:
    """A borrower production subject: the resolved id + its MISMO index + the snapshot to read from.

    The id is the ``belongs_to`` UUID (from the LP-332 ``borrower.{n}.borrower_id`` link), so a tag
    keyed under it MEETS the LP-331 consumer (``_per_borrower`` reads ``by_subject[borrower_id]``). The
    index is how this borrower's facts are read (``borrower.{index}.<field>``); the snapshot lets a
    borrower recipe also gather this borrower's DOCUMENTS (its ``belongs_to`` facts)."""

    borrower_id: str
    index: int
    snapshot: Snapshot


_BORROWER_ID_KEY = re.compile(r"^borrower\.(\d+)\.borrower_id$")


def _borrower_enumerate(snapshot: Snapshot) -> list[Subject]:
    """One subject per MISMO borrower that carries the LP-332 id link, keyed by that borrower_id.

    A borrower group WITHOUT a ``borrower_id`` fact is SKIPPED (no attribution is safe → its
    borrower-keyed tags stay absent → the rule couldnt_checks; never a name-guessed attribution).

    Enumerates EVERY ``borrower.{n}.borrower_id`` fact present (sorted by index) rather than assuming
    contiguous indices from 1 — a gap (a co-borrower dropped mid-build, an emitter change) must not
    silently truncate the borrower set, which would leave a real borrower un-checked with no signal."""
    if snapshot.mismo.absent:
        return []
    indices = sorted(
        int(m.group(1)) for name in snapshot.mismo.facts if (m := _BORROWER_ID_KEY.match(name))
    )
    subjects: list[Subject] = []
    seen: set[str] = set()
    for index in indices:
        id_field = snapshot.mismo.facts[f"borrower.{index}.borrower_id"]
        borrower_id = str(_field_value(id_field) or "")  # None/PII-display-safe extraction
        if (
            borrower_id and borrower_id not in seen
        ):  # a duplicate/blank id is unsafe → skip (fail-closed)
            seen.add(borrower_id)
            subjects.append((borrower_id, BorrowerSubject(borrower_id, index, snapshot)))
    return subjects


def _borrower_read_field(raw: object, field: str) -> RawField | None:
    assert isinstance(raw, BorrowerSubject)
    if raw.snapshot.mismo.absent:
        return None
    return raw.snapshot.mismo.facts.get(f"borrower.{raw.index}.{field}")


def _borrower_context(raw: object, applies_to: frozenset[str] | None) -> dict[str, object]:
    """The per-borrower AI context: this borrower's MISMO facts PLUS the documents ATTRIBUTED to them
    (LP-385). The generic per-borrower-over-documents primitive: a group asking a CROSS-document question
    (income_stability's 2-year history / decline / continuance) sees all of ONE borrower's documents at
    once — the per-document framing that made those questions structurally unanswerable (LP-378: 0/120).

    Attribution is by ``belongs_to`` — the LP-202 EVIDENCE-based document→borrower link (the SSN/name
    resolved at upload), NEVER a guess. A document with no ``belongs_to`` (unattributed) is NOT gathered
    for any borrower — the context is honestly incomplete and the tag abstains with a reason, never a
    trend fabricated from a mis-attributed document (LP-332/LP-336: "never a guessed attribution"). Fields
    carry PiiField MASKED displays only (via ``_field_value``) — no raw PII leaves in the prompt.

    ``applies_to`` (the group's declared doc-types, LP-385 generalizing LP-377-D) filters the gathered set
    to the group's relevant document types, so a non-income document (a bank statement / tax bill / ID) is
    NOT sent to income_stability — the prompt's "ignore non-income" instruction is not a load-bearing
    filter (LP-378 measured that backstop failing: ~20 fabricated income values). FAILS OPEN exactly like
    the LP-377-D gate: an unknown / ``None`` type is kept (the classifier abstained — never dropped on a
    guess); only a KNOWN, confident type outside ``applies_to`` is excluded. ``applies_to=None`` → keep all.
    """
    assert isinstance(raw, BorrowerSubject)
    snapshot = raw.snapshot
    mismo: dict[str, object] = {}
    if not snapshot.mismo.absent:
        prefix = f"borrower.{raw.index}."
        mismo = {
            name[len(prefix) :]: _field_value(field)
            for name, field in snapshot.mismo.facts.items()
            if name.startswith(prefix)
        }
    documents: list[dict[str, object]] = []
    if not snapshot.documents.absent:
        for entry in snapshot.documents.entries:
            attributed = entry.belongs_to is not None and any(
                str(ref.borrower_id) == raw.borrower_id for ref in entry.belongs_to
            )
            if not attributed:
                continue  # unattributed → not this borrower's → the context is honestly incomplete
            # Fail-open doc-type filter (LP-385): drop only a KNOWN, confident type the group's applies_to
            # excludes; keep None/"unknown" (classifier abstained) and everything when applies_to is None.
            if (
                applies_to is not None
                and entry.document_type not in (None, _UNKNOWN_DOC_TYPE)
                and entry.document_type not in applies_to
            ):
                continue
            documents.append(
                {
                    "document_type": entry.document_type,
                    "fields": {name: _field_value(field) for name, field in entry.fields.items()},
                }
            )
    return {"borrower_mismo": mismo, "documents": documents}


_SUBJECT_TYPES: dict[str, SubjectType] = {
    "transaction": SubjectType(_txn_enumerate, _txn_read_field, _txn_context),
    "document": SubjectType(_doc_enumerate, _doc_read_field, _doc_context),
    "loan": SubjectType(_loan_enumerate, _loan_read_field, _loan_context),
    "borrower": SubjectType(_borrower_enumerate, _borrower_read_field, _borrower_context),
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
