"""The evaluation-result shapes for the thin rule engine (LP-315).

A rule produces an in-memory :class:`RuleEvaluation` per subject — a VERDICT plus everything a
human (or LP-316's finding persistence) needs to trust it: the load-bearing tags it rested on
(inline, with their value/confidence/reasoning — the provenance move), the threshold used and
whether that threshold is Priya-validated, the verdict confidence, and the fix. Nothing is
persisted here (LP-316) and no AI runs (LP-313/314 produced the tags).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Verdict(StrEnum):
    """The five verdicts a rule can reach for one subject (§3D fail-closed lifecycle)."""

    FIRED = "fired"  # the rule's condition is met (e.g. an unsourced large deposit)
    SATISFIED = "satisfied"  # earned a pass — present, confident, non-firing
    COULDNT_CHECK = "couldnt_check"  # a required input was absent/unknown — cannot judge
    NEEDS_REVIEW = "needs_review"  # a load-bearing tag is low-confidence / contradictory
    NOT_APPLICABLE = "not_applicable"  # this subject is outside the rule's scope


@dataclass(frozen=True)
class LoadBearingTag:
    """One tag a verdict relied on, carried inline so the verdict never cites a bare number."""

    tag_id: str
    value: object
    confidence: float | None
    reasoning: str | None
    # The raw facts the tag cited (LP-312 content_ids) — the provenance trail LP-316 persists.
    source_facts: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleEvaluation:
    """One rule's verdict for one subject — the in-memory result (LP-316 persists it later)."""

    rule_id: str
    subject_id: str  # the deposit's stable content_id (LP-312) — never a position
    verdict: Verdict
    verdict_confidence: float | None  # min of the load-bearing tags' confidences
    load_bearing_tags: tuple[LoadBearingTag, ...]
    threshold_used: Decimal | None  # the threshold this verdict compared against (from the spec)
    priya_validated: bool  # whether that threshold is Priya-confirmed
    gated_pending_signoff: (
        bool  # True when the threshold is NOT validated — withhold from "shipped"
    )
    reasoning: str
    how_to_fix: str | None
    # LP-319: an AI-at-rule-time JUDGMENT rule (e.g. OC-2) NEVER auto-ships — its verdict is always
    # ratification-pending until a human confirms. True marks that mandatory-ratification armor; a
    # deterministic rule (AS-1) leaves it False. A ratification-pending rule only ever reaches
    # needs_review / couldnt_check — never a confident satisfied/fired.
    ratification_pending: bool = False
