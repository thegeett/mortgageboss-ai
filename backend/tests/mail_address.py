"""Mail-address helpers for tests (LP-991).

`link_mail_domain` gives a company an active mail domain, so its files have the address
`lf-<display_id>@<domain>` (`services/mail_domain.file_address`). Each call makes a new domain:
domains are unique across companies, and tests build several.

`file_mail_address` is a file's address, linking a domain to its company first if it has none.
`deliver` runs a raw message through the real ingest with its `To` header as the SES envelope, for
tests about what happens after routing. Tests about routing itself pass `receipt` directly.
"""

import email
from email.utils import getaddresses
from typing import Any
from uuid import UUID, uuid4

from app.models.company_mail_domain import CompanyMailDomain, MailDomainStatus
from app.models.loan_file import LoanFile
from app.services.inbound_ingest import IngestResult, process_raw_message
from app.services.mail_domain import set_company_mail_domain
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def link_mail_domain(db: AsyncSession, company_id: UUID) -> str:
    domain = f"mb-mail-{uuid4().hex[:8]}.example.test"
    await set_company_mail_domain(db, company_id=company_id, domain=domain)
    return domain


async def file_mail_address(db: AsyncSession, loan_file: LoanFile) -> str:
    domain: str | None = await db.scalar(
        select(CompanyMailDomain.domain).where(CompanyMailDomain.company_id == loan_file.company_id)
    )
    if domain is None:
        domain = await link_mail_domain(db, loan_file.company_id)
    return f"{loan_file.display_id.lower()}@{domain}"


async def deliver(
    db: AsyncSession, *, raw: bytes, receipt: dict[str, Any] | None = None, **kwargs: Any
) -> IngestResult:
    to = email.message_from_bytes(raw).get_all("To", [])
    recipients = [address for _name, address in getaddresses(to) if address]
    return await process_raw_message(
        db, raw=raw, receipt={"recipients": recipients, **(receipt or {})}, **kwargs
    )


async def _active_row(db: AsyncSession, company_id: UUID) -> CompanyMailDomain | None:
    row: CompanyMailDomain | None = await db.scalar(
        select(CompanyMailDomain).where(
            CompanyMailDomain.company_id == company_id,
            CompanyMailDomain.status == MailDomainStatus.ACTIVE,
        )
    )
    return row


async def active_mail_domain(db: AsyncSession, company_id: UUID) -> str | None:
    """The company's active domain, or None. (The app reads it with the sending switch, in one
    query: `mail_domain.file_address_and_sending`, LP-997.)"""
    row = await _active_row(db, company_id)
    return row.domain if row else None


async def sending_switched_on(db: AsyncSession, company_id: UUID) -> bool:
    """LP-997 — the company's active domain has sending from the app switched on."""
    row = await _active_row(db, company_id)
    return bool(row and row.sending_enabled)
