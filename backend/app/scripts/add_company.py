"""Create a NEW company and its first admin in a deployed environment.

The third provisioning door. :mod:`app.scripts.bootstrap_admin` makes the first
company and refuses once any user exists; :mod:`app.scripts.add_user` adds users
to a company that already exists and refuses to create one. Neither can onboard a
second tenant, and this is the deliberate act that does.

Usage (as a one-off ECS task; see ``./scripts/deploy <env> add-company``)::

    uv run python -m app.scripts.add_company

Environment variables, ALL REQUIRED, no defaults:

    ADD_COMPANY_NAME
    ADD_COMPANY_SLUG                 lowercase letters, digits, single hyphens
    ADD_COMPANY_ADMIN_EMAIL
    ADD_COMPANY_ADMIN_PASSWORD_HASH  a bcrypt hash -- NEVER a password
    ADD_COMPANY_ADMIN_FIRST_NAME
    ADD_COMPANY_ADMIN_LAST_NAME

    ADD_COMPANY_ALLOWED_ENVIRONMENTS comma-separated, defaults to "staging"

**The company and its admin are made together, in one transaction.** A company
with no user is a tenant nobody can log in to, and add-user would then be the
only way to finish it -- a second step that, if forgotten, leaves a stray row.

**A second tenant is the thing add_user refuses to make by accident**, so this
script refuses the ways a deliberate one can still be a mistake: a slug any
company already has (soft-deleted included -- the unique index covers them, and
reusing a decommissioned tenant's slug is how its old links would resolve to the
new one), a name a live company already has under another slug, and an admin
email any user already has.

Prints one line and no secret.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from dataclasses import dataclass

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_maker
from app.models.company import Company
from app.models.types import SHORT_STRING
from app.models.user import User, UserRole
from app.scripts._provisioning import (
    ProvisioningError,
    assert_email_unused,
    assert_environment_allowed,
    normalize_email,
    require_env,
    validate_bcrypt_hash,
)

logger = structlog.get_logger(__name__)

ALLOWLIST_VAR = "ADD_COMPANY_ALLOWED_ENVIRONMENTS"
DEFAULT_ALLOWED_ENVIRONMENTS = "staging"

# Lowercase alphanumeric runs joined by single hyphens: `vemamortgage`,
# `acme-mortgage`. Not normalized for the operator -- `Vema Mortgage` typed at
# the slug prompt is a refusal, not a silent `vema-mortgage`, because the slug is
# permanent and the operator should see the one they are getting.
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass(frozen=True)
class AddCompanyConfig:
    """Everything the tool needs. Built once, validated before use."""

    company_name: str
    company_slug: str
    admin_email: str
    admin_password_hash: str
    admin_first_name: str
    admin_last_name: str


def validate_slug(value: str) -> str:
    """Return ``value`` if it is a well-formed company slug, or raise."""
    if len(value) > SHORT_STRING:
        raise ProvisioningError(
            f"ADD_COMPANY_SLUG is {len(value)} characters; the limit is {SHORT_STRING}."
        )
    if not SLUG_PATTERN.fullmatch(value):
        raise ProvisioningError(
            f"ADD_COMPANY_SLUG {value!r} is not a valid slug: use lowercase letters, "
            f"digits and single hyphens, e.g. 'acme-mortgage'."
        )
    return value


def config_from_env() -> AddCompanyConfig:
    """Read and validate every input. Raises :class:`ProvisioningError`."""
    return AddCompanyConfig(
        company_name=require_env("ADD_COMPANY_NAME"),
        company_slug=validate_slug(require_env("ADD_COMPANY_SLUG")),
        admin_email=normalize_email(
            require_env("ADD_COMPANY_ADMIN_EMAIL"), var_name="ADD_COMPANY_ADMIN_EMAIL"
        ),
        admin_password_hash=validate_bcrypt_hash(
            require_env("ADD_COMPANY_ADMIN_PASSWORD_HASH"),
            var_name="ADD_COMPANY_ADMIN_PASSWORD_HASH",
        ),
        admin_first_name=require_env("ADD_COMPANY_ADMIN_FIRST_NAME"),
        admin_last_name=require_env("ADD_COMPANY_ADMIN_LAST_NAME"),
    )


async def add_company(
    db: AsyncSession,
    config: AddCompanyConfig,
    *,
    environment: str,
    allowed_environments: str,
) -> tuple[Company, User]:
    """Create the company and its admin, or refuse.

    Every guard runs before the first write, and lives here rather than in
    :func:`main`, so no caller can reach the writes without passing them.

    Raises:
        ProvisioningError: the environment is not allowlisted, the hash, email or
            slug is malformed, the slug is taken by any company, the name is taken
            by a live company, or the email is taken.
    """
    assert_environment_allowed(
        current=environment,
        allowed_raw=allowed_environments,
        allowlist_var=ALLOWLIST_VAR,
    )
    # Re-validated deliberately: config_from_env is not the only way to build an
    # AddCompanyConfig, and this is the last point before a write.
    validate_bcrypt_hash(config.admin_password_hash, var_name="ADD_COMPANY_ADMIN_PASSWORD_HASH")
    email = normalize_email(config.admin_email, var_name="ADD_COMPANY_ADMIN_EMAIL")
    slug = validate_slug(config.company_slug)
    name = config.company_name.strip()
    if not name:
        raise ProvisioningError("ADD_COMPANY_NAME is required and was not set.")

    # ANY company, soft-deleted included. The unique index on `companies.slug`
    # covers every row, so skipping deleted ones would only swap this refusal for
    # an IntegrityError.
    taken = await db.scalar(select(Company).where(Company.slug == slug))
    if taken is not None:
        state = "a soft-deleted" if taken.deleted_at is not None else "an existing"
        raise ProvisioningError(
            f"The slug {slug!r} belongs to {state} company. Slugs are never reused. "
            f"To add a user to an existing company, use the add-user stage. Nothing was "
            f"changed."
        )

    # LIVE companies only, ignoring case and surrounding space. The same tenant
    # created twice under two slugs is the duplicate add_user's refusal exists to
    # prevent; re-onboarding a decommissioned one under its old name is not.
    twin = await db.scalar(
        select(Company).where(
            func.lower(func.trim(Company.name)) == name.lower(),
            Company.deleted_at.is_(None),
        )
    )
    if twin is not None:
        raise ProvisioningError(
            f"A live company named {name!r} already exists with slug {twin.slug!r}. "
            f"Refusing to create a second tenant with the same name. Nothing was changed."
        )

    await assert_email_unused(db, email)

    company = Company(name=name, slug=slug, is_active=True)
    db.add(company)
    await db.flush()

    user = User(
        company_id=company.id,
        email=email,
        hashed_password=config.admin_password_hash,
        first_name=config.admin_first_name,
        last_name=config.admin_last_name,
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    return company, user


def _allowed_environments() -> str:
    return os.environ.get(ALLOWLIST_VAR, DEFAULT_ALLOWED_ENVIRONMENTS)


def success_line(company: Company, user: User) -> str:
    """The single line this script prints on success.

    Its own function so a test can assert what it does and does not contain:
    these logs live in CloudWatch for 30 days.
    """
    return f"created company {company.slug}, admin {user.email}"


async def _run() -> None:
    config = config_from_env()
    async with async_session_maker() as db:
        company, user = await add_company(
            db,
            config,
            environment=settings.environment,
            allowed_environments=_allowed_environments(),
        )
        # A standalone script owns its transaction: nothing else will commit.
        await db.commit()
        line = success_line(company, user)
    print(line)


def main() -> None:
    """Entry point. Turns a refusal into a clear message and a non-zero exit."""
    try:
        asyncio.run(_run())
    except ProvisioningError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
