"""LP-813 at the layer a caller reaches — the admin gate, and the assignment.

The service tests cover the assignment rules. These cover two things only true here:

* **Reads stay open and writes are admin-only, on one prefix.** The gate is declared per route
  rather than on the router, because gating the router would have taken the existing
  processor-facing `GET /lenders` with it and broken the intake form. A per-route gate is easy to
  forget on the next route added, so every write has a test that a processor is refused.
* **Assigning is NOT admin-gated.** Configuring which lenders exist is administration; deciding who
  is handling this file is the processor's own work, and gating it would make every reassignment
  wait on somebody else.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest_asyncio
from app.core.database import get_db
from app.main import app
from app.models import Company, LoanProgram, User, UserRole
from app.models.lender import Lender
from app.models.lender_contact import LenderContact, LenderContactRole
from app.services.loan_files import create_loan_file
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

LENDERS = "/api/v1/lenders"
FILES = "/api/v1/loan-files"


@pytest_asyncio.fixture
async def db(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    connection = await test_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http_client:
            yield http_client
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _company_with_users(db: AsyncSession, *, slug: str):
    """A company with BOTH an admin and a processor, so the gate can be measured in both directions.

    A fixture with only an admin cannot tell a working gate from an absent one.
    """
    from app.core.jwt import create_access_token

    company = Company(name=slug, slug=f"{slug}-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    tokens = {}
    for role in (UserRole.ADMIN, UserRole.PROCESSOR):
        user = User(
            company_id=company.id,
            email=f"{role.value}-{uuid4().hex[:6]}@{slug}.com",
            hashed_password="x",  # pragma: allowlist secret
            first_name="Pat",
            last_name=role.value.title(),
            role=role,
        )
        db.add(user)
        await db.flush()
        tokens[role.value] = create_access_token(user.id)
    return company, tokens


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _lender(db: AsyncSession, company: Company, slug: str) -> Lender:
    lender = Lender(company_id=company.id, name=slug.upper(), slug=slug, supported_programs=[])
    db.add(lender)
    await db.flush()
    return lender


async def _contact(db: AsyncSession, lender: Lender, *, email: str | None = None) -> LenderContact:
    contact = LenderContact(
        lender_id=lender.id,
        name="Dana Reed",
        email=email or f"{uuid4().hex[:8]}@lender.example.com",
        role=LenderContactRole.UNDERWRITER,
    )
    db.add(contact)
    await db.flush()
    return contact


# --------------------------------------------------------------------------------------------- #
# The gate, in both directions
# --------------------------------------------------------------------------------------------- #
async def test_an_admin_can_create_a_lender(client: AsyncClient, db: AsyncSession) -> None:
    """THE FIRST WAY TO CREATE ONE. Until LP-813 every lender came from the seed script, which is
    why `lenders.contact_email` — one of LP-805's three participant sources — was NULL on any real
    installation."""
    _company, tokens = await _company_with_users(db, slug="acme")
    await db.commit()

    resp = await client.post(
        LENDERS,
        json={"name": "United Wholesale", "supported_programs": ["conventional"]},
        headers=_auth(tokens["admin"]),
    )

    assert resp.status_code == 201
    assert resp.json()["slug"] == "united-wholesale"


async def test_a_processor_cannot_create_a_lender(client: AsyncClient, db: AsyncSession) -> None:
    _company, tokens = await _company_with_users(db, slug="acme")
    await db.commit()

    resp = await client.post(
        LENDERS, json={"name": "United Wholesale"}, headers=_auth(tokens["processor"])
    )

    assert resp.status_code == 403


async def test_a_processor_can_still_list_lenders(client: AsyncClient, db: AsyncSession) -> None:
    """THE REASON THE GATE IS PER ROUTE. On the router it would take this with it, and the intake
    form's lender dropdown would 403 for every processor."""
    company, tokens = await _company_with_users(db, slug="acme")
    await _lender(db, company, "uwm")
    await db.commit()

    resp = await client.get(LENDERS, headers=_auth(tokens["processor"]))

    assert resp.status_code == 200
    assert [row["name"] for row in resp.json()] == ["UWM"]


async def test_a_processor_cannot_add_a_contact(client: AsyncClient, db: AsyncSession) -> None:
    company, tokens = await _company_with_users(db, slug="acme")
    lender = await _lender(db, company, "uwm")
    await db.commit()

    resp = await client.post(
        f"{LENDERS}/{lender.id}/contacts",
        json={"name": "Dana Reed", "email": "dana@uwm.example.com"},
        headers=_auth(tokens["processor"]),
    )

    assert resp.status_code == 403


async def test_a_processor_can_read_contacts(client: AsyncClient, db: AsyncSession) -> None:
    """They are who a file gets assigned to; a processor who cannot see them cannot assign one."""
    company, tokens = await _company_with_users(db, slug="acme")
    lender = await _lender(db, company, "uwm")
    await _contact(db, lender)
    await db.commit()

    resp = await client.get(f"{LENDERS}/{lender.id}/contacts", headers=_auth(tokens["processor"]))

    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_a_processor_cannot_update_or_delete_a_contact(
    client: AsyncClient, db: AsyncSession
) -> None:
    company, tokens = await _company_with_users(db, slug="acme")
    contact = await _contact(db, await _lender(db, company, "uwm"))
    await db.commit()

    patched = await client.patch(
        f"{LENDERS}/contacts/{contact.id}",
        json={"name": "Someone Else"},
        headers=_auth(tokens["processor"]),
    )
    deleted = await client.delete(
        f"{LENDERS}/contacts/{contact.id}", headers=_auth(tokens["processor"])
    )

    assert patched.status_code == 403
    assert deleted.status_code == 403


async def test_a_processor_cannot_update_a_lender(client: AsyncClient, db: AsyncSession) -> None:
    company, tokens = await _company_with_users(db, slug="acme")
    lender = await _lender(db, company, "uwm")
    await db.commit()

    resp = await client.patch(
        f"{LENDERS}/{lender.id}",
        json={"contact_email": "ops@uwm.example.com"},
        headers=_auth(tokens["processor"]),
    )

    assert resp.status_code == 403


# --------------------------------------------------------------------------------------------- #
# Tenancy, at the layer where the id is typed
# --------------------------------------------------------------------------------------------- #
async def test_another_companys_lender_is_a_404(client: AsyncClient, db: AsyncSession) -> None:
    theirs, _their_tokens = await _company_with_users(db, slug="theirs")
    _mine, my_tokens = await _company_with_users(db, slug="mine")
    their_lender = await _lender(db, theirs, "uwm")
    await db.commit()

    read = await client.get(f"{LENDERS}/{their_lender.id}", headers=_auth(my_tokens["processor"]))
    contacts = await client.get(
        f"{LENDERS}/{their_lender.id}/contacts", headers=_auth(my_tokens["processor"])
    )
    patched = await client.patch(
        f"{LENDERS}/{their_lender.id}",
        json={"name": "Renamed"},
        headers=_auth(my_tokens["admin"]),
    )

    assert read.status_code == contacts.status_code == patched.status_code == 404


async def test_another_companys_contact_cannot_be_edited(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A REAL contact at a real other company's lender — an id that resolves to something."""
    theirs, _their_tokens = await _company_with_users(db, slug="edit-theirs")
    _mine, my_tokens = await _company_with_users(db, slug="edit-mine")
    their_contact = await _contact(db, await _lender(db, theirs, "uwm"))
    await db.commit()

    resp = await client.patch(
        f"{LENDERS}/contacts/{their_contact.id}",
        json={"name": "Renamed"},
        headers=_auth(my_tokens["admin"]),
    )

    assert resp.status_code == 404


async def test_a_duplicate_email_at_one_lender_is_refused(
    client: AsyncClient, db: AsyncSession
) -> None:
    company, tokens = await _company_with_users(db, slug="dupe")
    lender = await _lender(db, company, "uwm")
    await _contact(db, lender, email="dana@uwm.example.com")
    await db.commit()

    resp = await client.post(
        f"{LENDERS}/{lender.id}/contacts",
        json={"name": "Dana Again", "email": "DANA@uwm.example.com"},
        headers=_auth(tokens["admin"]),
    )

    assert resp.status_code == 409


async def test_a_duplicate_slug_is_refused_with_a_sentence(
    client: AsyncClient, db: AsyncSession
) -> None:
    company, tokens = await _company_with_users(db, slug="slug")
    await _lender(db, company, "uwm")
    await db.commit()

    resp = await client.post(LENDERS, json={"name": "UWM"}, headers=_auth(tokens["admin"]))

    assert resp.status_code == 409
    assert "uwm" in resp.json()["error"]["message"]


# --------------------------------------------------------------------------------------------- #
# The assignment
# --------------------------------------------------------------------------------------------- #
async def test_a_processor_assigns_the_underwriter(client: AsyncClient, db: AsyncSession) -> None:
    """NOT ADMIN-GATED. Deciding who is handling this file is the processor's own work."""
    company, tokens = await _company_with_users(db, slug="assign")
    lender = await _lender(db, company, "uwm")
    contact = await _contact(db, lender)
    loan_file = await create_loan_file(
        db, company_id=company.id, lender_id=lender.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await db.commit()

    resp = await client.put(
        f"{FILES}/{loan_file.display_id}/underwriter",
        json={"contact_id": str(contact.id)},
        headers=_auth(tokens["processor"]),
    )

    assert resp.status_code == 200
    assert resp.json()["id"] == str(contact.id)


async def test_assigning_makes_them_a_participant(client: AsyncClient, db: AsyncSession) -> None:
    """WITHOUT THIS THE ASSIGNMENT IS DECORATION — asserted through the endpoint, because the
    re-seed happens there and a service test would not notice it missing."""
    from app.models.loan_file_participant import LoanFileParticipant, ParticipantRole
    from sqlalchemy import select

    company, tokens = await _company_with_users(db, slug="seeded")
    lender = await _lender(db, company, "uwm")
    contact = await _contact(db, lender, email="dana@uwm.example.com")
    loan_file = await create_loan_file(
        db, company_id=company.id, lender_id=lender.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await db.commit()

    await client.put(
        f"{FILES}/{loan_file.display_id}/underwriter",
        json={"contact_id": str(contact.id)},
        headers=_auth(tokens["processor"]),
    )

    rows = (
        (
            await db.execute(
                select(LoanFileParticipant).where(
                    LoanFileParticipant.loan_file_id == loan_file.id,
                    LoanFileParticipant.role == ParticipantRole.UNDERWRITER,
                )
            )
        )
        .scalars()
        .all()
    )
    assert [row.email for row in rows] == ["dana@uwm.example.com"]


async def test_another_companys_contact_is_a_409_not_an_assignment(
    client: AsyncClient, db: AsyncSession
) -> None:
    theirs, _their_tokens = await _company_with_users(db, slug="a-theirs")
    mine, my_tokens = await _company_with_users(db, slug="a-mine")
    their_contact = await _contact(db, await _lender(db, theirs, "uwm"))
    my_lender = await _lender(db, mine, "uwm")
    loan_file = await create_loan_file(
        db, company_id=mine.id, lender_id=my_lender.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await db.commit()

    resp = await client.put(
        f"{FILES}/{loan_file.display_id}/underwriter",
        json={"contact_id": str(their_contact.id)},
        headers=_auth(my_tokens["processor"]),
    )

    assert resp.status_code == 409
    await db.refresh(loan_file)
    assert loan_file.underwriter_contact_id is None


async def test_clearing_returns_null(client: AsyncClient, db: AsyncSession) -> None:
    company, tokens = await _company_with_users(db, slug="clear")
    lender = await _lender(db, company, "uwm")
    contact = await _contact(db, lender)
    loan_file = await create_loan_file(
        db, company_id=company.id, lender_id=lender.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await db.commit()
    await client.put(
        f"{FILES}/{loan_file.display_id}/underwriter",
        json={"contact_id": str(contact.id)},
        headers=_auth(tokens["processor"]),
    )

    resp = await client.put(
        f"{FILES}/{loan_file.display_id}/underwriter",
        json={"contact_id": None},
        headers=_auth(tokens["processor"]),
    )

    assert resp.status_code == 200
    assert resp.json() is None


# --------------------------------------------------------------------------------------------- #
# The gate is per route, so something has to notice a new route without it (review finding)
# --------------------------------------------------------------------------------------------- #
#: Mutating routes that are DELIBERATELY not admin-gated, each with the reason it is exempt.
#:
#: Named individually rather than pattern-matched: an exemption should cost somebody a line in this
#: file and a sentence explaining it, which is the only thing that makes the default meaningful.
_UNGATED_BY_DESIGN = {
    (
        "PUT",
        "/loan-files/{file_identifier}/underwriter",
    ): "configuring which lenders exist is administration; deciding who is handling THIS file is "
    "the processor's own work, and gating it would make every reassignment wait on somebody else",
}


def test_every_mutating_lender_route_is_admin_gated() -> None:
    """LP-813 put the admin gate on each route rather than the router, and that was right — on the
    router it would have taken the processor-facing `GET /lenders` with it and 403'd the intake
    form's lender dropdown.

    The cost of per-route is that a NEW write route added without the gate is silently open, and
    every existing refusal test passes because they test the routes that exist. This walks the
    routers instead, so the failure arrives when the route is added rather than when someone
    notices.

    Detected by dependency IDENTITY — the same `_ADMIN` object every gated route shares — rather
    than by reading source or matching a name, so a route that merely mentions `require_role` in a
    docstring does not count as gated.
    """
    from app.api.lenders import _ADMIN, file_router, router

    admin_dependency = _ADMIN.dependency
    ungated: list[str] = []

    for route in [*router.routes, *file_router.routes]:
        methods = getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}
        mutating = methods - {"GET"}
        if not mutating:
            continue
        gated = any(
            dependency.call is admin_dependency for dependency in route.dependant.dependencies
        )
        for method in sorted(mutating):
            if gated or (method, route.path) in _UNGATED_BY_DESIGN:
                continue
            ungated.append(f"{method} {route.path}")

    assert not ungated, (
        "these mutating routes carry no admin gate. Either add `_ADMIN`, or add them to "
        f"_UNGATED_BY_DESIGN with the reason: {ungated}"
    )


def test_the_exemption_list_describes_routes_that_exist() -> None:
    """A stale exemption is worse than none: it reads as a considered decision about a route that
    is no longer there, and it would silently cover a future route that reused the path."""
    from app.api.lenders import file_router, router

    live = {
        (method, route.path)
        for route in [*router.routes, *file_router.routes]
        for method in getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}
    }
    stale = [entry for entry in _UNGATED_BY_DESIGN if entry not in live]

    assert not stale, f"exemptions for routes that no longer exist: {stale}"


def test_the_gate_detection_would_notice_an_ungated_route() -> None:
    """The positive control for the two tests above.

    Both are absence assertions over a set the code supplies, so they would pass just as happily
    against a detector that found nothing at all. This builds a route with no gate and asserts the
    detection sees it — the same shape as an unrouted fixture that cannot reach the dangerous case.
    """
    from app.api.lenders import _ADMIN
    from fastapi import APIRouter

    probe = APIRouter()

    @probe.post("/probe")
    async def _probe() -> None:  # pragma: no cover - never called
        return None

    (route,) = probe.routes
    gated = any(dependency.call is _ADMIN.dependency for dependency in route.dependant.dependencies)
    assert gated is False
