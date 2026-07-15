"""Document-type applicability (LP-329, GAP-C) — a per-document rule DECLARES which document types it
applies to; out-of-scope subjects resolve to not_applicable (never couldnt_check).

THE §8 HONESTY CONTRACT is the heart of this ticket: not_applicable (scope-false — a paystub for a POA
rule) and couldnt_check (data-missing — a POA doc present but unreadable) are DIFFERENT outcomes and
must never collapse. A false 'not applicable' would hide a real gap.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.judgment import evaluate_judgment_rule
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import DocumentEntry, DocumentsSection, Snapshot, TagsSection
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

pytestmark = pytest.mark.anyio


def _tag(value: str, *, by: TagProducedBy = TagProducedBy.AI, conf: float | None = 0.9) -> Tag:
    return Tag(
        value=value,
        confidence=conf,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=by,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _snapshot(docs: list[tuple[str, str, dict[str, Tag]]]) -> Snapshot:
    """docs = [(content_id, document_type, tags)]."""
    entries = [DocumentEntry(content_id=cid, document_type=dtype) for cid, dtype, _ in docs]
    by_subject = {cid: tags for cid, _, tags in docs if tags}
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present(entries),
        tags=TagsSection.present(by_subject),
    )


class _Reasoner:
    def __init__(self, value: str = "yes") -> None:
        self.value = value
        self.calls = 0

    async def __call__(self, _ctx: str) -> RuleJudgmentResult:
        self.calls += 1
        return RuleJudgmentResult(RuleJudgment(self.value, 0.9, "x"), 1, 1, "stub", False)


async def _id9(docs, reasoner):
    return await evaluate_judgment_rule(load_rule_spec("ID-9"), _snapshot(docs), reasoner=reasoner)


def _id7(docs):
    return evaluate_deterministic_rule(load_rule_spec("ID-7"), _snapshot(docs))


# --------------------------------------------------------------------------- #
# THE §8 HONESTY CONTRACT — the same rule, over two documents, resolves DIFFERENTLY
# --------------------------------------------------------------------------- #
async def test_honesty_contract_not_applicable_never_absorbs_couldnt_check() -> None:
    stub = _Reasoner("yes")
    evals = await _id9(
        [
            ("pay", "paystub", {}),  # out of scope → not_applicable (Tab 4)
            (
                "poa",
                "power_of_attorney",
                {"id.poa_present_and_acceptable": _tag("unknown")},
            ),  # in scope, degraded → couldnt_check (Tab 1)
        ],
        stub,
    )
    by_subject = {e.evaluation.subject_id: e.evaluation for e in evals}
    assert by_subject["pay"].verdict is Verdict.NOT_APPLICABLE
    assert "does not apply" in by_subject["pay"].reasoning
    assert by_subject["poa"].verdict is Verdict.COULDNT_CHECK
    assert "unknown" in by_subject["poa"].reasoning
    # The two are DIFFERENT outcomes — the whole point.
    assert by_subject["pay"].verdict is not by_subject["poa"].verdict
    assert stub.calls == 0  # neither made an AI call (out-of-scope skips; degraded gates first)


async def test_out_of_scope_costs_nothing_no_ai_no_tag() -> None:
    stub = _Reasoner("yes")
    (ev,) = await _id9([("pay", "paystub", {})], stub)
    assert ev.evaluation.verdict is Verdict.NOT_APPLICABLE
    assert ev.judgment_tag is None  # no tag emitted for an out-of-scope subject
    assert stub.calls == 0  # no AI call


async def test_no_flood_one_poa_in_thirty_documents() -> None:
    stub = _Reasoner("yes")
    docs = [(f"pay{i}", "paystub", {}) for i in range(29)]
    docs.append(("poa", "power_of_attorney", {"id.poa_present_and_acceptable": _tag("yes")}))
    evals = await _id9(docs, stub)
    verdicts = [e.evaluation.verdict for e in evals]
    assert verdicts.count(Verdict.NOT_APPLICABLE) == 29  # the non-POA docs — NO findings, NO flood
    assert (
        verdicts.count(Verdict.COULDNT_CHECK) == 0
    )  # ZERO couldnt_check for the out-of-scope docs
    assert verdicts.count(Verdict.NEEDS_REVIEW) == 1  # the one POA judged (ratification-pending)
    assert stub.calls == 1  # the AI ran ONCE (only the in-scope POA)


async def test_absent_document_no_poa_is_all_not_applicable_not_couldnt_check() -> None:
    # A file with NO POA document → every doc is out of scope → not_applicable (visible, no vanish),
    # NEVER couldnt_check (POA is not a required document here).
    stub = _Reasoner("yes")
    evals = await _id9([("w2", "w2", {}), ("bank", "bank_statement", {})], stub)
    assert [e.evaluation.verdict for e in evals] == [Verdict.NOT_APPLICABLE, Verdict.NOT_APPLICABLE]
    assert stub.calls == 0


async def test_id9_every_verdict_ratification_pending() -> None:
    stub = _Reasoner("no")  # the POA is judged unacceptable
    (ev,) = await _id9(
        [("poa", "power_of_attorney", {"id.poa_present_and_acceptable": _tag("no")})], stub
    )
    assert ev.evaluation.verdict is Verdict.NEEDS_REVIEW  # a judgment NEVER auto-fires
    assert ev.evaluation.ratification_pending is True  # LP-319/327 armor survives the scoping
    assert ev.judgment_tag is not None and ev.judgment_tag.value == "no"


# --------------------------------------------------------------------------- #
# ID-7 — deterministic per_document, scoped to title documents
# --------------------------------------------------------------------------- #
def test_id7_title_mismatch_fires_consistent_satisfied_scoped_to_title() -> None:
    mismatch = _id7([("title", "title_commitment", {"id.title_vesting_consistent": _tag("no")})])
    assert [r.verdict for r in mismatch] == [Verdict.FIRED]

    ok = _id7([("title", "title_commitment", {"id.title_vesting_consistent": _tag("yes")})])
    assert [r.verdict for r in ok] == [Verdict.SATISFIED]

    # A non-title document ALONGSIDE a title → the paystub is scope-false → not_applicable; the title
    # evaluates (LP-329 scoping intact). (A file with NO title → couldnt_check — the LP-330 fix, tested
    # in test_absent_document.py.)
    verdicts = {
        r.subject_id: r.verdict
        for r in _id7(
            [
                ("title", "title_commitment", {"id.title_vesting_consistent": _tag("yes")}),
                ("pay", "paystub", {}),
            ]
        )
    }
    assert verdicts["pay"] is Verdict.NOT_APPLICABLE
    assert verdicts["title"] is Verdict.SATISFIED


def test_id7_title_present_but_unreadable_is_couldnt_check_not_not_applicable() -> None:
    # The title doc IS in scope; its consistency tag is "unknown" → couldnt_check (Tab 1), a REAL gap
    # — NOT not_applicable. This is the honesty contract for the deterministic path.
    (r,) = _id7([("title", "title_commitment", {"id.title_vesting_consistent": _tag("unknown")})])
    assert r.verdict is Verdict.COULDNT_CHECK


# --------------------------------------------------------------------------- #
# DATA-ONLY — no document types hardcoded in the evaluators
# --------------------------------------------------------------------------- #
def test_no_document_types_hardcoded_in_the_evaluators() -> None:
    engine = Path(__file__).parents[3] / "app" / "verification" / "rule_engine"
    for name in ("judgment.py", "deterministic.py", "applicability.py"):
        src = (engine / name).read_text()
        assert "title_commitment" not in src, name  # the value lives ONLY in the spec (yaml)
        assert "power_of_attorney" not in src, name


# --------------------------------------------------------------------------- #
# Load-time guard: document.document_type is injected ONLY for per_document (LP-329 review) — a spec
# scoping on it under any other enumeration would silently never apply (all couldnt_check).
# --------------------------------------------------------------------------- #
def test_document_type_applicability_on_non_per_document_fails_loud() -> None:
    from app.verification.rules.specs import DOC_TYPE_TAG, RuleSpec

    spec = {
        "rule_id": "ID-7",  # reuse ID-7's kinds row; a distinct synthetic body
        "name": "misconfigured doc-type rule",
        "category": "Identity",
        "kind": "structural",
        "numeric_check": False,
        "criteria": "n/a",
        "applicability": {"scope": "n/a", "trigger": "n/a"},
        "required_inputs": [{"name": "f", "snapshot_path": 't["x"]', "description": "f"}],
        "reference_values": {"priya_validated": False, "threshold_needs_signoff": False},
        "subject_enumeration": "loan",  # WRONG — DOC_TYPE_TAG is not injected for loan subjects
        "subject_key_fields": ["loan"],
        "evidence_required": "n/a",
        "guideline_reference": "n/a — synthetic",
        "spec_version": 1,
        "deterministic": {
            "applicability": {"tag": DOC_TYPE_TAG, "op": "eq", "value": "title_commitment"},
            "load_bearing_tags": ["x.flag"],
            "gated_tags": ["x.flag"],
            "outcomes": [{"verdict": "satisfied", "default": True, "reasoning": "ok"}],
        },
    }
    with pytest.raises(ValueError, match="requires subject_enumeration: per_document"):
        RuleSpec.model_validate(spec)
