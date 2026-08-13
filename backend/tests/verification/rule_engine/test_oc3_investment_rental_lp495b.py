"""LP-495b — OC-3 (investment rental support), activated on a scenario-fixture self-consistency rate.

Every verdict assertion runs through a REAL rule evaluation (materialize_tags -> evaluate_rules), and
the ratification proof in particular does, rather than calling ratifies_every_finding — ratification is
the whole safety substitute for the missing measurement, so proving it by calling the mechanism proves
nothing (LP-508's lesson).

The seam is the FULL {**stub_materialization_reasoners(), "occupancy_rental": ...}; a partial seam is
not a seam and has cost real money twice.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.verification.eval.stubs import stub_materialization_reasoners
from app.verification.rule_engine.activation_bars import (
    is_eligible,
    load_activation_bars,
    ratifies_every_finding,
)
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization.ai import (
    AiGroupResult,
    AiSubjectJudgment,
    AiTagJudgment,
)
from app.verification.tag_materialization.declarations import load_ai_groups
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_LOAN = UUID("95000000-0000-4000-8000-0000000000b1")
_DATE = datetime(2026, 7, 1, tzinfo=UTC)
_TAG = "occupancy.rental_support"


def _reasoner(value: str):
    async def run(context_json: str) -> AiGroupResult:
        subjects = json.loads(context_json).get("subjects", [])
        return AiGroupResult(
            [
                AiSubjectJudgment(
                    index=int(s["index"]),
                    tags={"rental_support": AiTagJudgment(value, 0.95, "the documents were read")},
                )
                for s in subjects
            ],
            input_tokens=1,
            output_tokens=1,
            model="stub",
            truncated=False,
        )

    return run


def _snapshot(occupancy: str | None = "investment") -> Snapshot:
    mismo = (
        {"property.occupancy": Field.present(occupancy, source=FieldSource.PARSED)}
        if occupancy is not None
        else {}
    )
    return Snapshot(
        loan_file_id=_LOAN,
        run_id=uuid4(),
        created_at=_DATE,
        documents=DocumentsSection.present([]),
        mismo=MismoSection.present(mismo),
        tags=TagsSection.present({}),
    )


def _judge(value: str):
    """OC-3 is a JUDGMENT rule — it calls the model at RULE time as well as at materialisation. Stubbing
    only the materialisation reasoners leaves the rule-time call to reach the real provider, which is the
    partial-seam mistake this codebase has paid for twice. Both seams are supplied."""
    from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult

    async def judge(_context_json: str) -> RuleJudgmentResult:
        return RuleJudgmentResult(
            judgment=RuleJudgment(value=value, confidence=0.9, reasoning="scripted"),
            input_tokens=1,
            output_tokens=1,
            model="stub-oc3",
            truncated=False,
        )

    return judge


async def _evaluate(value: str, occupancy: str | None = "investment", verdict: str = "yes"):
    reasoners = {**stub_materialization_reasoners(), "occupancy_rental": _reasoner(value)}
    snapshot = await materialize_tags(_snapshot(occupancy), ai_reasoners=reasoners)
    evaluations, _tags = await evaluate_rules(
        snapshot, rule_ids=("OC-3",), judgment_reasoners={"OC-3": _judge(verdict)}
    )
    return evaluations


async def test_a_judgmental_rule_never_auto_ships_even_on_a_yes() -> None:
    """OC-3 is ai_judgment, so LP-376-B's armor in judgment.py routes EVERY verdict to needs_review with
    ratification — there is no `satisfied` path at all. Asserted rather than assumed, because the
    obvious expectation (a "yes" judgment clears the rule) is wrong here by design: ratify is the
    destination, not a waypoint."""
    evaluations = await _evaluate("adequate", verdict="yes")
    assert [e.verdict for e in evaluations] == [Verdict.NEEDS_REVIEW]
    assert all(e.ratification_pending for e in evaluations)


async def test_inadequate_rental_support_surfaces() -> None:
    """An investment property with no rental documentation behind it. Judgmental, so it routes to a
    human either way — the verdict is what a ratifier sees, not an auto-assertion."""
    verdicts = [e.verdict for e in await _evaluate("inadequate", verdict="no")]
    assert verdicts and Verdict.SATISFIED not in verdicts


async def test_unknown_support_never_clears() -> None:
    """The abstain that matters: an unreadable support picture must not read as supported."""
    assert [e.verdict for e in await _evaluate("unknown")] == [Verdict.COULDNT_CHECK]


async def test_a_file_with_no_documents_is_never_satisfied() -> None:
    """Never satisfied on a missing document, by code path. An investment file with nothing in it must
    not clear — that is the false all-clear this rule exists to avoid."""
    for value in ("unknown", "inadequate"):
        assert Verdict.SATISFIED not in [
            e.verdict for e in await _evaluate(value, verdict="unknown")
        ]


async def test_no_stated_occupancy_never_clears() -> None:
    assert Verdict.SATISFIED not in [e.verdict for e in await _evaluate("adequate", occupancy=None)]


async def test_oc3_has_no_satisfied_path_at_all() -> None:
    """The same property from the other side: across every tag value and judgment value, OC-3 never
    produces `satisfied`. A judgmental rule's output is always something a human signs."""
    for tag_value in ("adequate", "inadequate", "unknown"):
        for judgment in ("yes", "no", "unknown"):
            verdicts = [e.verdict for e in await _evaluate(tag_value, verdict=judgment)]
            assert Verdict.SATISFIED not in verdicts, (tag_value, judgment, verdicts)


@pytest.mark.parametrize("value", ["adequate", "inadequate"])
async def test_every_oc3_finding_carries_ratification(value: str) -> None:
    """Ratification is the ENTIRE safety substitute for the missing measurement (ADR-378), so it is
    proven here through materialisation and the real evaluator — including on `satisfied`, because a
    wrong `satisfied` is exactly what would let unsupported rental income through."""
    findings = [
        e
        for e in await _evaluate(value, verdict="yes" if value == "adequate" else "no")
        if e.verdict is not Verdict.NOT_APPLICABLE
    ]
    assert findings, "OC-3 produced no findings to check"
    assert all(e.ratification_pending for e in findings), (
        "OC-3 shipped a finding with no human in the loop: "
        f"{[(e.subject_id, e.verdict.value) for e in findings if not e.ratification_pending]}"
    )


def test_oc3_is_active_on_a_scenario_fixture_rate() -> None:
    assert "OC-3" in ACTIVE_RULE_IDS
    bar = load_activation_bars()["OC-3"]
    assert bar.status == "ratify-pending"
    assert bar.self_consistency_rate == pytest.approx(1.0)
    assert bar.self_consistency_cases == 4
    assert bar.measured_accuracy is None  # a rate is not a measurement
    assert is_eligible(bar) and ratifies_every_finding("OC-3")


def test_the_group_sees_documents() -> None:
    """The defect the derivation found, pinned. `occupancy_rental` is a LOAN-subject group whose prompt
    tells the model to consider leases, Schedule E and rent schedules — and the loan context carried
    MISMO facts ONLY, so it was handed zero documents and answered from 1003 facts alone. That is PC-5's
    failure shape and it was latent from LP-418 until LP-495b. If the opt-in is ever removed, the model
    silently stops seeing the documents it is being asked about."""
    group = load_ai_groups()["occupancy_rental"]
    assert group.include_documents is True
    assert "lease" in group.system_prompt.lower()


def test_dt7_is_built_but_held_on_its_enum_gap() -> None:
    """DT-7's tag is declared enum ["complete","incomplete"] with NO abstain. The prompt sanctions
    "unknown" and ai.py coerces it — but a coerced tag carries confidence=None, which is the fail-closed
    marker the orchestrator's degradation scan matches, so every run where ATR cannot be determined is
    flagged `degraded`. The txn.is_nsf_or_overdraft precedent does not cover it: AS-7 is inert, so that
    pattern has never run through the orchestrator. This pins BOTH halves — the rule stays held, and the
    enum stays two-valued — so whoever fixes the vocabulary sees why."""
    from app.verification.tag_materialization.declarations import load_declarations

    assert "DT-7" not in ACTIVE_RULE_IDS
    assert load_activation_bars()["DT-7"].status == "not-calibratable-yet"
    allowed = load_declarations()["dti.atr_factors_documented"].allowed_values
    assert allowed == ("complete", "incomplete"), (
        "the enum gained a value — if it now has an abstain, DT-7 can activate on the rate already "
        "recorded on its bar"
    )
    assert load_rule_spec("DT-7").judgment is not None  # built, not deleted
