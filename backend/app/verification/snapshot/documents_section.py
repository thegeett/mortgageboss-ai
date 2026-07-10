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

Extractors already MASK sensitive numbers at extraction time — a document's
``extracted_data`` holds ``account_number_masked`` / ``taxpayer_ssn_masked``, never
a raw account number or SSN. So there is no raw value to route through
``PiiField.from_raw``; those pre-masked fields become a ``PiiField`` carrying a
canonical last-4 display and ``match_hash=None`` (non-matchable — only the masked
form was ever captured). ``social_security_wages`` / ``_tax_withheld`` are dollar
amounts, not SSNs, and stay ordinary fields.

## Absent ≠ empty

A field the extractor didn't produce (``value`` is null, or the field absent) is
omitted — distinct from a present empty string. Nothing is fabricated.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.borrower import Borrower
from app.models.document import Document
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.services.borrower_name_matching import BORROWER_NAME_FIELDS
from app.services.document_borrower_links import get_document_borrower_links
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import BorrowerRef, DocumentEntry, SnapshotField
from app.verification.snapshot.pii import PiiField, PiiKind

_EXTRACTED = FieldSource.EXTRACTED

# The catch-all list key inside extracted_data (not a typed field).
_CATCH_ALL_KEY = "additional_sections"

# Typed fields whose extracted value is ALREADY MASKED at extraction time → route
# to a PiiField (canonical display, non-matchable hash). Explicit, not
# pattern-matched, so ``social_security_wages`` (a dollar amount) is never caught.
_MASKED_PII_FIELDS: dict[str, PiiKind] = {
    "account_number_masked": PiiKind.ACCOUNT,
    "taxpayer_ssn_masked": PiiKind.SSN,
}


def _confidence(raw: Any) -> float | None:
    """LP-201's confidence, surfaced faithfully — only a genuine number, else None."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def _scalar(value: Any) -> str | int | float | bool | None:
    """A JSON scalar, or None to skip a nested (list/dict) extracted value."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    return None  # nested structures (e.g. bank-statement transactions) not surfaced here


def _masked_pii(value: Any, kind: PiiKind, confidence: float | None) -> PiiField:
    """A PiiField for an ALREADY-MASKED extracted value (canonical last-4 display).

    The raw value never existed in the extraction, so ``match_hash`` is ``None``
    (non-matchable). We render the display from the value's last four alphanumerics
    rather than re-masking (LP-203's ``mask`` would placeholder a value that already
    has only four significant chars), so even a badly-masked input shows only 4.
    """
    last4 = "".join(c for c in str(value) if c.isalnum())[-4:]
    if kind is PiiKind.SSN:
        display = f"***-**-{last4}" if len(last4) == 4 else "***-**-****"
    else:
        display = f"****{last4}" if len(last4) == 4 else "****"
    return PiiField(display=display, match_hash=None, source=_EXTRACTED, confidence=confidence)


def _asserted_name(extracted: dict[str, Any], document_type: str | None) -> Field | None:
    """The raw borrower name the document printed (its LP-202 borrower-name field)."""
    for key in BORROWER_NAME_FIELDS.get(document_type or "", ()):
        entry = extracted.get(key)
        if isinstance(entry, dict):
            value = entry.get("value")
            if isinstance(value, str) and value.strip():
                return Field.present(
                    value.strip(),
                    source=_EXTRACTED,
                    confidence=_confidence(entry.get("confidence")),
                )
    return None


def build_document_fields(
    extracted: dict[str, Any], document_type: str | None
) -> dict[str, SnapshotField]:
    """Reshape one document's ``extracted_data`` into snapshot fields (pure)."""
    fields: dict[str, SnapshotField] = {}
    for key, entry in extracted.items():
        if key == _CATCH_ALL_KEY or not isinstance(entry, dict) or "value" not in entry:
            continue
        value = entry.get("value")
        if value is None:  # absent — omit
            continue
        confidence = _confidence(entry.get("confidence"))
        kind = _MASKED_PII_FIELDS.get(key)
        if kind is not None:
            fields[key] = _masked_pii(value, kind, confidence)
            continue
        scalar = _scalar(value)
        if scalar is None:  # nested/non-scalar — not surfaced here
            continue
        fields[key] = Field.present(scalar, source=_EXTRACTED, confidence=confidence)

    asserted = _asserted_name(extracted, document_type)
    if asserted is not None:
        fields["asserted_name"] = asserted
    return fields


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
                .options(selectinload(Document.extractions))
                .order_by(Document.document_type, Document.created_at, Document.id)
            )
        )
        .scalars()
        .all()
    )

    borrower_names = await _active_borrower_names(db, loan_file.id)

    entries: list[DocumentEntry] = []
    for document in documents:
        extraction = document.current_extraction
        extracted = extraction.extracted_data if extraction and extraction.extracted_data else {}
        fields = build_document_fields(extracted, document.document_type)

        links = await get_document_borrower_links(db, document.id)
        refs = tuple(
            BorrowerRef(borrower_id=link.borrower_id, name=borrower_names[link.borrower_id])
            for link in links
            if link.borrower_id in borrower_names
        )
        entries.append(
            DocumentEntry(
                document_type=document.document_type,
                belongs_to=refs or None,  # None when no borrower resolved
                fields=fields,
            )
        )
    return entries


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
