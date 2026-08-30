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

from app.mismo.schema import ParseWarning


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
    # LP-569 review — READABLE, so the UI can show why a debt left the DTI, and WRITABLE on the
    # input below so a processor can say so. Without the write path the flag was settable only by a
    # MISMO `true`, which the real export never carries — the mechanism would have been inert on
    # exactly the file whose 58.59% → 34.39% correction motivated it.
    paid_off_at_closing: bool | None
    payoff_source: str | None


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
    # Only True excludes the payment from the DTI; None means "not established" and keeps it
    # counted. `payoff_source` is NOT accepted from the client — it is provenance, and the route
    # stamps it, so a caller cannot claim the export said something it did not.
    paid_off_at_closing: bool | None = None


class StatedAssetInput(BaseModel):
    asset_type: str | None = None
    value: Decimal | None = None
    holder_name: str | None = None


class MismoImportSummary(BaseModel):
    """The import event — surfaces the parse warnings (honest, non-blocking)."""

    source_format: str
    status: str
    #: LP-UI-024 — each carries the subject the parser was looking at, so the
    #: warnings panel links one to the section it concerns. Read through
    #: `ParseWarning.coerce`: rows written before the subject existed hold bare
    #: strings, and they are still true.
    warnings: list[ParseWarning]
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
