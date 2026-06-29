"""Overlay admin endpoints (LP-87) — view + edit lender overlays (ADMIN-gated).

Closes the LP-80 hand-edited-JSON deferral. ADMIN-only (overlays are company config, not
per-processor) and tenant-scoped (a lender resolves within the caller's company → 404
otherwise). A change ``reason`` is required and the edit is audited (from→to). Editing an
overlay returns the recomposed effect-legible view (each override's effective threshold).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import CurrentCompanyId, CurrentUser, require_role
from app.core.database import DbSession
from app.models.user import UserRole
from app.schemas.lender import LenderSummary
from app.schemas.overlay_admin import LenderOverlayView, OverlayUpdateRequest
from app.services.lenders import list_lenders
from app.services.overlay_admin import (
    UnknownOverlayRuleError,
    build_overlay_view,
    get_lender,
    update_lender_overlay,
)

router = APIRouter(
    prefix="/admin/lenders",
    tags=["overlay-admin"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],  # admin-only surface
)

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lender not found")


@router.get("", response_model=list[LenderSummary])
async def list_overlay_lenders(db: DbSession, company_id: CurrentCompanyId) -> list[LenderSummary]:
    """The admin's company's lenders (each editable for its overlay)."""
    lenders = await list_lenders(db, company_id=company_id)
    return [LenderSummary.model_validate(lender) for lender in lenders]


@router.get("/{lender_id}/overlay", response_model=LenderOverlayView)
async def get_overlay(
    lender_id: UUID, db: DbSession, company_id: CurrentCompanyId
) -> LenderOverlayView:
    """View one lender's overlay — each override's effect made legible (base → effective)."""
    lender = await get_lender(db, company_id=company_id, lender_id=lender_id)
    if lender is None:
        raise _NOT_FOUND
    return build_overlay_view(lender)


@router.put("/{lender_id}/overlay", response_model=LenderOverlayView)
async def put_overlay(
    lender_id: UUID,
    payload: OverlayUpdateRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> LenderOverlayView:
    """Replace the lender's overlay overrides (reason required, audited); return the view."""
    try:
        lender = await update_lender_overlay(
            db,
            company_id=current_user.company_id,
            lender_id=lender_id,
            request=payload,
            actor_user_id=current_user.id,
        )
    except UnknownOverlayRuleError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown rule_id: {exc}",
        ) from exc
    if lender is None:
        raise _NOT_FOUND
    await db.commit()
    return build_overlay_view(lender)
