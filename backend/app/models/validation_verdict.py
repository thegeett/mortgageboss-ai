"""ValidationVerdict model (LP-89) — the captured verdict on a grounded-starter item.

Every rule (LP-82..86) and calculator methodology (LP-87) is GROUNDED-STARTER — researched
against the real sources but NOT yet validated by the domain expert (Priya). Her session is
the validation. This table CAPTURES her verdict per item as the developer records it during
that session — it does NOT fabricate validation. A row exists only once a verdict is
recorded; the absence of a row means the item is still ``grounded_starter`` (the default).

Company-scoped (each company validates for its own lenders/scenarios) + self-audited (the
actor + timestamps + the corrected value ARE the LP-80.5 value-recording trail). The verdict
applies because Priya said so (recorded with attribution), not because the system decided.
"""

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import MediumStr, ShortStr

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.user import User


class VerdictKind(StrEnum):
    """The domain expert's verdict on a grounded-starter item (recorded, not inferred).

    ``VALIDATED`` — confirmed correct as-is; ``CORRECTED`` — a new value/threshold given
    (captured in ``corrected_value`` + a note); ``FLAGGED_REMOVE`` — not applicable / wrong
    (the note says why); ``ADD_NEW`` — a missing rule/check she names (the note describes it;
    ``item_id`` is null — it isn't an existing inventory item yet).
    """

    VALIDATED = "validated"
    CORRECTED = "corrected"
    FLAGGED_REMOVE = "flagged_remove"
    ADD_NEW = "add_new"


class ValidationVerdict(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One captured verdict on a grounded-starter rule / calculator methodology item."""

    __tablename__ = "validation_verdicts"
    # One active verdict per (company, item). NULL item_id (ADD_NEW) rows are exempt —
    # Postgres treats NULLs as distinct, so multiple proposed additions coexist.
    __table_args__ = (
        UniqueConstraint("company_id", "item_id", name="uq_validation_verdicts_company_item"),
    )

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The inventory item this verdict is about (a rule_id like "conv.dti.back_end_max" or a
    # methodology id like "calc.pmi_rate"). NULL only for an ADD_NEW proposal.
    item_id: Mapped[ShortStr | None] = mapped_column(nullable=True, index=True)
    kind: Mapped[VerdictKind] = mapped_column(str_enum(VerdictKind), nullable=False)
    # The corrected value Priya gave (CORRECTED) — stored as a string (exact, audit-safe).
    corrected_value: Mapped[ShortStr | None] = mapped_column(nullable=True)
    # A short label for an ADD_NEW proposal (the missing rule's name).
    title: Mapped[MediumStr | None] = mapped_column(nullable=True)
    # Priya's rationale / the correction note / why-remove / the addition description.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Who recorded it (the developer in the session) — the attribution.
    recorded_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    company: Mapped["Company"] = relationship()
    recorded_by: Mapped["User | None"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<ValidationVerdict {self.item_id or 'add_new'}={self.kind} company={self.company_id}>"
        )
