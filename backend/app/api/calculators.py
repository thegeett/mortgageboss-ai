"""Calculator endpoints (LP-87) — the four calculators, one parameterized router.

``GET`` returns a calculator's transparent auto-populated view; ``PUT`` / ``DELETE`` set
and clear a per-field override (recomputing in the response — the real-time recalculation
of LP-76/77). The ``{calculator}`` path segment selects mortgage_insurance / self_employed
/ reserves / max_loan. Every route is tenant-scoped (cross-company → 404); overrides are
audited in the service.
"""

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import CurrentUser
from app.core.database import DbSession
from app.schemas.calculators import CalcOverrideInput, CalculatorView
from app.services.aggression import active_cutoff
from app.services.calculators import (
    CALCULATORS,
    UnknownCalcFieldError,
    UnknownCalculatorError,
    build_calculator,
    clear_calculator_override,
    set_calculator_override,
)
from app.services.loan_files import get_loan_file

router = APIRouter(prefix="/loan-files", tags=["calculators"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan file not found")
_UNKNOWN_CALC = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown calculator")
_UNKNOWN_FIELD = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Unknown calculator input field"
)


def _check_calculator(calculator: str) -> None:
    if calculator not in CALCULATORS:
        raise _UNKNOWN_CALC


@router.get("/{identifier}/calculators/{calculator}", response_model=CalculatorView)
async def get_calculator(
    identifier: str, calculator: str, db: DbSession, current_user: CurrentUser
) -> CalculatorView:
    """The auto-populated, transparent view for one calculator on one of the caller's files."""
    _check_calculator(calculator)
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    return await build_calculator(
        db,
        loan_file=loan_file,
        calculator=calculator,
        confidence_cutoff=active_cutoff(loan_file, current_user),
    )


@router.put(
    "/{identifier}/calculators/{calculator}/overrides/{field_key}",
    response_model=CalculatorView,
)
async def put_calculator_override(
    identifier: str,
    calculator: str,
    field_key: str,
    payload: CalcOverrideInput,
    db: DbSession,
    current_user: CurrentUser,
) -> CalculatorView:
    """Override one calculator input (audited, persisted); return the recomputed view."""
    _check_calculator(calculator)
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    try:
        view = await set_calculator_override(
            db,
            loan_file=loan_file,
            calculator=calculator,
            field_key=field_key,
            data=payload,
            actor_user_id=current_user.id,
            confidence_cutoff=active_cutoff(loan_file, current_user),
        )
    except UnknownCalculatorError as exc:
        raise _UNKNOWN_CALC from exc
    except UnknownCalcFieldError as exc:
        raise _UNKNOWN_FIELD from exc
    await db.commit()
    return view


@router.delete(
    "/{identifier}/calculators/{calculator}/overrides/{field_key}",
    response_model=CalculatorView,
)
async def delete_calculator_override(
    identifier: str, calculator: str, field_key: str, db: DbSession, current_user: CurrentUser
) -> CalculatorView:
    """Clear an override (revert to auto), audited; return the recompute."""
    _check_calculator(calculator)
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    view = await clear_calculator_override(
        db,
        loan_file=loan_file,
        calculator=calculator,
        field_key=field_key,
        actor_user_id=current_user.id,
        confidence_cutoff=active_cutoff(loan_file, current_user),
    )
    await db.commit()
    return view
