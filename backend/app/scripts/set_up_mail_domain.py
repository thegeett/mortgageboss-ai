"""Set up a customer's mail subdomain, in stages, during their onboarding call (LP-1005).

Usage::

    uv run python -m app.scripts.set_up_mail_domain <company id or exact name> <subdomain>

Each run moves the domain on as far as it can (`services/mail_domain.advance_mail_domain`) and says
where it is and what comes next:

1. pending_ns: our Route 53 zone exists. Prints the NS record the customer adds at their DNS provider.
2. verifying: the NS record is live; the SES identity and every record are written. AWS verifies.
3. active: AWS has verified the domain. Files get `lf-…@<subdomain>` and sending is switched on.

Safe to run again at any point; nothing is created twice. The hourly check (LP-1006) runs the same
step on its own, so nobody has to wait by the keyboard while DNS spreads.

Refuses a subdomain of mortgageboss.ai (ours, managed by Terraform), a subdomain another company
has, and a company that already has a different domain (changing a domain is manual for now).

In staging this runs as a one-off ECS task; see `docs/tickets/LP-1005.md` for the command.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker
from app.models.company import Company
from app.models.company_mail_domain import CompanyMailDomain, MailDomainStatus
from app.scripts.set_company_mail_domain import find_company
from app.services.domain_provider import (
    DomainProvider,
    DomainProviderNotAllowed,
    DomainSetupError,
    get_domain_provider,
)
from app.services.mail_domain import (
    MailDomainError,
    advance_mail_domain,
    normalise_domain,
    set_company_mail_domain,
)

#: Our own domain. Its subdomains are Terraform's (LP-1004 denies the app any change to them).
OUR_DOMAIN = "mortgageboss.ai"
#: Zone, then verifying, then active.
MAX_STEPS = 3


async def prepare(
    db: AsyncSession, *, company_ref: str, subdomain: str
) -> tuple[Company, CompanyMailDomain]:
    """Find the company and its row for `subdomain`, creating it (pending_ns) if it has none.
    Refuses what the module docstring lists. Flushes; `advance_mail_domain` commits."""
    cleaned = normalise_domain(subdomain)
    if cleaned == OUR_DOMAIN or cleaned.endswith("." + OUR_DOMAIN):
        raise MailDomainError(
            f"{cleaned} is under {OUR_DOMAIN}, which is ours and managed by Terraform."
        )
    company = await find_company(db, company_ref)
    row = await db.scalar(
        select(CompanyMailDomain).where(CompanyMailDomain.company_id == company.id)
    )
    if row is not None and row.domain != cleaned:
        raise MailDomainError(
            f"{company.name} already has the domain {row.domain}; changing a domain is manual for now."
        )
    if row is None:
        # Refuses a subdomain another company has.
        row = await set_company_mail_domain(
            db, company_id=company.id, domain=cleaned, status=MailDomainStatus.PENDING_NS
        )
        await db.flush()
    return company, row


async def run(
    db: AsyncSession, *, company_ref: str, subdomain: str, provider: DomainProvider
) -> tuple[Company, CompanyMailDomain, bool]:
    """Prepare, then advance until nothing changes (at most `MAX_STEPS`). Returns whether this run
    created the zone."""
    company, row = await prepare(db, company_ref=company_ref, subdomain=subdomain)
    zone_created = False
    for _ in range(MAX_STEPS):
        before = (row.status, row.zone_id)
        await advance_mail_domain(db, row, provider)
        if before[1] is None and row.zone_id is not None:
            zone_created = True
        if (row.status, row.zone_id) == before:
            break
    return company, row, zone_created


def describe(company: Company, row: CompanyMailDomain, *, zone_created: bool) -> list[str]:
    lines = [f"{company.name} ({company.id}): {row.domain} [{row.status.value}]"]
    if row.nameservers and (zone_created or row.status is MailDomainStatus.PENDING_NS):
        lines.append("Ask the customer to add this record at their DNS provider:")
        lines.append(f"  Name: {row.domain}   Type: NS   Value:")
        lines.extend(f"    {name}" for name in row.nameservers)
    if row.status is MailDomainStatus.PENDING_NS:
        lines.append("Then run this command again (or wait for the hourly check).")
    elif row.status is MailDomainStatus.VERIFYING:
        lines.append("Records written. Waiting for AWS to verify (usually minutes).")
    elif row.status is MailDomainStatus.ACTIVE:
        lines.append(f"Active. Files of {company.name} now use lf-…@{row.domain}.")
    else:
        lines.append(f"Nothing to do here while the domain is {row.status.value}.")
    return lines


async def _main(args: argparse.Namespace) -> int:
    try:
        provider = get_domain_provider()
    except DomainProviderNotAllowed as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    async with async_session_maker() as db:
        try:
            company, row, zone_created = await run(
                db, company_ref=args.company, subdomain=args.subdomain, provider=provider
            )
        except MailDomainError as exc:
            print(f"Refused: {exc}", file=sys.stderr)
            return 1
        except DomainSetupError as exc:
            # Every stage already done is committed, so a re-run resumes from here; but only a
            # busy or unreachable AWS passes on its own.
            if exc.retryable:
                print(f"Stopped: {exc} Run the command again to resume.", file=sys.stderr)
            else:
                print(
                    f"Stopped: {exc} AWS refused it, so running again fails the same way; "
                    "this needs a fix first.",
                    file=sys.stderr,
                )
            return 2
        for line in describe(company, row, zone_created=zone_created):
            print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set up a customer's mail subdomain (LP-1005).")
    parser.add_argument("company", help="the company's id, or its exact name")
    parser.add_argument("subdomain", help="e.g. mb-mail.abcmortgage.com")
    return asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
