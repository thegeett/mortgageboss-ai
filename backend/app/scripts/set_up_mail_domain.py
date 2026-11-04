"""Set up a customer's mail subdomain, in stages, during their onboarding call (LP-1005).

Usage::

    uv run python -m app.scripts.set_up_mail_domain <company id or exact name> <subdomain>
        [--replace] [--custom-subdomain]

Each run moves the domain on as far as it can (`services/mail_domain.advance_mail_domain`) and says
where it is and what comes next:

1. pending_ns: our Route 53 zone exists. Prints the NS record the customer adds at their DNS provider.
2. verifying: the NS record is live; the SES identity and every record are written. AWS verifies.
3. active: AWS has verified the domain. Files get `lf-…@<subdomain>` and sending is switched on.

Safe to run again at any point; nothing is created twice. The hourly check (LP-1006) runs the same
step on its own, so nobody has to wait by the keyboard while DNS spreads.

Refuses a subdomain of mortgageboss.ai (ours, managed by Terraform), a subdomain another company
has, and a company that already has a different domain.

- `--replace` corrects a mistyped domain while it is still at pending_ns. Past that, changing a
  domain is manual for now. The old zone stays in AWS (the app has no delete permission); the command
  prints its id.
- A new subdomain must start with `mb-mail.`, because the record we print moves the name's whole DNS
  to us: on a customer's root domain that takes down their website and email. `--custom-subdomain`
  allows a prefix the customer chose. There is no list of public suffixes, so with that flag a person
  still has to read the name.

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
    replace_pending_domain,
    set_company_mail_domain,
)

#: Our own domain. Its subdomains are Terraform's (LP-1004 denies the app any change to them).
OUR_DOMAIN = "mortgageboss.ai"
#: The default prefix (`loan-email.md` §3: "Default `mb-mail`, customer can change"; "Root domain
#: never used").
DEFAULT_PREFIX = "mb-mail."
#: Zone, then verifying, then active.
MAX_STEPS = 3


def _refuse_a_root_domain(cleaned: str, *, custom_subdomain: bool) -> None:
    if len(cleaned.split(".")) < 3 or not (custom_subdomain or cleaned.startswith(DEFAULT_PREFIX)):
        raise MailDomainError(
            f"{cleaned} doesn't look like a subdomain for us: it must start with {DEFAULT_PREFIX} and "
            "a customer's root domain is never used. For another subdomain the customer chose, pass "
            "--custom-subdomain."
        )


async def prepare(
    db: AsyncSession,
    *,
    company_ref: str,
    subdomain: str,
    replace: bool = False,
    custom_subdomain: bool = False,
) -> tuple[Company, CompanyMailDomain, tuple[str, str | None] | None]:
    """Find the company and its row for `subdomain`, creating it (pending_ns) if it has none, or
    replacing a pending domain when asked. Returns the old domain and zone if it replaced one.
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
    if row is not None and row.domain == cleaned:
        return company, row, None
    if row is not None and row.status is not MailDomainStatus.PENDING_NS:
        raise MailDomainError(
            f"{company.name} already has the domain {row.domain} ({row.status.value}); changing a "
            "domain past pending_ns is manual for now."
        )
    if row is not None and not replace:
        raise MailDomainError(
            f"{company.name} already has the domain {row.domain}, still waiting for its NS record. "
            "To correct it, run this again with --replace."
        )
    _refuse_a_root_domain(cleaned, custom_subdomain=custom_subdomain)
    replaced = None
    if row is not None:
        replaced = (row.domain, row.zone_id)
        await replace_pending_domain(db, row=row, domain=cleaned)
    else:
        # Refuses a subdomain another company has.
        row = await set_company_mail_domain(
            db, company_id=company.id, domain=cleaned, status=MailDomainStatus.PENDING_NS
        )
        await db.flush()
    return company, row, replaced


async def run(
    db: AsyncSession,
    *,
    company_ref: str,
    subdomain: str,
    provider: DomainProvider,
    replace: bool = False,
    custom_subdomain: bool = False,
) -> tuple[Company, CompanyMailDomain, bool, tuple[str, str | None] | None]:
    """Prepare, then advance until nothing changes (at most `MAX_STEPS`). Returns whether this run
    created the zone, and the domain and zone it replaced, if any."""
    company, row, replaced = await prepare(
        db,
        company_ref=company_ref,
        subdomain=subdomain,
        replace=replace,
        custom_subdomain=custom_subdomain,
    )
    zone_created = False
    for _ in range(MAX_STEPS):
        before = (row.status, row.zone_id)
        await advance_mail_domain(db, row, provider)
        if before[1] is None and row.zone_id is not None:
            zone_created = True
        if (row.status, row.zone_id) == before:
            break
    return company, row, zone_created, replaced


def describe(
    company: Company,
    row: CompanyMailDomain,
    *,
    zone_created: bool,
    replaced: tuple[str, str | None] | None = None,
) -> list[str]:
    lines = [f"{company.name} ({company.id}): {row.domain} [{row.status.value}]"]
    if replaced is not None:
        old_domain, old_zone = replaced
        lines.append(f"Replaced {old_domain}; nothing uses it now.")
        if old_zone is not None:
            lines.append(
                f"Delete by hand in AWS: Route 53 zone {old_zone}, and the SES identity "
                f"{old_domain} if there is one."
            )
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
            company, row, zone_created, replaced = await run(
                db,
                company_ref=args.company,
                subdomain=args.subdomain,
                provider=provider,
                replace=args.replace,
                custom_subdomain=args.custom_subdomain,
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
        for line in describe(company, row, zone_created=zone_created, replaced=replaced):
            print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set up a customer's mail subdomain (LP-1005).")
    parser.add_argument("company", help="the company's id, or its exact name")
    parser.add_argument("subdomain", help="e.g. mb-mail.abcmortgage.com")
    parser.add_argument(
        "--replace", action="store_true", help="correct a domain still at pending_ns"
    )
    parser.add_argument(
        "--custom-subdomain",
        action="store_true",
        help="allow a subdomain that doesn't start with mb-mail.",
    )
    return asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
