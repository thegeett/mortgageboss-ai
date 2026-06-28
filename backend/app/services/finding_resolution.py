"""Verification finding resolution (LP-75) — APPLIED / OVERRIDDEN, and the hook.

A finding must reach a resolution before the file can submit (the blocking rule).
There are exactly two verification resolutions — **nothing is silently ignored**:

* :func:`apply_finding` — **APPLIED**: incorporate the finding into the
  *structured data* (e.g. add an undisclosed obligation to liabilities). Because
  applying *changes the structured data*, it is the trigger point of the
  **AI↔deterministic interlock**: the changed data should drive the deterministic
  recompute (DTI rule + calculators). LP-75 builds the **hook**
  (:func:`mark_recompute_needed`); the full recompute loop is LP-78 + the
  calculators (LP-76/77).
* :func:`override_finding` — **OVERRIDDEN**: dismiss the finding with a
  **recorded reason** (required). The reason is stored on the finding and
  activity-logged.

Both record the resolution trail (who / when) and an activity-log entry. Uses
``flush`` (not ``commit``) — the caller owns the transaction.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.borrower import Borrower
from app.models.finding import Finding, FindingResolutionStatus
from app.models.loan_file import LoanFile
from app.models.stated_financials import StatedIncomeItem, StatedLiability
from app.services.activity_log import log_activity
from app.services.verifications import mark_verification_stale


async def apply_finding(
    db: AsyncSession,
    *,
    finding: Finding,
    loan_file: LoanFile,
    actor_user_id: UUID,
) -> Finding:
    """Resolve a finding as APPLIED — incorporate it into the structured data.

    Performs the structured-data change the finding describes (the apply hook),
    records what was applied on ``applied_record``, sets the resolution trail, and
    fires the recompute hook. Logs a ``FINDING_RESOLVED`` activity.
    """
    applied_record = await _incorporate_into_structured_data(
        db, finding=finding, loan_file=loan_file
    )

    finding.resolution_status = FindingResolutionStatus.APPLIED
    finding.applied_record = applied_record
    finding.resolved_by_user_id = actor_user_id
    finding.resolved_at = utcnow()

    # The hook: applying changed the structured data → downstream deterministic
    # rules + calculators should recompute. Full wiring is LP-78 + LP-76/77.
    await mark_recompute_needed(db, loan_file=loan_file)

    await log_activity(
        db,
        loan_file_id=finding.loan_file_id,
        activity_type=ActivityType.FINDING_RESOLVED,
        summary=f"Finding {finding.rule_id} applied",
        actor_user_id=actor_user_id,
        detail={
            "finding_id": str(finding.id),
            "rule_id": finding.rule_id,
            "resolution": FindingResolutionStatus.APPLIED.value,
            "applied_record": applied_record,
        },
    )
    await db.flush()
    return finding


async def override_finding(
    db: AsyncSession,
    *,
    finding: Finding,
    actor_user_id: UUID,
    reason: str,
) -> Finding:
    """Resolve a finding as OVERRIDDEN — dismissed with a **required** reason.

    Raises ``ValueError`` if ``reason`` is blank: a dismissal must be justified
    (no silent ignore). The reason is recorded on the finding and activity-logged.
    """
    if not reason or not reason.strip():
        raise ValueError("an override requires a recorded reason")

    finding.resolution_status = FindingResolutionStatus.OVERRIDDEN
    finding.resolution_note = reason
    finding.resolved_by_user_id = actor_user_id
    finding.resolved_at = utcnow()

    await log_activity(
        db,
        loan_file_id=finding.loan_file_id,
        activity_type=ActivityType.FINDING_RESOLVED,
        summary=f"Finding {finding.rule_id} overridden",
        actor_user_id=actor_user_id,
        detail={
            "finding_id": str(finding.id),
            "rule_id": finding.rule_id,
            "resolution": FindingResolutionStatus.OVERRIDDEN.value,
            "reason": reason,
        },
    )
    await db.flush()
    return finding


async def mark_recompute_needed(db: AsyncSession, *, loan_file: LoanFile) -> None:
    """The APPLY→recompute hook (LP-75 seam, completed in LP-78).

    Applying a finding mutates the structured data the deterministic rules and
    calculators read, so their prior results are now out of date. LP-78 completes
    the loop:

    * The **DTI / LTV calculators** (LP-76/77) read the structured data live, so
      the change flows into the next calculation automatically (the recompute
      consumers — the corrected income / added obligation moves the ratio).
    * The **cross-source verification** is marked **stale** here, so the processor
      is prompted to re-run it against the changed data.
    """
    await mark_verification_stale(db, loan_file_id=loan_file.id)


async def _incorporate_into_structured_data(
    db: AsyncSession, *, finding: Finding, loan_file: LoanFile
) -> dict[str, Any] | None:
    """Perform the structured-data change an APPLIED finding describes.

    The change is declared in ``finding.details["apply"]`` (the generator emits
    it; e.g. an undisclosed-obligation finding declares an ``add_liability``).
    LP-75 implements the obligation case (the canonical interlock example) and
    leaves a clear extension point for the rest (income adjustments, etc., which
    land with the AI cross-source layer, LP-78). Returns the record of what was
    applied, or ``None`` if the finding declares no structured change.
    """
    spec = finding.details.get("apply")
    if not isinstance(spec, dict):
        return None

    action = spec.get("action")
    if action == "add_liability":
        liability = StatedLiability(
            loan_file_id=loan_file.id,
            liability_type=spec.get("liability_type") or "Installment",
            monthly_payment=_to_money(spec.get("monthly_payment")),
            unpaid_balance=_to_money(spec.get("unpaid_balance")),
            holder_name=spec.get("holder_name"),
        )
        db.add(liability)
        await db.flush()
        return {
            "action": "add_liability",
            "liability_id": str(liability.id),
            "monthly_payment": _stringify_money(liability.monthly_payment),
        }

    if action == "correct_income":
        # Correct a stated income item to the verified figure (LP-78 — the income
        # half of the interlock). Lower income → the DTI recomputes higher.
        return await _correct_income(db, loan_file=loan_file, spec=spec)

    # Unknown action: the hook exists but performs no change (novel findings the AI
    # surfaces that have no deterministic remediation are handled by the human).
    return {"action": action, "applied": False}


async def _correct_income(
    db: AsyncSession, *, loan_file: LoanFile, spec: dict[str, Any]
) -> dict[str, Any]:
    """Update a stated income item to the verified amount (tenant-checked)."""
    raw_id = spec.get("income_item_id")
    new_amount = _to_money(spec.get("monthly_amount"))
    if not isinstance(raw_id, str) or new_amount is None:
        return {"action": "correct_income", "applied": False}
    try:
        item_id = UUID(raw_id)
    except ValueError:
        return {"action": "correct_income", "applied": False}

    item = await db.get(StatedIncomeItem, item_id)
    if item is None or item.deleted_at is not None:
        return {"action": "correct_income", "applied": False}
    # The item must belong to this file (via its borrower) — tenant safety.
    borrower = await db.get(Borrower, item.borrower_id)
    if borrower is None or borrower.loan_file_id != loan_file.id:
        return {"action": "correct_income", "applied": False}

    prior = item.monthly_amount
    item.monthly_amount = new_amount
    await db.flush()
    return {
        "action": "correct_income",
        "income_item_id": str(item.id),
        "from": _stringify_money(prior),
        "to": _stringify_money(new_amount),
    }


def _to_money(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _stringify_money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
