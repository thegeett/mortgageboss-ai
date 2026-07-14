"""The thin AS-1 rule (LP-315) — query tags + arithmetic, no AI, no direction filter."""

from __future__ import annotations

from decimal import Decimal

from app.verification.rule_engine.as1 import (
    TAG_AMOUNT,
    TAG_HAS_SOURCE,
    TAG_IS_MONEY_IN,
    evaluate_as1,
)
from app.verification.rule_engine.result import RuleEvaluation, Verdict
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

_INCOME = Decimal("8000")  # threshold = 0.5 * 8000 = 4000
_MULTIPLIER = Decimal("0.5")


def _tag(
    tag_id: str,
    value: str,
    *,
    confidence: float | None,
    produced_by: TagProducedBy,
    stage: TagStage,
) -> Tag:
    return Tag(
        value=value,
        confidence=confidence,
        reasoning=f"{tag_id} reason",
        source_facts=("txndeposit0000000",),
        produced_by=produced_by,
        tag_role=TagRole.STRUCTURAL_FACT,
        tag_version=1,
        stage=stage,
    )


def _money_in(value: str = "in", *, confidence: float | None = 0.9) -> Tag:
    return _tag(
        TAG_IS_MONEY_IN,
        value,
        confidence=confidence,
        produced_by=TagProducedBy.AI,
        stage=TagStage.A,
    )


def _amount(value: str) -> Tag:
    return _tag(
        TAG_AMOUNT, value, confidence=None, produced_by=TagProducedBy.PARSED, stage=TagStage.A
    )


def _source(value: str = "no", *, confidence: float | None = 0.8) -> Tag:
    return _tag(
        TAG_HAS_SOURCE, value, confidence=confidence, produced_by=TagProducedBy.AI, stage=TagStage.B
    )


def _evaluate(
    tags: dict[str, Tag],
    *,
    confidence_floor: float = 0.5,
    contradiction: bool = False,
    income: Decimal | None = _INCOME,
) -> RuleEvaluation:
    return evaluate_as1(
        "txndeposit0000000",
        tags,
        threshold_multiplier=_MULTIPLIER,
        qualifying_income=income,
        priya_validated=False,
        confidence_floor=confidence_floor,
        contradiction=contradiction,
    )


# --------------------------------------------------------------------------- #
# Fires / satisfied
# --------------------------------------------------------------------------- #


def test_fires_on_unsourced_large_deposit() -> None:
    result = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in(confidence=0.9),
            TAG_AMOUNT: _amount("5000.00"),
            TAG_HAS_SOURCE: _source("no", confidence=0.8),
        }
    )
    assert result.verdict is Verdict.FIRED
    assert result.threshold_used == Decimal("4000.0")  # 0.5 * 8000
    assert result.verdict_confidence == 0.8  # min(is_money_in 0.9, has_source 0.8); amount ignored
    assert result.how_to_fix is not None
    # The three load-bearing tags are carried inline (provenance — never a bare number).
    ids = {t.tag_id for t in result.load_bearing_tags}
    assert ids == {TAG_IS_MONEY_IN, TAG_AMOUNT, TAG_HAS_SOURCE}
    assert result.gated_pending_signoff is True  # AS-1 threshold not Priya-validated


def test_satisfied_when_sourced() -> None:
    result = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in(),
            TAG_AMOUNT: _amount("5000.00"),
            TAG_HAS_SOURCE: _source("yes"),
        }
    )
    assert result.verdict is Verdict.SATISFIED


def test_satisfied_when_below_threshold() -> None:
    result = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in(),
            TAG_AMOUNT: _amount("3000.00"),
            TAG_HAS_SOURCE: _source("no"),
        }
    )
    assert result.verdict is Verdict.SATISFIED


def test_threshold_boundary_uses_strict_greater_than() -> None:
    # Exactly at the threshold (4000) is NOT over (GT is strict) → satisfied.
    at = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in(),
            TAG_AMOUNT: _amount("4000.00"),
            TAG_HAS_SOURCE: _source("no"),
        }
    )
    assert at.verdict is Verdict.SATISFIED
    # A cent above fires.
    over = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in(),
            TAG_AMOUNT: _amount("4000.01"),
            TAG_HAS_SOURCE: _source("no"),
        }
    )
    assert over.verdict is Verdict.FIRED


# --------------------------------------------------------------------------- #
# Fail-closed gate
# --------------------------------------------------------------------------- #


def test_has_identified_source_unknown_is_couldnt_check_not_fired() -> None:
    result = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in(),
            TAG_AMOUNT: _amount("5000.00"),
            TAG_HAS_SOURCE: _source("unknown"),
        }
    )
    assert result.verdict is Verdict.COULDNT_CHECK
    assert "unknown" in result.reasoning


def test_is_money_in_unknown_is_couldnt_check() -> None:
    result = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in("unknown"),
            TAG_AMOUNT: _amount("5000.00"),
            TAG_HAS_SOURCE: _source("no"),
        }
    )
    assert result.verdict is Verdict.COULDNT_CHECK


def test_absent_source_tag_is_couldnt_check_distinct_reason() -> None:
    result = _evaluate(
        {TAG_IS_MONEY_IN: _money_in(), TAG_AMOUNT: _amount("5000.00")}
    )  # no has_source
    assert result.verdict is Verdict.COULDNT_CHECK
    assert "absent" in result.reasoning and TAG_HAS_SOURCE in result.reasoning


def test_low_confidence_load_bearing_tag_is_needs_review() -> None:
    result = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in(confidence=0.9),
            TAG_AMOUNT: _amount("5000.00"),
            TAG_HAS_SOURCE: _source("no", confidence=0.3),
        }
    )
    assert result.verdict is Verdict.NEEDS_REVIEW  # NOT a confident satisfied/fired
    assert result.verdict_confidence == 0.3


def test_contradiction_is_needs_review() -> None:
    result = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in(),
            TAG_AMOUNT: _amount("5000.00"),
            TAG_HAS_SOURCE: _source("no"),
        },
        contradiction=True,
    )
    assert result.verdict is Verdict.NEEDS_REVIEW


def test_income_unavailable_is_couldnt_check() -> None:
    result = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in(),
            TAG_AMOUNT: _amount("5000.00"),
            TAG_HAS_SOURCE: _source("no"),
        },
        income=None,
    )
    assert result.verdict is Verdict.COULDNT_CHECK


# --------------------------------------------------------------------------- #
# Applicability + the no-direction-filter guarantee
# --------------------------------------------------------------------------- #


def test_money_out_is_not_applicable() -> None:
    result = _evaluate({TAG_IS_MONEY_IN: _money_in("out"), TAG_AMOUNT: _amount("5000.00")})
    assert result.verdict is Verdict.NOT_APPLICABLE


def test_deposit_is_evaluated_regardless_of_raw_label() -> None:
    """The bug cannot recur: applicability is the is_money_in TAG, not a raw label. A deposit the
    AI judged money-in is evaluated even though its raw label was 'transfer'/ambiguous."""
    # We only carry the TAG here — there is no raw 'direction' anywhere in the rule's input.
    result = _evaluate(
        {
            TAG_IS_MONEY_IN: _money_in("in"),
            TAG_AMOUNT: _amount("9000.00"),
            TAG_HAS_SOURCE: _source("no"),
        }
    )
    assert result.verdict is Verdict.FIRED  # evaluated + fired, not silently dropped


def test_deterministic_same_tags_same_verdict() -> None:
    tags = {
        TAG_IS_MONEY_IN: _money_in(),
        TAG_AMOUNT: _amount("5000.00"),
        TAG_HAS_SOURCE: _source("no"),
    }
    assert _evaluate(tags).verdict == _evaluate(tags).verdict == Verdict.FIRED
