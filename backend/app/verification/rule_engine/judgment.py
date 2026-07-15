"""The GENERIC AI-at-rule-time JUDGMENT evaluator (LP-324, generalizing LP-319's OC-2).

Runs ANY judgment rule from its spec, with ZERO per-rule Python. The procedural armor (§3D) is here,
not in a prompt:

    gate the load-bearing structural tags (fail-closed, before any AI call) → reason over the
    declared TAGS (never raw docs) → produce the rule_judgment tag → MANDATORY human ratification
    (every verdict ratification-pending — never auto-ships) → confidence-gated → provenance inline.

OC-2 is re-expressed as data on this evaluator (`OC-2.yaml`'s `judgment` block); its former per-rule
module carries no flow logic. Reuses ``evaluate_gate`` + the LP-313/314 AI clone as-is.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from app.ai.client import AIClientError
from app.ai.rule_judgment import RuleJudgmentResult, reason_rule_judgment
from app.core.logging import get_logger
from app.verification.rule_engine.enumerators import enumerate_subjects
from app.verification.rule_engine.gate import GateStatus, evaluate_gate
from app.verification.rule_engine.result import LoadBearingTag, RuleEvaluation, Verdict
from app.verification.rules.specs import JudgmentEval, RuleSpec
from app.verification.snapshot.model import Snapshot
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

logger = get_logger(__name__)

_UNKNOWN = "unknown"

# The injected reasoner seam (keyless tests supply a stub; None → the real model with the spec prompt).
Reasoner = Callable[[str], Awaitable[RuleJudgmentResult]]


@dataclass(frozen=True)
class JudgmentEvaluation:
    """A judgment rule's output: the rule_judgment tag (None when the AI could not be consulted) +
    the ALWAYS-ratification-pending evaluation result."""

    judgment_tag: Tag | None
    evaluation: RuleEvaluation


def _load_bearing(
    reasoned_over: tuple[str, ...], subject_tags: Mapping[str, Tag]
) -> tuple[LoadBearingTag, ...]:
    """The structural-fact tags the AI reasoned over, inline (provenance for the ratifier)."""
    return tuple(
        LoadBearingTag(tag_id, tag.value, tag.confidence, tag.reasoning, tag.source_facts)
        for tag_id in reasoned_over
        if (tag := subject_tags.get(tag_id)) is not None
    )


def _build_context(
    reasoned_over: tuple[str, ...], subject_tags: Mapping[str, Tag]
) -> dict[str, object]:
    """The judgment context — ONLY the declared structural tags (never raw documents)."""
    return {
        "tags": {
            tag_id: {"value": tag.value, "confidence": tag.confidence, "reasoning": tag.reasoning}
            for tag_id in reasoned_over
            if (tag := subject_tags.get(tag_id)) is not None
        }
    }


def _result(
    spec: RuleSpec,
    subject_id: str,
    verdict: Verdict,
    reasoning: str,
    reasoned_over: tuple[str, ...],
    subject_tags: Mapping[str, Tag],
    *,
    verdict_confidence: float | None = None,
) -> RuleEvaluation:
    """A ratification-pending RuleEvaluation carrying the structural tags inline (provenance)."""
    return RuleEvaluation(
        rule_id=spec.rule_id,
        subject_id=subject_id,
        verdict=verdict,
        verdict_confidence=verdict_confidence,
        load_bearing_tags=_load_bearing(reasoned_over, subject_tags),
        threshold_used=None,  # a judgment rule has no numeric threshold
        priya_validated=spec.reference_values.priya_validated,
        gated_pending_signoff=True,
        reasoning=reasoning,
        how_to_fix=None,
        ratification_pending=True,  # a judgment rule NEVER auto-ships
    )


def _judgment_tag(
    jud: JudgmentEval, subject_id: str, value: str, confidence: float | None, reasoning: str | None
) -> Tag:
    """The rule_judgment tag — the rule's verdict in tag shape (§3D)."""
    return Tag(
        value=value,
        confidence=confidence,
        reasoning=reasoning,
        source_facts=(subject_id,),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.RULE_JUDGMENT,  # a per-rule verdict, NOT a shared structural fact
        stage=TagStage.B,  # produced at rule-time, correlating structural facts (cross-entity)
    )


def _resolve(
    result: RuleJudgmentResult, domain: tuple[str, ...]
) -> tuple[str, float | None, str | None]:
    """The judgment value/confidence/reasoning, honestly — a malformed/off-domain answer → unknown."""
    judgment = result.judgment
    if judgment is None:
        return _UNKNOWN, None, "the judgment response was malformed — treated as unknown"
    if judgment.value not in domain:
        # The model's confidence was in its INVALID answer, not "unknown" — drop it.
        return (
            _UNKNOWN,
            None,
            judgment.reasoning or "the model returned an out-of-domain value — treated as unknown",
        )
    return judgment.value, judgment.confidence, judgment.reasoning


def _verdict_reasoning(
    value: str, reasoning: str | None, confidence: float | None, floor: float
) -> str:
    """The needs_review reasoning — the AI's judgment + why it awaits ratification."""
    base = reasoning or f"the judgment is '{value}'"
    if value == _UNKNOWN:
        return f"{base} — the tags do not support a confident judgment; a human must review"
    if confidence is not None and confidence < floor:
        return f"{base} — the judgment '{value}' is low-confidence ({confidence} < {floor}); a human must ratify"
    return f"{base} — '{value}' is an AI judgment and must be ratified by a human"


async def evaluate_judgment_rule(
    spec: RuleSpec,
    snapshot: Snapshot,
    *,
    reasoner: Reasoner | None = None,
    confidence_floor: float | None = None,
) -> JudgmentEvaluation:
    """Evaluate a judgment rule over its (single) subject, entirely from ``spec.judgment``."""
    jud = spec.judgment
    assert jud is not None, f"{spec.rule_id} is not a judgment rule"
    floor = confidence_floor if confidence_floor is not None else jud.confidence_floor
    # A judgment rule is single-subject (loan-level); this evaluator produces ONE verdict + ONE tag.
    # Fail loud on a misconfigured enumeration rather than silently judging only the first subject
    # (or IndexError-ing on an empty one).
    subjects = enumerate_subjects(spec.subject_enumeration, snapshot)
    if len(subjects) != 1:
        raise ValueError(
            f"judgment rule {spec.rule_id} must enumerate exactly one subject, got {len(subjects)} "
            f"(subject_enumeration={spec.subject_enumeration!r} is not single-subject)"
        )
    subject_id, subject_tags = subjects[0]

    reason_fn = reasoner if reasoner is not None else _bind_prompt(jud.system_prompt)

    # 1. Fail-closed gate over the load-bearing structural facts — before any AI call.
    gate = evaluate_gate(
        {tag_id: subject_tags.get(tag_id) for tag_id in jud.load_bearing_tags},
        confidence_floor=floor,
    )
    if gate.status is GateStatus.COULDNT_CHECK:
        return JudgmentEvaluation(
            None,
            _result(
                spec,
                subject_id,
                Verdict.COULDNT_CHECK,
                gate.reason or "",
                jud.reasoned_over,
                subject_tags,
            ),
        )
    if gate.status is GateStatus.NEEDS_REVIEW:
        # A shaky input can't produce a trustworthy judgment — needs_review with NO AI call, NO tag.
        return JudgmentEvaluation(
            None,
            _result(
                spec,
                subject_id,
                Verdict.NEEDS_REVIEW,
                gate.reason or "",
                jud.reasoned_over,
                subject_tags,
                verdict_confidence=gate.verdict_confidence,
            ),
        )

    # 2. Reason over the TAGS (never raw docs). Honest/fail-closed on transport + truncation.
    context = _build_context(jud.reasoned_over, subject_tags)
    try:
        result = await reason_fn(json.dumps(context))
    except AIClientError:
        logger.warning("judgment_ai_failed", rule=spec.rule_id)
        return JudgmentEvaluation(
            None,
            _result(
                spec,
                subject_id,
                Verdict.COULDNT_CHECK,
                "the judgment could not be produced (AI call failed) — cannot judge",
                jud.reasoned_over,
                subject_tags,
                verdict_confidence=gate.verdict_confidence,
            ),
        )
    if result.truncated:
        return JudgmentEvaluation(
            None,
            _result(
                spec,
                subject_id,
                Verdict.COULDNT_CHECK,
                "the judgment response was truncated — cannot trust a partial judgment",
                jud.reasoned_over,
                subject_tags,
                verdict_confidence=gate.verdict_confidence,
            ),
        )

    # 3. Ratification-pending verdict + the rule_judgment tag (a malformed/off-domain answer →
    #    honest unknown, never a defaulted verdict). MANDATORY: always needs_review.
    value, confidence, reasoning = _resolve(result, jud.value_domain)
    tag = _judgment_tag(jud, subject_id, value, confidence, reasoning)
    evaluation = _result(
        spec,
        subject_id,
        Verdict.NEEDS_REVIEW,
        _verdict_reasoning(value, reasoning, confidence, floor),
        jud.reasoned_over,
        subject_tags,
        verdict_confidence=confidence if confidence is not None else gate.verdict_confidence,
    )
    return JudgmentEvaluation(tag, evaluation)


def _bind_prompt(system_prompt: str) -> Reasoner:
    """The default reasoner — the real model with the spec's prompt bound."""

    async def _call(context_json: str) -> RuleJudgmentResult:
        return await reason_rule_judgment(system_prompt, context_json)

    return _call


__all__ = ["JudgmentEvaluation", "Reasoner", "evaluate_judgment_rule"]
