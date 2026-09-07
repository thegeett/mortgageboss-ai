"""Who is legitimately part of a loan file's correspondence (LP-805).

THE ALLOWLIST THE TRUST DECISION NEEDS. `phase4.md` §2.3 makes quarantine the default and auto-accept
the narrow exception, and one of its conditions is *sender ∈ loan file participants*. Without this
table that condition is unsatisfiable and every message goes to triage — which is safe, and is also
the product not working.

SEEDABLE FROM WHAT ALREADY EXISTS: `borrowers.email`, `loan_files.loan_officer_email` and
`lenders.contact_email` are all populated today. Seeding rather than asking a processor to type them
is what makes the allowlist real on day one rather than a table nobody fills in.

`is_trusted_sender` IS SEPARATE FROM MEMBERSHIP, deliberately. Being on the file is not the same as
being trusted to drop documents into it: an estate agent is a participant and is not somebody whose
attachments should bypass review. Membership answers "do we know this person"; trust answers "may
their mail be accepted without a human".
"""

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import MEDIUM_STRING

if TYPE_CHECKING:
    from app.models.loan_file import LoanFile


class ParticipantRole(StrEnum):
    """What this person is to the file."""

    BORROWER = "borrower"
    CO_BORROWER = "co_borrower"
    LOAN_OFFICER = "loan_officer"
    AGENT = "agent"
    TITLE = "title"
    UNDERWRITER = "underwriter"
    # LP-820 — the three parties LP-800's catalog sorts documents to and that had no address
    # anywhere in the schema. MEASURED before adding them: of 166 document types, 113 go to the
    # borrower, 24 to the processor (who orders them and needs no request), 16 to the lender — and
    # the remaining 13 went to title, employer, CPA, agent and insurer, of which only title and
    # agent had even a ROLE here, and neither had a writer. A clock for a party with no address is a
    # reminder nobody can act on.
    EMPLOYER = "employer"
    CPA = "cpa"
    INSURER = "insurer"
    OTHER = "other"


class LoanFileParticipant(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One person or organisation on one loan file.

    A file-owned child (ADR-052): no `company_id`, reached only through the file, scoped
    transitively. That is the right shape here for a reason beyond convention — the same email
    address can be a participant on two companies' files, and a company-scoped table would make
    "is this sender known?" a question with a cross-tenant answer.
    """

    __tablename__ = "loan_file_participants"
    __table_args__ = (
        # One row per address per file. Seeding runs more than once — a borrower's email is edited,
        # a loan officer is assigned — and it must converge rather than accumulate.
        Index(
            "uq_loan_file_participants_file_email",
            "loan_file_id",
            "email",
            unique=True,
        ),
        Index("ix_loan_file_participants_email", "email"),
    )

    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[ParticipantRole] = mapped_column(str_enum(ParticipantRole), nullable=False)
    name: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    #: Stored LOWERCASE. Matching a sender against this list is the trust decision's input, and a
    #: case-sensitive comparison would fail to recognise a borrower whose client capitalised their
    #: own address — sending their documents to triage every time.
    email: Mapped[str] = mapped_column(String(MEDIUM_STRING), nullable=False)
    #: Whether mail from this address may be accepted without a human. NOT implied by membership —
    #: see the module docstring. Defaults to False, which is the whole posture of §2.3.
    is_trusted_sender: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    loan_file: Mapped["LoanFile"] = relationship()

    def __repr__(self) -> str:
        return f"<LoanFileParticipant {self.role} loan_file_id={self.loan_file_id}>"
