"""The GENERIC AI-at-rule-time JUDGMENT evaluator (LP-324, generalizing LP-319's OC-2).

Runs ANY judgment rule from its spec, with ZERO per-rule Python. The procedural armor (§3D) is here,
not in a prompt, applied PER SUBJECT:

    gate the load-bearing structural tags (fail-closed, before any AI call) → reason over the
    declared TAGS (never raw docs) → produce the rule_judgment tag KEYED TO THAT SUBJECT → MANDATORY
    human ratification (every verdict ratification-pending — never auto-ships) → confidence-gated →
    provenance inline.

MULTI-SUBJECT (LP-327): the rule declares its subjects via the executable ``subject_enumeration`` key
(``loan`` | ``per_document`` | …), resolved by the enumerators registry — exactly as
``deterministic.py`` / ``consistency.py`` do. One AI call per subject (a reasoned verdict is
per-subject; batching risks the position-degradation LP-313 guards against — so N subjects = N calls).
PER-SUBJECT FAIL-CLOSED: one subject's gate/AI failure/truncation/malformed degrades ONLY that subject
(couldnt_check / unknown-with-reason); the others still evaluate (LP-321's partial-snapshot discipline,
at the rule level). OC-2 declares ``subject_enumeration: loan`` → exactly one subject → identical
results (the LP-324 equivalence property preserved).

Reuses ``evaluate_gate`` + the LP-313/314 AI clone as-is.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass

from app.ai.client import AIClientError
from app.ai.rule_judgment import Reasoner, RuleJudgmentResult, reason_rule_judgment
from app.core.logging import get_logger
from app.verification.rule_engine.applicability import (
    absent_document_couldnt_check,
    missing_document_subject_id,
    resolve_applicabilities,
)
from app.verification.rule_engine.deterministic import _loan_tags
from app.verification.rule_engine.enumerators import enumerate_subjects
from app.verification.rule_engine.gate import GateStatus, evaluate_gate
from app.verification.rule_engine.result import LoadBearingTag, RuleEvaluation, Verdict
from app.verification.rules.specs import JudgmentEval, RuleSpec, _as_conditions
from app.verification.snapshot.model import Snapshot
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

logger = get_logger(__name__)

_UNKNOWN = "unknown"

# Bound the parallel per-subject AI calls: subjects are independent, so a multi-subject rule runs them
# concurrently (cutting wall-clock from N x latency), capped so a large per-document rule cannot fan
# out into a burst of simultaneous model calls (rate limits). One subject (OC-2) → one call, as before.
_MAX_CONCURRENT_SUBJECTS = 8

# The injected reasoner seam is the shared ``Reasoner`` alias (re-exported for existing importers such
# as oc2.py); keyless tests supply a stub, None → the real model with the spec prompt.


@dataclass(frozen=True)
class JudgmentEvaluation:
    """A judgment rule's output: the rule_judgment tag (None when the AI could not be consulted) + the
    evaluation result.

    Ratification-pending in every case EXCEPT a declared guideline exemption (LP-516 `exempt_when`),
    where a deterministic predicate — not the model's answer — clears the finding."""

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
    extra_load_bearing: tuple[LoadBearingTag, ...] = (),
    ratification_pending: bool = True,
) -> RuleEvaluation:
    """A ratification-pending RuleEvaluation carrying the structural tags inline (provenance).

    ``extra_load_bearing`` (LP-376-B) appends the AI VERDICT itself (value + the model's reasoning) to the
    provenance, so the ratifier reads WHY in the provenance card — while the ``reasoning`` (the finding's
    message) states the verdict, not the raw reasoning paragraph."""
    return RuleEvaluation(
        rule_id=spec.rule_id,
        subject_id=subject_id,
        verdict=verdict,
        verdict_confidence=verdict_confidence,
        load_bearing_tags=_load_bearing(reasoned_over, subject_tags) + extra_load_bearing,
        threshold_used=None,  # a judgment rule has no numeric threshold
        priya_validated=spec.reference_values.priya_validated,
        gated_pending_signoff=True,
        reasoning=reasoning,
        how_to_fix=None,
        # A judgment rule NEVER auto-ships on the model's say-so. The ONE exception is a GUIDELINE
        # exemption (LP-516 `exempt_when`), where the clearing is done by a deterministic predicate and
        # the model can only ever ADD a review, never remove one.
        ratification_pending=ratification_pending,
    )


def _guideline_exempts(jud: JudgmentEval, subject_tags: Mapping[str, Tag], value: str) -> bool:
    """Does a declared guideline exemption clear this subject? (LP-516)

    True only when the predicate is DEFINITELY satisfied and the model did not object. Three ways to
    return False, all deliberate:

    * no `exempt_when` declared — the rule has no exemption, the default for every judgment rule;
    * the predicate tag is ABSENT or ``"unknown"`` — an undetermined fact must never clear a finding
      (the §8 honesty contract: scope-false and data-missing are different things);
    * the model's answer is in `exempt_unless_judgment_in` — the guide's own escape hatch, where a
      readily-identifiable source still warrants review because the lender has questions anyway.
    """
    if jud.exempt_when is None:
        return False
    tag = subject_tags.get(jud.exempt_when.tag_id)
    if tag is None or str(tag.value) == "unknown":
        return False
    observed = str(tag.value)
    holds = (
        observed == jud.exempt_when.value
        if jud.exempt_when.op == "eq"
        else observed != jud.exempt_when.value
    )
    return holds and value not in jud.exempt_unless_judgment_in


def _exempt_message(jud: JudgmentEval, subject_tags: Mapping[str, Tag]) -> str:
    """The finding text for an exempted subject — it must name WHY, not merely that it passed.

    A processor reading "satisfied" on a borrowed-funds check is entitled to know the guideline did the
    clearing rather than a model. The predicate tag's own reasoning carries the specifics (which
    category, and the guide's clause), so it is quoted rather than restated.
    """
    tag = subject_tags.get(jud.exempt_when.tag_id) if jud.exempt_when else None
    detail = (tag.reasoning or "").strip() if tag is not None else ""
    return (
        f"no further review is required for this deposit — {detail}"
        if detail
        else "no further review is required for this deposit under the applicable guideline"
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


def _verdict_message(value: str, confidence: float | None, floor: float) -> str:
    """The needs_review MESSAGE — states the VERDICT (LP-376-B), never the raw AI reasoning paragraph
    (which now lives in the provenance, as a load-bearing tag). Engine-internal reasoning ("Tag
    id.citizenship confirms…") must not leak to a processor as a finding's identity."""
    if value == _UNKNOWN:
        return "the tags do not support a confident judgment — a human must review"
    if confidence is not None and confidence < floor:
        return f"the AI judged '{value}' at low confidence ({confidence} < {floor}) — a human must ratify"
    return f"the AI judged '{value}' — an AI verdict a human must ratify (it never auto-ships)"


async def evaluate_judgment_rule(
    spec: RuleSpec,
    snapshot: Snapshot,
    *,
    reasoner: Reasoner | None = None,
    confidence_floor: float | None = None,
) -> list[JudgmentEvaluation]:
    """Evaluate a judgment rule over ALL its enumerated subjects, entirely from ``spec.judgment``.

    Returns one :class:`JudgmentEvaluation` per subject (each ratification-pending, each tag keyed to
    its subject). PER-SUBJECT FAIL-CLOSED: one subject's degraded inputs / AI failure degrade ONLY
    that subject; the others still evaluate. OC-2 (``subject_enumeration: loan``) yields exactly one.
    """
    jud = spec.judgment
    assert jud is not None, f"{spec.rule_id} is not a judgment rule"
    floor = confidence_floor if confidence_floor is not None else jud.confidence_floor
    reason_fn = reasoner if reasoner is not None else _bind_prompt(jud.system_prompt)

    subjects = enumerate_subjects(spec.subject_enumeration, snapshot)

    # LP-330: an EXPECTED-but-confidently-absent document is a GAP (couldnt_check, §8 Tab 1), not
    # scope-false. (ID-9's POA leaves applicability_expected False → absent = not_applicable, unchanged.)
    # The missing-document path names ONE document type, and `applicability_expected` validates that a
    # rule using it declares exactly one predicate (LP-517) — so the conjunction collapses safely here.
    doc_applic = next(iter(_as_conditions(jud.applicability)), None)
    absent_reason = absent_document_couldnt_check(
        doc_applic,
        jud.applicability_expected,
        subjects,
        documents_absent=snapshot.documents.absent,
    )
    if absent_reason is not None:
        assert doc_applic is not None  # guaranteed when a reason is returned
        return [
            JudgmentEvaluation(
                None,
                _result(
                    spec,
                    missing_document_subject_id(doc_applic),
                    Verdict.COULDNT_CHECK,
                    absent_reason,
                    jud.reasoned_over,
                    {},
                ),
            )
        ]

    sem = asyncio.Semaphore(_MAX_CONCURRENT_SUBJECTS)

    async def _bounded(subject_id: str, subject_tags: Mapping[str, Tag]) -> JudgmentEvaluation:
        # Each subject is self-contained + internally fail-closed (AI errors → couldnt_check), so
        # bounded-concurrent evaluation preserves per-subject semantics; gather keeps subject order.
        async with sem:
            return await _evaluate_one_subject(
                spec, jud, subject_id, subject_tags, reason_fn, floor, _loan_tags(snapshot)
            )

    return list(await asyncio.gather(*(_bounded(sid, tags) for sid, tags in subjects)))


async def _evaluate_one_subject(
    spec: RuleSpec,
    jud: JudgmentEval,
    subject_id: str,
    subject_tags: Mapping[str, Tag],
    reason_fn: Reasoner,
    floor: float,
    loan_tags: Mapping[str, Tag],
) -> JudgmentEvaluation:
    """The per-subject judgment armor (§3D) — one subject's applicability → gate → AI → tag →
    ratification-pending verdict. Self-contained so one subject's failure never touches another's."""
    # 0. Declared applicability (LP-329, GAP-C) — BEFORE the gate, so an out-of-scope subject costs
    #    nothing (no gate, no AI, no tag). §8: out-of-scope → not_applicable; an absent/"unknown"
    #    predicate → couldnt_check — the two must never collapse.
    if jud.applicability is not None:
        terminal = resolve_applicabilities(
            _as_conditions(jud.applicability), subject_tags, loan_tags
        )
        if terminal is not None:
            verdict, reason = terminal
            return JudgmentEvaluation(
                None, _result(spec, subject_id, verdict, reason, jud.reasoned_over, subject_tags)
            )

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
        logger.warning("judgment_ai_failed", rule=spec.rule_id, subject=subject_id)
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
    # LP-376-B: the AI's own verdict + reasoning goes into the PROVENANCE (a load-bearing tag the ratifier
    # reads in the card), NOT the message. The message states the verdict; the reasoning explains it.
    # Skip it when the output tag is already among the reasoned-over provenance (a rule reasoning over its
    # own output) so it never renders twice.
    verdict_provenance = LoadBearingTag(jud.output_tag, value, confidence, reasoning, (subject_id,))
    extra_load_bearing = () if jud.output_tag in jud.reasoned_over else (verdict_provenance,)
    # LP-516 — THE GUIDELINE EXEMPTION (ask-then-suppress). The model has been asked and answered; if
    # the guideline says this deposit needs no further review AND the model did not object, the finding
    # is satisfied rather than sent to a human. The predicate does the clearing, not the model's
    # confidence — and `exempt_unless_judgment_in` preserves the guide's own escape hatch ("if the
    # lender still has questions as to whether the funds may have been borrowed ...").
    #
    # FAIL-CLOSED: only a DEFINITELY-TRUE predicate exempts. An absent or "unknown" predicate tag leaves
    # the verdict exactly where it was — needs_review — so an undetermined category can never clear.
    if _guideline_exempts(jud, subject_tags, value):
        return JudgmentEvaluation(
            judgment_tag=tag,
            evaluation=_result(
                spec,
                subject_id,
                Verdict.SATISFIED,
                _exempt_message(jud, subject_tags),
                jud.reasoned_over,
                subject_tags,
                verdict_confidence=confidence
                if confidence is not None
                else gate.verdict_confidence,
                extra_load_bearing=extra_load_bearing,
                ratification_pending=False,
            ),
        )

    evaluation = _result(
        spec,
        subject_id,
        Verdict.NEEDS_REVIEW,
        _verdict_message(value, confidence, floor),
        jud.reasoned_over,
        subject_tags,
        verdict_confidence=confidence if confidence is not None else gate.verdict_confidence,
        extra_load_bearing=extra_load_bearing,
    )
    return JudgmentEvaluation(tag, evaluation)


def _bind_prompt(system_prompt: str) -> Reasoner:
    """The default reasoner — the real model with the spec's prompt bound."""

    async def _call(context_json: str) -> RuleJudgmentResult:
        return await reason_rule_judgment(system_prompt, context_json)

    return _call


__all__ = ["JudgmentEvaluation", "Reasoner", "evaluate_judgment_rule"]
