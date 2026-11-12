"""Reading and changing a company's settings (LP-MB-Admin-02).

Every change is audited with before and after values (ADR-441). The settings are JSON on the
company row.
"""

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.company_settings import CompanySettings
from app.core.permissions import Permission
from app.schemas.company import CompanySettingsUpdate
from app.services.activity_log import field_changes
from app.services.authorization import ensure
from app.services.company_audit import AuditAction, log_company_action

if TYPE_CHECKING:
    from app.api.dependencies import Actor


async def update_company_settings(
    db: AsyncSession, actor: "Actor", update: CompanySettingsUpdate
) -> CompanySettings:
    """Apply the fields ``update`` carries to the actor's company, audit them, and flush.

    An omitted field is left as it is, and an unknown key already stored survives. A request that
    changes nothing writes nothing, not even an audit row.

    The row is RE-READ under ``FOR UPDATE`` first. The company was loaded at the start of the
    request, and the whole JSON column is written back, so without the lock two saves at once (or
    another feature writing its own key meanwhile) would each write their stale copy and the last
    would silently undo the other, while the audit log recorded both.
    """
    ensure(actor, Permission.COMPANY_SETTINGS_MANAGE)
    company = actor.user.company
    await db.refresh(company, attribute_names=["settings"], with_for_update=True)
    current = company.settings_model
    sent = update.model_dump(exclude_unset=True)
    changes = field_changes(
        {field: getattr(current, field) for field in sent},
        sent,
    )
    if not changes:
        return current

    new = current.model_copy(update=sent)
    # `model_dump` includes the unknown keys `extra="allow"` kept, so they are written back.
    company.settings = new.model_dump()
    # Assigning a NEW dict already marks the column dirty (measured: the PATCH test passes without
    # this line). Kept, as in `overlay_admin`, so an in-place edit added here later is still written.
    flag_modified(company, "settings")
    await db.flush()
    await log_company_action(
        db,
        company_id=actor.company_id,
        actor_user_id=actor.user.id,
        action=AuditAction.COMPANY_SETTINGS_CHANGED,
        target_type="company",
        target_id=actor.company_id,
        summary="Company settings changed",
        detail={"changes": changes},
    )
    return new
