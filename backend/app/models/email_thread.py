"""A conversation on a loan file (LP-805).

WHAT IT IS FOR. Routing rung 2 matches an inbound reply against message ids we generated. That works
because `Communication.external_message_id` already stores them — so this table is NOT the mechanism
that makes rung 2 work, and it is worth saying so plainly rather than implying it.

What it is for is LP-812's timeline and LP-818's reply: a conversation has a root, a subject that
stays stable while clients prepend "Re:" to it, and a participant set that grows as people are cc'd
in. None of that is derivable from a flat list of messages without recomputing it every time.
"""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.types import MEDIUM_STRING

if TYPE_CHECKING:
    from app.models.loan_file import LoanFile


class EmailThread(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One conversation. File-owned (ADR-052): no `company_id`, scoped through the file."""

    __tablename__ = "email_threads"
    __table_args__ = (
        Index(
            "uq_email_threads_file_root",
            "loan_file_id",
            "root_message_id",
            unique=True,
        ),
    )

    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), index=True, nullable=False
    )
    #: The `Message-ID` of the message that started it, normalised without angle brackets.
    root_message_id: Mapped[str] = mapped_column(String(MEDIUM_STRING), nullable=False)
    #: The subject with reply and forward prefixes stripped. Threads survive a client that writes
    #: "Re:", "RE:", "Fwd:" or a localised equivalent; matching on the raw subject does not.
    subject_normalized: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    #: Addresses seen on the thread, as a list. Grows; never used as an allowlist — that is
    #: `loan_file_participants`, and conflating them would let anyone cc'd onto a thread become
    #: trusted by having been cc'd.
    participants: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    loan_file: Mapped["LoanFile"] = relationship()

    def __repr__(self) -> str:
        return f"<EmailThread loan_file_id={self.loan_file_id}>"
