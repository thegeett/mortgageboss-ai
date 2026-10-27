"""LP-991 — a file's address is `lf-<display_id>@<company's active domain>`, or nothing."""

from __future__ import annotations

import pytest
from app.models.company_mail_domain import MailDomainStatus
from app.services.loan_files import create_loan_file
from app.services.mail_domain import (
    MailDomainError,
    active_mail_domain,
    file_address,
    normalise_domain,
    set_company_mail_domain,
)
from sqlalchemy.ext.asyncio import AsyncSession
from tests.models.conftest_helpers import make_company


async def test_an_active_domain_gives_the_lowercase_display_id_address(
    db_session: AsyncSession,
) -> None:
    company = await make_company(db_session)
    await set_company_mail_domain(db_session, company_id=company.id, domain="Mail.Example.TEST")
    loan_file = await create_loan_file(db_session, company_id=company.id)

    address = await file_address(db_session, loan_file)

    assert loan_file.display_id.startswith("LF-")
    assert address == f"{loan_file.display_id.lower()}@mail.example.test"
    # One `lf-`, not two: `display_id` already carries the prefix.
    assert address is not None and address.startswith("lf-") and not address.startswith("lf-lf-")
    assert address == address.lower()


async def test_no_row_means_no_address(db_session: AsyncSession) -> None:
    company = await make_company(db_session)
    loan_file = await create_loan_file(db_session, company_id=company.id)

    assert await active_mail_domain(db_session, company.id) is None
    assert await file_address(db_session, loan_file) is None


async def test_an_inactive_domain_means_no_address(db_session: AsyncSession) -> None:
    company = await make_company(db_session)
    await set_company_mail_domain(
        db_session,
        company_id=company.id,
        domain="inactive.example.test",
        status=MailDomainStatus.INACTIVE,
    )
    loan_file = await create_loan_file(db_session, company_id=company.id)

    assert await file_address(db_session, loan_file) is None


async def test_another_companys_domain_is_not_mine(db_session: AsyncSession) -> None:
    """The lookup is by company: a linked company does not give an unlinked one an address."""
    mine = await make_company(db_session)
    theirs = await make_company(db_session)
    await set_company_mail_domain(db_session, company_id=theirs.id, domain="theirs.example.test")
    loan_file = await create_loan_file(db_session, company_id=mine.id)

    assert await file_address(db_session, loan_file) is None


async def test_setting_again_updates_the_one_row(db_session: AsyncSession) -> None:
    company = await make_company(db_session)
    first = await set_company_mail_domain(
        db_session, company_id=company.id, domain="one.example.test"
    )
    second = await set_company_mail_domain(
        db_session,
        company_id=company.id,
        domain="two.example.test",
        status=MailDomainStatus.INACTIVE,
    )

    assert second.id == first.id
    assert (second.domain, second.status) == ("two.example.test", MailDomainStatus.INACTIVE)


async def test_a_domain_another_company_has_is_refused(db_session: AsyncSession) -> None:
    owner = await make_company(db_session)
    other = await make_company(db_session)
    await set_company_mail_domain(db_session, company_id=owner.id, domain="taken.example.test")

    with pytest.raises(MailDomainError, match="another company"):
        await set_company_mail_domain(db_session, company_id=other.id, domain="@TAKEN.example.test")
    assert await active_mail_domain(db_session, other.id) is None


@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        ("mail.staging.mortgageboss.ai", "mail.staging.mortgageboss.ai"),
        ("  MB-Mail.Example.COM ", "mb-mail.example.com"),
        ("@mb-mail.localhost", "mb-mail.localhost"),
        (".mb-mail.localhost.", "mb-mail.localhost"),
    ],
)
def test_the_domain_is_stored_lowercase_without_a_leading_at_or_dot(raw: str, stored: str) -> None:
    assert normalise_domain(raw) == stored


@pytest.mark.parametrize(
    "raw",
    ["", "localhost", "a..b", "-bad.example", "has space.example", "x@y.example", "é.example"],
)
def test_what_is_not_a_domain_is_refused(raw: str) -> None:
    with pytest.raises(MailDomainError):
        normalise_domain(raw)
