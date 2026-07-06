"""Property endpoints — a singleton nested under a loan file (LP-29).

Routes live under ``/api/v1/loan-files/{file_identifier}/property``. Like
borrowers, every route declares :data:`ScopedLoanFile`, so the parent file is
company-scope-checked **first** (``404`` if not the caller's) — the tenant gate.

The property is a **per-file singleton**: ``GET``/``PATCH``/``DELETE`` operate on
the single property (``404`` when none), and a second ``POST`` returns ``409``.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import CurrentUser, ScopedLoanFile
from app.core.database import DbSession
from app.models.activity_log import ActivityType
from app.schemas.property import PropertyCreate, PropertyResponse, PropertyUpdate
from app.services.activity_log import field_changes, log_activity
from app.services.properties import (
    PropertyExistsError,
    create_property,
    get_property,
    soft_delete_property,
    update_property,
)
from app.services.verifications import mark_verification_stale

router = APIRouter(prefix="/loan-files/{file_identifier}/property", tags=["property"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")


@router.get("", response_model=PropertyResponse)
async def retrieve(loan_file: ScopedLoanFile, db: DbSession) -> PropertyResponse:
    """Get the file's subject property; 404 if it has none."""
    property_obj = await get_property(db, loan_file_id=loan_file.id)
    if property_obj is None:
        raise _NOT_FOUND
    return PropertyResponse.model_validate(property_obj)


@router.post("", response_model=PropertyResponse, status_code=status.HTTP_201_CREATED)
async def create(
    payload: PropertyCreate, loan_file: ScopedLoanFile, db: DbSession
) -> PropertyResponse:
    """Attach the subject property; 409 if the file already has one (singleton)."""
    try:
        property_obj = await create_property(db, loan_file_id=loan_file.id, data=payload)
    except PropertyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This loan file already has a property.",
        ) from exc
    await db.commit()
    return PropertyResponse.model_validate(property_obj)


@router.patch("", response_model=PropertyResponse)
async def update(
    payload: PropertyUpdate, loan_file: ScopedLoanFile, current_user: CurrentUser, db: DbSession
) -> PropertyResponse:
    """Update the file's property; 404 if it has none.

    Audited with the actual **from→to values** and **marks verification stale**
    (LP-80.5) — the property is a verification baseline input (it drives LTV), so a
    change moves the baseline, the same as a document change. Property edits were
    previously silent; they are now audited.
    """
    property_obj = await get_property(db, loan_file_id=loan_file.id)
    if property_obj is None:
        raise _NOT_FOUND

    provided = payload.model_dump(exclude_unset=True)
    before: dict[str, Any] = {field: getattr(property_obj, field) for field in provided}
    await update_property(db, property_obj=property_obj, data=payload)
    changes = field_changes(before, provided)
    if changes:
        await log_activity(
            db,
            loan_file_id=loan_file.id,
            activity_type=ActivityType.FILE_UPDATED,
            summary="Edited the subject property",
            actor_user_id=current_user.id,
            detail={"section": "property", "action": "edit", "changes": changes},
        )
        await mark_verification_stale(db, loan_file_id=loan_file.id)
    await db.commit()
    return PropertyResponse.model_validate(property_obj)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete(loan_file: ScopedLoanFile, db: DbSession) -> None:
    """Soft-delete the file's property; 404 if it has none."""
    property_obj = await get_property(db, loan_file_id=loan_file.id)
    if property_obj is None:
        raise _NOT_FOUND
    await soft_delete_property(db, property_obj=property_obj)
    await db.commit()
