"""Mail-address helpers for tests (LP-991).

`link_mail_domain` gives a company an active mail domain, so its files have the address
`lf-<display_id>@<domain>` (`services/mail_domain.file_address`). Each call makes a new domain:
domains are unique across companies, and tests build several.

`token_address` is the address the inbound resolver still routes on. `LoanFile.get_inbox_address`
composed it until LP-991; the resolver is unchanged until step 4 and still matches
`lf-<inbox_token>@<INBOX_DOMAIN>`, so the tests that feed it mail build that form here. Step 4
replaces it with `file_address`.
"""

from uuid import UUID, uuid4

from app.core.config import settings
from app.models.loan_file import LoanFile
from app.services.mail_domain import set_company_mail_domain
from sqlalchemy.ext.asyncio import AsyncSession


async def link_mail_domain(db: AsyncSession, company_id: UUID) -> str:
    domain = f"mb-mail-{uuid4().hex[:8]}.example.test"
    await set_company_mail_domain(db, company_id=company_id, domain=domain)
    return domain


def token_address(loan_file: LoanFile) -> str:
    return f"lf-{loan_file.inbox_token}@{settings.inbox_domain}"
