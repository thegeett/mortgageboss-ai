"""Tests for the first-account bootstrap script.

The guards are the point of this script, so they are what is tested hardest: it
runs as a one-off task against a deployed environment holding real borrower NPI,
where a mistake is expensive and there is no undo.
"""

import pytest
from app.core.security import hash_password, verify_password
from app.models.company import Company
from app.models.user import User, UserRole
from app.scripts._provisioning import ProvisioningError
from app.scripts.bootstrap_admin import (
    ALLOWLIST_VAR,
    BootstrapConfig,
    bootstrap,
    success_line,
)
from app.services.auth import authenticate_user
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

PASSWORD = "correct horse battery staple"  # pragma: allowlist secret  (test-only)


def _config(**overrides: str) -> BootstrapConfig:
    base = {
        "admin_email": "admin@example.com",
        "admin_password_hash": hash_password(PASSWORD),
        "admin_first_name": "Ada",
        "admin_last_name": "Lovelace",
        "company_name": "Example Processing",
        "company_slug": "example",
    }
    base.update(overrides)
    return BootstrapConfig(**base)


async def _bootstrap(db: AsyncSession, config: BootstrapConfig, **kw: str) -> tuple[Company, User]:
    return await bootstrap(
        db,
        config,
        environment=kw.get("environment", "staging"),
        allowed_environments=kw.get("allowed_environments", "staging"),
    )


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #


async def test_creates_one_company_and_one_admin(db_session: AsyncSession) -> None:
    company, user = await _bootstrap(db_session, _config())

    assert company.slug == "example"
    assert company.is_active is True
    assert user.company_id == company.id
    assert user.role is UserRole.ADMIN
    assert user.is_active is True

    assert await db_session.scalar(select(func.count()).select_from(Company)) == 1
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1


async def test_created_user_authenticates_through_the_app(db_session: AsyncSession) -> None:
    """The whole point: the account must work through the real login path.

    Not `verify_password` in isolation -- `authenticate_user` is what the login
    endpoint calls, and it also enforces is_active.
    """
    _, user = await _bootstrap(db_session, _config())

    authenticated = await authenticate_user(
        db_session, email="admin@example.com", password=PASSWORD
    )
    assert authenticated.id == user.id
    assert authenticated.role is UserRole.ADMIN


async def test_the_supplied_hash_is_stored_verbatim(db_session: AsyncSession) -> None:
    """The script stores the hash it was given -- it never re-hashes."""
    supplied = hash_password(PASSWORD)
    _, user = await _bootstrap(db_session, _config(admin_password_hash=supplied))

    assert user.hashed_password == supplied
    assert verify_password(PASSWORD, user.hashed_password) is True


# --------------------------------------------------------------------------- #
# Guard (a) -- refuse against a populated database
# --------------------------------------------------------------------------- #


async def test_refuses_when_any_user_exists(db_session: AsyncSession) -> None:
    await _bootstrap(db_session, _config())

    with pytest.raises(ProvisioningError, match="already contains"):
        await _bootstrap(
            db_session,
            _config(admin_email="second@example.com", company_slug="second"),
        )

    # And nothing from the refused run was left behind.
    assert await db_session.scalar(select(func.count()).select_from(Company)) == 1
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1


async def test_refuses_even_when_the_only_user_is_soft_deleted(
    db_session: AsyncSession,
) -> None:
    """A soft-deleted user still means this database has been used.

    Counting only live rows would let 'bootstrap' run against an environment
    with history, which is exactly what the guard exists to prevent.
    """
    _, user = await _bootstrap(db_session, _config())
    user.deleted_at = user.created_at
    await db_session.flush()

    with pytest.raises(ProvisioningError, match="already contains"):
        await _bootstrap(
            db_session, _config(admin_email="second@example.com", company_slug="second")
        )


# --------------------------------------------------------------------------- #
# Guard (b) -- the explicit environment allowlist
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("environment", ["development", "production", "prod", "test", ""])
async def test_refuses_outside_the_allowlist(db_session: AsyncSession, environment: str) -> None:
    with pytest.raises(ProvisioningError, match="Refusing to run"):
        await _bootstrap(db_session, _config(), environment=environment)

    assert await db_session.scalar(select(func.count()).select_from(Company)) == 0


async def test_allowlist_refuses_before_touching_the_database(
    db_session: AsyncSession,
) -> None:
    """The environment check runs first, so a wrong environment writes nothing."""
    with pytest.raises(ProvisioningError):
        await _bootstrap(db_session, _config(), environment="production")

    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


async def test_allowlist_accepts_a_multi_entry_list(db_session: AsyncSession) -> None:
    company, _ = await _bootstrap(
        db_session,
        _config(),
        environment="sandbox",
        allowed_environments="staging, sandbox",
    )
    assert company.slug == "example"


async def test_empty_allowlist_permits_nothing(db_session: AsyncSession) -> None:
    """An empty list must fail closed, not open."""
    with pytest.raises(ProvisioningError, match="no environment is permitted"):
        await _bootstrap(db_session, _config(), allowed_environments="")


async def test_the_refusal_names_the_allowlist_variable(db_session: AsyncSession) -> None:
    """The operator has to know which knob to turn."""
    with pytest.raises(ProvisioningError, match=ALLOWLIST_VAR):
        await _bootstrap(db_session, _config(), environment="production")


# --------------------------------------------------------------------------- #
# Hash validation -- before any write
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "bad_hash",
    [
        pytest.param(PASSWORD, id="a-plaintext-password"),
        pytest.param("$1$abcdefgh$xxxxxxxxxxxxxxxxxxxxxx", id="wrong-algorithm"),
        pytest.param(hash_password(PASSWORD)[:40], id="truncated"),
        pytest.param(hash_password(PASSWORD) + "xx", id="too-long"),
        pytest.param("$2b$12$" + "!" * 53, id="right-shape-unparseable"),
        pytest.param("", id="empty"),
    ],
)
async def test_rejects_a_malformed_hash_before_any_write(
    db_session: AsyncSession, bad_hash: str
) -> None:
    with pytest.raises(ProvisioningError):
        await _bootstrap(db_session, _config(admin_password_hash=bad_hash))

    # The company must NOT have been created first and orphaned.
    assert await db_session.scalar(select(func.count()).select_from(Company)) == 0
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


async def test_accepts_a_2a_hash(db_session: AsyncSession) -> None:
    """`$2a$` is a legitimate bcrypt variant and must not be rejected."""
    as_2a = "$2a$" + hash_password(PASSWORD)[4:]
    _, user = await _bootstrap(db_session, _config(admin_password_hash=as_2a))
    assert user.hashed_password.startswith("$2a$")


# --------------------------------------------------------------------------- #
# Output hygiene -- these logs live in CloudWatch for 30 days
# --------------------------------------------------------------------------- #


async def test_success_line_contains_no_secret(db_session: AsyncSession) -> None:
    supplied = hash_password(PASSWORD)
    company, user = await _bootstrap(db_session, _config(admin_password_hash=supplied))

    line = success_line(company, user)

    assert supplied not in line
    assert PASSWORD not in line
    # The bcrypt marker would signal a hash leaked in even if it were mangled.
    assert "$2" not in line
    assert line == "created company example, user admin@example.com"


@pytest.mark.parametrize(
    "bad_hash",
    [PASSWORD, hash_password(PASSWORD)[:40], "$2b$12$" + "!" * 53],
)
async def test_refusal_messages_contain_no_secret(db_session: AsyncSession, bad_hash: str) -> None:
    """A guard message must be safe to paste into a ticket."""
    with pytest.raises(ProvisioningError) as excinfo:
        await _bootstrap(db_session, _config(admin_password_hash=bad_hash))

    message = str(excinfo.value)
    assert bad_hash not in message
    assert PASSWORD not in message
