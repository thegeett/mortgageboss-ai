"""The identity family authored as DATA (LP-323-ID-B) — ID-1/ID-3/ID-6 run through the GENERIC
evaluators from their specs, with ZERO engine Python for this wave.

These are minimal fires / doesn't-fire / couldnt_check cases proving each authored rule evaluates
through the generic path (the full 13-point matrix is the -C ticket's job). Also: ID-10 → not_applicable,
and a guard that no per-rule / rule-id branch leaked into the evaluators.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.consistency import evaluate_consistency_rule
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

pytestmark = pytest.mark.anyio

_B = uuid4()


def _tag(
    value: object, *, confidence: float | None = None, by: TagProducedBy = TagProducedBy.PARSED
) -> Tag:
    return Tag(
        value=value,
        confidence=confidence,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=by,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _snapshot(
    by_subject: dict[str, dict[str, Tag]], *, borrower_docs: list[str] | None = None
) -> Snapshot:
    entries = [
        DocumentEntry(
            content_id=cid,
            document_type="doc",
            belongs_to=(BorrowerRef(borrower_id=_B, name="Sam"),)
            if borrower_docs and cid in borrower_docs
            else None,
            fields={},
        )
        for cid in by_subject
    ]
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present(entries),
        tags=TagsSection.present(by_subject),
    )


def _loan_snapshot(app_present: str | None) -> Snapshot:
    tags = (
        {"loan": {"id.app_required_fields_present": _tag(app_present, by=TagProducedBy.DERIVED)}}
        if app_present
        else {}
    )
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present([]),
        tags=TagsSection.present(tags),
    )


async def _agree(_ctx: str) -> RuleJudgmentResult:
    return RuleJudgmentResult(RuleJudgment("agree", 0.9, "same person"), 1, 1, "stub", False)


class _CountingReasoner:
    def __init__(self, value: str) -> None:
        self.value = value
        self.calls = 0

    async def __call__(self, _ctx: str) -> RuleJudgmentResult:
        self.calls += 1
        return RuleJudgmentResult(RuleJudgment(self.value, 0.9, "x"), 1, 1, "stub", False)


# --------------------------------------------------------------------------- #
# ID-1 — name (fuzzy consistency)
# --------------------------------------------------------------------------- #
async def test_id1_exact_match_satisfied_no_ai_call() -> None:
    stub = _CountingReasoner("agree")
    snap = _snapshot(
        {
            "app": {"id.name_normalized": _tag("Robert Smith", by=TagProducedBy.AI)},
            "dl": {"id.name_normalized": _tag("Robert Smith", by=TagProducedBy.AI)},
        },
        borrower_docs=["app", "dl"],
    )
    results = await evaluate_consistency_rule(load_rule_spec("ID-1"), snap, reasoner=stub)
    assert [r.verdict for r in results] == [Verdict.SATISFIED]
    assert stub.calls == 0  # the exact bookend short-circuits — the cost property


async def test_id1_nickname_variance_ai_judges_ratification_pending() -> None:
    stub = _CountingReasoner("agree")
    snap = _snapshot(
        {
            "app": {"id.name_normalized": _tag("Robert Smith", by=TagProducedBy.AI)},
            "dl": {"id.name_normalized": _tag("Bob Smith", by=TagProducedBy.AI)},
        },
        borrower_docs=["app", "dl"],
    )
    results = await evaluate_consistency_rule(load_rule_spec("ID-1"), snap, reasoner=stub)
    assert [r.verdict for r in results] == [Verdict.SATISFIED]
    assert stub.calls == 1  # exact differed → the AI judged the residue
    assert results[0].ratification_pending is True


# --------------------------------------------------------------------------- #
# ID-3 — DOB (exact consistency, declared date normalizer)
# --------------------------------------------------------------------------- #
async def test_id3_date_format_variance_normalized_satisfied_no_ai() -> None:
    snap = _snapshot(
        {"app": {"id.dob": _tag("03/04/1985")}, "dl": {"id.dob": _tag("1985-03-04")}},
        borrower_docs=["app", "dl"],
    )
    results = await evaluate_consistency_rule(load_rule_spec("ID-3"), snap)  # exact → no AI
    assert [r.verdict for r in results] == [
        Verdict.SATISFIED
    ]  # the `date` normalizer canonicalized both


async def test_id3_genuinely_different_dob_fired() -> None:
    snap = _snapshot(
        {"app": {"id.dob": _tag("1985-03-04")}, "cr": {"id.dob": _tag("1986-03-04")}},
        borrower_docs=["app", "cr"],
    )
    results = await evaluate_consistency_rule(load_rule_spec("ID-3"), snap)
    assert [r.verdict for r in results] == [Verdict.FIRED]


async def test_id3_single_source_couldnt_check() -> None:
    snap = _snapshot({"app": {"id.dob": _tag("1985-03-04")}}, borrower_docs=["app"])
    results = await evaluate_consistency_rule(load_rule_spec("ID-3"), snap)
    assert [r.verdict for r in results] == [
        Verdict.COULDNT_CHECK
    ]  # a single source is not agreement


# --------------------------------------------------------------------------- #
# ID-6 — 1003 completeness (deterministic, loan subject)
# --------------------------------------------------------------------------- #
def test_id6_complete_satisfied() -> None:
    results = evaluate_deterministic_rule(load_rule_spec("ID-6"), _loan_snapshot("complete"))
    assert [r.verdict for r in results] == [Verdict.SATISFIED]


def test_id6_incomplete_fired() -> None:
    results = evaluate_deterministic_rule(
        load_rule_spec("ID-6"), _loan_snapshot("incomplete + list")
    )
    assert [r.verdict for r in results] == [Verdict.FIRED]


def test_id6_absent_tag_couldnt_check() -> None:
    results = evaluate_deterministic_rule(load_rule_spec("ID-6"), _loan_snapshot(None))
    assert [r.verdict for r in results] == [
        Verdict.COULDNT_CHECK
    ]  # fail-closed, never a silent pass


# --------------------------------------------------------------------------- #
# ID-10 — OFAC / sanctions: OUT OF SCOPE → not_applicable (never couldnt_check, never a spec)
# --------------------------------------------------------------------------- #
def test_id10_is_out_of_scope_no_spec() -> None:
    from app.verification.rules.kinds import RuleKindName, kind_for
    from app.verification.rules.specs import RuleSpecNotFound
    from app.verification.rules.specs import load_rule_spec as _load

    rk = kind_for("ID-10")
    assert rk is not None and rk.kind is RuleKindName.OUT_OF_SCOPE  # §8 Tab 4 — not a couldnt_check
    with pytest.raises(RuleSpecNotFound):
        _load(
            "ID-10"
        )  # no spec, no tags — the registry resolves it to not_applicable (evaluates nothing)


# --------------------------------------------------------------------------- #
# Orchestrator dispatch — ID-1/ID-3/ID-6 run through the SAME registry path the orchestrator uses
# --------------------------------------------------------------------------- #
async def test_orchestrator_dispatch_runs_the_authored_rules_from_specs() -> None:
    from app.verification.rule_engine.registry import evaluate_rules

    snap = _snapshot(
        {
            "app": {
                "id.name_normalized": _tag("Robert Smith", by=TagProducedBy.AI),
                "id.dob": _tag("1985-03-04"),
            },
            "dl": {
                "id.name_normalized": _tag("Robert Smith", by=TagProducedBy.AI),
                "id.dob": _tag("03/04/1985"),  # a pure format difference → normalized to a match
            },
            "loan": {"id.app_required_fields_present": _tag("complete", by=TagProducedBy.DERIVED)},
        },
        borrower_docs=["app", "dl"],
    )
    results, _tags = await evaluate_rules(
        snap,
        consistency_reasoners={"ID-1": _agree},  # exact match short-circuits; stub is a safety net
        rule_ids=("ID-1", "ID-3", "ID-6"),
        confidence_floor=0.5,
    )
    by_rule = {r.rule_id: r.verdict for r in results}
    assert by_rule == {
        "ID-1": Verdict.SATISFIED,
        "ID-3": Verdict.SATISFIED,
        "ID-6": Verdict.SATISFIED,
    }


def test_id1_auto_wires_its_ai_group_in_the_orchestrator() -> None:
    # ID-1's gather tag (id.name_normalized) is AI → the orchestrator's materialization stage runs the
    # id_name group generically, because it's derived from the ACTIVE rules' load-bearing tags.
    from app.services.verification_run import _required_ai_groups

    assert "id_name" in _required_ai_groups()


# --------------------------------------------------------------------------- #
# THE WAVE'S SUCCESS CRITERION — zero per-rule / rule-id branch in the evaluators
# --------------------------------------------------------------------------- #
def test_no_rule_id_or_family_branch_in_the_engine() -> None:
    engine = Path(__file__).parents[3] / "app" / "verification" / "rule_engine"
    for py in engine.glob("*.py"):
        for line in py.read_text().splitlines():
            code = line.split("#", 1)[0]  # ignore comments
            assert "rule_id ==" not in code, f"per-rule branch in {py.name}: {line}"
            assert 'startswith("ID' not in code, f"family branch in {py.name}: {line}"
            assert 'startswith("id.' not in code, f"family branch in {py.name}: {line}"
