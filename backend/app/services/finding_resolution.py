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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.borrower import Borrower
from app.models.finding import Finding, FindingResolutionStatus, FindingStatus
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.needs_item import (
    NeedsItem,
    NeedsItemDisposition,
    NeedsItemOrigin,
    NeedsItemPriority,
    NeedsItemStatus,
)
from app.models.property import Property
from app.models.stated_financials import StatedIncomeItem, StatedLiability
from app.services.activity_log import log_activity
from app.services.needs_items import create_needs_item
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
    # AN APPLY THAT CHANGED NOTHING MUST NOT CLOSE THE FINDING. Every handler returns
    # `applied: False` when it could not perform its change — a typo'd action name, a target row that
    # is gone, an unparseable amount. Before LP-558 the finding was marked APPLIED regardless, so a
    # processor saw "resolved" over a loan file nothing had been written to, and the DTI they were
    # trusting had not moved. Fail loudly instead: the finding stays open and the caller is told.
    if isinstance(applied_record, dict) and applied_record.get("applied") is False:
        raise CannotApplyError(
            f"this finding declares an apply the system could not perform "
            f"({applied_record.get('action')!r}) — nothing was changed"
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


async def add_finding_note(
    db: AsyncSession,
    *,
    finding: Finding,
    actor_user_id: UUID,
    note: str,
) -> Finding:
    """Append a free-text note to a finding **without** changing its resolution (LP-81).

    Notes accumulate on ``details["notes"]`` (each with author + timestamp) and are
    activity-logged. A note is informational — it neither resolves the finding nor
    marks verification stale. Raises ``ValueError`` on a blank note. ``flush`` only.
    """
    if not note or not note.strip():
        raise ValueError("a note cannot be empty")

    existing = finding.details.get("notes")
    notes = list(existing) if isinstance(existing, list) else []
    notes.append({"note": note, "by": str(actor_user_id), "at": utcnow().isoformat()})
    # Reassign so SQLAlchemy detects the JSON change (mutating in place would not).
    finding.details = {**finding.details, "notes": notes}

    await log_activity(
        db,
        loan_file_id=finding.loan_file_id,
        activity_type=ActivityType.NOTE_ADDED,
        summary=f"Note added to finding {finding.rule_id}",
        actor_user_id=actor_user_id,
        detail={"finding_id": str(finding.id), "rule_id": finding.rule_id, "note": note},
    )
    await db.flush()
    return finding


async def accept_risk_finding(
    db: AsyncSession,
    *,
    finding: Finding,
    actor_user_id: UUID,
    reason: str | None = None,
) -> Finding:
    """Resolve a finding as ACCEPTED_RISK — acknowledged as a known/accepted risk (LP-88).

    DISTINCT from OVERRIDDEN (which dismisses the finding as not-applicable): accept-risk
    acknowledges a REAL finding the processor chooses to proceed with — the FHA
    compensating-factors (LP-84) + subject-to-repair (LP-85) conditional model, where the
    finding is mitigable, not a hard block. The optional reason (the compensating factor /
    the accepted-risk rationale) is recorded; the resolution trail + activity are logged.
    """
    finding.resolution_status = FindingResolutionStatus.ACCEPTED_RISK
    finding.resolution_note = reason
    finding.resolved_by_user_id = actor_user_id
    finding.resolved_at = utcnow()

    await log_activity(
        db,
        loan_file_id=finding.loan_file_id,
        activity_type=ActivityType.FINDING_RESOLVED,
        summary=f"Finding {finding.rule_id} accepted as risk",
        actor_user_id=actor_user_id,
        detail={
            "finding_id": str(finding.id),
            "rule_id": finding.rule_id,
            "resolution": FindingResolutionStatus.ACCEPTED_RISK.value,
            "reason": reason,
        },
    )
    await db.flush()
    return finding


class CannotRatifyError(Exception):
    """A finding that is not awaiting ratification cannot be ratified (LP-560).

    Ratification means "I reviewed the AI's judgment and agree". A deterministic verdict was never a
    judgment, so signing it would record a review that did not happen and make the audit trail claim
    more than it can support."""


class CannotApplyError(Exception):
    """An apply that could not perform its structured change (LP-558).

    Raised INSTEAD of closing the finding, so a processor never sees "resolved" over a loan file
    nothing was written to. The four ways to get here are a typo'd action name, a target row that is
    gone, an unparseable amount, and an ambiguous target."""


class CannotUndoError(Exception):
    """The finding is not in an undoable (resolved) state."""


# The resolutions Undo can reverse. RESOLVED / WAIVED (legacy LP-17 states) are not produced by
# the verification flow, so Undo does not handle them.
_UNDOABLE = (
    FindingResolutionStatus.APPLIED,
    FindingResolutionStatus.OVERRIDDEN,
    FindingResolutionStatus.ACCEPTED_RISK,
    # LP-560 — a ratification is a signature, and a signature given in error has to be retractable.
    # It made no data change, so reversing it is the OVERRIDDEN path: flip back to OPEN.
    FindingResolutionStatus.RATIFIED,
)


async def ratify_finding(
    db: AsyncSession,
    *,
    finding: Finding,
    actor_user_id: UUID,
    note: str | None = None,
) -> Finding:
    """Record that a human reviewed an AI judgment and AGREED with it (LP-560).

    Changes NO structured data — the loan is unchanged and no ratio moves. What changes is that the
    verdict now carries a person's name, which is the only thing that made shipping an uncalibrated
    judgment rule defensible in the first place.

    The note is OPTIONAL, deliberately, where Override's reason is required. Overriding contradicts the
    system and has to say why; ratifying agrees with what is already written on the finding, and
    demanding a second explanation of it would be friction on the common path — the path we want taken.
    """
    if not finding.details or not finding.details.get("ratification_pending"):
        raise CannotRatifyError(
            "this finding is not awaiting ratification — only an AI judgment can be ratified"
        )
    if finding.resolution_status is not FindingResolutionStatus.OPEN:
        raise CannotRatifyError(f"finding is already {finding.resolution_status.value}")

    finding.resolution_status = FindingResolutionStatus.RATIFIED
    finding.resolved_by_user_id = actor_user_id
    finding.resolved_at = utcnow()
    if note and note.strip():
        finding.resolution_note = note.strip()

    await log_activity(
        db,
        loan_file_id=finding.loan_file_id,
        activity_type=ActivityType.FINDING_RESOLVED,
        summary=f"Finding {finding.rule_id} ratified",
        actor_user_id=actor_user_id,
        detail={
            "finding_id": str(finding.id),
            "rule_id": finding.rule_id,
            "resolution": FindingResolutionStatus.RATIFIED.value,
        },
    )
    await db.flush()
    return finding


async def undo_finding(
    db: AsyncSession,
    *,
    finding: Finding,
    loan_file: LoanFile,
    actor_user_id: UUID,
) -> Finding:
    """Reverse a finding's resolution — Undo (LP-98). The reversal DIFFERS by resolution type.

    * **APPLIED** → **reverse the data change** by RESTORING the recorded pre-apply state
      (:attr:`applied_record` — the one source of truth, LP-97 verified it captures enough): the
      added liability is removed, or the corrected income restored to its prior value — EXACTLY,
      not approximated. The DTI/LTV then recompute back (they read the structured data live), and
      the recompute hook marks verification stale so the (now un-applied) issue re-detects.
    * **OVERRIDDEN** / **ACCEPTED_RISK** / **RATIFIED** → just flip back to OPEN (they made no data
      change — an
      override dismissed it; accept-risk acknowledged it).

    The finding returns to **OPEN** and its resolution trail is cleared. Audited
    (``FINDING_UNDONE``, who / when / the reversal). ``flush`` only; the caller owns the
    transaction. Raises :class:`CannotUndoError` if the finding is not resolved.
    """
    prior = finding.resolution_status
    if prior not in _UNDOABLE:
        raise CannotUndoError(f"finding is {prior.value}, not a resolved state that can be undone")

    reversal: dict[str, Any] = {"undone_from": prior.value}
    if prior is FindingResolutionStatus.APPLIED:
        reversal["reversed_change"] = await _reverse_applied_change(
            db, finding=finding, loan_file=loan_file
        )
        # The structured data changed back → the deterministic rules + calculators should
        # recompute, and the un-applied issue should re-detect on the next run (LP-94 compose).
        await mark_recompute_needed(db, loan_file=loan_file)

    finding.resolution_status = FindingResolutionStatus.OPEN
    finding.resolution_note = None
    finding.resolved_by_user_id = None
    finding.resolved_at = None
    finding.applied_record = None  # the pre-apply state has been restored; nothing left to reverse

    await log_activity(
        db,
        loan_file_id=finding.loan_file_id,
        activity_type=ActivityType.FINDING_UNDONE,
        summary=f"Undid {prior.value} on finding {finding.rule_id}",
        actor_user_id=actor_user_id,
        detail={"finding_id": str(finding.id), "rule_id": finding.rule_id, **reversal},
    )
    await db.flush()
    return finding


async def _reverse_applied_change(
    db: AsyncSession, *, finding: Finding, loan_file: LoanFile
) -> dict[str, Any]:
    """Undo the structured-data change an APPLIED finding performed — the EXACT inverse.

    Restores from the recorded :attr:`applied_record` (LP-75/97), never an approximation:
    ``add_liability`` → soft-delete the exact liability that was added; ``correct_income`` →
    restore the income item to its recorded prior (``from``) value. Tenant-checked. Returns a
    record of what was reversed (for the audit).
    """
    record = finding.applied_record or {}
    action = record.get("action")

    if action == "add_liability":
        raw_id = record.get("liability_id")
        if isinstance(raw_id, str):
            liability = await db.get(StatedLiability, UUID(raw_id))
            if (
                liability is not None
                and liability.loan_file_id == loan_file.id
                and liability.deleted_at is None
            ):
                liability.deleted_at = utcnow()  # remove the exact row the apply added
                await db.flush()
                return {"action": "remove_liability", "liability_id": raw_id}
        return {"action": "remove_liability", "applied": False}

    # LP-558 — the inverse of each new apply. Undo restores from `applied_record`, never an
    # approximation: a money correction records its `from` value precisely so it can be put back.
    if action == "correct_liability_payment":
        return await _restore_liability_payment(db, loan_file=loan_file, record=record)

    if action in ("correct_purchase_price", "correct_valuation"):
        restored: dict[str, Any] = await _restore_property_money(
            db, loan_file=loan_file, record=record
        )
        return restored

    if action == "correct_income":
        return await _restore_income(db, loan_file=loan_file, record=record)

    # Unknown / no-op apply (a novel finding with no deterministic remediation): nothing to reverse.
    return {"action": action, "reversed": False}


async def _restore_income(
    db: AsyncSession, *, loan_file: LoanFile, record: dict[str, Any]
) -> dict[str, Any]:
    """Restore a stated income item to its recorded pre-apply value (tenant-checked)."""
    raw_id = record.get("income_item_id")
    prior = _to_money(record.get("from"))
    if not isinstance(raw_id, str):
        return {"action": "restore_income", "reversed": False}
    item = await db.get(StatedIncomeItem, UUID(raw_id))
    if item is None or item.deleted_at is not None:
        return {"action": "restore_income", "reversed": False}
    borrower = await db.get(Borrower, item.borrower_id)
    if borrower is None or borrower.loan_file_id != loan_file.id:
        return {"action": "restore_income", "reversed": False}
    item.monthly_amount = prior  # the exact recorded prior value, not a computed guess
    await db.flush()
    return {
        "action": "restore_income",
        "income_item_id": raw_id,
        "restored_to": _stringify_money(prior),
    }


_STATUS_TO_PRIORITY = {
    FindingStatus.RED: NeedsItemPriority.BLOCKING,
    FindingStatus.YELLOW: NeedsItemPriority.STANDARD,
}


async def request_documents_in_bulk(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    by_document: dict[str, list[Finding]],
    actor_user_id: UUID,
    note: str | None = None,
) -> list[NeedsItem]:
    """Create ONE needs item per DOCUMENT, from many findings at once (LP-562).

    ONE PER DOCUMENT, NOT ONE PER FINDING, and that is the whole reason this exists rather than a loop
    over `request_docs_for_finding`. On the file that prompted it, nine findings wanted five distinct
    documents — four CR-6 rows all want the same tri-merge credit report, and CR-13 wants it again in
    different words. Requesting per finding would put nine items on the needs list for five documents,
    five of them near-duplicate credit-report asks whose titles are whole finding messages.

    The title is the DOCUMENT, not the finding's prose: a needs list is read as a shopping list, and
    "Credit report" is what a processor puts in an email. Which rules are waiting on it goes in the
    description, where it explains the ask without becoming the ask.

    ALREADY-REQUESTED DOCUMENTS ARE SKIPPED. A second click must not produce a second copy — a
    duplicate request is worse than no button, because the borrower gets asked twice for one thing.
    """
    existing = {
        row.needs_type
        for row in (
            (
                await db.execute(
                    only_active(
                        select(NeedsItem).where(
                            NeedsItem.loan_file_id == loan_file.id,
                            NeedsItem.status == NeedsItemStatus.PENDING,
                        ),
                        NeedsItem,
                    )
                )
            )
            .scalars()
            .all()
        )
        if row.needs_type
    }

    created: list[NeedsItem] = []
    for document, findings in by_document.items():
        slug = document.strip().lower().replace(" ", "_")
        if not slug or slug in existing:
            continue
        rules = ", ".join(sorted({f.rule_id for f in findings}))
        first = findings[0]
        item = await create_needs_item(
            db,
            loan_file_id=loan_file.id,
            title=document[:200],
            needs_type=slug,
            origin=NeedsItemOrigin.FINDING,
            priority=_STATUS_TO_PRIORITY.get(first.status, NeedsItemPriority.STANDARD),
            disposition=NeedsItemDisposition.CONFIRMED,
            description=note,
            # NOT `source_finding_id`: that column's foreign key points at `document_findings`, a
            # different table, so it cannot reference a verification finding. The linkage a request can
            # carry is therefore textual — the rule ids in `reasoning` — and `request_docs_for_finding`
            # has the same limit for the same reason.
            reasoning=f"Requested from verification findings: {rules}",
        )
        existing.add(slug)
        created.append(item)

    if created:
        await log_activity(
            db,
            loan_file_id=loan_file.id,
            activity_type=ActivityType.FINDING_RESOLVED,
            summary=f"Requested {len(created)} document(s) from verification findings",
            actor_user_id=actor_user_id,
            detail={"documents": [item.title for item in created]},
        )
    await db.flush()
    return created


async def request_docs_for_finding(
    db: AsyncSession,
    *,
    finding: Finding,
    actor_user_id: UUID,
    note: str | None = None,
) -> NeedsItem:
    """Create a needs-list item FROM a finding (LP-88) — the "request docs" action.

    Generates a ``FINDING``-origin needs item (the doc request the borrower must satisfy)
    with the priority derived from the finding severity, and records a note on the finding
    that the docs were requested (so the tab shows the linkage). Does NOT resolve the
    finding — it stays open until the request is satisfied. The needs item is the artifact
    the needs list + Phase-4 communication act on. ``flush`` only.
    """
    title = f"Documents for: {finding.message}"[:200]
    item = await create_needs_item(
        db,
        loan_file_id=finding.loan_file_id,
        title=title,
        origin=NeedsItemOrigin.FINDING,
        priority=_STATUS_TO_PRIORITY.get(finding.status, NeedsItemPriority.STANDARD),
        disposition=NeedsItemDisposition.CONFIRMED,  # a processor-requested need is real
        description=note,
        reasoning=f"Requested from verification finding {finding.rule_id}",
    )
    # Mark the finding so the tab shows docs were requested (without resolving it).
    requested = {
        "by": str(actor_user_id),
        "at": utcnow().isoformat(),
        "needs_item_id": str(item.id),
    }
    finding.details = {**finding.details, "docs_requested": requested}

    await log_activity(
        db,
        loan_file_id=finding.loan_file_id,
        activity_type=ActivityType.NEEDS_ITEM_CREATED,
        summary=f"Requested docs from finding {finding.rule_id}",
        actor_user_id=actor_user_id,
        detail={
            "finding_id": str(finding.id),
            "rule_id": finding.rule_id,
            "needs_item_id": str(item.id),
        },
    )
    await db.flush()
    return item


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

    # LP-558 — the loan-writing half of ADR "Apply writes the finding into the loan". Each targets a
    # different structured surface, and the calculators recompute from whichever moved.
    if action == "correct_liability_payment":
        return await _correct_liability_payment(db, loan_file=loan_file, spec=spec)

    if action == "correct_purchase_price":
        return await _correct_property_money(
            db, loan_file=loan_file, spec=spec, column="purchase_price"
        )

    if action == "correct_valuation":
        return await _correct_property_money(
            db, loan_file=loan_file, spec=spec, column="valuation_amount"
        )

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


async def _restore_liability_payment(
    db: AsyncSession, *, loan_file: LoanFile, record: dict[str, Any]
) -> dict[str, Any]:
    """Put a corrected liability payment back to its recorded prior value (LP-558's undo half)."""
    raw_id, prior = record.get("liability_id"), _to_money(record.get("from"))
    if not isinstance(raw_id, str):
        return {"action": "restore_liability_payment", "applied": False}
    liability = await db.get(StatedLiability, UUID(raw_id))
    if liability is None or liability.loan_file_id != loan_file.id:
        return {"action": "restore_liability_payment", "applied": False}
    liability.monthly_payment = prior  # `from` may legitimately have been null
    await db.flush()
    return {"action": "restore_liability_payment", "liability_id": raw_id}


async def _restore_property_money(
    db: AsyncSession, *, loan_file: LoanFile, record: dict[str, Any]
) -> dict[str, Any]:
    """Put a corrected price or valuation back (LP-558's undo half)."""
    column = (
        "purchase_price" if record.get("action") == "correct_purchase_price" else "valuation_amount"
    )
    raw_id, prior = record.get("property_id"), _to_money(record.get("from"))
    if not isinstance(raw_id, str):
        return {"action": f"restore_{column}", "applied": False}
    prop = await db.get(Property, UUID(raw_id))
    if prop is None or prop.loan_file_id != loan_file.id:
        return {"action": f"restore_{column}", "applied": False}
    setattr(prop, column, prior)
    await db.flush()
    return {"action": f"restore_{column}", "property_id": raw_id}


async def _correct_liability_payment(
    db: AsyncSession, *, loan_file: LoanFile, spec: dict[str, Any]
) -> dict[str, Any]:
    """Raise a stated liability's monthly payment to the figure the documents show (DT-6).

    TARGETED BY HOLDER NAME, NOT BY A ROW ID, and that is forced rather than chosen. A governed
    rule works on the SNAPSHOT — its subjects are content-ids (LP-312), never `stated_liabilities`
    primary keys — so it cannot name a DB row the way the legacy cross-source findings can. The holder
    is the business key both sides already share.

    EXACTLY ONE MATCH, OR NOTHING. Two liabilities from the same holder (a card and a HELOC with the
    same bank) are indistinguishable here, and picking either would silently edit the wrong debt. An
    ambiguous match declines and the processor edits it by hand.
    """
    holder = spec.get("holder_name")
    new_payment = _to_money(spec.get("monthly_payment"))
    if not isinstance(holder, str) or not holder.strip() or new_payment is None:
        return {"action": "correct_liability_payment", "applied": False}

    rows = (
        (
            await db.execute(
                only_active(
                    select(StatedLiability).where(
                        StatedLiability.loan_file_id == loan_file.id,
                        StatedLiability.holder_name == holder,
                    ),
                    StatedLiability,
                )
            )
        )
        .scalars()
        .all()
    )
    if len(rows) != 1:
        return {"action": "correct_liability_payment", "applied": False}

    liability = rows[0]
    prior = liability.monthly_payment
    liability.monthly_payment = new_payment
    await db.flush()
    return {
        "action": "correct_liability_payment",
        "liability_id": str(liability.id),
        "holder_name": holder,
        "from": _stringify_money(prior),
        "to": _stringify_money(new_payment),
    }


async def _correct_property_money(
    db: AsyncSession, *, loan_file: LoanFile, spec: dict[str, Any], column: str
) -> dict[str, Any]:
    """Correct the subject property's price or valuation — the two inputs LTV is computed from.

    No targeting problem: a loan file has ONE subject property, so unlike a liability there is nothing
    to disambiguate.
    """
    action = "correct_purchase_price" if column == "purchase_price" else "correct_valuation"
    new_value = _to_money(spec.get("value"))
    if new_value is None:
        return {"action": action, "applied": False}

    prop = (
        (
            await db.execute(
                only_active(select(Property).where(Property.loan_file_id == loan_file.id), Property)
            )
        )
        .scalars()
        .first()
    )
    if prop is None:
        return {"action": action, "applied": False}

    prior = getattr(prop, column)
    setattr(prop, column, new_value)
    await db.flush()
    return {
        "action": action,
        "property_id": str(prop.id),
        "from": _stringify_money(prior),
        "to": _stringify_money(new_value),
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
