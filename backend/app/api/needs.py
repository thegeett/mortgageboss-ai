"""Needs-list read endpoint (LP-34) — nested under a loan file.

Like borrowers/property (LP-29), the route declares :data:`ScopedLoanFile`, so
the parent file is fetched and company-scope-checked **first** (``404`` if it
isn't the caller's) — the tenant gate. Needs items have no ``company_id``; they
are reachable only through a file the company owns.
"""

from fastapi import APIRouter

from app.api.dependencies import ScopedLoanFile
from app.core.database import DbSession
from app.schemas.needs_item import NeedsItemPublic
from app.services.needs_items import list_needs_items

router = APIRouter(prefix="/loan-files/{file_identifier}/needs", tags=["needs"])


@router.get("", response_model=list[NeedsItemPublic])
async def list_(loan_file: ScopedLoanFile, db: DbSession) -> list[NeedsItemPublic]:
    """List the file's needs items (blocking-first). File gate via the dependency."""
    items = await list_needs_items(db, loan_file_id=loan_file.id)
    return [NeedsItemPublic.model_validate(item) for item in items]
