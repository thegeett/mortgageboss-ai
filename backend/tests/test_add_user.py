"""Tests for the ongoing user-creation script.

The counterpart to ``bootstrap_admin``: it runs against a POPULATED database, so
it drops the no-users-yet guard and keeps every other one. Its refusals matter
more, not less, for that reason.
"""

import pytest
from app.core.security import hash_password
from app.models.company import Company
from app.models.user import User, UserRole
from app.scripts._provisioning import ProvisioningError
from app.scripts.add_user import (
    ALLOWLIST_VAR,
    AddUserConfig,
    add_user,
    parse_role,
    success_line,
)
from app.services.auth import authenticate_user
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

PASSWORD = "correct horse battery staple"  # pragma: allowlist secret  (test-only)


async def _company(db: AsyncSession, slug: str = "example") -> Company:
    company = Company(name=f"Company {slug}", slug=slug, is_active=True)
    db.add(company)
    await db.flush()
    return company


def _config(**overrides: object) -> AddUserConfig:
    base: dict[str, object] = {
        "email": "processor@example.com",
        "password_hash": hash_password(PASSWORD),
        "first_name": "Grace",
        "last_name": "Hopper",
        "role": UserRole.PROCESSOR,
        "company_slug": "example",
    }
    base.update(overrides)
    return AddUserConfig(**base)  # type: ignore[arg-type]


async def _add(db: AsyncSession, config: AddUserConfig, **kw: str) -> User:
    return await add_user(
        db,
        config,
        environment=kw.get("environment", "staging"),
        allowed_environments=kw.get("allowed_environments", "staging"),
    )


# --------------------------------------------------------------------------- #
# The happy path, both roles
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.PROCESSOR])
async def test_creates_a_user_in_either_role(db_session: AsyncSession, role: UserRole) -> None:
    company = await _company(db_session)

    user = await _add(db_session, _config(role=role))

    assert user.company_id == company.id
    assert user.role is role
    assert user.is_active is True


async def test_created_user_authenticates_through_the_app(db_session: AsyncSession) -> None:
    await _company(db_session)
    user = await _add(db_session, _config())

    authenticated = await authenticate_user(
        db_session, email="processor@example.com", password=PASSWORD
    )
    assert authenticated.id == user.id


async def test_adds_to_a_populated_database(db_session: AsyncSession) -> None:
    """Unlike bootstrap_admin, existing users are not an obstacle."""
    company = await _company(db_session)
    db_session.add(
        User(
            company_id=company.id,
            email="first@example.com",
            hashed_password=hash_password(PASSWORD),
            first_name="First",
            last_name="User",
            role=UserRole.ADMIN,
            is_active=True,
        )
    )
    await db_session.flush()

    await _add(db_session, _config())

    assert await db_session.scalar(select(func.count()).select_from(User)) == 2


# --------------------------------------------------------------------------- #
# Refuse an unknown company
# --------------------------------------------------------------------------- #


async def test_refuses_an_unknown_company_slug(db_session: AsyncSession) -> None:
    await _company(db_session, slug="example")

    with pytest.raises(ProvisioningError, match="No company with slug"):
        await _add(db_session, _config(company_slug="exmaple"))


async def test_does_not_create_the_missing_company(db_session: AsyncSession) -> None:
    """A typo'd slug must not silently produce a second tenant.

    It matters because authenticate_user does not check company.is_active: a user
    attached to a stray company logs in perfectly well and sees an empty,
    wrong tenant.
    """
    await _company(db_session, slug="example")

    with pytest.raises(ProvisioningError):
        await _add(db_session, _config(company_slug="typo"))

    assert await db_session.scalar(select(func.count()).select_from(Company)) == 1
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


# --------------------------------------------------------------------------- #
# Refuse a duplicate email
# --------------------------------------------------------------------------- #


async def test_refuses_a_duplicate_email(db_session: AsyncSession) -> None:
    await _company(db_session)
    await _add(db_session, _config())

    with pytest.raises(ProvisioningError, match="already exists"):
        await _add(db_session, _config(first_name="Different"))

    assert await db_session.scalar(select(func.count()).select_from(User)) == 1


async def test_refuses_a_duplicate_email_from_another_company(
    db_session: AsyncSession,
) -> None:
    """Email is GLOBALLY unique, not per tenant.

    A clear refusal, not an IntegrityError traceback out of the driver.
    """
    await _company(db_session, slug="first")
    await _company(db_session, slug="second")
    await _add(db_session, _config(company_slug="first"))

    with pytest.raises(ProvisioningError, match="globally unique"):
        await _add(db_session, _config(company_slug="second"))


# --------------------------------------------------------------------------- #
# Role parsing -- explicit, no default
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ADMIN", UserRole.ADMIN),
        ("admin", UserRole.ADMIN),
        ("PROCESSOR", UserRole.PROCESSOR),
        ("processor", UserRole.PROCESSOR),
        ("  Admin  ", UserRole.ADMIN),
    ],
)
def test_parse_role_accepts_either_case(raw: str, expected: UserRole) -> None:
    assert parse_role(raw) is expected


@pytest.mark.parametrize("raw", ["", "owner", "ADMINISTRATOR", "admin,processor", "1"])
def test_parse_role_refuses_anything_else(raw: str) -> None:
    with pytest.raises(ProvisioningError, match="ADD_USER_ROLE must be one of"):
        parse_role(raw)


def test_parse_role_error_lists_the_valid_values() -> None:
    with pytest.raises(ProvisioningError) as excinfo:
        parse_role("owner")
    message = str(excinfo.value)
    assert "ADMIN" in message
    assert "PROCESSOR" in message


# --------------------------------------------------------------------------- #
# The allowlist and the hash -- same guards as the bootstrap script
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("environment", ["development", "production", "prod", ""])
async def test_refuses_outside_the_allowlist(db_session: AsyncSession, environment: str) -> None:
    await _company(db_session)

    with pytest.raises(ProvisioningError, match=ALLOWLIST_VAR):
        await _add(db_session, _config(), environment=environment)

    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


@pytest.mark.parametrize(
    "bad_hash",
    [
        pytest.param(PASSWORD, id="a-plaintext-password"),
        pytest.param(hash_password(PASSWORD)[:40], id="truncated"),
        pytest.param("$2b$12$" + "!" * 53, id="right-shape-unparseable"),
    ],
)
async def test_rejects_a_malformed_hash_before_any_write(
    db_session: AsyncSession, bad_hash: str
) -> None:
    await _company(db_session)

    with pytest.raises(ProvisioningError):
        await _add(db_session, _config(password_hash=bad_hash))

    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


# --------------------------------------------------------------------------- #
# Output hygiene
# --------------------------------------------------------------------------- #


async def test_success_line_contains_no_secret(db_session: AsyncSession) -> None:
    await _company(db_session)
    supplied = hash_password(PASSWORD)
    user = await _add(db_session, _config(password_hash=supplied))

    line = success_line(user, "example")

    assert supplied not in line
    assert PASSWORD not in line
    assert "$2" not in line
    assert line == "created user processor@example.com as processor in example"


async def test_refusal_messages_contain_no_secret(db_session: AsyncSession) -> None:
    await _company(db_session)
    supplied = hash_password(PASSWORD)

    with pytest.raises(ProvisioningError) as excinfo:
        await _add(db_session, _config(password_hash=supplied, company_slug="missing"))

    assert supplied not in str(excinfo.value)
