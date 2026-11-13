"""The seed scripts give an EXISTING user the roles a fresh seed would (LP-MB-Admin-01).

A dev database seeded before roles became a set holds only the backfilled role; a re-run without
`--reset` must top it up, or the "admin who is also a processor" later tickets rely on never exists.
"""

from typing import Any
from uuid import uuid4

import pytest
from app.core.file_scope import FileScope
from app.models import Company, LoanFile, User, UserRole
from app.models.helpers import scope_files
from app.scripts import seed_dev, seed_dev_data
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from tests.user_factory import make_user


@pytest.mark.parametrize("module", [seed_dev, seed_dev_data])
async def test_a_rerun_adds_missing_roles_to_an_existing_user(
    db_session: AsyncSession, module: Any
) -> None:
    company = Company(name="Demo", slug=f"demo-{uuid4().hex[:8]}")
    db_session.add(company)
    await db_session.flush()
    email = f"admin-{uuid4().hex[:8]}@demo.com"
    db_session.add(
        make_user(
            company_id=company.id,
            email=email,
            hashed_password="x",  # pragma: allowlist secret
            first_name="Demo",
            last_name="Admin",
            roles=[UserRole.ADMIN],
        )
    )
    await db_session.flush()
    extra = {"password": "x"} if module is seed_dev else {}  # pragma: allowlist secret

    user, created = await module._get_or_create_user(
        db_session,
        company_id=company.id,
        email=email,
        first_name="Demo",
        last_name="Admin",
        roles=[UserRole.ADMIN, UserRole.PROCESSOR],
        **extra,
    )

    assert created is False
    assert user.role_set == {UserRole.ADMIN, UserRole.PROCESSOR}
    db_session.expunge_all()
    again, _ = await module._get_or_create_user(
        db_session,
        company_id=company.id,
        email=email,
        first_name="Demo",
        last_name="Admin",
        roles=[UserRole.ADMIN, UserRole.PROCESSOR],
        **extra,
    )
    # Stored, and a second re-run adds nothing (the unique index would refuse a duplicate).
    assert again.role_set == {UserRole.ADMIN, UserRole.PROCESSOR}
    assert len(again.roles) == 2


async def test_the_restricted_demo_company_shows_each_login_what_its_docstring_says(
    db_session: AsyncSession,
) -> None:
    """LP-MB-Admin-06 — the seed's Harbor logins see the files `seed_dev_data`'s docstring lists."""
    assert await seed_dev_data._seed_restricted_company(db_session) is True
    assert await seed_dev_data._seed_restricted_company(db_session) is False  # idempotent
    db_session.expunge_all()
    users = {
        user.email: user
        for user in await db_session.scalars(
            select(User)
            .join(Company, User.company_id == Company.id)
            .where(Company.slug == seed_dev_data._RESTRICTED_SLUG)
            .options(selectinload(User.company))
        )
    }

    async def visible(email: str) -> int:
        scope = FileScope.for_user(users[email])
        return int(
            await db_session.scalar(
                select(func.count()).select_from(scope_files(select(LoanFile.id), scope).subquery())
            )
            or 0
        )

    assert await visible(seed_dev_data._RESTRICTED_ADMIN_EMAIL) == 2
    assert await visible(seed_dev_data._RESTRICTED_LO_1_EMAIL) == 1
    assert await visible(seed_dev_data._RESTRICTED_LO_2_EMAIL) == 1
    assert await visible(seed_dev_data._RESTRICTED_PROCESSOR_EMAIL) == 1
    assert await visible(seed_dev_data._RESTRICTED_SEES_ALL_EMAIL) == 2
