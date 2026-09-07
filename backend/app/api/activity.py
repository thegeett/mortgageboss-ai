"""Activity-feed read endpoint (LP-34) — nested under a loan file.

Like the needs endpoint, the route declares :data:`ScopedLoanFile` so the parent
file is company-scope-checked **first** (``404`` if not the caller's). Returns
the file's recent activity, most-recent-first.
"""

from fastapi import APIRouter, Query

from app.api.dependencies import ScopedLoanFile
from app.core.database import DbSession
from app.schemas.activity import ActivityPublic
from app.services.activity_log import list_recent_activity

router = APIRouter(prefix="/loan-files/{file_identifier}/activity", tags=["activity"])


#: The most a single request will return. LP-825 — a cap, not a page size: `limit` is a client's
#: ask and this is the ceiling on it, so "see more" cannot become "load this file's entire history
#: in one request" by a client passing a large number.
MAX_ACTIVITY_LIMIT = 200


@router.get("", response_model=list[ActivityPublic])
async def list_(
    loan_file: ScopedLoanFile,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=MAX_ACTIVITY_LIMIT),
) -> list[ActivityPublic]:
    """List the file's recent activity (most-recent-first). File gate via the dependency.

    LP-825 — `limit` IS A CLIENT'S ASK NOW, because this is where the rest of the file's history
    went. The Communication page used to carry every non-message activity; it no longer does, so
    twenty rows with no way past them is the whole record a processor can reach.

    NO CURSOR, AND THAT IS A DECISION rather than an omission. The feed is newest-first and the
    client asks for more by raising the limit, which re-reads rows it already has. That is cheap at
    these sizes and it cannot skip an entry the way an offset can when something is written between
    two requests — which on an append-at-the-top feed is the ordinary case, not the rare one.
    """
    entries = await list_recent_activity(db, loan_file_id=loan_file.id, limit=limit)
    return [ActivityPublic.model_validate(entry) for entry in entries]
