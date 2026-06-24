"""Needs-list engine (LP-68) — the DETERMINISTIC backbone of the needs list.

This is the deterministic part (NO AI — the case-by-case intelligence is LP-69). It
provides:

  * **State transitions** — the five-state arrival lifecycle (Pending → Received →
    Verified | Rejected; any → Waived), guarded by a valid-transition map.
  * **Satisfaction-matching** — when a document is processed, advance a matching
    pending need (TYPE-LEVEL: a need for ``needs_type == document_type``). Runs
    **serialized per loan file** (the Celery task in :mod:`app.tasks.needs` wraps
    this with :func:`loan_file_needs_lock`).
  * **The thin deterministic floor** — a small set of near-certain needs seeded from
    the stated MISMO data (employment income → pay stubs + W-2s; a purchase →
    purchase agreement; stated assets → a bank statement). The reliable baseline
    LP-69's AI augments.
  * **Source-agnostic ingestion** — a need carries its ``origin`` (floor / suggestion
    / ai_reasoning). :func:`ingest_suggested_need` turns an LP-67 ``SuggestedNeed``
    into a need (carrying the reasoning + source-finding link); LP-69 proposals
    ingest the same way.

Quantity/recency-granular matching ("2 pay stubs", "within 30 days") is a documented
future refinement; matching is type-level now.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Literal
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis_client
from app.models.base import utcnow
from app.models.borrower import Borrower
from app.models.document import Document, DocumentCategory, DocumentStatus
from app.models.helpers import only_active
from app.models.loan_file import LoanFile, LoanPurpose
from app.models.needs_item import (
    NeedsItem,
    NeedsItemDisposition,
    NeedsItemOrigin,
    NeedsItemStatus,
)
from app.models.stated_financials import StatedAsset, StatedIncomeItem
from app.services.needs_items import create_needs_item

if TYPE_CHECKING:
    from app.services.implications import SuggestedNeed

logger = structlog.get_logger(__name__)


# --------------------------------------------------------------------------- #
# State transitions (deterministic; guarded)
# --------------------------------------------------------------------------- #

# The locked arrival lifecycle + the orthogonal REQUESTED (LP-19). "any → WAIVED",
# plus sensible re-open paths (a rejected need can re-receive; a waived/verified can
# re-open to pending if a processor reverts).
_VALID_TRANSITIONS: dict[NeedsItemStatus, set[NeedsItemStatus]] = {
    NeedsItemStatus.PENDING: {
        NeedsItemStatus.REQUESTED,
        NeedsItemStatus.RECEIVED,
        NeedsItemStatus.WAIVED,
    },
    NeedsItemStatus.REQUESTED: {
        NeedsItemStatus.PENDING,
        NeedsItemStatus.RECEIVED,
        NeedsItemStatus.WAIVED,
    },
    NeedsItemStatus.RECEIVED: {
        NeedsItemStatus.VERIFIED,
        NeedsItemStatus.REJECTED,
        NeedsItemStatus.WAIVED,
    },
    NeedsItemStatus.VERIFIED: {NeedsItemStatus.PENDING, NeedsItemStatus.WAIVED},
    NeedsItemStatus.REJECTED: {
        NeedsItemStatus.PENDING,
        NeedsItemStatus.RECEIVED,
        NeedsItemStatus.WAIVED,
    },
    NeedsItemStatus.WAIVED: {NeedsItemStatus.PENDING},
}


class InvalidNeedTransition(ValueError):
    """Raised when a needs-item state transition is not allowed (guarded)."""


async def transition_need(
    db: AsyncSession,
    *,
    need: NeedsItem,
    to_state: NeedsItemStatus,
    document_id: UUID | None = None,
    reason: str | None = None,
) -> NeedsItem:
    """Move a need to ``to_state`` if the transition is valid (else raise).

    Side effects per target state: RECEIVED links the arriving document; VERIFIED
    stamps ``satisfied_at``; REJECTED/WAIVED record the ``reason`` (WAIVED also sets
    the disposition). Deterministic. Uses ``flush`` (the caller owns the transaction).
    """
    if to_state != need.status and to_state not in _VALID_TRANSITIONS.get(need.status, set()):
        raise InvalidNeedTransition(f"{need.status} -> {to_state} is not a valid transition")

    need.status = to_state
    if to_state is NeedsItemStatus.RECEIVED and document_id is not None:
        need.satisfied_by_document_id = document_id
    if to_state is NeedsItemStatus.VERIFIED:
        need.satisfied_at = utcnow()
    if to_state is NeedsItemStatus.REJECTED:
        need.reason = reason
    if to_state is NeedsItemStatus.WAIVED:
        need.reason = reason
        need.disposition = NeedsItemDisposition.WAIVED
    await db.flush()
    return need


async def waive_need(db: AsyncSession, *, need: NeedsItem, reason: str | None = None) -> NeedsItem:
    """Processor action: waive a need (any state → WAIVED), with a reason."""
    return await transition_need(db, need=need, to_state=NeedsItemStatus.WAIVED, reason=reason)


async def record_need_correction(
    db: AsyncSession,
    *,
    need: NeedsItem,
    action: Literal["confirm", "dismiss", "adjust"],
    note: str | None = None,
) -> NeedsItem:
    """Capture a processor's disposition of an (AI-)proposed need — the LP-69 signal.

    The disposition is recorded **on the need** (the captured signal): ``confirm`` /
    ``adjust`` → ``CONFIRMED`` (a real need); ``dismiss`` → ``DISMISSED`` + the need is
    waived (not a real need). The simple V1 *use* of this signal: the AI reasoning
    folds existing needs (incl. dismissed) into "already covered", so a dismissed
    proposal is not re-proposed. A richer corrections store + a full learning loop is
    a documented future evolution. The processor's confirm/adjust/dismiss UI is LP-70;
    this is the capture it calls. Uses ``flush``.
    """
    if action == "dismiss":
        # Dismissed = not a real need for this file → take it out of the open set,
        # then mark the disposition DISMISSED (more specific than the WAIVED the
        # transition sets).
        if need.status is not NeedsItemStatus.WAIVED:
            await transition_need(db, need=need, to_state=NeedsItemStatus.WAIVED, reason=note)
        need.disposition = NeedsItemDisposition.DISMISSED
    else:  # confirm / adjust — the processor kept it
        need.disposition = NeedsItemDisposition.CONFIRMED
    if note is not None:
        need.notes = note
    await db.flush()
    logger.info(
        "needs_item_correction",
        need_id=str(need.id),
        action=action,  # a category, not PII
        origin=need.origin,
    )
    return need


# --------------------------------------------------------------------------- #
# Satisfaction-matching (deterministic, type-level)
# --------------------------------------------------------------------------- #

# A need awaiting a document is in one of these (the orthogonal REQUESTED counts).
_OPEN_STATES = (NeedsItemStatus.PENDING, NeedsItemStatus.REQUESTED)


async def apply_document_to_needs(db: AsyncSession, document: Document) -> NeedsItem | None:
    """Advance the matching pending need for a just-processed document (LP-68).

    TYPE-LEVEL: finds the oldest open need on the document's loan file whose
    ``needs_type`` equals the document's ``document_type``, and advances it
    Received → Verified (the document passed — terminal ``COMPLETED``) | Rejected
    (it failed — ``NEEDS_REVIEW`` / ``FAILED``). Deterministic; no AI. No matching
    need (or no type) → no-op. **Runs serialized per loan file** (see
    :mod:`app.tasks.needs`), so concurrent arrivals never race on the shared state.
    """
    if not document.document_type:
        return None
    stmt = (
        select(NeedsItem)
        .where(
            NeedsItem.loan_file_id == document.loan_file_id,
            NeedsItem.needs_type == document.document_type,
            NeedsItem.status.in_(_OPEN_STATES),
        )
        .order_by(NeedsItem.created_at)
        .limit(1)
    )
    need = await db.scalar(only_active(stmt, NeedsItem))
    if need is None:
        return None

    await transition_need(db, need=need, to_state=NeedsItemStatus.RECEIVED, document_id=document.id)
    if document.status is DocumentStatus.COMPLETED:
        await transition_need(db, need=need, to_state=NeedsItemStatus.VERIFIED)
    else:  # NEEDS_REVIEW / FAILED — a document arrived but did not pass
        await transition_need(
            db,
            need=need,
            to_state=NeedsItemStatus.REJECTED,
            reason=f"A document arrived but did not pass processing ({document.status.value}).",
        )
    logger.info(
        "needs_item_advanced",
        need_id=str(need.id),
        document_id=str(document.id),
        new_status=need.status,
    )
    return need


# --------------------------------------------------------------------------- #
# The thin deterministic floor (from the stated MISMO data)
# --------------------------------------------------------------------------- #


async def _has_stated_employment_income(db: AsyncSession, loan_file_id: UUID) -> bool:
    """Any borrower on the file with a stated employment-income item."""
    stmt = (
        select(StatedIncomeItem.id)
        .join(Borrower, StatedIncomeItem.borrower_id == Borrower.id)
        .where(Borrower.loan_file_id == loan_file_id, StatedIncomeItem.employment_income.is_(True))
        .limit(1)
    )
    return await db.scalar(only_active(only_active(stmt, StatedIncomeItem), Borrower)) is not None


async def _has_stated_assets(db: AsyncSession, loan_file_id: UUID) -> bool:
    stmt = select(StatedAsset.id).where(StatedAsset.loan_file_id == loan_file_id).limit(1)
    return await db.scalar(only_active(stmt, StatedAsset)) is not None


async def seed_floor_needs(db: AsyncSession, loan_file: LoanFile) -> list[NeedsItem]:
    """Seed the THIN deterministic floor of near-certain needs from the stated data.

    Idempotent: if the file already has floor needs, this is a no-op (re-importing a
    MISMO file won't duplicate). The floor is intentionally thin — the bulk of the
    intelligence is LP-69's AI reasoning, which augments this baseline. Floor needs
    are ``origin=FLOOR`` and ``disposition=CONFIRMED`` (near-certain). Uses ``flush``.

    Flushes FIRST so the stated-data rules see the caller's just-added rows: the
    session runs ``autoflush=False`` (ADR), so ``StatedIncomeItem`` / ``StatedAsset``
    rows that a caller ``db.add``-ed but hasn't flushed are invisible to the SELECTs
    in :func:`_has_stated_employment_income` / :func:`_has_stated_assets`. Without
    this flush the employment (→ pay stubs + W-2) and asset (→ bank statements) rules
    silently miss the data and only the purchase rule (in-memory ``loan_purpose``)
    fires (LP-71.5).
    """
    await db.flush()
    existing = await db.scalar(
        only_active(
            select(NeedsItem.id)
            .where(
                NeedsItem.loan_file_id == loan_file.id,
                NeedsItem.origin == NeedsItemOrigin.FLOOR,
            )
            .limit(1),
            NeedsItem,
        )
    )
    if existing is not None:
        return []  # already seeded

    specs: list[tuple[str, str, DocumentCategory]] = []
    if await _has_stated_employment_income(db, loan_file.id):
        specs.append(("pay_stub", "Recent pay stubs", DocumentCategory.INCOME_EMPLOYMENT))
        specs.append(("w2", "W-2 (most recent year)", DocumentCategory.INCOME_EMPLOYMENT))
    if loan_file.loan_purpose is LoanPurpose.PURCHASE:
        specs.append(("purchase_agreement", "Purchase agreement", DocumentCategory.PROPERTY))
    if await _has_stated_assets(db, loan_file.id):
        specs.append(("bank_statement", "Bank statements", DocumentCategory.ASSETS))

    created: list[NeedsItem] = []
    for needs_type, title, category in specs:
        need = await create_needs_item(
            db,
            loan_file_id=loan_file.id,
            title=title,
            needs_type=needs_type,
            category=category,
            origin=NeedsItemOrigin.FLOOR,
            disposition=NeedsItemDisposition.CONFIRMED,
        )
        created.append(need)
    if created:
        logger.info("needs_floor_seeded", loan_file_id=str(loan_file.id), count=len(created))
    return created


# --------------------------------------------------------------------------- #
# Source-agnostic ingestion (LP-67 suggestions; LP-69 proposals ingest the same way)
# --------------------------------------------------------------------------- #


async def ingest_suggested_need(
    db: AsyncSession, *, loan_file_id: UUID, suggested: "SuggestedNeed"
) -> NeedsItem | None:
    """Turn an LP-67 ``SuggestedNeed`` into a needs item (source-agnostic, LP-68).

    Carries the reasoning + the source-finding link (traceable). ``origin=SUGGESTION``,
    ``disposition=PROPOSED`` (the processor confirms in LP-70). Idempotent per source
    finding: re-ingesting the same finding's suggestion is a no-op. Uses ``flush``.
    """
    if suggested.source_finding_id is not None:
        already = await db.scalar(
            only_active(
                select(NeedsItem.id)
                .where(
                    NeedsItem.loan_file_id == loan_file_id,
                    NeedsItem.source_finding_id == suggested.source_finding_id,
                )
                .limit(1),
                NeedsItem,
            )
        )
        if already is not None:
            return None
    return await create_needs_item(
        db,
        loan_file_id=loan_file_id,
        title=suggested.need_description,
        needs_type=suggested.need_type,
        origin=NeedsItemOrigin.SUGGESTION,
        disposition=NeedsItemDisposition.PROPOSED,
        reasoning=suggested.reasoning,
        source_finding_id=suggested.source_finding_id,
    )


# --------------------------------------------------------------------------- #
# Per-file serialization — the race fix (Redis lock, keyed on the loan file)
# --------------------------------------------------------------------------- #


@asynccontextmanager
async def loan_file_needs_lock(
    loan_file_id: UUID | str, *, timeout: int = 30, blocking_timeout: int = 30
) -> AsyncIterator[bool]:
    """A Redis lock keyed on the loan file — serializes needs updates PER FILE.

    Concurrent document arrivals for the SAME file acquire this one at a time (no
    race on the shared needs state); DIFFERENT files use different keys → parallel.
    Yields whether the lock was acquired (the caller proceeds either way — a missed
    lock just means another worker is applying, and a re-run is safe). ``timeout``
    auto-expires a held lock so a crashed worker never deadlocks the file.
    """
    client = get_redis_client()
    lock = client.lock(
        f"needs-lock:{loan_file_id}", timeout=timeout, blocking_timeout=blocking_timeout
    )
    acquired = await lock.acquire()
    try:
        yield bool(acquired)
    finally:
        if acquired:
            try:
                await lock.release()
            except Exception:  # the lock may have expired (timeout) — never crash on release
                logger.warning("needs_lock_release_failed", loan_file_id=str(loan_file_id))
