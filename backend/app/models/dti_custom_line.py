"""DtiCustomLine model (LP-643) — a line a PROCESSOR added to the DTI, that the engine did not.

WHY THIS IS NOT A `DtiOverride`. An override changes the VALUE of a line the calculator produced, and
is keyed by the `field_key` the calculator emitted. A processor-added row has no such key, because
nothing produced it — a documented obligation the credit report missed, an income source the file
states nowhere structured. Reusing `field_key` would mean inventing keys for lines the engine has
never heard of, and `uq_dti_overrides_loan_file_id_field_key` would then collide two unrelated
additions on one made-up name.

THREE PROPERTIES IT SHARES WITH AN OVERRIDE, deliberately:

  * it PERSISTS per file, so a processor's work survives the next document upload and the
    recomputation that follows;
  * it is SOFT-DELETED rather than erased, so removing one leaves the trail;
  * it carries a `note`, because a DTI is the number a loan qualifies on and a figure nobody can
    attribute is a figure with no author.

AND ONE IT DOES NOT: an added row does NOT clear a gate. A gate says a REQUIRED INPUT IS UNKNOWN, and
adding an unrelated row does not make it known — a processor who types "Rent — $2,000" into income
has not produced the Form 1007 that B3-3.8-02 requires. Overriding the gated line itself remains the
way to supply a figure, and that path already clears the gate because it answers the actual question.
See `services/dti.py` for where that is enforced.

REMOVING AN ENGINE LINE IS A DIFFERENT ACT and does not belong here. Deleting a liability the credit
report produced is an EXCLUSION — a claim that a real debt should not count — and the calculator
already renders that as a struck-through line with its reason (`excluded_reason`), which is visible
where a vanished row is not. Only lines added through this model can be removed through it.

File-owned child (no ``company_id`` — scoped transitively through the loan file, ADR-052).
"""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.types import Money, ShortStr

if TYPE_CHECKING:
    from app.models.loan_file import LoanFile


class DtiCustomLine(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One processor-added DTI line: which section it belongs to, what it is, and how much."""

    __tablename__ = "dti_custom_lines"

    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    #: "income" | "housing" | "debt" — which side of the ratio this lands on. Not an enum column:
    #: the calculator's three sections are its own vocabulary and a fourth would be a calculator
    #: change, not a migration. Validated at the API boundary.
    section: Mapped[ShortStr] = mapped_column(nullable=False)
    #: What a processor reads on the line. Theirs, not generated — the whole point is a row the
    #: engine could not name.
    label: Mapped[ShortStr] = mapped_column(nullable=False)
    #: The monthly amount (Decimal money, never float).
    value: Mapped[Money] = mapped_column(nullable=False)
    #: WHY this line exists. Optional in the column and expected in practice: the audit trail for a
    #: figure that entered a qualifying ratio without any document behind it.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # A bare relationship, matching `DtiOverride`: `LoanFile` carries no collection for either,
    # since both are read by the calculator through an explicit query rather than by traversal.
    loan_file: Mapped["LoanFile"] = relationship()

    def __repr__(self) -> str:
        return f"<DtiCustomLine {self.section}/{self.label} {self.value}>"
