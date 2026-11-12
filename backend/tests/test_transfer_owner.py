"""Tests for the transfer-owner script (LP-MB-Admin-01).

The owner moves only to another active admin of the same company, and every
move writes one `owner_transferred` audit row.
"""

from uuid import UUID

import pytest
from app.models import Company, CompanyAuditLog, User, UserRole
from app.scripts._provisioning import ProvisioningError
from app.scripts.transfer_owner import (
    TransferOwnerConfig,
    success_line,
    transfer_owner,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.user_factory import make_user


async def _company(db: AsyncSession, slug: str) -> Company:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    return company


async def _user(
    db: AsyncSession, company: Company, email: str, *roles: UserRole, is_active: bool = True
) -> User:
    user = make_user(
        company_id=company.id,
        email=email,
        hashed_password="x",  # pragma: allowlist secret
        first_name="T",
        last_name="U",
        is_active=is_active,
        roles=roles,
    )
    db.add(user)
    await db.flush()
    return user


async def _owned(db: AsyncSession) -> tuple[Company, User]:
    """A company whose first admin is its owner, as add_company leaves it."""
    company = await _company(db, "acme")
    owner = await _user(db, company, "owner@acme.com", UserRole.ADMIN)
    company.owner_user_id = owner.id
    await db.flush()
    return company, owner


async def _transfer(
    db: AsyncSession, email: str, *, slug: str = "acme", environment: str = "staging"
) -> tuple[Company, User]:
    return await transfer_owner(
        db,
        TransferOwnerConfig(company_slug=slug, email=email),
        environment=environment,
        allowed_environments="staging",
    )


async def _stored_owner(db: AsyncSession, company: Company) -> UUID | None:
    owner: UUID | None = await db.scalar(
        text("SELECT owner_user_id FROM companies WHERE id = :id"), {"id": company.id}
    )
    return owner


async def test_moves_the_owner_to_another_active_admin_and_logs_it(
    db_session: AsyncSession,
) -> None:
    company, old = await _owned(db_session)
    new = await _user(db_session, company, "second@acme.com", UserRole.PROCESSOR, UserRole.ADMIN)

    _, moved_to = await _transfer(db_session, "second@acme.com")

    assert moved_to.id == new.id
    assert await _stored_owner(db_session, company) == new.id
    entries = list(
        await db_session.scalars(
            select(CompanyAuditLog).where(CompanyAuditLog.company_id == company.id)
        )
    )
    assert len(entries) == 1
    entry = entries[0]
    assert (entry.action, entry.target_type, entry.target_id, entry.actor_user_id) == (
        "owner_transferred",
        "company",
        company.id,
        None,
    )
    assert entry.detail == {
        "changes": [{"field": "owner_user_id", "from": str(old.id), "to": str(new.id)}]
    }
    assert success_line(company, new) == "owner of acme is now second@acme.com"


async def test_sets_the_owner_of_a_company_the_migration_left_without_one(
    db_session: AsyncSession,
) -> None:
    company = await _company(db_session, "acme")
    admin = await _user(db_session, company, "admin@acme.com", UserRole.ADMIN)

    await _transfer(db_session, "ADMIN@acme.com")

    assert await _stored_owner(db_session, company) == admin.id


@pytest.mark.parametrize(
    ("setup", "match"),
    [
        ("processor", "not an admin"),
        ("loan_officer", "not an admin"),
        ("inactive_admin", "inactive or deleted"),
        ("other_company_admin", "belongs to another company"),
        ("current_owner", "already the owner"),
        ("nobody", "No user with email"),
    ],
)
async def test_refuses_anyone_but_another_active_admin_of_the_company(
    db_session: AsyncSession, setup: str, match: str
) -> None:
    company, owner = await _owned(db_session)
    email = "target@acme.com"
    if setup == "processor":
        await _user(db_session, company, email, UserRole.PROCESSOR)
    elif setup == "loan_officer":
        await _user(db_session, company, email, UserRole.LOAN_OFFICER)
    elif setup == "inactive_admin":
        await _user(db_session, company, email, UserRole.ADMIN, is_active=False)
    elif setup == "other_company_admin":
        other = await _company(db_session, "other")
        await _user(db_session, other, email, UserRole.ADMIN)
    elif setup == "current_owner":
        email = owner.email

    with pytest.raises(ProvisioningError, match=match):
        await _transfer(db_session, email)

    assert await _stored_owner(db_session, company) == owner.id
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM company_audit_log WHERE company_id = :id"),
            {"id": company.id},
        )
        == 0
    )


async def test_refuses_an_unknown_or_soft_deleted_company(db_session: AsyncSession) -> None:
    company, _ = await _owned(db_session)
    await _user(db_session, company, "second@acme.com", UserRole.ADMIN)

    with pytest.raises(ProvisioningError, match="No live company"):
        await _transfer(db_session, "second@acme.com", slug="acme-typo")

    company.deleted_at = company.created_at
    await db_session.flush()
    with pytest.raises(ProvisioningError, match="No live company"):
        await _transfer(db_session, "second@acme.com")


@pytest.mark.parametrize("environment", ["production", "development", ""])
async def test_refuses_outside_the_allowlist(db_session: AsyncSession, environment: str) -> None:
    company, owner = await _owned(db_session)
    await _user(db_session, company, "second@acme.com", UserRole.ADMIN)

    with pytest.raises(ProvisioningError):
        await _transfer(db_session, "second@acme.com", environment=environment)

    assert await _stored_owner(db_session, company) == owner.id


async def test_refuses_an_email_two_users_share_in_different_case(
    db_session: AsyncSession,
) -> None:
    """The unique index is case-sensitive, so `Bob@` and `bob@` can both exist; neither is chosen."""
    company, owner = await _owned(db_session)
    await _user(db_session, company, "Bob@acme.com", UserRole.ADMIN)
    await _user(db_session, company, "bob@acme.com", UserRole.ADMIN)

    with pytest.raises(ProvisioningError, match="2 users have the email"):
        await _transfer(db_session, "bob@acme.com")

    assert await _stored_owner(db_session, company) == owner.id
