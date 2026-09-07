"""Addresses that must not be emailed again (LP-819).

A HARD BOUNCE MEANS THE MAILBOX DOES NOT EXIST. Sending to it again produces another bounce, and
enough of those damage a sending domain's reputation — which is shared by every borrower this system
writes to. So a `5.x.x` is recorded here and the send path refuses.

SCOPED PER COMPANY, even though "this mailbox does not exist" is a fact about the world rather than
about a tenant. Two reasons, and the second is the one that decides it:

* One company's bounce must not silently block another company's send. A borrower shopping two
  brokers is ordinary.
* A shared table would LEAK. "That address is suppressed" tells company B that somebody else has been
  emailing their borrower — the same disclosure LP-811a's rate limit was corrected for.

The cost is a second company learning the same fact the hard way, once. That is the right trade.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import MEDIUM_STRING

if TYPE_CHECKING:
    from app.models.company import Company


class SuppressionReason(StrEnum):
    """Why an address stopped being written to."""

    HARD_BOUNCE = "hard_bounce"  # RFC 3463 5.x.x — permanent
    COMPLAINT = "complaint"  # the recipient marked it as spam
    MANUAL = "manual"  # a person decided


class SuppressedAddress(Base, UUIDMixin, TimestampMixin):
    """One address this company must not email.

    Deliberately NOT soft-deletable. Un-suppressing is a real decision a person makes — a borrower
    fixes their address, or the bounce was a misconfiguration at their end — and it should be a
    DELETE that leaves the activity log as the record, not a tombstone that a later query forgets to
    filter out. A suppression that is silently still in force is worse than one that is gone.
    """

    __tablename__ = "suppressed_addresses"
    __table_args__ = (
        Index(
            "uq_suppressed_addresses_company_address",
            "company_id",
            "address",
            unique=True,
        ),
    )

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    #: Stored LOWERCASE. The local part is case-sensitive per RFC 5321 and case-insensitive in
    #: practice at every provider anyone uses; matching case-sensitively would let one typo of
    #: capitalisation walk straight past a suppression.
    address: Mapped[str] = mapped_column(String(MEDIUM_STRING), nullable=False)
    reason: Mapped[SuppressionReason] = mapped_column(str_enum(SuppressionReason), nullable=False)
    #: The RFC 3463 status the provider returned, e.g. `5.1.1`. Kept verbatim.
    status_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: The provider's own words. Useful to a person deciding whether to un-suppress; never shown to
    #: a borrower, and never logged.
    diagnostic: Mapped[str | None] = mapped_column(Text, nullable=True)
    suppressed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    company: Mapped["Company"] = relationship()

    def __repr__(self) -> str:
        return f"<SuppressedAddress {self.reason} company_id={self.company_id}>"
