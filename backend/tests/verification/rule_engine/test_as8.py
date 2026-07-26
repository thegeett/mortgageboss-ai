"""AS-8 statement chaining (continuity) — the first Bucket 2 rule to go LIVE (LP-406-2b). A trivial
DETERMINISTIC rule that branches on the derived stmt.continuity enum (LP-410, which unblocked the
LP-406-2 / ADR-322 ordered-pairwise stop). No AI dependency, no Priya threshold → it activates (24 → 25).

These pin: the four branches (broken→fired, chained→satisfied, nothing_to_chain→NOT_APPLICABLE,
unknown→couldnt_check) — especially nothing_to_chain → not_applicable, NOT couldnt_check (the LP-406-2
trap); the AS-10 scope boundary (AS-8 says "balances don't carry", never "a month is missing"); plain
reasons (no dotted tag ids in the surfaced verdicts); the subject match (anti-structural-death); the real
LF-6T3N verdict (satisfied — its 5 statements chain); and that AS-8 is LIVE + eligible.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rule_engine.result import RuleEvaluation, Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import DocumentsSection, Snapshot, TagsSection
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_LOAN = "loan"
_SPEC = load_rule_spec("AS-8")


def _continuity_snapshot(value: str | None) -> Snapshot:
    tags: dict[str, dict[str, Tag]] = {}
    if value is not None:
        tags[_LOAN] = {
            "stmt.continuity": Tag(
                value=value,
                confidence=None,  # derived, a parsed-style passthrough
                reasoning="fixture",
                source_facts=(_LOAN,),
                produced_by=TagProducedBy.DERIVED,
                tag_role=TagRole.STRUCTURAL_FACT,
                tag_version=1,
                stage=TagStage.A,
            )
        }
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        documents=DocumentsSection.present([]),
        tags=TagsSection.present(tags),
    )


def _evaluate(value: str | None) -> list[RuleEvaluation]:
    return evaluate_deterministic_rule(_SPEC, _continuity_snapshot(value))


# --------------------------------------------------------------------------- #
# The four branches (D3) — especially nothing_to_chain → NOT_APPLICABLE (the trap)
# --------------------------------------------------------------------------- #


def test_broken_fires() -> None:
    results = _evaluate("broken")
    assert [r.verdict for r in results] == [Verdict.FIRED]
    assert results[0].how_to_fix  # a fired finding tells the processor how to fix it


def test_chained_satisfies() -> None:
    assert [r.verdict for r in _evaluate("chained")] == [Verdict.SATISFIED]


def test_nothing_to_chain_is_not_applicable_not_couldnt_check() -> None:
    # THE TRAP (LP-406-2): a file whose accounts each have one statement has NOTHING to chain — that is
    # scope-false (not_applicable), NOT a data gap (couldnt_check). Collapsing it into couldnt_check would
    # make AS-8 look broken on ordinary one-statement files.
    results = _evaluate("nothing_to_chain")
    assert [r.verdict for r in results] == [Verdict.NOT_APPLICABLE]


def test_unknown_is_couldnt_check() -> None:
    # A statement balance/period unreadable, or statements ungroupable → couldnt_check, never a false pass.
    assert [r.verdict for r in _evaluate("unknown")] == [Verdict.COULDNT_CHECK]


def test_absent_continuity_tag_is_couldnt_check() -> None:
    # No stmt.continuity produced at all (e.g. an un-materialized snapshot) → couldnt_check, never satisfied.
    assert [r.verdict for r in _evaluate(None)] == [Verdict.COULDNT_CHECK]


# --------------------------------------------------------------------------- #
# The AS-10 scope boundary — AS-8 is the BALANCE chain only, never "a missing month"
# --------------------------------------------------------------------------- #


def test_reasons_stay_within_the_balance_chain_scope() -> None:
    # AS-8 owns the balance carryover; the missing-PERIOD / recency dimension is AS-10's. AS-8 must not say
    # "month" / "missing month" — two rules firing on one gap is noise for the processor.
    for value in ("broken", "chained"):
        for r in _evaluate(value):
            assert "month" not in r.reasoning.lower()
            assert "balance" in r.reasoning.lower()  # it DOES name the balance carryover


def test_surfaced_reasons_are_plain_language_no_dotted_tag_ids() -> None:
    # The user-facing verdicts (fired / satisfied / couldnt_check) name the concern in plain words — no
    # dotted tag ids reach a processor (LP-376-C). (not_applicable is scope-false, never a surfaced finding.)
    for value in ("broken", "chained", "unknown"):
        for r in _evaluate(value):
            assert "stmt.continuity" not in r.reasoning
            assert "stmt." not in r.reasoning


# --------------------------------------------------------------------------- #
# The subject match (anti-structural-death) + the real fixture
# --------------------------------------------------------------------------- #


def test_continuity_tag_is_produced_at_the_subject_as8_reads() -> None:
    # AS-8 enumerates the loan subject; stmt.continuity must be PRODUCED there, else AS-8 couldnt_checks on
    # every file forever (the ID-5 structural-death class).
    assert _SPEC.subject_enumeration == _LOAN
    assert load_declarations()["stmt.continuity"].subject == _LOAN


async def test_as8_satisfied_on_the_real_lf6t3n_fixture() -> None:
    # LP-410 measured stmt.continuity == "chained" on the 5 REAL LF-6T3N statements → AS-8 SATISFIED (its
    # input resolves end-to-end, which is what made it eligible to activate).
    mat = await materialize_tags(build_lf6t3n_snapshot(), only_groups=frozenset())  # parsed+derived
    results = evaluate_deterministic_rule(_SPEC, mat)
    assert [r.verdict for r in results] == [Verdict.SATISFIED]


# --------------------------------------------------------------------------- #
# Live + eligible — no AI dependency, no calibration hold (unlike OC-1)
# --------------------------------------------------------------------------- #


def test_as8_is_live_and_eligible_no_ai_dependency() -> None:
    assert "AS-8" in ACTIVE_RULE_IDS
    bar = load_activation_bars()["AS-8"]
    assert bar.status == "no-ai-dependency"
    assert bar.load_bearing_ai_tags == ()  # nothing to calibrate
    assert bar.input_resolves is True and is_eligible(bar) is True
