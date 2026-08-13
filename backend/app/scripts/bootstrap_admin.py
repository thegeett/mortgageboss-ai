"""Create the FIRST company and admin user in a deployed environment.

There is no registration route in this application — no signup endpoint, no
users router, no password-reset flow. The first account has to be made by a
deliberate act, and this is it.

Usage (as a one-off ECS task; see ``./scripts/deploy <env> bootstrap-admin``)::

    uv run python -m app.scripts.bootstrap_admin

Environment variables, ALL REQUIRED, no defaults:

    BOOTSTRAP_ADMIN_EMAIL
    BOOTSTRAP_ADMIN_PASSWORD_HASH   a bcrypt hash -- NEVER a password
    BOOTSTRAP_ADMIN_FIRST_NAME
    BOOTSTRAP_ADMIN_LAST_NAME
    BOOTSTRAP_COMPANY_NAME
    BOOTSTRAP_COMPANY_SLUG

    BOOTSTRAP_ALLOWED_ENVIRONMENTS  comma-separated, defaults to "staging"

⚠️ **A HASH, not a password.** The value reaches the task through
``run-task --overrides``, which is visible in ``describe-tasks`` for about an
hour and recorded in the CloudTrail ``RunTask`` event. Hash locally with
``scripts/hash-password``; the plaintext never leaves your machine.

⚠️ **This tool refuses to run against a populated database.** It is a bootstrap,
not a user-creation tool. To add users to an environment that already has some,
use :mod:`app.scripts.add_user`.

Prints one line and no secret: the company slug and the email. The hash is never
printed, logged, or included in an error message -- CloudWatch retains these
logs for 30 days.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_maker
from app.models.company import Company
from app.models.user import User, UserRole
from app.scripts._provisioning import (
    ProvisioningError,
    assert_environment_allowed,
    normalize_email,
    require_env,
    validate_bcrypt_hash,
)

logger = structlog.get_logger(__name__)

ALLOWLIST_VAR = "BOOTSTRAP_ALLOWED_ENVIRONMENTS"
DEFAULT_ALLOWED_ENVIRONMENTS = "staging"


@dataclass(frozen=True)
class BootstrapConfig:
    """Everything the bootstrap needs. Built once, validated before use."""

    admin_email: str
    admin_password_hash: str
    admin_first_name: str
    admin_last_name: str
    company_name: str
    company_slug: str


def config_from_env() -> BootstrapConfig:
    """Read and validate every input. Raises :class:`ProvisioningError`.

    The hash is validated HERE, before the database is opened, so a malformed
    value costs nothing and leaves nothing behind. The email is normalized for
    the same reason and one more: it must come out in the form the login
    endpoint will search for. See :func:`normalize_email`.
    """
    return BootstrapConfig(
        admin_email=normalize_email(
            require_env("BOOTSTRAP_ADMIN_EMAIL"), var_name="BOOTSTRAP_ADMIN_EMAIL"
        ),
        admin_password_hash=validate_bcrypt_hash(
            require_env("BOOTSTRAP_ADMIN_PASSWORD_HASH"),
            var_name="BOOTSTRAP_ADMIN_PASSWORD_HASH",
        ),
        admin_first_name=require_env("BOOTSTRAP_ADMIN_FIRST_NAME"),
        admin_last_name=require_env("BOOTSTRAP_ADMIN_LAST_NAME"),
        company_name=require_env("BOOTSTRAP_COMPANY_NAME"),
        company_slug=require_env("BOOTSTRAP_COMPANY_SLUG"),
    )


async def bootstrap(
    db: AsyncSession,
    config: BootstrapConfig,
    *,
    environment: str,
    allowed_environments: str,
) -> tuple[Company, User]:
    """Create the one company and the one admin, or refuse.

    Both guards live here rather than in :func:`main` so that no caller -- test,
    future script, or REPL -- can reach the writes without passing them.

    Raises:
        ProvisioningError: the environment is not allowlisted, the hash is
            malformed, or the database already contains a user.
    """
    assert_environment_allowed(
        current=environment,
        allowed_raw=allowed_environments,
        allowlist_var=ALLOWLIST_VAR,
    )

    # Re-validated deliberately: config_from_env is not the only way to build a
    # BootstrapConfig, and this is the last point before a write.
    validate_bcrypt_hash(config.admin_password_hash, var_name="BOOTSTRAP_ADMIN_PASSWORD_HASH")
    email = normalize_email(config.admin_email, var_name="BOOTSTRAP_ADMIN_EMAIL")

    # ⚠️ GUARD (a). Counts EVERY user, including soft-deleted ones: a
    # soft-deleted row still means this database has been used, and "bootstrap"
    # stops being an accurate description of what this would do.
    existing_users = await db.scalar(select(func.count()).select_from(User))
    if existing_users:
        raise ProvisioningError(
            f"Refusing to bootstrap: this database already contains {existing_users} "
            f"user(s). This tool creates the FIRST account only. To add another "
            f"user to a populated environment, use app.scripts.add_user."
        )

    company = Company(
        name=config.company_name,
        slug=config.company_slug,
        is_active=True,
    )
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


def success_line(company: Company, user: User) -> str:
    """The single line this script prints on success.

    Its own function so a test can assert what it does and does not contain:
    these logs live in CloudWatch for 30 days.
    """
    return f"created company {company.slug}, user {user.email}"


async def _run() -> None:
    config = config_from_env()
    async with async_session_maker() as db:
        company, user = await bootstrap(
            db,
            config,
            environment=settings.environment,
            allowed_environments=_allowed_environments(),
        )
        # A standalone script owns its transaction: nothing else will commit.
        await db.commit()
        line = success_line(company, user)
    print(line)


def _allowed_environments() -> str:
    return os.environ.get(ALLOWLIST_VAR, DEFAULT_ALLOWED_ENVIRONMENTS)


def main() -> None:
    """Entry point. Turns a refusal into a clear message and a non-zero exit."""
    try:
        asyncio.run(_run())
    except ProvisioningError as exc:
        # str(exc) is safe by construction: no guard puts a value in its message.
        print(f"REFUSED: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
