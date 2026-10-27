"""LP-991 — `app.scripts.set_company_mail_domain`: create, update, refuse a taken domain."""

from __future__ import annotations

import pytest
from app.models.company_mail_domain import CompanyMailDomain, MailDomainStatus
from app.scripts.set_company_mail_domain import describe, run
from app.services.mail_domain import MailDomainError, active_mail_domain
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.models.conftest_helpers import make_company


async def test_creates_the_row_by_company_id(db_session: AsyncSession) -> None:
    company = await make_company(db_session, name="Create Co")

    found, row = await run(db_session, company_ref=str(company.id), domain="mail.create.test")

    assert found.id == company.id
    assert (row.domain, row.status) == ("mail.create.test", MailDomainStatus.ACTIVE)
    assert describe(found, row) == f"Create Co ({company.id}): mail.create.test [active]"


async def test_updates_the_row_by_exact_name(db_session: AsyncSession) -> None:
    company = await make_company(db_session, name="Update Co LP-991")
    _, first = await run(db_session, company_ref=str(company.id), domain="mail.update.test")

    _, second = await run(
        db_session, company_ref="Update Co LP-991", domain="mail2.update.test", inactive=True
    )

    assert second.id == first.id
    assert (second.domain, second.status) == ("mail2.update.test", MailDomainStatus.INACTIVE)
    assert await active_mail_domain(db_session, company.id) is None


async def test_refuses_a_domain_another_company_has(db_session: AsyncSession) -> None:
    owner = await make_company(db_session, name="Owner Co")
    other = await make_company(db_session, name="Other Co")
    await run(db_session, company_ref=str(owner.id), domain="mail.taken.test")

    with pytest.raises(MailDomainError, match="another company"):
        await run(db_session, company_ref=str(other.id), domain="MAIL.taken.test")
    assert await active_mail_domain(db_session, other.id) is None


async def test_refuses_an_unknown_company(db_session: AsyncSession) -> None:
    with pytest.raises(MailDomainError, match="No company"):
        await run(db_session, company_ref="No Such Company LP-991", domain="mail.none.test")


async def test_the_dev_seed_links_once_and_leaves_an_operators_change_alone(
    db_session: AsyncSession,
) -> None:
    """A re-run of the seed must not re-activate a domain set `--inactive`, or put back one that was
    changed, since the first run."""
    from app.scripts.seed_dev_data import _link_dev_mail_domain

    company = await make_company(db_session, name="Seed Co LP-991")
    assert await _link_dev_mail_domain(db_session, company=company) is True
    assert await active_mail_domain(db_session, company.id) == "mb-mail.localhost"

    await run(db_session, company_ref=str(company.id), domain="mail.seed.test", inactive=True)
    assert await _link_dev_mail_domain(db_session, company=company) is False

    row = await db_session.scalar(
        select(CompanyMailDomain).where(CompanyMailDomain.company_id == company.id)
    )
    assert row is not None
    assert (row.domain, row.status) == ("mail.seed.test", MailDomainStatus.INACTIVE)
