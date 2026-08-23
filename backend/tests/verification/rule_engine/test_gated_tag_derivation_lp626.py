"""LP-626 — a calculative rule shows the arithmetic that decided it.

IN-10 fired on LF-ABRS reading only "the income is declining year-over-year — stability/continuance
must be reviewed". The tag behind it carried the whole calculation:

    "2024 full-year wages were $155,443.80 from FINRA; 2025 wages were $49,674.77 (partial year,
     ~4 months based on end date 2025-04-27). Annualizing 2025 (~$149,024 if extrapolated for 12
     months) still shows decline..."

All of it in the provenance panel, none of it in the sentence. That matters because of how the rule was
CALIBRATED: its activation bar accepts false positives in as many words — "FN (uses declining income at
face value -> a bad loan ships) >> FP (a false decline -> a human glances)". The glance IS the remedy,
and it cost opening a panel.
"""

from __future__ import annotations

from app.verification.rule_engine.deterministic import _gated_tag_derivation
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage


def _tag(value: str, *, produced_by: TagProducedBy, reasoning: str | None = None) -> Tag:
    return Tag(
        value=value,
        confidence=0.9,
        reasoning=reasoning,
        produced_by=produced_by,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.B,
    )


def test_the_ai_tags_reasoning_becomes_the_derivation() -> None:
    """THE REPORTED CASE. IN-10 gates on exactly one AI tag, so that tag's reasoning IS why the rule
    fired — and `derivation` is the field LP-535 made un-paraphrasable by the composer."""
    det = load_rule_spec("IN-10").deterministic
    arithmetic = "2024 wages $155,443.80; annualized 2025 ~$149,024 — a decline."

    result = _gated_tag_derivation(
        det,
        {"income.is_declining": _tag("yes", produced_by=TagProducedBy.AI, reasoning=arithmetic)},
    )

    assert result == arithmetic


def test_a_tag_with_no_reasoning_derives_nothing() -> None:
    """Empty is honest. A derivation that says nothing is worse than none, because it occupies the
    place a reader expects the arithmetic to be."""
    det = load_rule_spec("IN-10").deterministic

    assert (
        _gated_tag_derivation(
            det, {"income.is_declining": _tag("yes", produced_by=TagProducedBy.AI)}
        )
        is None
    )
    assert (
        _gated_tag_derivation(
            det,
            {"income.is_declining": _tag("yes", produced_by=TagProducedBy.AI, reasoning="   ")},
        )
        is None
    )


def test_a_parsed_or_derived_tag_is_not_repeated() -> None:
    """Only an AI tag carries a reasoning the rule's own template does not already state. A derived
    tag's provenance IS the arithmetic the rule describes, so repeating it is noise dressed as
    auditability."""
    det = load_rule_spec("IN-10").deterministic

    for produced_by in (TagProducedBy.DERIVED, TagProducedBy.PARSED):
        assert (
            _gated_tag_derivation(
                det,
                {"income.is_declining": _tag("yes", produced_by=produced_by, reasoning="computed")},
            )
            is None
        )


def test_a_rule_gating_on_several_tags_derives_nothing() -> None:
    """There is no single "the reason" when a verdict compares several tags, and picking one would
    assert that it decided the outcome. AS-1 gates on three."""
    det = load_rule_spec("AS-1").deterministic
    assert det is not None and len(det.gated_tags) > 1, "AS-1 no longer gates on several tags"

    tags = {
        tag_id: _tag("yes", produced_by=TagProducedBy.AI, reasoning="x")
        for tag_id in det.gated_tags
    }

    assert _gated_tag_derivation(det, tags) is None


def test_an_absent_tag_derives_nothing() -> None:
    """The fail-closed gate has already routed this subject to couldnt_check; there is no arithmetic."""
    det = load_rule_spec("IN-10").deterministic

    assert _gated_tag_derivation(det, {}) is None
