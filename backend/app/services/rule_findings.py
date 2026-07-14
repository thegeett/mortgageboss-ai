"""Persist rule-engine evaluations as durable findings (LP-316).

Takes LP-315's in-memory :class:`RuleEvaluation` results (as refined by LP-314a) and writes them
as :class:`Finding` rows on the EXISTING shared model — not a fork. It maps the verdict onto the
new evaluation-OUTCOME axis, promotes ``subject_key`` to a stable content-id column, carries the
load-bearing tags inline (the §3D provenance move — a finding never cites a bare number), and
emits a ``created`` event on the per-finding log.

SINGLE-RUN (LP-316): this INSERTs a finding per evaluated subject. Cross-run reconciliation
(carry-forward / retire / outcome-change) is LP-322 — it will drive this through
``reconcile_findings`` using the outcome axis + ``subject_key`` + the event log; this ticket does
not touch that path. Flush-only; the caller owns the transaction.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import (
    EvaluationOutcome,
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingResolutionStatus,
    FindingStatus,
)
from app.models.finding_event import FindingEvent, FindingEventType
from app.verification.rule_engine.result import LoadBearingTag, RuleEvaluation, Verdict

_SOURCE_STRENGTH_TAG = "txn.source_strength"

# Verdict → (evaluation outcome, severity color). NOT_APPLICABLE is absent → not persisted (the
# rule does not apply to that subject). Severity is a COARSE triage color derived from the outcome;
# the evaluation_outcome axis carries the precise signal.
_OUTCOME_BY_VERDICT: dict[Verdict, tuple[EvaluationOutcome, FindingStatus]] = {
    Verdict.FIRED: (EvaluationOutcome.OPEN, FindingStatus.RED),
    Verdict.SATISFIED: (EvaluationOutcome.SATISFIED, FindingStatus.GREEN),
    Verdict.NEEDS_REVIEW: (EvaluationOutcome.NEEDS_REVIEW, FindingStatus.YELLOW),
    Verdict.COULDNT_CHECK: (EvaluationOutcome.COULDNT_CHECK, FindingStatus.YELLOW),
}


def outcome_for_verdict(verdict: Verdict) -> EvaluationOutcome | None:
    """The persisted evaluation-outcome for a verdict, or ``None`` when no finding is persisted
    (``not_applicable``). The SINGLE source of truth for the verdict→outcome mapping — the eval
    harness scores against this, so a change here can never silently diverge from what persists.
    """
    mapping = _OUTCOME_BY_VERDICT.get(verdict)
    return mapping[0] if mapping is not None else None


def _tag_dict(tag: LoadBearingTag) -> dict[str, object]:
    """One load-bearing tag as inline provenance JSON (id + value + confidence + reasoning + facts)."""
    return {
        "tag_id": tag.tag_id,
        "value": tag.value,
        "confidence": tag.confidence,
        "reasoning": tag.reasoning,
        "source_facts": list(tag.source_facts),
    }


def _source_strength(result: RuleEvaluation) -> str | None:
    """The source-strength value (LP-314a) if this evaluation carried one, else None."""
    for tag in result.load_bearing_tags:
        if tag.tag_id == _SOURCE_STRENGTH_TAG and tag.value is not None:
            return str(tag.value)
    return None


def _details(result: RuleEvaluation) -> dict[str, object]:
    """The evaluation metadata + the subject_key the ``finding_identity`` substrate still reads."""
    return {
        "verdict": result.verdict.value,
        "verdict_confidence": result.verdict_confidence,
        "threshold_used": str(result.threshold_used) if result.threshold_used is not None else None,
        "priya_validated": result.priya_validated,
        "gated_pending_signoff": result.gated_pending_signoff,
        "how_to_fix": result.how_to_fix,
        "source_strength": _source_strength(result),
        # Duplicated into details ONLY so LP-93's finding_identity() (which reads details.subject_key)
        # keeps working alongside the new indexed column. Both are written from the SAME
        # result.subject_id here, so they cannot diverge; this copy is transitional — drop it once
        # finding_identity() reads Finding.subject_key directly. Do NOT set one without the other.
        "subject_key": result.subject_id,
    }


async def persist_evaluation_findings(
    db: AsyncSession,
    *,
    loan_file_id: UUID,
    verification_id: UUID | None,
    results: list[RuleEvaluation],
    category: FindingCategory = FindingCategory.ASSETS,
) -> list[Finding]:
    """Persist evaluated subjects as findings + a ``created`` event each (flush-only).

    One finding per subject whose verdict is persisted (``not_applicable`` is skipped). ``open`` /
    ``satisfied`` / ``needs_review`` / ``couldnt_check`` all persist — including ``couldnt_check``,
    which previously left no record. Refuses to persist a finding with empty reasoning (§3D: a
    verdict must say WHY).
    """
    # Pre-pass: resolve each persistable subject and validate its reasoning BEFORE any db.add, so a
    # single empty-reasoning verdict (§3D: a verdict must say WHY) refuses the whole batch cleanly
    # rather than after partially populating the session.
    persistable: list[tuple[RuleEvaluation, EvaluationOutcome, FindingStatus, str]] = []
    for result in results:
        mapping = _OUTCOME_BY_VERDICT.get(result.verdict)
        if mapping is None:
            continue  # not_applicable — this subject is outside the rule's scope; no finding
        outcome, severity = mapping
        message = (result.reasoning or "").strip()
        if not message:
            raise ValueError(
                f"refusing to persist a finding with empty reasoning "
                f"(rule {result.rule_id}, subject {result.subject_id})"
            )
        persistable.append((result, outcome, severity, message))

    outcomes: list[tuple[Finding, EvaluationOutcome]] = []
    for result, outcome, severity, message in persistable:
        finding = Finding(
            loan_file_id=loan_file_id,
            verification_id=verification_id,
            rule_id=result.rule_id,
            origin=FindingOrigin.DETERMINISTIC_RULE,  # AS-1's rule is deterministic; its tags are ai/derived
            status=severity,
            category=category,
            message=message,
            details=_details(result),
            # None for a deterministic pass (all-parsed tags) AND for a couldnt_check with an absent
            # tag; default to 1.0 so a fail-closed outcome is never HIDDEN by a confidence cutoff
            # (open / needs_review / couldnt_check must stay visible). This coarse column is for
            # visibility; evaluation_outcome carries the precise signal.
            confidence=result.verdict_confidence if result.verdict_confidence is not None else 1.0,
            evaluation_outcome=outcome,
            subject_key=result.subject_id,  # the deposit's stable content_id (LP-312)
            load_bearing_tags=[_tag_dict(tag) for tag in result.load_bearing_tags],
            resolution_status=FindingResolutionStatus.OPEN,
        )
        db.add(finding)
        outcomes.append((finding, outcome))

    await db.flush()  # assign finding ids before logging their creation

    for finding, outcome in outcomes:
        db.add(
            FindingEvent(
                finding_id=finding.id,
                event_type=FindingEventType.CREATED,
                from_outcome=None,
                to_outcome=outcome,
                detail={},
            )
        )
    await db.flush()
    return [finding for finding, _ in outcomes]


__all__ = ["outcome_for_verdict", "persist_evaluation_findings"]
