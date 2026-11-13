"""People: the users API, its rules, and the audit log (LP-MB-Admin-03).

The real app, with the database bound to the test's rollback session. The company has an owner (an
admin), a second admin who acts in most tests (so the owner rules are tested from outside), a
processor and a loan officer.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.api.auth import REFRESH_COOKIE_PATH, REFRESH_TOKEN_COOKIE
from app.core.database import get_db
from app.core.jwt import create_access_token, create_refresh_token
from app.core.security import hash_password
from app.main import app
from app.models import Company, CompanyAuditLog, User, UserRole
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.user_factory import make_user

API = "/api/v1"
PASSWORD = "correct horse battery staple"  # pragma: allowlist secret
A, P, LO = UserRole.ADMIN, UserRole.PROCESSOR, UserRole.LOAN_OFFICER


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


@dataclass
class Shop:
    company_id: UUID
    owner: UUID
    admin: UUID
    processor: UUID
    loan_officer: UUID
    hashes: list[str]


async def _person(db: AsyncSession, company: Company, first: str, *roles: UserRole) -> User:
    user = make_user(
        company_id=company.id,
        email=f"{first.lower()}-{uuid4().hex[:6]}@acme.com",
        hashed_password=hash_password(PASSWORD),
        first_name=first,
        last_name="Test",
        roles=roles,
    )
    db.add(user)
    await db.flush()
    return user


async def _shop(db: AsyncSession) -> Shop:
    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    owner = await _person(db, company, "Olive", A, P)
    company.owner_user_id = owner.id
    admin = await _person(db, company, "Adam", A)
    processor = await _person(db, company, "Pat", P)
    loan_officer = await _person(db, company, "Lou", LO)
    await db.flush()
    shop = Shop(
        company.id,
        owner.id,
        admin.id,
        processor.id,
        loan_officer.id,
        [u.hashed_password for u in (owner, admin, processor, loan_officer)],
    )
    db.expunge_all()  # each request loads what it needs, as in production
    return shop


def _as(user_id: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def _audit_rows(db: AsyncSession, company_id: UUID) -> list[CompanyAuditLog]:
    db.expunge_all()
    rows = await db.scalars(
        select(CompanyAuditLog)
        .where(CompanyAuditLog.company_id == company_id)
        .order_by(CompanyAuditLog.created_at)
    )
    return list(rows)


async def _roles_of(db: AsyncSession, user_id: UUID) -> list[str]:
    rows = await db.scalars(
        text("SELECT role FROM user_roles WHERE user_id = :id ORDER BY role"), {"id": user_id}
    )
    return list(rows)


# --------------------------------------------------------------------------- #
# Who: users.manage, and nobody else
# --------------------------------------------------------------------------- #


def _calls(target: UUID) -> list[tuple[str, str, dict[str, Any] | None]]:
    return [
        ("GET", f"{API}/users", None),
        ("GET", f"{API}/users/{target}", None),
        ("PATCH", f"{API}/users/{target}", {"title": "X"}),
        ("PUT", f"{API}/users/{target}/roles", {"roles": ["processor"]}),
        ("POST", f"{API}/users/{target}/deactivate", None),
        ("POST", f"{API}/users/{target}/reactivate", None),
    ]


@pytest.mark.parametrize("who", ["processor", "loan_officer"])
async def test_every_endpoint_refuses_a_non_admin(
    client: AsyncClient, db_session: AsyncSession, who: str
) -> None:
    shop = await _shop(db_session)
    for method, url, body in _calls(shop.admin):
        resp = await client.request(method, url, json=body, headers=_as(getattr(shop, who)))
        assert resp.status_code == 403, (method, url)
    resp = await client.get(f"{API}/audit-log", headers=_as(getattr(shop, who)))
    assert resp.status_code == 403
    assert await _audit_rows(db_session, shop.company_id) == []


async def test_another_companys_user_is_404_everywhere_and_nothing_changes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    mine = await _shop(db_session)
    theirs = await _shop(db_session)

    for method, url, body in _calls(theirs.processor)[1:]:
        resp = await client.request(method, url, json=body, headers=_as(mine.admin))
        assert resp.status_code == 404, (method, url)

    listed = await client.get(f"{API}/users", headers=_as(mine.admin))
    assert theirs.processor not in {UUID(row["id"]) for row in listed.json()}
    stranger = await db_session.get(User, theirs.processor)
    assert stranger is not None
    assert (stranger.is_active, stranger.title) == (True, None)
    assert await _roles_of(db_session, theirs.processor) == ["processor"]
    assert await _audit_rows(db_session, theirs.company_id) == []
    assert await _audit_rows(db_session, mine.company_id) == []


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


async def test_list_shows_everyone_with_roles_owner_and_status(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    await client.post(f"{API}/users/{shop.processor}/deactivate", headers=_as(shop.admin))

    resp = await client.get(f"{API}/users", headers=_as(shop.admin))

    assert resp.status_code == 200
    rows = {UUID(row["id"]): row for row in resp.json()}
    assert set(rows) == {shop.owner, shop.admin, shop.processor, shop.loan_officer}
    assert rows[shop.owner]["roles"] == ["admin", "processor"]
    assert rows[shop.owner]["is_owner"] is True
    assert rows[shop.admin]["is_owner"] is False
    assert rows[shop.processor]["is_active"] is False
    assert rows[shop.loan_officer]["licensed_states"] == []
    assert "hashed_password" not in resp.text


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("status=active", {"owner", "admin", "loan_officer"}),
        ("status=inactive", {"processor"}),
        ("role=admin", {"owner", "admin"}),
        ("role=loan_officer", {"loan_officer"}),
        ("status=active&role=processor", {"owner"}),
    ],
)
async def test_list_filters(
    client: AsyncClient, db_session: AsyncSession, query: str, expected: set[str]
) -> None:
    shop = await _shop(db_session)
    await client.post(f"{API}/users/{shop.processor}/deactivate", headers=_as(shop.admin))

    resp = await client.get(f"{API}/users?{query}", headers=_as(shop.admin))

    assert {UUID(row["id"]) for row in resp.json()} == {getattr(shop, n) for n in expected}


# --------------------------------------------------------------------------- #
# Details
# --------------------------------------------------------------------------- #


async def test_patch_changes_only_what_is_sent_and_audits_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)

    resp = await client.patch(
        f"{API}/users/{shop.loan_officer}",
        json={"title": "Loan Officer", "nmls_id": "123456", "licensed_states": ["PA", "NJ"]},
        headers=_as(shop.admin),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert (body["title"], body["nmls_id"], body["licensed_states"]) == (
        "Loan Officer",
        "123456",
        ["NJ", "PA"],
    )
    assert body["first_name"] == "Lou"  # not sent, not changed
    rows = await _audit_rows(db_session, shop.company_id)
    assert len(rows) == 1
    assert (rows[0].action, rows[0].target_type, rows[0].target_id, rows[0].actor_user_id) == (
        "user_details_changed",
        "user",
        shop.loan_officer,
        shop.admin,
    )
    assert rows[0].detail == {
        "changes": [
            {"field": "licensed_states", "from": [], "to": ["NJ", "PA"]},
            {"field": "nmls_id", "from": None, "to": "123456"},
            {"field": "title", "from": None, "to": "Loan Officer"},
        ]
    }


async def test_a_patch_that_changes_nothing_writes_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)

    resp = await client.patch(
        f"{API}/users/{shop.processor}", json={"first_name": "Pat"}, headers=_as(shop.admin)
    )

    assert resp.status_code == 200
    assert await _audit_rows(db_session, shop.company_id) == []


@pytest.mark.parametrize(
    "body",
    [
        {"licensed_states": ["nj"]},
        {"licensed_states": ["NJ", "NJ"]},
        {"licensed_states": ["ZZ"]},
        {"first_name": None},
        {"first_name": ""},
        {"email": "new@acme.com"},
        {"sees_all_loans": None},
    ],
)
async def test_patch_refuses_bad_input(
    client: AsyncClient, db_session: AsyncSession, body: dict[str, Any]
) -> None:
    shop = await _shop(db_session)
    resp = await client.patch(f"{API}/users/{shop.processor}", json=body, headers=_as(shop.admin))
    assert resp.status_code == 422


async def test_patch_may_clear_an_optional_field(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    await client.patch(
        f"{API}/users/{shop.processor}", json={"phone": "555"}, headers=_as(shop.admin)
    )
    resp = await client.patch(
        f"{API}/users/{shop.processor}", json={"phone": None}, headers=_as(shop.admin)
    )
    assert resp.status_code == 200
    assert resp.json()["phone"] is None


# --------------------------------------------------------------------------- #
# The rules: self, owner, at least one role, admins make admins
# --------------------------------------------------------------------------- #


async def test_self(client: AsyncClient, db_session: AsyncSession) -> None:
    shop = await _shop(db_session)
    me = _as(shop.admin)

    own_roles = await client.put(
        f"{API}/users/{shop.admin}/roles", json={"roles": ["admin", "processor"]}, headers=me
    )
    own_off = await client.post(f"{API}/users/{shop.admin}/deactivate", headers=me)
    own_name = await client.patch(f"{API}/users/{shop.admin}", json={"title": "Boss"}, headers=me)

    assert own_roles.status_code == 409
    assert own_roles.json()["error"]["message"] == "You can't change your own roles"
    assert own_off.status_code == 409
    assert own_off.json()["error"]["message"] == "You can't deactivate yourself"
    assert own_name.status_code == 200
    assert await _roles_of(db_session, shop.admin) == ["admin"]


async def test_the_owner(client: AsyncClient, db_session: AsyncSession) -> None:
    shop = await _shop(db_session)
    other_admin = _as(shop.admin)
    owner_msg = "This is the account owner. Contact MortgageBoss to change their access."

    off = await client.post(f"{API}/users/{shop.owner}/deactivate", headers=other_admin)
    demote = await client.put(
        f"{API}/users/{shop.owner}/roles", json={"roles": ["processor"]}, headers=other_admin
    )
    renamed = await client.patch(
        f"{API}/users/{shop.owner}", json={"title": "Founder"}, headers=other_admin
    )
    other_roles = await client.put(
        f"{API}/users/{shop.owner}/roles",
        json={"roles": ["admin", "loan_officer"]},
        headers=other_admin,
    )
    own_name = await client.patch(
        f"{API}/users/{shop.owner}", json={"first_name": "Liv"}, headers=_as(shop.owner)
    )
    own_roles = await client.put(
        f"{API}/users/{shop.owner}/roles", json={"roles": ["admin"]}, headers=_as(shop.owner)
    )

    assert (off.status_code, off.json()["error"]["message"]) == (409, owner_msg)
    assert (demote.status_code, demote.json()["error"]["message"]) == (409, owner_msg)
    assert renamed.status_code == 200
    assert other_roles.status_code == 200
    assert other_roles.json()["roles"] == ["admin", "loan_officer"]
    assert own_name.status_code == 200
    assert own_roles.status_code == 409
    assert own_roles.json()["error"]["message"] == "You can't change your own roles"
    owner = await db_session.get(User, shop.owner)
    assert owner is not None and owner.is_active is True


async def test_at_least_one_role(client: AsyncClient, db_session: AsyncSession) -> None:
    shop = await _shop(db_session)
    resp = await client.put(
        f"{API}/users/{shop.processor}/roles", json={"roles": []}, headers=_as(shop.admin)
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["message"] == "A person needs at least one role"
    assert await _roles_of(db_session, shop.processor) == ["processor"]


async def test_admins_make_and_unmake_admins(client: AsyncClient, db_session: AsyncSession) -> None:
    shop = await _shop(db_session)

    made = await client.put(
        f"{API}/users/{shop.processor}/roles",
        json={"roles": ["processor", "admin"]},
        headers=_as(shop.admin),
    )
    # The new admin removes ADMIN from the other (non-owner) admin.
    unmade = await client.put(
        f"{API}/users/{shop.admin}/roles",
        json={"roles": ["processor"]},
        headers=_as(shop.processor),
    )

    assert made.status_code == 200
    assert unmade.status_code == 200
    assert await _roles_of(db_session, shop.admin) == ["processor"]
    granted = await db_session.scalar(
        text("SELECT granted_by_user_id FROM user_roles WHERE user_id = :u AND role = 'admin'"),
        {"u": shop.processor},
    )
    assert granted == shop.admin


async def test_a_role_change_audits_both_sorted_sets(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)

    await client.put(
        f"{API}/users/{shop.processor}/roles",
        json={"roles": ["processor", "loan_officer"]},
        headers=_as(shop.admin),
    )
    # The same set again: no change, no row.
    await client.put(
        f"{API}/users/{shop.processor}/roles",
        json={"roles": ["loan_officer", "processor"]},
        headers=_as(shop.admin),
    )

    rows = await _audit_rows(db_session, shop.company_id)
    assert len(rows) == 1
    assert rows[0].action == "user_roles_changed"
    assert rows[0].detail == {
        "changes": [{"field": "roles", "from": ["processor"], "to": ["loan_officer", "processor"]}]
    }


# --------------------------------------------------------------------------- #
# Deactivate and reactivate
# --------------------------------------------------------------------------- #


async def test_deactivation_ends_access_on_the_next_request_and_refresh(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    token = _as(shop.processor)
    assert (await client.get(f"{API}/auth/me", headers=token)).status_code == 200

    off = await client.post(f"{API}/users/{shop.processor}/deactivate", headers=_as(shop.admin))
    me = await client.get(f"{API}/auth/me", headers=token)
    client.cookies.set(
        REFRESH_TOKEN_COOKIE,
        create_refresh_token(shop.processor),
        domain="test",
        path=REFRESH_COOKIE_PATH,
    )
    refreshed = await client.post(f"{API}/auth/refresh")

    assert off.status_code == 200
    assert off.json()["is_active"] is False
    assert me.status_code == 401
    assert refreshed.status_code == 401


async def test_reactivation_restores_access_with_the_same_roles(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    await client.put(
        f"{API}/users/{shop.processor}/roles",
        json={"roles": ["processor", "loan_officer"]},
        headers=_as(shop.admin),
    )
    await client.post(f"{API}/users/{shop.processor}/deactivate", headers=_as(shop.admin))

    back = await client.post(f"{API}/users/{shop.processor}/reactivate", headers=_as(shop.admin))

    assert back.status_code == 200
    assert back.json()["is_active"] is True
    assert back.json()["roles"] == ["loan_officer", "processor"]
    assert (await client.get(f"{API}/auth/me", headers=_as(shop.processor))).status_code == 200
    actions = [row.action for row in await _audit_rows(db_session, shop.company_id)]
    assert actions == ["user_roles_changed", "user_deactivated", "user_reactivated"]


async def test_deactivating_twice_writes_one_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    await client.post(f"{API}/users/{shop.processor}/deactivate", headers=_as(shop.admin))
    again = await client.post(f"{API}/users/{shop.processor}/deactivate", headers=_as(shop.admin))
    assert again.status_code == 200
    rows = await _audit_rows(db_session, shop.company_id)
    assert [row.action for row in rows] == ["user_deactivated"]
    assert rows[0].detail == {"changes": [{"field": "status", "from": "active", "to": "inactive"}]}


# --------------------------------------------------------------------------- #
# The audit log
# --------------------------------------------------------------------------- #


async def _three_changes(client: AsyncClient, shop: Shop) -> None:
    await client.patch(
        f"{API}/users/{shop.processor}", json={"title": "Senior"}, headers=_as(shop.admin)
    )
    await client.put(
        f"{API}/users/{shop.loan_officer}/roles",
        json={"roles": ["loan_officer", "processor"]},
        headers=_as(shop.owner),
    )
    await client.post(f"{API}/users/{shop.processor}/deactivate", headers=_as(shop.admin))


async def test_no_audit_row_holds_a_password_hash(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    await _three_changes(client, shop)
    await client.post(f"{API}/users/{shop.processor}/reactivate", headers=_as(shop.admin))

    rows = await _audit_rows(db_session, shop.company_id)
    assert len(rows) == 4
    for row in rows:
        stored = f"{row.summary} {row.detail}"
        assert "hashed_password" not in stored
        assert "password" not in stored
        assert not any(digest in stored for digest in shop.hashes)


async def test_the_log_reads_newest_first_with_names_and_pages_by_cursor(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    await _three_changes(client, shop)

    first = await client.get(f"{API}/audit-log?limit=2", headers=_as(shop.admin))
    body = first.json()
    second = await client.get(
        f"{API}/audit-log",
        params={"limit": 2, "before": body["next_cursor"]},
        headers=_as(shop.admin),
    )

    assert first.status_code == 200
    assert body["total"] == 3
    assert [item["action"] for item in body["items"]] == ["user_deactivated", "user_roles_changed"]
    newest = body["items"][0]
    assert newest["actor"] == {"id": str(shop.admin), "name": "Adam Test"}
    assert (newest["target_type"], newest["target_name"]) == ("user", "Pat Test")
    assert body["next_cursor"] is not None
    assert [item["action"] for item in second.json()["items"]] == ["user_details_changed"]
    assert second.json()["next_cursor"] is None


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("target_type=user", ["user_deactivated", "user_roles_changed", "user_details_changed"]),
        ("target_type=company", []),
        ("target_id={processor}", ["user_deactivated", "user_details_changed"]),
        ("actor_user_id={owner}", ["user_roles_changed"]),
        ("since=2999-01-01T00:00:00Z", []),
    ],
)
async def test_the_log_filters(
    client: AsyncClient, db_session: AsyncSession, query: str, expected: list[str]
) -> None:
    shop = await _shop(db_session)
    await _three_changes(client, shop)
    url = f"{API}/audit-log?" + query.format(processor=shop.processor, owner=shop.owner)

    resp = await client.get(url, headers=_as(shop.admin))

    assert [item["action"] for item in resp.json()["items"]] == expected


async def test_a_bad_cursor_is_422(client: AsyncClient, db_session: AsyncSession) -> None:
    shop = await _shop(db_session)
    resp = await client.get(f"{API}/audit-log?before=yesterday", headers=_as(shop.admin))
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# last_login_at: a sign-in, not a refresh
# --------------------------------------------------------------------------- #


async def test_last_login_at_is_set_on_login_and_not_by_refresh(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    pat = await db_session.get(User, shop.processor)
    assert pat is not None and pat.last_login_at is None
    email = pat.email

    login = await client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    db_session.expunge_all()
    after_login = await db_session.scalar(
        select(User.last_login_at).where(User.id == shop.processor)
    )
    refresh = await client.post(f"{API}/auth/refresh")  # the cookie login set
    db_session.expunge_all()
    after_refresh = await db_session.scalar(
        select(User.last_login_at).where(User.id == shop.processor)
    )

    assert login.status_code == 200
    assert after_login is not None
    assert refresh.status_code == 200
    assert after_refresh == after_login


# --------------------------------------------------------------------------- #
# Review fixes (after 21a32911)
# --------------------------------------------------------------------------- #


async def test_the_owner_rule_reads_the_company_row_not_a_loaded_copy(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """An ownership change is honoured by the next request: the new owner is protected, the old is not.

    NOT a test of review finding 1 (the owner read from the EFFECTIVE company rather than the actor's
    own). The two companies are always the same today, so no request can tell them apart, and
    measured: replacing the read with the session's cached `Company` also passes here.
    """
    shop = await _shop(db_session)
    # Ownership moves to the processor-made-admin (as `transfer_owner` would) after the shop loaded.
    await client.put(
        f"{API}/users/{shop.processor}/roles", json={"roles": ["admin"]}, headers=_as(shop.admin)
    )
    await db_session.execute(
        text("UPDATE companies SET owner_user_id = :u WHERE id = :c"),
        {"u": shop.processor, "c": shop.company_id},
    )

    new_owner = await client.post(
        f"{API}/users/{shop.processor}/deactivate", headers=_as(shop.admin)
    )
    old_owner = await client.post(f"{API}/users/{shop.owner}/deactivate", headers=_as(shop.admin))

    assert new_owner.status_code == 409
    assert old_owner.status_code == 200


async def test_a_change_decides_from_the_row_as_it_is_now(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Finding 2: the person is locked and re-read, so a change another admin already made is seen.

    Simulated in one session: the row is deactivated behind the session's back after it loaded the
    person. Deciding from the stale copy would deactivate again and write a second audit row.
    """
    shop = await _shop(db_session)
    pat = await db_session.get(User, shop.processor)
    assert pat is not None and pat.is_active is True  # the session now holds an active copy
    await db_session.execute(
        text("UPDATE users SET is_active = false WHERE id = :u"), {"u": shop.processor}
    )

    resp = await client.post(f"{API}/users/{shop.processor}/deactivate", headers=_as(shop.admin))

    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
    assert await _audit_rows(db_session, shop.company_id) == []


async def test_signing_in_does_not_move_updated_at(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Finding 4: `updated_at` keeps meaning "last edited", not "last signed in"."""
    shop = await _shop(db_session)
    before = (
        await db_session.execute(
            select(User.email, User.updated_at).where(User.id == shop.processor)
        )
    ).one()

    login = await client.post(
        f"{API}/auth/login", json={"email": before.email, "password": PASSWORD}
    )

    db_session.expunge_all()
    after = (
        await db_session.execute(
            select(User.updated_at, User.last_login_at).where(User.id == shop.processor)
        )
    ).one()
    assert login.status_code == 200
    assert after.last_login_at is not None
    assert after.updated_at == before.updated_at


@pytest.mark.parametrize("body", [{"first_name": " "}, {"last_name": "\t"}])
async def test_a_blank_name_is_refused(
    client: AsyncClient, db_session: AsyncSession, body: dict[str, Any]
) -> None:
    """Finding 5: spaces only would show as a blank row and a blank name in the audit log."""
    shop = await _shop(db_session)
    resp = await client.patch(f"{API}/users/{shop.processor}", json=body, headers=_as(shop.admin))
    assert resp.status_code == 422


async def test_a_name_is_stored_trimmed(client: AsyncClient, db_session: AsyncSession) -> None:
    shop = await _shop(db_session)
    resp = await client.patch(
        f"{API}/users/{shop.processor}", json={"first_name": "  Patricia "}, headers=_as(shop.admin)
    )
    assert resp.json()["first_name"] == "Patricia"


async def test_only_the_first_page_carries_the_count(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Finding 6: "Load more" does not recount the whole log."""
    shop = await _shop(db_session)
    await _three_changes(client, shop)

    first = (await client.get(f"{API}/audit-log?limit=2", headers=_as(shop.admin))).json()
    second = (
        await client.get(
            f"{API}/audit-log",
            params={"limit": 2, "before": first["next_cursor"]},
            headers=_as(shop.admin),
        )
    ).json()

    assert first["total"] == 3
    assert second["total"] is None
