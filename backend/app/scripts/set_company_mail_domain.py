"""Link a company to its mail domain (LP-991).

Usage::

    uv run python -m app.scripts.set_company_mail_domain <company id or exact name> <domain> [--inactive]

Creates or updates the company's `company_mail_domains` row and prints it. Refuses a domain another
company already has. While the row is active, every file of the company has the address
`lf-<display_id>@<domain>`; `--inactive` (or no row) means no address at all.

In staging this runs as a one-off ECS task; see `docs/tickets/LP-991.md` for the command.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker
from app.models.company import Company
from app.models.company_mail_domain import CompanyMailDomain, MailDomainStatus
from app.services.mail_domain import MailDomainError, set_company_mail_domain


async def find_company(db: AsyncSession, ref: str) -> Company:
    """The live company with this id, or with exactly this name. Refuses none or several."""
    try:
        company_id = UUID(ref)
    except ValueError:
        matches = (
            await db.scalars(
                select(Company).where(Company.name == ref, Company.deleted_at.is_(None))
            )
        ).all()
    else:
        matches = (
            await db.scalars(
                select(Company).where(Company.id == company_id, Company.deleted_at.is_(None))
            )
        ).all()
    if not matches:
        raise MailDomainError(f"No company with id or exact name {ref!r}.")
    if len(matches) > 1:
        raise MailDomainError(f"{len(matches)} companies are named {ref!r}; pass the id instead.")
    return matches[0]


async def run(
    db: AsyncSession, *, company_ref: str, domain: str, inactive: bool = False
) -> tuple[Company, CompanyMailDomain]:
    """Find the company and set its domain. Flushes; the caller commits."""
    company = await find_company(db, company_ref)
    status = MailDomainStatus.INACTIVE if inactive else MailDomainStatus.ACTIVE
    row = await set_company_mail_domain(db, company_id=company.id, domain=domain, status=status)
    return company, row


def describe(company: Company, row: CompanyMailDomain) -> str:
    return f"{company.name} ({company.id}): {row.domain} [{row.status.value}]"


async def _main(args: argparse.Namespace) -> int:
    async with async_session_maker() as db:
        try:
            company, row = await run(
                db, company_ref=args.company, domain=args.domain, inactive=args.inactive
            )
        except MailDomainError as exc:
            print(f"Refused: {exc}", file=sys.stderr)
            return 1
        line = describe(company, row)
        await db.commit()
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Link a company to its mail domain (LP-991).")
    parser.add_argument("company", help="the company's id, or its exact name")
    parser.add_argument("domain", help="e.g. mail.staging.mortgageboss.ai")
    parser.add_argument(
        "--inactive", action="store_true", help="store the domain but give files no address"
    )
    return asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
