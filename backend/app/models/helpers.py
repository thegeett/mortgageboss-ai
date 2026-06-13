"""Query helpers for common model patterns.

Deliberately small: V1 has no generic repository/CRUD abstraction (ADR-040).
Services write explicit queries; these helpers cover the few patterns that
would otherwise be repeated verbatim everywhere.
"""

from typing import Any, Protocol, cast
from uuid import UUID

from sqlalchemy import Select
from sqlalchemy.orm import InstrumentedAttribute

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


class CompanyScoped(Protocol):
    """Structural type for any tenant-owned model that carries a ``company_id``.

    Used only to type :func:`scope_to_company`: a model is acceptable if it has
    a ``company_id`` mapped column. The tenant root (``Company`` itself) has no
    ``company_id`` and so is — correctly — not scopeable.

    The member is declared as a **read-only property** returning the
    class-access type (``InstrumentedAttribute[UUID]``), not a mutable
    ``company_id: Mapped[UUID]`` attribute, on purpose. A mutable protocol
    attribute is matched *invariantly* and the value type seen on an instance is
    ``UUID`` (the mapped descriptor unwraps it), so ``type[CompanyScoped]`` would
    reject every concrete model class — ``User``, ``LoanFile``, … — which is
    exactly what we pass to :func:`scope_to_company`. A read-only property is
    matched covariantly against *class* access, where ``Model.company_id`` is the
    ``InstrumentedAttribute[UUID]`` column expression, so the model classes
    satisfy the protocol while ``Company`` (no ``company_id``) is still correctly
    rejected. We only read ``company_id`` here, so read-only is also honest.
    """

    @property
    def company_id(self) -> InstrumentedAttribute[UUID]: ...


def scope_to_company[SelectT: Select[Any]](
    stmt: SelectT, model: type[CompanyScoped], company_id: UUID
) -> SelectT:
    """Restrict a query to a single company's records (tenant isolation).

    Every query that touches company-owned data MUST be scoped to the current
    user's company. This helper centralizes that filter so the rule has one
    obvious, greppable name. It composes with :func:`only_active`::

        stmt = select(User)
        stmt = scope_to_company(stmt, User, current_user.company_id)
        stmt = only_active(stmt, User)

    Forgetting to scope a company-owned query is a tenant data leak — see the
    multi-tenancy section of ``docs/database.md`` and ADR-041/ADR-043.
    """
    # Accessing the property on the protocol *type* loses the column-expression
    # typing (mypy can't see it as InstrumentedAttribute through the property),
    # so name what it genuinely is at class access before building the filter.
    company_column = cast("InstrumentedAttribute[UUID]", model.company_id)
    return stmt.where(company_column == company_id)
