"""The generic fail-closed gate (LP-315) — decision order + verdict_confidence."""

from __future__ import annotations

from app.verification.rule_engine.gate import GateStatus, evaluate_gate
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage


def _tag(
    value: str, *, confidence: float | None = 0.9, produced_by: TagProducedBy = TagProducedBy.AI
) -> Tag:
    return Tag(
        value=value,
        confidence=confidence,
        reasoning="r",
        source_facts=("cid",),
        produced_by=produced_by,
        tag_role=TagRole.STRUCTURAL_FACT,
        tag_version=1,
        stage=TagStage.A,
    )


def test_pass_when_all_present_confident_known() -> None:
    result = evaluate_gate(
        {"a": _tag("in", confidence=0.9), "b": _tag("yes", confidence=0.8)}, confidence_floor=0.5
    )
    assert result.status is GateStatus.PASS
    assert result.verdict_confidence == 0.8  # min of the two


def test_absent_tag_is_couldnt_check_naming_the_tag() -> None:
    result = evaluate_gate({"a": _tag("in"), "b": None}, confidence_floor=0.5)
    assert result.status is GateStatus.COULDNT_CHECK
    assert "'b'" in (result.reason or "") and "absent" in (result.reason or "")


def test_unknown_tag_is_couldnt_check_distinct_from_absent() -> None:
    result = evaluate_gate({"a": _tag("unknown")}, confidence_floor=0.5)
    assert result.status is GateStatus.COULDNT_CHECK
    assert "unknown" in (result.reason or "") and "absent" not in (result.reason or "")


def test_absent_takes_precedence_over_unknown() -> None:
    # Decision order: absent is checked before unknown.
    result = evaluate_gate({"a": None, "b": _tag("unknown")}, confidence_floor=0.5)
    assert result.status is GateStatus.COULDNT_CHECK and "absent" in (result.reason or "")


def test_contradiction_is_needs_review() -> None:
    result = evaluate_gate({"a": _tag("in")}, confidence_floor=0.5, contradiction=True)
    assert result.status is GateStatus.NEEDS_REVIEW and "contradiction" in (result.reason or "")


def test_below_confidence_floor_is_needs_review() -> None:
    result = evaluate_gate({"a": _tag("in", confidence=0.3)}, confidence_floor=0.5)
    assert result.status is GateStatus.NEEDS_REVIEW
    assert result.verdict_confidence == 0.3


def test_parsed_passthrough_none_confidence_is_ignored() -> None:
    # A parsed passthrough (confidence None) never gates and never lowers the min.
    result = evaluate_gate(
        {
            "amount": _tag("5000", confidence=None, produced_by=TagProducedBy.PARSED),
            "judged": _tag("in", confidence=0.7),
        },
        confidence_floor=0.5,
    )
    assert result.status is GateStatus.PASS
    assert result.verdict_confidence == 0.7  # only the AI tag's confidence counts


def test_all_parsed_yields_none_verdict_confidence() -> None:
    result = evaluate_gate(
        {"amount": _tag("5000", confidence=None, produced_by=TagProducedBy.PARSED)},
        confidence_floor=0.5,
    )
    assert result.status is GateStatus.PASS and result.verdict_confidence is None
