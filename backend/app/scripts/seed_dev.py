"""Minimal development seed script (LP-26).

Creates one company with an admin and a processor user, using real bcrypt
hashes so the seeded accounts work through the normal login flow. Idempotent:
safe to run repeatedly. DEV ONLY — the default passwords are for local
development.

Run: ``uv run python -m app.scripts.seed_dev``

NOTE: This is a minimal seed to unblock Epic 4 development/testing. The
comprehensive seed (multiple companies, lenders, sample loan files, etc.) is
LP-48. The full onboarding/invitation flow is documented in
``docs/onboarding-and-tenancy.md`` and built in later phases.

Default emails use the ``.com`` TLD rather than ``.test`` because the login
endpoint validates ``email`` as a Pydantic ``EmailStr``, which rejects reserved
special-use TLDs (``.test``/``.example``/...). Using a normal domain keeps the
seeded accounts usable through the real auth flow. No email is ever sent.
"""

import asyncio
import os
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker
from app.core.security import hash_password
from app.models.company import Company
from app.models.user import User, UserRole

# DEV-ONLY default credentials (override via env). Do NOT use in production.
# These are local-dev conveniences, not secrets.
ADMIN_EMAIL = os.getenv("SEED_ADMIN_EMAIL", "admin@demo.com")
ADMIN_PASSWORD = os.getenv("SEED_ADMIN_PASSWORD", "adminpass123")  # pragma: allowlist secret
PROCESSOR_EMAIL = os.getenv("SEED_PROCESSOR_EMAIL", "processor@demo.com")
PROCESSOR_PASSWORD = os.getenv(
    "SEED_PROCESSOR_PASSWORD", "processorpass123"
)  # pragma: allowlist secret
COMPANY_NAME = os.getenv("SEED_COMPANY_NAME", "Demo Mortgage Processing")
COMPANY_SLUG = os.getenv("SEED_COMPANY_SLUG", "demo")


async def _get_or_create_company(db: AsyncSession) -> tuple[Company, bool]:
    """Return the demo company, creating it if absent. Keyed on the unique slug."""
    existing = await db.scalar(select(Company).where(Company.slug == COMPANY_SLUG))
    if existing is not None:
        return existing, False
    company = Company(name=COMPANY_NAME, slug=COMPANY_SLUG, is_active=True)
    db.add(company)
    await db.flush()
    return company, True


async def _get_or_create_user(
    db: AsyncSession,
    *,
    company_id: UUID,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    role: UserRole,
) -> tuple[User, bool]:
    """Return the user with this (globally unique) email, creating it if absent.

    Existence is checked by email so a re-run never duplicates; the password is
    hashed with bcrypt so the seeded account works through the normal login flow.
    """
    existing = await db.scalar(select(User).where(User.email == email))
    if existing is not None:
        return existing, False
    user = User(
        company_id=company_id,
        email=email,
        hashed_password=hash_password(password),
        first_name=first_name,
        last_name=last_name,
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user, True


async def seed() -> None:
    """Seed the minimal dev dataset (idempotent) and print the credentials."""
    async with async_session_maker() as db:
        company, company_created = await _get_or_create_company(db)
        _admin, admin_created = await _get_or_create_user(
            db,
            company_id=company.id,
            email=ADMIN_EMAIL,
            password=ADMIN_PASSWORD,
            first_name="Demo",
            last_name="Admin",
            role=UserRole.ADMIN,
        )
        _processor, processor_created = await _get_or_create_user(
            db,
            company_id=company.id,
            email=PROCESSOR_EMAIL,
            password=PROCESSOR_PASSWORD,
            first_name="Demo",
            last_name="Processor",
            role=UserRole.PROCESSOR,
        )
        # Standalone script: commit our own transaction (services flush and let
        # the request handler commit; here there is no handler).
        await db.commit()

    def _status(created: bool) -> str:
        return "created" if created else "already existed"

    print("=== Dev seed complete ===")
    print(f"Company: {COMPANY_NAME} (slug: {COMPANY_SLUG}) [{_status(company_created)}]")
    print(f"Admin login:     {ADMIN_EMAIL} / {ADMIN_PASSWORD} [{_status(admin_created)}]")
    print(
        f"Processor login: {PROCESSOR_EMAIL} / {PROCESSOR_PASSWORD} [{_status(processor_created)}]"
    )
    print("(DEV ONLY — these default passwords are for local development.)")


if __name__ == "__main__":
    asyncio.run(seed())
