"""Persisting rule-engine evaluations as findings (LP-316).

Extends the shared Finding model with an evaluation-outcome axis, a stable content-id subject_key,
inline load-bearing-tag provenance, and an append-only per-finding event log. All DB-backed via the
rollback fixture; no AI (RuleEvaluation results are built directly).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from app.models import (
    Company,
    EvaluationOutcome,
    Finding,
    FindingEvent,
    FindingEventType,
    FindingOrigin,
    FindingResolutionStatus,
    FindingStatus,
)
from app.services.loan_files import create_loan_file
from app.services.rule_findings import persist_evaluation_findings
from app.verification.rule_engine.result import LoadBearingTag, RuleEvaluation, Verdict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

_SUBJECT = "txndeposit00000001"


def _lb(
    tag_id: str,
    value: object,
    *,
    confidence: float | None = 0.9,
    reasoning: str = "because",
    source_facts: tuple[str, ...] = (_SUBJECT,),
) -> LoadBearingTag:
    return LoadBearingTag(tag_id, value, confidence, reasoning, source_facts)


def _result(
    verdict: Verdict,
    *,
    subject_id: str = _SUBJECT,
    reasoning: str = "the verdict reasoning",
    verdict_confidence: float | None = 0.8,
    threshold_used: Decimal | None = Decimal("14084.40"),
    how_to_fix: str | None = None,
    load_bearing: tuple[LoadBearingTag, ...] | None = None,
) -> RuleEvaluation:
    return RuleEvaluation(
        rule_id="AS-1",
        subject_id=subject_id,
        verdict=verdict,
        verdict_confidence=verdict_confidence,
        load_bearing_tags=load_bearing
        or (
            _lb("txn.is_money_in", "in"),
            _lb("txn.amount", "20000.00", confidence=None),
            _lb("txn.has_identified_source", "no", reasoning="no matching source found"),
        ),
        threshold_used=threshold_used,
        priya_validated=False,
        gated_pending_signoff=True,
        reasoning=reasoning,
        how_to_fix=how_to_fix,
    )


async def _loan_file_id(db: AsyncSession) -> UUID:
    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    lf = await create_loan_file(db, company_id=company.id)
    return lf.id


async def _persist(db: AsyncSession, results: list[RuleEvaluation]) -> list[Finding]:
    lf_id = await _loan_file_id(db)
    return await persist_evaluation_findings(
        db, loan_file_id=lf_id, verification_id=None, results=results
    )


# --------------------------------------------------------------------------- #
# Outcomes persist
# --------------------------------------------------------------------------- #


async def test_fired_persists_open_finding_with_provenance(db_session: AsyncSession) -> None:
    [finding] = await _persist(db_session, [_result(Verdict.FIRED)])

    assert finding.evaluation_outcome is EvaluationOutcome.OPEN
    assert finding.status is FindingStatus.RED
    assert finding.rule_id == "AS-1"
    assert finding.origin is FindingOrigin.DETERMINISTIC_RULE
    assert finding.resolution_status is FindingResolutionStatus.OPEN
    # subject_key is the stable content_id (LP-312), promoted to a column.
    assert finding.subject_key == _SUBJECT
    assert finding.confidence == 0.8  # verdict_confidence
    # Provenance inline (§3D Move 1): the load-bearing tags with reasoning + source_facts.
    assert finding.load_bearing_tags is not None
    by_id = {t["tag_id"]: t for t in finding.load_bearing_tags}
    assert by_id["txn.has_identified_source"]["reasoning"] == "no matching source found"
    assert by_id["txn.has_identified_source"]["source_facts"] == [_SUBJECT]
    # Evaluation metadata in details.
    assert finding.details["verdict"] == "fired"
    assert finding.details["threshold_used"] == "14084.40"
    assert finding.details["priya_validated"] is False
    # The message is the non-empty reasoning.
    assert finding.message == "the verdict reasoning"


async def test_satisfied_and_couldnt_check_persist(db_session: AsyncSession) -> None:
    satisfied = _result(Verdict.SATISFIED, subject_id="txnsat000000000001", reasoning="sourced")
    couldnt = _result(
        Verdict.COULDNT_CHECK, subject_id="txncc0000000000001", reasoning="has_source unknown"
    )
    findings = await _persist(db_session, [satisfied, couldnt])
    by_subject = {f.subject_key: f for f in findings}

    assert by_subject["txnsat000000000001"].evaluation_outcome is EvaluationOutcome.SATISFIED
    assert by_subject["txnsat000000000001"].status is FindingStatus.GREEN
    # couldnt_check now PERSISTS a record (it left none before LP-316).
    assert by_subject["txncc0000000000001"].evaluation_outcome is EvaluationOutcome.COULDNT_CHECK
    assert by_subject["txncc0000000000001"].status is FindingStatus.YELLOW


async def test_needs_review_self_asserted_carries_how_to_fix_and_strength(
    db_session: AsyncSession,
) -> None:
    result = _result(
        Verdict.NEEDS_REVIEW,
        reasoning="claims an own-account source but no matching debit was found",
        how_to_fix="Obtain the statement for the source account showing the withdrawal.",
        load_bearing=(
            _lb("txn.is_money_in", "in"),
            _lb("txn.amount", "20000.00", confidence=None),
            _lb("txn.has_identified_source", "yes", reasoning="claimed in description only"),
            _lb("txn.source_strength", "self_asserted", reasoning="no matching debit"),
        ),
    )
    [finding] = await _persist(db_session, [result])

    assert finding.evaluation_outcome is EvaluationOutcome.NEEDS_REVIEW
    assert (
        finding.details["how_to_fix"] is not None and "statement" in finding.details["how_to_fix"]
    )
    assert finding.details["source_strength"] == "self_asserted"  # LP-314a strength recorded


async def test_not_applicable_is_not_persisted(db_session: AsyncSession) -> None:
    findings = await _persist(db_session, [_result(Verdict.NOT_APPLICABLE)])
    assert findings == []


# --------------------------------------------------------------------------- #
# subject_key identity + the event log + provenance guard
# --------------------------------------------------------------------------- #


async def test_same_subject_key_twice_violates_uniqueness(db_session: AsyncSession) -> None:
    lf_id = await _loan_file_id(db_session)
    await persist_evaluation_findings(
        db_session, loan_file_id=lf_id, verification_id=None, results=[_result(Verdict.FIRED)]
    )
    # A second finding for the SAME (loan_file, rule, subject_key) — the partial unique index rejects it.
    with pytest.raises(IntegrityError):
        await persist_evaluation_findings(
            db_session,
            loan_file_id=lf_id,
            verification_id=None,
            results=[_result(Verdict.FIRED)],
        )


async def test_different_subjects_get_distinct_findings(db_session: AsyncSession) -> None:
    findings = await _persist(
        db_session,
        [
            _result(Verdict.FIRED, subject_id="txnaaaaaaaaaaaaa01"),
            _result(Verdict.SATISFIED, subject_id="txnbbbbbbbbbbbbb02"),
        ],
    )
    assert {f.subject_key for f in findings} == {"txnaaaaaaaaaaaaa01", "txnbbbbbbbbbbbbb02"}


async def test_created_event_logged_per_finding(db_session: AsyncSession) -> None:
    [finding] = await _persist(db_session, [_result(Verdict.FIRED)])
    events = (
        (
            await db_session.execute(
                select(FindingEvent).where(FindingEvent.finding_id == finding.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].event_type is FindingEventType.CREATED
    assert events[0].from_outcome is None
    assert events[0].to_outcome is EvaluationOutcome.OPEN


async def test_empty_reasoning_is_refused(db_session: AsyncSession) -> None:
    lf_id = await _loan_file_id(db_session)
    with pytest.raises(ValueError, match="empty reasoning"):
        await persist_evaluation_findings(
            db_session,
            loan_file_id=lf_id,
            verification_id=None,
            results=[_result(Verdict.FIRED, reasoning="   ")],
        )


async def test_finding_identity_still_reads_subject_key_from_details(
    db_session: AsyncSession,
) -> None:
    # Coexistence: details.subject_key is still written for the existing finding_identity substrate.
    [finding] = await _persist(db_session, [_result(Verdict.FIRED)])
    assert finding.details["subject_key"] == _SUBJECT
