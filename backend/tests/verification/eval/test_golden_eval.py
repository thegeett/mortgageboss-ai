"""The golden eval harness, scored keyless (LP-317).

The GO/NO-GO regression instrument: every labeled case (1-12) must score as labeled at BOTH the tag
and finding level, both directions of AS-1 must be covered (must-fire + no-false-fire on the real
file), FIRED/NEEDS_REVIEW verdicts must carry inline provenance, and the harness must actually
DETECT a diff (not trivially pass). Keyless (stubbed) for determinism; the calibration summary runs
keyless as a plumbing check and skips live cleanly without a key.
"""

from __future__ import annotations

import dataclasses

from app.models.finding import EvaluationOutcome
from app.services.rule_findings import persist_evaluation_findings
from app.verification.eval.calibration import summarize
from app.verification.eval.cases import CASES, EvalCase, crafted_cases
from app.verification.eval.harness import (
    CaseResult,
    _build_snapshot,
    _materialize_income_tag,
    run_case,
    run_suite,
)
from app.verification.rule_engine.engine import evaluate_as1_rule
from app.verification.rule_engine.result import Verdict


def _fmt(result: CaseResult) -> str:
    return f"case {result.case_id} ({result.title}): " + "; ".join(
        f"{m.dimension}@{m.subject} expected {m.expected!r} got {m.actual!r}"
        for m in result.all_mismatches
    )


# --------------------------------------------------------------------------- #
# Every case scores as labeled (tag + finding level)
# --------------------------------------------------------------------------- #


async def test_all_cases_score_as_labeled() -> None:
    results = await run_suite(CASES)
    failures = [r for r in results if not r.passed]
    assert not failures, "cases failed:\n" + "\n".join(_fmt(r) for r in failures)
    # All 12 cases present + scored.
    assert {r.case_id for r in results} == {str(i) for i in range(1, 13)}


async def test_must_fire_cases_fire() -> None:
    # Both directions - the fires-when-it-should direction LF-6T3N could not provide. Cases 1
    # (unsourced large), 5 (regression: non-'credit' label), 7 (intrinsic-not-a-loophole).
    for case_id in ("1", "5", "7"):
        case = next(c for c in CASES if c.case_id == case_id)
        result = await run_case(case)
        assert result.passed, _fmt(result)
        assert case.must_fire
        # The subject's verdict really is FIRED → open.
        snapshot = _build_snapshot(case)
        # (re-run the pipeline to inspect the verdict directly)
        from app.services.tag_correlation import produce_stage_b_sourcing_tags
        from app.services.tag_production import produce_stage_a_transaction_tags
        from app.verification.eval.stubs import StubStageAReasoner, StubStageBReasoner

        snapshot = await produce_stage_a_transaction_tags(
            snapshot, reasoner=StubStageAReasoner(case.txns)
        )
        snapshot = await produce_stage_b_sourcing_tags(
            snapshot, reasoner=StubStageBReasoner(case.txns)
        )
        snapshot = _materialize_income_tag(
            snapshot
        )  # LP-366 — AS-1 reads the derived income loan tag
        verdicts = {r.verdict for r in evaluate_as1_rule(snapshot)}
        assert Verdict.FIRED in verdicts, f"case {case_id} did not fire: {verdicts}"


async def test_real_file_no_false_fire() -> None:
    # The no-false-fire direction on REAL data (the frozen LF-6T3N trace): 0 fired, and the large
    # deposits carry the sourcing distinction (>=1 verified, >=1 self_asserted).
    case = next(c for c in CASES if c.level == "real")
    result = await run_case(case)
    assert result.passed, _fmt(result)
    assert case.no_false_fire


async def test_verified_requires_a_matched_debit_cited_by_content_id() -> None:
    # Case 9: strength=verified only when the deterministic search found a real debit - and the
    # sourcing tag cites that debit's content_id (provenance to the paper trail).
    case = next(c for c in CASES if c.case_id == "9")
    snapshot = _build_snapshot(case)
    from app.services.tag_correlation import produce_stage_b_sourcing_tags
    from app.services.tag_production import produce_stage_a_transaction_tags
    from app.verification.eval.stubs import StubStageAReasoner, StubStageBReasoner

    snapshot = await produce_stage_a_transaction_tags(
        snapshot, reasoner=StubStageAReasoner(case.txns)
    )
    snapshot = await produce_stage_b_sourcing_tags(snapshot, reasoner=StubStageBReasoner(case.txns))
    # The deposit's content_id + the debit's content_id.
    txns = [t for e in snapshot.documents.entries for t in (e.transactions or ())]
    deposit = next(t for t in txns if t.description.value == "TRANSFER FROM BROKERAGE ACCT")
    debit = next(t for t in txns if t.description.value == "WIRE TO BROKERAGE ACCT")
    tags = snapshot.tags.by_subject[deposit.content_id]
    assert tags["txn.source_strength"].value == "verified"
    # The sourcing tag's provenance cites the matched debit.
    assert debit.content_id in tags["txn.has_identified_source"].source_facts


# --------------------------------------------------------------------------- #
# The harness DETECTS a diff (it is not a trivially-passing rubber stamp)
# --------------------------------------------------------------------------- #


async def test_regression_detection_flags_a_changed_outcome() -> None:
    # Mislabel case 1's expected outcome (open → satisfied). The harness MUST flag the diff.
    case_1 = next(c for c in CASES if c.case_id == "1")
    mutated_txn = dataclasses.replace(case_1.txns[0], expect_outcome="satisfied")
    mutated = dataclasses.replace(case_1, txns=(mutated_txn,))
    result = await run_case(mutated)
    assert not result.passed
    assert any(m.dimension == "outcome" for m in result.finding_mismatches)


async def test_regression_detection_flags_a_changed_strength() -> None:
    # Mislabel case 2's expected strength (verified → self_asserted). Tag-level diff must be caught.
    case_2 = next(c for c in CASES if c.case_id == "2")
    deposit = dataclasses.replace(case_2.txns[0], expect_strength="self_asserted")
    mutated: EvalCase = dataclasses.replace(case_2, txns=(deposit, case_2.txns[1]))
    result = await run_case(mutated)
    assert not result.passed
    assert any(m.dimension == "txn.source_strength" for m in result.tag_mismatches)


# --------------------------------------------------------------------------- #
# Provenance (§3D Move 1) + calibration
# --------------------------------------------------------------------------- #


async def test_fired_and_needs_review_carry_inline_provenance() -> None:
    results = await run_suite(crafted_cases())
    for r in results:
        assert not r.provenance_failures, _fmt(r)


async def test_persisted_fired_finding_carries_load_bearing_provenance(db_session) -> None:  # type: ignore[no-untyped-def]
    # Phase 4, concretely: persist a FIRED case's evaluations and assert the FINDING carries its
    # load-bearing tags inline (LP-316), so a human can see WHY - end to end.
    from app.models import Company
    from app.services.loan_files import create_loan_file

    case = next(c for c in CASES if c.case_id == "1")
    snapshot = _build_snapshot(case)
    from app.services.tag_correlation import produce_stage_b_sourcing_tags
    from app.services.tag_production import produce_stage_a_transaction_tags
    from app.verification.eval.stubs import StubStageAReasoner, StubStageBReasoner

    snapshot = await produce_stage_a_transaction_tags(
        snapshot, reasoner=StubStageAReasoner(case.txns)
    )
    snapshot = await produce_stage_b_sourcing_tags(snapshot, reasoner=StubStageBReasoner(case.txns))
    snapshot = _materialize_income_tag(snapshot)  # LP-366 — AS-1 reads the derived income loan tag
    results = [r for r in evaluate_as1_rule(snapshot) if r.verdict is Verdict.FIRED]
    assert results

    company = Company(name="Acme", slug="acme-eval")
    db_session.add(company)
    await db_session.flush()
    lf = await create_loan_file(db_session, company_id=company.id)
    findings = await persist_evaluation_findings(
        db_session, loan_file_id=lf.id, verification_id=None, results=results
    )
    [finding] = findings
    assert finding.evaluation_outcome is EvaluationOutcome.OPEN
    assert finding.load_bearing_tags
    source = next(
        t for t in finding.load_bearing_tags if t["tag_id"] == "txn.has_identified_source"
    )
    assert (source["reasoning"] or "").strip()  # non-empty WHY


async def test_calibration_keyless_is_a_perfect_baseline() -> None:
    # Keyless observations replay the labels → concrete accuracy is 1.0 and nothing is flagged.
    results = await run_suite(crafted_cases())
    summaries = summarize(results)
    assert summaries  # dimensions were observed
    for s in summaries:
        assert s.accuracy_when_concrete == 1.0, f"{s.dimension} not perfect keyless"
        assert not s.under_abstaining
