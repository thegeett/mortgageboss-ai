"""DTI calculator endpoints (LP-76).

``GET`` returns the full, transparent, auto-populated calculation; ``PUT`` /
``DELETE`` set and clear a per-field override (recomputing in the response, so
the client gets the new numbers in one round-trip — the real-time recalculation).
Every route is tenant-scoped: the loan file is resolved within the caller's
company first (cross-company → 404). Overrides are audited in the service.
"""

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import CurrentUser
from app.core.database import DbSession
from app.schemas.dti import DtiCalculation, DtiOverrideInput
from app.services.aggression import active_cutoff
from app.services.dti import (
    UnknownDtiFieldError,
    build_dti_calculation,
    clear_dti_override,
    set_dti_override,
)
from app.services.loan_files import get_loan_file

router = APIRouter(prefix="/loan-files", tags=["dti"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan file not found")


@router.get("/{identifier}/dti", response_model=DtiCalculation)
async def get_dti(identifier: str, db: DbSession, current_user: CurrentUser) -> DtiCalculation:
    """The auto-populated, itemized DTI calculation for one of the caller's files."""
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    return await build_dti_calculation(
        db, loan_file=loan_file, confidence_cutoff=active_cutoff(loan_file, current_user)
    )


@router.put("/{identifier}/dti/overrides/{field_key}", response_model=DtiCalculation)
async def put_dti_override(
    identifier: str,
    field_key: str,
    payload: DtiOverrideInput,
    db: DbSession,
    current_user: CurrentUser,
) -> DtiCalculation:
    """Override one DTI input (audited, persisted) and return the recomputed result."""
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    try:
        calculation = await set_dti_override(
            db,
            loan_file=loan_file,
            field_key=field_key,
            data=payload,
            actor_user_id=current_user.id,
            confidence_cutoff=active_cutoff(loan_file, current_user),
        )
    except UnknownDtiFieldError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown DTI input field"
        ) from exc
    await db.commit()
    return calculation


@router.delete("/{identifier}/dti/overrides/{field_key}", response_model=DtiCalculation)
async def delete_dti_override(
    identifier: str, field_key: str, db: DbSession, current_user: CurrentUser
) -> DtiCalculation:
    """Clear an override (revert to the auto value), audited; return the recompute."""
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    calculation = await clear_dti_override(
        db,
        loan_file=loan_file,
        field_key=field_key,
        actor_user_id=current_user.id,
        confidence_cutoff=active_cutoff(loan_file, current_user),
    )
    await db.commit()
    return calculation
