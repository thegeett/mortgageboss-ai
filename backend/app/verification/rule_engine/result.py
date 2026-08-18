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
    """The verdicts a rule can reach for one subject (§3D fail-closed lifecycle)."""

    FIRED = "fired"  # the rule's condition is met (e.g. an unsourced large deposit)
    SATISFIED = "satisfied"  # earned a pass — present, confident, non-firing
    COULDNT_CHECK = "couldnt_check"  # a required input was absent/unknown — cannot judge
    NEEDS_REVIEW = "needs_review"  # a load-bearing tag is low-confidence / contradictory
    NOT_APPLICABLE = "not_applicable"  # this subject is outside the rule's scope
    # LP-391 — the THIRD rule state (applicable-but-manual): a BLOCKED rule is applicable to a subject and
    # its data is present, but it is not activated (no trusted verdict). Its would-be verdict is DISCARDED
    # and this manual-review flag ships instead — never the untrusted satisfied/fired. Only the pending-check
    # pass produces it; no spec authors it (like NOT_APPLICABLE, it is derived, absent from VERDICT_BY_NAME).
    PENDING_AUTOMATION = "pending_automation"


# The spec-outcome verdict names → Verdict, shared by every generic evaluator that reads a declared
# `verdict:` string from a spec (deterministic, consistency). One mapping so a rename/addition can
# never leave two evaluators disagreeing on which outcome strings are legal. NOT_APPLICABLE is not a
# declarable outcome (it is derived, not authored), so it is intentionally absent.
VERDICT_BY_NAME: dict[str, Verdict] = {
    "fired": Verdict.FIRED,
    "satisfied": Verdict.SATISFIED,
    "needs_review": Verdict.NEEDS_REVIEW,
    "couldnt_check": Verdict.COULDNT_CHECK,
}


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
    # LP-535 — the materiality arithmetic that put this subject in scope ("$2,000.00 is above the
    # $1,316.67 (10% of $13,166.70 monthly qualifying income) materiality floor"), carried STRUCTURALLY
    # rather than only folded into `reasoning`. It is an AUDITABILITY requirement: a processor who can
    # see the threshold's derivation can judge the threshold itself, and a bare floor cannot be argued
    # with. The composer rewrites `reasoning` freely, and on the first composed run it dropped this
    # clause from four of five AS-12 findings — so a field it cannot paraphrase away is the only way
    # the requirement actually holds.
    derivation: str | None = None
    # LP-319/325: True marks a verdict an AI produced that a human must confirm before it ships. A
    # deterministic rule (AS-1) leaves it False. OC-2's judgment PATH forces every verdict to
    # needs_review — so for it, ratification-pending only ever reaches needs_review / couldnt_check.
    # A cross-source CONSISTENCY rule (LP-325) is different: its DETERMINISTIC exact bookend decides
    # the clear-agree case (satisfied, NO AI → NOT pending); only the fuzzy RESIDUE calls the AI, and
    # that AI verdict may land satisfied (benign variance) OR fired (real discrepancy) while still
    # ratification-pending. So the invariant is per-path, not universal: pending ⟹ an AI made the call.
    ratification_pending: bool = False
