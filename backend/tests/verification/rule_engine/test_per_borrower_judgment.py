"""Borrower-keyed facts for per-borrower judgment (LP-331, GAP-D).

The `per_borrower` enumerator now ASSEMBLES each borrower's subject map from the borrower's OWN facts
(borrower-keyed) + the loan-level SHARED facts (each fact from its ONE declared keying — no
duplication). A consistency rule still IGNORES this map and gathers document-keyed facts itself
(equivalence), so ID-1/2/3/4 and LP-326's document keying are untouched. ID-8 (citizenship eligibility)
is the proof: a per-borrower judgment now reasons over THAT borrower's facts instead of an empty map.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.consistency import evaluate_consistency_rule
from app.verification.rule_engine.judgment import evaluate_judgment_rule
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

_A = uuid4()
_B = uuid4()


def _tag(value: str, *, conf: float | None = 0.9, by: TagProducedBy = TagProducedBy.PARSED) -> Tag:
    return Tag(
        value=value,
        confidence=conf,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=by,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _snapshot(
    *,
    borrowers: list,
    borrower_tags: dict[str, dict[str, Tag]],
    loan_tags: dict[str, Tag] | None = None,
) -> Snapshot:
    """One document per borrower (so per_borrower enumerates them via belongs_to); borrower-keyed tags
    under by_subject[str(borrower_id)]; loan-level tags under by_subject['loan']."""
    entries = [
        DocumentEntry(
            content_id=f"doc_{i}",
            document_type="doc",
            belongs_to=(BorrowerRef(borrower_id=b, name="X"),),
        )
        for i, b in enumerate(borrowers)
    ]
    by_subject = dict(borrower_tags)
    if loan_tags:
        by_subject["loan"] = loan_tags
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present(entries),
        tags=TagsSection.present(by_subject),
    )


class _Reasoner:
    def __init__(self, value: str = "yes", *, raise_ai: bool = False) -> None:
        self.value = value
        self.raise_ai = raise_ai
        self.calls = 0
        self.contexts: list[str] = []

    async def __call__(self, context_json: str) -> RuleJudgmentResult:
        self.calls += 1
        self.contexts.append(context_json)
        if self.raise_ai:
            from app.ai.client import AIClientError

            raise AIClientError("boom")
        return RuleJudgmentResult(RuleJudgment(self.value, 0.9, "x"), 1, 1, "stub", False)


async def _id8(snapshot: Snapshot, reasoner):
    return await evaluate_judgment_rule(load_rule_spec("ID-8"), snapshot, reasoner=reasoner)


# --------------------------------------------------------------------------- #
# THE FIX — a per-borrower judgment reasons over EACH borrower's own facts, not an empty map
# --------------------------------------------------------------------------- #
async def test_two_borrowers_two_verdicts_each_over_its_own_facts() -> None:
    stub = _Reasoner("yes")
    snap = _snapshot(
        borrowers=[_A, _B],
        borrower_tags={
            str(_A): {"id.citizenship": _tag("us_citizen")},
            str(_B): {"id.citizenship": _tag("non_permanent")},
        },
        loan_tags={"program.type": _tag("conventional")},
    )
    evals = await _id8(snap, stub)
    assert {e.evaluation.subject_id for e in evals} == {
        str(_A),
        str(_B),
    }  # one verdict PER borrower
    assert all(
        e.evaluation.verdict is Verdict.NEEDS_REVIEW for e in evals
    )  # a judgment never auto-fires
    assert all(e.evaluation.ratification_pending for e in evals)  # LP-319/327 armor — no auto-ship
    assert all(e.judgment_tag is not None for e in evals)
    assert stub.calls == 2  # the AI judged each borrower (its own facts were present, not empty)


async def test_borrower_isolation_no_cross_borrower_leak() -> None:
    stub = _Reasoner("yes")
    snap = _snapshot(
        borrowers=[_A, _B],
        borrower_tags={
            str(_A): {"id.citizenship": _tag("us_citizen")},
            str(_B): {"id.citizenship": _tag("non_permanent")},
        },
        loan_tags={"program.type": _tag("conventional")},
    )
    await _id8(snap, stub)
    ctx_by_citizenship = {}
    for c in stub.contexts:
        ctx_by_citizenship[json.loads(c)["tags"]["id.citizenship"]["value"]] = c
    # Each borrower's prompt has ITS OWN citizenship + the SHARED loan program — never the other
    # borrower's citizenship.
    assert "non_permanent" not in ctx_by_citizenship["us_citizen"]  # A's context has no B fact
    assert "us_citizen" not in ctx_by_citizenship["non_permanent"]
    assert all("conventional" in c for c in stub.contexts)  # loan program shared into BOTH contexts


async def test_loan_level_fact_is_shared_into_each_borrower_context() -> None:
    stub = _Reasoner("yes")
    snap = _snapshot(
        borrowers=[_A],
        borrower_tags={str(_A): {"id.citizenship": _tag("us_citizen")}},
        loan_tags={"program.type": _tag("fha")},
    )
    (ev,) = await _id8(snap, stub)
    # The loan-level program.type is present in the borrower's load-bearing provenance (LP-331 merge).
    lb = {t.tag_id: t.value for t in ev.evaluation.load_bearing_tags}
    assert lb.get("program.type") == "fha" and lb.get("id.citizenship") == "us_citizen"


# --------------------------------------------------------------------------- #
# PER-SUBJECT FAIL-CLOSED + GATE-BEFORE-AI + ARMOR
# --------------------------------------------------------------------------- #
async def test_one_borrower_missing_citizenship_couldnt_check_the_other_still_evaluates() -> None:
    stub = _Reasoner("yes")
    snap = _snapshot(
        borrowers=[_A, _B],
        borrower_tags={
            str(_A): {},  # A has no citizenship fact → gated
            str(_B): {"id.citizenship": _tag("us_citizen")},
        },
        loan_tags={"program.type": _tag("conventional")},
    )
    evals = {e.evaluation.subject_id: e for e in await _id8(snap, stub)}
    assert (
        evals[str(_A)].evaluation.verdict is Verdict.COULDNT_CHECK
    )  # A fail-closed (missing input)
    assert (
        "citizenship" in evals[str(_A)].evaluation.reasoning
    )  # LP-376-C: the fact, not the tag id
    assert evals[str(_A)].judgment_tag is None  # gate-before-AI: no tag on a gated subject
    assert evals[str(_B)].evaluation.verdict is Verdict.NEEDS_REVIEW  # B still evaluates
    assert stub.calls == 1  # the AI was NOT called for the gated borrower A


async def test_one_borrower_ai_failure_degrades_only_that_borrower() -> None:
    stub = _Reasoner(raise_ai=True)
    snap = _snapshot(
        borrowers=[_A, _B],
        borrower_tags={
            str(_A): {"id.citizenship": _tag("us_citizen")},
            str(_B): {"id.citizenship": _tag("non_permanent")},
        },
        loan_tags={"program.type": _tag("conventional")},
    )
    evals = await _id8(snap, stub)
    # BOTH AI calls fail independently → each couldnt_check (not a wholesale rule failure).
    assert [e.evaluation.verdict for e in evals] == [Verdict.COULDNT_CHECK, Verdict.COULDNT_CHECK]


# --------------------------------------------------------------------------- #
# EQUIVALENCE — consistency IGNORES the now-populated per_borrower map (ID-4 residence filter intact)
# --------------------------------------------------------------------------- #
async def test_consistency_unchanged_by_the_populated_map_id4_residence_filter() -> None:
    async def _match(_ctx: str) -> RuleJudgmentResult:
        return RuleJudgmentResult(RuleJudgment("agree", 0.9, "same"), 1, 1, "stub", False)

    # Two residence addresses for one borrower + a borrower-keyed tag that would be in the per_borrower
    # map — consistency gathers the DOCUMENT-keyed addresses and ignores the borrower map entirely.
    docs = [
        DocumentEntry(
            content_id="app",
            document_type="doc",
            belongs_to=(BorrowerRef(borrower_id=_A, name="X"),),
        ),
        DocumentEntry(
            content_id="dl",
            document_type="doc",
            belongs_to=(BorrowerRef(borrower_id=_A, name="X"),),
        ),
    ]
    by_subject = {
        "app": {
            "id.address_normalized": _tag("123 N Main St", by=TagProducedBy.AI),
            "id.current_address_type": _tag("residence", by=TagProducedBy.AI),
        },
        "dl": {
            "id.address_normalized": _tag("123 North Main Street", by=TagProducedBy.AI),
            "id.current_address_type": _tag("residence", by=TagProducedBy.AI),
        },
        str(_A): {
            "id.citizenship": _tag("us_citizen")
        },  # a borrower-keyed tag — consistency must ignore it
    }
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present(docs),
        tags=TagsSection.present(by_subject),
    )
    results = await evaluate_consistency_rule(load_rule_spec("ID-4"), snap, reasoner=_match)
    assert [r.verdict for r in results] == [
        Verdict.SATISFIED
    ]  # residence↔residence compared, unchanged


# --------------------------------------------------------------------------- #
# DATA-ONLY — a NEW per-borrower judgment runs from a SPEC alone; no rule-id branch
# --------------------------------------------------------------------------- #
_SYNTH = {
    "rule_id": "ID-8",  # reuse ID-8's kinds row; a distinct synthetic body
    "name": "synthetic per-borrower judgment",
    "category": "Identity",
    "kind": "judgmental",
    "numeric_check": False,
    "criteria": "judge each borrower's flag",
    "applicability": {"scope": "every borrower", "trigger": "per borrower"},
    "required_inputs": [
        {"name": "f", "snapshot_path": 'tags[<bid>]["x.flag"]', "description": "f"}
    ],
    "reference_values": {"priya_validated": False, "threshold_needs_signoff": False},
    "subject_enumeration": "per_borrower",
    "subject_key_fields": ["borrower"],
    "evidence_required": "the flag",
    "guideline_reference": "n/a — synthetic",
    "spec_version": 1,
    "judgment": {
        "subject": "per_borrower",
        "load_bearing_tags": ["x.flag"],
        "reasoned_over": ["x.flag"],
        "output_tag": "x.judged",
        "value_domain": ["yes", "no", "unknown"],
        "system_prompt": "judge the flag",
    },
}


async def test_a_new_per_borrower_judgment_runs_from_a_spec_only() -> None:
    spec = RuleSpec.model_validate(_SYNTH)
    stub = _Reasoner("yes")
    snap = _snapshot(
        borrowers=[_A, _B],
        borrower_tags={str(_A): {"x.flag": _tag("a")}, str(_B): {"x.flag": _tag("b")}},
    )
    evals = await evaluate_judgment_rule(spec, snap, reasoner=stub)
    assert len(evals) == 2 and all(e.evaluation.ratification_pending for e in evals)


def test_no_rule_id_branch_in_the_enumerator() -> None:
    # The mechanism is generic — the enumerator must carry no rule-id / family BRANCH (docstring
    # mentions of "ID-8" as an example are fine; a `rule_id == "ID-8"` comparison is not).
    src = (
        Path(__file__).parents[3] / "app" / "verification" / "rule_engine" / "enumerators.py"
    ).read_text()
    for line in src.splitlines():
        code = line.split("#", 1)[0]
        assert "rule_id ==" not in code, line
        assert '== "ID-' not in code and 'startswith("ID' not in code, line
        assert "spec.rule_id" not in code, line
