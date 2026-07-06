"""DtiOverride model (LP-76) — a processor's per-field override of a DTI input.

The DTI calculator auto-populates from the file's structured data, but the
auto-populated values are a trustworthy *starting point*, not a cage: a processor
can override any input (a debt paid at closing, a documented income adjustment, a
bonus to exclude). Each override is one row keyed by a stable ``field_key`` (e.g.
``"housing.taxes"``, ``"debt.<liability_id>"``) holding the override amount; it
**takes precedence** over the auto value and **persists** for the file.

The override row is the *current* state (one per field_key, unique); the
immutable *audit trail* (what changed, the prior value, by whom) lives in the
activity log — every set/clear is logged (LP-76). Clearing an override
soft-deletes the row, so the field falls back to its auto-populated value.

File-owned child (no ``company_id`` — scoped transitively through the loan file,
ADR-052).
"""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.types import Money, ShortStr

if TYPE_CHECKING:
    from app.models.loan_file import LoanFile


class DtiOverride(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One processor override of a DTI calculator input field."""

    __tablename__ = "dti_overrides"
    # One active override per field per file. A cleared override is soft-deleted
    # and revived in place on re-set, so a single row per key is maintained.
    __table_args__ = (
        UniqueConstraint(
            "loan_file_id", "field_key", name="uq_dti_overrides_loan_file_id_field_key"
        ),
    )

    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Stable identifier of the input being overridden, matching the calculator's
    # line keys: "income.<id>" / "debt.<id>" / "housing.principal_interest" /
    # "housing.taxes" / "housing.insurance" / "housing.mortgage_insurance" /
    # "housing.hoa".
    field_key: Mapped[ShortStr] = mapped_column(nullable=False)
    # The override monthly amount (Decimal money, never float).
    value: Mapped[Money] = mapped_column(nullable=False)
    # Optional processor note (why the override) — the reason, for the audit.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Who set the override (SET NULL keeps the row if the user is removed).
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    loan_file: Mapped["LoanFile"] = relationship()

    def __repr__(self) -> str:
        return f"<DtiOverride {self.field_key}={self.value} loan_file_id={self.loan_file_id}>"
