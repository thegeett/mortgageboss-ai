"""Activity-feed read endpoint (LP-34) — nested under a loan file.

Like the needs endpoint, the route declares :data:`ScopedLoanFile` so the parent
file is company-scope-checked **first** (``404`` if not the caller's). Returns
the file's recent activity, most-recent-first.
"""

from fastapi import APIRouter

from app.api.dependencies import ScopedLoanFile
from app.core.database import DbSession
from app.schemas.activity import ActivityPublic
from app.services.activity_log import list_recent_activity

router = APIRouter(prefix="/loan-files/{file_identifier}/activity", tags=["activity"])


@router.get("", response_model=list[ActivityPublic])
async def list_(loan_file: ScopedLoanFile, db: DbSession) -> list[ActivityPublic]:
    """List the file's recent activity (most-recent-first). File gate via the dependency."""
    entries = await list_recent_activity(db, loan_file_id=loan_file.id)
    return [ActivityPublic.model_validate(entry) for entry in entries]
