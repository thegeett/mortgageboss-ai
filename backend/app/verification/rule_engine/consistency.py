"""The GENERIC cross-source CONSISTENCY evaluator (LP-325) — the third rule shape.

AS-1 is per-transaction; OC-2 is loan-level. A large family of rules is instead "gather fact T for
subject S across ALL sources, compare, judge agreement" (ID-1/2/3/4/7; later IN-1/IN-3, CR-1,
PC-3/PR-7). This runs ANY such rule from its ``consistency`` spec block, with ZERO per-rule Python.

The EXACT BOOKEND → AI-FUZZY RESIDUE design (mirrors LP-314 candidate-then-judge — deterministic does
the mechanical part; AI judges only the small ambiguous set):

    enumerate subjects → GATHER tag T across the declared source scope (applying the declared filter)
    → absent≠empty / <2-instances → couldnt_check → the fail-closed gate (LP-315, over the gathered
    instances) → EXACT compare after declared normalization (all equal → AGREE, NO AI) → if they
    DIFFER: ``exact`` mode → a discrepancy (NO AI); ``fuzzy`` mode → the AI judges the SMALL differing
    set ONLY (never the file) benign-variance vs real-discrepancy → the declared outcome.

The absent≠disagreeing rules (§3D, critical): a source that simply LACKS the fact is EXCLUDED (not a
mismatch) — the tag is absent OR an AI perceiver returned ``"unknown"`` (it states no value), which is
absent-for-comparison, NOT a value that agrees/disagrees; fewer than two STATED instances after
filtering → couldnt_check (a single source is not "agreement").

Reuses ``evaluate_gate`` + ``reason_rule_judgment`` (LP-313/314) + the LP-319 armor as-is; a fuzzy
verdict is ratification-pending (the AI made the call) — the exact bookend never is.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from app.ai.client import AIClientError
from app.ai.rule_judgment import Reasoner, RuleJudgmentResult, reason_rule_judgment
from app.core.logging import get_logger
from app.verification.rule_engine.enumerators import enumerate_subjects
from app.verification.rule_engine.gate import GateStatus, evaluate_gate
from app.verification.rule_engine.result import (
    VERDICT_BY_NAME,
    LoadBearingTag,
    RuleEvaluation,
    Verdict,
)
from app.verification.rules.specs import ConsistencyEval, ConsistencyOutcome, RuleSpec, TagCondition
from app.verification.snapshot.model import DocumentEntry, Snapshot
from app.verification.snapshot.tag import Tag

logger = get_logger(__name__)

_UNKNOWN = "unknown"

# The AI seam is the shared ``Reasoner`` alias (keyless tests supply a stub; None → the real model
# with the spec prompt). The AI is called ONLY on the differing residue of a fuzzy rule.


# --------------------------------------------------------------------------- #
# Declared normalization — DATA, not code-per-rule (applied before the exact compare)
# --------------------------------------------------------------------------- #
_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")

_NORMALIZERS: dict[str, Callable[[str], str]] = {
    "strip": str.strip,
    "casefold": str.casefold,
    "collapse_ws": lambda s: _WS.sub(" ", s),
    "drop_punct": lambda s: _PUNCT.sub("", s),
}


def _normalize(value: object, keys: tuple[str, ...]) -> str:
    """Apply the declared normalizer chain (raises KeyError on an unknown normalizer key)."""
    text = value if isinstance(value, str) else str(value)
    for key in keys:
        normalizer = _NORMALIZERS.get(key)
        if normalizer is None:
            raise KeyError(f"unknown normalization key {key!r} (known: {sorted(_NORMALIZERS)})")
        text = normalizer(text)
    return text


# --------------------------------------------------------------------------- #
# Declared source scopes — where a subject's instances of the fact are gathered from
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Gathered:
    """One gathered instance of the fact: its value-tag + the SOURCE it came from (a content_id)."""

    source_id: str
    tag: Tag


@dataclass(frozen=True)
class _GatherResult:
    """A gather over one subject: the INCLUDED instances (to compare) + the classification tags that
    DECIDED inclusion (gated for confidence, so a shaky residence/mailing label cannot silently
    include or exclude a source) + the count of value-bearing candidates (matched or not)."""

    included: list[_Gathered]
    filter_tags: dict[str, Tag]
    candidate_count: int


# A borrower_id -> its documents index, built ONCE per run (not re-scanned per subject — that was
# O(borrowers x documents)).
_DocIndex = dict[str, list[DocumentEntry]]


def _index_borrower_documents(snapshot: Snapshot) -> _DocIndex:
    """Group every document under each borrower it belongs to — a single O(documents) pass so the
    per-subject gather is O(that borrower's docs), not a full rescan."""
    index: _DocIndex = {}
    if snapshot.documents.absent:
        return index
    for entry in snapshot.documents.entries:
        if entry.belongs_to is None:
            continue
        for ref in entry.belongs_to:
            index.setdefault(str(ref.borrower_id), []).append(entry)
    return index


def _tag_holds(cond: TagCondition, tags: dict[str, Tag]) -> bool:
    """Whether a source's tags satisfy a gather filter — an ABSENT filter tag is a non-match (the
    source is not of the required type, so it is excluded, not counted as disagreeing)."""
    tag = tags.get(cond.tag)
    if tag is None:
        return False
    observed = str(tag.value)
    return (observed == cond.value) if cond.op == "eq" else (observed != cond.value)


def _borrower_documents(
    snapshot: Snapshot,
    subject_id: str,
    gather_tag: str,
    gather_filter: TagCondition | None,
    index: _DocIndex,
) -> _GatherResult:
    """Gather ``gather_tag`` from every document belonging to the borrower (filtered).

    A document that lacks the fact is ABSENT → not a candidate (absent≠empty). A value-bearing
    document that fails the filter is excluded (a mailing/prior address is not a residence), but its
    PRESENT filter tag is still returned so the evaluator can gate the confidence of that
    inclusion/exclusion decision — a shaky classification must not silently drive the compare set."""
    if snapshot.tags.absent:
        return _GatherResult([], {}, 0)
    included: list[_Gathered] = []
    filter_tags: dict[str, Tag] = {}
    candidate_count = 0
    for entry in index.get(subject_id, []):
        source_tags = snapshot.tags.by_subject.get(entry.content_id, {})
        tag = source_tags.get(gather_tag)
        # absent≠unknown≠empty: a source that does not STATE the fact is EXCLUDED — the tag was never
        # produced (None), OR an AI perceiver returned "unknown" (it looked and found no value: a bank
        # statement has no address). Neither is a value to compare; counting it would inflate the
        # candidate count and poison the filter gate with a non-stated source's classification.
        if tag is None or str(tag.value) == _UNKNOWN:
            continue
        candidate_count += 1
        if gather_filter is not None:
            filter_tag = source_tags.get(gather_filter.tag)
            if filter_tag is not None:  # gate its confidence/known-ness (absent → excluded below)
                filter_tags[entry.content_id] = filter_tag
            if not _tag_holds(gather_filter, source_tags):
                continue
        included.append(_Gathered(entry.content_id, tag))
    return _GatherResult(included, filter_tags, candidate_count)


_Scope = Callable[[Snapshot, str, str, "TagCondition | None", "_DocIndex"], _GatherResult]
_SOURCE_SCOPES: dict[str, _Scope] = {
    "borrower_documents": _borrower_documents,
}


# --------------------------------------------------------------------------- #
# The evaluator
# --------------------------------------------------------------------------- #
def _load_bearing(gathered: list[_Gathered], gather_tag: str) -> tuple[LoadBearingTag, ...]:
    """Each gathered value WITH ITS SOURCE, inline — so a human sees WHAT disagreed and WHERE."""
    return tuple(
        LoadBearingTag(
            gather_tag,
            inst.tag.value,
            inst.tag.confidence,
            inst.tag.reasoning,
            (inst.source_id, *inst.tag.source_facts),
        )
        for inst in gathered
    )


def _result(
    spec: RuleSpec,
    subject_id: str,
    verdict: Verdict,
    reasoning: str,
    gathered: list[_Gathered],
    *,
    verdict_confidence: float | None = None,
    how_to_fix: str | None = None,
    ratification_pending: bool = False,
) -> RuleEvaluation:
    assert spec.consistency is not None
    return RuleEvaluation(
        rule_id=spec.rule_id,
        subject_id=subject_id,
        verdict=verdict,
        verdict_confidence=verdict_confidence,
        load_bearing_tags=_load_bearing(gathered, spec.consistency.gather_tag),
        threshold_used=None,  # a consistency rule has no numeric threshold
        priya_validated=spec.reference_values.priya_validated,
        gated_pending_signoff=not spec.reference_values.priya_validated,
        reasoning=reasoning,
        how_to_fix=how_to_fix,
        ratification_pending=ratification_pending,
    )


def _outcome_result(
    spec: RuleSpec,
    subject_id: str,
    outcome: ConsistencyOutcome,
    gathered: list[_Gathered],
    *,
    verdict_confidence: float | None,
    ratification_pending: bool,
) -> RuleEvaluation:
    """Build the RuleEvaluation for a declared outcome, formatting its reasoning over the gathered set."""
    fields = {
        "values": ", ".join(str(inst.tag.value) for inst in gathered),
        "sources": ", ".join(inst.source_id for inst in gathered),
        "count": str(len(gathered)),
    }
    return _result(
        spec,
        subject_id,
        VERDICT_BY_NAME[outcome.verdict],
        outcome.reasoning.format(**fields),
        gathered,
        verdict_confidence=verdict_confidence,
        how_to_fix=outcome.how_to_fix,
        ratification_pending=ratification_pending,
    )


async def _judge_residue(
    con: ConsistencyEval, gathered: list[_Gathered], reason_fn: Reasoner
) -> tuple[str, float | None]:
    """Ask the AI about the DIFFERING residue only (values + sources — never the file). Returns a
    (signal, confidence) where signal is 'agree' / 'disagree' / 'cannot_tell'."""
    assert con.judge is not None
    # BOUNDED context: the DISTINCT gathered values (byte-identical duplicates collapsed) each with
    # the sources that reported it — the differing residue only, never the whole file / transactions.
    by_value: dict[str, list[str]] = {}
    for inst in gathered:
        by_value.setdefault(str(inst.tag.value), []).append(inst.source_id)
    context = {
        "values": [{"value": value, "sources": sources} for value, sources in by_value.items()]
    }
    try:
        result = await reason_fn(json.dumps(context))
    except AIClientError:
        logger.warning("consistency_ai_failed", rule=con.gather_tag)
        return "ai_failed", None
    if result.truncated:
        return "truncated", None
    judgment = result.judgment
    if judgment is None or judgment.value not in con.judge.value_domain:
        return (
            "cannot_tell",
            None,
        )  # malformed / off-domain → honest cannot-tell (never a default agree)
    if judgment.value == con.judge.consistent_value:
        return "agree", judgment.confidence
    if judgment.value == con.judge.inconsistent_value:
        return "disagree", judgment.confidence
    return "cannot_tell", judgment.confidence  # an in-domain "unknown"


async def evaluate_consistency_rule(
    spec: RuleSpec,
    snapshot: Snapshot,
    *,
    reasoner: Reasoner | None = None,
    confidence_floor: float | None = None,
) -> list[RuleEvaluation]:
    """Evaluate a cross-source consistency rule over its subjects, entirely from ``spec.consistency``."""
    con = spec.consistency
    assert con is not None, f"{spec.rule_id} is not a consistency rule"
    floor = confidence_floor if confidence_floor is not None else con.confidence_floor
    scope = _SOURCE_SCOPES.get(con.source_scope)
    if scope is None:
        raise KeyError(
            f"unknown source_scope {con.source_scope!r} (known: {sorted(_SOURCE_SCOPES)})"
        )

    doc_index = _index_borrower_documents(snapshot)  # built ONCE, not re-scanned per subject
    results: list[RuleEvaluation] = []
    for subject_id, _subject_tags in enumerate_subjects(con.subject, snapshot):
        result = scope(snapshot, subject_id, con.gather_tag, con.gather_filter, doc_index)
        gathered = result.included

        # 1. GATE THE INCLUSION DECISION — when ≥2 value-bearing sources could be compared, a shaky
        #    filter classification (a below-floor or "unknown" residence/mailing label) means we
        #    cannot trust WHICH sources are in scope → fail closed rather than silently include or
        #    exclude one. Only present filter tags are checked (an absent one → excluded, absent≠empty).
        #    Skipped when <2 candidates exist (nothing could be compared regardless of classification).
        if result.candidate_count >= 2 and result.filter_tags:
            filter_gate = evaluate_gate(result.filter_tags, confidence_floor=floor)
            if filter_gate.status is not GateStatus.PASS:
                verdict = (
                    Verdict.COULDNT_CHECK
                    if filter_gate.status is GateStatus.COULDNT_CHECK
                    else Verdict.NEEDS_REVIEW
                )
                results.append(
                    _result(
                        spec,
                        subject_id,
                        verdict,
                        f"the '{con.gather_filter.tag}' classification that decides which sources "  # type: ignore[union-attr]
                        f"to compare is not trustworthy: {filter_gate.reason}",
                        gathered,
                        verdict_confidence=filter_gate.verdict_confidence,
                    )
                )
                continue

        # 2. absent≠empty / a single source is not agreement → couldnt_check (nothing to compare).
        if len(gathered) < 2:
            of_type = (
                f" of type {con.gather_filter.value!r}" if con.gather_filter is not None else ""
            )
            results.append(
                _result(
                    spec,
                    subject_id,
                    Verdict.COULDNT_CHECK,
                    f"only {len(gathered)} source(s) carry '{con.gather_tag}'{of_type} for this "
                    f"subject — nothing to compare across sources",
                    gathered,
                )
            )
            continue

        # 4. The generic fail-closed gate over the gathered instances (unknown value → couldnt_check
        #    distinct; a below-floor confidence → needs_review; verdict_confidence = min).
        gate = evaluate_gate(
            {inst.source_id: inst.tag for inst in gathered}, confidence_floor=floor
        )
        if gate.status is GateStatus.COULDNT_CHECK:
            results.append(
                _result(
                    spec,
                    subject_id,
                    Verdict.COULDNT_CHECK,
                    gate.reason or "",
                    gathered,
                    verdict_confidence=gate.verdict_confidence,
                )
            )
            continue
        if gate.status is GateStatus.NEEDS_REVIEW:
            results.append(
                _result(
                    spec,
                    subject_id,
                    Verdict.NEEDS_REVIEW,
                    gate.reason or "",
                    gathered,
                    verdict_confidence=gate.verdict_confidence,
                )
            )
            continue

        # 5. THE EXACT BOOKEND — all equal after declared normalization → AGREE. NO AI CALL.
        normalized = {_normalize(inst.tag.value, con.normalization) for inst in gathered}
        if len(normalized) == 1:
            results.append(
                _outcome_result(
                    spec,
                    subject_id,
                    con.on_agree,
                    gathered,
                    verdict_confidence=gate.verdict_confidence,
                    ratification_pending=False,
                )
            )
            continue

        # 6. They DIFFER. exact mode → a discrepancy (NO AI). fuzzy mode → the AI judges the residue.
        if con.compare_mode == "exact":
            results.append(
                _outcome_result(
                    spec,
                    subject_id,
                    con.on_disagree,
                    gathered,
                    verdict_confidence=gate.verdict_confidence,
                    ratification_pending=False,
                )
            )
            continue

        reason_fn = reasoner if reasoner is not None else _bind_prompt(con)
        signal, ai_confidence = await _judge_residue(con, gathered, reason_fn)
        conf = ai_confidence if ai_confidence is not None else gate.verdict_confidence
        if signal == "agree":
            results.append(
                _outcome_result(
                    spec,
                    subject_id,
                    con.on_agree,
                    gathered,
                    verdict_confidence=conf,
                    ratification_pending=True,
                )
            )
        elif signal == "disagree":
            results.append(
                _outcome_result(
                    spec,
                    subject_id,
                    con.on_disagree,
                    gathered,
                    verdict_confidence=conf,
                    ratification_pending=True,
                )
            )
        elif signal == "ai_failed":
            results.append(
                _result(
                    spec,
                    subject_id,
                    Verdict.COULDNT_CHECK,
                    "the consistency judgment could not be produced (AI call failed) — cannot judge",
                    gathered,
                    verdict_confidence=gate.verdict_confidence,
                )
            )
        elif signal == "truncated":
            results.append(
                _result(
                    spec,
                    subject_id,
                    Verdict.COULDNT_CHECK,
                    "the consistency judgment response was truncated — cannot trust a partial judgment",
                    gathered,
                    verdict_confidence=gate.verdict_confidence,
                )
            )
        else:  # cannot_tell — an honest AI "unknown", NEVER a defaulted agree
            assert con.on_cannot_tell is not None  # required for fuzzy rules (validated at load)
            results.append(
                _outcome_result(
                    spec,
                    subject_id,
                    con.on_cannot_tell,
                    gathered,
                    verdict_confidence=conf,
                    ratification_pending=True,
                )
            )

    return results


def _bind_prompt(con: ConsistencyEval) -> Reasoner:
    """The default reasoner — the real model with the fuzzy judge's prompt bound."""
    assert con.judge is not None

    async def _call(context_json: str) -> RuleJudgmentResult:
        assert con.judge is not None
        return await reason_rule_judgment(con.judge.system_prompt, context_json)

    return _call


__all__ = ["Reasoner", "evaluate_consistency_rule"]
