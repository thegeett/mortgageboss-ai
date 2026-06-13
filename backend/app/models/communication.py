"""Communication model — messages in and out of a loan file (LP-20).

Records borrower document requests, lender condition responses, and inbound
borrower replies (which arrive via the loan file's inbox token, LP-13) — a single
timeline of everything said and heard about a file. It is the data foundation for
the Phase 4 communication module.

This ticket creates the **record** and a minimal create helper. Email **sending**
and inbound **routing** are Phase 4; here a communication is just persisted state.

A communication is a separate model from :class:`~app.models.activity_log.
ActivityLog` (ADR-070): it carries message-specific fields (sender/recipient/
subject/body) that an event log doesn't need. A *sent* communication may also
produce an activity-log entry.

Like other file-owned children, a communication has no ``company_id`` — it is
company-scoped transitively through its loan file (ADR-052). The needs-item and
initiating-user links are ``SET NULL`` so the message survives if the referenced
row is removed.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import MEDIUM_STRING

if TYPE_CHECKING:
    from app.models.loan_file import LoanFile
    from app.models.needs_item import NeedsItem
    from app.models.user import User


class CommunicationDirection(StrEnum):
    """Whether the message was received by us or sent by us."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CommunicationChannel(StrEnum):
    """The medium of the message.

    V1 is **email only** (enabled by the loan file's inbox token, ADR-072).
    Other channels (phone, SMS, portal) can be added later as new VARCHAR + CHECK
    values without a type migration — listing them now would imply capabilities
    that don't exist yet.
    """

    EMAIL = "email"


class CommunicationStatus(StrEnum):
    """Delivery state. DRAFT/SENT/DELIVERED/FAILED are outbound; RECEIVED inbound."""

    DRAFT = "draft"  # outbound, not yet sent
    SENT = "sent"  # outbound, sent
    DELIVERED = "delivered"  # outbound, delivery confirmed (if known)
    FAILED = "failed"  # outbound, send failed
    RECEIVED = "received"  # inbound


class Communication(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A message associated with a loan file."""

    __tablename__ = "communications"

    # --- Ownership (owned child of the loan file, ADR-052) -----------------
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # --- Envelope ----------------------------------------------------------
    direction: Mapped[CommunicationDirection] = mapped_column(
        str_enum(CommunicationDirection), index=True, nullable=False
    )
    channel: Mapped[CommunicationChannel] = mapped_column(
        str_enum(CommunicationChannel),
        default=CommunicationChannel.EMAIL,
        nullable=False,
    )
    status: Mapped[CommunicationStatus] = mapped_column(
        str_enum(CommunicationStatus), index=True, nullable=False
    )
    sender: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    recipient: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Links + provenance ------------------------------------------------
    # The need this message concerns, if any (e.g. a document request). SET NULL:
    # the message survives if the need is removed.
    needs_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("needs_items.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    # The user who initiated an outbound message; null for inbound/system. SET NULL.
    initiated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # e.g. an inbound email Message-ID, kept for threading/dedup.
    external_message_id: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Relationships -----------------------------------------------------
    loan_file: Mapped["LoanFile"] = relationship(back_populates="communications")
    needs_item: Mapped["NeedsItem | None"] = relationship()
    initiated_by: Mapped["User | None"] = relationship()

    def __repr__(self) -> str:
        return f"<Communication {self.direction}/{self.status} loan_file_id={self.loan_file_id}>"
