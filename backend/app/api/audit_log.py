"""The company audit log, read-only (LP-MB-Admin-03). ``audit.view``."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import CurrentActor, require_permission
from app.core.database import DbSession
from app.core.permissions import Permission
from app.schemas.audit import AuditPage
from app.services.company_audit import decode_cursor, list_audit_log

router = APIRouter(
    prefix="/audit-log",
    tags=["audit-log"],
    dependencies=[Depends(require_permission(Permission.AUDIT_VIEW))],
)


@router.get("", response_model=AuditPage)
async def read_audit_log(
    db: DbSession,
    actor: CurrentActor,
    target_type: str | None = None,
    target_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    since: datetime | None = None,
    before: Annotated[str | None, Query(description="`next_cursor` of the previous page")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditPage:
    """The company's admin actions, newest first. Nothing here can be changed or removed."""
    cursor = None
    if before is not None:
        try:
            cursor = decode_cursor(before)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid cursor"
            ) from exc
    return await list_audit_log(
        db,
        actor,
        target_type=target_type,
        target_id=target_id,
        actor_user_id=actor_user_id,
        since=since,
        before=cursor,
        limit=limit,
    )
