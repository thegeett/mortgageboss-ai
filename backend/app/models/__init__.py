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
from app.models.enums import RecordStatus, str_enum
from app.models.helpers import only_active
from app.models.types import (
    LongStr,
    MediumStr,
    Money,
    ShortStr,
)

__all__ = [
    "Base",
    "LongStr",
    "MediumStr",
    "Money",
    "RecordStatus",
    "ShortStr",
    "SoftDeleteMixin",
    "TimestampMixin",
    "UUIDMixin",
    "only_active",
    "str_enum",
    "utcnow",
]

# Concrete models will be imported here in later tickets (e.g. Company in
# LP-11) with a re-export marker so linters keep the import. Importing them
# here ensures Alembic autogenerate sees all tables.
