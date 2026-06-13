"""SQLAlchemy declarative base, mixins, and naming conventions.

Every model in the application inherits from Base. Common patterns
(timestamps, soft delete, UUID primary keys) are provided as mixins.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Constraint naming convention for readable, predictable constraint names.
# This makes migrations and debugging far easier. Set once, applies everywhere.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for all models.

    Uses a MetaData with a naming convention so that constraints
    (foreign keys, indexes, unique constraints, etc.) get readable,
    predictable names instead of database-generated cryptic ones.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(UTC)


class TimestampMixin:
    """Adds created_at and updated_at timestamp columns.

    Both are timezone-aware (stored as timestamptz in Postgres, always UTC).
    created_at is set on insert; updated_at is set on insert and updated on
    every modification.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class SoftDeleteMixin:
    """Adds a deleted_at column for soft deletion.

    Records are marked deleted (deleted_at set to a timestamp) rather than
    physically removed, preserving the audit trail. Filtering out deleted
    records is explicit at the query level — this mixin provides the column
    and a convenience property, not automatic global filtering.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        nullable=True,
    )

    @property
    def is_deleted(self) -> bool:
        """True if this record has been soft-deleted."""
        return self.deleted_at is not None


class UUIDMixin:
    """Adds a UUID primary key column with automatic generation.

    Most tables use UUID primary keys. The exception is loan_files, which
    uses human-readable IDs (LF-XXX); that is handled separately in its model.
    """

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )
