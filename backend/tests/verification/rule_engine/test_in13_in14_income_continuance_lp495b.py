"""LP-495b — IN-13 (other income continuance) and IN-14 (rental income support).

Both activated on scenario-fixture self-consistency rates. Every verdict assertion runs through a REAL
rule evaluation, and the ratification proofs run through materialize_tags -> evaluate_rules rather than
calling ratifies_every_finding — ratification is the whole safety substitute for the missing
measurement.

Both are judgment rules, so BOTH seams are supplied: the materialization reasoners AND the rule-time
judgment reasoner. A partial seam is not a seam and has cost real money twice.
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
    BorrowerRef,
    DocumentEntry,
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

_BORROWER = UUID("b0000000-0000-4000-8000-000000000001")
_DATE = datetime(2026, 7, 1, tzinfo=UTC)


def _f(v: object) -> Field:
    return Field.present(v, source=FieldSource.PARSED)


def _snapshot(doc_type: str | None = "social_security_award_letter") -> Snapshot:
    docs = (
        [
            DocumentEntry(
                content_id="d1",
                document_type=doc_type,
                belongs_to=(BorrowerRef(borrower_id=_BORROWER, name="A. Borrower"),),
                fields={"monthly_benefit_amount": _f("1840.00")},
            )
        ]
        if doc_type is not None
        else []
    )
    return Snapshot(
        loan_file_id=UUID("95000000-0000-4000-8000-0000000000c1"),
        run_id=uuid4(),
        created_at=_DATE,
        documents=DocumentsSection.present(docs),
        mismo=MismoSection.present(
            {
                "borrower.1.borrower_id": _f(str(_BORROWER)),
                "property.occupancy": _f("investment"),
            }
        ),
        tags=TagsSection.present({}),
    )


def _group_reasoner(values: dict[str, str]):
    async def run(context_json: str) -> AiGroupResult:
        subjects = json.loads(context_json).get("subjects", [])
        return AiGroupResult(
            [
                AiSubjectJudgment(
                    index=int(s["index"]),
                    tags={k: AiTagJudgment(v, 0.9, "scripted") for k, v in values.items()},
                )
                for s in subjects
            ],
            input_tokens=1,
            output_tokens=1,
            model="stub",
            truncated=False,
        )

    return run


def _judge(value: str):
    from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult

    async def judge(_context_json: str) -> RuleJudgmentResult:
        return RuleJudgmentResult(
            judgment=RuleJudgment(value=value, confidence=0.9, reasoning="scripted"),
            input_tokens=1,
            output_tokens=1,
            model="stub-in",
            truncated=False,
        )

    return judge


async def _evaluate(
    rule_id: str,
    continuance: str,
    judgment: str = "yes",
    doc: str | None = "social_security_award_letter",
):
    reasoners = {
        **stub_materialization_reasoners(),
        "income_stability": _group_reasoner({"continuance_3yr": continuance}),
        "occupancy_rental": _group_reasoner({"rental_support": "adequate"}),
    }
    snapshot = await materialize_tags(_snapshot(doc), ai_reasoners=reasoners)
    evaluations, _tags = await evaluate_rules(
        snapshot, rule_ids=(rule_id,), judgment_reasoners={rule_id: _judge(judgment)}
    )
    return evaluations


# --------------------------------------------------------------------------- #
# Verdicts, through a real evaluation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rule_id", ["IN-13", "IN-14"])
async def test_a_judgmental_income_rule_never_auto_ships(rule_id: str) -> None:
    """Both are ai_judgment, so LP-376-B's armor routes every verdict to needs_review with ratification.
    There is no `satisfied` path — asserted, because the obvious expectation is wrong here by design."""
    evaluations = await _evaluate(rule_id, continuance="yes", judgment="yes")
    assert evaluations, f"{rule_id} produced no evaluation"
    assert all(e.verdict is Verdict.NEEDS_REVIEW for e in evaluations)


@pytest.mark.parametrize("rule_id", ["IN-13", "IN-14"])
async def test_an_unknown_continuance_never_clears(rule_id: str) -> None:
    """The abstain that matters. An income whose continuance cannot be established must not clear."""
    evaluations = await _evaluate(rule_id, continuance="unknown", judgment="unknown")
    assert Verdict.SATISFIED not in [e.verdict for e in evaluations]


@pytest.mark.parametrize("rule_id", ["IN-13", "IN-14"])
async def test_no_documents_never_clears(rule_id: str) -> None:
    """Never satisfied on a missing document, by code path."""
    evaluations = await _evaluate(rule_id, continuance="unknown", judgment="unknown", doc=None)
    assert Verdict.SATISFIED not in [e.verdict for e in evaluations]


@pytest.mark.parametrize("rule_id", ["IN-13", "IN-14"])
async def test_every_finding_carries_ratification(rule_id: str) -> None:
    """Ratification is the ENTIRE safety substitute for the missing measurement (ADR-378), proven here
    through materialisation and the real evaluator rather than by calling the mechanism."""
    findings = [
        e
        for e in await _evaluate(rule_id, continuance="yes", judgment="yes")
        if e.verdict is not Verdict.NOT_APPLICABLE
    ]
    assert findings, f"{rule_id} produced no findings to check"
    assert all(e.ratification_pending for e in findings), (
        f"{rule_id} shipped a finding with no human in the loop: "
        f"{[(e.subject_id, e.verdict.value) for e in findings if not e.ratification_pending]}"
    )


# --------------------------------------------------------------------------- #
# The research and the producer fix, pinned
# --------------------------------------------------------------------------- #
def test_in13_carries_the_per_type_continuance_table_not_one_blanket_rule() -> None:
    """The real work of this ticket. IN-13 applied ONE blanket three-year test across every income type;
    B3-3.4 sets the requirement PER TYPE. An income type outside the researched table must ABSTAIN, not
    fall through to the default — asserted on the spec so a future edit cannot quietly re-flatten it."""
    spec = load_rule_spec("IN-13")
    values = spec.reference_values.values
    assert values["alimony_child_support_history_months"] == "6"
    assert values["capital_gains_history_years"] == "2"
    assert values["capital_gains_averaging_months"] == "24"
    assert values["social_security_own_record_continuance"] == "no_defined_expiration_required"
    assert values["housing_allowance_history_months"] == "12"
    prompt = spec.judgment.system_prompt.lower()
    assert "do not apply one blanket three-year test" in prompt
    assert "not one of those" in prompt or "cannot place it" in prompt


def test_in14_carries_the_verified_75_percent_factor() -> None:
    """B3-3.8-01 (page dated 10/08/2025), verified verbatim: gross monthly rent x 75%, the remaining 25%
    absorbed by vacancy and maintenance. A researched, cited threshold is calibrated (ADR-361)."""
    values = load_rule_spec("IN-14").reference_values.values
    assert values["gross_rent_qualifying_factor_percent"] == "75"
    assert values["vacancy_and_maintenance_absorption_percent"] == "25"
    assert values["lease_support_bank_statement_months"] == "2"
    assert "B3-3.8-01" in load_rule_spec("IN-14").guideline_reference


def test_the_continuance_group_can_see_non_employment_documents() -> None:
    """The producer defect this ticket fixed, pinned. income_stability's applies_to was
    [w2, pay_stub, voe, uniform_residential_loan_application] — ALL EMPLOYMENT DOCUMENTS — so the group
    producing "other income continuance" could never see an award letter, a pension letter or a lease.
    The prompt asked about continuance; the gathering delivered only pay stubs. If these types are ever
    removed, IN-13 and IN-14 silently stop seeing the documents they are about."""
    applies_to = load_ai_groups()["income_stability"].applies_to
    assert applies_to is not None
    for doc_type in (
        "social_security_award_letter",
        "disability_award_letter",
        "retirement_pension_award_letter",
        "lease_agreement",
    ):
        assert doc_type in applies_to, f"{doc_type} cannot reach the continuance group"


@pytest.mark.parametrize("rule_id", ["IN-13", "IN-14"])
def test_both_are_active_on_a_scenario_fixture_rate(rule_id: str) -> None:
    assert rule_id in ACTIVE_RULE_IDS
    bar = load_activation_bars()[rule_id]
    assert bar.status == "ratify-pending"
    assert bar.self_consistency_rate == pytest.approx(1.0)
    assert bar.measured_accuracy is None  # a rate is not a measurement
    assert is_eligible(bar) and ratifies_every_finding(rule_id)
