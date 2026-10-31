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
`display_id`, so until then `settings.file_addresses_enabled` is off and no address is shown anywhere.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
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


async def file_address_and_sending(
    db: AsyncSession, loan_file: LoanFile
) -> tuple[str | None, bool]:
    """The file address (see `file_address`) and whether the company is switched on for sending
    (LP-997), from one read of the company's row. `(None, False)` when there is no address."""
    if not settings.file_addresses_enabled:
        return None, False
    row = (
        await db.execute(
            select(CompanyMailDomain.domain, CompanyMailDomain.sending_enabled).where(
                CompanyMailDomain.company_id == loan_file.company_id,
                CompanyMailDomain.status == MailDomainStatus.ACTIVE,
            )
        )
    ).first()
    if row is None:
        return None, False
    return f"{loan_file.display_id.lower()}@{row.domain}", bool(row.sending_enabled)


async def file_address(db: AsyncSession, loan_file: LoanFile) -> str | None:
    """`lf-<display_id>@<domain>`, lowercase, or None.

    None when the company has no active domain, and for every company while
    `settings.file_addresses_enabled` is off (nothing routes the address until step 4).
    """
    address, _ = await file_address_and_sending(db, loan_file)
    return address


async def set_email_sending(
    db: AsyncSession, *, company_id: UUID, enabled: bool
) -> CompanyMailDomain:
    """LP-997 — switch real email from the app on or off. Refuses a company with no active domain:
    the app sends From the file address, which needs one. Flushes; the caller commits."""
    row = await db.scalar(
        select(CompanyMailDomain).where(CompanyMailDomain.company_id == company_id)
    )
    if row is None or row.status is not MailDomainStatus.ACTIVE:
        raise MailDomainError("This company has no active mail domain; link one first.")
    row.sending_enabled = enabled
    await db.flush()
    return row


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
    # The check above and this write are two statements, so a concurrent writer can take the domain
    # (or create this company's row) between them. The unique constraints refuse it; the savepoint
    # keeps that refusal from poisoning the caller's transaction, so it reads like the check's own.
    try:
        async with db.begin_nested():
            if row is None:
                row = CompanyMailDomain(company_id=company_id, domain=cleaned, status=status)
                db.add(row)
            else:
                row.domain = cleaned
                row.status = status
    except IntegrityError as exc:
        raise MailDomainError(
            f"{cleaned} could not be set: another write took it or this company's row first."
        ) from exc
    return row


__all__ = [
    "MailDomainError",
    "file_address",
    "file_address_and_sending",
    "normalise_domain",
    "set_company_mail_domain",
    "set_email_sending",
]
