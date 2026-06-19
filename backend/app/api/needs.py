"""Needs-list endpoints (LP-34 read; LP-70 disposition writes) — nested under a file.

Like borrowers/property (LP-29), every route declares :data:`ScopedLoanFile`, so the
parent file is fetched and company-scope-checked **first** (``404`` if it isn't the
caller's) — the tenant gate. Needs items have no ``company_id``; they are reachable
only through a file the company owns, and a per-need action additionally 404s if the
need isn't in that file.

The writes are the **LP-70 disposition flow** — the AI proposes (LP-69), the
processor disposes: confirm / adjust / dismiss / waive / add. Each updates the need,
**captures the correction signal** (LP-69's improve-from-corrections — the
disposition recorded on the need), and is **audited** (an activity-log entry). The
endpoints commit explicitly (``get_db`` does not auto-commit).
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import CurrentUser, ScopedLoanFile
from app.core.database import DbSession
from app.models.activity_log import ActivityType
from app.models.needs_item import NeedsItem, NeedsItemDisposition, NeedsItemOrigin
from app.schemas.needs_item import (
    NeedsItemAdjust,
    NeedsItemCreate,
    NeedsItemPublic,
    NeedsItemReason,
)
from app.services.activity_log import log_activity
from app.services.needs_engine import record_need_correction, waive_need
from app.services.needs_items import (
    adjust_needs_item,
    create_needs_item,
    get_needs_item,
    list_needs_items,
)

router = APIRouter(prefix="/loan-files/{file_identifier}/needs", tags=["needs"])

_NEED_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Needs item not found"
)


async def _scoped_need(db: DbSession, loan_file_id: UUID, needs_item_id: UUID) -> NeedsItem:
    """Fetch a need within the (already company-scoped) file, or 404."""
    need = await get_needs_item(db, loan_file_id=loan_file_id, needs_item_id=needs_item_id)
    if need is None:
        raise _NEED_NOT_FOUND
    return need


@router.get("", response_model=list[NeedsItemPublic])
async def list_(loan_file: ScopedLoanFile, db: DbSession) -> list[NeedsItemPublic]:
    """List the file's needs items (blocking-first). File gate via the dependency."""
    items = await list_needs_items(db, loan_file_id=loan_file.id)
    return [NeedsItemPublic.from_model(item) for item in items]


@router.post("", response_model=NeedsItemPublic, status_code=status.HTTP_201_CREATED)
async def add(
    loan_file: ScopedLoanFile,
    payload: NeedsItemCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> NeedsItemPublic:
    """Add a need the AI missed (LP-70) — a processor-authored, confirmed need.

    A processor-added need is a real need, so it is created ``CONFIRMED`` (not a
    proposal). ``origin=MANUAL`` records the provenance (the correction signal: the
    AI missed it). Audited.
    """
    item = await create_needs_item(
        db,
        loan_file_id=loan_file.id,
        title=payload.title,
        description=payload.description,
        needs_type=payload.needs_type,
        category=payload.category,
        priority=payload.priority,
        borrower_id=payload.borrower_id,
        origin=NeedsItemOrigin.MANUAL,
        disposition=NeedsItemDisposition.CONFIRMED,
    )
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.NEEDS_ITEM_CREATED,
        summary=f"Added need: {item.title}",
        actor_user_id=current_user.id,
        detail={"needs_item_id": str(item.id), "needs_type": item.needs_type},
    )
    await db.commit()
    created = await _scoped_need(db, loan_file.id, item.id)
    return NeedsItemPublic.from_model(created)


@router.post("/{needs_item_id}/confirm", response_model=NeedsItemPublic)
async def confirm(
    loan_file: ScopedLoanFile,
    needs_item_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> NeedsItemPublic:
    """Confirm a proposed need (proposed → confirmed) — the human-in-the-loop signal."""
    need = await _scoped_need(db, loan_file.id, needs_item_id)
    await record_need_correction(db, need=need, action="confirm")
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.NEEDS_ITEM_CONFIRMED,
        summary=f"Confirmed need: {need.title}",
        actor_user_id=current_user.id,
        detail={"needs_item_id": str(need.id)},
    )
    await db.commit()
    return NeedsItemPublic.from_model(need)


@router.patch("/{needs_item_id}", response_model=NeedsItemPublic)
async def adjust(
    loan_file: ScopedLoanFile,
    needs_item_id: UUID,
    payload: NeedsItemAdjust,
    db: DbSession,
    current_user: CurrentUser,
) -> NeedsItemPublic:
    """Adjust a need's content (LP-70) — a correction signal; confirms the disposition."""
    need = await _scoped_need(db, loan_file.id, needs_item_id)
    await adjust_needs_item(
        db,
        needs_item=need,
        title=payload.title,
        description=payload.description,
        needs_type=payload.needs_type,
        priority=payload.priority,
    )
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.NEEDS_ITEM_ADJUSTED,
        summary=f"Adjusted need: {need.title}",
        actor_user_id=current_user.id,
        detail={"needs_item_id": str(need.id)},
    )
    await db.commit()
    return NeedsItemPublic.from_model(need)


@router.post("/{needs_item_id}/dismiss", response_model=NeedsItemPublic)
async def dismiss(
    loan_file: ScopedLoanFile,
    needs_item_id: UUID,
    payload: NeedsItemReason,
    db: DbSession,
    current_user: CurrentUser,
) -> NeedsItemPublic:
    """Dismiss a proposed need (doesn't apply) — a correction signal; the need is set aside."""
    need = await _scoped_need(db, loan_file.id, needs_item_id)
    await record_need_correction(db, need=need, action="dismiss", note=payload.reason)
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.NEEDS_ITEM_DISMISSED,
        summary=f"Dismissed need: {need.title}",
        actor_user_id=current_user.id,
        detail={"needs_item_id": str(need.id)},
    )
    await db.commit()
    return NeedsItemPublic.from_model(need)


@router.post("/{needs_item_id}/waive", response_model=NeedsItemPublic)
async def waive(
    loan_file: ScopedLoanFile,
    needs_item_id: UUID,
    payload: NeedsItemReason,
    db: DbSession,
    current_user: CurrentUser,
) -> NeedsItemPublic:
    """Waive a need (not required for this file), with a reason — any state → waived."""
    need = await _scoped_need(db, loan_file.id, needs_item_id)
    await waive_need(db, need=need, reason=payload.reason)
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.NEEDS_ITEM_WAIVED,
        summary=f"Waived need: {need.title}",
        actor_user_id=current_user.id,
        detail={"needs_item_id": str(need.id)},
    )
    await db.commit()
    return NeedsItemPublic.from_model(need)
