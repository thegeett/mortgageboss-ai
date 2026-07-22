"""LP-390-5 — the income-tag calibration join, reproducibly (the live model scores are a point-in-time
snapshot in docs/tickets/LP-390-5.md; this pins the MECHANISM keyless).

score_snapshot_against_golden joins a materialized snapshot's predicted tags to Priya's golden by the stable
(tag_id, subject_id) key and scores each. These assert: a match is scored by the tag's declared method; a
golden with NO produced tag is REPORTED as unmatched (never silently dropped — a missing prediction is a
finding); the join is deterministic given the snapshot (the only non-determinism is the live model upstream).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.verification.eval.live_calibration import (
    score_snapshot_against_golden,
    summarize,
)
from app.verification.snapshot.model import (
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage


def _tag(value: str, *, conf: float | None = 0.9) -> Tag:
    return Tag(
        value=value,
        confidence=conf,
        reasoning="fixture",
        source_facts=("r",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _snap(by_subject: dict[str, dict[str, Tag]]) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 22, tzinfo=UTC),
        documents=DocumentsSection.present([]),
        tags=TagsSection.present(by_subject),
    )


def test_join_scores_matches_and_reports_unmatched() -> None:
    # predicted tags across transaction + document subjects (as the real materialization places them)
    snap = _snap(
        {
            "txn1": {"txn.apparent_category": _tag("payroll")},
            "stmt1": {"stmt.owner_matches_borrower": _tag("no")},  # WRONG vs golden "yes"
        }
    )
    golden = {
        ("txn.apparent_category", "txn1"): "payroll",  # match -> correct
        ("stmt.owner_matches_borrower", "stmt1"): "yes",  # produced "no" -> incorrect
        ("stmt.is_reserve_eligible", "stmt_missing"): "yes",  # NO prediction -> unmatched
    }
    scored, unmatched = score_snapshot_against_golden(snap, golden)
    assert len(scored) == 2  # the two with a matching prediction
    assert unmatched == [("stmt.is_reserve_eligible", "stmt_missing")]  # reported, not dropped

    by_tag = {s.tag_id: s for s in scored}
    assert by_tag["txn.apparent_category"].correct is True
    assert by_tag["stmt.owner_matches_borrower"].correct is False  # golden yes, predicted no


def test_abstention_scoring_and_summary_n() -> None:
    # a golden that IS an abstention ('unknown') is correct WHEN the model abstains (measures correct
    # abstention, not over-abstention); summarize reports n per tag so a thin measurement is visible.
    snap = _snap(
        {
            "d1": {"asset.liquidation_terms": _tag("unknown")},
            "d2": {"asset.liquidation_terms": _tag("immediate")},
        }
    )
    golden = {
        ("asset.liquidation_terms", "d1"): "unknown",  # abstained, golden abstains -> correct
        ("asset.liquidation_terms", "d2"): "immediate",  # concrete match -> correct
    }
    scored, unmatched = score_snapshot_against_golden(snap, golden)
    assert not unmatched
    (dim,) = summarize(scored)
    # summarize.total counts ANSWERABLE goldens only (an 'unknown' golden is excluded — a correct abstention
    # can't trip over-abstaining), so n=1 here; both scored cases are correct (the abstention + the concrete).
    assert dim.dimension == "asset.liquidation_terms" and dim.total == 1
    assert all(s.correct for s in scored)  # correct abstention (d1) + correct concrete (d2)


def test_a_labeled_subject_absent_from_the_snapshot_is_unmatched_not_a_pass() -> None:
    # the LP-390-5 guarantee: a label whose subject never materialized is REPORTED, never silently a pass.
    snap = _snap({})  # no tags produced at all
    golden = {("income.has_2yr_history", "borrower-1"): "yes"}
    scored, unmatched = score_snapshot_against_golden(snap, golden)
    assert scored == [] and unmatched == [("income.has_2yr_history", "borrower-1")]
