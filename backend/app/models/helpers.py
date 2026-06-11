"""Query helpers for common model patterns.

Deliberately small: V1 has no generic repository/CRUD abstraction (ADR-040).
Services write explicit queries; these helpers cover the few patterns that
would otherwise be repeated verbatim everywhere.
"""

from typing import Any

from sqlalchemy import Select

from app.models.base import SoftDeleteMixin


# The statement type is a PEP 695 type parameter bound to Select, so the exact
# statement type flows through unchanged: Select.where() returns Self, so
# only_active(select(Company)) stays a Select of Company rows for the caller
# and downstream type-checking.
def only_active[SelectT: Select[Any]](stmt: SelectT, model: type[SoftDeleteMixin]) -> SelectT:
    """Add a filter excluding soft-deleted records (``deleted_at IS NULL``).

    Soft-delete filtering is explicit, not global (see SoftDeleteMixin), so
    callers opt in per query::

        stmt = select(Company)
        stmt = only_active(stmt, Company)
        # stmt now excludes rows where deleted_at IS NOT NULL
    """
    return stmt.where(model.deleted_at.is_(None))
