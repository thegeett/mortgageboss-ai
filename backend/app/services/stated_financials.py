"""Read service for a file's stated financials (LP-55).

Assembles the :class:`StatedFinancialsResponse` from the LP-52 rows for a loan
file: borrowers (with their income + employers grouped), the file's liabilities
and assets, the extended MISMO loan/property fields, and the latest import
record (its parse warnings). The ``loan_file`` is assumed already tenant-scoped
(resolved via the company-scoped ``get_loan_file``); these reads are children of
that file.
"""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.borrower import Borrower
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.mismo_import import MismoImport
from app.models.stated_financials import (
    StatedAsset,
    StatedEmployer,
    StatedIncomeItem,
    StatedLiability,
)
from app.schemas.stated_financials import (
    MismoImportSummary,
    StatedAssetPublic,
    StatedBorrowerPublic,
    StatedFinancialsResponse,
    StatedIncomeItemPublic,
    StatedLiabilityPublic,
    StatedLoanTerms,
    StatedPropertyExtras,
)


async def get_stated_financials(
    db: AsyncSession, *, loan_file: LoanFile
) -> StatedFinancialsResponse:
    borrowers = (
        await db.scalars(
            only_active(
                select(Borrower).where(Borrower.loan_file_id == loan_file.id), Borrower
            ).order_by(Borrower.borrower_position)
        )
    ).all()
    borrower_ids = [b.id for b in borrowers]

    income_by_borrower: dict[UUID, list[StatedIncomeItemPublic]] = defaultdict(list)
    employers_by_borrower: dict[UUID, list[str]] = defaultdict(list)
    if borrower_ids:
        for item in (
            await db.scalars(
                only_active(
                    select(StatedIncomeItem).where(StatedIncomeItem.borrower_id.in_(borrower_ids)),
                    StatedIncomeItem,
                )
            )
        ).all():
            income_by_borrower[item.borrower_id].append(
                StatedIncomeItemPublic(
                    monthly_amount=item.monthly_amount,
                    income_type=item.income_type,
                    employment_income=item.employment_income,
                )
            )
        for emp in (
            await db.scalars(
                only_active(
                    select(StatedEmployer).where(StatedEmployer.borrower_id.in_(borrower_ids)),
                    StatedEmployer,
                )
            )
        ).all():
            if emp.employer_name:
                employers_by_borrower[emp.borrower_id].append(emp.employer_name)

    borrower_views = [
        StatedBorrowerPublic(
            id=b.id,
            full_name=b.full_name,
            masked_ssn=b.masked_ssn,
            date_of_birth=b.date_of_birth,
            marital_status=b.marital_status.value if b.marital_status else None,
            dependent_count=b.dependent_count,
            citizenship=b.citizenship,
            is_primary=b.is_primary,
            declarations=b.declarations,
            income_items=income_by_borrower.get(b.id, []),
            employers=employers_by_borrower.get(b.id, []),
        )
        for b in borrowers
    ]

    liabilities = [
        StatedLiabilityPublic(
            liability_type=row.liability_type,
            monthly_payment=row.monthly_payment,
            unpaid_balance=row.unpaid_balance,
            holder_name=row.holder_name,
        )
        for row in (
            await db.scalars(
                only_active(
                    select(StatedLiability).where(StatedLiability.loan_file_id == loan_file.id),
                    StatedLiability,
                )
            )
        ).all()
    ]
    assets = [
        StatedAssetPublic(asset_type=row.asset_type, value=row.value, holder_name=row.holder_name)
        for row in (
            await db.scalars(
                only_active(
                    select(StatedAsset).where(StatedAsset.loan_file_id == loan_file.id),
                    StatedAsset,
                )
            )
        ).all()
    ]

    latest_import = (
        await db.scalars(
            only_active(
                select(MismoImport).where(MismoImport.loan_file_id == loan_file.id), MismoImport
            ).order_by(MismoImport.created_at.desc())
        )
    ).first()
    import_summary = (
        MismoImportSummary(
            source_format=latest_import.source_format,
            status=latest_import.status.value,
            warnings=latest_import.parse_warnings or [],
            imported_at=latest_import.created_at,
        )
        if latest_import is not None
        else None
    )

    prop = loan_file.property
    property_extras = (
        StatedPropertyExtras(
            valuation_amount=prop.valuation_amount,
            attachment_type=prop.attachment_type,
            construction_method=prop.construction_method,
            financed_unit_count=prop.financed_unit_count,
        )
        if prop is not None
        else None
    )

    return StatedFinancialsResponse(
        borrowers=borrower_views,
        liabilities=liabilities,
        assets=assets,
        loan_terms=StatedLoanTerms(
            note_amount=loan_file.note_amount,
            note_rate_percent=loan_file.note_rate_percent,
            lien_priority=loan_file.lien_priority,
            amortization_type=loan_file.amortization_type,
            amortization_months=loan_file.amortization_months,
            application_received_date=loan_file.application_received_date,
        ),
        property_extras=property_extras,
        mismo_import=import_summary,
    )
