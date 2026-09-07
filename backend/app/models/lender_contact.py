"""A named person at a lender (LP-813).

PROCESSORS WORK WITH UNDERWRITERS, NOT INSTITUTIONS. `Lender` has carried a single `contact_email`
since LP-13 and its own docstring says it is "for direct underwriter communication" — but one address
per lender cannot express what the work actually looks like: UWM has many underwriters, a file is
assigned to one of them, and the one on this file is not the one on the next.

NO `company_id`, AND THAT IS THE POINT. A contact is reached only through its lender, and a lender is
company-owned — so scoping is transitive, the same shape ADR-052 gives file-owned children. Storing
the company here as well would make a contact whose `company_id` disagreed with its lender's a
representable state, and nothing would ever notice. The same underwriter really does work with
several processing companies; each configures its own `Lender` row for UWM (ADR-045), so each gets
its own contact row, and one company editing a phone number cannot change what another company sees.
"""

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import LONG_STRING, MEDIUM_STRING, SHORT_STRING, MediumStr

if TYPE_CHECKING:
    from app.models.lender import Lender


class LenderContactRole(StrEnum):
    """What this person does at the lender.

    UNDERWRITER is the one the product is built around; the others exist so a processor recording a
    real contact is not forced to call them an underwriter, which would then be wrong on the file.
    """

    UNDERWRITER = "underwriter"
    ACCOUNT_EXECUTIVE = "account_executive"
    CLOSER = "closer"
    OTHER = "other"


class LenderContact(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One person at one lender."""

    __tablename__ = "lender_contacts"
    __table_args__ = (
        # THE SAME PERSON ENTERED TWICE IS THE FAILURE TO PREVENT. Two rows for one underwriter
        # under two spellings of their address means a file assigned to one of them and mail
        # arriving from the other — so the participant lookup misses and their reply goes to triage.
        #
        # Case-insensitive, because that is how the address is compared everywhere else
        # (`normalise_address`), and partial, because a contact with no email is a legitimate row —
        # a phone-only contact — and several of them must not collide on NULL.
        Index(
            "uq_lender_contacts_lender_email",
            "lender_id",
            func.lower(text("email")),
            unique=True,
            postgresql_where=text("email IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    lender_id: Mapped[UUID] = mapped_column(
        # RESTRICT, matching `lenders.company_id`: lenders are soft-deleted, never hard-deleted, so
        # a cascade here would only ever fire on a delete that is not supposed to happen.
        ForeignKey("lenders.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )

    name: Mapped[MediumStr] = mapped_column(nullable=False)
    #: Stored as given, compared lowercased. The one field that makes this contact reachable —
    #: LP-805 seeds participants from it, which is what lets their reply route rather than triage.
    email: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    role: Mapped[LenderContactRole] = mapped_column(
        str_enum(LenderContactRole), default=LenderContactRole.UNDERWRITER, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(String(LONG_STRING), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    lender: Mapped["Lender"] = relationship()

    def __repr__(self) -> str:
        return f"<LenderContact {self.role} lender={self.lender_id}>"
