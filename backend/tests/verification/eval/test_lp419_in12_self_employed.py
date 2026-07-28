"""LP-419 — IN-12 (a self-employed borrower needs 2 years of income history), written now that LP-418's
income.is_self_employed producer exists.

IN-12 was blocked since LP-390-2a: the naive fix (per-borrower re-scope reading has_2yr_history) is FORBIDDEN —
that tag is income-type-agnostic, so a bare re-scope fires IDENTICALLY to IN-11 (ADR-310). LP-418 built the
missing piece; LP-419 gates IN-12 on income.is_self_employed == yes, then checks the history. The applicability
gate IS what distinguishes IN-12 from IN-11.

These pin: the four branches (W-2 → NOT_APPLICABLE, self-employed + no history → FIRED, + history → satisfied,
unknown/absent → couldnt_check); the D2 IN-11 boundary (both fire on the same borrower, reasons provably
distinct — observed, not assumed); IN-11 unchanged; the subject match; the end-to-end producer→rule composition
on a standalone self-employed scenario; LF-6T3N's W-2 borrowers → NOT_APPLICABLE; and NO activation change
(IN-12 holds — its self-employment scope gate rests on the still-unscored income.type).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.eval.fire_path_scenarios import build_self_employed_no_history_snapshot
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.eval.stubs import stub_materialization_reasoners
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.ai import AiGroupResult, AiSubjectJudgment, AiTagJudgment
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.producer import materialize_tags
from tests.expected_active import EXPECTED_ACTIVE_RULE_COUNT

pytestmark = pytest.mark.anyio

_IN12 = load_rule_spec("IN-12")
_IN11 = load_rule_spec("IN-11")
_SE_BORROWER = "95000000-0000-4000-8000-0000000001aa"


def _tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=0.9,
        reasoning="stub",
        source_facts=("d",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _borrower_snap(tags: dict[str, str]) -> Snapshot:
    """A one-borrower snapshot: a tax_return attributed to the borrower + the borrower's tags at its subject."""
    b = uuid4()
    doc = DocumentEntry(
        content_id="tr",
        document_type="tax_return",
        belongs_to=(BorrowerRef(borrower_id=b, name="X"),),
        fields={},
    )
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        documents=DocumentsSection.present([doc]),
        mismo=MismoSection.present(
            {"borrower.1.borrower_id": Field.present(str(b), source=FieldSource.PARSED)}
        ),
        tags=TagsSection.present({str(b): {k: _tag(v) for k, v in tags.items()}}),
    )


def _in12(tags: dict[str, str]) -> Verdict:
    (result,) = evaluate_deterministic_rule(_IN12, _borrower_snap(tags))
    return result.verdict


# ======================================================================= #
# The four branches (reported, not predicted)
# ======================================================================= #
def test_w2_borrower_is_not_applicable_not_couldnt_check() -> None:
    # THE KEY BRANCH: a W-2 borrower (is_self_employed == no) is OUT OF SCOPE → not_applicable, never a gap.
    assert (
        _in12({"income.is_self_employed": "no", "income.has_2yr_history": "no"})
        is Verdict.NOT_APPLICABLE
    )


def test_self_employed_without_history_fires() -> None:
    assert (
        _in12({"income.is_self_employed": "yes", "income.has_2yr_history": "no"}) is Verdict.FIRED
    )


def test_self_employed_with_history_is_satisfied() -> None:
    assert (
        _in12({"income.is_self_employed": "yes", "income.has_2yr_history": "yes"})
        is Verdict.SATISFIED
    )


def test_unknown_or_absent_self_employment_couldnt_checks() -> None:
    # is_self_employed unknown, OR the gate absent entirely → couldnt_check (we cannot tell if the rule applies).
    assert (
        _in12({"income.is_self_employed": "unknown", "income.has_2yr_history": "no"})
        is Verdict.COULDNT_CHECK
    )
    assert _in12({"income.has_2yr_history": "no"}) is Verdict.COULDNT_CHECK  # gate absent


# ======================================================================= #
# D2 — the IN-11 boundary (observed, not assumed) + IN-11 unchanged
# ======================================================================= #
def test_in11_and_in12_both_fire_on_the_same_self_employed_borrower_with_distinct_reasons() -> None:
    # The double-fire is the accepted precedent (AS-8/AS-10, IN-5/IN-6): both read the same has_2yr_history, so
    # both fire — but the standards genuinely differ (B3-3.1-01 variable-income averaging vs B3-3.2
    # self-employment / Form 1084). The resolution is that IN-12's reason is PROVABLY DISTINCT, so the processor
    # sees two separable concerns, not one duplicated. IN-11 is LIVE and untouched (LP-419 changed only IN-12).
    snap = _borrower_snap({"income.is_self_employed": "yes", "income.has_2yr_history": "no"})
    (r11,) = evaluate_deterministic_rule(_IN11, snap)
    (r12,) = evaluate_deterministic_rule(_IN12, snap)
    assert r11.verdict is Verdict.FIRED and r12.verdict is Verdict.FIRED  # both fire
    assert r11.reasoning != r12.reasoning  # provably distinct
    assert "self-employment" in r12.reasoning.lower() and "1084" in r12.reasoning.lower()
    assert "variable income" in r11.reasoning.lower()  # IN-11's own framing, unchanged


def test_in11_spec_is_unchanged_still_ungated_per_borrower() -> None:
    # LP-419 must not touch IN-11 (live). It stays per_borrower with NO applicability gate — it fires on any
    # income lacking a 2-year history (its documented over-fire limitation), a separate concern from IN-12.
    det = _IN11.deterministic
    assert det is not None
    assert det.applicability is None  # ungated — the boundary is IN-12's gate, not IN-11's
    assert _IN11.subject_enumeration == "per_borrower"


# ======================================================================= #
# D4 — the subject match (from the declarations)
# ======================================================================= #
def test_subject_match_is_borrower_all_the_way_down() -> None:
    decls = load_declarations()
    assert decls["income.is_self_employed"].subject == "borrower"  # the gate
    assert decls["income.has_2yr_history"].subject == "borrower"  # the verdict tag
    assert _IN12.subject_enumeration == "per_borrower"  # the rule


# ======================================================================= #
# D5 — the fire path proven end to end (producer → rule) on a standalone scenario
# ======================================================================= #
class _Fixed:
    """A reasoner that returns fixed short-name values per subject (for the income groups)."""

    def __init__(self, by_short: dict[str, str]) -> None:
        self.by_short = by_short

    async def __call__(self, ctx_json: str) -> AiGroupResult:
        subjects = json.loads(ctx_json)["subjects"]
        judgments = [
            AiSubjectJudgment(
                index=int(s["index"]),
                tags={k: AiTagJudgment(v, 0.9, "stub") for k, v in self.by_short.items()},
            )
            for s in subjects
        ]
        return AiGroupResult(
            judgments, input_tokens=1, output_tokens=1, model="stub", truncated=False
        )


async def test_self_employed_scenario_materializes_the_gate_and_in12_fires() -> None:
    # The full composition: the income AI group perceives income.type == self_employment (per document) → the
    # LP-418 derived income.is_self_employed promotes to "yes" at the borrower → IN-12's gate opens → with
    # has_2yr_history == no, IN-12 FIRES. And IN-11 fires on the same borrower (D2 observed end to end).
    reasoners = stub_materialization_reasoners()
    reasoners["income_amounts"] = _Fixed({"type": "self_employment"})
    reasoners["income_stability"] = _Fixed({"has_2yr_history": "no"})
    mat = await materialize_tags(build_self_employed_no_history_snapshot(), ai_reasoners=reasoners)
    borrower_tags = mat.tags.by_subject[_SE_BORROWER]
    assert borrower_tags["income.is_self_employed"].value == "yes"  # LP-418 producer, materialized
    assert borrower_tags["income.has_2yr_history"].value == "no"

    (r12,) = evaluate_deterministic_rule(_IN12, mat)
    assert r12.verdict is Verdict.FIRED and str(r12.subject_id) == _SE_BORROWER
    (r11,) = evaluate_deterministic_rule(_IN11, mat)
    assert r11.verdict is Verdict.FIRED  # the double-fire, observed on a real materialized snapshot


# ======================================================================= #
# LF-6T3N — its W-2 borrowers → IN-12 NOT_APPLICABLE (evaluated directly; IN-12 is not live)
# ======================================================================= #
async def test_lf6t3n_w2_borrowers_are_not_applicable_for_in12() -> None:
    # LF-6T3N's borrowers are W-2 (LP-107 sample data). With income.type perceived as W-2 income ("base"), the
    # LP-418 promotion reads income.is_self_employed == "no" → IN-12 is NOT_APPLICABLE for every borrower — the
    # KEY branch (out of scope, never a couldnt_check gap). The root is the W-2 gate, named explicitly.
    #
    # (Under the PLAIN keyless stub income.type is honest-unknown → is_self_employed unknown → IN-12
    # couldnt_checks — the correct fail-closed state when the income type is unreadable. The not_applicable below
    # is the W-2 case the real AI produces; we drive it with a "base" income.type stub to pin the gate root.)
    reasoners = stub_materialization_reasoners()
    reasoners["income_amounts"] = _Fixed({"type": "base"})  # W-2 income → is_self_employed "no"
    mat = await materialize_tags(build_lf6t3n_snapshot(), ai_reasoners=reasoners)
    results = evaluate_deterministic_rule(_IN12, mat)
    assert results  # borrowers were enumerated
    assert all(
        r.verdict is Verdict.NOT_APPLICABLE for r in results
    )  # W-2 → out of scope, not a gap


# ======================================================================= #
# Activation — LP-419 HELD it; LP-423 ACTIVATED it (its gate became a deterministic Schedule-C fact)
# ======================================================================= #
def test_in12_is_activated_lp423() -> None:
    # LP-419 held IN-12 because its self-employment scope gate rested on the unscored income.type. LP-422 made
    # the gate a DETERMINISTIC read of Schedule C presence (LP-421), so LP-423 activated it: the verdict tag
    # has_2yr_history inherits IN-11's Priya-validated 0.9 (measured 100%), so the bar is calibratable-now /
    # validated / eligible. income.type is dropped as load-bearing (the deterministic gate supersedes it).
    bar = load_activation_bars()["IN-12"]
    assert bar.status == "calibratable-now" and bar.validated and is_eligible(bar)
    assert bar.load_bearing_ai_tags == (
        "income.has_2yr_history",
    )  # income.type dropped (LP-422 gate)
    assert "IN-12" in ACTIVE_RULE_IDS
    assert len(ACTIVE_RULE_IDS) == EXPECTED_ACTIVE_RULE_COUNT  # 31 — IN-12 added
    assert "IN-11" in ACTIVE_RULE_IDS  # IN-11 still live (unchanged)
