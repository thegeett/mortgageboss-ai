"""Document findings endpoint (LP-66) — findings are visible + queryable per file.

A single read endpoint surfacing a loan file's document findings (the LP-67 +
Phase 3 feedstock). Tenant-scoped via :data:`ScopedLoanFile`: the loan file is
company-scope-checked first (``404`` if not the caller's), so a Company A user can
never read Company B's findings — the findings hang off that file's documents.
"""

from fastapi import APIRouter

from app.api.dependencies import ScopedLoanFile
from app.core.database import DbSession
from app.schemas.document_finding import DocumentFindingResponse
from app.services.document_findings import list_findings_for_loan_file

router = APIRouter(prefix="/loan-files/{file_identifier}/findings", tags=["findings"])


@router.get("", response_model=list[DocumentFindingResponse])
async def list_findings(loan_file: ScopedLoanFile, db: DbSession) -> list[DocumentFindingResponse]:
    """List the loan file's document findings (newest first), tenant-scoped."""
    findings = await list_findings_for_loan_file(db, loan_file_id=loan_file.id)
    return [DocumentFindingResponse.model_validate(f) for f in findings]
