"""LtvOverride model (LP-77) — a processor's per-field override of an LTV input.

The LTV calculator (the parallel to DTI, LP-76) auto-populates from the file's
structured data, but any input is override-able — the appraised value (the
appraisal may not be extracted yet), a second lien, a HELOC's credit limit. Each
override is one row keyed by a stable ``field_key`` (e.g. ``"ltv.appraised_value"``,
``"ltv.heloc_credit_limit"``) holding the override amount; it **takes precedence**
over the auto value and **persists** for the file.

Mirrors :class:`~app.models.dti_override.DtiOverride` exactly (the current state is
one row per field_key; the immutable audit trail lives in the activity log).
File-owned child (scoped transitively through the loan file).
"""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.types import Money, ShortStr

if TYPE_CHECKING:
    from app.models.loan_file import LoanFile


class LtvOverride(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One processor override of an LTV calculator input field."""

    __tablename__ = "ltv_overrides"
    __table_args__ = (
        UniqueConstraint(
            "loan_file_id", "field_key", name="uq_ltv_overrides_loan_file_id_field_key"
        ),
    )

    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Stable identifier of the input being overridden, matching the calculator's
    # line keys: "ltv.first_loan" / "ltv.second_loan" / "ltv.heloc_drawn" /
    # "ltv.heloc_credit_limit" / "ltv.purchase_price" / "ltv.appraised_value".
    field_key: Mapped[ShortStr] = mapped_column(nullable=False)
    value: Mapped[Money] = mapped_column(nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    loan_file: Mapped["LoanFile"] = relationship()

    def __repr__(self) -> str:
        return f"<LtvOverride {self.field_key}={self.value} loan_file_id={self.loan_file_id}>"
