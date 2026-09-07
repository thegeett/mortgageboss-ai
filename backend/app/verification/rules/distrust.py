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

# WHERE THE SPECS LIVE is now `app.documents.schema_fields`' problem, and the history is worth
# keeping because it is why that module raises instead of returning empty. This file used to derive
# the directory as ``parents[4] / "docs" / "schema-specs"``, which counted on a ``backend/``
# directory that exists in the repo and NOT in the image: the container's package root is ``/app``,
# so the walk landed on ``/docs/schema-specs``, the spec set came back EMPTY, and every
# containerised rule-engine run raised DistrustError on the first ``fields:`` entry — a packaging
# problem reported as a rename of the first-listed field, for the whole life of the image.


class DistrustError(Exception):
    """The distrusted-field list is malformed, or names something that does not exist."""


@cache
def _document() -> dict[str, object]:
    """The parsed YAML, loaded and root-shape-checked ONCE.

    Both sections used to re-read and re-parse the file independently, and the second read did not guard
    the root type — a list or scalar root raised ``AttributeError`` from inside ``evaluate_gate`` instead
    of a ``DistrustError``. One load, one guard.
    """
    raw = yaml.safe_load(_PATH.read_text())
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise DistrustError("distrusted_fields.yaml: the top level must be a mapping")
    return raw


@cache
def _schema_fields() -> set[tuple[str, str]]:
    """Every ``(document_type, field)`` the schema specs declare — typed core AND nested-list rows.

    The universe a ``fields:`` entry must name something in. Built from ``app/schema_specs/*.json``
    rather than from parsed declarations, because a distrusted field is a property of the DOCUMENT, and
    the tag that reads it may be derived (IH-1's case) or not exist yet.

    DELEGATES to :mod:`app.documents.schema_fields` (LP-703), which grew a second caller when a
    processor became able to ADD a field by hand and that key had to be checked against the same
    universe. Two copies of this walk is how they come to disagree about what a type declares.

    An unreadable spec directory still raises HERE, as ``DistrustError``, naming the directory —
    falling through with an empty set made every ``fields:`` entry look like a typo, so a packaging
    problem was reported as a rename of the first-listed field.
    """
    from app.documents.schema_fields import SchemaSpecsUnreadable, schema_field_pairs

    try:
        return schema_field_pairs()
    except SchemaSpecsUnreadable as exc:
        raise DistrustError(str(exc)) from exc


@cache
def load_distrusted_fields() -> dict[tuple[str, str], str]:
    """``{(document_type, field): reason}`` — the declared list, validated.

    An entry with a blank reason is rejected: a bare field name is unreviewable later and cannot be pruned
    with confidence, which is the whole point of keeping the list small.

    ⚠️ An entry naming a field NO schema spec declares is rejected too. The two sections used to disagree
    about failing loud — ``tags:`` raised on an unknown tag id ("a distrust entry naming a tag that does
    not exist would silently protect nothing") while ``fields:`` silently dropped an unmatched entry. The
    asymmetry meant a typo, or an extractor renaming a field, would disable protection with nothing
    failing anywhere. Same reasoning, so: same behaviour.
    """
    raw = _document().get("fields") or {}
    if not isinstance(raw, dict):
        raise DistrustError(
            "distrusted_fields.yaml `fields` must map document_type -> {field: reason}"
        )
    known_fields = _schema_fields()
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
            if (str(document_type), str(field)) not in known_fields:
                raise DistrustError(
                    f"distrusted_fields.yaml {document_type}.{field}: no schema spec declares that field "
                    "on that document type — a distrust entry that resolves to nothing silently protects "
                    "nothing (check for a typo, or an extractor field rename)"
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
    avoid. Such a tag is named EXPLICITLY in the file's ``tags:`` section instead, and those are merged
    in here.

    ⚠️ THE TRAP THIS WALKED INTO, recorded so the next entry does not repeat it: a rule almost never gates
    on the PARSED tag. It gates on a DERIVED tag computed from it — ID-5 on ``id.borrower_id_expiration``,
    CR-13 on ``credit.report_age_months_at_closing``, PR-6 on ``property.appraisal_age_months_at_closing``.
    Listing only the field therefore protected NOTHING for those three: the distrusted set held the parsed
    upstream tags, and no rule read them. Every derived consumer must be named in ``tags:`` explicitly.
    ``test_every_distrusted_field_reaches_a_rule`` now fails when one is missing.
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
    explicit = _document().get("tags") or {}
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
