"""The production DECLARATION — how each vocabulary tag is materialized (LP-326).

Production is a property of the TAG, declared in the vocabulary (``fact_tags.csv``'s ``production_*``
columns + the ``tag_ai_groups.yaml`` companion for AI prompts), not per-family Python. A tag declares
its MODE (parsed / derived / ai), the SUBJECT it is keyed under (transaction / document / loan — the
LP-325 keying, distinct from the logical ``entity``), and mode data (a field / a recipe key / an AI
group). A tag with NO declaration is simply not-yet-materialized (its family's wave will declare it);
a tag WITH one that is invalid FAILS LOUD (no silently-unproducible tag).

This module reads + validates the declarations; the generic producers (``parsed`` / ``derived`` /
``ai``) resolve them against the subject / recipe / AI-group registries.

The declaration lives in ``tag_production.yaml`` (a companion to the vocabulary) rather than in
``fact_tags.csv`` because that CSV is GENERATED from ``docs/snapshot-fact-tags.xlsx`` — a hand-edited
column there would be overwritten by the generator. The YAML is the version-controlled home for
production; the tag's ``allowed_values`` still come from the generated vocabulary CSV.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any

import yaml

_RULES_DIR = Path(__file__).parents[1] / "rules"
_FACT_TAGS_CSV = _RULES_DIR / "fact_tags.csv"
_PRODUCTION_YAML = _RULES_DIR / "tag_production.yaml"

# The subject keys a production declaration may attach a tag to (resolved by the subjects registry).
KNOWN_SUBJECTS = frozenset({"transaction", "document", "loan"})


class DeclarationError(Exception):
    """A production declaration is missing required data or references an unknown registry key."""


class ProductionMode(StrEnum):
    PARSED = "parsed"
    DERIVED = "derived"
    AI = "ai"


@dataclass(frozen=True)
class TagDeclaration:
    """One tag's production declaration (from ``fact_tags.csv``)."""

    tag_id: str
    mode: ProductionMode
    subject: str
    data: str  # parsed: field[:hash] · derived: recipe key · ai: group key
    allowed_values: tuple[str, ...] | None  # the vocabulary's allowed_values (for ai coercion)


@dataclass(frozen=True)
class AiGroup:
    """One AI structuring pass — a subject, the tags it co-produces, a context builder, a prompt."""

    key: str
    subject: str
    context_builder: str
    tag_ids: tuple[str, ...]
    system_prompt: str


def _parse_allowed(raw: str) -> tuple[str, ...] | None:
    raw = raw.strip()
    if not raw:
        return None
    import json

    parsed = json.loads(raw)
    return tuple(str(v) for v in parsed) if isinstance(parsed, list) else None


@cache
def _production_doc() -> dict[str, Any]:
    """The parsed ``tag_production.yaml`` (a mapping with ``tags`` + ``ai_groups`` sections)."""
    raw = yaml.safe_load(_PRODUCTION_YAML.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise DeclarationError("tag_production.yaml must be a mapping")
    return raw


@cache
def _allowed_values_by_tag() -> dict[str, tuple[str, ...] | None]:
    """The vocabulary's ``allowed_values`` per tag (from the generated ``fact_tags.csv``)."""
    allowed: dict[str, tuple[str, ...] | None] = {}
    with _FACT_TAGS_CSV.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            allowed[row["tag_id"].strip()] = _parse_allowed(row.get("allowed_values") or "")
    return allowed


@cache
def load_ai_groups() -> dict[str, AiGroup]:
    """Load + validate the AI-group declarations (``tag_production.yaml`` ``ai_groups`` section)."""
    raw_groups = _production_doc().get("ai_groups") or {}
    if not isinstance(raw_groups, dict):
        raise DeclarationError(
            "tag_production.yaml `ai_groups` must be a mapping of group_key -> group"
        )
    groups: dict[str, AiGroup] = {}
    for key, body in raw_groups.items():
        if not isinstance(body, dict):
            raise DeclarationError(f"ai group {key!r} must be a mapping")
        subject = str(body.get("subject", "")).strip()
        context_builder = str(body.get("context_builder", "")).strip()
        tags = body.get("tags")
        prompt = body.get("system_prompt")
        if subject not in KNOWN_SUBJECTS:
            raise DeclarationError(f"ai group {key!r}: unknown subject {subject!r}")
        if not isinstance(tags, list) or not tags:
            raise DeclarationError(f"ai group {key!r}: `tags` must be a non-empty list")
        if not isinstance(prompt, str) or not prompt.strip():
            raise DeclarationError(f"ai group {key!r}: `system_prompt` is required")
        groups[key] = AiGroup(
            key=key,
            subject=subject,
            context_builder=context_builder,
            tag_ids=tuple(str(t) for t in tags),
            system_prompt=prompt,
        )
    return groups


@cache
def load_declarations() -> dict[str, TagDeclaration]:
    """Load the per-tag production declarations (``tag_production.yaml`` ``tags`` section).

    A tag absent here is not-yet-materialized. A declared tag with a missing/unknown mode or subject
    FAILS LOUD (no silently-unproducible tag). ``allowed_values`` are read from the vocabulary CSV.
    """
    raw_tags = _production_doc().get("tags") or {}
    if not isinstance(raw_tags, dict):
        raise DeclarationError(
            "tag_production.yaml `tags` must be a mapping of tag_id -> declaration"
        )
    allowed = _allowed_values_by_tag()
    declarations: dict[str, TagDeclaration] = {}
    for tag_id, body in raw_tags.items():
        if not isinstance(body, dict):
            raise DeclarationError(f"tag {tag_id!r}: declaration must be a mapping")
        mode_raw = str(body.get("mode", "")).strip()
        try:
            mode = ProductionMode(mode_raw)
        except ValueError as exc:
            raise DeclarationError(
                f"tag {tag_id!r}: unknown mode {mode_raw!r} "
                f"(known: {[m.value for m in ProductionMode]})"
            ) from exc
        subject = str(body.get("subject", "")).strip()
        data = str(body.get("data", "")).strip()
        if subject not in KNOWN_SUBJECTS:
            raise DeclarationError(
                f"tag {tag_id!r}: subject {subject!r} is not a known subject ({sorted(KNOWN_SUBJECTS)})"
            )
        if not data:
            raise DeclarationError(f"tag {tag_id!r}: `data` is required for mode {mode}")
        if tag_id not in allowed:
            raise DeclarationError(
                f"tag {tag_id!r}: declared for production but absent from the fact-tag vocabulary"
            )
        declarations[tag_id] = TagDeclaration(
            tag_id=tag_id, mode=mode, subject=subject, data=data, allowed_values=allowed[tag_id]
        )
    return declarations


def validate_declarations(
    *, known_recipes: frozenset[str], known_context_builders: frozenset[str]
) -> None:
    """Fail loud on any declaration whose mode data cannot be resolved (no unproducible tag).

    Cross-checks: a ``derived`` recipe key exists; an ``ai`` group exists, targets the tag's subject,
    and LISTS the tag. ``parsed`` field validity is per-subject and checked at production time (a
    field simply absent → an absent tag, not an error). Called by the projection loader (LP-311).
    """
    ai_groups = load_ai_groups()
    for group in ai_groups.values():
        if group.context_builder not in known_context_builders:
            raise DeclarationError(
                f"ai group {group.key!r}: unknown context_builder {group.context_builder!r} "
                f"(known: {sorted(known_context_builders)})"
            )
    for decl in load_declarations().values():
        if decl.mode is ProductionMode.DERIVED:
            if decl.data not in known_recipes:
                raise DeclarationError(
                    f"tag {decl.tag_id!r}: unknown derived recipe {decl.data!r} "
                    f"(known: {sorted(known_recipes)})"
                )
            # Derived recipes are snapshot -> ONE value (loan-level) today; a non-loan subject would
            # be silently misrouted to the loan subject, so reject it at load rather than at run.
            if decl.subject != "loan":
                raise DeclarationError(
                    f"tag {decl.tag_id!r}: derived recipes are loan-level today; "
                    f"subject {decl.subject!r} is unsupported"
                )
        if decl.mode is ProductionMode.AI:
            ai_group = ai_groups.get(decl.data)
            if ai_group is None:
                raise DeclarationError(
                    f"tag {decl.tag_id!r}: unknown ai group {decl.data!r} "
                    f"(groups: {sorted(ai_groups)})"
                )
            if decl.tag_id not in ai_group.tag_ids:
                raise DeclarationError(
                    f"tag {decl.tag_id!r}: ai group {ai_group.key!r} does not list it in its tags"
                )
            if ai_group.subject != decl.subject:
                raise DeclarationError(
                    f"tag {decl.tag_id!r}: subject {decl.subject!r} disagrees with ai group "
                    f"{ai_group.key!r} subject {ai_group.subject!r}"
                )


__all__ = [
    "KNOWN_SUBJECTS",
    "AiGroup",
    "DeclarationError",
    "ProductionMode",
    "TagDeclaration",
    "load_ai_groups",
    "load_declarations",
    "validate_declarations",
]
