"""Verification runner (LP-121) — snapshot → filter → evaluator → four-bucket result.

The orchestrator that ties the data-driven engine together and runs a rule END TO END. It does NOT
reimplement any stage — it ORCHESTRATES the existing pieces:

1. **Snapshot (LP-118.6)** — build the frozen fact snapshot ONCE (calculators computed once, facts
   canonicalized + frozen). Everything downstream reads this one snapshot.
2. **Applicability filter (LP-119)** — classify EVERY enabled rule → doesn't-apply / couldn't-check /
   ready-to-run, reading each rule's ``applicability`` as DATA.
3. **Evaluators (LP-120)** — for each READY-TO-RUN rule ONLY, dispatch its registered evaluator →
   finding / satisfied. Never dispatched for couldn't-check / doesn't-apply (the honesty contract).
4. **Collect** — the four-bucket :class:`VerificationRunResult` (finding / couldn't-check / satisfied
   / doesn't-apply), each rule carrying its reason / message / confidence / provenance.

General + data-driven: adding a rule = author its applicability + register its evaluator — **no
runner change**. This runs **alongside** the live cross-source path (``run_cross_source``); it does
not replace or modify it (that retirement is LP-161). It computes + returns the result — persisting
it is a later concern (LP-140/162). Distinct entry name (``run_rule_engine``) to avoid colliding
with the live ``run_verification`` route / ``run_cross_source`` service.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.loan_file import LoanFile
from app.models.verification_rule import VerificationRule
from app.verification.applicability import RuleClassification, classify_rules
from app.verification.evaluators import (
    ConfidenceMode,
    EvaluationResult,
    Provenance,
    Verdict,
    ensure_registered,
    evaluate_rule,
    get_evaluator,
)
from app.verification.fact_namespace import assemble_fact_namespace

Bucket = Literal["finding", "satisfied", "couldnt_check", "doesnt_apply"]


class RuleOutcome(BaseModel):
    """One rule's outcome in a run — its bucket + the "why" (for a later UI/API + the trust surface)."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    bucket: Bucket
    # PROVISIONAL (post-review FIX 5): the rule's threshold isn't Priya-validated
    # (``VerificationRule.validated`` is False), so its verdict is shown as provisional / pending
    # validation, NOT asserted as authoritative — "an unvalidated threshold must not go live at full
    # confidence".
    provisional: bool = False
    message: str | None = None
    reasons: list[str] = []
    missing_inputs: list[str] = []
    confidence: float | None = None
    # One vocabulary end-to-end (post-review FIX 6): the ConfidenceMode enum ({deterministic,
    # computed}) — the SAME values the seed writes to ``verification_rules.confidence_mode``.
    confidence_mode: ConfidenceMode | None = None
    provenance: list[Provenance] = []


class VerificationRunResult(BaseModel):
    """The four-bucket result of one engine run (LP-121) — consumable by an API/UI (LP-162)."""

    model_config = ConfigDict(frozen=True)

    loan_file_id: str
    findings: list[RuleOutcome]
    satisfied: list[RuleOutcome]
    couldnt_check: list[RuleOutcome]
    doesnt_apply: list[RuleOutcome]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "finding": len(self.findings),
            "satisfied": len(self.satisfied),
            "couldnt_check": len(self.couldnt_check),
            "doesnt_apply": len(self.doesnt_apply),
        }


_EVALUATOR_BUCKET: dict[Verdict, Bucket] = {
    Verdict.FINDING: "finding",
    Verdict.SATISFIED: "satisfied",
    Verdict.COULDNT_CHECK: "couldnt_check",  # post-review FIX 8 — evaluator ran but undeterminable
}


def _from_classification(
    rc: RuleClassification, bucket: Bucket, *, provisional: bool
) -> RuleOutcome:
    return RuleOutcome(
        rule_id=rc.rule_id,
        bucket=bucket,
        provisional=provisional,
        reasons=list(rc.classification.reasons),
        missing_inputs=list(rc.classification.missing_inputs),
    )


def _from_evaluation(result: EvaluationResult, *, provisional: bool) -> RuleOutcome:
    return RuleOutcome(
        rule_id=result.rule_id,
        bucket=_EVALUATOR_BUCKET[result.verdict],
        provisional=provisional,
        message=result.message,
        confidence=result.confidence,
        confidence_mode=result.confidence_mode,
        provenance=list(result.provenance),
    )


async def run_rule_engine(
    db: AsyncSession,
    loan_file: LoanFile,
    *,
    rules: Sequence[VerificationRule] | None = None,
) -> VerificationRunResult:
    """Run the data-driven engine on one loan file → the four-bucket result (LP-121).

    Orchestrates LP-118.6 → LP-119 → LP-120. Reads the enabled ``verification_rules`` (or the
    ``rules`` passed by a caller/test). No per-rule logic. **Genuinely read-only (post-review FIX 4):**
    it persists nothing and writes no borrower↔document links — it READS the existing links via the
    snapshot. Refreshing those links is a separate explicit, committed operation
    (``assign_documents_to_borrowers``), run when documents change — NOT on every verification.
    """
    ensure_registered()  # FIX 10 — the runner guarantees the registry is populated before dispatch

    # Build the frozen snapshot ONCE (all rules read this same object). Read-only.
    snapshot = await assemble_fact_namespace(db, loan_file)  # LP-118.6

    if rules is None:
        rules = (
            (
                await db.execute(
                    select(VerificationRule)
                    .where(VerificationRule.enabled.is_(True))
                    .order_by(VerificationRule.rule_id)
                )
            )
            .scalars()
            .all()
        )
    rule_by_id = {rule.rule_id: rule for rule in rules}

    def _provisional(rule_id: str) -> bool:
        rule = rule_by_id.get(rule_id)
        return rule is not None and not rule.validated  # FIX 5 — unvalidated → provisional

    classified = classify_rules(list(rules), snapshot)  # LP-119

    findings: list[RuleOutcome] = []
    satisfied: list[RuleOutcome] = []
    couldnt_check: list[RuleOutcome] = []
    by_bucket = {"finding": findings, "satisfied": satisfied, "couldnt_check": couldnt_check}

    # Evaluators run ONLY on ready-to-run rules (never couldn't-check / doesn't-apply).
    for rc in classified.ready_to_run:
        rule = rule_by_id.get(rc.rule_id)
        params = rule.params if rule is not None else {}
        provisional = _provisional(rc.rule_id)
        if get_evaluator(rc.rule_id) is None:
            # Applicable + data present, but no evaluator is built yet → couldn't check it (honest,
            # surfaced, never a silent pass). Does NOT crash the runner.
            couldnt_check.append(
                RuleOutcome(
                    rule_id=rc.rule_id,
                    bucket="couldnt_check",
                    provisional=provisional,
                    reasons=["no evaluator registered (rule not yet built)"],
                )
            )
            continue
        result = evaluate_rule(rc.rule_id, snapshot, params)  # LP-120
        assert result is not None  # get_evaluator confirmed one is registered
        outcome = _from_evaluation(result, provisional=provisional)
        by_bucket[outcome.bucket].append(outcome)  # finding / satisfied / couldnt_check (FIX 8)

    couldnt_check.extend(
        _from_classification(rc, "couldnt_check", provisional=_provisional(rc.rule_id))
        for rc in classified.couldnt_check
    )
    doesnt_apply = [
        _from_classification(rc, "doesnt_apply", provisional=_provisional(rc.rule_id))
        for rc in classified.doesnt_apply
    ]

    return VerificationRunResult(
        loan_file_id=str(loan_file.id),
        findings=findings,
        satisfied=satisfied,
        couldnt_check=couldnt_check,
        doesnt_apply=doesnt_apply,
    )
