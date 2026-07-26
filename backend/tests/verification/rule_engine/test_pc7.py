"""PC-7 closing-date realism (LP-406-1b) — the last of the three derived-tag rules, and the only one that
compares a NUMBER to a THRESHOLD (the IN-2 operand path, not an enum branch). It branches on the derived
contract.days_until_closing (signed days, LP-410) against a TWO-SIDED window (past + far-future), each a
Priya default → HELD pending her sign-off.

These pin: the two-sided window (past→fired, far-future→fired, in-window→satisfied) with DISTINCT reasons;
NEGATIVE-number coercion (the D3 risk — a past date must fire, not silently couldnt_check); the reason
INTERPOLATES the actual day count (D6); unknown/absent → couldnt_check; the boundaries (day 0 and day 90
satisfied); the subject match (anti-structural-death); and that PC-7 is HELD (no-ai, input_resolves:false —
its window is an unvalidated default).
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
_SPEC = load_rule_spec("PC-7")


def _snapshot(days: str | None) -> Snapshot:
    tags: dict[str, dict[str, Tag]] = {}
    if days is not None:
        tags[_LOAN] = {
            "contract.days_until_closing": Tag(
                value=days,
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


def _evaluate(days: str | None) -> list[RuleEvaluation]:
    return evaluate_deterministic_rule(_SPEC, _snapshot(days))


# --------------------------------------------------------------------------- #
# The two-sided window (D2/D5) — past→fired, far-future→fired, in-window→satisfied
# --------------------------------------------------------------------------- #


def test_past_closing_date_fires_and_names_the_past() -> None:
    # D3 RISK: a negative day count must COERCE and FIRE, never silently couldnt_check.
    results = _evaluate("-10")
    assert [r.verdict for r in results] == [Verdict.FIRED]
    assert "passed" in results[0].reasoning and results[0].how_to_fix


def test_far_future_closing_date_fires() -> None:
    results = _evaluate("200")
    assert [r.verdict for r in results] == [Verdict.FIRED]
    assert "far ahead" in results[0].reasoning


def test_past_and_far_future_have_distinct_reasons() -> None:
    # They are DIFFERENT problems for a processor (a passed date vs a premature one) — distinct messages.
    assert _evaluate("-10")[0].reasoning != _evaluate("200")[0].reasoning


def test_near_term_and_today_satisfy() -> None:
    assert [r.verdict for r in _evaluate("1")] == [Verdict.SATISFIED]
    assert [r.verdict for r in _evaluate("0")] == [Verdict.SATISFIED]  # closes today — fine


def test_window_boundaries() -> None:
    assert _evaluate("90")[0].verdict is Verdict.SATISFIED  # at the far-future default, not over
    assert _evaluate("91")[0].verdict is Verdict.FIRED  # just over
    assert _evaluate("-1")[0].verdict is Verdict.FIRED  # any strictly-past date (default grace 0)


def test_unknown_and_absent_are_couldnt_check() -> None:
    assert [r.verdict for r in _evaluate("unknown")] == [Verdict.COULDNT_CHECK]
    assert [r.verdict for r in _evaluate(None)] == [Verdict.COULDNT_CHECK]


# --------------------------------------------------------------------------- #
# D6 — the reason INTERPOLATES the actual day count (PC-7 has a real operand, unlike AS-8/IN-6)
# --------------------------------------------------------------------------- #


def test_reason_interpolates_the_day_count() -> None:
    assert "-10 day" in _evaluate("-10")[0].reasoning  # the signed number, verbatim
    assert "200 day" in _evaluate("200")[0].reasoning
    for days in ("-10", "200"):
        assert "contract.days_until_closing" not in _evaluate(days)[0].reasoning  # no dotted tag id


# --------------------------------------------------------------------------- #
# Subject match + held + the real fixture
# --------------------------------------------------------------------------- #


def test_days_until_closing_is_produced_at_the_subject_pc7_reads() -> None:
    assert _SPEC.subject_enumeration == _LOAN
    assert load_declarations()["contract.days_until_closing"].subject == _LOAN


def test_pc7_is_written_but_held_no_ai_window_pending_priya() -> None:
    # no-ai (the tag is derived from a PARSED closing date) — but its two-sided window is an unvalidated
    # Priya default, so it is HELD via input_resolves:false (the model-gap note in the bar). Not active.
    bar = load_activation_bars()["PC-7"]
    assert bar.status == "no-ai-dependency"
    assert bar.load_bearing_ai_tags == ()  # no AI tag
    assert bar.input_resolves is False and is_eligible(bar) is False
    assert "PC-7" not in ACTIVE_RULE_IDS


async def test_pc7_satisfied_on_the_real_lf6t3n_fixture() -> None:
    # LP-410 measured contract.days_until_closing == "1" on LF-6T3N (closes in 1 day) → PC-7 SATISFIED under
    # any sane window. Proves the input resolves end-to-end (the reason it could activate once Priya signs off).
    mat = await materialize_tags(build_lf6t3n_snapshot(), only_groups=frozenset())
    assert [r.verdict for r in evaluate_deterministic_rule(_SPEC, mat)] == [Verdict.SATISFIED]
