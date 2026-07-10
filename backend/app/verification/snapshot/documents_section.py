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

# Extraction transaction_type values → credit (money in) / debit (money out).
_CREDIT_TYPES = frozenset({"deposit", "credit", "interest", "refund", "transfer_in"})
_DEBIT_TYPES = frozenset({"withdrawal", "debit", "fee", "payment", "transfer_out", "check"})

# The exact patterns the LP-209 at-rest guard rejects — redacted OUT of a
# transaction description so a surfaced description is never a raw account/SSN/id at
# rest (real descriptions carry payroll/confirmation/transfer ids that would trip the
# guard). The sourcing signal (PAYROLL / TRANSFER / VENMO) and short ids (SAV 5683,
# dates) are kept. See ADR-248.
_DESC_REDACT = re.compile(r"\d{3}-\d{2}-\d{4}|\d{9,}")
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
    """credit (money in) / debit (money out) from transaction_type, else amount sign."""
    ttype = txn.get("transaction_type")
    if isinstance(ttype, str):
        key = ttype.strip().lower().replace(" ", "_")
        if key in _CREDIT_TYPES:
            return "credit"
        if key in _DEBIT_TYPES:
            return "debit"
    amount = txn.get("amount")
    if isinstance(amount, (int, float)):
        return "credit" if amount >= 0 else "debit"
    if isinstance(amount, str):
        stripped = amount.strip().replace(",", "").replace("$", "")
        if stripped.startswith("-"):
            return "debit"
        if stripped[:1].isdigit():
            return "credit"
    return None


def _redact_description(value: Any) -> str | None:
    """The description with any 9+-digit run / SSN pattern redacted (PII-safe at rest)."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return _DESC_REDACT.sub(_REDACTED, text) if text else None


def _txn_field(value: Any) -> Field:
    """A transaction attribute as a Field (extracted, no confidence), absent when null."""
    if value is None:
        return Field.missing()
    scalar = _scalar(value)  # date/amount/etc. already stringified by the extractor's JSON dump
    if scalar is None:
        return Field.missing()
    return Field.present(scalar, source=_EXTRACTED)


def _statement_account(extracted: dict[str, Any]) -> PiiField:
    """The statement's account for the transactions to carry as DISPLAY/CONTEXT (LP-302a).

    A **pre-masked** :class:`PiiField` (``display`` = ``****NNNN``, ``match_hash=None``):
    extraction only ever holds ``account_number_masked`` — the raw account never reached
    us, so there is nothing to hash and the mask must NOT be hashed (hashing ``****5667``
    would collide with every same-last-4 account — the LP-203 colliding-hash bug).
    ``match_hash=None`` is honest and structurally non-matchable. Absent (no account on
    the statement) → ``PiiField.missing()``. This is context, not a cross-section match key.
    """
    entry = extracted.get("account_number_masked")
    value = entry.get("value") if isinstance(entry, dict) else None
    if value is None:
        return PiiField.missing()
    # pre_masked, NOT from_raw: the value is already masked and has no raw form to hash.
    return PiiField.pre_masked(value, kind=PiiKind.ACCOUNT, source=_EXTRACTED)


def build_transactions(
    extracted: dict[str, Any], document_type: str | None
) -> tuple[TransactionRecord, ...] | None:
    """The bank-statement transaction rows (LP-302a), or ``None`` when not surfaced.

    ``None`` = absent (a non-bank document, or a statement whose extraction carried no
    transaction list); an empty tuple = a statement present with zero transactions
    (present-empty). Pure read + reshape; no correlation. ``description`` is redacted
    so a raw account/id never lands at rest.
    """
    if document_type not in _TRANSACTION_DOC_TYPES:
        return None
    raw = extracted.get(_TRANSACTIONS_KEY)
    if not isinstance(raw, list):
        return None  # statement present but no transaction list → absent, not empty
    # The account is a per-STATEMENT fact — resolve it once and every row carries the
    # same pre-masked, non-matchable PiiField (display/context only).
    account = _statement_account(extracted)
    records: list[TransactionRecord] = []
    for txn in raw:
        if not isinstance(txn, dict):
            continue
        records.append(
            TransactionRecord(
                date=_txn_field(txn.get("date")),
                amount=_txn_field(txn.get("amount")),
                direction=_txn_field(_direction(txn)),
                description=_txn_field(_redact_description(txn.get("description"))),
                account=account,
            )
        )
    return tuple(records)


async def build_documents_section(db: AsyncSession, loan_file: LoanFile) -> list[DocumentEntry]:
    """Assemble the ``documents`` section for a loan file (active documents only).

    Reads each active, current document's extraction + stored borrower links. No
    extraction, no matching — a pure read + reshape.
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

    entries: list[DocumentEntry] = []
    for document in documents:
        extraction = document.current_extraction
        extracted = extraction.extracted_data if extraction and extraction.extracted_data else {}
        fields = build_document_fields(extracted, document.document_type, loan_file_id=loan_file.id)

        refs = tuple(
            BorrowerRef(borrower_id=link.borrower_id, name=borrower_names[link.borrower_id])
            for link in links_by_doc.get(document.id, ())
            if link.borrower_id in borrower_names  # excludes links to soft-deleted borrowers
        )
        entries.append(
            DocumentEntry(
                document_type=document.document_type,
                belongs_to=refs or None,  # None when no borrower resolved
                fields=fields,
                transactions=build_transactions(extracted, document.document_type),
            )
        )
    return entries


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
                .order_by(DocumentBorrowerLink.confidence.desc())
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
