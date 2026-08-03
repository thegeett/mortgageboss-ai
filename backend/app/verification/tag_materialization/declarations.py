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

from app.documents.catalog import CATALOG

_RULES_DIR = Path(__file__).parents[1] / "rules"
_FACT_TAGS_CSV = _RULES_DIR / "fact_tags.csv"
_PRODUCTION_YAML = _RULES_DIR / "tag_production.yaml"
# LP-328 (GAP-E): the HAND-EDITABLE vocabulary overlay lives HERE (the vocabulary loader) rather than
# in projection, so declarations owns the vocabulary's source of truth (CSV + overlay) and no longer
# imports projection — the two are one-directional (projection reads the vocabulary, not vice versa).
_VOCAB_EXTRA_YAML = _RULES_DIR / "vocabulary_extra.yaml"

# The subject keys a production declaration may attach a tag to (resolved by the subjects registry).
# LP-332 added `borrower` (a tag keyed by borrower_id, materialized from MISMO borrower.{n}.*).
KNOWN_SUBJECTS = frozenset({"transaction", "document", "loan", "borrower"})

# The subjects a DERIVED recipe may be declared for. LP-332 generalized the derived producer beyond
# loan-only; the producer enumerates the subject registry and passes the subject's own raw object to the
# recipe, keyed under its subject_id. loan/borrower recipes read loan-level MISMO / a borrower's facts.
# LP-447 adds DOCUMENT: a per-document derived recipe (ins.dwelling_settlement_basis) that reads its OWN
# DocumentEntry and keys under the content_id — the producer already handles this correctly (verified), so
# a document recipe does NOT mis-key. A derived tag on `transaction` stays unsupported (no recipe reads a
# TransactionRecord). Each recipe still asserts its expected raw type, so a wrong subject fails loudly.
_DERIVED_SUBJECTS = frozenset({"loan", "borrower", "document"})


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
    """One AI structuring pass — a subject, the tags it co-produces, a context builder, a prompt.

    ``applies_to`` (LP-377-D) declares the DOCUMENT TYPES a per-document group is relevant to — the
    applicability that was always IMPLICIT in the prompt's runtime "not my document" abstention, now
    DECLARED so the dispatcher can skip the redundant call (and stop a group over-producing on a document
    it doesn't apply to). ``None`` = "all" (runs on every document — cross-document / presence groups, and
    a fail-open default). Only consulted for ``subject == "document"`` groups; the gate ALWAYS fails open on
    an unknown/low-confidence/no-match document (see the dispatcher)."""

    key: str
    subject: str
    context_builder: str
    tag_ids: tuple[str, ...]
    system_prompt: str
    applies_to: frozenset[str] | None = None  # None = all document types (fail-open default)
    # LP-390-8a — a DOCUMENT group that must compare a document's stated party against the loan's borrowers
    # (stmt.owner_matches_borrower) declares this; the producer then adds the loan's borrower roster to the
    # group's context. DECLARED (not a per-group code branch): a group that does not set it is byte-unchanged.
    include_borrower_roster: bool = False
    # LP-444 — a group that needs a document's GENERIC LISTS (LP-437: entry.lists — tradelines, etc.) in its
    # context OPTS IN here. DECLARED, opt-in only: a group that does not set it sees NO list data, so every
    # existing group's context is byte-unchanged. The serialiser caps each list + marks truncation + scrubs
    # list-row values (subjects.py); only document/borrower subjects carry documents (hence lists).
    include_lists: bool = False
    # LP-444 — the per-list row cap (how many rows are serialised before the truncation marker fires).
    # Per-group so a dense list (a long credit report) can be given more rows; default is the module default.
    list_row_cap: int = 50
    # LP-444 — a BORROWER group that must compare against the app's file-level MISMO liabilities (CR-4:
    # undisclosed tradeline) opts in here; the borrower context then adds `stated_liabilities`. Off by
    # default → an existing borrower group is byte-unchanged.
    include_stated_liabilities: bool = False


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


def load_vocab_extra() -> dict[str, dict[str, Any]]:
    """The hand-editable vocabulary overlay (LP-328, GAP-E) -> ``{tag_id: field-dict}`` (empty when the
    file has no tags). Shaped to match a ``fact_tags.csv`` row so projection treats both alike. Each
    entry needs ``entity`` + ``value_type``; ``allowed_values`` (list | null) drives AI coercion.

    Owned here (the vocabulary loader) so both readers — projection (rows) and ``_allowed_values_by_tag``
    (coercion domains) — import ONE reader without a projection<->declarations import cycle.
    """
    if not _VOCAB_EXTRA_YAML.is_file():
        return {}
    raw = yaml.safe_load(_VOCAB_EXTRA_YAML.read_text(encoding="utf-8")) or {}
    tags = raw.get("tags") if isinstance(raw, dict) else None
    if not isinstance(tags, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for tag_id, body in tags.items():
        if not isinstance(body, dict) or not body.get("entity") or not body.get("value_type"):
            raise DeclarationError(
                f"vocabulary_extra.yaml tag {tag_id!r} needs at least `entity` and `value_type`"
            )
        allowed = body.get("allowed_values")
        out[str(tag_id).strip()] = {
            "entity": str(body["entity"]).strip(),
            "value_type": str(body["value_type"]).strip(),
            "allowed_values": [str(v) for v in allowed] if isinstance(allowed, list) else None,
            "description": str(body.get("description", "")),
            "produced_by": str(body.get("produced_by", "derived")).strip(),
            "tag_role": None,
            "tag_version": int(body.get("tag_version", 1)),
            "extras": {
                "decision": "",
                "used_by_rules": "",
                "type_raw": "",
                "source": "vocabulary_extra",
            },
        }
    return out


@cache
def _allowed_values_by_tag() -> dict[str, tuple[str, ...] | None]:
    """The vocabulary's ``allowed_values`` per tag — from the generated ``fact_tags.csv`` AND the
    hand-editable overlay (LP-328), so a wave-added tag's domain is available for AI coercion.

    A duplicate overlay tag_id (already in the CSV) FAILS LOUD — the same guard projection enforces, so
    the two overlay readers can never disagree (never silently shadow an xlsx-authored tag's domain)."""
    allowed: dict[str, tuple[str, ...] | None] = {}
    with _FACT_TAGS_CSV.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            allowed[row["tag_id"].strip()] = _parse_allowed(row.get("allowed_values") or "")
    for tag_id, body in load_vocab_extra().items():
        if tag_id in allowed:
            raise DeclarationError(
                f"vocabulary_extra.yaml tag {tag_id!r} duplicates a fact_tags.csv tag "
                "(hand-added tags must be NEW — remove it from the overlay or the xlsx)"
            )
        values = body.get("allowed_values")
        allowed[tag_id] = tuple(str(v) for v in values) if isinstance(values, list) else None
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
        roster = body.get("include_borrower_roster", False)
        if not isinstance(roster, bool):
            raise DeclarationError(
                f"ai group {key!r}: `include_borrower_roster` must be a boolean, got {roster!r}"
            )
        if roster and subject != "document":
            raise DeclarationError(
                f"ai group {key!r}: `include_borrower_roster` is only for a document-subject group "
                f"(the roster is the comparison context for a document's stated party), got subject={subject!r}"
            )
        include_lists = body.get("include_lists", False)
        if not isinstance(include_lists, bool):
            raise DeclarationError(
                f"ai group {key!r}: `include_lists` must be a boolean, got {include_lists!r}"
            )
        if include_lists and subject not in ("document", "borrower"):
            raise DeclarationError(
                f"ai group {key!r}: `include_lists` is only for a document- or borrower-subject group "
                f"(only those carry documents, hence generic lists), got subject={subject!r}"
            )
        cap = body.get("list_row_cap", 50)
        if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
            raise DeclarationError(
                f"ai group {key!r}: `list_row_cap` must be a positive integer, got {cap!r}"
            )
        include_liabilities = body.get("include_stated_liabilities", False)
        if not isinstance(include_liabilities, bool):
            raise DeclarationError(
                f"ai group {key!r}: `include_stated_liabilities` must be a boolean, got {include_liabilities!r}"
            )
        if include_liabilities and subject != "borrower":
            raise DeclarationError(
                f"ai group {key!r}: `include_stated_liabilities` is only for a borrower-subject group "
                f"(the file-level liabilities are the per-borrower comparison set), got subject={subject!r}"
            )
        groups[key] = AiGroup(
            key=key,
            subject=subject,
            context_builder=context_builder,
            tag_ids=tuple(str(t) for t in tags),
            system_prompt=prompt,
            applies_to=_parse_applies_to(key, subject, body.get("applies_to")),
            include_borrower_roster=roster,
            include_lists=include_lists,
            list_row_cap=cap,
            include_stated_liabilities=include_liabilities,
        )
    return groups


def _parse_applies_to(key: str, subject: str, raw: object) -> frozenset[str] | None:
    """``applies_to`` (LP-377-D): a list of document-type slugs, or absent / ``"all"`` → None (all types).

    None is the fail-open default — an omitted or ``all`` declaration runs the group on every document, so a
    group is never accidentally narrowed by a missing entry (too-wide is a redundant call; too-narrow is a
    silent-dead tag). Guarded at load: ``applies_to`` is document-only (the dispatcher only gates document
    subjects), and every slug MUST be a real document type in the catalog — a typo / rename would otherwise
    silently gate the group to death (LP-373's silent-dead-tag class)."""
    if raw is None or (isinstance(raw, str) and raw.strip().lower() == "all"):
        return None
    # `applies_to` names document types, so it is only meaningful for a group that GATES on them
    # (document subject — LP-377-D dispatcher gate) or GATHERS them (borrower subject — LP-385 context
    # filter). On a loan/transaction group it would silently do nothing, so reject it.
    if subject not in ("document", "borrower"):
        raise DeclarationError(
            f"ai group {key!r}: `applies_to` is only meaningful for a document- or borrower-subject group "
            f"(subject={subject!r} does not gate or gather documents) — use 'all' or omit it"
        )
    if not isinstance(raw, list) or not all(isinstance(v, str) and v.strip() for v in raw):
        raise DeclarationError(
            f"ai group {key!r}: `applies_to` must be a non-empty list of document-type strings or 'all'"
        )
    slugs = frozenset(v.strip() for v in raw)
    unknown = slugs - set(CATALOG)
    if unknown:
        raise DeclarationError(
            f"ai group {key!r}: `applies_to` names document types not in the catalog: "
            f"{sorted(unknown)} — a typo or renamed slug would silently gate the group to death"
        )
    return slugs


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
        # LP-332: derived recipes run for a declared subject (the producer enumerates the subject registry,
        # like parsed/ai). Supported subjects are in _DERIVED_SUBJECTS — loan, borrower, and (LP-447) document
        # (a per-document recipe reads its own DocumentEntry, keyed under content_id; the producer handles
        # this and each recipe asserts its raw type). `transaction` stays unsupported (no recipe reads a
        # TransactionRecord), so a derived tag declared for it is rejected at load.
        if decl.mode is ProductionMode.DERIVED:
            if decl.subject not in _DERIVED_SUBJECTS:
                raise DeclarationError(
                    f"tag {decl.tag_id!r}: derived subject {decl.subject!r} is not supported "
                    f"(a recipe is written for {sorted(_DERIVED_SUBJECTS)})"
                )
            if decl.data not in known_recipes:
                raise DeclarationError(
                    f"tag {decl.tag_id!r}: unknown derived recipe {decl.data!r} "
                    f"(known: {sorted(known_recipes)})"
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
    "load_vocab_extra",
    "validate_declarations",
]
