"""Finding apply-impact preview — the "View fix" dry-run (LP-97).

Before a processor commits an Apply, "View fix" shows the FULL itemized before/after impact — the
new debt line, the recomputed totals, and the resulting DTI (with any limit crossing). The
guardrail: the preview must MATCH what the real apply does, so it is computed by REUSING the real
apply→recompute (:func:`app.services.finding_resolution.apply_finding` + the DTI/LTV calculators)
in a **simulate-don't-persist** mode — a savepoint the caller rolls back — NOT a parallel
computation that could diverge (the two-source-of-truth class of bug).

The flow:

1. Snapshot the DTI / LTV **before**.
2. Open a **savepoint**, run the **real** ``apply_finding`` (which performs the structured-data
   change + fires the recompute), snapshot the DTI / LTV **after**, then **roll the savepoint
   back** — so nothing persists.
3. Return the itemized before/after (the existing calculator schemas, already line-itemized) +
   which calculators changed. The frontend renders the diff; on confirm it calls the real apply
   endpoint (the same ``apply_finding``), so what was previewed is what happens.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finding import Finding
from app.models.loan_file import LoanFile
from app.schemas.finding_impact import FindingImpactPreview
from app.services.dti import build_dti_calculation
from app.services.finding_resolution import apply_finding
from app.services.ltv import build_ltv_calculation


def _summarize_change(finding: Finding) -> str:
    """A one-line human summary of the structured-data change the apply performs."""
    spec = finding.details.get("apply")
    if not isinstance(spec, dict):
        return "No structured change."
    action = spec.get("action")
    if action == "add_liability":
        who = spec.get("holder_name") or spec.get("liability_type") or "obligation"
        return f"Add to monthly debts: {who} — ${spec.get('monthly_payment')}/mo"
    if action == "correct_income":
        return f"Correct stated income to ${spec.get('monthly_amount')}/mo"
    return f"Apply: {action}"


def has_apply_spec(finding: Finding) -> bool:
    """Whether the finding declares a structured-data change (→ it gets View fix, not bare Apply)."""
    return isinstance(finding.details.get("apply"), dict)


async def preview_finding_apply(
    db: AsyncSession,
    *,
    finding: Finding,
    loan_file: LoanFile,
    actor_user_id: UUID,
) -> FindingImpactPreview:
    """Compute the itemized before/after impact of applying a finding — a DRY-RUN (LP-97).

    Reuses the REAL ``apply_finding`` + the DTI/LTV recompute inside a savepoint that is rolled
    back, so the result MATCHES the actual apply but persists NOTHING. The caller must not commit
    the preview (it doesn't); the savepoint rollback + object expiry keep the session clean.
    """
    finding_id = finding.id  # capture before the (rolled-back) apply mutates the object
    summary = _summarize_change(finding)
    dti_before = await build_dti_calculation(db, loan_file=loan_file)
    ltv_before = await build_ltv_calculation(db, loan_file=loan_file)

    savepoint = await db.begin_nested()
    try:
        # The REAL apply (one source of truth) — performs the structured-data change; the
        # calculators then recompute from it. Rolled back below, so nothing is persisted.
        await apply_finding(db, finding=finding, loan_file=loan_file, actor_user_id=actor_user_id)
        applied_record = dict(finding.applied_record or {})
        dti_after = await build_dti_calculation(db, loan_file=loan_file)
        ltv_after = await build_ltv_calculation(db, loan_file=loan_file)
    finally:
        await savepoint.rollback()

    # The savepoint rollback reverted the DB AND expired the objects it mutated. Reload them (an
    # awaited refresh, not a lazy sync access) so the finding + file are back to their real,
    # un-applied state and are safe to reuse — the preview persisted nothing.
    await db.refresh(finding)
    await db.refresh(loan_file)

    dti_changed = (
        dti_before.back_end_dti != dti_after.back_end_dti
        or dti_before.front_end_dti != dti_after.front_end_dti
    )
    ltv_changed = ltv_before.ltv != ltv_after.ltv

    affects: list[str] = []
    if dti_changed:
        affects.append("dti")
    if ltv_changed:
        affects.append("ltv")

    return FindingImpactPreview(
        finding_id=finding_id,
        summary=summary,
        applied_record=applied_record,
        affects=affects,
        # Only the calculators the apply actually moves are returned (the rest would be noise).
        dti_before=dti_before if dti_changed else None,
        dti_after=dti_after if dti_changed else None,
        ltv_before=ltv_before if ltv_changed else None,
        ltv_after=ltv_after if ltv_changed else None,
    )
