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
from app.models.document import Document, DocumentStatus
from app.models.needs_item import NeedsItem, NeedsItemDisposition, NeedsItemOrigin
from app.schemas.needs_item import (
    NeedsItemAdjust,
    NeedsItemCreate,
    NeedsItemPublic,
    NeedsItemReason,
)
from app.services.activity_log import log_activity
from app.services.documents import list_documents
from app.services.needs_dedup import confirm_duplicate_merge, dismiss_duplicate_flag
from app.services.needs_engine import (
    confirm_need_coverage,
    documents_matching_need,
    needs_coverage_confirmation,
    record_need_correction,
    waive_need,
)
from app.services.needs_items import (
    adjust_needs_item,
    create_needs_item,
    get_needs_item,
    list_needs_items,
)


async def _completed_documents(db: DbSession, loan_file_id: UUID) -> list[Document]:
    """The file's COMPLETED documents — the source for the LP-109 derive-on-read matching set."""
    docs = await list_documents(db, loan_file_id=loan_file_id)
    return [d for d in docs if d.status is DocumentStatus.COMPLETED]


def _public(need: NeedsItem, completed: list[Document]) -> NeedsItemPublic:
    """Build the response with the derived matching-document set (LP-109) — the FULL set for a
    graded need (so the processor confirms coverage against all the evidence); a simple-presence
    need keeps its single satisfying document."""
    matches = (
        documents_matching_need(need, completed) if needs_coverage_confirmation(need) else None
    )
    return NeedsItemPublic.from_model(need, matching_documents=matches)


async def _public_one(db: DbSession, loan_file_id: UUID, need: NeedsItem) -> NeedsItemPublic:
    return _public(need, await _completed_documents(db, loan_file_id))


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
    completed = await _completed_documents(db, loan_file.id)  # loaded once (LP-109, no N+1)
    return [_public(item, completed) for item in items]


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
    return await _public_one(db, loan_file.id, created)


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
    return await _public_one(db, loan_file.id, need)


@router.post("/{needs_item_id}/confirm-coverage", response_model=NeedsItemPublic)
async def confirm_coverage(
    loan_file: ScopedLoanFile,
    needs_item_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> NeedsItemPublic:
    """Confirm a graded need's COVERAGE (LP-108): RECEIVED → VERIFIED.

    A matched document put the need in RECEIVED ("documents attached — confirm coverage"); the
    processor, having judged the full coverage the system can't (all accounts / months / years),
    confirms it. Distinct from ``/confirm`` (which confirms an AI PROPOSAL's disposition).
    """
    need = await _scoped_need(db, loan_file.id, needs_item_id)
    await confirm_need_coverage(db, need=need)
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.NEEDS_ITEM_SATISFIED,
        summary=f"Confirmed coverage: {need.title}",
        actor_user_id=current_user.id,
        detail={"needs_item_id": str(need.id)},
    )
    await db.commit()
    return await _public_one(db, loan_file.id, need)


@router.post("/{needs_item_id}/merge-duplicate", response_model=NeedsItemPublic)
async def merge_duplicate(
    loan_file: ScopedLoanFile,
    needs_item_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> NeedsItemPublic:
    """Confirm an AI-flagged possible-duplicate (LP-111): merge this need into its flagged twin.

    The processor agrees the two are the same ask; this need is folded into its ``possible_duplicate_of``
    twin (provenance unioned) and set aside. Returns the surviving need. If the twin is gone, the
    stale flag is cleared and this need kept (never a silent drop).
    """
    need = await _scoped_need(db, loan_file.id, needs_item_id)
    survivor = await confirm_duplicate_merge(db, need=need)
    kept = survivor if survivor is not None else need
    if survivor is not None:
        await log_activity(
            db,
            loan_file_id=loan_file.id,
            activity_type=ActivityType.NEEDS_ITEM_DISMISSED,
            summary=f"Merged duplicate need: {need.title}",
            actor_user_id=current_user.id,
            detail={"needs_item_id": str(need.id), "merged_into": str(survivor.id)},
        )
    await db.commit()
    return await _public_one(db, loan_file.id, kept)


@router.post("/{needs_item_id}/not-duplicate", response_model=NeedsItemPublic)
async def not_duplicate(
    loan_file: ScopedLoanFile,
    needs_item_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> NeedsItemPublic:
    """Dismiss an AI duplicate flag (LP-111): "not a duplicate — keep both".

    Clears the ``possible_duplicate_of`` flag and marks it reviewed so the AI pass never re-flags
    this pair. Both needs survive (the under-merge safety — never a wrongly-dropped need).
    """
    need = await _scoped_need(db, loan_file.id, needs_item_id)
    await dismiss_duplicate_flag(db, need=need)
    await db.commit()
    return await _public_one(db, loan_file.id, need)


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
    return await _public_one(db, loan_file.id, need)


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
    return await _public_one(db, loan_file.id, need)


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
    return await _public_one(db, loan_file.id, need)
