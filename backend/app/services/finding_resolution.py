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
from app.models.finding import Finding, FindingResolutionStatus
from app.models.loan_file import LoanFile
from app.models.stated_financials import StatedLiability
from app.services.activity_log import log_activity


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
    """The APPLY→recompute hook seam (LP-75) — applying changed structured data.

    Applying a finding mutates the structured data the deterministic rules and
    calculators read, so their prior results are now stale and should recompute.
    LP-75 establishes the call site; the recompute **consumers** wire in later:

    * **LP-78** — the cross-source layer + the full APPLY→recompute loop (e.g.
      marking verification stale and re-running on demand);
    * **LP-76/77** — the DTI / LTV calculators recompute from the changed data.

    The observable signal today is the structured-data change itself (a new
    liability, an adjusted income) which a recompute consumer reads directly.
    Intentionally a no-op until those consumers exist.
    """
    # No-op seam — see docstring. Kept as the explicit hook call site.
    return None


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

    # Unknown action: the hook exists but performs no change (LP-78 extends this).
    return {"action": action, "applied": False}


def _to_money(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _stringify_money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
