"""Tests for the Company model (LP-11).

Covers basic create/read, the globally-unique slug, and soft-delete filtering.
Uses the transaction-rollback ``db_session`` fixture from LP-10.
"""

from datetime import datetime

import pytest
from app.models import Company, only_active, utcnow
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def test_create_and_query_company(db_session: AsyncSession) -> None:
    """A company can be created and read back with all fields and defaults."""
    company = Company(name="Acme Mortgage", slug="acme-mortgage")
    db_session.add(company)
    await db_session.flush()
    await db_session.refresh(company)

    fetched = await db_session.get(Company, company.id)
    assert fetched is not None
    assert fetched.name == "Acme Mortgage"
    assert fetched.slug == "acme-mortgage"
    # JSON settings defaults to an empty dict.
    assert fetched.settings == {}
    # is_active defaults to True; soft-delete column starts null.
    assert fetched.is_active is True
    assert fetched.deleted_at is None
    assert fetched.is_deleted is False
    # Mixins populate id and timestamps.
    assert fetched.id is not None
    assert isinstance(fetched.created_at, datetime)
    assert isinstance(fetched.updated_at, datetime)


async def test_settings_roundtrips_json(db_session: AsyncSession) -> None:
    """The settings JSON column stores and returns a structured object."""
    company = Company(
        name="Configured Co",
        slug="configured-co",
        settings={"feature_flags": {"beta": True}, "timezone": "America/New_York"},
    )
    db_session.add(company)
    await db_session.flush()
    await db_session.refresh(company)

    assert company.settings["feature_flags"] == {"beta": True}
    assert company.settings["timezone"] == "America/New_York"


async def test_slug_is_globally_unique(db_session: AsyncSession) -> None:
    """Two companies cannot share a slug (slug is globally unique, ADR-042-style)."""
    db_session.add(Company(name="First", slug="dup"))
    await db_session.flush()

    # Contain the expected failure in a SAVEPOINT so it doesn't poison the
    # outer (rolled-back) test transaction.
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(Company(name="Second", slug="dup"))
            await db_session.flush()


async def test_soft_delete_and_only_active(db_session: AsyncSession) -> None:
    """Soft delete sets deleted_at; only_active() filters such rows out."""
    live = Company(name="Live", slug="live")
    gone = Company(name="Gone", slug="gone")
    db_session.add_all([live, gone])
    await db_session.flush()

    gone.deleted_at = utcnow()
    await db_session.flush()
    assert gone.is_deleted is True

    # Without the helper, both rows are visible.
    all_slugs = {c.slug for c in (await db_session.scalars(select(Company))).all()}
    assert all_slugs == {"live", "gone"}

    # With the helper, the soft-deleted row is excluded.
    active = only_active(select(Company), Company)
    active_slugs = {c.slug for c in (await db_session.scalars(active)).all()}
    assert active_slugs == {"live"}
