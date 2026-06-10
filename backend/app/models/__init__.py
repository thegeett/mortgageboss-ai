"""Models package.

Exports the declarative Base and common mixins. As concrete models are
added in subsequent tickets, they will also be imported here so that
Alembic autogenerate can discover them.
"""

from app.models.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDMixin,
    utcnow,
)

__all__ = [
    "Base",
    "SoftDeleteMixin",
    "TimestampMixin",
    "UUIDMixin",
    "utcnow",
]

# Concrete models will be imported here in later tickets (e.g. Company in
# LP-11) with a re-export marker so linters keep the import. Importing them
# here ensures Alembic autogenerate sees all tables.
