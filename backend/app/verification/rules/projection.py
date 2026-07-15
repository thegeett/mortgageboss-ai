"""Files -> DB projection loader for rules + fact-tags (LP-311, ADR-250).

The version-controlled FILES are the source of truth (§3D "Storage"):

* ``rule_kinds.csv``        — rule identity + kind + the Priya-validation gate flags
  (read through :func:`app.verification.rules.kinds.load_rule_kinds`, the gate of record).
* ``specs/<rule_id>.yaml``  — the full ``RuleSpec`` (read through
  :func:`app.verification.rules.specs.load_rule_spec`, which also cross-checks the CSV).
* ``fact_tags.csv``         — the fact-tag vocabulary.
* ``rule_tags.csv``         — rule -> required-tag edges.
* ``tag_dependencies.csv``  — the tag DAG (currently empty; no ``depends_on`` in the file yet).

This module PROJECTS those files into the ``rules`` / ``tags`` / ``rule_tags`` /
``tag_dependencies`` tables. The projection is a faithful mirror: it INSERTs new rows,
UPDATEs changed rows, and REMOVEs rows that vanished from the files. The DB carries no
truth the files do not, so a hand-mutated row is overwritten on the next run — the DB
is never a hand-edit path. The loader is idempotent: unchanged files produce no writes.

Before writing anything it runs the load-time CONSISTENCY checks (Phase 4) and FAILS
LOUD (:class:`ProjectionError`) on: a rule requiring a tag absent from the vocabulary,
a dependency edge to a non-existent tag, or a cycle in the tag DAG. Spec/CSV agreement
is enforced by ``load_rule_spec`` itself (``RuleSpecInconsistent``).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rule import Rule
from app.models.tag import RuleTag, Tag, TagDependency
from app.verification.rules.kinds import load_rule_kinds
from app.verification.rules.specs import RuleSpecNotFound, load_rule_spec

_RULES_DIR = Path(__file__).parent
_FACT_TAGS_CSV = _RULES_DIR / "fact_tags.csv"
_RULE_TAGS_CSV = _RULES_DIR / "rule_tags.csv"
_TAG_DEPS_CSV = _RULES_DIR / "tag_dependencies.csv"
# LP-328 (GAP-E): the HAND-EDITABLE vocabulary overlay. ``fact_tags.csv`` is GENERATED from the
# authoring xlsx (a binary a PR cannot review, and the generator would overwrite a hand-added row), so
# the waves ADD a tag here — a version-controlled YAML, reviewed in a PR, that the generator never
# touches. Same field shape as a fact_tags.csv row; a tag_id already in the vocabulary fails loud.
_VOCAB_EXTRA_YAML = _RULES_DIR / "vocabulary_extra.yaml"


class ProjectionError(Exception):
    """A source-file inconsistency that must block the projection (fail loud)."""


@dataclass
class _TableDelta:
    inserted: int = 0
    updated: int = 0
    deleted: int = 0

    def touched(self) -> bool:
        return bool(self.inserted or self.updated or self.deleted)


@dataclass
class ProjectionResult:
    """Per-table counts of what the projection changed (for logging + tests)."""

    rules: _TableDelta = field(default_factory=_TableDelta)
    tags: _TableDelta = field(default_factory=_TableDelta)
    rule_tags: _TableDelta = field(default_factory=_TableDelta)
    tag_dependencies: _TableDelta = field(default_factory=_TableDelta)

    def changed(self) -> bool:
        return any(
            d.touched() for d in (self.rules, self.tags, self.rule_tags, self.tag_dependencies)
        )


# --------------------------------------------------------------------------- #
# Desired state — read the files (pure; no DB). Testable on their own.
# --------------------------------------------------------------------------- #

# The rule fields compared/written (natural key ``rule_id`` excluded).
_RULE_FIELDS = (
    "name",
    "category",
    "kind",
    "evaluation_path",
    "numeric_check",
    "exact_match",
    "priya_validated",
    "threshold_needs_signoff",
    "rationale",
    "spec",
)
_TAG_FIELDS = (
    "entity",
    "value_type",
    "allowed_values",
    "description",
    "produced_by",
    "tag_role",
    "tag_version",
    "extras",
)


def load_desired_rules() -> dict[str, dict[str, Any]]:
    """rule_kinds.csv (+ any spec file) -> {rule_id: field-dict}.

    ``kind``/``evaluation_path`` come from the validated :class:`RuleKind` (enum
    values as strings). ``spec`` is the full ``RuleSpec`` payload when a spec file
    exists (which also validates it against the CSV), else ``None``.
    """
    desired: dict[str, dict[str, Any]] = {}
    for rule_id, rk in load_rule_kinds().items():
        try:
            spec = load_rule_spec(rule_id).model_dump(mode="json")
        except RuleSpecNotFound:
            spec = None
        desired[rule_id] = {
            "name": rk.name,
            "category": rk.category,
            "kind": rk.kind.value,
            "evaluation_path": rk.evaluation_path.value,
            "numeric_check": rk.numeric_check,
            "exact_match": rk.exact_match,
            "priya_validated": rk.priya_validated,
            "threshold_needs_signoff": rk.threshold_needs_signoff,
            "rationale": rk.rationale,
            "spec": spec,
        }
    return desired


def load_desired_tags() -> dict[str, dict[str, Any]]:
    """fact_tags.csv (+ the hand-editable vocabulary_extra.yaml overlay) -> {tag_id: field-dict}."""
    desired: dict[str, dict[str, Any]] = {}
    with _FACT_TAGS_CSV.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            tag_id = row["tag_id"].strip()
            # A duplicate tag_id must fail loud (like the rule loader), not silently
            # overwrite the earlier row — a shadowed vocabulary definition is exactly
            # the kind of source-file inconsistency this projection exists to catch.
            if tag_id in desired:
                raise ProjectionError(f"duplicate tag_id in fact_tags.csv: {tag_id!r}")
            allowed_raw = row.get("allowed_values", "").strip()
            desired[tag_id] = {
                "entity": row["entity"].strip(),
                "value_type": row["value_type"].strip(),
                "allowed_values": json.loads(allowed_raw) if allowed_raw else None,
                "description": row["description"],
                "produced_by": row["produced_by"].strip(),
                # Not in the vocabulary file yet (LP-311 Phase 0).
                "tag_role": None,
                "tag_version": 1,
                "extras": {
                    "decision": row.get("decision", "").strip(),
                    "used_by_rules": row.get("used_by_rules", "").strip(),
                    "type_raw": row.get("type_raw", "").strip(),
                },
            }
    _merge_vocab_extra(desired)
    return desired


def _merge_vocab_extra(desired: dict[str, dict[str, Any]]) -> None:
    """Merge the hand-editable overlay (LP-328, GAP-E). A tag_id already in the vocabulary fails loud
    (never silently shadow an xlsx-authored tag)."""
    for tag_id, body in load_vocab_extra().items():
        if tag_id in desired:
            raise ProjectionError(
                f"vocabulary_extra.yaml tag {tag_id!r} duplicates a fact_tags.csv tag — "
                "hand-added tags must be NEW (remove it from the overlay or the xlsx)"
            )
        desired[tag_id] = body


def load_vocab_extra() -> dict[str, dict[str, Any]]:
    """The hand-editable vocabulary overlay -> {tag_id: field-dict} (empty when the file has no tags).

    Each entry: ``entity`` / ``value_type`` (required); ``allowed_values`` (list | null), ``description``,
    ``produced_by`` (optional). Shaped to match a fact_tags.csv row so the projection treats both alike.
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
            raise ProjectionError(
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


def _load_edges(path: Path, left: str, right: str) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            a, b = row[left].strip(), row[right].strip()
            if a and b:
                edges.add((a, b))
    return edges


def load_desired_rule_tags() -> set[tuple[str, str]]:
    """rule_tags.csv -> {(rule_id, tag_id)}."""
    return _load_edges(_RULE_TAGS_CSV, "rule_id", "tag_id")


def load_desired_tag_dependencies() -> set[tuple[str, str]]:
    """tag_dependencies.csv -> {(tag_id, depends_on_tag_id)} (empty today)."""
    return _load_edges(_TAG_DEPS_CSV, "tag_id", "depends_on_tag_id")


# --------------------------------------------------------------------------- #
# Consistency checks (Phase 4) — pure; raise ProjectionError. No DB.
# --------------------------------------------------------------------------- #


def check_consistency(
    *,
    rules: dict[str, dict[str, Any]],
    tags: dict[str, dict[str, Any]],
    rule_tags: set[tuple[str, str]],
    tag_dependencies: set[tuple[str, str]],
) -> None:
    """Fail loud on any file inconsistency before touching the DB."""
    # A rule may only require a tag that exists in the vocabulary, and only a rule
    # that exists may appear in the mapping.
    for rule_id, tag_id in sorted(rule_tags):
        if rule_id not in rules:
            raise ProjectionError(
                f"rule_tags references unknown rule {rule_id!r} (not in rule_kinds.csv)"
            )
        if tag_id not in tags:
            raise ProjectionError(
                f"rule {rule_id!r} requires tag {tag_id!r}, which is not in the fact-tag "
                f"vocabulary (fact_tags.csv)"
            )
    # Every dependency edge must reference existing tags on both ends.
    for tag_id, dep in sorted(tag_dependencies):
        if tag_id not in tags:
            raise ProjectionError(
                f"tag_dependencies references unknown tag {tag_id!r} (not in fact_tags.csv)"
            )
        if dep not in tags:
            raise ProjectionError(
                f"tag {tag_id!r} depends on unknown tag {dep!r} (not in fact_tags.csv)"
            )
    _reject_cycle(tag_dependencies)
    # Every tag with a PRODUCTION declaration (LP-326) must resolve to a real producer — no
    # silently-unproducible tag. Fails loud on an unknown mode/subject/recipe/ai-group.
    _check_production_declarations()


def _check_production_declarations() -> None:
    """Fail loud on any invalid tag-production declaration (LP-326)."""
    from app.verification.tag_materialization.declarations import (
        DeclarationError,
        validate_declarations,
    )
    from app.verification.tag_materialization.derived import KNOWN_RECIPES
    from app.verification.tag_materialization.subjects import KNOWN_CONTEXT_BUILDERS

    try:
        validate_declarations(
            known_recipes=KNOWN_RECIPES, known_context_builders=KNOWN_CONTEXT_BUILDERS
        )
    except DeclarationError as exc:
        raise ProjectionError(f"invalid tag-production declaration: {exc}") from exc


def _reject_cycle(edges: set[tuple[str, str]]) -> None:
    """Raise if the tag-dependency graph (tag -> depends_on) has a cycle."""
    adjacency: dict[str, list[str]] = {}
    for tag_id, dep in edges:
        adjacency.setdefault(tag_id, []).append(dep)

    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = {}

    def visit(node: str, stack: list[str]) -> None:
        color[node] = GREY
        stack.append(node)
        for nxt in adjacency.get(node, ()):
            if color.get(nxt, WHITE) == GREY:
                cycle = [*stack[stack.index(nxt) :], nxt]
                raise ProjectionError("tag_dependencies contains a cycle: " + " -> ".join(cycle))
            if color.get(nxt, WHITE) == WHITE:
                visit(nxt, stack)
        stack.pop()
        color[node] = BLACK

    for node in list(adjacency):
        if color.get(node, WHITE) == WHITE:
            visit(node, [])


# --------------------------------------------------------------------------- #
# Reconcile (the DB write). FK-safe order: upsert parents -> reconcile child
# edges -> delete stale parents. Only real diffs are written (idempotent).
# --------------------------------------------------------------------------- #


async def _upsert_rules(
    session: AsyncSession, desired: dict[str, dict[str, Any]], delta: _TableDelta
) -> None:
    existing = {r.rule_id: r for r in (await session.scalars(select(Rule))).all()}
    for rule_id, fields in desired.items():
        row = existing.get(rule_id)
        if row is None:
            session.add(Rule(rule_id=rule_id, **fields))
            delta.inserted += 1
        elif any(getattr(row, f) != fields[f] for f in _RULE_FIELDS):
            for f in _RULE_FIELDS:
                setattr(row, f, fields[f])
            delta.updated += 1


async def _upsert_tags(
    session: AsyncSession, desired: dict[str, dict[str, Any]], delta: _TableDelta
) -> None:
    existing = {t.tag_id: t for t in (await session.scalars(select(Tag))).all()}
    for tag_id, fields in desired.items():
        row = existing.get(tag_id)
        if row is None:
            session.add(Tag(tag_id=tag_id, **fields))
            delta.inserted += 1
        elif any(getattr(row, f) != fields[f] for f in _TAG_FIELDS):
            for f in _TAG_FIELDS:
                setattr(row, f, fields[f])
            delta.updated += 1


async def _delete_stale(
    session: AsyncSession,
    model: type[Rule] | type[Tag],
    key: str,
    desired_keys: set[str],
    delta: _TableDelta,
) -> None:
    for row in (await session.scalars(select(model))).all():
        if getattr(row, key) not in desired_keys:
            await session.delete(row)
            delta.deleted += 1


async def _reconcile_edges(
    session: AsyncSession,
    model: type[RuleTag] | type[TagDependency],
    left: str,
    right: str,
    desired: set[tuple[str, str]],
    delta: _TableDelta,
) -> None:
    existing_rows = (await session.scalars(select(model))).all()
    existing: dict[tuple[str, str], Any] = {
        (getattr(r, left), getattr(r, right)): r for r in existing_rows
    }
    for key, row in existing.items():
        if key not in desired:
            await session.delete(row)
            delta.deleted += 1
    for a, b in desired - set(existing):
        session.add(model(**{left: a, right: b}))
        delta.inserted += 1


async def project_files_to_db(session: AsyncSession) -> ProjectionResult:
    """Reconcile the DB projection to the source files. FLUSHES; caller commits.

    Reads the files, runs the consistency checks (fails loud), then applies the
    minimal set of inserts/updates/deletes so the four tables mirror the files. The
    caller owns the transaction boundary (the CLI commits; tests roll back), so this
    flushes rather than commits.
    """
    desired_rules = load_desired_rules()
    desired_tags = load_desired_tags()
    desired_rule_tags = load_desired_rule_tags()
    desired_tag_deps = load_desired_tag_dependencies()

    check_consistency(
        rules=desired_rules,
        tags=desired_tags,
        rule_tags=desired_rule_tags,
        tag_dependencies=desired_tag_deps,
    )

    result = ProjectionResult()
    # Parents first (so child edges can reference them), no deletes yet.
    await _upsert_rules(session, desired_rules, result.rules)
    await _upsert_tags(session, desired_tags, result.tags)
    await session.flush()
    # Child edges: delete stale + insert new (all referenced parents now exist).
    await _reconcile_edges(
        session, RuleTag, "rule_id", "tag_id", desired_rule_tags, result.rule_tags
    )
    await _reconcile_edges(
        session,
        TagDependency,
        "tag_id",
        "depends_on_tag_id",
        desired_tag_deps,
        result.tag_dependencies,
    )
    await session.flush()
    # Stale parents last (their child edges, if any, are already gone).
    await _delete_stale(session, Rule, "rule_id", set(desired_rules), result.rules)
    await _delete_stale(session, Tag, "tag_id", set(desired_tags), result.tags)

    await session.flush()
    return result
