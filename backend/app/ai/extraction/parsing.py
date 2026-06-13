"""Shared extraction parsing/coercion (LP-39a shape) — reused by every type.

The per-type modules (pay stub LP-39a, W-2 LP-39b, bank statement LP-39c) all
parse the same shape — a ``typed_core`` of ``{value, page, snippet}`` entries +
grouped ``additional_sections`` — so the field-level coercion, the typed-core
loop, the catch-all pass-through, and the status rule live here once. Everything
is **tolerant and never raises**: a single uncoercible value becomes ``None``
(keeping its source), bad sections/fields are skipped.
"""

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.models.extraction import ExtractionStatus

# A typed-core spec is a sequence of (field_name, value-coercer) pairs.
CoreSpec = tuple[tuple[str, Callable[[Any], Any]], ...]

# Date formats accepted from the model, tried in order (ISO first).
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%m-%d-%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
)


# --------------------------------------------------------------------------- #
# Field-level coercers — junk/empty/None → None (never raise)
# --------------------------------------------------------------------------- #


def coerce_decimal(value: Any) -> Decimal | None:
    """Currency strings (``"$4,200.00"``) and bare numbers → ``Decimal``; else ``None``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    if isinstance(value, str):
        cleaned = value.strip().replace("$", "").replace(",", "").replace(" ", "")
        if not cleaned:
            return None
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            return None
    return None


def coerce_date(value: Any) -> date | None:
    """ISO and common US date formats → ``date``; anything unparseable → ``None``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            pass
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    return None


def coerce_str(value: Any) -> str | None:
    """A non-empty trimmed string, else ``None``."""
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return None


def coerce_int(value: Any) -> int | None:
    """An integer (or an int-valued string/float, e.g. a tax year) → ``int``; else ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        candidate = value.strip()
        if candidate.isdigit() or (candidate.startswith("-") and candidate[1:].isdigit()):
            return int(candidate)
    return None


def coerce_page(value: Any) -> int | None:
    """A page number → ``int``; junk/absent → ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


# --------------------------------------------------------------------------- #
# Shape parsing
# --------------------------------------------------------------------------- #


def source_payload(entry: dict[str, Any]) -> dict[str, Any] | None:
    """A SourceLocation dict from an entry's page/snippet, or ``None`` if neither."""
    page = coerce_page(entry.get("page"))
    raw_snippet = entry.get("snippet")
    snippet = raw_snippet.strip() if isinstance(raw_snippet, str) and raw_snippet.strip() else None
    if page is None and snippet is None:
        return None
    return {"page": page, "snippet": snippet}


def parse_typed_core(
    payload: dict[str, Any], core_spec: CoreSpec
) -> tuple[dict[str, Any], int, bool]:
    """Coerce the typed core; return ``(core_payload, non_null_count, coercion_lost)``.

    Reads ``payload["typed_core"]`` (falling back to ``payload`` for a flat
    response). Each field becomes ``{"value": <coerced|None>, "source": <dict|None>}``;
    a present-but-uncoercible value → ``None`` (source kept) and flags
    ``coercion_lost``. The dict is ready for ``Model.model_validate``.
    """
    core = payload.get("typed_core")
    if not isinstance(core, dict):
        core = payload

    core_payload: dict[str, Any] = {}
    non_null = 0
    coercion_lost = False
    for key, coercer in core_spec:
        entry = core.get(key)
        if isinstance(entry, dict):
            raw = entry.get("value")
            source = source_payload(entry)
        else:
            raw = entry  # tolerant: a bare value with no source
            source = None
        coerced = coercer(raw)
        if coerced is None and raw not in (None, "") and not isinstance(raw, bool):
            coercion_lost = True  # a present value we couldn't coerce → data loss
        if coerced is not None:
            non_null += 1
        core_payload[key] = {"value": coerced, "source": source}
    return core_payload, non_null, coercion_lost


def parse_catch_all(raw: Any) -> list[dict[str, Any]]:
    """Pass through the grouped catch-all as section/field dicts (values stay strings).

    Skips non-dict sections/fields and fields without a label; drops empty
    sections; coerces only ``page`` (to int) and keeps ``snippet`` verbatim.
    """
    sections: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return sections
    for sec in raw:
        if not isinstance(sec, dict):
            continue
        name = sec.get("section")
        section_name = name.strip() if isinstance(name, str) and name.strip() else "Other"
        fields_out: list[dict[str, Any]] = []
        raw_fields = sec.get("fields")
        if isinstance(raw_fields, list):
            for field in raw_fields:
                if not isinstance(field, dict):
                    continue
                label = field.get("label")
                if not isinstance(label, str) or not label.strip():
                    continue
                value = field.get("value")
                value_str = None if value is None else (str(value).strip() or None)
                fields_out.append(
                    {"label": label.strip(), "value": value_str, "source": source_payload(field)}
                )
        if fields_out:
            sections.append({"section": section_name, "fields": fields_out})
    return sections


def derive_status(non_null: int, coercion_lost: bool) -> ExtractionStatus:
    """Status from the typed core: nothing read → FAILED; a coercion loss → PARTIAL; else SUCCEEDED."""
    if non_null == 0:
        return ExtractionStatus.FAILED
    if coercion_lost:
        return ExtractionStatus.PARTIAL
    return ExtractionStatus.SUCCEEDED
