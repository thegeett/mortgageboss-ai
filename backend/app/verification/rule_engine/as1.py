"""AS-1 — large-deposit sourcing sweep — as a THIN deterministic rule (LP-315).

The payoff of the fact-tag architecture: AS-1 is now a query over clean tags + arithmetic, with
NO AI and NO ``direction==`` label filter anywhere. It reads three tags per deposit —
``txn.is_money_in`` (Stage A), ``txn.amount`` (Stage A passthrough), ``txn.has_identified_source``
(Stage B) — plus the spec's Priya-validated threshold applied to qualifying income, and fires on
an unsourced large deposit.

The old bug (a ``direction=="credit"`` filter that silently dropped ambiguously-labelled deposits)
cannot recur: the subject universe is ``is_money_in == "in"`` — an AI-resolved TAG, never a raw
label — so a "transfer"/"ACH"/unlabelled deposit the AI judged money-in IS evaluated.

Evaluation order per transaction subject: applicability (via ``is_money_in``) → the generic
fail-closed gate over the load-bearing tags → the deterministic fire arithmetic (reusing
:func:`satisfies`, never a re-implemented ``>``).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from app.verification.rule_engine.gate import GateStatus, evaluate_gate
from app.verification.rule_engine.result import LoadBearingTag, RuleEvaluation, Verdict
from app.verification.rules.schema import Condition, Operator, satisfies
from app.verification.snapshot.tag import Tag

RULE_ID = "AS-1"

# The tags AS-1's verdict RESTS ON, in gate order (a subset of AS-1's declared rule_tags,
# LP-311). ``txn.amount`` is a parsed passthrough (confidence None → ignored in the min).
TAG_IS_MONEY_IN = "txn.is_money_in"
TAG_AMOUNT = "txn.amount"
TAG_HAS_SOURCE = "txn.has_identified_source"
LOAD_BEARING_TAGS = (TAG_IS_MONEY_IN, TAG_AMOUNT, TAG_HAS_SOURCE)

_MONEY_IN = "in"
_UNKNOWN = "unknown"
_SOURCED = "yes"

_HOW_TO_FIX = (
    "Document this deposit's source — a payroll/direct-deposit match, a transfer from the "
    "borrower's own account, or a gift / large-deposit letter — before the file is complete."
)


def _parse_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("$", "").replace(" ", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _load_bearing(subject_tags: Mapping[str, Tag]) -> tuple[LoadBearingTag, ...]:
    """The present load-bearing tags, inline, in a stable order (provenance on the verdict)."""
    return tuple(
        LoadBearingTag(tag_id, tag.value, tag.confidence, tag.reasoning)
        for tag_id in LOAD_BEARING_TAGS
        if (tag := subject_tags.get(tag_id)) is not None
    )


def _result(
    subject_id: str,
    verdict: Verdict,
    reasoning: str,
    subject_tags: Mapping[str, Tag],
    *,
    verdict_confidence: float | None = None,
    threshold_used: Decimal | None = None,
    how_to_fix: str | None = None,
    priya_validated: bool,
) -> RuleEvaluation:
    return RuleEvaluation(
        rule_id=RULE_ID,
        subject_id=subject_id,
        verdict=verdict,
        verdict_confidence=verdict_confidence,
        load_bearing_tags=_load_bearing(subject_tags),
        threshold_used=threshold_used,
        priya_validated=priya_validated,
        gated_pending_signoff=not priya_validated,
        reasoning=reasoning,
        how_to_fix=how_to_fix,
    )


def evaluate_as1(
    subject_id: str,
    subject_tags: Mapping[str, Tag],
    *,
    threshold_multiplier: Decimal,
    qualifying_income: Decimal | None,
    priya_validated: bool,
    confidence_floor: float,
    contradiction: bool = False,
) -> RuleEvaluation:
    """Evaluate AS-1 for ONE transaction subject — applicability → gate → fire arithmetic.

    ``subject_tags`` is the deposit's tag map (``by_subject[content_id]``). ``qualifying_income``
    is the loan-level monthly qualifying income (from the DTI calculator). Pure + deterministic:
    the same tags yield the same verdict every run.
    """
    is_money_in = subject_tags.get(TAG_IS_MONEY_IN)

    # 1. Applicability, decided from the is_money_in TAG (never a raw direction label).
    if is_money_in is None:
        return _result(
            subject_id,
            Verdict.COULDNT_CHECK,
            "txn.is_money_in was not produced for this transaction — cannot tell if it is a deposit",
            subject_tags,
            priya_validated=priya_validated,
        )
    if is_money_in.value == _UNKNOWN:
        return _result(
            subject_id,
            Verdict.COULDNT_CHECK,
            "txn.is_money_in is unknown — cannot confirm this is a money-in deposit",
            subject_tags,
            priya_validated=priya_validated,
        )
    if is_money_in.value != _MONEY_IN:
        return _result(
            subject_id,
            Verdict.NOT_APPLICABLE,
            "not a money-in deposit (is_money_in != 'in') — AS-1 does not apply",
            subject_tags,
            priya_validated=priya_validated,
        )

    # 2. The generic fail-closed gate over the load-bearing tags.
    gate = evaluate_gate(
        {
            TAG_IS_MONEY_IN: is_money_in,
            TAG_AMOUNT: subject_tags.get(TAG_AMOUNT),
            TAG_HAS_SOURCE: subject_tags.get(TAG_HAS_SOURCE),
        },
        confidence_floor=confidence_floor,
        contradiction=contradiction,
    )
    if gate.status is GateStatus.COULDNT_CHECK:
        return _result(
            subject_id,
            Verdict.COULDNT_CHECK,
            gate.reason or "",
            subject_tags,
            verdict_confidence=gate.verdict_confidence,
            priya_validated=priya_validated,
        )
    if gate.status is GateStatus.NEEDS_REVIEW:
        return _result(
            subject_id,
            Verdict.NEEDS_REVIEW,
            gate.reason or "",
            subject_tags,
            verdict_confidence=gate.verdict_confidence,
            priya_validated=priya_validated,
        )

    # 3. Gate passed — the deterministic arithmetic. Income is a required rule-level input.
    if qualifying_income is None:
        return _result(
            subject_id,
            Verdict.COULDNT_CHECK,
            "qualifying monthly income is unavailable — cannot compute the large-deposit threshold",
            subject_tags,
            verdict_confidence=gate.verdict_confidence,
            priya_validated=priya_validated,
        )
    amount = _parse_decimal(subject_tags[TAG_AMOUNT].value)
    if amount is None:
        return _result(
            subject_id,
            Verdict.COULDNT_CHECK,
            "the deposit amount is not a parseable number",
            subject_tags,
            verdict_confidence=gate.verdict_confidence,
            priya_validated=priya_validated,
        )

    threshold = qualifying_income * threshold_multiplier
    over_threshold = satisfies(Condition(op=Operator.GT, value=threshold, unit="usd"), amount)
    sourced = subject_tags[TAG_HAS_SOURCE].value == _SOURCED

    if over_threshold and not sourced:
        return _result(
            subject_id,
            Verdict.FIRED,
            f"deposit {amount} exceeds the large-deposit threshold {threshold} "
            f"(= {threshold_multiplier} x qualifying income {qualifying_income}) and is not sourced "
            f"(has_identified_source={subject_tags[TAG_HAS_SOURCE].value})",
            subject_tags,
            verdict_confidence=gate.verdict_confidence,
            threshold_used=threshold,
            how_to_fix=_HOW_TO_FIX,
            priya_validated=priya_validated,
        )
    reason = (
        "the deposit is already sourced (has_identified_source=yes)"
        if over_threshold
        else f"deposit {amount} is at or below the large-deposit threshold {threshold}"
    )
    return _result(
        subject_id,
        Verdict.SATISFIED,
        reason,
        subject_tags,
        verdict_confidence=gate.verdict_confidence,
        threshold_used=threshold,
        priya_validated=priya_validated,
    )
