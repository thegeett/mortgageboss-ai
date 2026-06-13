"""Read schema for a file's stated financials (LP-55).

A read-only view of the **stated** data MISMO import populated (LP-52/53) so the
frontend can display "Application Data (Stated)" — the visible proof the import
worked. Borrower/property/loan core fields live on ``LoanFileDetail``; this adds
the multi-row stated financials (income/employers/liabilities/assets), the
extended MISMO core fields, and the import record (its parse warnings, surfaced
honestly + non-blocking). SSN is **masked** (``masked_ssn`` only).
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class StatedIncomeItemPublic(BaseModel):
    id: UUID  # needed for editing (LP-56)
    monthly_amount: Decimal | None
    income_type: str | None
    employment_income: bool | None


class StatedEmployerPublic(BaseModel):
    id: UUID  # needed for editing (LP-56)
    employer_name: str | None
    is_current: bool | None


class StatedLiabilityPublic(BaseModel):
    id: UUID  # needed for editing (LP-56)
    liability_type: str | None
    monthly_payment: Decimal | None
    unpaid_balance: Decimal | None
    holder_name: str | None


class StatedAssetPublic(BaseModel):
    id: UUID  # needed for editing (LP-56)
    asset_type: str | None
    value: Decimal | None
    holder_name: str | None


class StatedBorrowerPublic(BaseModel):
    """A borrower's stated detail — SSN masked, with their income + employers."""

    id: UUID
    full_name: str
    masked_ssn: str | None
    date_of_birth: date | None
    marital_status: str | None
    dependent_count: int | None
    citizenship: str | None
    is_primary: bool
    declarations: dict[str, str] | None
    income_items: list[StatedIncomeItemPublic]
    employers: list[StatedEmployerPublic]


# --- Edit inputs (LP-56) — all fields optional (POST add → fill; PATCH partial). #


class StatedIncomeItemInput(BaseModel):
    monthly_amount: Decimal | None = None
    income_type: str | None = None
    employment_income: bool | None = None


class StatedEmployerInput(BaseModel):
    employer_name: str | None = None
    is_current: bool | None = None


class StatedLiabilityInput(BaseModel):
    liability_type: str | None = None
    monthly_payment: Decimal | None = None
    unpaid_balance: Decimal | None = None
    holder_name: str | None = None


class StatedAssetInput(BaseModel):
    asset_type: str | None = None
    value: Decimal | None = None
    holder_name: str | None = None


class MismoImportSummary(BaseModel):
    """The import event — surfaces the parse warnings (honest, non-blocking)."""

    source_format: str
    status: str
    warnings: list[str]
    imported_at: datetime


class StatedLoanTerms(BaseModel):
    """The MISMO loan terms beyond the core (which are on ``LoanFileDetail``)."""

    note_amount: Decimal | None
    note_rate_percent: Decimal | None
    lien_priority: str | None
    amortization_type: str | None
    amortization_months: int | None
    application_received_date: date | None


class StatedPropertyExtras(BaseModel):
    """The MISMO property fields beyond the core (which are on ``LoanFileDetail``)."""

    valuation_amount: Decimal | None
    attachment_type: str | None
    construction_method: str | None
    financed_unit_count: int | None


class StatedFinancialsResponse(BaseModel):
    """Everything the "Application Data (Stated)" view needs for a file."""

    borrowers: list[StatedBorrowerPublic]
    liabilities: list[StatedLiabilityPublic]
    assets: list[StatedAssetPublic]
    loan_terms: StatedLoanTerms
    property_extras: StatedPropertyExtras | None
    # Present only for MISMO-imported files (manual files → null).
    mismo_import: MismoImportSummary | None
