"""IH-3 — insurance effective date vs closing (LP-417): the first Bucket 3 rule live. A trivial DETERMINISTIC
rule that compares two loan-level DATE tags — ins.loan_effective_date (LP-417's promotion off the already-
extracted homeowners_insurance binder) and contract.loan_closing_date — NATIVELY (the ID-5 date-vs-date shape,
direction flipped). No AI, no threshold → it activates (28 → 29).

These pin: the branches (effective after closing → fired with the dates interpolated; on/before → satisfied;
absent/ambiguous → couldnt_check); the multi-binder abstain (two disagreeing effective dates → unknown, never a
picked binder); the reason interpolates BOTH dates; the subject match (anti-structural-death); the binder
scenarios are standalone (95… namespace, NOT LF-6T3N); and IH-3 is LIVE + eligible.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.eval.fire_path_scenarios import (
    EXPECTED_INS_EFFECTIVE_IN_FORCE,
    EXPECTED_INS_EFFECTIVE_LATE,
    build_insurance_binder_plus_decree_snapshot,
    build_insurance_decree_only_snapshot,
    build_insurance_in_force_snapshot,
    build_insurance_late_snapshot,
    build_insurance_two_binder_snapshot,
)
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rule_engine.result import RuleEvaluation, Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import DocumentsSection, MismoSection, Snapshot, TagsSection
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_LOAN = "loan"
_SPEC = load_rule_spec("IH-3")


def _date_tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=None,
        reasoning="fixture",
        source_facts=(_LOAN,),
        produced_by=TagProducedBy.DERIVED,
        tag_role=TagRole.STRUCTURAL_FACT,
        tag_version=1,
        stage=TagStage.A,
    )


def _snapshot(effective: str | None, closing: str | None) -> Snapshot:
    tags: dict[str, Tag] = {}
    if effective is not None:
        tags["ins.loan_effective_date"] = _date_tag(effective)
    if closing is not None:
        tags["contract.loan_closing_date"] = _date_tag(closing)
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        documents=DocumentsSection.present([]),
        mismo=MismoSection.present({}),
        tags=TagsSection.present({_LOAN: tags} if tags else {}),
    )


def _evaluate(effective: str | None, closing: str | None) -> list[RuleEvaluation]:
    return evaluate_deterministic_rule(_SPEC, _snapshot(effective, closing))


# --------------------------------------------------------------------------- #
# The branches
# --------------------------------------------------------------------------- #
def test_effective_after_closing_fires_with_both_dates() -> None:
    results = _evaluate("2026-08-15", "2026-07-15")
    assert [r.verdict for r in results] == [Verdict.FIRED]
    # the reason interpolates BOTH dates (IH-3 has real operands, unlike AS-8/IN-6)
    assert "2026-08-15" in results[0].reasoning and "2026-07-15" in results[0].reasoning
    assert results[0].how_to_fix


def test_effective_before_closing_satisfies() -> None:
    assert [r.verdict for r in _evaluate("2026-06-01", "2026-07-15")] == [Verdict.SATISFIED]


def test_effective_ON_closing_satisfies_not_fired() -> None:
    # The same-day boundary (D6): a policy effective ON the closing date is in force at closing → satisfied
    # (`>` fires, so `==` does not) — the ID-5 == boundary, benign here.
    assert [r.verdict for r in _evaluate("2026-07-15", "2026-07-15")] == [Verdict.SATISFIED]


def test_absent_effective_date_is_couldnt_check() -> None:
    # No binder / no effective date → the operand coerces to None → couldnt_check (never a guessed pass). This
    # is the LF-6T3N / no-binder case (D5): couldnt_check, NOT not_applicable (insurance is required).
    assert [r.verdict for r in _evaluate(None, "2026-07-15")] == [Verdict.COULDNT_CHECK]


def test_absent_closing_date_is_couldnt_check() -> None:
    assert [r.verdict for r in _evaluate("2026-06-01", None)] == [Verdict.COULDNT_CHECK]


# --------------------------------------------------------------------------- #
# The subject match (anti-structural-death)
# --------------------------------------------------------------------------- #
def test_both_tags_are_produced_at_the_subject_ih3_reads() -> None:
    # IH-3 enumerates the loan subject; both date tags must be produced there, else it couldnt_checks on every
    # file forever (the ID-5 structural-death class).
    assert _SPEC.subject_enumeration == _LOAN
    decls = load_declarations()
    assert decls["ins.loan_effective_date"].subject == _LOAN
    assert decls["contract.loan_closing_date"].subject == _LOAN


# --------------------------------------------------------------------------- #
# On the REAL binder scenarios (LP-417's fixtures — NOT LF-6T3N)
# --------------------------------------------------------------------------- #
async def _materialize(snap: Snapshot) -> Snapshot:
    return await materialize_tags(snap, only_groups=frozenset())  # parsed + derived, no AI


async def test_in_force_binder_scenario_satisfies() -> None:
    mat = await _materialize(build_insurance_in_force_snapshot())
    assert (
        mat.tags.by_subject[_LOAN]["ins.loan_effective_date"].value
        == EXPECTED_INS_EFFECTIVE_IN_FORCE
    )
    assert [r.verdict for r in evaluate_deterministic_rule(_SPEC, mat)] == [Verdict.SATISFIED]


async def test_late_binder_scenario_fires() -> None:
    mat = await _materialize(build_insurance_late_snapshot())
    assert (
        mat.tags.by_subject[_LOAN]["ins.loan_effective_date"].value == EXPECTED_INS_EFFECTIVE_LATE
    )
    results = evaluate_deterministic_rule(_SPEC, mat)
    assert [r.verdict for r in results] == [Verdict.FIRED]
    assert "2026-08-15" in results[0].reasoning and "2026-07-15" in results[0].reasoning


async def test_two_binder_disagreement_abstains_to_couldnt_check() -> None:
    # The multi-binder abstain (D2, mirroring housing.insurance_monthly): two binders with different effective
    # dates → ins.loan_effective_date "unknown" → IH-3 couldnt_check, never a silently-picked binder.
    mat = await _materialize(build_insurance_two_binder_snapshot())
    assert str(mat.tags.by_subject[_LOAN]["ins.loan_effective_date"].value) == "unknown"
    assert [r.verdict for r in evaluate_deterministic_rule(_SPEC, mat)] == [Verdict.COULDNT_CHECK]


async def test_a_divorce_decree_effective_date_is_not_an_insurance_binder() -> None:
    # REGRESSION (LP-417 review): the `effective_date` FIELD is emitted by BOTH homeowners_insurance and
    # divorce_decree, and a document parsed tag is scoped by field NAME — so ins.effective_date materializes on
    # a decree too. _loan_effective_date must read ONLY homeowners_insurance documents. With a decree effective
    # 2026-09-01 (after the 2026-07-15 closing) but NO binder, IH-3 must COULDNT_CHECK (an honest missing-
    # insurance gap) — NOT fire on the decree's date as though a policy takes effect after closing.
    mat = await _materialize(build_insurance_decree_only_snapshot())
    assert str(mat.tags.by_subject[_LOAN]["ins.loan_effective_date"].value) == "unknown"
    assert [r.verdict for r in evaluate_deterministic_rule(_SPEC, mat)] == [Verdict.COULDNT_CHECK]


async def test_a_decree_does_not_shadow_a_real_binder() -> None:
    # REGRESSION (LP-417 review): a real binder effective 2026-06-01 (before closing) PLUS a divorce_decree with
    # a DIFFERENT effective_date (2026-09-01) must resolve ins.loan_effective_date to the BINDER's date and
    # SATISFY — the decree must NOT create a false two-binder disagreement that abstains to couldnt_check (a
    # missed coverage-gap check).
    mat = await _materialize(build_insurance_binder_plus_decree_snapshot())
    assert (
        mat.tags.by_subject[_LOAN]["ins.loan_effective_date"].value
        == EXPECTED_INS_EFFECTIVE_IN_FORCE
    )
    assert [r.verdict for r in evaluate_deterministic_rule(_SPEC, mat)] == [Verdict.SATISFIED]


async def test_lf6t3n_couldnt_checks_no_binder() -> None:
    # LF-6T3N has NO homeowners binder (LP-414 A3 kept it off, to not move the DTI insurance line) → IH-3
    # couldnt_checks there. An honest absence, not a bug; the branches are proven on the binder scenarios above.
    mat = await _materialize(build_lf6t3n_snapshot())
    assert [r.verdict for r in evaluate_deterministic_rule(_SPEC, mat)] == [Verdict.COULDNT_CHECK]


# --------------------------------------------------------------------------- #
# Live + eligible — no AI dependency, no threshold (like AS-8 / PC-2)
# --------------------------------------------------------------------------- #
def test_ih3_is_live_and_eligible_no_ai_dependency() -> None:
    assert "IH-3" in ACTIVE_RULE_IDS
    bar = load_activation_bars()["IH-3"]
    assert bar.status == "no-ai-dependency"
    assert bar.load_bearing_ai_tags == () and bar.threshold is None
    assert bar.input_resolves is True and is_eligible(bar) is True
