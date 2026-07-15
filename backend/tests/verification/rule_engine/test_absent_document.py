"""Declared absent-document resolution (LP-330) — fixing ID-7's live false-green.

LP-329 resolved EVERY zero-subject rule to not_applicable. That is correct for ID-9 (a POA rule when no
POA was used — genuinely irrelevant) but WRONG for ID-7 (a purchase with NO title commitment — title IS
relevant; the document is MISSING = lost visibility = couldnt_check, §8 Tab 1, BLOCKS). The expectation
is now DECLARED per rule (`applicability_expected`); the SAME mechanism gives ID-7 and ID-9 OPPOSITE
answers on an absent document.
"""

from __future__ import annotations

from datetime import UTC, datetime
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


def _tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=0.9,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _snapshot(docs: list[tuple[str, str, dict[str, Tag]]]) -> Snapshot:
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
        self.calls = 0
        self.value = value

    async def __call__(self, _ctx: str) -> RuleJudgmentResult:
        self.calls += 1
        return RuleJudgmentResult(RuleJudgment(self.value, 0.9, "x"), 1, 1, "stub", False)


# --------------------------------------------------------------------------- #
# THE FIX — a file with NO title commitment → ID-7 couldnt_check (Tab 1), not not_applicable
# --------------------------------------------------------------------------- #
def test_purchase_with_no_title_commitment_is_couldnt_check_the_false_green_fix() -> None:
    # A file whose documents are a paystub + a W-2, NO title commitment. Title IS expected → its
    # confident absence is a GAP → couldnt_check. (Before LP-330 this was not_applicable — a
    # false-green that never blocked.)
    results = evaluate_deterministic_rule(
        load_rule_spec("ID-7"), _snapshot([("pay", "paystub", {}), ("w2", "w2", {})])
    )
    assert [r.verdict for r in results] == [Verdict.COULDNT_CHECK]
    r = results[0]
    assert r.verdict is not Verdict.NOT_APPLICABLE  # the fix — NOT swept into the doesn't-block tab
    assert (
        "title_commitment" in r.reasoning and "missing" in r.reasoning
    )  # names the missing document
    assert r.subject_id == "missing:title_commitment"  # stable identity for reconciliation


def test_no_documents_at_all_is_also_couldnt_check_for_id7() -> None:
    (r,) = evaluate_deterministic_rule(load_rule_spec("ID-7"), _snapshot([]))
    assert r.verdict is Verdict.COULDNT_CHECK
    assert "title_commitment" in r.reasoning


def test_documents_section_absent_does_not_mint_a_missing_document_finding() -> None:
    # LP-330 review: a DEGRADED documents section ("couldn't look") is NOT "confidently absent". ID-7
    # must NOT claim the title is missing — the missing SECTION is recorded by the orchestrator's
    # degradation scan, not mis-attributed here. (An empty-but-PRESENT section IS missing → the test
    # above.) So a degraded run emits NOTHING for ID-7, never a spurious "missing:title" couldnt_check.
    degraded = _snapshot([]).model_copy(
        update={"documents": DocumentsSection.failed("build failed")}
    )
    assert evaluate_deterministic_rule(load_rule_spec("ID-7"), degraded) == []


# --------------------------------------------------------------------------- #
# THE CONTRAST — ID-9 (POA not expected) → not_applicable, UNCHANGED. Same mechanism, opposite answer.
# --------------------------------------------------------------------------- #
async def test_no_poa_is_not_applicable_unchanged() -> None:
    stub = _Reasoner("yes")
    evals = await evaluate_judgment_rule(
        load_rule_spec("ID-9"), _snapshot([("pay", "paystub", {}), ("w2", "w2", {})]), reasoner=stub
    )
    # Every subject is out-of-scope and POA is NOT expected → not_applicable (Tab 4), never
    # couldnt_check. No missing-document finding.
    assert all(e.evaluation.verdict is Verdict.NOT_APPLICABLE for e in evals)
    assert not any(e.evaluation.subject_id.startswith("missing:") for e in evals)
    assert stub.calls == 0


def test_id7_and_id9_resolve_an_absent_document_differently_from_one_mechanism() -> None:
    docs = [("pay", "paystub", {})]  # no title, no POA
    id7 = evaluate_deterministic_rule(load_rule_spec("ID-7"), _snapshot(docs))
    assert id7[0].verdict is Verdict.COULDNT_CHECK  # title expected → gap
    # (ID-9's not_applicable is proven in the async test above.) The declaration — not the code —
    # is the only difference.
    assert load_rule_spec("ID-7").deterministic.applicability_expected is True
    assert load_rule_spec("ID-9").judgment.applicability_expected is False


# --------------------------------------------------------------------------- #
# The three §8 cases stay DISTINCT — the fix does not blur present-but-unreadable with absent
# --------------------------------------------------------------------------- #
def test_present_but_unreadable_is_a_different_couldnt_check_than_absent() -> None:
    absent = evaluate_deterministic_rule(
        load_rule_spec("ID-7"), _snapshot([("pay", "paystub", {})])
    )
    present_unreadable = evaluate_deterministic_rule(
        load_rule_spec("ID-7"),
        _snapshot(
            [("title", "title_commitment", {"id.title_vesting_consistent": _tag("unknown")})]
        ),
    )
    assert absent[0].verdict is present_unreadable[0].verdict is Verdict.COULDNT_CHECK
    # Both block, but for DIFFERENT reasons — the fix keeps them distinct.
    assert "missing" in absent[0].reasoning  # the document is absent
    assert "unknown" in present_unreadable[0].reasoning  # the document is present but unreadable
    assert absent[0].reasoning != present_unreadable[0].reasoning


def test_a_title_present_means_no_missing_document_finding() -> None:
    # When the expected document EXISTS (even if in-scope subjects also include out-of-scope docs), the
    # missing-document couldnt_check must NOT fire — the document is there.
    results = evaluate_deterministic_rule(
        load_rule_spec("ID-7"),
        _snapshot(
            [
                ("pay", "paystub", {}),
                ("title", "title_commitment", {"id.title_vesting_consistent": _tag("no")}),
            ]
        ),
    )
    assert not any(r.subject_id.startswith("missing:") for r in results)
    assert any(r.verdict is Verdict.FIRED for r in results)  # the title was evaluated


# --------------------------------------------------------------------------- #
# EQUIVALENCE — a rule that does NOT declare the expectation behaves exactly as LP-329
# --------------------------------------------------------------------------- #
def test_default_no_declaration_is_lp329_not_applicable() -> None:
    # ID-6 (loan, no applicability) and any spec without applicability_expected are unchanged. A
    # synthetic per_document rule with applicability but WITHOUT expected → absent = not_applicable.
    from app.verification.rules.specs import RuleSpec

    spec = RuleSpec.model_validate(
        {
            "rule_id": "ID-7",  # reuse ID-7's kinds row; a distinct synthetic body (expected omitted)
            "name": "synthetic scoped rule (no expectation)",
            "category": "Identity",
            "kind": "structural",
            "numeric_check": False,
            "criteria": "scoped, not expected",
            "applicability": {"scope": "title docs", "trigger": "per title doc"},
            "required_inputs": [
                {"name": "x", "snapshot_path": 'tags[<doc>]["x.flag"]', "description": "x"}
            ],
            "reference_values": {"priya_validated": False, "threshold_needs_signoff": False},
            "subject_enumeration": "per_document",
            "subject_key_fields": ["document"],
            "evidence_required": "x",
            "guideline_reference": "n/a — synthetic",
            "spec_version": 1,
            "deterministic": {
                "load_bearing_tags": ["x.flag"],
                "gated_tags": ["x.flag"],
                "applicability": {
                    "tag": "document.document_type",
                    "op": "eq",
                    "value": "title_commitment",
                },
                # applicability_expected omitted → default False → LP-329 behavior
                "outcomes": [
                    {
                        "verdict": "fired",
                        "when_tags": [{"tag": "x.flag", "op": "ne", "value": "ok"}],
                        "reasoning": "bad",
                    },
                    {"verdict": "satisfied", "default": True, "reasoning": "ok"},
                ],
            },
        }
    )
    (r,) = evaluate_deterministic_rule(spec, _snapshot([("pay", "paystub", {})]))
    assert r.verdict is Verdict.NOT_APPLICABLE  # no expectation → LP-329 default, unchanged


def test_expected_without_applicability_fails_loud_at_load() -> None:
    from app.verification.rules.specs import RuleSpec

    bad = {
        "rule_id": "ID-6",
        "name": "bad",
        "category": "Identity",
        "kind": "structural",
        "numeric_check": False,
        "criteria": "x",
        "applicability": {"scope": "s", "trigger": "t"},
        "required_inputs": [{"name": "x", "snapshot_path": "p", "description": "d"}],
        "reference_values": {"priya_validated": False, "threshold_needs_signoff": False},
        "subject_enumeration": "loan",
        "subject_key_fields": ["loan"],
        "evidence_required": "x",
        "guideline_reference": "n/a",
        "spec_version": 1,
        "deterministic": {
            "load_bearing_tags": ["x.flag"],
            "gated_tags": ["x.flag"],
            "applicability_expected": True,  # but NO applicability predicate
            "outcomes": [{"verdict": "satisfied", "default": True, "reasoning": "ok"}],
        },
    }
    with pytest.raises(ValueError, match="requires an `applicability`"):
        RuleSpec.model_validate(bad)


def test_expected_on_a_non_document_applicability_fails_loud_at_load() -> None:
    # LP-330 review: applicability_expected declares a MISSING DOCUMENT is a gap, so the predicate must
    # be the document-type tag — else the missing-document reason frames a non-document scope as a
    # missing document.
    from app.verification.rules.specs import RuleSpec

    bad = {
        "rule_id": "ID-7",  # reuse ID-7's kinds row; a distinct synthetic body
        "name": "bad",
        "category": "Identity",
        "kind": "structural",
        "numeric_check": False,
        "criteria": "x",
        "applicability": {"scope": "s", "trigger": "t"},
        "required_inputs": [{"name": "x", "snapshot_path": "p", "description": "d"}],
        "reference_values": {"priya_validated": False, "threshold_needs_signoff": False},
        "subject_enumeration": "per_document",
        "subject_key_fields": ["document"],
        "evidence_required": "x",
        "guideline_reference": "n/a",
        "spec_version": 1,
        "deterministic": {
            "load_bearing_tags": ["x.flag"],
            "gated_tags": ["x.flag"],
            "applicability": {"tag": "some.other.tag", "op": "eq", "value": "v"},  # not doc-type
            "applicability_expected": True,
            "outcomes": [{"verdict": "satisfied", "default": True, "reasoning": "ok"}],
        },
    }
    with pytest.raises(ValueError, match="requires a document-type applicability"):
        RuleSpec.model_validate(bad)
