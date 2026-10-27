"""A company's own mail domain (LP-991).

Every loan file's email address is `lf-<display_id>@<this domain>`, e.g.
`lf-y36e@mail.staging.mortgageboss.ai`. A company with no ACTIVE row has no file address at all:
nothing shows one and no template mentions one (loan-email.md §3, "No active subdomain").

One row per company, and one company per domain. The domain is stored lowercase with no leading `@`
or dot; `services/mail_domain.normalise_domain` is the one place that shapes it.
"""

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import MEDIUM_STRING

if TYPE_CHECKING:
    from app.models.company import Company


class MailDomainStatus(StrEnum):
    """Whether files of this company get an address on the domain.

    Step 3 adds the onboarding states (and the zone, nameserver and SES identity columns) to this
    same table.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"


class CompanyMailDomain(Base, UUIDMixin, TimestampMixin):
    """The domain a company's file addresses are built on."""

    __tablename__ = "company_mail_domains"

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    domain: Mapped[str] = mapped_column(String(MEDIUM_STRING), unique=True, nullable=False)
    status: Mapped[MailDomainStatus] = mapped_column(str_enum(MailDomainStatus), nullable=False)

    company: Mapped["Company"] = relationship()

    def __repr__(self) -> str:
        return f"<CompanyMailDomain {self.domain} ({self.status})>"
