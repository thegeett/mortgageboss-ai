"""The cross-source CONSISTENCY primitive (LP-325) — the third rule shape, as DATA.

ID-2 (SSN, EXACT) and ID-4 (address, FUZZY) are re-expressed as specs and run through ONE generic
evaluator — ZERO per-rule Python. These tests pin the design: the exact bookend never calls AI (the
cost property), the AI judges only the differing residue (never the file), absent≠disagreeing, a
single source is not agreement (<2 → couldnt_check), the mailing-vs-residence filter, and the fuzzy
leg's ratification armor.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.ai.client import AIClientError
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.consistency import evaluate_consistency_rule
from app.verification.rule_engine.registry import evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import RuleSpec, load_rule_spec
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

pytestmark = pytest.mark.anyio

_BORROWER = uuid4()
_OTHER = uuid4()


# --------------------------------------------------------------------------- #
# Snapshot fixtures — documents belonging to a borrower, each carrying source-level tags
# --------------------------------------------------------------------------- #
def _tag(
    value: object,
    *,
    confidence: float | None = None,
    produced_by: TagProducedBy = TagProducedBy.PARSED,
) -> Tag:
    return Tag(
        value=value,
        confidence=confidence,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=produced_by,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _snapshot(sources: list[tuple[str, dict[str, Tag]]], *, borrower=_BORROWER) -> Snapshot:
    """A snapshot with one document per (source_id, tags) pair, all belonging to ``borrower``."""
    entries = [
        DocumentEntry(
            content_id=source_id,
            document_type="doc",
            belongs_to=(BorrowerRef(borrower_id=borrower, name="Sam Borrower"),),
            fields={},
        )
        for source_id, _ in sources
    ]
    by_subject = dict(sources)
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        documents=DocumentsSection.present(entries),
        tags=TagsSection.present(by_subject),
    )


class _Reasoner:
    """A keyless stub for the fuzzy judge — records whether it was called + the exact context given."""

    def __init__(
        self,
        value: str,
        *,
        confidence: float | None = 0.9,
        truncated: bool = False,
        raise_ai: bool = False,
    ):
        self.value = value
        self.confidence = confidence
        self.truncated = truncated
        self.raise_ai = raise_ai
        self.calls = 0
        self.context: str | None = None

    async def __call__(self, context_json: str) -> RuleJudgmentResult:
        self.calls += 1
        self.context = context_json
        if self.raise_ai:
            raise AIClientError("boom")
        judgment = (
            None
            if self.value == "__malformed__"
            else RuleJudgment(self.value, self.confidence, "because")
        )
        return RuleJudgmentResult(
            judgment, input_tokens=1, output_tokens=1, model="stub", truncated=self.truncated
        )


def _ssn(v: str, **kw) -> dict[str, Tag]:
    return {"id.ssn_hash": _tag(v, **kw)}


def _addr(v: str, kind: str = "residence", **kw) -> dict[str, Tag]:
    return {
        "id.address_normalized": _tag(v, produced_by=TagProducedBy.AI, **kw),
        "id.current_address_type": _tag(kind, produced_by=TagProducedBy.AI),
    }


async def _eval_id2(snapshot: Snapshot, reasoner=None):
    return await evaluate_consistency_rule(load_rule_spec("ID-2"), snapshot, reasoner=reasoner)


async def _eval_id4(snapshot: Snapshot, reasoner=None):
    return await evaluate_consistency_rule(load_rule_spec("ID-4"), snapshot, reasoner=reasoner)


# --------------------------------------------------------------------------- #
# ID-2 — SSN, EXACT (never calls AI)
# --------------------------------------------------------------------------- #
async def test_id2_identical_hashes_satisfied_no_ai() -> None:
    stub = _Reasoner("agree")
    results = await _eval_id2(
        _snapshot([("dl", _ssn("H")), ("cr", _ssn("H")), ("app", _ssn("H"))]), reasoner=stub
    )
    assert [r.verdict for r in results] == [Verdict.SATISFIED]
    assert stub.calls == 0  # an exact rule NEVER calls the AI
    assert results[0].ratification_pending is False
    assert "3 sources" in results[0].reasoning


async def test_id2_differing_hashes_fired_no_ai() -> None:
    stub = _Reasoner("agree")
    results = await _eval_id2(_snapshot([("app", _ssn("H1")), ("cr", _ssn("H2"))]), reasoner=stub)
    assert [r.verdict for r in results] == [Verdict.FIRED]
    assert stub.calls == 0
    # provenance names BOTH sources so a human sees WHERE it disagreed.
    assert "app" in results[0].reasoning and "cr" in results[0].reasoning
    assert {t.source_facts[0] for t in results[0].load_bearing_tags} == {"app", "cr"}


async def test_id2_null_hash_source_is_absent_not_a_false_match() -> None:
    # One source lacks the hash entirely (ABSENT) → excluded; only one real instance remains → <2.
    results = await _eval_id2(_snapshot([("app", _ssn("H")), ("dl", {})]))
    assert [r.verdict for r in results] == [Verdict.COULDNT_CHECK]
    assert "nothing to compare" in results[0].reasoning


async def test_id2_single_source_is_not_agreement() -> None:
    results = await _eval_id2(_snapshot([("app", _ssn("H"))]))
    assert results[0].verdict is Verdict.COULDNT_CHECK  # a single source is NOT "satisfied"


async def test_id2_unknown_value_couldnt_check_distinct() -> None:
    results = await _eval_id2(_snapshot([("app", _ssn("unknown")), ("cr", _ssn("H"))]))
    assert results[0].verdict is Verdict.COULDNT_CHECK
    assert "unknown" in results[0].reasoning  # distinct reason — never "agrees"/"disagrees"


# --------------------------------------------------------------------------- #
# ID-4 — address, FUZZY (exact bookend, then AI on the residue only)
# --------------------------------------------------------------------------- #
async def test_id4_identical_addresses_satisfied_no_ai() -> None:
    # The cost property: the exact bookend short-circuits — the AI is NOT invoked on a clean match.
    stub = _Reasoner("agree")
    results = await _eval_id4(
        _snapshot([("app", _addr("123 Main St")), ("dl", _addr("123 Main St"))]), reasoner=stub
    )
    assert [r.verdict for r in results] == [Verdict.SATISFIED]
    assert stub.calls == 0
    assert results[0].ratification_pending is False


async def test_id4_benign_variance_ai_agrees_satisfied_ratification_pending() -> None:
    stub = _Reasoner("agree", confidence=0.88)
    snap = _snapshot(
        [("app", _addr("123 N Main St Apt 4")), ("dl", _addr("123 North Main Street #4"))]
    )
    results = await _eval_id4(snap, reasoner=stub)
    assert [r.verdict for r in results] == [Verdict.SATISFIED]
    assert stub.calls == 1  # exact differed → the AI judged the residue
    assert results[0].ratification_pending is True  # the AI made the call → LP-319 armor
    assert results[0].verdict_confidence == 0.88


async def test_id4_real_discrepancy_ai_disagrees_fired_with_provenance() -> None:
    stub = _Reasoner("disagree")
    snap = _snapshot([("app", _addr("123 Main St")), ("dl", _addr("500 Oak Ave"))])
    results = await _eval_id4(snap, reasoner=stub)
    assert [r.verdict for r in results] == [Verdict.FIRED]
    assert results[0].ratification_pending is True
    # provenance names BOTH values AND both sources.
    lb = {(t.value, t.source_facts[0]) for t in results[0].load_bearing_tags}
    assert lb == {("123 Main St", "app"), ("500 Oak Ave", "dl")}


async def test_id4_bounded_ai_context_is_only_the_differing_values() -> None:
    stub = _Reasoner("agree")
    snap = _snapshot([("app", _addr("123 N Main St")), ("dl", _addr("123 North Main Street"))])
    await _eval_id4(snap, reasoner=stub)
    assert stub.context is not None
    # ONLY the differing values + their sources — never the whole file.
    assert "123 N Main St" in stub.context and "123 North Main Street" in stub.context
    assert "app" in stub.context and "dl" in stub.context
    assert "belongs_to" not in stub.context and "document_type" not in stub.context


async def test_id4_mailing_only_is_couldnt_check_not_a_discrepancy() -> None:
    # THE ABSENT≠EMPTY TRAP: the borrower's only residence-typed source is one; the other is a mailing
    # address → filtered out → <2 residence instances → couldnt_check, NOT a discrepancy/satisfied.
    stub = _Reasoner("disagree")
    snap = _snapshot(
        [("app", _addr("123 Main St", "residence")), ("dl", _addr("PO Box 9", "mailing"))]
    )
    results = await _eval_id4(snap, reasoner=stub)
    assert [r.verdict for r in results] == [Verdict.COULDNT_CHECK]
    assert stub.calls == 0
    assert "residence" in results[0].reasoning  # names WHY it couldn't compare


async def test_id4_ai_failure_is_couldnt_check_never_a_defaulted_agree() -> None:
    stub = _Reasoner("agree", raise_ai=True)
    snap = _snapshot([("app", _addr("123 N Main St")), ("dl", _addr("123 North Main Street"))])
    results = await _eval_id4(snap, reasoner=stub)
    assert results[0].verdict is Verdict.COULDNT_CHECK
    assert "AI call failed" in results[0].reasoning
    assert results[0].ratification_pending is False


async def test_id4_truncated_is_couldnt_check() -> None:
    stub = _Reasoner("agree", truncated=True)
    snap = _snapshot([("app", _addr("123 N Main St")), ("dl", _addr("123 North Main Street"))])
    results = await _eval_id4(snap, reasoner=stub)
    assert results[0].verdict is Verdict.COULDNT_CHECK
    assert "truncated" in results[0].reasoning


async def test_id4_malformed_ai_is_cannot_tell_never_defaulted_agree() -> None:
    stub = _Reasoner("__malformed__")
    snap = _snapshot([("app", _addr("123 N Main St")), ("dl", _addr("123 North Main Street"))])
    results = await _eval_id4(snap, reasoner=stub)
    assert (
        results[0].verdict is Verdict.COULDNT_CHECK
    )  # on_cannot_tell — never a defaulted satisfied


async def test_id4_off_domain_ai_is_cannot_tell() -> None:
    stub = _Reasoner("maybe")  # not in value_domain
    snap = _snapshot([("app", _addr("123 N Main St")), ("dl", _addr("123 North Main Street"))])
    results = await _eval_id4(snap, reasoner=stub)
    assert results[0].verdict is Verdict.COULDNT_CHECK


async def test_absent_source_is_excluded_not_counted_as_mismatch() -> None:
    # Three sources agree; a fourth belongs to the borrower but lacks the fact → excluded, still agree.
    stub = _Reasoner("agree")
    snap = _snapshot([("a", _addr("123 Main St")), ("b", _addr("123 Main St")), ("c", {})])
    results = await _eval_id4(snap, reasoner=stub)
    assert results[0].verdict is Verdict.SATISFIED
    assert stub.calls == 0


async def test_per_borrower_evaluates_each_borrower_independently() -> None:
    # Two borrowers; one agrees, one disagrees — two independent verdicts.
    b1 = [("a", _ssn("H")), ("b", _ssn("H"))]
    entries = [
        DocumentEntry(
            content_id=sid,
            document_type="doc",
            belongs_to=(BorrowerRef(borrower_id=_BORROWER, name="Sam"),),
            fields={},
        )
        for sid, _ in b1
    ] + [
        DocumentEntry(
            content_id="c",
            document_type="doc",
            belongs_to=(BorrowerRef(borrower_id=_OTHER, name="Pat"),),
            fields={},
        ),
        DocumentEntry(
            content_id="d",
            document_type="doc",
            belongs_to=(BorrowerRef(borrower_id=_OTHER, name="Pat"),),
            fields={},
        ),
    ]
    by_subject = {"a": _ssn("H"), "b": _ssn("H"), "c": _ssn("X1"), "d": _ssn("X2")}
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        documents=DocumentsSection.present(entries),
        tags=TagsSection.present(by_subject),
    )
    results = await _eval_id2(snap)
    by_subject_verdict = {r.subject_id: r.verdict for r in results}
    assert by_subject_verdict[str(_BORROWER)] is Verdict.SATISFIED
    assert by_subject_verdict[str(_OTHER)] is Verdict.FIRED


# --------------------------------------------------------------------------- #
# DATA-ONLY — a brand-new consistency rule runs from a spec, and the registry dispatches by block
# --------------------------------------------------------------------------- #
_SYNTH_SPEC = {
    "rule_id": "ID-2",  # reuse ID-2's kinds row for the CSV cross-check; body is a distinct synthetic
    "name": "synthetic consistency rule",
    "category": "Identity",
    "kind": "structural",
    "numeric_check": False,
    "criteria": "a fact must agree across sources",
    "applicability": {"scope": "all borrowers", "trigger": "per borrower"},
    "required_inputs": [
        {"name": "f", "snapshot_path": 'tags[...]["x.fact"]', "description": "the fact"}
    ],
    "reference_values": {"priya_validated": False, "threshold_needs_signoff": False},
    "subject_enumeration": "per_borrower",
    "subject_key_fields": ["borrower"],
    "evidence_required": "the fact per source",
    "guideline_reference": "n/a — synthetic",
    "spec_version": 1,
    "consistency": {
        "subject": "per_borrower",
        "gather_tag": "x.fact",
        "source_scope": "borrower_documents",
        "compare_mode": "exact",
        "normalization": ["casefold", "strip"],
        "on_agree": {"verdict": "satisfied", "reasoning": "{count} sources agree"},
        "on_disagree": {"verdict": "fired", "reasoning": "differ: {values}"},
        "on_cannot_tell": {"verdict": "couldnt_check", "reasoning": "cannot compare"},
    },
}


async def test_a_new_consistency_rule_runs_from_a_spec_only() -> None:
    spec = RuleSpec.model_validate(_SYNTH_SPEC)
    snap = _snapshot(
        [("a", {"x.fact": _tag("YES")}), ("b", {"x.fact": _tag("yes")})]
    )  # casefold → agree
    results = await evaluate_consistency_rule(spec, snap)
    assert [r.verdict for r in results] == [Verdict.SATISFIED]


async def test_registry_dispatches_consistency_by_block() -> None:
    stub = _Reasoner("agree")
    snap = _snapshot([("app", _addr("123 N Main St")), ("dl", _addr("123 North Main Street"))])
    results, judgment_tags = await evaluate_rules(
        snap, consistency_reasoners={"ID-4": stub}, rule_ids=("ID-2", "ID-4"), confidence_floor=0.5
    )
    rule_ids = {r.rule_id for r in results}
    assert rule_ids == {"ID-2", "ID-4"}  # both dispatched by their consistency block, not by name
    assert judgment_tags == {}  # a consistency rule produces no rule_judgment tag
    # ID-4 saw the address residue; ID-2 saw no ssn tags → couldnt_check (fail-closed, not a crash).
    id4 = next(r for r in results if r.rule_id == "ID-4")
    assert id4.verdict is Verdict.SATISFIED
