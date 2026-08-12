"""Distrusted extraction fields (LP-508 / ADR-377) — the gate's FIFTH defence.

``gate.py`` has four: absent, ``"unknown"``, contradiction, and low confidence. A confidently-WRONG parsed
value defeats all four — it is present, not ``"unknown"``, uncontradicted, and the parsed producer sets
``confidence=None``, which the confidence minimum FILTERS OUT (and skips entirely when every load-bearing
tag is parsed). This module names the fields with a CONFIRMED wrong value in the corpus so a rule reading
one degrades instead of auto-asserting.

The list is DATA (``distrusted_fields.yaml``) so it is reviewable and PRUNABLE — an extractor that improves
should have its entry deleted, and every entry carries the document and the error behind it.

⚠️ Resolution is by DECLARATION, not by name. A field is distrusted for a DOCUMENT TYPE; this maps that to
the tag ids that actually read it, using the same ``tag_production.yaml`` declarations the producers use. A
tag reading the same field name on a DIFFERENT document type is unaffected.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

_PATH = Path(__file__).with_name("distrusted_fields.yaml")


class DistrustError(Exception):
    """The distrusted-field list is malformed, or names something that does not exist."""


@cache
def load_distrusted_fields() -> dict[tuple[str, str], str]:
    """``{(document_type, field): reason}`` — the declared list, validated.

    An entry with a blank reason is rejected: a bare field name is unreviewable later and cannot be pruned
    with confidence, which is the whole point of keeping the list small.
    """
    raw = (yaml.safe_load(_PATH.read_text()) or {}).get("fields") or {}
    if not isinstance(raw, dict):
        raise DistrustError(
            "distrusted_fields.yaml `fields` must map document_type -> {field: reason}"
        )
    out: dict[tuple[str, str], str] = {}
    for document_type, fields in raw.items():
        if not isinstance(fields, dict):
            raise DistrustError(
                f"distrusted_fields.yaml {document_type!r}: expected a mapping of field -> reason"
            )
        for field, reason in fields.items():
            text = str(reason or "").strip()
            if not text:
                raise DistrustError(
                    f"distrusted_fields.yaml {document_type}.{field}: a reason is REQUIRED — name the "
                    "document and what was wrong, so the entry can be reviewed and pruned later"
                )
            out[(str(document_type), str(field))] = text
    return out


@cache
def distrusted_tag_ids() -> dict[str, str]:
    """``{tag_id: reason}`` — the tags whose source field is distrusted.

    Resolved through the PRODUCTION DECLARATIONS: a ``parsed`` declaration names its ``data`` field and
    (usually) its ``document_type``, so this maps a distrusted (document_type, field) onto the tag that
    reads it. A declaration WITHOUT a document_type scope matches on field name alone — deliberately
    conservative: an unscoped parsed tag could read that field from any document.

    ⚠️ Field resolution covers ``parsed`` declarations only. A DERIVED tag computes from other tags, so
    inferring which fields its recipe reads would be guesswork — the very inference this layer exists to
    avoid. Such a tag is named EXPLICITLY in the file's ``tags:`` section instead (IH-1's
    ``ins.dwelling_settlement_basis`` is the motivating case), and those are merged in here.
    """
    # LAZY IMPORT — the declarations loader lives in tag_materialization, which imports from rules; the
    # projection loader navigates the same cycle the same way.
    from app.verification.tag_materialization.declarations import ProductionMode, load_declarations

    distrusted = load_distrusted_fields()
    out: dict[str, str] = {}
    for tag_id, decl in load_declarations().items():
        if decl.mode is not ProductionMode.PARSED:
            continue
        field = decl.data.split(":", 1)[0]  # a ``field:hash`` suffix is not part of the field name
        doc_type = getattr(decl, "document_type", None)
        for (listed_type, listed_field), reason in distrusted.items():
            if listed_field != field:
                continue
            if doc_type is None or doc_type == listed_type:
                out[tag_id] = reason
                break
    # The explicitly-named tags (derived, or a differently-named list-row field). Stated, never inferred.
    explicit = (yaml.safe_load(_PATH.read_text()) or {}).get("tags") or {}
    if not isinstance(explicit, dict):
        raise DistrustError("distrusted_fields.yaml `tags` must map tag_id -> reason")
    known = set(load_declarations())
    for tag_id, reason in explicit.items():
        text = str(reason or "").strip()
        if not text:
            raise DistrustError(f"distrusted_fields.yaml tags.{tag_id}: a reason is REQUIRED")
        if tag_id not in known:
            raise DistrustError(
                f"distrusted_fields.yaml tags.{tag_id}: no such declared tag — a distrust entry naming a "
                "tag that does not exist would silently protect nothing"
            )
        out[str(tag_id)] = text
    return out


__all__ = ["DistrustError", "distrusted_tag_ids", "load_distrusted_fields"]
