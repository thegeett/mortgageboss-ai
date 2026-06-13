"""Lender endpoints (LP-32).

A single company-scoped list, to populate the intake form's lender dropdown.
Auth-gated and scoped to ``current_user.company_id``; returns an empty list when
the company has no lenders (lenders are seeded later, LP-48).
"""

from fastapi import APIRouter

from app.api.dependencies import CurrentUser
from app.core.database import DbSession
from app.schemas.lender import LenderSummary
from app.services.lenders import list_lenders

router = APIRouter(prefix="/lenders", tags=["lenders"])


@router.get("", response_model=list[LenderSummary])
async def list_files(db: DbSession, current_user: CurrentUser) -> list[LenderSummary]:
    """List the caller's company's lenders (for the intake dropdown)."""
    lenders = await list_lenders(db, company_id=current_user.company_id)
    return [LenderSummary.model_validate(lender) for lender in lenders]
