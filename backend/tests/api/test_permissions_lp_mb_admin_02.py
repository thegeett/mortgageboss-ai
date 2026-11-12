"""Permission keys at the HTTP boundary (LP-MB-Admin-02).

The four admin routers moved off `require_role`, `loan.create` on the two file-creation routes, and
`/company/settings`. The real app, with the database bound to the test's rollback session.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.main import app
from app.models import Company, CompanyAuditLog, UserRole
from app.services.loan_files import create_loan_file
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.user_factory import make_user

API = "/api/v1"
SETTINGS = f"{API}/company/settings"


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _company(db: AsyncSession, settings: dict[str, Any] | None = None) -> Company:
    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:8]}", settings=settings or {})
    db.add(company)
    await db.flush()
    return company


async def _headers(db: AsyncSession, company: Company, *roles: UserRole) -> dict[str, str]:
    user = make_user(
        company_id=company.id,
        email=f"u-{uuid4().hex[:8]}@acme.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name="T",
        last_name="U",
        roles=roles,
    )
    db.add(user)
    await db.flush()
    # The request loads the user and company itself, as in production.
    db.expunge_all()
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


# --------------------------------------------------------------------------- #
# The four routers that moved off require_role(ADMIN)
# --------------------------------------------------------------------------- #


async def _lenders(
    db: AsyncSession, client: AsyncClient, h: dict[str, str], company: Company
) -> int:
    resp = await client.post(f"{API}/lenders", json={"name": f"L {uuid4().hex[:6]}"}, headers=h)
    return resp.status_code


async def _overlays(
    db: AsyncSession, client: AsyncClient, h: dict[str, str], company: Company
) -> int:
    return (await client.get(f"{API}/admin/lenders", headers=h)).status_code


async def _mail(db: AsyncSession, client: AsyncClient, h: dict[str, str], company: Company) -> int:
    # No connection exists, so an admin gets past the gate to a 404: creating one (Route B) is
    # superseded (LP-1011), and the gate is what this test is about.
    return (await client.delete(f"{API}/mailbox-connections/{uuid4()}", headers=h)).status_code


async def _evidence(
    db: AsyncSession, client: AsyncClient, h: dict[str, str], company: Company
) -> int:
    loan_file = await create_loan_file(db, company_id=company.id)
    resp = await client.post(
        f"{API}/loan-files/{loan_file.display_id}/legal-hold",
        json={"reason": "Litigation notice received"},
        headers=h,
    )
    return resp.status_code


_ROUTERS = {
    "lenders.manage": (_lenders, 201),
    "overlays.manage": (_overlays, 200),
    "mail.manage": (_mail, 404),
    "evidence.manage": (_evidence, 200),
}


@pytest.mark.parametrize("key", sorted(_ROUTERS))
@pytest.mark.parametrize(
    ("roles", "allowed"),
    [
        ((UserRole.ADMIN,), True),
        ((UserRole.PROCESSOR, UserRole.ADMIN), True),
        ((UserRole.PROCESSOR,), False),
        ((UserRole.LOAN_OFFICER,), False),
    ],
)
async def test_admin_routers_are_gated_by_their_key(
    client: AsyncClient,
    db_session: AsyncSession,
    key: str,
    roles: tuple[UserRole, ...],
    allowed: bool,
) -> None:
    company = await _company(db_session)
    headers = await _headers(db_session, company, *roles)
    call, admin_status = _ROUTERS[key]

    status = await call(db_session, client, headers, company)

    assert status == (admin_status if allowed else 403)


# --------------------------------------------------------------------------- #
# loan.create: on by default for processors, switched by the company setting
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("role", "setting", "expected"),
    [
        (UserRole.PROCESSOR, None, 201),  # never saved: the default
        (UserRole.PROCESSOR, True, 201),
        (UserRole.PROCESSOR, False, 403),
        (UserRole.LOAN_OFFICER, True, 201),
        (UserRole.LOAN_OFFICER, False, 201),
        (UserRole.ADMIN, False, 201),
    ],
)
async def test_creating_a_loan_file_needs_loan_create(
    client: AsyncClient,
    db_session: AsyncSession,
    role: UserRole,
    setting: bool | None,
    expected: int,
) -> None:
    stored = {} if setting is None else {"processors_can_create_loans": setting}
    company = await _company(db_session, stored)
    headers = await _headers(db_session, company, role)

    resp = await client.post(f"{API}/loan-files", json={}, headers=headers)

    assert resp.status_code == expected
    if expected == 403:
        assert resp.json()["error"]["message"] == "Insufficient permissions"


async def test_the_mismo_import_route_needs_loan_create_too(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Refused at the gate, before the upload is read: the file's content is irrelevant here."""
    company = await _company(db_session, {"processors_can_create_loans": False})
    headers = await _headers(db_session, company, UserRole.PROCESSOR)

    resp = await client.post(
        f"{API}/loan-files/import-mismo",
        files={"file": ("loan.xml", b"<MESSAGE/>", "application/xml")},
        headers=headers,
    )

    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# /company/settings
# --------------------------------------------------------------------------- #


async def test_get_settings_returns_the_defaults(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company = await _company(db_session)
    headers = await _headers(db_session, company, UserRole.ADMIN)

    resp = await client.get(SETTINGS, headers=headers)

    assert resp.status_code == 200
    assert resp.json() == {
        "processors_can_create_loans": True,
        "processors_can_invite_borrowers": True,
        "restrict_loans_to_team": False,
    }


async def test_patch_changes_one_setting_audits_it_and_keeps_unknown_keys(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company = await _company(db_session, {"some_future_flag": "kept"})
    company_id = company.id
    headers = await _headers(db_session, company, UserRole.ADMIN)

    resp = await client.patch(
        SETTINGS, json={"processors_can_create_loans": False}, headers=headers
    )

    assert resp.status_code == 200
    assert resp.json()["processors_can_create_loans"] is False
    assert resp.json()["processors_can_invite_borrowers"] is True
    db_session.expunge_all()
    stored = await db_session.scalar(select(Company.settings).where(Company.id == company_id))
    assert stored is not None
    assert stored["some_future_flag"] == "kept"
    assert stored["processors_can_create_loans"] is False
    entries = list(
        await db_session.scalars(
            select(CompanyAuditLog).where(CompanyAuditLog.company_id == company_id)
        )
    )
    assert len(entries) == 1
    assert entries[0].action == "company_settings_changed"
    assert entries[0].target_type == "company"
    assert entries[0].detail == {
        "changes": [{"field": "processors_can_create_loans", "from": True, "to": False}]
    }


async def test_patch_that_changes_nothing_writes_no_audit_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company = await _company(db_session)
    company_id = company.id
    headers = await _headers(db_session, company, UserRole.ADMIN)

    resp = await client.patch(SETTINGS, json={"restrict_loans_to_team": False}, headers=headers)

    assert resp.status_code == 200
    count = await db_session.scalar(
        select(CompanyAuditLog.id).where(CompanyAuditLog.company_id == company_id)
    )
    assert count is None


async def test_the_setting_takes_effect_on_the_next_request(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """An admin turns `processors_can_create_loans` off and a processor is refused straight away."""
    company = await _company(db_session)
    admin = await _headers(db_session, company, UserRole.ADMIN)
    processor = await _headers(db_session, company, UserRole.PROCESSOR)

    await client.patch(SETTINGS, json={"processors_can_create_loans": False}, headers=admin)
    resp = await client.post(f"{API}/loan-files", json={}, headers=processor)

    assert resp.status_code == 403


@pytest.mark.parametrize("role", [UserRole.PROCESSOR, UserRole.LOAN_OFFICER])
async def test_settings_are_refused_to_non_admins(
    client: AsyncClient, db_session: AsyncSession, role: UserRole
) -> None:
    company = await _company(db_session)
    headers = await _headers(db_session, company, role)

    assert (await client.get(SETTINGS, headers=headers)).status_code == 403
    patched = await client.patch(
        SETTINGS, json={"processors_can_create_loans": False}, headers=headers
    )
    assert patched.status_code == 403


async def test_patch_refuses_an_unknown_field(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company = await _company(db_session)
    headers = await _headers(db_session, company, UserRole.ADMIN)

    resp = await client.patch(SETTINGS, json={"processors_can_fly": True}, headers=headers)

    assert resp.status_code == 422


async def test_patch_refuses_an_explicit_null(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """`null` used to read as "omitted": 200 and nothing changed (review finding 7)."""
    company = await _company(db_session)
    headers = await _headers(db_session, company, UserRole.ADMIN)

    resp = await client.patch(SETTINGS, json={"restrict_loans_to_team": None}, headers=headers)

    assert resp.status_code == 422


async def test_a_bad_stored_setting_does_not_lock_the_company_out(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Review finding 3: a stored `null` used to 500 every request, login and `/auth/me` included."""
    company = await _company(db_session, {"processors_can_create_loans": None})
    headers = await _headers(db_session, company, UserRole.PROCESSOR)

    me = await client.get(f"{API}/auth/me", headers=headers)
    created = await client.post(f"{API}/loan-files", json={}, headers=headers)

    assert me.status_code == 200
    # The bad setting reads as its default (on), so the processor keeps `loan.create`.
    assert "loan.create" in me.json()["permissions"]
    assert created.status_code == 201
