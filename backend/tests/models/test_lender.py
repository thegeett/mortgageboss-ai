"""Tests for the Lender model (LP-12).

Covers create/read with JSON defaults, the **per-company unique slug**
(composite uniqueness — the key multi-tenant pattern), JSON round-trips for
``supported_programs`` and ``lender_overlays``, soft-delete filtering, the
``Company.lenders`` relationship, and tenant isolation via ``scope_to_company``.
Uses the transaction-rollback ``db_session`` fixture from LP-10.
"""

import pytest
from app.models import (
    Company,
    Lender,
    LoanProgram,
    only_active,
    scope_to_company,
    utcnow,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def _make_company(db_session: AsyncSession, slug: str) -> Company:
    company = Company(name=slug.title(), slug=slug)
    db_session.add(company)
    await db_session.flush()
    return company


async def test_create_lender_with_defaults(db_session: AsyncSession) -> None:
    """A lender can be created under a company; all fields and JSON defaults
    are correct."""
    company = await _make_company(db_session, "acme")
    lender = Lender(company_id=company.id, name="United Wholesale Mortgage", slug="uwm")
    db_session.add(lender)
    await db_session.flush()
    await db_session.refresh(lender)

    assert lender.id is not None
    assert lender.company_id == company.id
    assert lender.name == "United Wholesale Mortgage"
    assert lender.slug == "uwm"
    # Optional contact fields default to None.
    assert lender.contact_email is None
    assert lender.portal_url is None
    assert lender.contact_phone is None
    assert lender.notes is None
    # JSON defaults: empty dict / empty list.
    assert lender.lender_overlays == {}
    assert lender.supported_programs == []
    # is_active defaults True; soft-delete column starts null.
    assert lender.is_active is True
    assert lender.deleted_at is None


async def test_contact_fields_persist(db_session: AsyncSession) -> None:
    """Contact fields (for direct underwriter communication) round-trip."""
    company = await _make_company(db_session, "acme")
    lender = Lender(
        company_id=company.id,
        name="Sun West Mortgage",
        slug="sun-west",
        contact_email="uw@sunwest.test",
        portal_url="https://portal.sunwest.test",
        contact_phone="555-0100",
        notes="Direct underwriter: ask for the senior desk.",
    )
    db_session.add(lender)
    await db_session.flush()
    await db_session.refresh(lender)

    assert lender.contact_email == "uw@sunwest.test"
    assert lender.portal_url == "https://portal.sunwest.test"
    assert lender.contact_phone == "555-0100"
    assert lender.notes == "Direct underwriter: ask for the senior desk."


async def test_slug_unique_per_company(db_session: AsyncSession) -> None:
    """The same slug is allowed in different companies but not twice in one."""
    company_a = await _make_company(db_session, "company-a")
    company_b = await _make_company(db_session, "company-b")

    # Same slug "uwm" in company A — succeeds.
    db_session.add(Lender(company_id=company_a.id, name="UWM", slug="uwm"))
    await db_session.flush()

    # Same slug "uwm" in company B — succeeds (different company).
    db_session.add(Lender(company_id=company_b.id, name="UWM", slug="uwm"))
    await db_session.flush()

    # Second "uwm" in company A — fails the composite unique constraint.
    # Contain the expected failure in a SAVEPOINT so it doesn't poison the outer
    # (rolled-back) test transaction.
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(Lender(company_id=company_a.id, name="UWM Again", slug="uwm"))
            await db_session.flush()


async def test_supported_programs_roundtrips_list(db_session: AsyncSession) -> None:
    """supported_programs stores and returns a JSON list of program values."""
    company = await _make_company(db_session, "acme")
    lender = Lender(
        company_id=company.id,
        name="UWM",
        slug="uwm",
        supported_programs=[LoanProgram.CONVENTIONAL, LoanProgram.FHA],
    )
    db_session.add(lender)
    await db_session.flush()
    await db_session.refresh(lender)

    # StrEnum members serialize to their string values in JSON.
    assert lender.supported_programs == ["conventional", "fha"]


async def test_lender_overlays_stores_structured_json(db_session: AsyncSession) -> None:
    """lender_overlays defaults to {} and can hold structured JSON."""
    company = await _make_company(db_session, "acme")
    lender = Lender(
        company_id=company.id,
        name="UWM",
        slug="uwm",
        lender_overlays={"reserves_months": 2, "min_fico": 640},
    )
    db_session.add(lender)
    await db_session.flush()
    await db_session.refresh(lender)

    assert lender.lender_overlays == {"reserves_months": 2, "min_fico": 640}


async def test_soft_delete_and_only_active(db_session: AsyncSession) -> None:
    """Soft delete sets deleted_at; only_active() filters such rows out."""
    company = await _make_company(db_session, "acme")
    live = Lender(company_id=company.id, name="UWM", slug="uwm")
    gone = Lender(company_id=company.id, name="Sun West", slug="sun-west")
    db_session.add_all([live, gone])
    await db_session.flush()

    gone.deleted_at = utcnow()
    await db_session.flush()
    assert gone.is_deleted is True

    stmt = only_active(select(Lender), Lender)
    slugs = {lender.slug for lender in (await db_session.scalars(stmt)).all()}
    assert slugs == {"uwm"}


async def test_company_lenders_relationship_loads(db_session: AsyncSession) -> None:
    """Company.lenders loads all of the company's lenders (eager for async)."""
    company = await _make_company(db_session, "acme")
    db_session.add_all(
        [
            Lender(company_id=company.id, name="UWM", slug="uwm"),
            Lender(company_id=company.id, name="Sun West", slug="sun-west"),
        ]
    )
    await db_session.flush()

    stmt = select(Company).where(Company.id == company.id).options(selectinload(Company.lenders))
    loaded = (await db_session.scalars(stmt)).one()
    assert {lender.slug for lender in loaded.lenders} == {"uwm", "sun-west"}


async def test_scope_to_company_isolates_lenders(db_session: AsyncSession) -> None:
    """scope_to_company returns only the target company's lenders (isolation)."""
    company_a = await _make_company(db_session, "company-a")
    company_b = await _make_company(db_session, "company-b")
    db_session.add_all(
        [
            Lender(company_id=company_a.id, name="UWM", slug="uwm"),
            Lender(company_id=company_a.id, name="Sun West", slug="sun-west"),
            Lender(company_id=company_b.id, name="UWM", slug="uwm"),
        ]
    )
    await db_session.flush()

    stmt_a = scope_to_company(select(Lender), Lender, company_a.id)
    rows_a = (await db_session.scalars(stmt_a)).all()
    assert {lender.slug for lender in rows_a} == {"uwm", "sun-west"}
    assert all(lender.company_id == company_a.id for lender in rows_a)

    stmt_b = scope_to_company(select(Lender), Lender, company_b.id)
    rows_b = (await db_session.scalars(stmt_b)).all()
    assert {lender.slug for lender in rows_b} == {"uwm"}
    assert all(lender.company_id == company_b.id for lender in rows_b)
