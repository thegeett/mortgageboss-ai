"""CalculatorOverride model (LP-87) — a processor's per-field override of a calculator input.

The LP-87 calculators (mortgage insurance, self-employed income, reserves, max loan)
reuse the LP-76/77 DTI/LTV override pattern EXACTLY — auto-populated values are a
trustworthy starting point, not a cage; a processor can override any input and the
override takes precedence + persists. Rather than four near-identical override tables,
LP-87 uses ONE table with a ``calculator`` discriminator (the four LP-76/77 semantics
are unchanged — unique active row per (file, calculator, field_key); soft-delete to
revert; the immutable audit trail is the activity log).

File-owned child (no ``company_id`` — scoped transitively through the loan file, ADR-052).
"""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.types import Money, ShortStr

if TYPE_CHECKING:
    from app.models.loan_file import LoanFile


class CalculatorOverride(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One processor override of an LP-87 calculator input field (calculator-discriminated)."""

    __tablename__ = "calculator_overrides"
    # One active override per (file, calculator, field). Cleared → soft-deleted, revived in place.
    __table_args__ = (
        UniqueConstraint(
            "loan_file_id",
            "calculator",
            "field_key",
            name="uq_calculator_overrides_file_calc_field",
        ),
    )

    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Which calculator the override belongs to: "mortgage_insurance" / "self_employed" /
    # "reserves" / "max_loan".
    calculator: Mapped[ShortStr] = mapped_column(nullable=False)
    # Stable identifier of the input being overridden (the calculator's line key).
    field_key: Mapped[ShortStr] = mapped_column(nullable=False)
    # The override amount (Decimal money, never float).
    value: Mapped[Money] = mapped_column(nullable=False)
    # Optional processor note (why the override) — the reason, for the audit.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Who set the override (SET NULL keeps the row if the user is removed).
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    loan_file: Mapped["LoanFile"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<CalculatorOverride {self.calculator}.{self.field_key}={self.value} "
            f"loan_file_id={self.loan_file_id}>"
        )
