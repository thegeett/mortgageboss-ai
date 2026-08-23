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

from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String
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
    #
    # ⚠️ LP-624 — THIS COLUMN AND ITS COMMENT PREDATE ANYTHING POPULATING IT. The parser read only
    # `FullName`, so every stated employer imported with `is_current` NULL and the comment described an
    # intention rather than a behaviour. A nullable column nothing writes looks exactly like one that is
    # legitimately null, which is why it survived that way.
    is_current: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # LP-624 — the rest of the EMPLOYMENT record, which the MISMO states and the import discarded.
    # `self_employed` decides whether tax returns are the right ask; `position` is what a
    # same-line-of-work judgment compares; the dates are what an employment-gap check needs and could
    # not find, so IN-4 abstained over dates sitting in the file it had just imported.
    self_employed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    classification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    position: Mapped[str | None] = mapped_column(String(_HOLDER_LEN), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    monthly_income: Mapped[Money | None] = mapped_column(nullable=True)
    special_relationship: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

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

    # LP-568 — will this obligation survive closing? A refinance pays off the mortgage it
    # replaces, and a purchase can pay off a departing residence or a debt cleared to qualify;
    # in each case the payment must leave the DTI, because DTI measures what is owed AFTER
    # closing. Without this the same house is charged twice — once as the new housing payment,
    # once as the old liability.
    #
    # THREE-STATE, and ``None`` is the default on purpose (§8: absent is not the same as
    # known-false). Only ``True`` excludes the payment. A MISMO ``false`` does NOT land here as
    # ``False``: the real export carries ``LiabilityPayoffStatusIndicator=false`` on every row,
    # including five mortgages, so ``false`` is "not stated", not "retained". Treating it as
    # authoritative would silently suppress the question on every file.
    #
    # Excluding wrongly UNDERSTATES the DTI and can pass a loan that should fail, so nothing sets
    # this from a heuristic — only the source document (a MISMO `true`) or a processor through
    # `StatedLiabilityInput`. `payoff_source` is stamped server-side and never accepted from the
    # client, so a caller cannot label their own judgement as the export's.
    paid_off_at_closing: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Provenance for the flag above — who established it (``mismo`` / ``processor``). Kept
    # separate from the value so "excluded because the 1003 said so" and "excluded because a
    # processor said so" never blur together in an audit.
    payoff_source: Mapped[str | None] = mapped_column(String(_CATEGORY_LEN), nullable=True)

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


class StatedOwnedProperty(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One property the borrower already owns — the 1003's real-estate-owned schedule (LP-596).

    File-level, like assets and liabilities: MISMO carries ``OWNED_PROPERTY`` at the deal level.

    WHY THIS TABLE EXISTS. The parser retained these leaves in ``catch_all`` from the start, but
    ``catch_all`` never reaches the snapshot — so the rule engine could not see them, and three live
    rules were reporting they could not determine facts the application states outright:

    * DT-8 / DT-6 ask whether a mortgage is the lien being refinanced or one on property the borrower
      keeps. ``is_subject`` and ``disposition_status`` answer both.
    * AS-4 waives minimum reserves for a one-unit principal residence, but only when the borrower has
      no OTHER financed properties (B3-4.1-01). Sizing that needs the count, the lien balances, and
      ``current_usage_type`` — the principal residence is excluded from the aggregate.

    STATED, NOT VERIFIED. Everything here is what the application says; a lien balance is corroborated
    by a payoff statement and a value by an appraisal, neither of which this table claims. It is named
    for the ``Stated*`` family for exactly that reason.
    """

    __tablename__ = "stated_owned_properties"

    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # TRI-STATE, and a False is close to meaningless — the real export marks `false` on every block
    # because the subject property lives in its own section rather than being repeated here. Only a
    # True identifies the subject. See `_parse_owned_properties`.
    is_subject: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # MISMO OwnedPropertyDispositionStatusType: Retain / Sell / PendingSale.
    disposition_status: Mapped[str | None] = mapped_column(String(_CATEGORY_LEN), nullable=True)
    # The lien balance on THIS property. Joins to a StatedLiability by amount — in the real export the
    # five UPBs match the five MortgageLoan balances exactly.
    lien_upb: Mapped[Money | None] = mapped_column(nullable=True)
    unit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rental_income_gross: Mapped[Money | None] = mapped_column(nullable=True)
    rental_income_net: Mapped[Money | None] = mapped_column(nullable=True)
    # PrimaryResidence / Investment / SecondHome. The principal residence is EXCLUDED from the
    # reserves aggregate, so this is load-bearing for AS-4 rather than descriptive.
    current_usage_type: Mapped[str | None] = mapped_column(String(_CATEGORY_LEN), nullable=True)
    usage_type: Mapped[str | None] = mapped_column(String(_CATEGORY_LEN), nullable=True)
    estimated_value: Mapped[Money | None] = mapped_column(nullable=True)

    loan_file: Mapped[LoanFile] = relationship(back_populates="stated_owned_properties")


__all__ = [
    "StatedAsset",
    "StatedEmployer",
    "StatedIncomeItem",
    "StatedLiability",
    "StatedOwnedProperty",
]
