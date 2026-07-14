"""OC-2 occupancy reasonableness — the AI-at-rule-time JUDGMENT-rule pattern (LP-319).

Keyless (the Reasoner stub seam): proves the procedural armor for the judgment slice — reason over
TAGS not raw docs, MANDATORY human ratification (never auto-ships), confidence-gated, fail-closed,
and a rule_judgment tag carrying provenance. No AI, no DB.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.ai.client import AIClientError
from app.ai.occupancy_judgment import OccupancyJudgment, OccupancyJudgmentResult
from app.verification.rule_engine.oc2 import (
    LOAN_SUBJECT,
    REASONED_OVER,
    Oc2Evaluation,
    evaluate_oc2,
)
from app.verification.rule_engine.result import Verdict
from app.verification.snapshot.model import (
    CalculationsSection,
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

_WHEN = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Stub reasoner (the keyless seam) + snapshot / tag builders
# --------------------------------------------------------------------------- #


class _StubReasoner:
    """Replays a canned occupancy judgment; captures the context it was handed."""

    def __init__(
        self,
        *,
        value: str | None = "yes",
        confidence: float | None = 0.9,
        reasoning: str | None = "occupancy.stated=primary is consistent with the signals",
        truncated: bool = False,
        malformed: bool = False,
        raises: Exception | None = None,
    ) -> None:
        self._value = value
        self._confidence = confidence
        self._reasoning = reasoning
        self._truncated = truncated
        self._malformed = malformed
        self._raises = raises
        self.context: str | None = None

    async def __call__(self, context_json: str) -> OccupancyJudgmentResult:
        self.context = context_json
        if self._raises is not None:
            raise self._raises
        judgment = (
            None
            if self._malformed
            else OccupancyJudgment(
                value=self._value or "", confidence=self._confidence, reasoning=self._reasoning
            )
        )
        return OccupancyJudgmentResult(
            judgment=judgment,
            input_tokens=0,
            output_tokens=0,
            model="stub",
            truncated=self._truncated,
        )


def _tag(
    value: str,
    *,
    confidence: float | None,
    produced_by: TagProducedBy = TagProducedBy.AI,
    reasoning: str = "fixture",
) -> Tag:
    return Tag(
        value=value,
        confidence=confidence,
        reasoning=reasoning,
        source_facts=(LOAN_SUBJECT,),
        produced_by=produced_by,
        tag_role=TagRole.STRUCTURAL_FACT,
        tag_version=1,
        stage=TagStage.A,
    )


def _occupancy_tags(
    *,
    stated: str | None = "primary",
    consistent: str | None = "yes",
    consistent_conf: float | None = 0.9,
    address_type: str | None = "residence",
    address_match: str | None = "yes",
) -> dict[str, Tag]:
    tags: dict[str, Tag] = {}
    if stated is not None:  # parsed structural fact (confidence None)
        tags["occupancy.stated"] = _tag(stated, confidence=None, produced_by=TagProducedBy.PARSED)
    if consistent is not None:
        tags["occupancy.consistent_with_signals"] = _tag(consistent, confidence=consistent_conf)
    if address_type is not None:
        tags["id.current_address_type"] = _tag(address_type, confidence=0.9)
    if address_match is not None:
        tags["property.address_normalized_match"] = _tag(address_match, confidence=0.9)
    return tags


def _snapshot(tags: dict[str, Tag] | None, *, tags_absent: bool = False) -> Snapshot:
    by_subject = {} if tags is None else {LOAN_SUBJECT: tags}
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=_WHEN,
        documents=DocumentsSection.present([]),
        calculations=CalculationsSection.missing(),
        tags=TagsSection.missing() if tags_absent else TagsSection.present(by_subject),
    )


async def _evaluate(
    tags: dict[str, Tag] | None, reasoner: _StubReasoner, **kw: object
) -> Oc2Evaluation:
    return await evaluate_oc2(_snapshot(tags), reasoner=reasoner, **kw)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Reason over TAGS, not raw docs
# --------------------------------------------------------------------------- #


async def test_judgment_reasons_over_tags_not_raw_documents() -> None:
    stub = _StubReasoner(value="yes")
    await _evaluate(_occupancy_tags(), stub)
    assert stub.context is not None
    # The context is built from the STRUCTURAL TAGS, addressed by tag id — not raw documents.
    assert "occupancy_tags" in stub.context
    for tag_id in REASONED_OVER:
        assert tag_id in stub.context
    assert '"primary"' in stub.context  # the occupancy.stated value rode in as a tag value


# --------------------------------------------------------------------------- #
# MANDATORY ratification — never auto-ships satisfied/fired
# --------------------------------------------------------------------------- #


async def test_reasonable_judgment_is_still_ratification_pending() -> None:
    # A clean primary → the AI judges "reasonable" — but it STILL never auto-ships satisfied.
    stub = _StubReasoner(value="yes", confidence=0.95)
    ev = await _evaluate(_occupancy_tags(), stub)
    assert ev.evaluation.verdict is Verdict.NEEDS_REVIEW
    assert ev.evaluation.ratification_pending is True
    assert ev.evaluation.verdict not in (Verdict.SATISFIED, Verdict.FIRED)


async def test_not_reasonable_judgment_is_needs_review_with_reasoning() -> None:
    # stated=primary but signals contradict → the AI judges "not reasonable" → needs_review.
    stub = _StubReasoner(
        value="no",
        confidence=0.9,
        reasoning="occupancy.consistent_with_signals=no; the subject looks like a second home",
    )
    ev = await _evaluate(_occupancy_tags(stated="primary", consistent="no"), stub)
    assert ev.evaluation.verdict is Verdict.NEEDS_REVIEW
    assert ev.evaluation.ratification_pending is True
    assert "second home" in ev.evaluation.reasoning


async def test_no_judgment_path_ever_auto_ships() -> None:
    # Across yes / no / unknown, the verdict is NEVER satisfied or fired — the mandatory armor.
    for value in ("yes", "no", "unknown"):
        stub = _StubReasoner(value=value, confidence=0.9)
        ev = await _evaluate(_occupancy_tags(), stub)
        assert ev.evaluation.verdict is Verdict.NEEDS_REVIEW
        assert ev.evaluation.ratification_pending is True


# --------------------------------------------------------------------------- #
# Confidence-gated + fail-closed gate on the structural inputs
# --------------------------------------------------------------------------- #


async def test_low_confidence_judgment_is_needs_review() -> None:
    stub = _StubReasoner(value="yes", confidence=0.2)  # below the 0.5 floor
    ev = await _evaluate(_occupancy_tags(), stub)
    assert ev.evaluation.verdict is Verdict.NEEDS_REVIEW
    assert ev.evaluation.ratification_pending is True
    assert "low-confidence" in ev.evaluation.reasoning


async def test_absent_load_bearing_tag_yields_couldnt_check() -> None:
    # occupancy.stated absent → the gate blocks BEFORE the AI is called (no judging over a hole).
    stub = _StubReasoner(value="yes")
    ev = await _evaluate(_occupancy_tags(stated=None), stub)
    assert ev.evaluation.verdict is Verdict.COULDNT_CHECK
    assert ev.judgment_tag is None
    assert stub.context is None  # the AI was never consulted


async def test_unknown_load_bearing_tag_yields_couldnt_check() -> None:
    stub = _StubReasoner(value="yes")
    ev = await _evaluate(_occupancy_tags(consistent="unknown"), stub)
    assert ev.evaluation.verdict is Verdict.COULDNT_CHECK
    assert ev.judgment_tag is None
    assert stub.context is None


# --------------------------------------------------------------------------- #
# The rule_judgment tag + provenance
# --------------------------------------------------------------------------- #


async def test_occupancy_reasonable_is_a_rule_judgment_tag() -> None:
    stub = _StubReasoner(value="no", confidence=0.85, reasoning="signals contradict a primary")
    ev = await _evaluate(_occupancy_tags(consistent="no"), stub)
    assert ev.judgment_tag is not None
    tag = ev.judgment_tag
    assert tag.tag_role is TagRole.RULE_JUDGMENT  # a per-rule verdict, not a shared structural fact
    assert tag.produced_by is TagProducedBy.AI
    assert tag.value == "no"
    assert tag.confidence == 0.85
    assert tag.reasoning == "signals contradict a primary"
    assert tag.source_facts == (LOAN_SUBJECT,)


async def test_result_carries_structural_tags_inline_for_the_ratifier() -> None:
    stub = _StubReasoner(value="no")
    ev = await _evaluate(_occupancy_tags(), stub)
    by_id = {t.tag_id: t for t in ev.evaluation.load_bearing_tags}
    # The human ratifying sees the structural facts the AI reasoned over, with their reasoning.
    assert "occupancy.stated" in by_id
    assert by_id["occupancy.stated"].value == "primary"
    assert by_id["occupancy.consistent_with_signals"].reasoning  # non-empty provenance


# --------------------------------------------------------------------------- #
# Honesty / fail-closed
# --------------------------------------------------------------------------- #


async def test_malformed_response_is_unknown_needs_review_not_a_default() -> None:
    stub = _StubReasoner(malformed=True)
    ev = await _evaluate(_occupancy_tags(), stub)
    assert ev.evaluation.verdict is Verdict.NEEDS_REVIEW
    assert ev.judgment_tag is not None and ev.judgment_tag.value == "unknown"
    assert "unknown" in ev.evaluation.reasoning


async def test_model_unknown_is_preserved() -> None:
    stub = _StubReasoner(value="unknown", confidence=0.6, reasoning="the tags are ambiguous")
    ev = await _evaluate(_occupancy_tags(), stub)
    assert ev.judgment_tag is not None and ev.judgment_tag.value == "unknown"
    assert ev.evaluation.verdict is Verdict.NEEDS_REVIEW


async def test_off_vocabulary_value_is_treated_as_unknown() -> None:
    stub = _StubReasoner(value="maybe")  # not in the allowed value set
    ev = await _evaluate(_occupancy_tags(), stub)
    assert ev.judgment_tag is not None and ev.judgment_tag.value == "unknown"
    assert ev.evaluation.verdict is Verdict.NEEDS_REVIEW


async def test_ai_client_error_yields_couldnt_check_absent_tag() -> None:
    stub = _StubReasoner(raises=AIClientError("boom"))
    ev = await _evaluate(_occupancy_tags(), stub)
    assert ev.evaluation.verdict is Verdict.COULDNT_CHECK
    assert ev.judgment_tag is None  # absent, never a fabricated verdict


async def test_truncated_response_yields_couldnt_check_absent_tag() -> None:
    stub = _StubReasoner(value="yes", truncated=True)
    ev = await _evaluate(_occupancy_tags(), stub)
    assert ev.evaluation.verdict is Verdict.COULDNT_CHECK
    assert ev.judgment_tag is None
