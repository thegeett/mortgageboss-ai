"""Tests for the property service (LP-29).

Exercises :mod:`app.services.properties` against the rollback ``db_session``:
the per-file singleton invariant (a second create raises ``PropertyExistsError``),
plus get / update / soft delete.
"""

import pytest
from app.models import Company
from app.models.loan_file import LoanFile
from app.models.property import OccupancyType, PropertyType
from app.schemas.property import PropertyCreate, PropertyUpdate
from app.services.loan_files import create_loan_file
from app.services.properties import (
    PropertyExistsError,
    create_property,
    get_property,
    soft_delete_property,
    update_property,
)
from sqlalchemy.ext.asyncio import AsyncSession


async def _file(db: AsyncSession, slug: str = "acme") -> LoanFile:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    return await create_loan_file(db, company_id=company.id)


async def test_get_returns_none_when_absent(db_session: AsyncSession) -> None:
    """get_property returns None for a file with no property."""
    loan_file = await _file(db_session)
    assert await get_property(db_session, loan_file_id=loan_file.id) is None


async def test_create_then_get(db_session: AsyncSession) -> None:
    """A created property is retrievable with its fields."""
    loan_file = await _file(db_session)
    created = await create_property(
        db_session,
        loan_file_id=loan_file.id,
        data=PropertyCreate(
            address_line="123 Main St",
            city="Austin",
            state="TX",
            property_type=PropertyType.SINGLE_FAMILY,
            occupancy_type=OccupancyType.PRIMARY_RESIDENCE,
        ),
    )
    fetched = await get_property(db_session, loan_file_id=loan_file.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.address_line == "123 Main St"
    assert fetched.property_type is PropertyType.SINGLE_FAMILY


async def test_second_create_raises_exists(db_session: AsyncSession) -> None:
    """The per-file singleton: a second create raises PropertyExistsError."""
    loan_file = await _file(db_session)
    await create_property(db_session, loan_file_id=loan_file.id, data=PropertyCreate(city="Austin"))
    with pytest.raises(PropertyExistsError):
        await create_property(
            db_session, loan_file_id=loan_file.id, data=PropertyCreate(city="Dallas")
        )


async def test_update_applies_set_fields(db_session: AsyncSession) -> None:
    """Update applies only the provided fields."""
    loan_file = await _file(db_session)
    created = await create_property(
        db_session, loan_file_id=loan_file.id, data=PropertyCreate(city="Austin", state="TX")
    )
    await update_property(db_session, property_obj=created, data=PropertyUpdate(city="Dallas"))
    assert created.city == "Dallas"
    assert created.state == "TX"  # untouched


async def test_soft_delete_excludes_from_reads(db_session: AsyncSession) -> None:
    """Soft delete sets deleted_at and removes the property from get."""
    loan_file = await _file(db_session)
    created = await create_property(
        db_session, loan_file_id=loan_file.id, data=PropertyCreate(city="Austin")
    )
    await soft_delete_property(db_session, property_obj=created)
    assert created.deleted_at is not None
    assert await get_property(db_session, loan_file_id=loan_file.id) is None
    # NOTE: the DB unique(loan_file_id) constraint still holds for the soft-deleted
    # row, so re-creating a property on the same file is a separate concern (a
    # partial unique index would be a later model change); not exercised here.
