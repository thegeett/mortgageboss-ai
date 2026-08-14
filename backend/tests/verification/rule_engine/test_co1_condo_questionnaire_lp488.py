"""LP-488 — CO-1 (condo questionnaire present).

⚠️ EVERY VERDICT ASSERTION RUNS THROUGH A REAL RULE EVALUATION (LP-487's standing rule).

⚠️ PRESENCE ONLY, AND THAT IS A DELIBERATE SCOPE LIMIT. Priya's standing point is that condo rules must
distinguish WARRANTABLE from non-warrantable rather than merely confirm a questionnaire exists. That is
CO-3/CO-5's job and it is not buildable: `property.is_warrantable_condo` has NO source field in any of
the 121 schema specs (LP-487), because warrantability is a project-review CONCLUSION (Form 1076 / PERS),
not a readable datum. A test below pins that the tag stays inert, so nobody wires it to an invented
source and quietly widens CO-1 into a warrantability rule.

⚠️ A DOCUMENT-TYPE PRESENCE READ — the classifier's TYPE LABEL, never extracted fields (the IN-8/IN-9/
IN-16 discipline). This matters concretely: the one condo questionnaire in the bench corpus fills 0 of
its unit-count fields, and CO-1 is still correct to report it present.
"""

from __future__ import annotations

import pytest
from app.verification.eval.fire_path_scenarios import (
    build_co1_empty_file_snapshot,
    build_co1_not_condo_snapshot,
    build_co1_questionnaire_missing_snapshot,
    build_co1_questionnaire_present_snapshot,
)
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.distrust import distrusted_tag_ids
from app.verification.rules.specs import load_rule_spec
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio


async def _one(builder) -> Verdict:
    snapshot = await materialize_tags(builder(), only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("CO-1",))
    assert len(evaluations) == 1, f"CO-1 is loan-scoped, got {evaluations}"
    return evaluations[0].verdict


async def test_a_questionnaire_in_the_file_is_satisfied() -> None:
    """⚠️ The fixture's questionnaire states NO unit counts — the shape of the one real questionnaire in
    the corpus. CO-1 reads the TYPE LABEL, so it is still correct to report it present."""
    assert await _one(build_co1_questionnaire_present_snapshot) is Verdict.SATISFIED


async def test_a_condo_with_no_questionnaire_fires() -> None:
    assert await _one(build_co1_questionnaire_missing_snapshot) is Verdict.FIRED


async def test_a_non_condo_is_not_applicable() -> None:
    assert await _one(build_co1_not_condo_snapshot) is Verdict.NOT_APPLICABLE


async def test_an_empty_file_couldnt_checks_never_fires() -> None:
    """⚠️ THE ABSTAIN THAT MATTERS. A file with no documents at all is not evidence the questionnaire is
    missing — it is evidence nothing has been uploaded. Firing here would put a false gap on every condo
    file the moment it is created."""
    verdict = await _one(build_co1_empty_file_snapshot)
    assert verdict is Verdict.COULDNT_CHECK
    assert verdict is not Verdict.FIRED


async def test_lf6t3n_abstains() -> None:
    """LF-6T3N states no property type — surfaced, not skipped."""
    snapshot = await materialize_tags(build_lf6t3n_snapshot(), only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("CO-1",))
    assert [e.verdict for e in evaluations] == [Verdict.COULDNT_CHECK]


def test_the_condo_scoping_is_an_applicability_predicate() -> None:
    applicability = load_rule_spec("CO-1").deterministic.applicability
    assert applicability is not None
    assert (applicability.tag, applicability.op, applicability.value) == (
        "property.type",
        "eq",
        "condo",
    )


def test_warrantability_is_not_wired_into_co1() -> None:
    """⚠️ THE SCOPE FENCE. `property.is_warrantable_condo` has no source field anywhere — it is a
    project-review conclusion (Form 1076 / PERS), not a readable datum. If someone declares it against an
    invented source and CO-1 starts reading it, this fails: warrantability belongs to CO-3/CO-5, with a
    real input, not to a presence check quietly widened."""
    assert "property.is_warrantable_condo" not in load_declarations()
    gated = set(load_rule_spec("CO-1").deterministic.gated_tags)
    assert gated == {"condo.questionnaire_present"}


def test_co1_is_live_and_earned_it_through_the_gate() -> None:
    bars = load_activation_bars()
    assert "CO-1" in ACTIVE_RULE_IDS
    assert is_eligible(bars["CO-1"])
    assert bars["CO-1"].validated is False  # no-ai-dependency → validated is not read


def test_co1_reads_no_distrusted_tag() -> None:
    gated = set(load_rule_spec("CO-1").deterministic.gated_tags)
    assert not (gated & set(distrusted_tag_ids()))
