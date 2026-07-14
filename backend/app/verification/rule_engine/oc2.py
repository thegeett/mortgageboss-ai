"""OC-2 — occupancy reasonableness, the AI-at-rule-time JUDGMENT-rule pattern (LP-319).

The proof of the judgment slice (§3D): a rule whose verdict CANNOT reduce to a deterministic tag
query — the AI IS the evaluator. Because these are the highest-stakes, least-structurally-armored
rules, they get PROCEDURAL armor, all enforced here (not in the prompt):

* **Reason over TAGS, not raw docs.** The judgment context is assembled ONLY from the loan's
  structural-fact tags (occupancy.stated, consistency + address signals). No document is read.
* **Fail-closed gate on the inputs (LP-315).** A load-bearing structural tag that is absent or
  ``unknown`` → ``couldnt_check`` (we don't ask the AI to judge over a hole); a shaky one →
  needs_review — before the AI is ever called.
* **MANDATORY human ratification.** The verdict is ALWAYS ratification-pending — a judgment rule
  NEVER auto-ships a confident ``satisfied``/``fired``. Its only terminal verdicts are
  ``needs_review`` (a judgment was reached, a human must confirm) and ``couldnt_check`` (couldn't
  judge). Represented as LP-316's ``needs_review`` + ``RuleEvaluation.ratification_pending``.
* **Honest / fail-closed AI.** AIClientError or truncation → the judgment tag is absent-with-reason
  and the verdict is ``couldnt_check``; a malformed / off-vocabulary response → ``unknown`` →
  needs_review — NEVER a defaulted verdict.
* **Provenance for the ratifier.** The result carries the structural-fact tags it reasoned over
  inline, so the human sees WHY the AI judged as it did; the ``occupancy.reasonable`` rule_judgment
  tag cites those same structural subjects.

This is the PATTERN the other judgment rules follow: assemble tag context → gate → AI judge →
ratification-pending verdict + a ``rule_judgment`` tag. Only the prompt + the tag set change.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from app.ai.client import AIClientError
from app.ai.occupancy_judgment import (
    OCCUPANCY_REASONABLE_VALUES,
    OccupancyJudgmentResult,
    reason_oc2_occupancy,
)
from app.core.logging import get_logger
from app.verification.rule_engine.gate import GateStatus, evaluate_gate
from app.verification.rule_engine.result import LoadBearingTag, RuleEvaluation, Verdict
from app.verification.snapshot.model import Snapshot
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

logger = get_logger(__name__)

RULE_ID = "OC-2"

# The rule_judgment tag OC-2 produces — its verdict, in tag shape (§3D rule_judgment role).
JUDGMENT_TAG = "occupancy.reasonable"

# The loan-level subject under which loan-level structural-fact tags live in the tags layer. The
# snapshot is per-loan-file, so the loan is a single implicit subject; loan-level tags (occupancy.*,
# id.*, property.*) key here — distinct from the per-transaction content_id subjects Stage A/B use.
# A documented convention (LP-319): the occupancy structural tags are produced by OC-1/ID-4 (not
# this ticket) and land here; this evaluator reads them.
LOAN_SUBJECT = "loan"

# The structural-fact tags OC-2 REASONS OVER (never raw docs). A subset is load-bearing: without a
# stated occupancy and a consistency signal there is nothing to judge, so their absence/unknown
# fails closed to couldnt_check (the rest refine the judgment but do not gate).
TAG_OCCUPANCY_STATED = "occupancy.stated"
TAG_CONSISTENT_WITH_SIGNALS = "occupancy.consistent_with_signals"
TAG_CURRENT_ADDRESS_TYPE = "id.current_address_type"
TAG_ADDRESS_MATCH = "property.address_normalized_match"

REASONED_OVER = (
    TAG_OCCUPANCY_STATED,
    TAG_CONSISTENT_WITH_SIGNALS,
    TAG_CURRENT_ADDRESS_TYPE,
    TAG_ADDRESS_MATCH,
)
_LOAD_BEARING = (TAG_OCCUPANCY_STATED, TAG_CONSISTENT_WITH_SIGNALS)

# The confidence floor below which a judgment routes to needs_review (mirrors the LP-315 engine
# default; PRIYA-CONFIRMABLE later).
DEFAULT_CONFIDENCE_FLOOR = 0.5

_UNKNOWN = "unknown"

# Injected so a keyless test supplies a deterministic stub (the same seam as Stage A/B).
Reasoner = Callable[[str], Awaitable[OccupancyJudgmentResult]]


@dataclass(frozen=True)
class Oc2Evaluation:
    """OC-2's output: the ``occupancy.reasonable`` rule_judgment tag + the evaluation result.

    ``judgment_tag`` is ``None`` when the AI could not be consulted (gated inputs, or an
    AIClientError/truncation) — an absent tag, never a fabricated verdict. The ``evaluation`` is
    ALWAYS ratification-pending for a reached judgment (never satisfied/fired).
    """

    judgment_tag: Tag | None
    evaluation: RuleEvaluation


def _structural_load_bearing(subject_tags: Mapping[str, Tag]) -> tuple[LoadBearingTag, ...]:
    """The structural-fact tags OC-2 reasoned over, inline (provenance for the ratifying human)."""
    return tuple(
        LoadBearingTag(tag_id, tag.value, tag.confidence, tag.reasoning, tag.source_facts)
        for tag_id in REASONED_OVER
        if (tag := subject_tags.get(tag_id)) is not None
    )


def _build_context(subject_tags: Mapping[str, Tag]) -> dict[str, object]:
    """The judgment context — ONLY the structural-fact tags (never raw documents).

    Each tag is surfaced as its value + confidence + reasoning, addressed by its tag id, so the AI
    reasons over the same clean facts everything else uses and its judgment is reviewable.
    """
    return {
        "occupancy_tags": {
            tag_id: {
                "value": tag.value,
                "confidence": tag.confidence,
                "reasoning": tag.reasoning,
            }
            for tag_id in REASONED_OVER
            if (tag := subject_tags.get(tag_id)) is not None
        }
    }


def _result(
    verdict: Verdict,
    reasoning: str,
    subject_tags: Mapping[str, Tag],
    *,
    verdict_confidence: float | None = None,
) -> RuleEvaluation:
    """A ratification-pending RuleEvaluation carrying the structural tags inline (provenance)."""
    return RuleEvaluation(
        rule_id=RULE_ID,
        subject_id=LOAN_SUBJECT,
        verdict=verdict,
        verdict_confidence=verdict_confidence,
        load_bearing_tags=_structural_load_bearing(subject_tags),
        threshold_used=None,  # a judgment rule has no numeric threshold
        priya_validated=False,
        gated_pending_signoff=True,
        reasoning=reasoning,
        how_to_fix=None,
        ratification_pending=True,  # a judgment rule NEVER auto-ships
    )


def _judgment_tag(value: str, confidence: float | None, reasoning: str | None) -> Tag:
    """The occupancy.reasonable rule_judgment tag — OC-2's verdict in tag shape (§3D)."""
    return Tag(
        value=value,
        confidence=confidence,
        reasoning=reasoning,
        source_facts=(LOAN_SUBJECT,),  # the structural subject it reasoned over
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.RULE_JUDGMENT,  # a per-rule verdict, NOT a shared structural fact
        stage=TagStage.B,  # produced at rule-time, correlating structural facts (cross-entity)
    )


async def evaluate_oc2(
    snapshot: Snapshot,
    *,
    reasoner: Reasoner | None = None,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> Oc2Evaluation:
    """Evaluate OC-2 (occupancy reasonableness) as an AI-at-rule-time judgment rule.

    Assembles the loan's structural-fact tags → the fail-closed gate → the AI judge (over tags, not
    docs) → a ratification-pending verdict + the ``occupancy.reasonable`` rule_judgment tag. Pure of
    raw-document reading. The ``reasoner`` seam lets a keyless test inject a deterministic judgment.
    """
    reason_fn = reasoner if reasoner is not None else reason_oc2_occupancy
    subject_tags = {} if snapshot.tags.absent else snapshot.tags.by_subject.get(LOAN_SUBJECT, {})

    # 1. Fail-closed gate over the load-bearing structural facts (LP-315) — before any AI call.
    gate = evaluate_gate(
        {tag_id: subject_tags.get(tag_id) for tag_id in _LOAD_BEARING},
        confidence_floor=confidence_floor,
    )
    if gate.status is GateStatus.COULDNT_CHECK:
        # A required structural input is absent/unknown → we do not ask the AI to judge over a hole.
        return Oc2Evaluation(None, _result(Verdict.COULDNT_CHECK, gate.reason or "", subject_tags))

    # 2. Reason over the TAGS (never raw docs). Honest/fail-closed on transport + truncation.
    context = _build_context(subject_tags)
    try:
        result = await reason_fn(json.dumps(context))
    except AIClientError:
        logger.warning("oc2_judge_failed")
        return Oc2Evaluation(
            None,
            _result(
                Verdict.COULDNT_CHECK,
                "the occupancy judgment could not be produced (AI call failed) — cannot judge",
                subject_tags,
                verdict_confidence=gate.verdict_confidence,
            ),
        )
    if result.truncated:
        return Oc2Evaluation(
            None,
            _result(
                Verdict.COULDNT_CHECK,
                "the occupancy judgment response was truncated — cannot trust a partial judgment",
                subject_tags,
                verdict_confidence=gate.verdict_confidence,
            ),
        )

    # 3. Turn the judgment into a ratification-pending verdict + the rule_judgment tag. A malformed
    #    / off-vocabulary response is an honest "unknown", never a defaulted verdict.
    value, confidence, reasoning = _resolve(result)
    tag = _judgment_tag(value, confidence, reasoning)

    # MANDATORY ratification: whatever the AI concluded (yes/no/unknown), the verdict is
    # needs_review — a judgment rule never auto-ships satisfied/fired. Confidence is folded in for
    # the ratifier but does not let the verdict escape ratification.
    verdict_reasoning = _verdict_reasoning(value, reasoning, confidence, confidence_floor)
    evaluation = _result(
        Verdict.NEEDS_REVIEW,
        verdict_reasoning,
        subject_tags,
        verdict_confidence=confidence if confidence is not None else gate.verdict_confidence,
    )
    return Oc2Evaluation(tag, evaluation)


def _resolve(result: OccupancyJudgmentResult) -> tuple[str, float | None, str | None]:
    """The judgment value/confidence/reasoning, honestly — a malformed/off-vocab answer → unknown."""
    judgment = result.judgment
    if judgment is None:
        return _UNKNOWN, None, "the occupancy judgment response was malformed — treated as unknown"
    if judgment.value not in OCCUPANCY_REASONABLE_VALUES:
        return (
            _UNKNOWN,
            judgment.confidence,
            judgment.reasoning
            or "the model returned an out-of-vocabulary value — treated as unknown",
        )
    return judgment.value, judgment.confidence, judgment.reasoning


def _verdict_reasoning(
    value: str, reasoning: str | None, confidence: float | None, floor: float
) -> str:
    """The needs_review reasoning — the AI's judgment + why it awaits ratification."""
    base = reasoning or f"the occupancy judgment is '{value}'"
    if value == _UNKNOWN:
        return f"{base} — the tags do not support a confident judgment; a human must review"
    if confidence is not None and confidence < floor:
        return (
            f"{base} — the judgment '{value}' is low-confidence ({confidence} < {floor}); "
            f"a human must ratify"
        )
    return f"{base} — occupancy '{value}' is an AI judgment and must be ratified by a human"


__all__ = [
    "DEFAULT_CONFIDENCE_FLOOR",
    "JUDGMENT_TAG",
    "LOAN_SUBJECT",
    "REASONED_OVER",
    "RULE_ID",
    "Oc2Evaluation",
    "evaluate_oc2",
]
