"""Lender service — company-scoped reads (LP-32).

V1 only needs to list a company's lenders for the intake dropdown. Like every
company-owned read, it is scoped via :func:`scope_to_company` and excludes
soft-deleted rows. No pagination — a company has few lenders.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.helpers import only_active, scope_to_company
from app.models.lender import Lender


async def list_lenders(db: AsyncSession, *, company_id: UUID) -> list[Lender]:
    """The company's active lenders, ordered by name (empty list if none)."""
    stmt = select(Lender)
    stmt = scope_to_company(stmt, Lender, company_id)
    stmt = only_active(stmt, Lender)
    stmt = stmt.order_by(Lender.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())
