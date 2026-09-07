"""Standard document naming (LP-72) — a derived, consistent display name.

A document's raw upload filename (``scan1.pdf``, ``IMG_0042.pdf``) is unscannable and
unprofessional in a lender package. This derives a consistent name from the document's
**type + extracted data** — ``{Type}_{KeyIdentifier}_{Date}`` (no spaces), e.g.
``Pay-Stub_Thermofisher-PPD_2026-05-22``, ``Bank-Statement_Bank-of-America_2026-04-30``,
``Tax-Return-1040_Mahesh-Chhotala_2024``.

It is a **display / derived** name — the stored file is untouched (presentation +
package concern). The identifier + date come from the typed-core extraction (per type);
a CLASSIFIED document whose extraction is sparse (a known type with no rule, or extraction
pending) falls back to ``{Type}_{UploadDate}``. An UNCLASSIFIED document (type ``"unknown"``)
falls back to its **original uploaded filename** (LP-107) — the best identifier it has — while
the card still shows the "Unknown" type separately (the signal isn't hidden). Only non-sensitive
fields feed the name — never an SSN, account number, or DOB.

The per-type rules below are sensible starters; they refine with use / Priya.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.models.document import Document
from app.models.extraction import Extraction


@dataclass(frozen=True)
class NameRule:
    """How to name a document type: a label + which extracted fields identify it."""

    label: str
    identifier_fields: tuple[str, ...]  # tried in order; first non-empty wins
    date_field: str | None = None  # a typed-core date/year field, or None


# Per-type naming rules (the well-known Tier-1 types). Anything not here falls back to
# a humanized-type label + the upload date. Only non-PII fields are used.
#
# THESE LABELS ARE FILENAME COMPONENTS, not display names, and the distinction is easy to lose
# (LP-638 review). They are joined into `{Type}_{Identifier}_{Date}`, so they must carry no spaces
# and no separators — which is why `voe` is "VOE" here while the type picker calls the same type
# "Verification of employment (VOE)". The two are allowed to differ and should not be merged; see
# `_TYPE_LABEL_OVERRIDES` in `app/api/documents.py`, and the test that pins the property.
NAME_RULES: dict[str, NameRule] = {
    "pay_stub": NameRule("Pay-Stub", ("employer_name",), "pay_date"),
    "w2": NameRule("W-2", ("employer_name",), "tax_year"),
    "bank_statement": NameRule("Bank-Statement", ("bank_name",), "statement_period_end"),
    "tax_return": NameRule("Tax-Return-1040", ("taxpayer_names",), "tax_year"),
    "form_1099": NameRule("1099", ("payer_name",), "tax_year"),
    "drivers_license": NameRule("Drivers-License", ("full_name",), "expiration_date"),
    "mortgage_statement": NameRule("Mortgage-Statement", ("lender_name",), "due_date"),
    "homeowners_insurance": NameRule("Homeowners-Insurance", ("carrier_name",), "expiration_date"),
    # LP-105 — the remaining types that extract a date now feed it into the name (instead of
    # falling back to the upload date), so same-type documents are distinguishable. The
    # graceful {Type}_{UploadDate} fallback still applies when the date isn't extracted yet.
    "investment_account": NameRule(
        "Investment-Account", ("institution_name",), "statement_period_end"
    ),
    "retirement_account": NameRule(
        "Retirement-Account", ("institution_name",), "statement_period_end"
    ),
    "profit_and_loss": NameRule("Profit-And-Loss", ("business_name",), "period_end"),
    "voe": NameRule("VOE", ("employer_name",), "end_date"),
    "hoa_statement": NameRule("HOA-Statement", ("association_name",), "due_date"),
    "purchase_agreement": NameRule("Purchase-Agreement", ("property_address",), "closing_date"),
    "divorce_decree": NameRule("Divorce-Decree", (), "effective_date"),
    "letter_of_explanation": NameRule("Letter-Of-Explanation", ("subject",), "referenced_date"),
    # OUT OF SCOPE (kept on the {Type}_{UploadDate} fallback): property_tax_bill (due_dates is a
    # verbatim string, not a clean date — normalization is separate) and gift_letter (no date).
}


def _slug(text: str) -> str:
    """``"Thermofisher PPD, Inc."`` → ``"Thermofisher-PPD-Inc"`` — no spaces/punctuation."""
    out: list[str] = []
    prev_dash = False
    for ch in text.strip():
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        elif not prev_dash:
            out.append("-")
            prev_dash = True
    return "".join(out).strip("-")


def _typed_value(extracted_data: dict[str, Any], key: str) -> Any:
    """Read a typed-core field's ``value`` (the ``{value, source}`` shape), or None."""
    cell = extracted_data.get(key)
    return cell.get("value") if isinstance(cell, dict) else cell


def _identifier(extracted_data: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for key in fields:
        value = _typed_value(extracted_data, key)
        if value:
            slug = _slug(str(value))
            if slug:
                return slug
    return None


def _date_part(extracted_data: dict[str, Any], key: str | None) -> str | None:
    """A date field → ``YYYY-MM-DD``; a year (int) → ``YYYY``; else None."""
    if key is None:
        return None
    value = _typed_value(extracted_data, key)
    if value is None:
        return None
    if isinstance(value, int):  # a tax year
        return str(value)
    text = str(value)
    if text.isdigit() and len(text) == 4:  # a year stored as a string
        return text
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _humanized_label(document_type: str) -> str:
    """``"credit_report"`` → ``"Credit-Report"`` — for types without an explicit rule."""
    return "-".join(part.capitalize() for part in document_type.split("_") if part) or "Document"


def standard_name(document: Document, extraction: Extraction | None) -> str:
    """Derive the standard ``{Type}_{KeyIdentifier}_{Date}`` display name (no spaces).

    Uses the per-type rule + the typed-core extraction when available; falls back to
    ``{Type}_{UploadDate}`` for sparse data (Tier 2/3, extraction pending, or a missing
    identifier). Always returns a non-empty, space-free name.
    """
    data = extraction.extracted_data if extraction is not None else {}
    rule = NAME_RULES.get(document.document_type or "")
    upload_date = document.created_at.date().isoformat()

    if rule is not None:
        parts: list[str] = [rule.label]
        identifier = _identifier(data, rule.identifier_fields)
        if identifier:
            parts.append(identifier)
        date_part = _date_part(data, rule.date_field)
        if date_part:
            parts.append(date_part)
        # A rich name needs more than just the type label; otherwise fall back to the
        # type + the upload date so the name still distinguishes documents.
        if len(parts) > 1:
            return "_".join(parts)
        return f"{rule.label}_{upload_date}"

    # UNCLASSIFIED (LP-107): the classifier couldn't type it (``"unknown"``) or hasn't yet
    # (``None``). The ORIGINAL uploaded filename is the best available identifier — far better than
    # a non-distinguishing ``Unknown_{UploadDate}`` (four "Unknown" docs looked identical, and the
    # name discarded the real filename). The card still shows the "Unknown" TYPE separately, so the
    # unclassified signal is NOT hidden — only the name recovers the filename. This is distinct from
    # a CLASSIFIED type that merely lacks a naming rule (below), whose ``{Type}_{UploadDate}`` name is
    # meaningful (it states the type).
    if (document.document_type or "unknown") == "unknown" and document.original_filename:
        return document.original_filename

    label = _humanized_label(document.document_type) if document.document_type else "Document"
    return f"{label}_{upload_date}"
