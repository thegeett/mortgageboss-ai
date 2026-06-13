"""Tests for the User model (LP-11).

Covers create/read, the User↔Company relationship in both directions, the
globally-unique email (even across companies), and the role enum round-trip.
Relationships are loaded eagerly with ``selectinload`` because lazy loading is
not available under async sessions.
"""

import pytest
from app.models import Company, User, UserRole
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def _make_company(db_session: AsyncSession, slug: str) -> Company:
    company = Company(name=slug.title(), slug=slug)
    db_session.add(company)
    await db_session.flush()
    return company


async def test_create_user_with_defaults(db_session: AsyncSession) -> None:
    """A user can be created under a company; defaults are applied."""
    company = await _make_company(db_session, "acme")
    user = User(
        company_id=company.id,
        email="processor@acme.test",
        hashed_password="not-a-real-hash",  # pragma: allowlist secret  (test fixture, not a secret)
        first_name="Pat",
        last_name="Processor",
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)

    assert user.id is not None
    assert user.company_id == company.id
    assert user.email == "processor@acme.test"
    assert user.first_name == "Pat"
    assert user.last_name == "Processor"
    assert user.full_name == "Pat Processor"
    # role defaults to PROCESSOR; is_active defaults to True.
    assert user.role is UserRole.PROCESSOR
    assert user.is_active is True
    assert user.deleted_at is None


async def test_user_company_relationship_loads(db_session: AsyncSession) -> None:
    """user.company loads the parent Company (eager-loaded for async)."""
    company = await _make_company(db_session, "beta-co")
    db_session.add(
        User(
            company_id=company.id,
            email="u@beta-co.test",
            hashed_password="h",
            first_name="B",
            last_name="C",
        )
    )
    await db_session.flush()

    stmt = select(User).where(User.email == "u@beta-co.test").options(selectinload(User.company))
    loaded = (await db_session.scalars(stmt)).one()
    assert loaded.company.id == company.id
    assert loaded.company.slug == "beta-co"


async def test_company_users_relationship_loads(db_session: AsyncSession) -> None:
    """company.users loads all of the company's users (eager-loaded for async)."""
    company = await _make_company(db_session, "gamma")
    db_session.add_all(
        [
            User(
                company_id=company.id,
                email="one@gamma.test",
                hashed_password="h",
                first_name="One",
                last_name="G",
            ),
            User(
                company_id=company.id,
                email="two@gamma.test",
                hashed_password="h",
                first_name="Two",
                last_name="G",
            ),
        ]
    )
    await db_session.flush()

    stmt = select(Company).where(Company.id == company.id).options(selectinload(Company.users))
    loaded = (await db_session.scalars(stmt)).one()
    assert {u.email for u in loaded.users} == {"one@gamma.test", "two@gamma.test"}


async def test_email_is_globally_unique_across_companies(db_session: AsyncSession) -> None:
    """Email is globally unique — the same email fails even in a *different*
    company (ADR-042)."""
    company_a = await _make_company(db_session, "company-a")
    company_b = await _make_company(db_session, "company-b")

    db_session.add(
        User(
            company_id=company_a.id,
            email="shared@example.test",
            hashed_password="h",
            first_name="A",
            last_name="A",
        )
    )
    await db_session.flush()

    # Same email under a *different* company must still violate the unique index.
    # Contain the expected failure in a SAVEPOINT so it doesn't poison the outer
    # (rolled-back) test transaction.
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                User(
                    company_id=company_b.id,
                    email="shared@example.test",
                    hashed_password="h",
                    first_name="B",
                    last_name="B",
                )
            )
            await db_session.flush()


async def test_role_enum_roundtrips(db_session: AsyncSession) -> None:
    """The role enum round-trips and is stored as its string value."""
    company = await _make_company(db_session, "delta")
    user = User(
        company_id=company.id,
        email="admin@delta.test",
        hashed_password="h",
        first_name="Ada",
        last_name="Admin",
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)

    assert user.role is UserRole.ADMIN

    # native_enum=False persists the value (not the member name).
    raw = await db_session.scalar(text("SELECT role FROM users WHERE id = :id"), {"id": user.id})
    assert raw == "admin"
