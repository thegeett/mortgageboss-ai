"""Documents section assembler (LP-206, ADR-243).

Reads each ACTIVE document's already-extracted facts (LP-201 confidence) and its
already-stored borrower links (LP-202) and reshapes them into the snapshot's
``documents`` section. It does NOT extract and does NOT run matching — it READS the
stored links. It touches no other section and does no MISMO↔document correlation.

For each active, current document → a :class:`DocumentEntry`:

* ``document_type`` — the document's stored slug (e.g. ``"pay_stub"``, ``"1099"``).
* ``belongs_to`` — the RESOLVED borrowers, read from ``document_borrower_links``
  (LP-202), as a tuple of ``{borrower_id, name}`` (option-2); ``None`` when no
  borrower resolved (appraisal / no-match / unprocessable). Joint documents →
  multiple refs. The stored links are already soft-delete-safe (LP-202's read
  helper excludes a link to a soft-deleted document/borrower).
* ``fields`` — each extracted typed field → a ``Field`` (``source=extracted``)
  carrying LP-201's nullable confidence FAITHFULLY (null stays null — never
  fabricated). The RAW asserted name the document printed is surfaced here as
  ``asserted_name`` (distinct from ``belongs_to``'s resolved name).

## PII

Sensitive numbers are routed through ``PiiField`` (never a plain ``Field``) per an
explicit :data:`_PII_FIELDS` registry, so a raw value can't land as plaintext
``Field.value``. Two cases: a field the extractor stored **already masked**
(``account_number_masked`` / ``taxpayer_ssn_masked`` / ``id_number_masked``) →
``PiiField.pre_masked`` (canonical last-4 display, ``match_hash=None``); a field the
extractor stored **raw** ("as written" — W-2 ``employee_ssn`` / ``employer_ein``, 1099
``recipient_tin`` / ``payer_tin``) → ``PiiField.from_raw`` (masked here + a per-file
match-hash; the raw is discarded). ``social_security_wages`` / ``_tax_withheld`` are
dollar amounts, not ids, and stay ordinary fields. The institution tax ids
(``employer_ein`` / ``payer_tin``) are the employer/payer's id, not borrower PII, but
are masked anyway: a bare 9-digit tax id is exactly what the LP-209 at-rest guard flags
as a possible unmasked SSN, so masking keeps that guard strong (see the ``_PII_FIELDS``
note). The registry is drift-guarded by a test (any ``# SENSITIVE`` extractor field must
be routed here — the guard attributes the comment to its field even when ruff wraps the
field across lines).

## Absent ≠ empty

A field the extractor didn't produce (``value`` is null, or the field absent) is
omitted — distinct from a present empty string. Nothing is fabricated.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.parsing import coerce_optional_confidence
from app.models.borrower import Borrower
from app.models.document import Document
from app.models.document_borrower_link import DocumentBorrowerLink
from app.models.extraction import Extraction
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.services.borrower_name_matching import BORROWER_NAME_FIELDS
from app.verification.snapshot.content_id import (
    DOC_PREFIX,
    TXN_PREFIX,
    assign_content_ids,
    unordered_fingerprint,
)
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    SnapshotField,
    TransactionRecord,
)
from app.verification.snapshot.pii import PiiField, PiiKind

_EXTRACTED = FieldSource.EXTRACTED

# Document types that carry a nested transaction list (only bank statements today).
_TRANSACTION_DOC_TYPES = frozenset({"bank_statement"})
_TRANSACTIONS_KEY = "transactions"

# Extraction transaction_type values → credit (money in) / debit (money out). The
# extractor's vocabulary is "deposit / withdrawal / fee / interest / transfer / ..."
# (bank_statement prompt) — open-ended, so an UNKNOWN or genuinely AMBIGUOUS type (bare
# ``transfer`` / ``ach`` / ``wire`` — could be either direction) is DELIBERATELY absent
# from both sets → :func:`_direction` returns None (unclassifiable), never a guessed
# direction. Only unambiguous types are listed.
_CREDIT_TYPES = frozenset(
    {
        "deposit",
        "credit",
        "interest",
        "refund",
        "transfer_in",
        "direct_deposit",
        "dividend",
        "ach_credit",
        "mobile_deposit",
        "reversal",
    }
)
_DEBIT_TYPES = frozenset(
    {
        "withdrawal",
        "debit",
        "fee",
        "payment",
        "transfer_out",
        "check",
        "ach_debit",
        "purchase",
        "pos",
        "atm_withdrawal",
        "service_charge",
        "wire_out",
        "bill_pay",
    }
)

# Redacted OUT of a transaction description so a surfaced description is never a raw
# account/SSN/id at rest (real descriptions carry payroll/confirmation/account ids that
# would trip the LP-209 at-rest guard). Catches a dashed SSN AND any 9+-digit identifier,
# INCLUDING accounts/cards written in space- or dash-separated groups
# ("1234 5678 9012 3456", "1234-5678-9012") that a bare ``\d{9,}`` misses. Kept: dates
# (≤8 digits — "2026-05-05"), short ids ("SAV 5683"), the sourcing signal (PAYROLL /
# TRANSFER / VENMO). See ADR-248. (Broader than the persistence guard by design — this
# scrubs adversarial free text; a shared PII-pattern module is a deferred follow-up.)
_DESC_REDACT = re.compile(r"\d(?:[\s-]?\d){8,}")
_REDACTED = "[redacted]"

# The catch-all list key inside extracted_data (not a typed field).
_CATCH_ALL_KEY = "additional_sections"

# Extracted typed fields carrying borrower PII, and how to route each:
#   pre_masked=True  → the extractor already masked the value (display last-4, no hash);
#   pre_masked=False → the extractor stored it RAW ("as written") → mask + a per-file
#                      match-hash here so the raw never lands in the snapshot.
# Explicit (not pattern-matched) so a dollar amount like ``social_security_wages`` is
# never caught. Guarded against drift by test_documents_section: any extractor field
# annotated SENSITIVE must appear here. Institution tax ids (``employer_ein`` /
# ``payer_tin``) ARE routed too: though they are the employer/payer's id (not borrower
# PII), a 9-digit tax id is exactly what the LP-209 at-rest guard treats as a possible
# unmasked SSN — masking them keeps the strong guard intact rather than exempting them.
_PII_FIELDS: dict[str, tuple[PiiKind, bool]] = {
    "account_number_masked": (PiiKind.ACCOUNT, True),  # bank / investment / retirement
    "id_number_masked": (PiiKind.ACCOUNT, True),  # driver's-license number
    "taxpayer_ssn_masked": (PiiKind.SSN, True),  # tax return
    "employee_ssn": (PiiKind.SSN, False),  # W-2 — stored RAW ("SSN as written")
    "recipient_tin": (PiiKind.SSN, False),  # 1099 recipient — stored RAW ("TIN/SSN as written")
    "employer_ein": (PiiKind.ACCOUNT, False),  # W-2 employer tax id — masked ****NNNN
    "payer_tin": (PiiKind.ACCOUNT, False),  # 1099 payer tax id — masked ****NNNN
}


def _scalar(value: Any) -> str | int | float | bool | None:
    """A JSON scalar, or None to skip a nested (list/dict) extracted value."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    return None  # nested structures (e.g. bank-statement transactions) not surfaced here


def build_document_fields(
    extracted: dict[str, Any], document_type: str | None, *, loan_file_id: UUID
) -> dict[str, SnapshotField]:
    """Reshape one document's ``extracted_data`` into snapshot fields (pure).

    A field registered in :data:`_PII_FIELDS` is routed through ``PiiField`` — never a
    plain ``Field`` — so a raw SSN/TIN cannot land as plaintext ``Field.value``.
    ``loan_file_id`` salts the per-file match-hash for raw PII.
    """
    fields: dict[str, SnapshotField] = {}
    for key, entry in extracted.items():
        if key == _CATCH_ALL_KEY or not isinstance(entry, dict) or "value" not in entry:
            continue
        value = entry.get("value")
        if value is None:  # absent — omit
            continue
        confidence = coerce_optional_confidence(entry.get("confidence"))
        routing = _PII_FIELDS.get(key)
        if routing is not None:
            kind, pre_masked = routing
            if pre_masked:
                fields[key] = PiiField.pre_masked(
                    value, kind=kind, source=_EXTRACTED, confidence=confidence
                )
            else:  # raw value → mask + per-file match-hash; raw is discarded
                fields[key] = PiiField.from_raw(
                    value,
                    kind=kind,
                    loan_file_id=loan_file_id,
                    source=_EXTRACTED,
                    confidence=confidence,
                )
            continue
        scalar = _scalar(value)
        if scalar is None:  # nested/non-scalar — not surfaced here
            continue
        fields[key] = Field.present(scalar, source=_EXTRACTED, confidence=confidence)

    # ``asserted_name`` — a stable, doc-type-agnostic alias of the RAW borrower-name
    # field the document printed. Point it at the SAME already-built field (never a
    # re-parsed second copy that could normalize differently); don't clobber a real
    # extracted ``asserted_name``.
    if "asserted_name" not in fields:
        for name_key in BORROWER_NAME_FIELDS.get(document_type or "", ()):
            if name_key in fields:
                fields["asserted_name"] = fields[name_key]
                break
    return fields


def _direction(txn: dict[str, Any]) -> str | None:
    """credit (money in) / debit (money out) from transaction_type; None if unclassifiable.

    Classification is by ``transaction_type`` ONLY. The extractor stores ``amount``
    positive ("use transaction_type for direction", bank_statement prompt), so a positive
    amount carries NO direction signal — inferring "credit" from it would forge a deposit
    on every unlabelled withdrawal (a false AS-1 large-deposit). An unknown/ambiguous type
    therefore returns ``None`` (→ an absent ``direction`` Field), never a guess. Only an
    explicitly NEGATIVE / parenthesized amount (a signed export the prompt doesn't ask for,
    handled defensively) is read as a debit.
    """
    ttype = txn.get("transaction_type")
    if isinstance(ttype, str):
        key = ttype.strip().lower().replace(" ", "_")
        if key in _CREDIT_TYPES:
            return "credit"
        if key in _DEBIT_TYPES:
            return "debit"
    amount = txn.get("amount")
    if isinstance(amount, (int, float)) and amount < 0:
        return "debit"
    if isinstance(amount, str):
        stripped = amount.strip().replace(",", "").replace("$", "").replace(" ", "")
        if stripped.startswith("-") or (stripped.startswith("(") and stripped.endswith(")")):
            return "debit"
    return None  # unclassifiable — absent direction, never a fabricated "credit"


def _redact_description(value: Any) -> str | None:
    """The description with any 9+-digit identifier (bare or space/dash-grouped) redacted."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return _DESC_REDACT.sub(_REDACTED, text) if text else None


def _txn_field(value: Any, *, source: FieldSource = _EXTRACTED) -> Field:
    """A transaction attribute as a Field (no confidence), absent when null.

    ``source`` defaults to ``extracted`` (the value was read from the document); pass
    ``FieldSource.DERIVED`` for a COMPUTED attribute (``direction``) so its provenance is
    honest — a derived value is never tagged as if the extractor read it verbatim.
    """
    if value is None:
        return Field.missing()
    scalar = _scalar(value)  # date/amount/etc. already stringified by the extractor's JSON dump
    if scalar is None:
        return Field.missing()
    return Field.present(scalar, source=source)


# The four Fields of one transaction row, keyed by their TransactionRecord attribute.
TransactionFieldSet = dict[str, Field]


def transaction_field_sets(
    extracted: dict[str, Any], document_type: str | None
) -> list[TransactionFieldSet] | None:
    """The bank-statement transaction rows reshaped to Fields (LP-302a), or ``None``.

    ``None`` = absent (a non-bank document, or a statement whose extraction carried no
    transaction list); an empty list = a statement present with zero transactions
    (present-empty). Pure read + reshape; no correlation. ``description`` is redacted so a
    raw account/id never lands at rest.

    This is the reshape half of transaction building. The stable per-row ``content_id``
    (LP-312) is applied by :func:`build_transactions` once the parent document's id is
    known — a transaction id is scoped under its document, so it cannot be assigned here.
    """
    if document_type not in _TRANSACTION_DOC_TYPES:
        return None
    raw = extracted.get(_TRANSACTIONS_KEY)
    if not isinstance(raw, list):
        return None  # statement present but no transaction list → absent, not empty
    # The statement's masked account is NOT copied onto every row — it lives once on the
    # DocumentEntry's ``fields["account_number_masked"]`` (built by build_document_fields).
    field_sets: list[TransactionFieldSet] = []
    for txn in raw:
        if not isinstance(txn, dict):
            continue
        field_sets.append(
            {
                "date": _txn_field(txn.get("date")),
                "amount": _txn_field(txn.get("amount")),
                "direction": _txn_field(_direction(txn), source=FieldSource.DERIVED),
                "description": _txn_field(_redact_description(txn.get("description"))),
            }
        )
    return field_sets


def _txn_content(field_set: TransactionFieldSet) -> dict[str, Any]:
    """The content a transaction's id is derived from — its four Fields, JSON-canonical."""
    return {name: fld.model_dump(mode="json") for name, fld in field_set.items()}


def build_transactions(
    field_sets: list[TransactionFieldSet] | None,
    *,
    document_content_id: str,
    txn_contents: list[dict[str, Any]] | None = None,
) -> tuple[TransactionRecord, ...] | None:
    """Final :class:`TransactionRecord`\\s with stable content_ids, or ``None`` (absent).

    Each row's ``content_id`` is derived from the parent document's id + the row's own
    content, with a duplicate tiebreak (:func:`assign_content_ids`), so identical deposits
    in one statement still get distinct ids and no transaction id collides across documents.

    ``txn_contents`` (optional) is the ``_txn_content(fs)`` list the caller may have already
    computed for the document's transactions-fingerprint — passing it avoids serializing each
    row's Fields a second time. When omitted (external callers/tests) it is computed here.
    """
    if field_sets is None:
        return None
    contents = txn_contents if txn_contents is not None else [_txn_content(fs) for fs in field_sets]
    bases = [{"doc": document_content_id, **content} for content in contents]
    ids = assign_content_ids(TXN_PREFIX, bases)
    return tuple(
        TransactionRecord(content_id=cid, **fs) for cid, fs in zip(ids, field_sets, strict=True)
    )


def _document_base(
    document_type: str | None,
    refs: tuple[BorrowerRef, ...],
    fields: dict[str, SnapshotField],
    field_sets: list[TransactionFieldSet] | None,
    *,
    txn_contents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The content a document's stable id is derived from (excluding the id itself).

    Includes an ORDER-INDEPENDENT fingerprint of the document's transaction contents, so two
    statements identical in type/borrowers/fields but differing in their transactions get
    distinct ids deterministically (not by positional luck). ``fields`` is the JSON-canonical
    field map (sorted).

    ``belongs_to`` is reduced to the resolved borrower ids+names and **sorted by borrower_id**,
    so the document id is independent of the order the borrower links happen to arrive in. The
    link query orders by ``confidence`` and equal-confidence borrowers (a joint document
    matched to both spouses) have no stable relative order — folding that incidental order into
    the id would make it change between rebuilds, breaking the run-independence guarantee.

    ``txn_contents`` (optional) is the precomputed ``_txn_content(fs)`` list; when omitted it is
    computed from ``field_sets`` (keeps the pure-in-test call sites simple).
    """
    contents = (
        txn_contents
        if txn_contents is not None
        else (None if field_sets is None else [_txn_content(fs) for fs in field_sets])
    )
    return {
        "document_type": document_type,
        "belongs_to": (
            [
                {"borrower_id": str(r.borrower_id), "name": r.name}
                for r in sorted(refs, key=lambda ref: str(ref.borrower_id))
            ]
            if refs
            else None
        ),
        "fields": {key: value.model_dump(mode="json") for key, value in sorted(fields.items())},
        "transactions_fingerprint": (None if contents is None else unordered_fingerprint(contents)),
    }


@dataclass(frozen=True)
class _ReshapedDoc:
    """One document reshaped for id assignment — content only, no id yet.

    ``txn_contents`` is the ``_txn_content(fs)`` list computed once here and reused by both the
    document-id fingerprint and :func:`build_transactions`, so a row's Fields are serialized
    once per build rather than twice.
    """

    document_type: str | None
    refs: tuple[BorrowerRef, ...]
    fields: dict[str, SnapshotField]
    field_sets: list[TransactionFieldSet] | None
    txn_contents: list[dict[str, Any]] | None


async def _reshape_and_assign_ids(
    db: AsyncSession, loan_file: LoanFile
) -> tuple[list[Document], list[_ReshapedDoc], list[str]]:
    """Load the file's current documents, reshape each (type / resolved borrowers / fields / transaction
    field sets), and assign the stable, content-derived document ids — returned as ALIGNED lists
    ``(documents, reshaped, content_ids)``.

    The ONE place the document content-ids are derived, so the snapshot's ``documents`` section and the
    read-time ``content_id -> filename`` map (LP-377-B) build from the SAME reshape+assign — a finding's
    ``subject_key`` (a document content-id) is guaranteed to match the id the map keys on. Duplicating
    this reshape would let the two drift and silently resolve to nothing.
    """
    documents = (
        (
            await db.execute(
                only_active(
                    select(Document).where(
                        Document.loan_file_id == loan_file.id,
                        Document.is_current.is_(True),
                    ),
                    Document,
                )
                # Only the CURRENT extraction is used (current_extraction); don't
                # over-fetch every historical version and its extracted_data JSON.
                .options(selectinload(Document.extractions.and_(Extraction.is_current.is_(True))))
                .order_by(Document.document_type, Document.created_at, Document.id)
            )
        )
        .scalars()
        .all()
    )

    borrower_names = await _active_borrower_names(db, loan_file.id)
    links_by_doc = await _links_by_document(db, [d.id for d in documents])

    # Pass 1: reshape each document's content (type / resolved borrowers / fields / transaction
    # field sets) WITHOUT ids — nothing here depends on array position.
    reshaped: list[_ReshapedDoc] = []
    for document in documents:
        extraction = document.current_extraction
        extracted = extraction.extracted_data if extraction and extraction.extracted_data else {}
        fields = build_document_fields(extracted, document.document_type, loan_file_id=loan_file.id)
        refs = tuple(
            BorrowerRef(borrower_id=link.borrower_id, name=borrower_names[link.borrower_id])
            for link in links_by_doc.get(document.id, ())
            if link.borrower_id in borrower_names  # excludes links to soft-deleted borrowers
        )
        field_sets = transaction_field_sets(extracted, document.document_type)
        txn_contents = None if field_sets is None else [_txn_content(fs) for fs in field_sets]
        reshaped.append(
            _ReshapedDoc(document.document_type, refs, fields, field_sets, txn_contents)
        )

    # Pass 2: assign stable, content-derived document ids (with a duplicate tiebreak), aligned to the
    # documents/reshaped lists by input order.
    doc_ids = assign_content_ids(
        DOC_PREFIX,
        [
            _document_base(
                d.document_type, d.refs, d.fields, d.field_sets, txn_contents=d.txn_contents
            )
            for d in reshaped
        ],
    )
    return list(documents), reshaped, doc_ids


async def build_documents_section(db: AsyncSession, loan_file: LoanFile) -> list[DocumentEntry]:
    """Assemble the ``documents`` section for a loan file (active documents only).

    Reads each active, current document's extraction + stored borrower links. No
    extraction, no matching — a pure read + reshape. Each entry (and each transaction) is
    stamped with a stable, run-independent ``content_id`` (LP-312): documents get ids first,
    then each statement's transactions are scoped under their document's id.
    """
    _documents, reshaped, doc_ids = await _reshape_and_assign_ids(db, loan_file)
    entries: list[DocumentEntry] = []
    for d, doc_id in zip(reshaped, doc_ids, strict=True):
        entries.append(
            DocumentEntry(
                content_id=doc_id,
                document_type=d.document_type,
                belongs_to=d.refs or None,  # None when no borrower resolved
                fields=d.fields,
                transactions=build_transactions(
                    d.field_sets, document_content_id=doc_id, txn_contents=d.txn_contents
                ),
            )
        )
    return entries


async def document_filenames_by_content_id(db: AsyncSession, loan_file: LoanFile) -> dict[str, str]:
    """Map each current document's stable ``content_id`` → its ``original_filename`` (LP-377-B).

    The read path uses this to resolve a governed finding's document subject (its ``subject_key`` is a
    document content-id, LP-312) to a filename a processor recognises — never the raw hash. Reuses the
    EXACT reshape+assign the snapshot uses (:func:`_reshape_and_assign_ids`), so the keys match the
    findings' subject_keys. A document whose content changed since its run gets a DIFFERENT id now and is
    simply absent from the map (the read path then falls back honestly — the finding's subject is gone /
    no longer in this form). Documents with no stored filename are omitted (same honest fallback).
    """
    documents, _reshaped, doc_ids = await _reshape_and_assign_ids(db, loan_file)
    return {
        doc_id: document.original_filename
        for document, doc_id in zip(documents, doc_ids, strict=True)
        if document.original_filename
    }


async def _links_by_document(
    db: AsyncSession, document_ids: list[UUID]
) -> dict[UUID, list[DocumentBorrowerLink]]:
    """All borrower links for the given documents, grouped by document (ONE query).

    Replaces a per-document call (an N+1). No soft-delete joins are needed here: the
    caller passes only active documents and filters refs to active borrowers.
    """
    if not document_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(DocumentBorrowerLink)
                .where(DocumentBorrowerLink.document_id.in_(document_ids))
                # borrower_id is a deterministic tiebreak: equal-confidence links (a joint
                # document matched to both spouses) otherwise return in an unstable order.
                .order_by(DocumentBorrowerLink.confidence.desc(), DocumentBorrowerLink.borrower_id)
            )
        )
        .scalars()
        .all()
    )
    by_doc: dict[UUID, list[DocumentBorrowerLink]] = defaultdict(list)
    for link in rows:
        by_doc[link.document_id].append(link)
    return by_doc


async def _active_borrower_names(db: AsyncSession, loan_file_id: UUID) -> dict[UUID, str]:
    """Map active borrower id → resolved full name (for belongs_to)."""
    borrowers = (
        (
            await db.execute(
                only_active(select(Borrower).where(Borrower.loan_file_id == loan_file_id), Borrower)
            )
        )
        .scalars()
        .all()
    )
    return {b.id: b.full_name for b in borrowers}
