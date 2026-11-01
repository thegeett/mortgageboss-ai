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

import asyncio
import hashlib
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.company_mail_domain import CompanyMailDomain, MailDomainStatus
from app.models.loan_file import LoanFile
from app.services.domain_provider import DomainProvider

logger = structlog.get_logger(__name__)

#: Route 53 refuses a `CallerReference` longer than this.
_CALLER_REFERENCE_MAX = 128


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
    """Create or update the company's row. Refuses a domain another company already has, and a row
    `set_up_mail_domain` is setting up or has set up (LP-1005): writing over it would mark it active
    without AWS's check, and keep the old domain's zone.

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
    if row is not None and (
        row.zone_id is not None
        or row.status in (MailDomainStatus.PENDING_NS, MailDomainStatus.VERIFYING)
    ):
        raise MailDomainError(
            f"{row.domain} is being set up by set_up_mail_domain; use that command."
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


def caller_reference(company_id: UUID, domain: str) -> str:
    """LP-1005 — the same zone request every time for one company and domain, so Route 53 hands back
    the first zone instead of creating a second. A very long domain is hashed to fit."""
    reference = f"mb-{company_id}-{domain}"
    if len(reference) > _CALLER_REFERENCE_MAX:
        reference = f"mb-{company_id}-{hashlib.sha256(domain.encode()).hexdigest()[:64]}"
    return reference


async def advance_mail_domain(
    db: AsyncSession, row: CompanyMailDomain, provider: DomainProvider
) -> MailDomainStatus:
    """LP-1005 — move a domain being set up one stage on, as far as AWS and DNS allow today.

    - `pending_ns`, no zone yet: create the zone and save its id and nameservers.
    - `pending_ns` with a zone: once public DNS delegates the subdomain to our nameservers, create
      the SES identity, set MAIL FROM and write the records → `verifying`.
    - `verifying`: once SES has verified DKIM → `active`, and sending switched on (decision 10-31:
      an active domain turns the company on).
    - `active`, `inactive`, `problem`: unchanged here (the hourly check, LP-1006, owns them).

    COMMITS AFTER EACH STAGE, so a crash between two stages resumes from the second. The provider is
    safe to call again for the stage that crashed (see `services/domain_provider`).

    The command and the hourly check (LP-1006) both call this. Returns the status after the call.
    """
    # NOT OURS TO SET UP. A row with no zone was linked by hand (LP-991, e.g. MortgageBoss on
    # mail.staging.mortgageboss.ai, whose DNS and identity Terraform owns). Only a brand-new
    # pending_ns row may start without one. Without this, a hand-linked row put in `verifying`
    # would be checked against SES and switched on, overriding the emergency off.
    if row.zone_id is None and row.status is not MailDomainStatus.PENDING_NS:
        return row.status

    if row.status is MailDomainStatus.PENDING_NS:
        if row.zone_id is None:
            zone_id, nameservers = await asyncio.to_thread(
                provider.create_zone, row.domain, caller_reference(row.company_id, row.domain)
            )
            row.zone_id = zone_id
            row.nameservers = nameservers
        elif await asyncio.to_thread(provider.is_delegated, row.domain, row.nameservers or []):
            await asyncio.to_thread(provider.set_up_identity_and_records, row.domain, row.zone_id)
            row.status = MailDomainStatus.VERIFYING
        else:
            return row.status
    elif row.status is MailDomainStatus.VERIFYING:
        if not await asyncio.to_thread(provider.is_verified, row.domain):
            return row.status
        row.status = MailDomainStatus.ACTIVE
        row.sending_enabled = True
    else:
        return row.status

    await db.commit()
    logger.info("mail_domain_advanced", domain=row.domain, status=row.status.value)
    return row.status


__all__ = [
    "MailDomainError",
    "advance_mail_domain",
    "caller_reference",
    "file_address",
    "file_address_and_sending",
    "normalise_domain",
    "set_company_mail_domain",
    "set_email_sending",
]
