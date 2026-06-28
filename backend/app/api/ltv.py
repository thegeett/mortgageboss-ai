"""LTV calculator endpoints (LP-77) — mirrors the DTI calculator's endpoints.

``GET`` returns the full, transparent, auto-populated calculation (the three
ratios + the itemized breakdown); ``PUT`` / ``DELETE`` set and clear a per-field
override, recomputing in the response (the real-time recalc). Every route is
tenant-scoped (cross-company → 404). Overrides are audited in the service.
"""

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import CurrentUser
from app.core.database import DbSession
from app.schemas.ltv import LtvCalculation, LtvOverrideInput
from app.services.loan_files import get_loan_file
from app.services.ltv import (
    UnknownLtvFieldError,
    build_ltv_calculation,
    clear_ltv_override,
    set_ltv_override,
)

router = APIRouter(prefix="/loan-files", tags=["ltv"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan file not found")


@router.get("/{identifier}/ltv", response_model=LtvCalculation)
async def get_ltv(identifier: str, db: DbSession, current_user: CurrentUser) -> LtvCalculation:
    """The auto-populated, itemized LTV calculation for one of the caller's files."""
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    return await build_ltv_calculation(db, loan_file=loan_file)


@router.put("/{identifier}/ltv/overrides/{field_key}", response_model=LtvCalculation)
async def put_ltv_override(
    identifier: str,
    field_key: str,
    payload: LtvOverrideInput,
    db: DbSession,
    current_user: CurrentUser,
) -> LtvCalculation:
    """Override one LTV input (audited, persisted) and return the recomputed result."""
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    try:
        calculation = await set_ltv_override(
            db,
            loan_file=loan_file,
            field_key=field_key,
            data=payload,
            actor_user_id=current_user.id,
        )
    except UnknownLtvFieldError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown LTV input field"
        ) from exc
    await db.commit()
    return calculation


@router.delete("/{identifier}/ltv/overrides/{field_key}", response_model=LtvCalculation)
async def delete_ltv_override(
    identifier: str, field_key: str, db: DbSession, current_user: CurrentUser
) -> LtvCalculation:
    """Clear an override (revert to the auto value), audited; return the recompute."""
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    calculation = await clear_ltv_override(
        db, loan_file=loan_file, field_key=field_key, actor_user_id=current_user.id
    )
    await db.commit()
    return calculation
