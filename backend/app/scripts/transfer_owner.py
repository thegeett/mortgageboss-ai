"""Move a company's owner to another of its admins, in a deployed environment.

The owner (``companies.owner_user_id``, ADR-440) is the admin the app refuses to
deactivate or demote. Changing it is never an API: MortgageBoss runs this on the
customer's request. It is also how a company the LP-MB-Admin-01 migration left
with no owner gets one.

Usage (as a one-off ECS task; see ``./scripts/deploy <env> transfer-owner``)::

    uv run python -m app.scripts.transfer_owner

Environment variables, ALL REQUIRED, no defaults:

    TRANSFER_OWNER_COMPANY_SLUG      must already exist and be live
    TRANSFER_OWNER_EMAIL             the new owner: an active ADMIN of that company

    TRANSFER_OWNER_ALLOWED_ENVIRONMENTS   comma-separated, defaults to "staging"

**Only an active admin of the same company.** Anyone else is refused: a user of
another company would hand one tenant's guardrail to a stranger, and a
non-admin or inactive owner is the state the owner exists to rule out. Making
someone an admin first is a separate, deliberate step.

Writes one ``owner_transferred`` row to ``company_audit_log`` with no actor (the
platform, not a user of the company). Prints one line and no secret.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass

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
)
from app.services.activity_log import field_changes
from app.services.company_audit import AuditAction, log_company_action

ALLOWLIST_VAR = "TRANSFER_OWNER_ALLOWED_ENVIRONMENTS"
DEFAULT_ALLOWED_ENVIRONMENTS = "staging"


@dataclass(frozen=True)
class TransferOwnerConfig:
    """Everything the tool needs. Built once, validated before use."""

    company_slug: str
    email: str


def config_from_env() -> TransferOwnerConfig:
    """Read and validate every input. Raises :class:`ProvisioningError`."""
    return TransferOwnerConfig(
        company_slug=require_env("TRANSFER_OWNER_COMPANY_SLUG"),
        email=normalize_email(require_env("TRANSFER_OWNER_EMAIL"), var_name="TRANSFER_OWNER_EMAIL"),
    )


async def transfer_owner(
    db: AsyncSession,
    config: TransferOwnerConfig,
    *,
    environment: str,
    allowed_environments: str,
) -> tuple[Company, User]:
    """Make the named user the company's owner, or refuse.

    Every guard lives here rather than in :func:`main`, so no caller can reach
    the write without passing them.

    Raises:
        ProvisioningError: the environment is not allowlisted, the company slug
            is unknown or soft-deleted, the email names no user, or the user is
            in another company, inactive, deleted, not an admin, or already the
            owner.
    """
    assert_environment_allowed(
        current=environment,
        allowed_raw=allowed_environments,
        allowlist_var=ALLOWLIST_VAR,
    )
    email = normalize_email(config.email, var_name="TRANSFER_OWNER_EMAIL")

    company = await db.scalar(
        select(Company).where(
            Company.slug == config.company_slug,
            Company.deleted_at.is_(None),
        )
    )
    if company is None:
        raise ProvisioningError(
            f"No live company with slug {config.company_slug!r} (a soft-deleted one does "
            f"not count). Nothing was changed."
        )

    # Case-insensitive, like `assert_email_unused`: the index is not, and the
    # operator's typing should not decide whether the user is found. For the same
    # reason two rows can match; picking one would make a guess the owner.
    matches = list(await db.scalars(select(User).where(func.lower(User.email) == email.lower())))
    if not matches:
        raise ProvisioningError(f"No user with email {email!r}. Nothing was changed.")
    if len(matches) > 1:
        raise ProvisioningError(
            f"{len(matches)} users have the email {email!r} in different case; refusing to "
            f"guess which is meant. Nothing was changed."
        )
    user = matches[0]
    if user.company_id != company.id:
        raise ProvisioningError(
            f"{email} belongs to another company, not {company.slug!r}. The owner must be "
            f"one of the company's own admins. Nothing was changed."
        )
    if not user.is_active or user.deleted_at is not None:
        raise ProvisioningError(
            f"{email} is inactive or deleted; the owner must be an active admin. "
            f"Nothing was changed."
        )
    if UserRole.ADMIN not in user.role_set:
        raise ProvisioningError(
            f"{email} is not an admin of {company.slug!r}; the owner must be one. Grant "
            f"ADMIN first. Nothing was changed."
        )
    if company.owner_user_id == user.id:
        raise ProvisioningError(
            f"{email} is already the owner of {company.slug!r}. Nothing was changed."
        )

    before = company.owner_user_id
    company.owner_user_id = user.id
    await db.flush()
    await log_company_action(
        db,
        company_id=company.id,
        actor_user_id=None,
        action=AuditAction.OWNER_TRANSFERRED,
        target_type="company",
        target_id=company.id,
        summary="Owner transferred by MortgageBoss (platform script)",
        detail={"changes": field_changes({"owner_user_id": before}, {"owner_user_id": user.id})},
    )
    return company, user


def _allowed_environments() -> str:
    return os.environ.get(ALLOWLIST_VAR, DEFAULT_ALLOWED_ENVIRONMENTS)


def success_line(company: Company, user: User) -> str:
    """The single line this script prints on success.

    Its own function so a test can assert what it does and does not contain:
    these logs live in CloudWatch for 30 days.
    """
    return f"owner of {company.slug} is now {user.email}"


async def _run() -> None:
    config = config_from_env()
    async with async_session_maker() as db:
        company, user = await transfer_owner(
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
