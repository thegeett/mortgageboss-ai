"""Parsed MISMO intermediate representation (LP-51).

The deterministic parser (:mod:`app.mismo.parser`) turns a MISMO 3.4 XML file
into this structure: a **typed core** (the borrower / loan / property / stated
financials needed now and by Phase-3 verification) plus a **catch-all**
(everything else in the deal, grouped, so nothing is lost). It mirrors the
document-extraction shape (typed core + grouped catch-all, LP-39a) in spirit.

This is an *intermediate representation only* — mapping to DB models, encrypting
the SSN, and creating a loan file are the next ticket's job. Money/rates are
``Decimal`` (read exactly — the stated data is the source-of-truth baseline);
dates are ``date``. Every field is optional: a missing element becomes ``None``
(or an empty list), never an error.

**PII:** ``ParsedBorrower.ssn`` is sensitive. It is parsed into this structure
but **never logged**; encryption/masking happens downstream.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class ParsedIncomeItem(BaseModel):
    """One stated current-income item for a borrower."""

    monthly_amount: Decimal | None = None
    income_type: str | None = None
    employment_income: bool | None = None


class ParsedBorrower(BaseModel):
    """A borrower party (``PartyRoleType == "Borrower"``) — typed core."""

    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    ssn: str | None = None  # SENSITIVE — parsed but NEVER logged
    birth_date: date | None = None
    marital_status: str | None = None
    dependent_count: int | None = None
    classification: str | None = None  # Primary / Secondary
    email: str | None = None
    phone: str | None = None
    address_line: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    address_type: str | None = None
    citizenship: str | None = None
    income_items: list[ParsedIncomeItem] = Field(default_factory=list)
    employers: list[str] = Field(default_factory=list)
    # The 1003 declaration indicators (BankruptcyIndicator, IntentToOccupyType, …)
    # — kept as raw string values; they feed Phase-3 cross-source verification.
    declarations: dict[str, str] = Field(default_factory=dict)


class ParsedLoan(BaseModel):
    """The subject loan terms — typed core."""

    base_loan_amount: Decimal | None = None
    note_amount: Decimal | None = None
    note_rate_percent: Decimal | None = None
    loan_purpose: str | None = None  # Purchase / Refinance
    mortgage_type: str | None = None  # Conventional / FHA / …
    lien_priority: str | None = None
    amortization_type: str | None = None  # Fixed / …
    amortization_months: int | None = None
    application_received_date: date | None = None


class ParsedProperty(BaseModel):
    """The subject property — typed core."""

    address_line: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    county: str | None = None
    estimated_value: Decimal | None = None
    valuation_amount: Decimal | None = None
    sales_contract_amount: Decimal | None = None
    usage_type: str | None = None
    attachment_type: str | None = None
    construction_method: str | None = None
    financed_unit_count: int | None = None


class ParsedLiability(BaseModel):
    """One stated liability (feeds the DTI back-end)."""

    liability_type: str | None = None  # MortgageLoan / Installment / Revolving / …
    monthly_payment: Decimal | None = None
    unpaid_balance: Decimal | None = None
    holder_name: str | None = None


class ParsedAsset(BaseModel):
    """One stated asset."""

    asset_type: str | None = None  # CheckingAccount / RetirementFund / GiftOfCash / …
    value: Decimal | None = None
    holder_name: str | None = None


class CatchAllField(BaseModel):
    """A single non-core leaf value (label + its text)."""

    label: str
    value: str


class CatchAllSection(BaseModel):
    """Non-core leaves grouped by the section (entity path) they came from."""

    section: str
    fields: list[CatchAllField] = Field(default_factory=list)


class ParsedMismo(BaseModel):
    """The full deterministic parse: typed core + catch-all + parse metadata."""

    borrowers: list[ParsedBorrower] = Field(default_factory=list)
    loan: ParsedLoan | None = None
    property: ParsedProperty | None = None
    liabilities: list[ParsedLiability] = Field(default_factory=list)
    assets: list[ParsedAsset] = Field(default_factory=list)
    catch_all: list[CatchAllSection] = Field(default_factory=list)
    # Needed-now fields that were missing / odd (never includes PII values).
    parse_warnings: list[str] = Field(default_factory=list)
    source_format: str = "xml"  # "xml" | "html"
