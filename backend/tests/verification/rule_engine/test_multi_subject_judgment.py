"""The MULTI-SUBJECT judgment evaluator (LP-327, GAP-B) — judgment.py generalized from single-subject
to declared subject enumeration, mirroring its siblings.

Proves the new shapes as DATA: a per_document judgment runs from a SPEC alone over N subjects → N
verdicts, each ratification-pending, each tag keyed to its subject; per-subject fail-closed (one
subject's gate/AI failure degrades ONLY that subject); gate-before-AI; the LP-319 armor per subject;
reason-over-tags with bounded per-subject context. OC-2's equivalence is proven by its own suite.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.ai.client import AIClientError
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.judgment import evaluate_judgment_rule
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import RuleSpec
from app.verification.snapshot.model import DocumentEntry, DocumentsSection, Snapshot, TagsSection
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

pytestmark = pytest.mark.anyio


# A BRAND-NEW judgment rule in a NEW subject shape (per_document) — the multi-subject evaluator has
# never seen it; it must run from this SPEC alone, ZERO per-rule Python.
_PER_DOC_JUDGMENT = {
    "rule_id": "JDOC-1",
    "name": "synthetic per-document judgment",
    "category": "Identity",
    "kind": "judgmental",
    "numeric_check": False,
    "criteria": "judge each document's flag",
    "applicability": {"scope": "every document", "trigger": "once per document"},
    "required_inputs": [
        {"name": "flag", "snapshot_path": 'tags[<doc>]["x.flag"]', "description": "the flag"}
    ],
    "reference_values": {"priya_validated": False, "threshold_needs_signoff": False},
    "subject_enumeration": "per_document",
    "subject_key_fields": ["document"],
    "evidence_required": "the document's flag",
    "guideline_reference": "n/a — synthetic",
    "spec_version": 1,
    "judgment": {
        "subject": "per_document",
        "load_bearing_tags": ["x.flag"],
        "reasoned_over": ["x.flag"],
        "output_tag": "x.judged",
        "value_domain": ["yes", "no", "unknown"],
        "system_prompt": "judge each document's flag",
    },
}
_SPEC = RuleSpec.model_validate(_PER_DOC_JUDGMENT)


def _flag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=0.9,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _snapshot(docs: dict[str, dict[str, Tag]]) -> Snapshot:
    entries = [DocumentEntry(content_id=cid, document_type="doc") for cid in docs]
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present(entries),
        tags=TagsSection.present(docs),
    )


class _Reasoner:
    """A keyless judgment stub — records each per-subject context + returns a chosen value/state."""

    def __init__(
        self, value: str = "yes", *, truncated: bool = False, raise_ai: bool = False
    ) -> None:
        self.value = value
        self.truncated = truncated
        self.raise_ai = raise_ai
        self.contexts: list[str] = []

    async def __call__(self, context_json: str) -> RuleJudgmentResult:
        self.contexts.append(context_json)
        if self.raise_ai:
            raise AIClientError("boom")
        judgment = (
            None if self.value == "__malformed__" else RuleJudgment(self.value, 0.8, "because")
        )
        return RuleJudgmentResult(judgment, 1, 1, "stub", self.truncated)


async def test_per_document_judgment_runs_from_a_spec_over_n_subjects() -> None:
    stub = _Reasoner("no")
    snap = _snapshot({"d1": {"x.flag": _flag("a")}, "d2": {"x.flag": _flag("b")}})
    evals = await evaluate_judgment_rule(_SPEC, snap, reasoner=stub, confidence_floor=0.5)
    # ONE evaluation + ONE tag per document, each keyed to its own subject.
    assert [e.evaluation.subject_id for e in evals] == ["d1", "d2"]
    assert all(
        e.evaluation.verdict is Verdict.NEEDS_REVIEW for e in evals
    )  # a judgment never fires/satisfies
    assert all(e.evaluation.ratification_pending for e in evals)  # LP-319 armor, per subject
    assert all(e.judgment_tag is not None for e in evals)
    assert [e.judgment_tag.source_facts for e in evals] == [
        ("d1",),
        ("d2",),
    ]  # keyed to its subject
    assert len(stub.contexts) == 2  # one bounded AI call PER subject (N subjects = N calls)


async def test_per_subject_fail_closed_one_gated_subject_does_not_block_others() -> None:
    # d1 is missing the load-bearing tag → gated couldnt_check with NO AI call; d2 evaluates normally.
    stub = _Reasoner("yes")
    snap = _snapshot({"d1": {}, "d2": {"x.flag": _flag("b")}})
    evals = await evaluate_judgment_rule(_SPEC, snap, reasoner=stub, confidence_floor=0.5)
    by_subject = {e.evaluation.subject_id: e for e in evals}
    assert by_subject["d1"].evaluation.verdict is Verdict.COULDNT_CHECK
    assert by_subject["d1"].judgment_tag is None  # gate-before-AI: no tag on a gated subject
    assert by_subject["d2"].evaluation.verdict is Verdict.NEEDS_REVIEW
    assert len(stub.contexts) == 1  # the AI was NOT called for the gated d1


async def test_per_subject_ai_failure_degrades_only_that_subject() -> None:
    stub = _Reasoner("yes", raise_ai=True)
    snap = _snapshot({"d1": {"x.flag": _flag("a")}, "d2": {"x.flag": _flag("b")}})
    evals = await evaluate_judgment_rule(_SPEC, snap, reasoner=stub, confidence_floor=0.5)
    # BOTH subjects' AI calls fail independently → each couldnt_check (not a wholesale rule failure).
    assert [e.evaluation.verdict for e in evals] == [Verdict.COULDNT_CHECK, Verdict.COULDNT_CHECK]
    assert all("AI call failed" in e.evaluation.reasoning for e in evals)


async def test_reason_over_tags_bounded_per_subject_context() -> None:
    stub = _Reasoner("yes")
    snap = _snapshot({"d1": {"x.flag": _flag("ALPHA")}, "d2": {"x.flag": _flag("BETA")}})
    await evaluate_judgment_rule(_SPEC, snap, reasoner=stub, confidence_floor=0.5)
    # Each per-subject prompt contains ONLY that subject's declared TAGS — never the other subject's
    # data, never a raw document.
    ctx1, ctx2 = (json.loads(c) for c in stub.contexts)
    assert "tags" in ctx1 and ctx1["tags"]["x.flag"]["value"] == "ALPHA"
    assert "BETA" not in json.dumps(ctx1)  # d1's context does not leak d2's fact
    assert "ALPHA" not in json.dumps(ctx2)
    assert "document_type" not in json.dumps(ctx1)  # tags, not the raw document


async def test_malformed_and_off_domain_are_unknown_with_reason_never_defaulted() -> None:
    for bad in ("__malformed__", "maybe"):  # a null judgment / an off-domain value
        stub = _Reasoner(bad)
        snap = _snapshot({"d1": {"x.flag": _flag("a")}})
        (result,) = await evaluate_judgment_rule(_SPEC, snap, reasoner=stub, confidence_floor=0.5)
        assert result.evaluation.verdict is Verdict.NEEDS_REVIEW  # armor: still human-reviewed
        assert result.judgment_tag is not None and result.judgment_tag.value == "unknown"  # honest


async def test_truncated_is_couldnt_check_for_that_subject() -> None:
    stub = _Reasoner("yes", truncated=True)
    snap = _snapshot({"d1": {"x.flag": _flag("a")}})
    (result,) = await evaluate_judgment_rule(_SPEC, snap, reasoner=stub, confidence_floor=0.5)
    assert result.evaluation.verdict is Verdict.COULDNT_CHECK
    assert "truncated" in result.evaluation.reasoning


async def test_subjects_are_evaluated_concurrently_not_sequentially() -> None:
    # LP-327 review: per-subject AI calls run concurrently (bounded). A barrier reasoner blocks each
    # call until ALL subjects are in-flight — this can only resolve if they run concurrently; a
    # SEQUENTIAL loop would hang on the first call (the others never start) → TimeoutError.
    n = 4  # < _MAX_CONCURRENT_SUBJECTS, so all can be in-flight at once
    entered = 0
    all_entered = asyncio.Event()

    class _BarrierReasoner:
        async def __call__(self, context_json: str) -> RuleJudgmentResult:
            nonlocal entered
            entered += 1
            if entered == n:
                all_entered.set()
            await asyncio.wait_for(
                all_entered.wait(), timeout=5
            )  # concurrent → set; sequential → hang
            return RuleJudgmentResult(RuleJudgment("yes", 0.8, "ok"), 1, 1, "stub", False)

    snap = _snapshot({f"d{i}": {"x.flag": _flag(str(i))} for i in range(n)})
    evals = await evaluate_judgment_rule(
        _SPEC, snap, reasoner=_BarrierReasoner(), confidence_floor=0.5
    )
    assert [e.evaluation.subject_id for e in evals] == [
        f"d{i}" for i in range(n)
    ]  # order preserved


async def test_evaluate_oc2_fails_loud_when_not_exactly_one_evaluation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # evaluate_oc2 preserves the single-subject signature by indexing [0]; a mis-edited enumeration
    # that yields != 1 must fail LOUD, never IndexError or silently drop verdicts.
    from app.verification.rule_engine import oc2

    async def _fake(*_a: object, **_k: object) -> list[object]:
        return []  # simulate an enumeration that produced zero subjects

    monkeypatch.setattr(oc2, "evaluate_judgment_rule", _fake)
    with pytest.raises(ValueError, match="exactly one"):
        await oc2.evaluate_oc2(_snapshot({"d1": {"x.flag": _flag("a")}}))


# --------------------------------------------------------------------------- #
# LP-644 §1 review — the rules pass is an AI stage, and it is measured like one
# --------------------------------------------------------------------------- #


async def test_each_subjects_call_is_recorded_into_the_stage_metrics() -> None:
    """LP-644's table calls the rule engine deterministic and gives it no row. It is deterministic in
    what it may DECIDE from (ADR: AI for perception only), not in whether it calls the model — this
    evaluator awaits one call per SUBJECT. Unrecorded, that waiting was reported as `non_ai_seconds`,
    the figure the ticket uses to decide whether the rest of it is worth building.
    """
    from app.ai.stage_metrics import StageMetrics

    metrics = StageMetrics()
    snap = _snapshot({"d1": {"x.flag": _flag("a")}, "d2": {"x.flag": _flag("b")}})

    await evaluate_judgment_rule(
        _SPEC, snap, reasoner=_Reasoner("no"), confidence_floor=0.5, metrics=metrics
    )

    assert metrics.calls == 2, "one call per subject, the same count the stub sees"
    assert metrics.input_tokens == 2 and metrics.output_tokens == 2
    assert metrics.latency_seconds > 0


async def test_a_gated_subject_and_a_failed_call_are_not_counted_as_calls() -> None:
    """The same two exclusions every other stage makes: a subject gated BEFORE the AI never called,
    and a failed call has no tokens to attribute — counting it would deflate the per-call mean
    exactly when the backend is degraded.
    """
    from app.ai.stage_metrics import StageMetrics

    gated = StageMetrics()
    await evaluate_judgment_rule(
        _SPEC,
        _snapshot({"d1": {}, "d2": {"x.flag": _flag("b")}}),
        reasoner=_Reasoner("yes"),
        confidence_floor=0.5,
        metrics=gated,
    )
    assert gated.calls == 1  # d1 never reached the model

    failed = StageMetrics()
    await evaluate_judgment_rule(
        _SPEC,
        _snapshot({"d1": {"x.flag": _flag("a")}}),
        reasoner=_Reasoner("yes", raise_ai=True),
        confidence_floor=0.5,
        metrics=failed,
    )
    assert failed.calls == 0 and failed.latency_seconds == 0.0
