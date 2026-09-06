"""DTI calculator endpoints (LP-76).

``GET`` returns the full, transparent, auto-populated calculation; ``PUT`` /
``DELETE`` set and clear a per-field override (recomputing in the response, so
the client gets the new numbers in one round-trip — the real-time recalculation).
Every route is tenant-scoped: the loan file is resolved within the caller's
company first (cross-company → 404). Overrides are audited in the service.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import CurrentUser
from app.core.database import DbSession
from app.schemas.dti import (
    DtiCalculation,
    DtiCustomLineInput,
    DtiOverrideInput,
    DtiUngatePreview,
)
from app.services.aggression import active_cutoff
from app.services.dti import (
    UnknownDtiFieldError,
    add_dti_custom_line,
    apply_dti_ungate,
    build_dti_calculation,
    clear_dti_override,
    gate_display_ratios,
    preview_dti_ungate,
    remove_dti_custom_line,
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
    return gate_display_ratios(
        await build_dti_calculation(
            db, loan_file=loan_file, confidence_cutoff=active_cutoff(loan_file, current_user)
        )
    )


@router.post("/{identifier}/dti/lines", response_model=DtiCalculation)
async def add_dti_line(
    identifier: str,
    payload: DtiCustomLineInput,
    db: DbSession,
    current_user: CurrentUser,
) -> DtiCalculation:
    """Add a processor's own line to a DTI section (audited, persisted); return the recompute.

    LP-643 — a line the calculator did not produce, so it is not an override. An added line does NOT
    clear a gate: a gate says a required input is unknown, and an unrelated row does not make it
    known. Overriding the gated line itself remains the way to supply that figure.
    """
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    calculation = await add_dti_custom_line(
        db,
        loan_file=loan_file,
        data=payload,
        actor_user_id=current_user.id,
        confidence_cutoff=active_cutoff(loan_file, current_user),
    )
    await db.commit()
    return gate_display_ratios(calculation)


@router.delete("/{identifier}/dti/lines/{line_id}", response_model=DtiCalculation)
async def delete_dti_line(
    identifier: str, line_id: UUID, db: DbSession, current_user: CurrentUser
) -> DtiCalculation:
    """Remove a line the PROCESSOR added, audited; return the recompute.

    Only their own lines. An engine line has no delete endpoint by design — a credit-report liability
    that should not count is an exclusion, which shows struck through with its reason rather than
    vanishing.
    """
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    try:
        calculation = await remove_dti_custom_line(
            db,
            loan_file=loan_file,
            line_id=line_id,
            actor_user_id=current_user.id,
            confidence_cutoff=active_cutoff(loan_file, current_user),
        )
    except UnknownDtiFieldError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown DTI line"
        ) from exc
    await db.commit()
    return gate_display_ratios(calculation)


@router.get("/{identifier}/dti/ungate", response_model=DtiUngatePreview)
async def get_dti_ungate_preview(
    identifier: str, db: DbSession, current_user: CurrentUser
) -> DtiUngatePreview:
    """What an ungate would do, itemised — the confirmation popup's content. Persists nothing."""
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    return await preview_dti_ungate(
        db, loan_file=loan_file, confidence_cutoff=active_cutoff(loan_file, current_user)
    )


@router.post("/{identifier}/dti/ungate", response_model=DtiCalculation)
async def post_dti_ungate(
    identifier: str,
    payload: DtiOverrideInput | None,
    db: DbSession,
    current_user: CurrentUser,
) -> DtiCalculation:
    """Record every gated housing input as $0.00, behind the caller's confirmation (audited).

    LP-643 — a deliberate override of the fail-closed gate, which is what the popup exists to make a
    decision rather than a slip. Implemented as ordinary per-line overrides, so UNDO is the existing
    `DELETE .../overrides/{field_key}` rather than a second mechanism.
    """
    loan_file = await get_loan_file(db, company_id=current_user.company_id, identifier=identifier)
    if loan_file is None:
        raise _NOT_FOUND
    calculation = await apply_dti_ungate(
        db,
        loan_file=loan_file,
        note=payload.note if payload else None,
        actor_user_id=current_user.id,
        confidence_cutoff=active_cutoff(loan_file, current_user),
    )
    await db.commit()
    return gate_display_ratios(calculation)


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
    return gate_display_ratios(calculation)


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
    return gate_display_ratios(calculation)
