"""Tenant isolation tests (LP-11) — the critical security property.

Proves that ``scope_to_company`` restricts a query to a single company's rows:
a query scoped to Company A never returns Company B's data, and vice versa.
Forgetting to scope a company-owned query is a tenant data leak, so this test
guards the core multi-tenancy guarantee.
"""

from app.models import Company, User, UserRole, only_active, scope_to_company, utcnow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _company_with_users(db_session: AsyncSession, slug: str, emails: list[str]) -> Company:
    company = Company(name=slug.title(), slug=slug)
    db_session.add(company)
    await db_session.flush()
    db_session.add_all(
        [
            User(
                company_id=company.id,
                email=email,
                hashed_password="h",
                first_name="F",
                last_name="L",
                role=UserRole.PROCESSOR,
            )
            for email in emails
        ]
    )
    await db_session.flush()
    return company


async def test_scope_to_company_returns_only_target_company(
    db_session: AsyncSession,
) -> None:
    """A query scoped to A returns only A's users; scoping to B returns only B's."""
    company_a = await _company_with_users(db_session, "alpha", ["a1@alpha.test", "a2@alpha.test"])
    company_b = await _company_with_users(db_session, "bravo", ["b1@bravo.test"])

    # Scope to A — only A's users, never B's.
    stmt_a = scope_to_company(select(User), User, company_a.id)
    emails_a = {u.email for u in (await db_session.scalars(stmt_a)).all()}
    assert emails_a == {"a1@alpha.test", "a2@alpha.test"}
    assert "b1@bravo.test" not in emails_a

    # Scope to B — only B's users, never A's.
    stmt_b = scope_to_company(select(User), User, company_b.id)
    emails_b = {u.email for u in (await db_session.scalars(stmt_b)).all()}
    assert emails_b == {"b1@bravo.test"}
    assert emails_a.isdisjoint(emails_b)

    # Every returned row genuinely belongs to the scoped company.
    rows_a = (await db_session.scalars(stmt_a)).all()
    assert all(u.company_id == company_a.id for u in rows_a)


async def test_scope_composes_with_only_active(db_session: AsyncSession) -> None:
    """scope_to_company composes with only_active: a soft-deleted user in the
    scoped company is excluded, and the other company is never visible."""
    company_a = await _company_with_users(
        db_session, "charlie", ["c1@charlie.test", "c2@charlie.test"]
    )
    await _company_with_users(db_session, "delta", ["d1@delta.test"])

    # Soft-delete one of A's users.
    victim = (await db_session.scalars(select(User).where(User.email == "c2@charlie.test"))).one()
    victim.deleted_at = utcnow()
    await db_session.flush()

    stmt = only_active(scope_to_company(select(User), User, company_a.id), User)
    emails = {u.email for u in (await db_session.scalars(stmt)).all()}
    assert emails == {"c1@charlie.test"}
