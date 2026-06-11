"""Property model — the subject real estate of a loan file (LP-14).

Every loan is secured by a property. In V1 a loan file has exactly **one**
subject property (a one-to-one), enforced by a unique constraint on
``loan_file_id``: attempting to attach a second property to the same file fails
at the database. Multi-property files (blanket loans, multiple REO) are out of
scope for V1.

Like :class:`~app.models.borrower.Borrower`, a Property has no ``company_id`` of
its own — it is company-scoped *transitively* through its loan file (ADR-052).

Address and valuation fields are nullable: the subject property is often known
only as "TBD" early in a purchase, with the address, type, occupancy, and value
filled in from the purchase contract, appraisal, or processor entry later.
"""

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import MEDIUM_STRING, Money

if TYPE_CHECKING:
    from app.models.loan_file import LoanFile


class PropertyType(StrEnum):
    """The kind of dwelling securing the loan."""

    SINGLE_FAMILY = "single_family"
    CONDO = "condo"
    TOWNHOUSE = "townhouse"
    MULTI_FAMILY = "multi_family"
    MANUFACTURED = "manufactured"
    OTHER = "other"


class OccupancyType(StrEnum):
    """How the borrower will occupy the property.

    Occupancy drives pricing and eligibility (an investment property prices
    differently than a primary residence), so it is a first-class field.
    """

    PRIMARY_RESIDENCE = "primary_residence"
    SECOND_HOME = "second_home"
    INVESTMENT = "investment"


class Property(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """The subject property securing a loan file (one per file in V1)."""

    __tablename__ = "properties"

    # --- Ownership (one-to-one) -------------------------------------------
    # unique=True enforces one property per file (the one-to-one) and also
    # provides the index. ondelete=CASCADE: the property is owned by the file
    # and goes with it on a hard delete (normal flow soft-deletes).
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    # --- Address -----------------------------------------------------------
    address_line: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    address_line_2: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    city: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    # US state as a 2-letter code (e.g. "CA"); free text validated at the schema
    # layer (LP-29), not the DB.
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # --- Classification ----------------------------------------------------
    property_type: Mapped[PropertyType | None] = mapped_column(
        str_enum(PropertyType), nullable=True
    )
    occupancy_type: Mapped[OccupancyType | None] = mapped_column(
        str_enum(OccupancyType), nullable=True
    )

    # --- Valuation (Decimal, never float — see app.models.types.Money) ------
    estimated_value: Mapped[Money | None] = mapped_column(nullable=True)
    # Purchase price applies to purchases; null on refinances.
    purchase_price: Mapped[Money | None] = mapped_column(nullable=True)

    # --- Relationships -----------------------------------------------------
    loan_file: Mapped["LoanFile"] = relationship(back_populates="property")

    def __repr__(self) -> str:
        return f"<Property loan_file_id={self.loan_file_id} type={self.property_type}>"
