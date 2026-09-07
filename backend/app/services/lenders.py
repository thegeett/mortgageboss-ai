"""Lender service — company-scoped reads (LP-32) and writes (LP-813).

V1 only needed to list a company's lenders for the intake dropdown. LP-813 adds the writes, because
there was **no create or update path for a lender anywhere in the product**: every lender in every
environment came from the seed script. That is not merely a gap in admin convenience — `Lender`
carries `contact_email`, which is one of the three sources LP-805 seeds participants from, so the
lender side of the allowlist could never be populated and an underwriter's reply could never route.

Like every company-owned access, scoped via :func:`scope_to_company`, excluding soft-deleted rows.
No pagination — a company has few lenders.
"""

import re
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.helpers import only_active, scope_to_company
from app.models.lender import Lender

#: A slug is a URL-safe identity, unique per company (ADR-045). Derived from the name when the
#: caller does not supply one, because an admin typing "UWM" should not have to know what a slug is.
_SLUG_SAFE = re.compile(r"[^a-z0-9]+")


class LenderError(Exception):
    """The lender cannot be written as asked. Always names the rule that stopped it."""


def slugify(name: str) -> str:
    """A lender name as a slug. Empty when the name has nothing slug-able in it."""
    return _SLUG_SAFE.sub("-", name.strip().lower()).strip("-")


async def list_lenders(db: AsyncSession, *, company_id: UUID) -> list[Lender]:
    """The company's active lenders, ordered by name (empty list if none)."""
    stmt = select(Lender)
    stmt = scope_to_company(stmt, Lender, company_id)
    stmt = only_active(stmt, Lender)
    stmt = stmt.order_by(Lender.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_scoped_lender(
    db: AsyncSession, *, lender_id: UUID, company_id: UUID
) -> Lender | None:
    """One lender, only if this company owns it. None otherwise — never "not found" vs "not yours"."""
    stmt = select(Lender).where(Lender.id == lender_id)
    stmt = scope_to_company(stmt, Lender, company_id)
    return (await db.execute(only_active(stmt, Lender))).scalar_one_or_none()


async def _slug_taken(
    db: AsyncSession, *, company_id: UUID, slug: str, exclude: UUID | None
) -> bool:
    """Whether this company already has an ACTIVE lender with this slug.

    Excludes soft-deleted rows deliberately, and the composite unique constraint does NOT — so a
    company that soft-deletes "uwm" and adds it again gets a clear message from here rather than an
    IntegrityError from Postgres. That asymmetry is real and is the reason this check exists rather
    than a try/except around the flush.
    """
    stmt = select(Lender.id).where(func.lower(Lender.slug) == slug)
    stmt = scope_to_company(stmt, Lender, company_id)
    if exclude is not None:
        stmt = stmt.where(Lender.id != exclude)
    return (await db.scalar(only_active(stmt, Lender))) is not None


async def create_lender(
    db: AsyncSession,
    *,
    company_id: UUID,
    name: str,
    slug: str | None = None,
    supported_programs: list[str] | None = None,
    contact_email: str | None = None,
    contact_phone: str | None = None,
    portal_url: str | None = None,
    notes: str | None = None,
) -> Lender:
    """Add a lender to a company. ``flush`` only; the caller commits."""
    resolved = (slug or slugify(name)).strip().lower()
    if not resolved:
        raise LenderError("This name cannot be turned into an identifier. Give the lender a slug.")
    if await _slug_taken(db, company_id=company_id, slug=resolved, exclude=None):
        raise LenderError(f"This company already has a lender with the identifier {resolved!r}.")

    lender = Lender(
        company_id=company_id,
        name=name.strip(),
        slug=resolved,
        supported_programs=supported_programs or [],
        contact_email=contact_email,
        contact_phone=contact_phone,
        portal_url=portal_url,
        notes=notes,
        is_active=True,
    )
    db.add(lender)
    await db.flush()
    return lender


async def update_lender(db: AsyncSession, *, lender: Lender, fields: dict[str, object]) -> Lender:
    """Apply a partial update. Only keys present in ``fields`` are written.

    `company_id`, `id` and the overlay JSON are not writable here: ownership is not an editable
    field, and overlays have their own audited admin path (LP-87) that records a change reason.
    """
    if "slug" in fields:
        candidate = str(fields["slug"] or "").strip().lower()
        if not candidate:
            raise LenderError("A lender needs an identifier.")
        if await _slug_taken(db, company_id=lender.company_id, slug=candidate, exclude=lender.id):
            raise LenderError(
                f"This company already has a lender with the identifier {candidate!r}."
            )
        fields = {**fields, "slug": candidate}

    for field, value in fields.items():
        setattr(lender, field, value)
    await db.flush()
    return lender
