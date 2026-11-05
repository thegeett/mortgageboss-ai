"""A company's mail domain and the file address built on it (LP-991).

The address is `lf-<display_id>@<company's active domain>`, e.g. `lf-y36e@mail.staging.mortgageboss.ai`.
`display_id` already carries the `LF-` prefix, so lowercasing it gives the local part.

NO ACTIVE DOMAIN, NO ADDRESS. Before LP-991 the address was `lf-<inbox_token>@<INBOX_DOMAIN>`, a
domain that never received mail, and the document-request templates told borrowers to send documents
there. Returning None is what stops that: every caller hides the address and the templates drop the
sentence.

THE ADDRESS IS NOT A SECRET. `display_id` is guessable by design (ADR-048); the defence is the
authenticated-sender gate — DMARC pass plus a known contact on the file (ADR-397, amended LP-991).

The inbound resolver reads this address since LP-1008. `settings.file_addresses_enabled` still hides
it wherever it is off, until LP-1011 removes the setting.
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
from app.services.domain_provider import DomainProvider, DomainSetupError

logger = structlog.get_logger(__name__)

#: LP-1006 — why a company's email is paused: the Send screen, the API's refusal and the worker.
MAIL_DOMAIN_PAUSED = "Email for this company is paused: its DNS setup changed. Contact support."

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
                # LP-1006 — a domain with a problem keeps its addresses, but doesn't send.
                CompanyMailDomain.status.in_([MailDomainStatus.ACTIVE, MailDomainStatus.PROBLEM]),
            )
        )
    ).first()
    if row is None:
        return None, False
    return f"{loan_file.display_id.lower()}@{row.domain}", bool(row.sending_enabled)


async def file_address(db: AsyncSession, loan_file: LoanFile) -> str | None:
    """`lf-<display_id>@<domain>`, lowercase, or None.

    None when the company has no active domain, and for every company while
    `settings.file_addresses_enabled` is off (LP-1011 removes it). A domain with a problem keeps its addresses (LP-1006), so an address alone doesn't mean it may send.
    """
    address, _ = await file_address_and_sending(db, loan_file)
    return address


async def mail_domain_paused(db: AsyncSession, company_id: UUID) -> bool:
    """LP-1006 — the company's domain is in `problem`: the hourly check found its setup broken."""
    status = await db.scalar(
        select(CompanyMailDomain.status).where(CompanyMailDomain.company_id == company_id)
    )
    return status is MailDomainStatus.PROBLEM


async def set_email_sending(
    db: AsyncSession, *, company_id: UUID, enabled: bool
) -> CompanyMailDomain:
    """LP-997 — switch real email from the app on or off. Refuses a company with no active domain:
    the app sends From the file address, which needs one. Flushes; the caller commits.

    LP-1006 — a domain in `problem` can be switched off, so that it stays off when the domain
    recovers (the emergency off). It can't be switched on until then."""
    row = await db.scalar(
        select(CompanyMailDomain).where(CompanyMailDomain.company_id == company_id)
    )
    if row is not None and row.status is MailDomainStatus.PROBLEM and enabled:
        raise MailDomainError(MAIL_DOMAIN_PAUSED)
    if row is None or row.status not in (MailDomainStatus.ACTIVE, MailDomainStatus.PROBLEM):
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
            f"{row.domain} is managed by set_up_mail_domain; this command can't change it."
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


async def replace_pending_domain(db: AsyncSession, *, row: CompanyMailDomain, domain: str) -> None:
    """LP-1005 — correct a domain that is still waiting for its NS record. Nothing is live at that
    stage, so the row simply starts again; later stages have real records and mail behind them, so
    they are refused. Forgets the old zone: the caller tells the operator to delete it.

    Flushes, does not commit: the caller owns the transaction.
    """
    if row.status is not MailDomainStatus.PENDING_NS:
        raise MailDomainError(f"{row.domain} is {row.status.value}, past pending_ns.")
    cleaned = normalise_domain(domain)
    owner = await db.scalar(
        select(CompanyMailDomain.company_id).where(CompanyMailDomain.domain == cleaned)
    )
    if owner is not None and owner != row.company_id:
        raise MailDomainError(f"{cleaned} already belongs to another company ({owner}).")
    try:
        async with db.begin_nested():
            row.domain = cleaned
            row.zone_id = None
            row.nameservers = None
    except IntegrityError as exc:
        raise MailDomainError(f"{cleaned} could not be set: another write took it first.") from exc


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


async def lock_mail_domain(db: AsyncSession, row_id: UUID) -> CompanyMailDomain | None:
    """LP-1006 — lock the row and read it fresh, or None when someone else holds it. Stops the command
    and the hourly check working on one domain at once. The lock ends at the next commit or rollback,
    so `advance_mail_domain`'s commit ends it; each stage locks again."""
    row: CompanyMailDomain | None = await db.scalar(
        select(CompanyMailDomain)
        .where(CompanyMailDomain.id == row_id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    return row


async def _check_locked(db: AsyncSession, row: CompanyMailDomain, provider: DomainProvider) -> str:
    if row.zone_id is None or row.status is MailDomainStatus.INACTIVE:
        return "skipped"
    if row.status in (MailDomainStatus.PENDING_NS, MailDomainStatus.VERIFYING):
        return (await advance_mail_domain(db, row, provider)).value

    delegation = await asyncio.to_thread(
        provider.delegation_state, row.domain, row.nameservers or []
    )
    dkim = await asyncio.to_thread(provider.dkim_state, row.domain)
    if row.status is MailDomainStatus.ACTIVE and (delegation == "wrong" or dkim == "failed"):
        row.status = MailDomainStatus.PROBLEM
        logger.warning("mail_domain_problem", domain=row.domain, delegation=delegation, dkim=dkim)
        return MailDomainStatus.PROBLEM.value
    if row.status is MailDomainStatus.PROBLEM and delegation == "ok" and dkim == "ok":
        # `sending_enabled` stays as it is: someone may have switched it off on purpose.
        row.status = MailDomainStatus.ACTIVE
        logger.info("mail_domain_recovered", domain=row.domain)
        return MailDomainStatus.ACTIVE.value
    return "unchanged"


async def check_mail_domain(
    db: AsyncSession, row: CompanyMailDomain, provider: DomainProvider
) -> str:
    """LP-1006 — one domain's hourly check. Returns what happened, for the log.

    - No zone (linked by hand) or `inactive`: `skipped`, never touched.
    - `pending_ns`, `verifying`: `advance_mail_domain`; returns the new status.
    - `active`: a CLEAR failure, in DNS or at SES → `problem`. Otherwise `unchanged`.
    - `problem`: DNS and SES both fine → `active`. Otherwise `unchanged`.
    - An error from AWS while advancing: `error`, nothing changed; the next hour tries again.
    - Someone else holds the row (the command): `locked`, nothing changed.

    A hiccup (`unknown`) never moves a domain, so a timeout can't pause a company's email.

    COMMITS, which ends the lock.
    """
    domain = row.domain
    locked = await lock_mail_domain(db, row.id)
    if locked is None:
        await db.commit()
        return "locked"
    try:
        outcome = await _check_locked(db, locked, provider)
    except DomainSetupError as exc:
        await db.rollback()
        logger.warning("mail_domain_check_failed", domain=domain, error_code=exc.code)
        return "error"
    await db.commit()
    return outcome


__all__ = [
    "MAIL_DOMAIN_PAUSED",
    "MailDomainError",
    "advance_mail_domain",
    "caller_reference",
    "check_mail_domain",
    "file_address",
    "file_address_and_sending",
    "lock_mail_domain",
    "mail_domain_paused",
    "normalise_domain",
    "replace_pending_domain",
    "set_company_mail_domain",
    "set_email_sending",
]
