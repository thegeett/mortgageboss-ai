"""Switch real email from the app on or off for a company (LP-997).

Usage::

    uv run python -m app.scripts.set_email_sending <company id or exact name> on|off

Run it once the company's mail domain is onboarded for sending (`set_company_mail_domain` first).
While it is off, which is the default, the screens offer copy / open in mail app / "Mark as sent";
once it is on they offer Send, and the API accepts it. Refuses a company with no active domain. A
domain in `problem` (LP-1006) can only be switched off, and it stays off when the domain recovers.

In staging this runs as a one-off ECS task, like `set_company_mail_domain` (`docs/tickets/LP-991.md`).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker
from app.models.company import Company
from app.models.company_mail_domain import CompanyMailDomain
from app.scripts.set_company_mail_domain import find_company
from app.services.mail_domain import MailDomainError, set_email_sending


async def run(
    db: AsyncSession, *, company_ref: str, enabled: bool
) -> tuple[Company, CompanyMailDomain]:
    """Find the company and set the flag. Flushes; the caller commits."""
    company = await find_company(db, company_ref)
    row = await set_email_sending(db, company_id=company.id, enabled=enabled)
    return company, row


def describe(company: Company, row: CompanyMailDomain) -> str:
    state = "on" if row.sending_enabled else "off"
    return f"{company.name} ({company.id}): {row.domain} — sending from the app {state}"


async def _main(args: argparse.Namespace) -> int:
    async with async_session_maker() as db:
        try:
            company, row = await run(db, company_ref=args.company, enabled=args.state == "on")
        except MailDomainError as exc:
            print(f"Refused: {exc}", file=sys.stderr)
            return 1
        line = describe(company, row)
        await db.commit()
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Switch real email from the app on or off for a company (LP-997)."
    )
    parser.add_argument("company", help="the company's id, or its exact name")
    parser.add_argument("state", choices=("on", "off"))
    return asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
