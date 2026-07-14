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
from decimal import Decimal

from app.ai.extraction.parsing import coerce_decimal
from app.verification.rule_engine.gate import GateStatus, evaluate_gate
from app.verification.rule_engine.result import LoadBearingTag, RuleEvaluation, Verdict
from app.verification.rules.schema import Condition, Operator, satisfies
from app.verification.snapshot.tag import Tag

RULE_ID = "AS-1"

# The tags AS-1's verdict RESTS ON — carried inline as provenance. ``txn.amount`` is a parsed
# passthrough (confidence None → ignored in the min). ``txn.source_strength`` (LP-314a) refines a
# sourced verdict; it is shown here for provenance but is NOT gated (derived from
# has_identified_source, and may be absent on older snapshots).
TAG_IS_MONEY_IN = "txn.is_money_in"
TAG_AMOUNT = "txn.amount"
TAG_HAS_SOURCE = "txn.has_identified_source"
TAG_SOURCE_STRENGTH = "txn.source_strength"
LOAD_BEARING_TAGS = (TAG_IS_MONEY_IN, TAG_AMOUNT, TAG_HAS_SOURCE, TAG_SOURCE_STRENGTH)

# The subset the fail-closed gate actually inspects — a proper subset of LOAD_BEARING_TAGS. The
# gate dict is built from THIS constant (not hand-listed), so the gated set has one source of
# truth and can never silently drift from the provenance list. ``source_strength`` is deliberately
# excluded: it is provenance-only, so its absence must never force couldnt_check.
_GATED_TAGS = (TAG_IS_MONEY_IN, TAG_AMOUNT, TAG_HAS_SOURCE)

_MONEY_IN = "in"
_UNKNOWN = "unknown"
_SOURCED = "yes"
_STRENGTH_SELF_ASSERTED = "self_asserted"  # a description-only claim — not a proven paper trail

_HOW_TO_FIX = (
    "Document this deposit's source — a payroll/direct-deposit match, a transfer from the "
    "borrower's own account, or a gift / large-deposit letter — before the file is complete."
)
# For a large deposit whose source is only self-asserted (claimed in the description, no matching
# debit found): the processor "show me the debit" discipline (LP-314a).
_HOW_TO_FIX_SELF_ASSERTED = (
    "This large deposit claims an own-account or gift source in its description, but no matching "
    "withdrawal was found in the file. Obtain the statement for the source account named in the "
    "deposit's description showing the corresponding withdrawal (the paper trail)."
)


def _tag_value(subject_tags: Mapping[str, Tag], tag_id: str) -> object:
    """The value of a tag if present, else None (for optional, non-gated refinement tags)."""
    tag = subject_tags.get(tag_id)
    return tag.value if tag is not None else None


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
    threshold_multiplier: Decimal | None,
    qualifying_income: Decimal | None,
    priya_validated: bool,
    confidence_floor: float,
    contradiction: bool = False,
) -> RuleEvaluation:
    """Evaluate AS-1 for ONE transaction subject — applicability → gate → fire arithmetic.

    ``subject_tags`` is the deposit's tag map (``by_subject[content_id]``). ``qualifying_income``
    is the loan-level monthly qualifying income (from the DTI calculator); ``threshold_multiplier``
    is the spec's percentage as a fraction. Either being ``None`` (income unavailable, or the spec
    prose carried no usable percentage) yields ``couldnt_check`` — never a fabricated threshold.
    Pure + deterministic: the same tags yield the same verdict every run.
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

    # 2. The generic fail-closed gate over the GATED tags (source_strength is provenance-only).
    gate = evaluate_gate(
        {tag_id: subject_tags.get(tag_id) for tag_id in _GATED_TAGS},
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

    # 3. Gate passed — the deterministic arithmetic. The threshold inputs are required rule-level
    # inputs: either being None yields couldnt_check, never a fabricated threshold.
    if threshold_multiplier is None:
        return _result(
            subject_id,
            Verdict.COULDNT_CHECK,
            "the spec's large-deposit threshold carries no usable percentage — cannot compute it",
            subject_tags,
            verdict_confidence=gate.verdict_confidence,
            priya_validated=priya_validated,
        )
    if qualifying_income is None:
        return _result(
            subject_id,
            Verdict.COULDNT_CHECK,
            "qualifying monthly income is unavailable — cannot compute the large-deposit threshold",
            subject_tags,
            verdict_confidence=gate.verdict_confidence,
            priya_validated=priya_validated,
        )
    amount = coerce_decimal(subject_tags[TAG_AMOUNT].value)
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
    at_or_over_threshold = satisfies(Condition(op=Operator.GE, value=threshold, unit="usd"), amount)
    sourced = subject_tags[TAG_HAS_SOURCE].value == _SOURCED

    if not sourced:
        # Unsourced (has_identified_source == "no"): the fraud case, if it is a large deposit.
        if over_threshold:
            return _result(
                subject_id,
                Verdict.FIRED,
                f"deposit {amount} exceeds the large-deposit threshold {threshold} "
                f"(= {threshold_multiplier} x qualifying income {qualifying_income}) and is not "
                f"sourced (has_identified_source={subject_tags[TAG_HAS_SOURCE].value})",
                subject_tags,
                verdict_confidence=gate.verdict_confidence,
                threshold_used=threshold,
                how_to_fix=_HOW_TO_FIX,
                priya_validated=priya_validated,
            )
        return _result(
            subject_id,
            Verdict.SATISFIED,
            f"deposit {amount} is at or below the large-deposit threshold {threshold}",
            subject_tags,
            verdict_confidence=gate.verdict_confidence,
            threshold_used=threshold,
            priya_validated=priya_validated,
        )

    # Sourced (has_identified_source == "yes"). A LARGE deposit whose source is only SELF-ASSERTED
    # (claimed in the description, no matching debit) is not a clean pass — it needs the paper
    # trail, exactly as a processor would ask (LP-314a). A verified / intrinsic source, or a small
    # self-asserted transfer, is satisfied. Uses GE ("at or over"): the soft needs-review nudge is
    # deliberately more inclusive at the boundary than the strict GT "exceeds" of the hard FIRE.
    strength = _tag_value(subject_tags, TAG_SOURCE_STRENGTH)
    if strength == _STRENGTH_SELF_ASSERTED and at_or_over_threshold:
        return _result(
            subject_id,
            Verdict.NEEDS_REVIEW,
            f"deposit {amount} is at or over the large-deposit threshold {threshold} and claims an "
            f"own-account/gift source, but no matching debit was found in the file (self_asserted) "
            f"— a verified paper trail is needed",
            subject_tags,
            verdict_confidence=gate.verdict_confidence,
            threshold_used=threshold,
            how_to_fix=_HOW_TO_FIX_SELF_ASSERTED,
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
