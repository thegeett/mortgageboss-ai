"""The schema-spec model + loader (LP-434), per ``docs/schema-specs/_FORMAT.md``.

A thin, tolerant wrapper over the raw JSON: it reads only the fields the generator
needs (``document_type``, ``typed_core``, ``nested_lists``, ``open_questions``,
``existing_extractor``) and keeps the raw dict around for anything else. It does NOT
judge the spec — that is the validator's job (:mod:`.validator`). Loading never
raises on a *content* problem (a missing ``reason_class``, a bad ``type``); those
surface as refusals downstream. It raises only on a structurally unreadable file
(not JSON, not an object).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The four coercers that exist in ``app.ai.extraction.parsing`` (guide §3). A spec
# field typed as anything else has no coercer → a stop condition, not generation.
VALID_TYPES: tuple[str, ...] = ("str", "Decimal", "date", "int")

# spec ``type`` → the coercer imported into the generated module.
TYPE_TO_COERCER: dict[str, str] = {
    "str": "coerce_str",
    "Decimal": "coerce_decimal",
    "date": "coerce_date",
    "int": "coerce_int",
}

# spec ``type`` → the Python annotation used inside ``TypedField[...]``.
TYPE_TO_ANNOTATION: dict[str, str] = {
    "str": "str",
    "Decimal": "Decimal",
    "date": "date",
    "int": "int",
}

# spec ``type`` → the JSON type placeholder shown in the prompt contract.
TYPE_TO_JSON: dict[str, str] = {
    "str": "string",
    "Decimal": "number",
    "date": "string",
    "int": "int",
}

# spec ``type`` → the human label shown against a field in the prompt's typed-core list.
TYPE_TO_PROMPT_LABEL: dict[str, str] = {
    "str": "string",
    "Decimal": "number",
    "date": "date (YYYY-MM-DD)",
    "int": "integer",
}


class SpecError(ValueError):
    """A spec file that cannot be read as a JSON object (structural, not content)."""


@dataclass(frozen=True)
class SpecField:
    """One ``typed_core`` entry — only the keys the generator reads, plus the raw dict."""

    name: str
    type: str | None
    reason_class: str | None
    pii: dict[str, Any] | None
    exists_today: bool
    prompt_hint: str | None
    degraded_from: str | None
    raw: dict[str, Any]

    @property
    def pii_kind(self) -> str | None:
        """The declared ``pii.kind`` (e.g. ``"SSN"``), or ``None`` when the field is not PII."""
        if not self.pii:
            return None
        kind = self.pii.get("kind")
        return kind if isinstance(kind, str) else None

    @property
    def pii_pre_masked(self) -> bool:
        """Whether the extractor is expected to pre-mask the value (``pii.pre_masked``)."""
        return bool(self.pii and self.pii.get("pre_masked") is True)


@dataclass(frozen=True)
class NestedList:
    """One ``nested_lists`` entry — the name and item count; the generator never emits these."""

    name: str
    expected_item_count: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class Spec:
    """A loaded schema spec — the generator's input."""

    document_type: str
    existing_extractor: str | None
    catalog_coverage: str | None
    tier: int | None
    summary_hint: str | None
    typed_core: tuple[SpecField, ...]
    nested_lists: tuple[NestedList, ...]
    open_questions: tuple[dict[str, Any], ...]
    path: Path
    raw: dict[str, Any]

    @property
    def is_diff_mode(self) -> bool:
        """True when a shipping extractor exists → the generator reports additions, never a module."""
        return bool(self.existing_extractor)

    @property
    def new_fields(self) -> tuple[SpecField, ...]:
        """The ``exists_today: false`` typed-core fields — what a diff-mode addition would add."""
        return tuple(f for f in self.typed_core if not f.exists_today)


def _field(raw: Any) -> SpecField | None:
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        return None
    pii = raw.get("pii")
    return SpecField(
        name=name,
        type=raw.get("type") if isinstance(raw.get("type"), str) else None,
        reason_class=raw.get("reason_class") if isinstance(raw.get("reason_class"), str) else None,
        pii=pii if isinstance(pii, dict) else None,
        exists_today=raw.get("exists_today") is True,
        prompt_hint=raw.get("prompt_hint") if isinstance(raw.get("prompt_hint"), str) else None,
        degraded_from=raw.get("degraded_from")
        if isinstance(raw.get("degraded_from"), str)
        else None,
        raw=raw,
    )


def _nested(raw: Any) -> NestedList | None:
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        return None
    count = raw.get("expected_item_count")
    return NestedList(
        name=name,
        expected_item_count=count if isinstance(count, str) else None,
        raw=raw,
    )


def load_spec(path: str | Path) -> Spec:
    """Read a ``NNN-<slug>.json`` spec into a :class:`Spec`. Raises :class:`SpecError` only
    on a structurally unreadable file (not JSON / not an object)."""
    p = Path(path)
    try:
        payload: Any = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError) as exc:
        raise SpecError(f"{p}: not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SpecError(f"{p}: top level is not a JSON object")

    document_type = payload.get("document_type")
    if not isinstance(document_type, str) or not document_type:
        raise SpecError(f"{p}: missing/invalid 'document_type'")

    typed_core = tuple(
        f for f in (_field(x) for x in _as_list(payload.get("typed_core"))) if f is not None
    )
    nested_lists = tuple(
        n for n in (_nested(x) for x in _as_list(payload.get("nested_lists"))) if n is not None
    )
    open_questions = tuple(
        x for x in _as_list(payload.get("open_questions")) if isinstance(x, dict)
    )
    existing = payload.get("existing_extractor")
    catalog = payload.get("catalog_coverage")
    tier = payload.get("tier")
    summary = payload.get("summary_hint")

    return Spec(
        document_type=document_type,
        existing_extractor=existing if isinstance(existing, str) and existing else None,
        catalog_coverage=catalog if isinstance(catalog, str) else None,
        tier=tier if isinstance(tier, int) else None,
        summary_hint=summary if isinstance(summary, str) else None,
        typed_core=typed_core,
        nested_lists=nested_lists,
        open_questions=open_questions,
        path=p,
        raw=payload,
    )


def _as_list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []
