"""Loan file service — creation and core operations."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lender import LoanProgram
from app.models.loan_file import LoanFile, LoanFileStatus, LoanPurpose
from app.services.loan_file_ids import (
    generate_inbox_token,
    generate_unique_display_id,
)


async def create_loan_file(
    db: AsyncSession,
    *,
    company_id: UUID,
    lender_id: UUID | None = None,
    loan_program: LoanProgram | None = None,
    loan_purpose: LoanPurpose | None = None,
    loan_officer_name: str | None = None,
    loan_officer_email: str | None = None,
) -> LoanFile:
    """Create a new loan file with generated display ID and inbox token.

    The display ID is collision-checked against existing files; the inbox token
    is an independent cryptographic value (ADR-036, ADR-050). The new file
    starts in :attr:`LoanFileStatus.DRAFT`.

    Minimal creation only: needs-list generation and activity logging are added
    in later tickets (LP-30). Uses ``flush`` rather than ``commit`` so the
    caller controls the transaction (and tests stay isolated).
    """
    display_id = await generate_unique_display_id(db)
    inbox_token = generate_inbox_token()

    loan_file = LoanFile(
        display_id=display_id,
        inbox_token=inbox_token,
        company_id=company_id,
        lender_id=lender_id,
        loan_program=loan_program,
        loan_purpose=loan_purpose,
        status=LoanFileStatus.DRAFT,
        loan_officer_name=loan_officer_name,
        loan_officer_email=loan_officer_email,
    )
    db.add(loan_file)
    await db.flush()  # populate defaults/PK without committing (caller controls tx)
    return loan_file
