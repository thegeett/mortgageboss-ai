"""What field names a document type declares (LP-703).

The universe a hand-entered field key has to name something in. A processor
adding a field the model missed picks from THIS set, not from free text: a key
outside it is data no rule can ever read, so accepting one would let someone type
a value into a field that silently reaches nobody.

Built from ``app/schema_specs/*.json`` — the same specs the extraction contracts
are generated from — rather than from the rule declarations, because a field is a
property of the DOCUMENT and the tag that reads it may be derived, or may not
exist yet.

**One loader, two callers.** ``verification.rules.distrust`` had its own copy of
this walk and now delegates here. Two call sites deriving the same set is how they
come to disagree about what a document type declares, and only one of them would
be wrong at a time.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from app.schema_specs import SPECS_DIR


class SchemaSpecsUnreadable(RuntimeError):
    """The spec directory is missing or empty.

    Raised rather than returning an empty set, because empty is indistinguishable
    from "this type declares nothing" at every call site — and a packaging problem
    that reads as a field rename cost LP-508 the whole life of an image.
    """


def _field_names(block: object) -> list[str]:
    """The field names in a spec block, whether a list of objects or a name-keyed mapping."""
    if isinstance(block, dict):
        return [str(key) for key in block]
    if isinstance(block, list):
        return [str(item["name"]) for item in block if isinstance(item, dict) and item.get("name")]
    return []


@cache
def _parsed_specs() -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    """``(typed_core, nested_rows)``, each ``{document_type: {field_name, ...}}``.

    THE TWO ARE KEPT APART, and that is the whole reason this is not one set. A
    typed-core key is a field ON the document. A nested-row key names a column
    INSIDE a list — ``earning_type`` is a column of a pay stub's
    ``earnings_lines``, not a field of the pay stub. They read identically as bare
    strings, which is how a first version of this offered a processor
    ``earning_type`` as something to add at the top level: a key that would have
    been stored, displayed, and read by nothing.

    Cached: the specs ship inside the package and do not change at runtime.
    """
    specs = sorted(Path(SPECS_DIR).glob("*.json"))
    if not specs:
        raise SchemaSpecsUnreadable(
            f"no schema specs found at {SPECS_DIR} — this set is the universe every "
            "hand-entered field key is checked against, so an empty one rejects EVERY "
            "key. The directory ships inside the package; check it was not dropped "
            "from the build or the wheel."
        )
    core: dict[str, set[str]] = {}
    nested: dict[str, set[str]] = {}
    for path in specs:
        payload = json.loads(path.read_text(encoding="utf-8"))
        document_type = payload.get("document_type")
        if not isinstance(document_type, str) or not document_type:
            continue
        core.setdefault(document_type, set()).update(_field_names(payload.get("typed_core")))
        rows = nested.setdefault(document_type, set())
        for block in payload.get("nested_lists") or []:
            rows.update(_field_names((block or {}).get("fields")))
    return (
        {k: frozenset(v) for k, v in core.items()},
        {k: frozenset(v) for k, v in nested.items()},
    )


def declared_fields() -> dict[str, frozenset[str]]:
    """``{document_type: {typed-core field name, ...}}`` — the document's OWN fields."""
    return _parsed_specs()[0]


def fields_for(document_type: str | None) -> frozenset[str]:
    """The typed-core fields one document type declares; empty for unknown or untyped.

    TYPED CORE ONLY — nested-row columns are deliberately excluded. This is the set
    a processor may ADD to, and a nested column added at the top level would be a
    key that is stored, displayed, and read by nothing.

    EMPTY IS A REFUSAL, not a permission. A document with no type has no declared
    field set, so nothing can be added to it, which is the safe direction.
    """
    if not document_type:
        return frozenset()
    return declared_fields().get(document_type, frozenset())


def schema_field_pairs() -> set[tuple[str, str]]:
    """Every ``(document_type, field)`` the specs declare — typed core AND nested rows.

    The WIDER set, and the right one for its caller: ``verification.rules.distrust``
    validates that a distrusted field names something real, and a distrusted field
    can be a nested-row column (IH-1's case). Deliberately not what ``fields_for``
    returns — see its note.
    """
    core, nested = _parsed_specs()
    return {
        (document_type, field)
        for source in (core, nested)
        for document_type, fields in source.items()
        for field in fields
    }
