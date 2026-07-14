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

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

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


def evaluate_gate(
    load_bearing: Mapping[str, Tag | None],
    *,
    confidence_floor: float,
    contradiction: bool = False,
) -> GateResult:
    """Run the fail-closed gate over a subject's load-bearing tags (fixed decision order).

    Order (a degradation short-circuits at the first that applies):

    1. a required tag is ABSENT (not produced) → ``couldnt_check`` (names the tag).
    2. a load-bearing tag value is ``"unknown"`` → ``couldnt_check`` (distinct reason).
    3. a contradiction is flagged for the subject → ``needs_review``.
    4. the minimum load-bearing confidence is below ``confidence_floor`` → ``needs_review``.
    5. else → ``PASS`` (the rule may run and return satisfied/fired).

    ``verdict_confidence`` is the min of the tags' non-None confidences (None when they are all
    parsed passthroughs — no AI-derived uncertainty).
    """
    for tag_id, tag in load_bearing.items():
        if tag is None:
            return GateResult(
                GateStatus.COULDNT_CHECK, f"required tag '{tag_id}' is absent (not produced)", None
            )
    for tag_id, tag in load_bearing.items():
        if tag is not None and tag.value == _UNKNOWN:
            return GateResult(
                GateStatus.COULDNT_CHECK, f"load-bearing tag '{tag_id}' is unknown", None
            )
    if contradiction:
        return GateResult(
            GateStatus.NEEDS_REVIEW, "a contradiction is flagged for this subject", None
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
            f"a load-bearing tag confidence ({verdict_confidence}) is below the floor "
            f"({confidence_floor})",
            verdict_confidence,
        )
    return GateResult(GateStatus.PASS, None, verdict_confidence)
