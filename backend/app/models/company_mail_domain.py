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

from sqlalchemy import Boolean, ForeignKey, String, Text, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import MEDIUM_STRING

if TYPE_CHECKING:
    from app.models.company import Company


class MailDomainStatus(StrEnum):
    """Whether files of this company get an address on the domain. Only ACTIVE gives one.

    LP-1005 — the onboarding states `set_up_mail_domain` moves a new domain through:
    PENDING_NS (our zone exists; waiting for the customer's NS record) → VERIFYING (SES identity
    and records written; waiting for AWS) → ACTIVE. PROBLEM is set by the hourly check (LP-1006).
    """

    PENDING_NS = "pending_ns"
    VERIFYING = "verifying"
    ACTIVE = "active"
    PROBLEM = "problem"
    INACTIVE = "inactive"


class CompanyMailDomain(Base, UUIDMixin, TimestampMixin):
    """The domain a company's file addresses are built on."""

    __tablename__ = "company_mail_domains"

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    domain: Mapped[str] = mapped_column(String(MEDIUM_STRING), unique=True, nullable=False)
    status: Mapped[MailDomainStatus] = mapped_column(str_enum(MailDomainStatus), nullable=False)
    #: LP-997 — real email from the app is switched on for this company. Off by default: the
    #: processor sends from her own mail and records it ("Mark as sent"). Turned on with
    #: `app.scripts.set_email_sending` once the company's domain is onboarded for sending; then the
    #: screens offer Send and the API accepts it.
    sending_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    #: LP-1005 — the Route 53 hosted zone `set_up_mail_domain` created for the domain (bare id,
    #: `Z…`) and its four nameservers, which the customer's NS record points at. Both None for a
    #: domain linked by hand (LP-991), whose DNS is not ours to manage here.
    zone_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    nameservers: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    company: Mapped["Company"] = relationship()

    def __repr__(self) -> str:
        sending = ", sending" if self.sending_enabled else ""
        return f"<CompanyMailDomain {self.domain} ({self.status}{sending})>"
