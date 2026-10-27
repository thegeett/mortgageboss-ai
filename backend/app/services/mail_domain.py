"""A company's mail domain and the file address built on it (LP-991).

The address is `lf-<display_id>@<company's active domain>`, e.g. `lf-y36e@mail.staging.mortgageboss.ai`.
`display_id` already carries the `LF-` prefix, so lowercasing it gives the local part.

NO ACTIVE DOMAIN, NO ADDRESS. Before LP-991 the address was `lf-<inbox_token>@<INBOX_DOMAIN>`, a
domain that never received mail, and the document-request templates told borrowers to send documents
there. Returning None is what stops that: every caller hides the address and the templates drop the
sentence.

THE ADDRESS IS NOT A SECRET. `display_id` is guessable by design (ADR-048); the defence is the
authenticated-sender gate — DMARC pass plus a known contact on the file (ADR-397, amended LP-991).

The inbound resolver still reads `lf-<inbox_token>@<settings.inbox_domain>` until step 4 moves it to
`display_id`.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company_mail_domain import CompanyMailDomain, MailDomainStatus
from app.models.loan_file import LoanFile


class MailDomainError(ValueError):
    """The domain cannot be set as asked."""


def normalise_domain(domain: str) -> str:
    """Lowercase, without a leading `@` or dot or a trailing dot. Refuses what is not a hostname."""
    cleaned = domain.strip().lower().lstrip("@.").rstrip(".")
    labels = cleaned.split(".")
    if (
        len(labels) < 2
        or len(cleaned) > 253
        or any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not all(ch.isascii() and (ch.isalnum() or ch == "-") for ch in label)
            for label in labels
        )
    ):
        raise MailDomainError(f"Not a domain: {domain!r}")
    return cleaned


async def active_mail_domain(db: AsyncSession, company_id: UUID) -> str | None:
    """The company's domain if it is active, otherwise None."""
    domain: str | None = await db.scalar(
        select(CompanyMailDomain.domain).where(
            CompanyMailDomain.company_id == company_id,
            CompanyMailDomain.status == MailDomainStatus.ACTIVE,
        )
    )
    return domain


async def file_address(db: AsyncSession, loan_file: LoanFile) -> str | None:
    """`lf-<display_id>@<domain>`, lowercase, or None when the company has no active domain."""
    domain = await active_mail_domain(db, loan_file.company_id)
    if domain is None:
        return None
    return f"{loan_file.display_id.lower()}@{domain}"


async def set_company_mail_domain(
    db: AsyncSession,
    *,
    company_id: UUID,
    domain: str,
    status: MailDomainStatus = MailDomainStatus.ACTIVE,
) -> CompanyMailDomain:
    """Create or update the company's row. Refuses a domain another company already has.

    Flushes, does not commit: the caller owns the transaction.
    """
    cleaned = normalise_domain(domain)
    owner = await db.scalar(
        select(CompanyMailDomain.company_id).where(CompanyMailDomain.domain == cleaned)
    )
    if owner is not None and owner != company_id:
        raise MailDomainError(f"{cleaned} already belongs to another company ({owner}).")

    row = await db.scalar(
        select(CompanyMailDomain).where(CompanyMailDomain.company_id == company_id)
    )
    if row is None:
        row = CompanyMailDomain(company_id=company_id, domain=cleaned, status=status)
        db.add(row)
    else:
        row.domain = cleaned
        row.status = status
    await db.flush()
    return row


__all__ = [
    "MailDomainError",
    "active_mail_domain",
    "file_address",
    "normalise_domain",
    "set_company_mail_domain",
]
