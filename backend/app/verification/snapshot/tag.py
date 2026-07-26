"""The fact-tag object model (LP-312, ADR-251) — the §3D tag contract.

A tag is the AI-structured, honest unit of the tags layer: it turns messy raw facts into a
clean structured value that deterministic code can query. Every tag is uniform — value +
confidence + reasoning + the raw facts it cites — so a wrong tag can be traced, not trusted
blindly (§3D "the armor"). This module is the TYPE ONLY: no production, no AI call, no rule
evaluation (LP-313/314 produce tags; this ships the shape they target).

The contract (§3D)::

    { "value": "no",                 # domain ALWAYS includes "unknown"; never fabricated
      "confidence": 0.62,            # nullable — null for parsed, a number for AI, never invented
      "reasoning": "no matching payroll…",
      "source_facts": ["txn_002"],   # STABLE content-ids into the raw layer (never array position)
      "produced_by": "ai",           # parsed | ai | derived | spec
      "tag_role": "structural_fact", # structural_fact (many rules) | rule_judgment (one rule)
      "tag_version": 1,              # additive-only vocabulary version
      "stage": "B" }                 # A = per-entity atomic; B = cross-entity correlation

Frozen, consistent with the rest of the snapshot (LP-204 immutability).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, JsonValue, field_validator
from pydantic import Field as PydField


class TagProducedBy(StrEnum):
    """Who produced the tag value (§3D ``produced_by``)."""

    PARSED = "parsed"  # read straight from a deterministic parse (confidence is null/1.0)
    AI = "ai"  # an AI structuring judgment (carries a real confidence)
    DERIVED = "derived"  # computed deterministically from other tags/facts
    SPEC = "spec"  # supplied by a rule spec (a Priya-validated threshold, etc.)


class TagRole(StrEnum):
    """Whether the tag is a shared fact or a single rule's judgment (§3D ``tag_role``)."""

    STRUCTURAL_FACT = "structural_fact"  # a reusable fact many rules read
    RULE_JUDGMENT = "rule_judgment"  # one rule's own judgment


class TagStage(StrEnum):
    """Which production stage emits the tag (§3D ``stage``)."""

    A = "A"  # per-entity atomic (from a single entity's raw facts)
    B = "B"  # cross-entity correlation (needs other entities' tags)


class Tag(BaseModel):
    """One fact-tag instance — the uniform honest object of the tags layer.

    ``value`` is any JSON value and its domain ALWAYS includes the string ``"unknown"`` — a
    tag never fabricates certainty. ``confidence`` is nullable (a genuine number for AI, null
    for a parsed fact — never an invented default). ``source_facts`` are the STABLE
    ``content_id``\\s (LP-312) of the raw facts this tag relied on — never array positions —
    so provenance survives a rebuild. Frozen: a built tag is never mutated.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    value: JsonValue = None
    confidence: float | None = None
    reasoning: str | None = None
    source_facts: tuple[str, ...] = ()
    produced_by: TagProducedBy
    tag_role: TagRole
    tag_version: int = PydField(default=1, ge=1)
    stage: TagStage

    @field_validator("confidence")
    @classmethod
    def _confidence_in_unit_interval(cls, v: float | None) -> float | None:
        """A present confidence is a probability in [0, 1]; absence stays ``None`` (honest)."""
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError("confidence must be within [0, 1] or None (never fabricated)")
        return v

    @field_validator("source_facts")
    @classmethod
    def _source_facts_are_non_empty_ids(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        """Each cited fact is a non-empty content_id — never a blank placeholder."""
        if any(not fact for fact in v):
            raise ValueError("source_facts entries must be non-empty content_ids")
        return v
