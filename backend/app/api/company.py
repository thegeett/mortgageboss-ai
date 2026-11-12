"""The caller's company: its settings (LP-MB-Admin-02).

``GET`` and ``PATCH /company/settings``, both ``company.settings.manage``. The company is always
the actor's effective company (ADR-443); there is no company id in the path.
"""

from fastapi import APIRouter, Depends

from app.api.dependencies import CurrentActor, require_permission
from app.core.company_settings import CompanySettings
from app.core.database import DbSession
from app.core.permissions import Permission
from app.schemas.company import CompanySettingsPublic, CompanySettingsUpdate
from app.services.company_settings import update_company_settings

router = APIRouter(
    prefix="/company",
    tags=["company"],
    dependencies=[Depends(require_permission(Permission.COMPANY_SETTINGS_MANAGE))],
)


def _public(settings: CompanySettings) -> CompanySettingsPublic:
    return CompanySettingsPublic.model_validate(settings, from_attributes=True)


@router.get("/settings", response_model=CompanySettingsPublic)
async def get_settings(actor: CurrentActor) -> CompanySettingsPublic:
    """The three settings; a setting never saved shows its default."""
    return _public(actor.user.company.settings_model)


@router.patch("/settings", response_model=CompanySettingsPublic)
async def patch_settings(
    payload: CompanySettingsUpdate, db: DbSession, actor: CurrentActor
) -> CompanySettingsPublic:
    """Change any of the three settings; each change is audited with before and after values."""
    settings = await update_company_settings(db, actor, payload)
    await db.commit()
    return _public(settings)
