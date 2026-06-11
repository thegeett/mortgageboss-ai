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
from app.models.company import Company
from app.models.enums import RecordStatus, str_enum
from app.models.helpers import only_active, scope_to_company
from app.models.types import (
    LongStr,
    MediumStr,
    Money,
    ShortStr,
)
from app.models.user import User, UserRole

__all__ = [
    "Base",
    "Company",
    "LongStr",
    "MediumStr",
    "Money",
    "RecordStatus",
    "ShortStr",
    "SoftDeleteMixin",
    "TimestampMixin",
    "UUIDMixin",
    "User",
    "UserRole",
    "only_active",
    "scope_to_company",
    "str_enum",
    "utcnow",
]

# Concrete models are imported here so Alembic autogenerate (which imports
# app.models) sees every table on Base.metadata.
