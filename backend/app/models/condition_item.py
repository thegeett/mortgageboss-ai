"""One thing a condition asks for, and what we are doing about it (LP-920, plan §5 LP-920).

The plan for a condition is its items plus, when the whole condition takes one step, its `next_step`
(`conditions.next_step`). Each item records the action (`option`), who acts (`performer` and the full
`performers` list, since 0132's disclosure is Borrower + LO), its own status, due date, the need it asks
through (`need_id`: one need can serve items on several conditions, §4a change 2), the document already
in the file (`document_id`) and the condition it waits on.

`specifics` restates the lender's amounts, bank and last four for this item: NPI, so no readonly view
carries this table.
"""

from datetime import date
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.condition_vocabulary import (
    ConditionItemOrigin,
    ConditionItemStatus,
    Performer,
    PlanOption,
)
from app.models.enums import str_enum

if TYPE_CHECKING:
    from app.models.condition import Condition


class ConditionItem(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "condition_items"
    __table_args__ = (
        Index("ix_condition_items_condition_id", "condition_id"),
        Index("ix_condition_items_loan_file_id", "loan_file_id"),
        Index("ix_condition_items_need_id", "need_id"),
    )

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), nullable=False
    )
    condition_id: Mapped[UUID] = mapped_column(
        ForeignKey("conditions.id", ondelete="CASCADE"), nullable=False
    )
    #: The round whose plan created it (a carried item keeps its first round's id).
    round_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("condition_rounds.id", ondelete="SET NULL"), nullable=True
    )
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    acceptable: Mapped[str] = mapped_column(Text, nullable=False, default="")
    performer: Mapped[Performer] = mapped_column(str_enum(Performer), nullable=False)
    performers: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    option: Mapped[PlanOption] = mapped_column(str_enum(PlanOption), nullable=False)
    status: Mapped[ConditionItemStatus] = mapped_column(
        str_enum(ConditionItemStatus),
        default=ConditionItemStatus.OPEN,
        server_default=ConditionItemStatus.OPEN.value,
        nullable=False,
    )
    origin: Mapped[ConditionItemOrigin] = mapped_column(
        str_enum(ConditionItemOrigin), default=ConditionItemOrigin.READING, nullable=False
    )
    documents: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    checks: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    specifics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    need_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("needs_items.id", ondelete="SET NULL"), nullable=True
    )
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    document_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    waits_on_condition_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conditions.id", ondelete="SET NULL"), nullable=True
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    condition: Mapped["Condition"] = relationship(foreign_keys=[condition_id])
