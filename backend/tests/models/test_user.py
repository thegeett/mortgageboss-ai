"""Tests for the User model (LP-11).

Covers create/read, the User↔Company relationship in both directions, the
globally-unique email (even across companies), and the role set (LP-MB-Admin-01).
Relationships are loaded eagerly with ``selectinload`` because lazy loading is
not available under async sessions.
"""

import pytest
from app.models import Company, User, UserRole
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from tests.user_factory import make_user


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
    # No role is implied (the set is what was granted) and LP-12's column is no longer written.
    assert user.role_set == frozenset()
    assert user.role is None
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


async def test_roles_roundtrip_as_a_set(db_session: AsyncSession) -> None:
    """A user holds several roles, one `user_roles` row each, stored as the enum's value."""
    company = await _make_company(db_session, "delta")
    user = make_user(
        company_id=company.id,
        email="admin@delta.test",
        hashed_password="h",
        first_name="Ada",
        last_name="Admin",
        roles=[UserRole.ADMIN, UserRole.PROCESSOR],
    )
    db_session.add(user)
    await db_session.flush()
    db_session.expunge(user)

    loaded = (await db_session.scalars(select(User).where(User.id == user.id))).one()
    assert loaded is not user
    # Loaded with the user (`lazy="selectin"`): reading it here would raise if it were lazy.
    assert loaded.role_set == {UserRole.ADMIN, UserRole.PROCESSOR}

    # native_enum=False persists the value (not the member name).
    raw = await db_session.scalars(
        text("SELECT role FROM user_roles WHERE user_id = :id ORDER BY role"), {"id": user.id}
    )
    assert list(raw) == ["admin", "processor"]


async def test_the_same_role_twice_is_refused(db_session: AsyncSession) -> None:
    company = await _make_company(db_session, "epsilon")
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                make_user(
                    company_id=company.id,
                    email="twice@epsilon.test",
                    hashed_password="h",
                    first_name="T",
                    last_name="W",
                    roles=[UserRole.ADMIN, UserRole.ADMIN],
                )
            )
            await db_session.flush()
