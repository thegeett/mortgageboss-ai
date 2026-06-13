"""Stated-financials models (LP-52) — the *stated* half of stated-vs-verified.

MISMO import (the primary file-creation path) produces multi-row structured
financials — many incomes, employers, liabilities, assets — that Phase-3
verification must compare against document-extracted values. They are persisted
as **typed, one-to-many rows** (not loose JSON): ``Decimal`` amounts (exact,
summable) and the MISMO category as a **flexible string** (the MISMO
``IncomeType`` / ``LiabilityType`` / ``AssetType`` sets are large and evolving,
so they are *not* CHECK-enums; see ADR-037 for when to use a CHECK-enum).

FK placement is by what Phase-3 needs (see ADR for this ticket):
- **income** and **employers** are per-**borrower** (MISMO nests them under the
  borrower role; income verification is per-borrower).
- **liabilities** and **assets** are per-**loan_file** (MISMO carries them at the
  deal level; DTI and reserves are computed file-level).

All are tenant-scoped **transitively** via the loan file (ADR-053) — no own
``company_id`` — and cascade from their parent. The shape is a **starter**,
refined with Priya / as Phase-3 rules firm up. Amounts are never logged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.types import Money

if TYPE_CHECKING:
    from app.models.borrower import Borrower
    from app.models.loan_file import LoanFile

# MISMO category values (IncomeType, LiabilityType, AssetType) are large/evolving
# enumerations, so they are stored as flexible strings (no CHECK), per ADR-037.
# Money is the shared Numeric(14, 2) Decimal type.
_CATEGORY_LEN = 64
_HOLDER_LEN = 256


class StatedIncomeItem(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One stated current-income item for a borrower (feeds income verification)."""

    __tablename__ = "stated_income_items"

    borrower_id: Mapped[UUID] = mapped_column(
        ForeignKey("borrowers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    monthly_amount: Mapped[Money | None] = mapped_column(nullable=True)
    # Flexible MISMO IncomeType (Base / Overtime / Bonus / Commission / …).
    income_type: Mapped[str | None] = mapped_column(String(_CATEGORY_LEN), nullable=True)
    employment_income: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    borrower: Mapped[Borrower] = relationship(back_populates="stated_income_items")


class StatedEmployer(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A stated employer for a borrower (feeds employment / income cross-checks)."""

    __tablename__ = "stated_employers"

    borrower_id: Mapped[UUID] = mapped_column(
        ForeignKey("borrowers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    employer_name: Mapped[str | None] = mapped_column(String(_HOLDER_LEN), nullable=True)
    # Whether this is the borrower's current employer (MISMO EmploymentStatusType
    # == "Current"); nullable — not always present.
    is_current: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    borrower: Mapped[Borrower] = relationship(back_populates="stated_employers")


class StatedLiability(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A stated liability for the file (feeds DTI back-end + undisclosed-debt checks).

    File-level (not borrower-level): MISMO carries liabilities at the deal level and
    DTI is computed for the file.
    """

    __tablename__ = "stated_liabilities"

    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Flexible MISMO LiabilityType (MortgageLoan / Installment / Revolving / …).
    liability_type: Mapped[str | None] = mapped_column(String(_CATEGORY_LEN), nullable=True)
    monthly_payment: Mapped[Money | None] = mapped_column(nullable=True)
    unpaid_balance: Mapped[Money | None] = mapped_column(nullable=True)
    holder_name: Mapped[str | None] = mapped_column(String(_HOLDER_LEN), nullable=True)

    loan_file: Mapped[LoanFile] = relationship(back_populates="stated_liabilities")


class StatedAsset(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A stated asset for the file (feeds reserves + asset cross-checks).

    File-level: MISMO carries assets at the deal level and reserves are file-level.
    """

    __tablename__ = "stated_assets"

    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Flexible MISMO AssetType (CheckingAccount / RetirementFund / GiftOfCash / …).
    asset_type: Mapped[str | None] = mapped_column(String(_CATEGORY_LEN), nullable=True)
    value: Mapped[Money | None] = mapped_column(nullable=True)
    holder_name: Mapped[str | None] = mapped_column(String(_HOLDER_LEN), nullable=True)

    loan_file: Mapped[LoanFile] = relationship(back_populates="stated_assets")


__all__ = ["StatedAsset", "StatedEmployer", "StatedIncomeItem", "StatedLiability"]
