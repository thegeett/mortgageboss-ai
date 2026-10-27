"""LP-991 — a file's address is `lf-<display_id>@<company's active domain>`, or nothing."""

from __future__ import annotations

import pytest
from app.core.config import Settings, settings
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

# Every test here is about what the address is when addresses are shown at all; the two flag tests
# below turn it back off.
pytestmark = pytest.mark.usefixtures("file_addresses_on")


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


def test_file_addresses_are_off_by_default() -> None:
    """Nothing routes `lf-<display_id>@<domain>` until step 4, so a deployment that sets nothing
    shows no address."""
    assert Settings.model_fields["file_addresses_enabled"].default is False


async def test_with_file_addresses_off_an_active_domain_gives_no_address(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    company = await make_company(db_session)
    await set_company_mail_domain(db_session, company_id=company.id, domain="off.example.test")
    loan_file = await create_loan_file(db_session, company_id=company.id)
    # The control: the same file, linked and active, has an address while the setting is on.
    assert await file_address(db_session, loan_file) is not None

    monkeypatch.setattr(settings, "file_addresses_enabled", False)

    assert await active_mail_domain(db_session, company.id) == "off.example.test"
    assert await file_address(db_session, loan_file) is None


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


async def test_a_domain_taken_after_the_check_is_refused_and_the_session_survives(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The race: another write takes the domain between the ownership check and the insert. The
    unique constraint refuses it; the savepoint turns that into the same refusal and leaves the
    caller's transaction usable."""
    owner = await make_company(db_session)
    other = await make_company(db_session)
    await set_company_mail_domain(db_session, company_id=owner.id, domain="raced.example.test")

    real_scalar = db_session.scalar
    calls = 0

    async def check_misses_the_owner(*args: object, **kwargs: object) -> object:
        # The first query is the ownership check; answering "nobody" is what a check that ran
        # before the other write committed would have seen.
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return await real_scalar(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(db_session, "scalar", check_misses_the_owner)
    with pytest.raises(MailDomainError, match="could not be set"):
        await set_company_mail_domain(db_session, company_id=other.id, domain="raced.example.test")
    monkeypatch.undo()

    assert calls == 2
    # The session still works, and holds the owner's row and nothing for the other company.
    assert await active_mail_domain(db_session, owner.id) == "raced.example.test"
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
