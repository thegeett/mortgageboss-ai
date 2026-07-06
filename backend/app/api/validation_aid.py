"""Validation-aid endpoints (LP-89) — the starter inventory + the verdict capture (ADMIN).

The developer's tool for the validation session with the domain expert (Priya): GET the
inventory of every grounded-starter item (rules + calculator methodologies) with citations +
current values + the recorded verdicts; POST a verdict per item as she gives it. ADMIN-only
(it edits company-level validation state) + tenant-scoped. HONEST: the verdict CAPTURES her
judgment — nothing is "validated" until she says so and it's recorded here.
"""

from fastapi import APIRouter, Depends

from app.api.dependencies import CurrentCompanyId, CurrentUser, require_role
from app.core.database import DbSession
from app.models.user import UserRole
from app.schemas.validation_aid import ValidationInventory, VerdictInput, VerdictView
from app.services.validation_aid import build_inventory, record_verdict

router = APIRouter(
    prefix="/admin/validation",
    tags=["validation-aid"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],  # admin-only surface
)


@router.get("/inventory", response_model=ValidationInventory)
async def get_inventory(db: DbSession, company_id: CurrentCompanyId) -> ValidationInventory:
    """The grounded-starter inventory (every rule + calculator methodology) + the verdicts."""
    return await build_inventory(db, company_id=company_id)


@router.post("/verdicts", response_model=VerdictView)
async def post_verdict(
    payload: VerdictInput, db: DbSession, current_user: CurrentUser
) -> VerdictView:
    """Record Priya's verdict on an item (validated / corrected / remove / add-new), audited."""
    verdict = await record_verdict(
        db, company_id=current_user.company_id, data=payload, actor_user_id=current_user.id
    )
    await db.commit()
    return VerdictView(
        kind=verdict.kind.value,
        corrected_value=verdict.corrected_value,
        title=verdict.title,
        note=verdict.note,
        recorded_at=verdict.updated_at.isoformat() if verdict.updated_at else None,
    )
