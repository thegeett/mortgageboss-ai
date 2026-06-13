"""Tests for the Property model (LP-14).

Covers the subject property: field round-tripping, the one-property-per-file
guarantee (a unique constraint on loan_file_id), the property_type / occupancy_
type CHECK constraints, Decimal money storage, the one-to-one relationship from
the loan file, and soft delete + only_active.

Uses the transaction-rollback ``db_session`` fixture from LP-10.
"""

from decimal import Decimal

import pytest
from app.models import (
    Company,
    LoanFile,
    OccupancyType,
    Property,
    PropertyType,
    only_active,
    utcnow,
)
from app.services.loan_files import create_loan_file
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def _make_company(db_session: AsyncSession, slug: str) -> Company:
    company = Company(name=slug.title(), slug=slug)
    db_session.add(company)
    await db_session.flush()
    return company


async def _make_loan_file(db_session: AsyncSession, company: Company) -> LoanFile:
    return await create_loan_file(db_session, company_id=company.id)


async def _add_property(
    db_session: AsyncSession, loan_file: LoanFile, **kwargs: object
) -> Property:
    prop = Property(loan_file_id=loan_file.id, **kwargs)
    db_session.add(prop)
    await db_session.flush()
    return prop


async def test_create_property_with_fields(db_session: AsyncSession) -> None:
    """A property persists its address, classification, and valuation fields."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    prop = await _add_property(
        db_session,
        loan_file,
        address_line="123 Main St",
        city="Austin",
        state="TX",
        postal_code="78701",
        property_type=PropertyType.SINGLE_FAMILY,
        occupancy_type=OccupancyType.PRIMARY_RESIDENCE,
    )

    await db_session.refresh(prop)
    assert prop.address_line == "123 Main St"
    assert prop.city == "Austin"
    assert prop.state == "TX"
    assert prop.postal_code == "78701"
    assert prop.property_type is PropertyType.SINGLE_FAMILY
    assert prop.occupancy_type is OccupancyType.PRIMARY_RESIDENCE


async def test_one_property_per_file(db_session: AsyncSession) -> None:
    """A second property on the same file fails the unique constraint."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    await _add_property(db_session, loan_file, property_type=PropertyType.CONDO)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await _add_property(db_session, loan_file, property_type=PropertyType.TOWNHOUSE)


async def test_property_type_check_constraint_rejects_invalid_value(
    db_session: AsyncSession,
) -> None:
    """The DB CHECK constraint rejects an out-of-range property_type."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    prop = await _add_property(db_session, loan_file, property_type=PropertyType.CONDO)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE properties SET property_type = :bad WHERE id = :id"),
                {"bad": "castle", "id": prop.id},
            )


async def test_occupancy_type_check_constraint_rejects_invalid_value(
    db_session: AsyncSession,
) -> None:
    """The DB CHECK constraint rejects an out-of-range occupancy_type."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    prop = await _add_property(db_session, loan_file, occupancy_type=OccupancyType.INVESTMENT)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE properties SET occupancy_type = :bad WHERE id = :id"),
                {"bad": "timeshare", "id": prop.id},
            )


async def test_money_fields_store_decimal(db_session: AsyncSession) -> None:
    """estimated_value and purchase_price store and read back exact Decimals."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    prop = await _add_property(
        db_session,
        loan_file,
        estimated_value=Decimal("525000.00"),
        purchase_price=Decimal("499999.99"),
    )

    await db_session.refresh(prop)
    assert prop.estimated_value == Decimal("525000.00")
    assert prop.purchase_price == Decimal("499999.99")
    assert isinstance(prop.estimated_value, Decimal)


async def test_loan_file_property_relationship_returns_single(db_session: AsyncSession) -> None:
    """loan_file.property is the single subject property (one-to-one)."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    prop = await _add_property(db_session, loan_file, property_type=PropertyType.SINGLE_FAMILY)

    stmt = (
        select(LoanFile).where(LoanFile.id == loan_file.id).options(selectinload(LoanFile.property))
    )
    loaded = (await db_session.scalars(stmt)).one()
    assert loaded.property is not None
    assert loaded.property.id == prop.id


async def test_soft_delete_and_only_active(db_session: AsyncSession) -> None:
    """Soft delete sets deleted_at; only_active() filters the property out."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    prop = await _add_property(db_session, loan_file, property_type=PropertyType.CONDO)

    prop.deleted_at = utcnow()
    await db_session.flush()
    assert prop.is_deleted is True

    stmt = only_active(select(Property), Property)
    ids = {p.id for p in (await db_session.scalars(stmt)).all()}
    assert prop.id not in ids
