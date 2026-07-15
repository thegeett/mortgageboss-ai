"""The GENERIC deterministic rule evaluator (LP-324) — runs ANY calculative/structural rule from its
spec, with ZERO per-rule Python.

Per subject (from the spec's executable ``subject_enumeration``):

    applicability (a declared tag predicate) → the fail-closed gate (LP-315, over the declared gated
    tags) → resolve the declared operands (tag / reference / calc / product) → the ordered outcome
    rules (first match wins; the fire condition is a declared Condition run through ``satisfies``) →
    a :class:`RuleEvaluation` with provenance inline.

AS-1 is re-expressed as data on this evaluator (`AS-1.yaml`'s `deterministic` block); its former
per-rule module carries no decision logic. Reuses ``evaluate_gate`` + ``satisfies`` as-is.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from app.ai.extraction.parsing import coerce_date, coerce_decimal
from app.verification.rule_engine.applicability import resolve_applicability
from app.verification.rule_engine.enumerators import enumerate_subjects
from app.verification.rule_engine.gate import GateResult, GateStatus, evaluate_gate
from app.verification.rule_engine.result import (
    VERDICT_BY_NAME,
    LoadBearingTag,
    RuleEvaluation,
    Verdict,
)
from app.verification.rules.schema import compare_values
from app.verification.rules.specs import (
    KNOWN_OPERAND_TYPES,
    DeterministicEval,
    Operand,
    OutcomeRule,
    RuleSpec,
    TagCondition,
)
from app.verification.snapshot.model import CalculationEntry, Snapshot
from app.verification.snapshot.tag import Tag

_UNKNOWN = "unknown"
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")

# Typed operand COERCERS (LP-328) — a declared operand ``type`` → the function that turns a raw tag
# value into a comparable typed value (or None when it cannot, which fails closed to couldnt_check —
# never a fabricated value, never a silent 0/epoch). ``date`` REUSES the SHARED ``coerce_date`` (one
# date parser across the deterministic + consistency evaluators, so they can never disagree; it never
# guesses an ambiguous date — an unparseable date → None → couldnt_check). A new type is one entry.
_COERCERS: dict[str, Callable[[Any], Any]] = {
    "decimal": coerce_decimal,
    "date": coerce_date,
}

# Drift guard: the coercer registry must cover EXACTLY the types specs validate against at load, so a
# declared-but-unhandled type fails loud at import rather than as an uncaught KeyError mid-run.
assert set(_COERCERS) == KNOWN_OPERAND_TYPES, "operand coercers drifted from KNOWN_OPERAND_TYPES"


def _load_bearing(
    spec: DeterministicEval, subject_tags: Mapping[str, Tag]
) -> tuple[LoadBearingTag, ...]:
    """The present load-bearing tags, inline, in the spec's declared order (provenance)."""
    return tuple(
        LoadBearingTag(tag_id, tag.value, tag.confidence, tag.reasoning, tag.source_facts)
        for tag_id in spec.load_bearing_tags
        if (tag := subject_tags.get(tag_id)) is not None
    )


def _result(
    spec: RuleSpec,
    subject_id: str,
    verdict: Verdict,
    reasoning: str,
    subject_tags: Mapping[str, Tag],
    *,
    verdict_confidence: float | None = None,
    threshold_used: Decimal | None = None,
    how_to_fix: str | None = None,
) -> RuleEvaluation:
    assert spec.deterministic is not None
    return RuleEvaluation(
        rule_id=spec.rule_id,
        subject_id=subject_id,
        verdict=verdict,
        verdict_confidence=verdict_confidence,
        load_bearing_tags=_load_bearing(spec.deterministic, subject_tags),
        threshold_used=threshold_used,
        priya_validated=spec.reference_values.priya_validated,
        gated_pending_signoff=not spec.reference_values.priya_validated,
        reasoning=reasoning,
        how_to_fix=how_to_fix,
    )


def _calc_operand(snapshot: Snapshot, calc_name: str, key: str) -> Decimal | None:
    """A calculator value, honoring the LP-318 gated flag (a gated calc is not trustworthy → None)."""
    calculations = snapshot.calculations
    if calculations.absent:
        return None
    entry = getattr(calculations, calc_name, None)
    if not isinstance(entry, CalculationEntry) or entry.gated:
        return None
    return coerce_decimal(entry.value.get(key))


def _reference_operand(spec: RuleSpec, key: str) -> Decimal | None:
    """A reference value: a trailing ``%`` → a fraction; else a plain Decimal. None if unusable."""
    raw = spec.reference_values.values.get(key)
    if raw is None:
        return None
    match = _PERCENT.search(raw)
    if match is not None:
        return Decimal(match.group(1)) / Decimal(100)
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _resolve_operand(
    operand: Operand, spec: RuleSpec, snapshot: Snapshot, subject_tags: Mapping[str, Tag]
) -> Any | None:
    """Resolve a declared operand to a TYPED value (Decimal / date), or None (→ couldnt_check).

    A ``tag`` operand is coerced per its declared ``type`` (LP-328); an ABSENT tag → None (absent ≠
    empty — couldnt_check with that reason, never fired), and an unparseable value → None (never a
    fabricated value). ``reference`` / ``calc`` / ``product`` are decimal by construction."""
    if operand.tag is not None:
        tag = subject_tags.get(operand.tag)
        return _COERCERS[operand.type](tag.value) if tag is not None else None
    if operand.reference is not None:
        return _reference_operand(spec, operand.reference)
    if operand.calc is not None:
        return _calc_operand(snapshot, operand.calc[0], operand.calc[1])
    if operand.product is not None:
        product = Decimal(1)
        for factor in operand.product:
            value = _resolve_operand(factor, spec, snapshot, subject_tags)
            if value is None:
                return None
            product *= value
        return product
    return None  # unreachable (the Operand validator guarantees exactly one source)


def _tags_hold(when_tags: tuple[TagCondition, ...], subject_tags: Mapping[str, Tag]) -> bool:
    for cond in when_tags:
        tag = subject_tags.get(cond.tag)
        observed = tag.value if tag is not None else None
        holds = (observed == cond.value) if cond.op == "eq" else (observed != cond.value)
        if not holds:
            return False
    return True


def _outcome_matches(
    outcome: OutcomeRule, subject_tags: Mapping[str, Tag], operands: dict[str, Any]
) -> bool:
    if outcome.default:
        return True
    if not _tags_hold(outcome.when_tags, subject_tags):
        return False
    if outcome.when_compare is not None:
        cmp = outcome.when_compare
        left, right = operands.get(cmp.left), operands.get(cmp.right)
        if left is None or right is None:
            return False
        # The shared, type-agnostic primitive (LP-328): the load-time validator guarantees left/right
        # are the SAME type, so ``<op>`` is well-defined for Decimal AND date. Decimal is byte-identical
        # to the former ``satisfies(Condition(op, right), left)``.
        return compare_values(cmp.op, left, right)
    return True


def evaluate_deterministic_rule(
    spec: RuleSpec, snapshot: Snapshot, *, confidence_floor: float | None = None
) -> list[RuleEvaluation]:
    """Evaluate a deterministic rule over its subjects, entirely from ``spec.deterministic``."""
    det = spec.deterministic
    assert det is not None, f"{spec.rule_id} is not a deterministic rule"
    floor = confidence_floor if confidence_floor is not None else det.confidence_floor
    threshold_operand = "threshold" if "threshold" in det.operands else None

    results: list[RuleEvaluation] = []
    for subject_id, subject_tags in enumerate_subjects(spec.subject_enumeration, snapshot):
        # 1. Applicability (from a declared tag predicate — the SHARED §8 resolver, LP-329).
        if det.applicability is not None:
            terminal = resolve_applicability(det.applicability, subject_tags)
            if terminal is not None:
                verdict, reason = terminal
                results.append(_result(spec, subject_id, verdict, reason, subject_tags))
                continue

        # 2. The generic fail-closed gate over the declared gated tags.
        gate: GateResult = evaluate_gate(
            {tag_id: subject_tags.get(tag_id) for tag_id in det.gated_tags},
            confidence_floor=floor,
        )
        if gate.status is GateStatus.COULDNT_CHECK:
            results.append(
                _result(
                    spec,
                    subject_id,
                    Verdict.COULDNT_CHECK,
                    gate.reason or "",
                    subject_tags,
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
                    subject_tags,
                    verdict_confidence=gate.verdict_confidence,
                )
            )
            continue

        # 3. Resolve the declared operands (each to its declared type). Any unresolvable operand →
        #    couldnt_check (never a fabricated value); threshold_used stays None.
        operands: dict[str, Any] = {}
        failed: str | None = None
        for name, operand in det.operands.items():
            value = _resolve_operand(operand, spec, snapshot, subject_tags)
            if value is None:
                failed = name
                break
            operands[name] = value
        if failed is not None:
            results.append(
                _result(
                    spec,
                    subject_id,
                    Verdict.COULDNT_CHECK,
                    f"operand '{failed}' could not be resolved — cannot evaluate the rule",
                    subject_tags,
                    verdict_confidence=gate.verdict_confidence,
                )
            )
            continue

        # threshold_used is the numeric threshold on the finding (Decimal-only by its column type); a
        # non-Decimal typed threshold (e.g. a date operand) leaves it None — the operands are inline.
        threshold_raw = operands.get(threshold_operand) if threshold_operand else None
        threshold_used = threshold_raw if isinstance(threshold_raw, Decimal) else None

        # 4. The ordered outcomes — first match wins (the fire condition via satisfies()).
        for outcome in det.outcomes:
            if _outcome_matches(outcome, subject_tags, operands):
                reasoning = outcome.reasoning.format(**{k: str(v) for k, v in operands.items()})
                results.append(
                    _result(
                        spec,
                        subject_id,
                        VERDICT_BY_NAME[outcome.verdict],
                        reasoning,
                        subject_tags,
                        verdict_confidence=gate.verdict_confidence,
                        threshold_used=threshold_used,
                        how_to_fix=outcome.how_to_fix,
                    )
                )
                break
        else:
            # Unreachable given the load-time default-outcome validation, but NEVER silently drop a
            # subject: fail closed to couldnt_check rather than emit no finding (a false green).
            results.append(
                _result(
                    spec,
                    subject_id,
                    Verdict.COULDNT_CHECK,
                    "no outcome matched this subject — cannot reach a verdict",
                    subject_tags,
                    verdict_confidence=gate.verdict_confidence,
                    threshold_used=threshold_used,
                )
            )

    return results


__all__ = ["evaluate_deterministic_rule"]
