"""Consolidated document period display (LP-105) — one type-aware ``{label, value}`` line.

17 of 18 Tier-1 extractors already capture a date/period (pay period, statement period, tax
year, policy term, due/closing/effective date, expiry). Those land in the detail drawer as
individual raw rows ("Pay period start", "Pay period end") and only reach the card indirectly
via the standard name. This derives ONE human-readable period line per document from the
already-extracted fields — so the card + drawer can show "Period: Jun 1 - Jun 15, 2026",
"Tax year: 2025", "Closes: Aug 15, 2026", etc. consistently.

**Display only** — no new extraction. **Graceful** — returns ``None`` when the type has no
period concept (gift_letter) or the date isn't extracted yet (pending/failed), so the UI shows
nothing rather than an empty "Period: -". Money/PII never appear here; only dates/years.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel

from app.models.document import Document
from app.models.extraction import Extraction


class DocumentPeriod(BaseModel):
    """A document's consolidated period line — e.g. ``label="Period"``, ``value="Jun 1 - Jun 15, 2026"``."""

    label: str
    value: str


@dataclass(frozen=True)
class _Range:
    """A start-end date range, e.g. a statement / pay / reporting / employment period."""

    start: str
    end: str
    label: str = "Period"


@dataclass(frozen=True)
class _Year:
    """A tax year (int)."""

    field: str
    label: str = "Tax year"


@dataclass(frozen=True)
class _Single:
    """A single labeled event date (due / closes / effective / expires)."""

    field: str
    label: str


@dataclass(frozen=True)
class _Verbatim:
    """A verbatim string date (e.g. a tax bill's two installment due dates), shown as-is."""

    field: str
    label: str


# Per-type period concept — from the already-extracted typed-core fields. gift_letter has no
# date concept (absent here → no period line). property_tax_bill shows its verbatim due_dates.
_PERIODS: dict[str, _Range | _Year | _Single | _Verbatim] = {
    "pay_stub": _Range("pay_period_start", "pay_period_end"),
    "bank_statement": _Range("statement_period_start", "statement_period_end"),
    "investment_account": _Range("statement_period_start", "statement_period_end"),
    "retirement_account": _Range("statement_period_start", "statement_period_end"),
    "profit_and_loss": _Range("period_start", "period_end"),
    "voe": _Range("start_date", "end_date"),
    "homeowners_insurance": _Range("effective_date", "expiration_date", label="Policy"),
    "w2": _Year("tax_year"),
    "form_1099": _Year("tax_year"),
    "tax_return": _Year("tax_year"),
    "mortgage_statement": _Single("due_date", "Due"),
    "hoa_statement": _Single("due_date", "Due"),
    "purchase_agreement": _Single("closing_date", "Closes"),
    "divorce_decree": _Single("effective_date", "Effective"),
    "drivers_license": _Single("expiration_date", "Expires"),
    "letter_of_explanation": _Single("referenced_date", "Dated"),
    "property_tax_bill": _Verbatim("due_dates", "Due"),
}


def _value(data: dict[str, Any], key: str) -> Any:
    """A typed-core field's ``value`` (the ``{value, source}`` shape), or the bare value."""
    cell = data.get(key)
    return cell.get("value") if isinstance(cell, dict) else cell


def _as_date(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _fmt(d: date) -> str:
    """``date(2026, 6, 1)`` -> ``"Jun 1, 2026"`` (no leading zero, portable)."""
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def _fmt_range(a: date, b: date) -> str:
    """``"Jun 1 - Jun 15, 2026"`` when the years match, else both dates in full."""
    if a.year == b.year:
        return f"{a.strftime('%b')} {a.day} - {b.strftime('%b')} {b.day}, {b.year}"
    return f"{_fmt(a)} - {_fmt(b)}"


def document_period(document: Document, extraction: Extraction | None) -> DocumentPeriod | None:
    """The consolidated, type-aware period line for a document, or ``None``.

    Reads the already-extracted typed-core date/year field(s) for the document's type and
    formats them per the type's concept (range / tax year / single labeled date / verbatim).
    Returns ``None`` when the type has no period concept or the date isn't extracted yet.
    """
    spec = _PERIODS.get(document.document_type or "")
    if spec is None:
        return None
    data = extraction.extracted_data if extraction is not None else {}

    if isinstance(spec, _Range):
        start = _as_date(_value(data, spec.start))
        end = _as_date(_value(data, spec.end))
        if start is not None and end is not None:
            return DocumentPeriod(label=spec.label, value=_fmt_range(start, end))
        one = start or end  # a partial range still surfaces the one date we have
        return DocumentPeriod(label=spec.label, value=_fmt(one)) if one is not None else None

    if isinstance(spec, _Year):
        raw = _value(data, spec.field)
        text = str(raw).strip() if raw is not None else ""
        if isinstance(raw, int):
            return DocumentPeriod(label=spec.label, value=str(raw))
        if text.isdigit() and len(text) == 4:
            return DocumentPeriod(label=spec.label, value=text)
        return None

    if isinstance(spec, _Single):
        d = _as_date(_value(data, spec.field))
        return DocumentPeriod(label=spec.label, value=_fmt(d)) if d is not None else None

    # _Verbatim — a string shown as-is (e.g. a tax bill's two installment due dates).
    raw = _value(data, spec.field)
    text = str(raw).strip() if raw is not None else ""
    return DocumentPeriod(label=spec.label, value=text) if text else None
