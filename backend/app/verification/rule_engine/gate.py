"""The generic fail-closed gate (LP-315) — the safety core every rule runs first.

§3D's armor: a degraded input must NEVER yield a confident "satisfied". Before any rule's
deterministic logic runs, this gate inspects the rule's declared load-bearing tags for a subject
and, in a fixed decision order, routes every degradation to ``couldnt_check`` / ``needs_review``
— never a silent pass. It is generic and reusable: a rule passes its load-bearing tags + a
confidence floor, and gets back a :class:`GateResult`.

The distinctions that matter (§3D):

* **absent ≠ unknown.** A required tag that was never produced (``None``) is ``couldnt_check`` for
  a DIFFERENT reason than a tag whose value is ``"unknown"`` — both block, but the reason differs.
* **verdict_confidence = min** of the load-bearing tags' confidences. Parsed passthroughs carry
  ``confidence=None`` (effectively certain — §3D) and are IGNORED in the min and the floor check;
  only genuinely-judged (AI) confidences gate.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum

from app.verification.rule_engine.reasons import fact_label
from app.verification.rules.distrust import distrusted_tag_ids
from app.verification.snapshot.tag import Tag

_UNKNOWN = "unknown"


class GateStatus(StrEnum):
    """The gate's outcome — PASS lets the rule run; the others are terminal verdicts."""

    PASS = "pass"
    COULDNT_CHECK = "couldnt_check"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class GateResult:
    """The gate's decision + the verdict confidence it computed (min of load-bearing confidences)."""

    status: GateStatus
    reason: str | None
    verdict_confidence: float | None
    # LP-508 / ADR-377 — set when the degradation was a DISTRUSTED field. The caller marks the finding
    # ratification_pending, so a processor confirms it rather than the engine auto-asserting.
    ratification_pending: bool = False


def evaluate_gate(
    load_bearing: Mapping[str, Tag | None],
    *,
    confidence_floor: float,
    contradiction: bool = False,
    distrust_tag_ids: Collection[str] | None = None,
) -> GateResult:
    """Run the fail-closed gate over a subject's load-bearing tags (fixed decision order).

    Order (a degradation short-circuits at the first that applies):

    1. a required tag is ABSENT (not produced) → ``couldnt_check`` (names the tag).
    2. a load-bearing tag value is ``"unknown"`` → ``couldnt_check`` (distinct reason).
    3. a load-bearing tag reads a DISTRUSTED extraction field → ``needs_review`` + ratification
       (LP-508 / ADR-377 — the fifth defence; see below).
    4. a contradiction is flagged for the subject → ``needs_review``.
    5. the minimum load-bearing confidence is below ``confidence_floor`` → ``needs_review``.
    6. else → ``PASS`` (the rule may run and return satisfied/fired).

    ⚠️ WHY CHECK 3 EXISTS. The other four cannot see a confidently-WRONG parsed value: it is present, not
    ``"unknown"``, uncontradicted, and a parsed passthrough carries ``confidence=None`` — which the
    minimum below FILTERS OUT, and skips entirely when every load-bearing tag is parsed. So a rule whose
    inputs are all parsed (IH-1) had NO confidence defence at all. Check 3 is that defence: a field with a
    CONFIRMED wrong value in the corpus degrades the verdict instead of auto-asserting it.

    ⚠️ DISTRUSTED IS A FIFTH STATE, not a fourth. It is not absent (the value is there), not empty, not
    ``"unknown"`` (the extractor was confident), and not low-confidence (there is no confidence to read).
    It must not collapse into any of them — hence its own check and its own reason.

    ``verdict_confidence`` is the min of the tags' non-None confidences (None when they are all
    parsed passthroughs — no AI-derived uncertainty).
    """
    # LP-376-C: name the MISSING FACT in mortgage terms (never the tag id) — the message a processor reads.
    for tag_id, tag in load_bearing.items():
        if tag is None:
            return GateResult(
                GateStatus.COULDNT_CHECK,
                f"the {fact_label(tag_id)} could not be found in the file — this check needs it",
                None,
            )
    for tag_id, tag in load_bearing.items():
        if tag is not None and tag.value == _UNKNOWN:
            return GateResult(
                GateStatus.COULDNT_CHECK,
                f"the {fact_label(tag_id)} could not be read from the documents "
                "(it is present but unclear)",
                None,
            )
    # LP-508 / ADR-377 — the fifth defence. Ordered AFTER absent/"unknown" (a missing value is a more
    # specific and more useful message than a distrusted one) and BEFORE contradiction, so a distrusted
    # field is reported as such rather than as a disagreement.
    # ⚠️ ``distrust_tag_ids`` OVERRIDES the map's keys, and the consistency path REQUIRES it (reported
    # finding). A consistency rule gathers ONE tag across many documents, so it keys the gate map by
    # document ``content_id`` to keep the instances distinct — meaning ``tag_id in distrusted`` compared a
    # document id against tag ids and could never match. ID-3 was on the distrust list and unprotected in
    # practice. The caller passes the tag id(s) it actually gathered.
    distrusted = distrusted_tag_ids()
    checked = distrust_tag_ids if distrust_tag_ids is not None else load_bearing.keys()
    present = any(tag is not None for tag in load_bearing.values())
    for tag_id in checked:
        tag = load_bearing.get(tag_id) if distrust_tag_ids is None else None
        if (tag is not None or (distrust_tag_ids is not None and present)) and tag_id in distrusted:
            return GateResult(
                GateStatus.NEEDS_REVIEW,
                f"the {fact_label(tag_id)} comes from a field the extractor has read wrongly before, so "
                "this check was not decided automatically — a human should confirm the value",
                None,
                ratification_pending=True,
            )
    if contradiction:
        return GateResult(
            GateStatus.NEEDS_REVIEW,
            "the documents contradict each other on this — a human should review",
            None,
        )

    confidences = [
        tag.confidence
        for tag in load_bearing.values()
        if tag is not None and tag.confidence is not None
    ]
    verdict_confidence = min(confidences) if confidences else None
    if verdict_confidence is not None and verdict_confidence < confidence_floor:
        return GateResult(
            GateStatus.NEEDS_REVIEW,
            f"the automated read of this was low-confidence ({verdict_confidence}) — "
            "a human should review it",
            verdict_confidence,
        )
    return GateResult(GateStatus.PASS, None, verdict_confidence)
