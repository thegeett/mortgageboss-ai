"""Stated-financials edit endpoints (LP-56; audit upgraded LP-80.5).

Import-directly (LP-53/54/55) is only safe if the imported data is correctable
afterward; this provides the CRUD for the multi-row stated financials a parse
got wrong or missed: update a row's values, **add** a missed row, **remove** a
spurious one (soft delete). Each is tenant-scoped (resource → [borrower →] file →
company; cross-company → ``404``) and validated (Decimals).

**LP-80.5 — value-recording audit + staleness.** Each edit is now audited with the
actual **from→to values** in the activity_log ``detail`` (a real field-level change
history, *superseding* the LP-56 value-free posture — the activity log thereby
inherits the stated data's PII posture, auth + tenant scoped), and **marks the
cross-source verification stale** (a stated-data change moves the verification
baseline — the same as a document change; the LP-78.1 fingerprint already makes the
re-run real, this adds the prompt).

The MISMO-specific *core* fields (borrower DOB/dependents/citizenship/declarations,
property valuation/etc., loan note-rate/terms) are edited through the existing
Epic 4 PATCH endpoints. The original MISMO (raw file + ``MismoImport`` record) is
untouched — edits change the working values only.
"""

from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies import CurrentUser
from app.core.database import DbSession
from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.borrower import Borrower
from app.models.stated_financials import (
    StatedAsset,
    StatedEmployer,
    StatedIncomeItem,
    StatedLiability,
)
from app.schemas.stated_financials import (
    StatedAssetInput,
    StatedAssetPublic,
    StatedEmployerInput,
    StatedEmployerPublic,
    StatedIncomeItemInput,
    StatedIncomeItemPublic,
    StatedLiabilityInput,
    StatedLiabilityPublic,
)
from app.services.activity_log import audit_value, field_changes, log_activity
from app.services.borrowers import get_borrower
from app.services.loan_files import get_loan_file
from app.services.stated_financials import (
    get_stated_asset_for_company,
    get_stated_employer_for_company,
    get_stated_income_for_company,
    get_stated_liability_for_company,
)
from app.services.verifications import mark_verification_stale

log = structlog.get_logger(__name__)

router = APIRouter(tags=["stated-financials"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


async def _audit(
    db: DbSession,
    *,
    loan_file_id: UUID,
    summary: str,
    user: CurrentUser,
    detail: dict[str, Any] | None = None,
) -> None:
    """Audit a stated-data edit + mark verification stale (LP-80.5).

    Records the from→to values in ``detail`` (a real change history) and marks the
    cross-source verification out of date — a stated-data change moves the baseline,
    the same as a document change. Actor = the current user.
    """
    await log_activity(
        db,
        loan_file_id=loan_file_id,
        activity_type=ActivityType.FILE_UPDATED,
        summary=summary,
        actor_user_id=user.id,
        detail=detail or {},
    )
    await mark_verification_stale(db, loan_file_id=loan_file_id)


def _apply_update(row: Any, body: BaseModel) -> list[dict[str, Any]]:
    """Apply a partial update to a stated row; return the ``[{field, from, to}]`` diff."""
    provided = body.model_dump(exclude_unset=True)
    before = {field: getattr(row, field) for field in provided}
    for field, value in provided.items():
        setattr(row, field, value)
    return field_changes(before, provided)


def _edit_detail(section: str, changes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"section": section, "action": "edit", "changes": changes}


def _add_detail(section: str, body: BaseModel) -> dict[str, Any]:
    values = {k: audit_value(v) for k, v in body.model_dump(exclude_unset=True).items()}
    return {"section": section, "action": "add", "values": values}


def _remove_detail(section: str, values: dict[str, Any]) -> dict[str, Any]:
    safe = {k: audit_value(v) for k, v in values.items()}
    return {"section": section, "action": "remove", "values": safe}


# --------------------------------------------------------------------------- #
# Liabilities (file-level)
# --------------------------------------------------------------------------- #


@router.post(
    "/loan-files/{file_identifier}/stated-liabilities",
    response_model=StatedLiabilityPublic,
    status_code=status.HTTP_201_CREATED,
)
async def add_stated_liability(
    file_identifier: str, body: StatedLiabilityInput, current_user: CurrentUser, db: DbSession
) -> StatedLiabilityPublic:
    loan_file = await get_loan_file(
        db, company_id=current_user.company_id, identifier=file_identifier
    )
    if loan_file is None:
        raise _NOT_FOUND
    row = StatedLiability(loan_file_id=loan_file.id, **body.model_dump())
    db.add(row)
    await db.flush()
    await _audit(
        db,
        loan_file_id=loan_file.id,
        summary="Added a stated liability",
        user=current_user,
        detail=_add_detail("stated_liability", body),
    )
    await db.commit()
    return StatedLiabilityPublic.model_validate(row, from_attributes=True)


@router.patch("/stated-liabilities/{item_id}", response_model=StatedLiabilityPublic)
async def update_stated_liability(
    item_id: UUID, body: StatedLiabilityInput, current_user: CurrentUser, db: DbSession
) -> StatedLiabilityPublic:
    row = await get_stated_liability_for_company(
        db, item_id=item_id, company_id=current_user.company_id
    )
    if row is None:
        raise _NOT_FOUND
    changes = _apply_update(row, body)
    await db.flush()
    await _audit(
        db,
        loan_file_id=row.loan_file_id,
        summary="Edited a stated liability",
        user=current_user,
        detail=_edit_detail("stated_liability", changes),
    )
    await db.commit()
    return StatedLiabilityPublic.model_validate(row, from_attributes=True)


@router.delete("/stated-liabilities/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stated_liability(item_id: UUID, current_user: CurrentUser, db: DbSession) -> None:
    row = await get_stated_liability_for_company(
        db, item_id=item_id, company_id=current_user.company_id
    )
    if row is None:
        raise _NOT_FOUND
    removed = {"liability_type": row.liability_type, "monthly_payment": row.monthly_payment}
    row.deleted_at = utcnow()
    await db.flush()
    await _audit(
        db,
        loan_file_id=row.loan_file_id,
        summary="Removed a stated liability",
        user=current_user,
        detail=_remove_detail("stated_liability", removed),
    )
    await db.commit()


# --------------------------------------------------------------------------- #
# Assets (file-level)
# --------------------------------------------------------------------------- #


@router.post(
    "/loan-files/{file_identifier}/stated-assets",
    response_model=StatedAssetPublic,
    status_code=status.HTTP_201_CREATED,
)
async def add_stated_asset(
    file_identifier: str, body: StatedAssetInput, current_user: CurrentUser, db: DbSession
) -> StatedAssetPublic:
    loan_file = await get_loan_file(
        db, company_id=current_user.company_id, identifier=file_identifier
    )
    if loan_file is None:
        raise _NOT_FOUND
    row = StatedAsset(loan_file_id=loan_file.id, **body.model_dump())
    db.add(row)
    await db.flush()
    await _audit(
        db,
        loan_file_id=loan_file.id,
        summary="Added a stated asset",
        user=current_user,
        detail=_add_detail("stated_asset", body),
    )
    await db.commit()
    return StatedAssetPublic.model_validate(row, from_attributes=True)


@router.patch("/stated-assets/{item_id}", response_model=StatedAssetPublic)
async def update_stated_asset(
    item_id: UUID, body: StatedAssetInput, current_user: CurrentUser, db: DbSession
) -> StatedAssetPublic:
    row = await get_stated_asset_for_company(
        db, item_id=item_id, company_id=current_user.company_id
    )
    if row is None:
        raise _NOT_FOUND
    changes = _apply_update(row, body)
    await db.flush()
    await _audit(
        db,
        loan_file_id=row.loan_file_id,
        summary="Edited a stated asset",
        user=current_user,
        detail=_edit_detail("stated_asset", changes),
    )
    await db.commit()
    return StatedAssetPublic.model_validate(row, from_attributes=True)


@router.delete("/stated-assets/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stated_asset(item_id: UUID, current_user: CurrentUser, db: DbSession) -> None:
    row = await get_stated_asset_for_company(
        db, item_id=item_id, company_id=current_user.company_id
    )
    if row is None:
        raise _NOT_FOUND
    removed = {"asset_type": row.asset_type, "value": row.value}
    row.deleted_at = utcnow()
    await db.flush()
    await _audit(
        db,
        loan_file_id=row.loan_file_id,
        summary="Removed a stated asset",
        user=current_user,
        detail=_remove_detail("stated_asset", removed),
    )
    await db.commit()


# --------------------------------------------------------------------------- #
# Income (borrower-level)
# --------------------------------------------------------------------------- #


@router.post(
    "/loan-files/{file_identifier}/borrowers/{borrower_id}/stated-income",
    response_model=StatedIncomeItemPublic,
    status_code=status.HTTP_201_CREATED,
)
async def add_stated_income(
    file_identifier: str,
    borrower_id: UUID,
    body: StatedIncomeItemInput,
    current_user: CurrentUser,
    db: DbSession,
) -> StatedIncomeItemPublic:
    loan_file = await get_loan_file(
        db, company_id=current_user.company_id, identifier=file_identifier
    )
    if loan_file is None:
        raise _NOT_FOUND
    borrower = await get_borrower(db, loan_file_id=loan_file.id, borrower_id=borrower_id)
    if borrower is None:
        raise _NOT_FOUND
    row = StatedIncomeItem(borrower_id=borrower.id, **body.model_dump())
    db.add(row)
    await db.flush()
    await _audit(
        db,
        loan_file_id=loan_file.id,
        summary="Added a stated income item",
        user=current_user,
        detail=_add_detail("stated_income", body),
    )
    await db.commit()
    return StatedIncomeItemPublic.model_validate(row, from_attributes=True)


@router.patch("/stated-income-items/{item_id}", response_model=StatedIncomeItemPublic)
async def update_stated_income(
    item_id: UUID, body: StatedIncomeItemInput, current_user: CurrentUser, db: DbSession
) -> StatedIncomeItemPublic:
    row = await get_stated_income_for_company(
        db, item_id=item_id, company_id=current_user.company_id
    )
    if row is None:
        raise _NOT_FOUND
    changes = _apply_update(row, body)
    await db.flush()
    file_id = await _borrower_loan_file_id(db, row.borrower_id)
    await _audit(
        db,
        loan_file_id=file_id,
        summary="Edited a stated income item",
        user=current_user,
        detail=_edit_detail("stated_income", changes),
    )
    await db.commit()
    return StatedIncomeItemPublic.model_validate(row, from_attributes=True)


@router.delete("/stated-income-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stated_income(item_id: UUID, current_user: CurrentUser, db: DbSession) -> None:
    row = await get_stated_income_for_company(
        db, item_id=item_id, company_id=current_user.company_id
    )
    if row is None:
        raise _NOT_FOUND
    removed = {"income_type": row.income_type, "monthly_amount": row.monthly_amount}
    row.deleted_at = utcnow()
    await db.flush()
    file_id = await _borrower_loan_file_id(db, row.borrower_id)
    await _audit(
        db,
        loan_file_id=file_id,
        summary="Removed a stated income item",
        user=current_user,
        detail=_remove_detail("stated_income", removed),
    )
    await db.commit()


# --------------------------------------------------------------------------- #
# Employers (borrower-level)
# --------------------------------------------------------------------------- #


@router.post(
    "/loan-files/{file_identifier}/borrowers/{borrower_id}/stated-employers",
    response_model=StatedEmployerPublic,
    status_code=status.HTTP_201_CREATED,
)
async def add_stated_employer(
    file_identifier: str,
    borrower_id: UUID,
    body: StatedEmployerInput,
    current_user: CurrentUser,
    db: DbSession,
) -> StatedEmployerPublic:
    loan_file = await get_loan_file(
        db, company_id=current_user.company_id, identifier=file_identifier
    )
    if loan_file is None:
        raise _NOT_FOUND
    borrower = await get_borrower(db, loan_file_id=loan_file.id, borrower_id=borrower_id)
    if borrower is None:
        raise _NOT_FOUND
    row = StatedEmployer(borrower_id=borrower.id, **body.model_dump())
    db.add(row)
    await db.flush()
    await _audit(
        db,
        loan_file_id=loan_file.id,
        summary="Added a stated employer",
        user=current_user,
        detail=_add_detail("stated_employer", body),
    )
    await db.commit()
    return StatedEmployerPublic.model_validate(row, from_attributes=True)


@router.patch("/stated-employers/{item_id}", response_model=StatedEmployerPublic)
async def update_stated_employer(
    item_id: UUID, body: StatedEmployerInput, current_user: CurrentUser, db: DbSession
) -> StatedEmployerPublic:
    row = await get_stated_employer_for_company(
        db, item_id=item_id, company_id=current_user.company_id
    )
    if row is None:
        raise _NOT_FOUND
    changes = _apply_update(row, body)
    await db.flush()
    file_id = await _borrower_loan_file_id(db, row.borrower_id)
    await _audit(
        db,
        loan_file_id=file_id,
        summary="Edited a stated employer",
        user=current_user,
        detail=_edit_detail("stated_employer", changes),
    )
    await db.commit()
    return StatedEmployerPublic.model_validate(row, from_attributes=True)


@router.delete("/stated-employers/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stated_employer(item_id: UUID, current_user: CurrentUser, db: DbSession) -> None:
    row = await get_stated_employer_for_company(
        db, item_id=item_id, company_id=current_user.company_id
    )
    if row is None:
        raise _NOT_FOUND
    removed = {"employer_name": row.employer_name}
    row.deleted_at = utcnow()
    await db.flush()
    file_id = await _borrower_loan_file_id(db, row.borrower_id)
    await _audit(
        db,
        loan_file_id=file_id,
        summary="Removed a stated employer",
        user=current_user,
        detail=_remove_detail("stated_employer", removed),
    )
    await db.commit()


async def _borrower_loan_file_id(db: DbSession, borrower_id: UUID) -> UUID:
    """The loan_file_id for a borrower (for audit on borrower-level stated edits)."""
    borrower = await db.get(Borrower, borrower_id)
    assert borrower is not None  # the row was just resolved within the company scope
    return borrower.loan_file_id
