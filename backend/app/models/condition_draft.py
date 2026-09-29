"""A draft email the plan made for a round's conditions (LP-922), linked to Phase 4's message.

The message itself is a `Communication` — Phase 4's draft, with its send, copy and delete — and this row
says which recipient it is for, which round made it and, for a question to the underwriter, which
condition it is about. An ask draft's items point back here (`condition_items.draft_id`).

KEPT OFF `communications.party` ON PURPOSE. Phase 4 finds "the open draft for the title company" by
that column, so a condition draft carrying it would be appended to by Phase 4's compose.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import str_enum


class DraftRecipient(StrEnum):
    """Who a condition draft goes to. Title and attorney share one email (S3-05)."""

    BORROWER = "borrower"
    TITLE_ATTORNEY = "title_attorney"
    LO = "lo"
    INSURANCE = "insurance"
    HOA = "hoa"
    EMPLOYER = "employer"
    OTHER_PARTY = "other_party"
    UNDERWRITER = "underwriter"


class ConditionDraft(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "condition_drafts"
    __table_args__ = (
        UniqueConstraint("communication_id"),
        Index("ix_condition_drafts_loan_file_id", "loan_file_id"),
    )

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), nullable=False
    )
    communication_id: Mapped[UUID] = mapped_column(
        ForeignKey("communications.id", ondelete="CASCADE"), nullable=False
    )
    #: The round whose plan made it. An accumulating draft keeps its first round.
    round_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("condition_rounds.id", ondelete="SET NULL"), nullable=True
    )
    recipient: Mapped[DraftRecipient] = mapped_column(str_enum(DraftRecipient), nullable=False)
    #: A question's condition (S3-06); null for an ask, whose conditions are its items'.
    condition_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conditions.id", ondelete="CASCADE"), nullable=True
    )
    #: When she used the AI's polish of this draft; cleared when the plan re-renders it from the
    #: library (LP-922 follow-up). The dialog's "Polished by AI" mark reads it.
    polished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
