"""Tests for the new-tenant provisioning script.

bootstrap_admin makes the first company; add_user refuses to make one at all.
add_company is the deliberate way to make a second, so its refusals are about
the ways a deliberate second tenant can still be a mistake.
"""

from datetime import UTC, datetime

import pytest
from app.core.security import hash_password
from app.models.company import Company
from app.models.user import User, UserRole
from app.schemas.auth import LoginRequest
from app.scripts._provisioning import ProvisioningError
from app.scripts.add_company import (
    ALLOWLIST_VAR,
    AddCompanyConfig,
    add_company,
    config_from_env,
    success_line,
    validate_slug,
)
from app.services.auth import authenticate_user
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

PASSWORD = "correct horse battery staple"  # pragma: allowlist secret  (test-only)


async def _existing(db: AsyncSession, *, slug: str = "first", name: str = "First Co") -> Company:
    """A populated environment: one company with one admin, as staging has."""
    company = Company(name=name, slug=slug, is_active=True)
    db.add(company)
    await db.flush()
    db.add(
        User(
            company_id=company.id,
            email=f"admin@{slug}.example.com",
            hashed_password=hash_password(PASSWORD),
            first_name="First",
            last_name="Admin",
            role=UserRole.ADMIN,
            is_active=True,
        )
    )
    await db.flush()
    return company


def _config(**overrides: str) -> AddCompanyConfig:
    base: dict[str, str] = {
        "company_name": "Vema Mortgage",
        "company_slug": "vemamortgage",
        "admin_email": "admin@vema.example.com",
        "admin_password_hash": hash_password(PASSWORD),
        "admin_first_name": "Grace",
        "admin_last_name": "Hopper",
    }
    base.update(overrides)
    return AddCompanyConfig(**base)


async def _add(db: AsyncSession, config: AddCompanyConfig, **kw: str) -> tuple[Company, User]:
    return await add_company(
        db,
        config,
        environment=kw.get("environment", "staging"),
        allowed_environments=kw.get("allowed_environments", "staging"),
    )


async def _counts(db: AsyncSession) -> tuple[int | None, int | None]:
    return (
        await db.scalar(select(func.count()).select_from(Company)),
        await db.scalar(select(func.count()).select_from(User)),
    )


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #


async def test_creates_a_second_company_and_its_admin(db_session: AsyncSession) -> None:
    """The case neither existing script can do: a populated database, a new tenant."""
    first = await _existing(db_session)

    company, user = await _add(db_session, _config())

    assert company.id != first.id
    assert (company.name, company.slug, company.is_active) == (
        "Vema Mortgage",
        "vemamortgage",
        True,
    )
    assert user.company_id == company.id
    assert user.role is UserRole.ADMIN
    assert user.is_active is True
    assert await _counts(db_session) == (2, 2)


async def test_works_on_an_empty_database_too(db_session: AsyncSession) -> None:
    await _add(db_session, _config())

    assert await _counts(db_session) == (1, 1)


async def test_the_new_admin_logs_in_through_the_app(db_session: AsyncSession) -> None:
    await _existing(db_session)
    typed = "Admin@Vema.Example.COM"
    _, user = await _add(db_session, _config(admin_email=typed))

    # What the API hands authenticate_user after pydantic parses the body.
    normalized = LoginRequest(email=typed, password=PASSWORD).email
    authenticated = await authenticate_user(db_session, email=normalized, password=PASSWORD)

    assert authenticated.id == user.id
    assert user.email == "Admin@vema.example.com"


# --------------------------------------------------------------------------- #
# Slug
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("slug", ["vemamortgage", "acme-mortgage", "a1", "x"])
def test_validate_slug_accepts_url_safe_slugs(slug: str) -> None:
    assert validate_slug(slug) == slug


@pytest.mark.parametrize(
    "slug",
    ["Vema", "vema mortgage", "vema_mortgage", "-vema", "vema-", "vema--mortgage", "vemä", ""],
)
def test_validate_slug_refuses_anything_else(slug: str) -> None:
    with pytest.raises(ProvisioningError, match="not a valid slug"):
        validate_slug(slug)


def test_validate_slug_refuses_one_longer_than_the_column() -> None:
    with pytest.raises(ProvisioningError, match="the limit is 64"):
        validate_slug("a" * 65)


async def test_refuses_a_malformed_slug_before_any_write(db_session: AsyncSession) -> None:
    await _existing(db_session)

    with pytest.raises(ProvisioningError, match="not a valid slug"):
        await _add(db_session, _config(company_slug="Vema Mortgage"))

    assert await _counts(db_session) == (1, 1)


async def test_refuses_a_slug_an_existing_company_has(db_session: AsyncSession) -> None:
    await _existing(db_session, slug="vemamortgage", name="Something Else")

    with pytest.raises(ProvisioningError, match="belongs to an existing company"):
        await _add(db_session, _config())

    assert await _counts(db_session) == (1, 1)


async def test_refuses_the_slug_of_a_soft_deleted_company(db_session: AsyncSession) -> None:
    """The unique index covers deleted rows; the refusal must, too."""
    gone = await _existing(db_session, slug="vemamortgage", name="Old Vema")
    gone.deleted_at = datetime.now(UTC)
    await db_session.flush()

    with pytest.raises(ProvisioningError, match="belongs to a soft-deleted company"):
        await _add(db_session, _config())

    assert await _counts(db_session) == (1, 1)


# --------------------------------------------------------------------------- #
# Name
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("existing_name", ["Vema Mortgage", "vema mortgage", "  VEMA MORTGAGE "])
async def test_refuses_a_name_a_live_company_has(
    db_session: AsyncSession, existing_name: str
) -> None:
    """The same tenant twice under two slugs is the duplicate add_user refuses."""
    await _existing(db_session, slug="vema", name=existing_name)

    with pytest.raises(ProvisioningError, match="already exists with slug 'vema'"):
        await _add(db_session, _config())

    assert await _counts(db_session) == (1, 1)


async def test_allows_the_name_of_a_soft_deleted_company(db_session: AsyncSession) -> None:
    """Re-onboarding a decommissioned tenant under its old name is legitimate."""
    gone = await _existing(db_session, slug="vema-old", name="Vema Mortgage")
    gone.deleted_at = datetime.now(UTC)
    await db_session.flush()

    company, _ = await _add(db_session, _config())

    assert company.slug == "vemamortgage"


async def test_stores_the_name_trimmed(db_session: AsyncSession) -> None:
    company, _ = await _add(db_session, _config(company_name="  Vema Mortgage  "))

    assert company.name == "Vema Mortgage"


async def test_refuses_a_blank_name(db_session: AsyncSession) -> None:
    with pytest.raises(ProvisioningError, match="ADD_COMPANY_NAME is required"):
        await _add(db_session, _config(company_name="   "))

    assert await _counts(db_session) == (0, 0)


# --------------------------------------------------------------------------- #
# Admin email -- globally unique, ignoring case
# --------------------------------------------------------------------------- #


async def test_refuses_an_email_a_user_in_another_company_has(db_session: AsyncSession) -> None:
    """The refusal must leave NO company behind: the check precedes every write."""
    await _existing(db_session, slug="first")

    with pytest.raises(ProvisioningError, match="globally unique"):
        await _add(db_session, _config(admin_email="Admin@First.Example.com"))

    assert await _counts(db_session) == (1, 1)


async def test_refuses_a_malformed_email_before_any_write(db_session: AsyncSession) -> None:
    with pytest.raises(ProvisioningError, match="not a valid email address"):
        await _add(db_session, _config(admin_email="not-an-email"))

    assert await _counts(db_session) == (0, 0)


# --------------------------------------------------------------------------- #
# The allowlist and the hash -- same guards as the other provisioning scripts
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("environment", ["development", "production", "prod", ""])
async def test_refuses_outside_the_allowlist(db_session: AsyncSession, environment: str) -> None:
    with pytest.raises(ProvisioningError, match=ALLOWLIST_VAR):
        await _add(db_session, _config(), environment=environment)

    assert await _counts(db_session) == (0, 0)


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
    with pytest.raises(ProvisioningError):
        await _add(db_session, _config(admin_password_hash=bad_hash))

    assert await _counts(db_session) == (0, 0)


# --------------------------------------------------------------------------- #
# Reading the environment
# --------------------------------------------------------------------------- #


_ENV = {
    "ADD_COMPANY_NAME": "Vema Mortgage",
    "ADD_COMPANY_SLUG": "vemamortgage",
    "ADD_COMPANY_ADMIN_EMAIL": "admin@vema.example.com",
    "ADD_COMPANY_ADMIN_FIRST_NAME": "Grace",
    "ADD_COMPANY_ADMIN_LAST_NAME": "Hopper",
}


def test_config_from_env_reads_every_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    supplied = hash_password(PASSWORD)
    for name, value in {**_ENV, "ADD_COMPANY_ADMIN_PASSWORD_HASH": supplied}.items():
        monkeypatch.setenv(name, value)

    config = config_from_env()

    assert config == AddCompanyConfig(
        company_name="Vema Mortgage",
        company_slug="vemamortgage",
        admin_email="admin@vema.example.com",
        admin_password_hash=supplied,
        admin_first_name="Grace",
        admin_last_name="Hopper",
    )


@pytest.mark.parametrize("missing", [*_ENV, "ADD_COMPANY_ADMIN_PASSWORD_HASH"])
def test_config_from_env_refuses_a_missing_variable(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    for name, value in {**_ENV, "ADD_COMPANY_ADMIN_PASSWORD_HASH": hash_password(PASSWORD)}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(missing)

    with pytest.raises(ProvisioningError, match=f"{missing} is required"):
        config_from_env()


# --------------------------------------------------------------------------- #
# Output hygiene
# --------------------------------------------------------------------------- #


async def test_success_line_contains_no_secret(db_session: AsyncSession) -> None:
    supplied = hash_password(PASSWORD)
    company, user = await _add(db_session, _config(admin_password_hash=supplied))

    line = success_line(company, user)

    assert supplied not in line
    assert PASSWORD not in line
    assert "$2" not in line
    assert line == "created company vemamortgage, admin admin@vema.example.com"


async def test_refusal_messages_contain_no_secret(db_session: AsyncSession) -> None:
    await _existing(db_session, slug="vemamortgage")
    supplied = hash_password(PASSWORD)

    with pytest.raises(ProvisioningError) as excinfo:
        await _add(db_session, _config(admin_password_hash=supplied))

    assert supplied not in str(excinfo.value)
