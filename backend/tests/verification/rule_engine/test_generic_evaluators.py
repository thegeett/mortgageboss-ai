"""The generic evaluators + registry (LP-324) — rules are SPECS, not per-rule Python.

The AS-1/OC-2 EQUIVALENCE proofs live in test_as1.py / test_engine.py / test_oc2.py / the eval
harness (all pass unchanged through the generic evaluators). These tests prove the GENERALIZATION:
the registry dispatches the active rule set by kind FROM SPECS, and a BRAND-NEW deterministic rule
runs from a spec ONLY — no new Python — which is what unblocks the rule waves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.judgment import evaluate_judgment_rule
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import RuleSpec
from app.verification.snapshot.model import DocumentsSection, Snapshot, TagsSection
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

pytestmark = pytest.mark.anyio


def _loan_snapshot(flag: str | None) -> Snapshot:
    """A snapshot with one loan-level tag ``x.flag`` (or none) under the loan subject."""
    tags: dict[str, dict[str, Tag]] = {}
    if flag is not None:
        tags["loan"] = {
            "x.flag": Tag(
                value=flag,
                confidence=0.9,
                reasoning="fixture",
                source_facts=("loan",),
                produced_by=TagProducedBy.AI,
                tag_role=TagRole.STRUCTURAL_FACT,
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


# A BRAND-NEW deterministic rule expressed as DATA ONLY — a shape AS-1 does not have (no operands,
# a pure tag compare, the loan subject). If this evaluates with zero new Python, the waves can add
# rules as specs.
_SYNTHETIC_SPEC = {
    "rule_id": "SYNTH-1",
    "name": "synthetic flag rule",
    "category": "Identity",
    "kind": "structural",
    "numeric_check": False,
    "criteria": "the flag must be ok",
    "applicability": {"scope": "all loans", "trigger": "once per loan"},
    "required_inputs": [
        {"name": "flag", "snapshot_path": 'tags["loan"]["x.flag"]', "description": "the flag"}
    ],
    "reference_values": {"priya_validated": False, "threshold_needs_signoff": False},
    "subject_enumeration": "loan",
    "subject_key_fields": ["loan"],
    "evidence_required": "the flag value",
    "guideline_reference": "n/a — synthetic test rule",
    "spec_version": 1,
    "deterministic": {
        "load_bearing_tags": ["x.flag"],
        "gated_tags": ["x.flag"],
        "outcomes": [
            {
                "verdict": "fired",
                "when_tags": [{"tag": "x.flag", "op": "ne", "value": "ok"}],
                "reasoning": "the flag is not ok",
            },
            {"verdict": "satisfied", "default": True, "reasoning": "the flag is ok"},
        ],
    },
}


def test_a_new_deterministic_rule_runs_from_a_spec_only() -> None:
    # No per-rule Python: a spec the evaluator has never seen evaluates over its subjects.
    spec = RuleSpec.model_validate(_SYNTHETIC_SPEC)

    fired = evaluate_deterministic_rule(spec, _loan_snapshot("bad"))
    assert [r.verdict for r in fired] == [Verdict.FIRED]
    assert fired[0].rule_id == "SYNTH-1" and fired[0].reasoning == "the flag is not ok"

    satisfied = evaluate_deterministic_rule(spec, _loan_snapshot("ok"))
    assert [r.verdict for r in satisfied] == [Verdict.SATISFIED]

    # Fail-closed for free (reused gate): the required tag absent → couldnt_check, never a silent pass.
    absent = evaluate_deterministic_rule(spec, _loan_snapshot(None))
    assert [r.verdict for r in absent] == [Verdict.COULDNT_CHECK]


async def test_registry_dispatches_the_active_rule_set_by_kind() -> None:
    # The orchestrator's dispatch is the registry running the rule SET from specs, each by its
    # evaluation block, not hardcoded names — AS-1 + OC-2 + ID-1..ID-4/ID-6 + ID-7/ID-9 (per_document,
    # document-type scoped, LP-329).
    assert (
        set(ACTIVE_RULE_IDS)
        == {
            "AS-1",
            "OC-2",
            "ID-2",
            "ID-4",
            "ID-1",
            "ID-3",
            "ID-6",
            "ID-7",
            "ID-9",
            "ID-8",  # LP-332 — borrower-keyed citizenship materialized
            "IN-2",  # LP-333 — pay-stub recency (parsed-only, no uncalibrated AI)
            # LP-389 — the first activation pass, via the eligibility gate:
            "IN-1",  # income.documented_monthly measured 100% >= its 0.98 bar (supersedes the LP-333 deferral)
            "IN-5",  # income.employer_normalized measured 100% >= its 0.95 bar
            "ID-5",  # LP-389-A — the document→loan subject mismatch fixed (per-borrower); input now resolves
            # LP-384 — the second activation pass (stuck deterministic rules, verified on build_lf6t3n_plus):
            "AS-9",  # a statement declaring 5 pages / 4 present → fires
            "IN-4",  # two VOEs with a 77-day gap → fires
            "AS-10",  # already resolves on the base fixture → satisfied
            "AS-2",  # LP-390-7 — EMD sourcing (auto), Priya signed off the 0.90 bar
            "AS-12",  # LP-390-7 — borrowed-funds (ratify)
            "IN-3",  # LP-390-9 — YTD-annualized shortfall (auto), same tag+evidence as IN-1
            # LP-393-6 — the scenario-calibrated income/asset rules (Priya signed off her heights + chose AUTO):
            "IN-7",  # same_line_of_work 100% — JUDGMENTAL, so ships RATIFY despite the AUTO sign-off (LP-376-B)
            "IN-10",  # is_declining 100%
            "IN-11",  # has_2yr_history 100% (RE-SCORED after Priya's B14 ruling)
            "AS-11",  # liquidation_terms 100% (6/6) after LP-393-4a's precedence-rule prompt fix
            "AS-8",  # LP-406-2b — statement chaining on the derived stmt.continuity tag (first Bucket 2 live)
            "IN-6",  # LP-412 — Priya signed off the 0.95 bar (calibratable-now, same as IN-5)
            "PC-7",  # LP-412 — Priya signed off the closing window (no-ai-threshold-pending)
            "PC-2",  # LP-407-3 — purchase price matches loan terms
            "IH-3",  # LP-417 — insurance effective date vs closing
            "PC-3",  # LP-407-4 — contract property address vs the loan file
            "IN-12",  # LP-423 — self-employed 2yr history (deterministic Schedule-C gate)
            "IN-8",  # LP-428 — VOE present (Priya signed off 0.95; voe_present 100% two-sided)
            "IN-9",  # LP-428 — offer letter present (Priya signed off 0.95; offer_letter_present 100%)
            "AS-6",  # LP-429 — account ownership (Priya signed off 0.95; routing 11/11)
            "IN-15",  # LP-430 — terminated-employment documentation (no-ai-dependency; deterministic)
            "IN-16",  # LP-433 — pay-stub-only documentation (no-ai-dependency; deterministic)
            "IH-1",  # LP-447 — insurance adequacy / dwelling settlement basis (no-ai-dependency)
            # LP-485 — the date-compare family, all deterministic (loan-scoped date/number compares).
            "CL-1",
            "CR-12",  # LP-486 — disputed accounts (structural, per_liability)
            "CR-13",
            "PR-6",
        }
    )
    snapshot = _loan_snapshot(None)  # no occupancy/txn tags → everything fail-closes honestly

    results, judgment_tags = await evaluate_rules(snapshot, confidence_floor=0.5)
    rule_ids = {r.rule_id for r in results}
    assert "OC-2" in rule_ids  # the judgment rule ran (couldnt_check here — no structural tags)
    # OC-2 (judgmental) produced no rule_judgment tag under gated inputs; the deterministic AS-1 had
    # no transaction subjects on this snapshot → no AS-1 results, and the run still completes.
    assert judgment_tags == {}
    assert all(r.rule_id in ACTIVE_RULE_IDS for r in results)


# A judgment spec over a NON-loan enumeration (per_deposit). LP-327 made judgment MULTI-SUBJECT (like
# its siblings), so this now yields ONE evaluation per subject — not a fail-loud, not a silent [0].
_MULTI_SUBJECT_JUDGMENT_SPEC = {
    "rule_id": "JBAD-1",
    "name": "multi-subject judgment rule",
    "category": "Occupancy",
    "kind": "judgmental",
    "numeric_check": False,
    "criteria": "n/a",
    "applicability": {"scope": "all loans", "trigger": "once per subject"},
    "required_inputs": [
        {"name": "flag", "snapshot_path": 'tags["loan"]["x.flag"]', "description": "the flag"}
    ],
    "reference_values": {"priya_validated": False, "threshold_needs_signoff": False},
    "subject_enumeration": "per_deposit",  # 0..N subjects — now handled, one verdict each
    "subject_key_fields": ["content_id"],
    "evidence_required": "n/a",
    "guideline_reference": "n/a — synthetic test rule",
    "spec_version": 1,
    "judgment": {
        "subject": "loan",
        "load_bearing_tags": ["x.flag"],
        "reasoned_over": ["x.flag"],
        "output_tag": "x.judged",
        "value_domain": ["yes", "no", "unknown"],
        "system_prompt": "judge the flag",
    },
}


async def test_judgment_rule_enumerates_multiple_subjects_lp327() -> None:
    # per_deposit over a snapshot with zero transactions → 0 subjects → an EMPTY list (no verdict, no
    # crash). The multi-subject evaluator returns one evaluation per subject, never fails loud.
    spec = RuleSpec.model_validate(_MULTI_SUBJECT_JUDGMENT_SPEC)
    evaluations = await evaluate_judgment_rule(spec, _loan_snapshot(None), confidence_floor=0.5)
    assert evaluations == []


def test_deterministic_no_outcome_match_fails_closed_to_couldnt_check() -> None:
    # Defense in depth for the load-time default-outcome validator: if a spec somehow reaches the
    # evaluator with a non-exhaustive outcome list, a matchless subject fails closed to couldnt_check
    # rather than being silently dropped (no finding = false green). Build such a spec by bypassing
    # the model validator (construct.__dict__) so we exercise the runtime for...else fallback.
    spec = RuleSpec.model_validate(_SYNTHETIC_SPEC)
    assert spec.deterministic is not None
    # Replace outcomes with a single NON-default branch that cannot match ("ok" flag, guard wants ne).
    non_exhaustive = spec.deterministic.model_copy(
        update={
            "outcomes": (
                spec.deterministic.outcomes[0],  # the `x.flag ne ok` fired branch, no catch-all
            )
        }
    )
    spec_no_catchall = spec.model_copy(update={"deterministic": non_exhaustive})

    results = evaluate_deterministic_rule(spec_no_catchall, _loan_snapshot("ok"))
    assert [r.verdict for r in results] == [Verdict.COULDNT_CHECK]
    assert "no outcome matched" in results[0].reasoning
