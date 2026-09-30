"""LP-940 — withdraw a condition she added by hand, entered in error. ADR-404 as amended.

A hand-added condition is HER entry, not the lender's demand, so she may take it back. Withdrawal is the
existing soft delete (`deleted_at`) plus a `condition_withdrawn` event carrying her reason; nothing is
removed, and Undo (`restore`) puts it back as it was. Every reader that lists, counts, plans, drafts or
packages conditions skips a soft-deleted one; the few that loaded one by id without looking are fixed
beside this module (drafts here, the package and the figures check in their own).

Refused, with a sentence she reads, for a sheet condition (ADR-404: only the lender clears those), one the
lender has answered on (a recorded verdict is the lender's word, not hers), and one that went to the
lender in a submitted package (the lender has seen it).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.communication import Communication, CommunicationStatus
from app.models.condition import Condition, ConditionOrigin
from app.models.condition_draft import ConditionDraft
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_item import ConditionItem
from app.models.condition_package import ConditionPackage, PackageStatus
from app.models.loan_file import LoanFile

logger = structlog.get_logger(__name__)

REASON_MAX = 500

NOT_HAND_ADDED = (
    "Only a condition you added by hand can be withdrawn. One from the lender's sheet stays until the "
    "lender clears or waives it."
)
LENDER_ANSWERED = "The lender's answer is recorded on it, so it stays on the file."
NO_REASON = "Say why — the reason is kept in the history."
NOT_WITHDRAWN = "This condition is not withdrawn."


class WithdrawRefused(Exception):
    """A refusal she reads, as the sentence says it."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Withdrawn:
    """One row of the "Withdrawn (n)" section."""

    id: UUID
    lender_code: str | None
    verbatim_text: str
    reason: str
    withdrawn_at: datetime


def _event(
    condition: Condition, kind: ConditionEventKind, detail: dict[str, Any], actor: UUID
) -> ConditionEvent:
    return ConditionEvent(
        company_id=condition.company_id,
        loan_file_id=condition.loan_file_id,
        condition_id=condition.id,
        round_id=condition.last_seen_round_id,
        kind=kind,
        actor_user_id=actor,
        detail=detail,
    )


async def _submitted_on(db: AsyncSession, condition: Condition) -> datetime | None:
    """When a submitted package holding this condition was submitted, or None."""
    packages = (
        await db.execute(
            select(ConditionPackage).where(
                ConditionPackage.loan_file_id == condition.loan_file_id,
                ConditionPackage.status == PackageStatus.SUBMITTED,
            )
        )
    ).scalars()
    for package in packages:
        if any(
            row.get("condition_id") == str(condition.id) and row.get("included", True)
            for row in package.rows or []
        ):
            return package.submitted_at or package.updated_at
    return None


async def _lender_answered(db: AsyncSession, condition: Condition) -> bool:
    return (
        await db.scalar(
            select(ConditionEvent.id)
            .where(
                ConditionEvent.condition_id == condition.id,
                ConditionEvent.kind == ConditionEventKind.CONDITION_VERDICT_RECORDED,
            )
            .limit(1)
        )
    ) is not None


async def _leave_unsent_drafts(db: AsyncSession, condition: Condition) -> None:
    """Out of every draft not yet sent: its items unlinked, its own question draft discarded. A SENT draft
    is history and keeps its items."""
    from app.services.condition_drafts import _discard

    loan_file = await db.get(LoanFile, condition.loan_file_id)
    assert loan_file is not None
    drafts = {
        d.id: d
        for d in (
            await db.execute(
                select(ConditionDraft).where(ConditionDraft.loan_file_id == condition.loan_file_id)
            )
        ).scalars()
    }

    async def unsent(draft: ConditionDraft) -> bool:
        message = await db.get(Communication, draft.communication_id)
        return message is not None and message.status is CommunicationStatus.DRAFT

    items = (
        await db.execute(
            select(ConditionItem).where(
                ConditionItem.condition_id == condition.id, ConditionItem.draft_id.is_not(None)
            )
        )
    ).scalars()
    for item in items:
        draft = drafts.get(item.draft_id) if item.draft_id else None
        if draft is not None and await unsent(draft):
            item.draft_id = None
    for draft in drafts.values():
        if draft.condition_id == condition.id and await unsent(draft):
            await _discard(db, loan_file=loan_file, draft=draft)
    await db.flush()


async def withdraw(
    db: AsyncSession, *, condition: Condition, reason: str, actor_user_id: UUID
) -> None:
    """Withdraw a hand-added condition entered in error. Flushes; the caller commits."""
    text = (reason or "").strip()
    if condition.origin is not ConditionOrigin.MANUAL:
        raise WithdrawRefused(NOT_HAND_ADDED)
    if await _lender_answered(db, condition):
        raise WithdrawRefused(LENDER_ANSWERED)
    submitted = await _submitted_on(db, condition)
    if submitted is not None:
        raise WithdrawRefused(
            f"It went to the lender in the package submitted on {submitted:%m/%d/%Y}, so it stays on "
            "the file."
        )
    if not text:
        raise WithdrawRefused(NO_REASON)
    await _leave_unsent_drafts(db, condition)
    condition.deleted_at = datetime.now(UTC)
    db.add(
        _event(
            condition,
            ConditionEventKind.CONDITION_WITHDRAWN,
            {"reason": text[:REASON_MAX]},
            actor_user_id,
        )
    )
    await db.flush()
    from app.services.condition_drafts import resync_file

    await resync_file(db, loan_file_id=condition.loan_file_id, actor_user_id=actor_user_id)
    logger.info(
        "condition_withdrawn",
        condition_id=str(condition.id),
        loan_file_id=str(condition.loan_file_id),
    )


async def restore(db: AsyncSession, *, condition: Condition, actor_user_id: UUID) -> None:
    """Undo a withdrawal: the condition is back, its asks return to the drafts. Flushes."""
    # WITHDRAWAL IS THE ONLY WAY A CONDITION IS SOFT-DELETED (measured: nothing else sets
    # `conditions.deleted_at`), so "deleted" is "withdrawn". If another path ever deletes conditions,
    # this must learn to tell the two apart; `test_only_a_withdrawal_deletes_a_condition` fails first.
    if condition.deleted_at is None:
        raise WithdrawRefused(NOT_WITHDRAWN)
    condition.deleted_at = None
    db.add(_event(condition, ConditionEventKind.CONDITION_RESTORED, {}, actor_user_id))
    await db.flush()
    from app.services.condition_drafts import resync_file

    await resync_file(db, loan_file_id=condition.loan_file_id, actor_user_id=actor_user_id)
    logger.info(
        "condition_restored",
        condition_id=str(condition.id),
        loan_file_id=str(condition.loan_file_id),
    )


async def withdrawn_for_file(db: AsyncSession, *, loan_file_id: UUID) -> list[Withdrawn]:
    """The "Withdrawn (n)" section: withdrawn hand-added conditions, the latest withdrawal first."""
    conditions = {
        c.id: c
        for c in (
            await db.execute(
                select(Condition).where(
                    Condition.loan_file_id == loan_file_id,
                    Condition.deleted_at.is_not(None),
                    Condition.origin == ConditionOrigin.MANUAL,
                )
            )
        ).scalars()
    }
    if not conditions:
        return []
    events = (
        await db.execute(
            select(ConditionEvent)
            .where(
                ConditionEvent.condition_id.in_(conditions),
                ConditionEvent.kind.in_(
                    (ConditionEventKind.CONDITION_WITHDRAWN, ConditionEventKind.CONDITION_RESTORED)
                ),
            )
            .order_by(ConditionEvent.occurred_at)
        )
    ).scalars()
    latest: dict[UUID, ConditionEvent] = {}
    for event in events:
        if event.condition_id is not None:
            latest[event.condition_id] = event
    out = [
        Withdrawn(
            id=cid,
            lender_code=conditions[cid].lender_code,
            verbatim_text=conditions[cid].verbatim_text,
            reason=str((event.detail or {}).get("reason") or ""),
            withdrawn_at=event.occurred_at,
        )
        for cid, event in latest.items()
        if event.kind is ConditionEventKind.CONDITION_WITHDRAWN
    ]
    return sorted(out, key=lambda row: row.withdrawn_at, reverse=True)
