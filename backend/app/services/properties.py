"""Property service — the subject property owned by a loan file (LP-29).

Like borrowers, a Property has no ``company_id``: it is scoped transitively
through its loan file (ADR-052/053), and these functions take an already
scope-checked ``loan_file_id``. The property is a **per-file singleton** (one
active property per file): :func:`create_property` raises
:class:`PropertyExistsError` if one already exists, which the endpoint maps to a
``409``. Reads exclude soft-deleted rows; services ``flush`` and the endpoint
commits.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.helpers import only_active
from app.models.property import Property
from app.schemas.property import PropertyCreate, PropertyUpdate


class PropertyExistsError(Exception):
    """Raised when creating a property for a file that already has one (409)."""


async def get_property(db: AsyncSession, *, loan_file_id: UUID) -> Property | None:
    """The file's active subject property, or ``None`` if it has none."""
    stmt = select(Property).where(Property.loan_file_id == loan_file_id)
    stmt = only_active(stmt, Property)
    property_obj: Property | None = await db.scalar(stmt)
    return property_obj


async def create_property(
    db: AsyncSession, *, loan_file_id: UUID, data: PropertyCreate
) -> Property:
    """Attach the subject property to a file (one per file).

    Raises :class:`PropertyExistsError` if the file already has an active
    property — the singleton invariant, also backed by the DB unique constraint.
    """
    if await get_property(db, loan_file_id=loan_file_id) is not None:
        raise PropertyExistsError("This loan file already has a property.")

    property_obj = Property(
        loan_file_id=loan_file_id,
        address_line=data.address_line,
        address_line_2=data.address_line_2,
        city=data.city,
        state=data.state,
        postal_code=data.postal_code,
        property_type=data.property_type,
        occupancy_type=data.occupancy_type,
        estimated_value=data.estimated_value,
        purchase_price=data.purchase_price,
    )
    db.add(property_obj)
    await db.flush()
    return property_obj


async def update_property(
    db: AsyncSession, *, property_obj: Property, data: PropertyUpdate
) -> Property:
    """Apply a partial update to the property (only provided fields change)."""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(property_obj, field, value)
    await db.flush()
    return property_obj


async def soft_delete_property(db: AsyncSession, *, property_obj: Property) -> None:
    """Soft-delete the property (set ``deleted_at``); never a hard delete."""
    property_obj.deleted_at = utcnow()
    await db.flush()
