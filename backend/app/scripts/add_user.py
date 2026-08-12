"""Add a user to an EXISTING company in a deployed environment.

The ongoing counterpart to :mod:`app.scripts.bootstrap_admin`, which refuses to
run once any user exists. This one is for a populated database, so it drops that
guard and keeps every other one.

Usage (as a one-off ECS task; see ``./scripts/deploy <env> add-user``)::

    uv run python -m app.scripts.add_user

Environment variables, ALL REQUIRED, no defaults:

    ADD_USER_EMAIL
    ADD_USER_PASSWORD_HASH      a bcrypt hash -- NEVER a password
    ADD_USER_FIRST_NAME
    ADD_USER_LAST_NAME
    ADD_USER_ROLE               ADMIN | PROCESSOR, explicit -- there is no default
    ADD_USER_COMPANY_SLUG       must already exist

    ADD_USER_ALLOWED_ENVIRONMENTS   comma-separated, defaults to "staging"

⚠️ **A HASH, not a password** -- same reasoning as the bootstrap script: the
value travels through ``run-task --overrides`` and lands in CloudTrail.

⚠️ **The company must already exist.** A typo'd slug silently creating a second
company is the failure this refuses to allow. It matters more than it looks:
``authenticate_user`` does not check ``company.is_active``, so a user attached to
a stray company would log in perfectly well and see an empty, wrong tenant.

⚠️ **Email is GLOBALLY unique**, not unique per company, so a collision with a
user in a different company is possible. That is reported as a refusal rather
than left to surface as an IntegrityError traceback.

Prints one line and no secret.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_maker
from app.models.company import Company
from app.models.user import User, UserRole
from app.scripts._provisioning import (
    ProvisioningError,
    assert_environment_allowed,
    require_env,
    validate_bcrypt_hash,
)

logger = structlog.get_logger(__name__)

ALLOWLIST_VAR = "ADD_USER_ALLOWED_ENVIRONMENTS"
DEFAULT_ALLOWED_ENVIRONMENTS = "staging"


@dataclass(frozen=True)
class AddUserConfig:
    """Everything the tool needs. Built once, validated before use."""

    email: str
    password_hash: str
    first_name: str
    last_name: str
    role: UserRole
    company_slug: str


def parse_role(raw: str) -> UserRole:
    """Parse the role, accepting either case. No default: it must be explicit.

    Defaulting would mean a typo silently producing the *less* privileged role
    (confusing) or the *more* privileged one (dangerous). Both are worse than a
    refusal.
    """
    try:
        return UserRole(raw.strip().lower())
    except ValueError as exc:
        valid = ", ".join(sorted(r.value.upper() for r in UserRole))
        raise ProvisioningError(
            f"ADD_USER_ROLE must be one of: {valid}. Got {raw.strip()!r}."
        ) from exc


def config_from_env() -> AddUserConfig:
    """Read and validate every input. Raises :class:`ProvisioningError`."""
    return AddUserConfig(
        email=require_env("ADD_USER_EMAIL"),
        password_hash=validate_bcrypt_hash(
            require_env("ADD_USER_PASSWORD_HASH"), var_name="ADD_USER_PASSWORD_HASH"
        ),
        first_name=require_env("ADD_USER_FIRST_NAME"),
        last_name=require_env("ADD_USER_LAST_NAME"),
        role=parse_role(require_env("ADD_USER_ROLE")),
        company_slug=require_env("ADD_USER_COMPANY_SLUG"),
    )


async def add_user(
    db: AsyncSession,
    config: AddUserConfig,
    *,
    environment: str,
    allowed_environments: str,
) -> User:
    """Create the user, or refuse.

    Every guard lives here rather than in :func:`main`, so no caller can reach
    the write without passing them.

    Raises:
        ProvisioningError: the environment is not allowlisted, the hash is
            malformed, the company slug is unknown, or the email is taken.
    """
    assert_environment_allowed(
        current=environment,
        allowed_raw=allowed_environments,
        allowlist_var=ALLOWLIST_VAR,
    )
    validate_bcrypt_hash(config.password_hash, var_name="ADD_USER_PASSWORD_HASH")

    company = await db.scalar(select(Company).where(Company.slug == config.company_slug))
    if company is None:
        raise ProvisioningError(
            f"No company with slug {config.company_slug!r}. Refusing to create one: a "
            f"typo'd slug that silently made a second company would produce a user who "
            f"logs in successfully into the wrong, empty tenant."
        )

    existing = await db.scalar(select(User).where(User.email == config.email))
    if existing is not None:
        raise ProvisioningError(
            f"A user with email {config.email} already exists. Email is globally "
            f"unique across all companies, not per company, so this collides even if "
            f"the existing user belongs to a different one. Nothing was changed."
        )

    user = User(
        company_id=company.id,
        email=config.email,
        hashed_password=config.password_hash,
        first_name=config.first_name,
        last_name=config.last_name,
        role=config.role,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    return user


def _allowed_environments() -> str:
    return os.environ.get(ALLOWLIST_VAR, DEFAULT_ALLOWED_ENVIRONMENTS)


def success_line(user: User, company_slug: str) -> str:
    """The single line this script prints on success.

    Its own function so a test can assert what it does and does not contain:
    these logs live in CloudWatch for 30 days.
    """
    return f"created user {user.email} as {user.role.value} in {company_slug}"


async def _run() -> None:
    config = config_from_env()
    async with async_session_maker() as db:
        user = await add_user(
            db,
            config,
            environment=settings.environment,
            allowed_environments=_allowed_environments(),
        )
        await db.commit()
        line = success_line(user, config.company_slug)
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
