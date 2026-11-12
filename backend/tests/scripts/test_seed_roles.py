"""The seed scripts give an EXISTING user the roles a fresh seed would (LP-MB-Admin-01).

A dev database seeded before roles became a set holds only the backfilled role; a re-run without
`--reset` must top it up, or the "admin who is also a processor" later tickets rely on never exists.
"""

from typing import Any
from uuid import uuid4

import pytest
from app.models import Company, UserRole
from app.scripts import seed_dev, seed_dev_data
from sqlalchemy.ext.asyncio import AsyncSession
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
