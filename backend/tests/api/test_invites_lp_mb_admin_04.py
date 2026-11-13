"""Staff invitations (LP-MB-Admin-04): the admin API, the public link, and the token's whereabouts.

The real app, with the database bound to the test's rollback session. No mail transport unless a test
sets one, so by default the API hands back `accept_url` (copy-the-link mode).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import structlog
from app.api.auth import REFRESH_TOKEN_COOKIE
from app.core.config import settings
from app.core.database import get_db
from app.core.jwt import create_access_token
from app.core.tokens import hash_token
from app.main import app
from app.models import Company, CompanyAuditLog, User, UserInvite, UserRole
from app.models.base import utcnow
from app.services import invites as invite_service
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from tests.user_factory import make_user

API = "/api/v1"
INVALID = {"error": {"type": "not_found", "message": "This invitation is no longer valid"}}
GOOD_PASSWORD = "a long enough password"  # pragma: allowlist secret


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
    admin: UUID
    processor: UUID
    loan_officer: UUID


async def _person(
    db: AsyncSession, company_id: UUID, email: str, *roles: UserRole, active: bool = True
) -> User:
    user = make_user(
        company_id=company_id,
        email=email,
        hashed_password="x",  # pragma: allowlist secret
        first_name=email.split("@")[0].title(),
        last_name="Test",
        is_active=active,
        roles=roles,
    )
    db.add(user)
    await db.flush()
    return user


async def _shop(db: AsyncSession, name: str = "Acme") -> Shop:
    company = Company(name=name, slug=f"{name.lower()}-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    tag = uuid4().hex[:6]
    admin = await _person(db, company.id, f"admin-{tag}@{name.lower()}.com", UserRole.ADMIN)
    company.owner_user_id = admin.id
    processor = await _person(db, company.id, f"pat-{tag}@{name.lower()}.com", UserRole.PROCESSOR)
    lo = await _person(db, company.id, f"lou-{tag}@{name.lower()}.com", UserRole.LOAN_OFFICER)
    await db.flush()
    shop = Shop(company.id, admin.id, processor.id, lo.id)
    db.expunge_all()
    return shop


def _as(user_id: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _token(body: dict[str, Any]) -> str:
    url = body["accept_url"]
    assert url and "/accept-invite#" in url
    return str(url.split("#", 1)[1])


async def _invite(
    client: AsyncClient, shop: Shop, email: str = "new@person.com", roles: list[str] | None = None
) -> tuple[dict[str, Any], str]:
    resp = await client.post(
        f"{API}/invites",
        json={"email": email, "roles": roles or ["processor"]},
        headers=_as(shop.admin),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body, _token(body)


async def _age_last_sent(db: AsyncSession, invite_id: str, seconds: int = 120) -> None:
    await db.execute(
        update(UserInvite)
        .where(UserInvite.id == UUID(invite_id))
        .values(last_sent_at=utcnow() - timedelta(seconds=seconds))
    )


async def _audit_actions(db: AsyncSession, company_id: UUID) -> list[str]:
    db.expunge_all()
    rows = await db.scalars(
        select(CompanyAuditLog.action)
        .where(CompanyAuditLog.company_id == company_id)
        .order_by(CompanyAuditLog.created_at)
    )
    return list(rows)


# --------------------------------------------------------------------------- #
# Who
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("who", ["processor", "loan_officer"])
async def test_admin_routes_refuse_a_non_admin(
    client: AsyncClient, db_session: AsyncSession, who: str
) -> None:
    shop = await _shop(db_session)
    body, _ = await _invite(client, shop)
    invite_id = body["invite"]["id"]
    headers = _as(getattr(shop, who))
    for method, url, payload in [
        ("POST", f"{API}/invites", {"email": "x@y.com", "roles": ["processor"]}),
        ("GET", f"{API}/invites", None),
        ("POST", f"{API}/invites/{invite_id}/resend", None),
        ("POST", f"{API}/invites/{invite_id}/revoke", None),
    ]:
        resp = await client.request(method, url, json=payload, headers=headers)
        assert resp.status_code == 403, (method, url)


# --------------------------------------------------------------------------- #
# Creating
# --------------------------------------------------------------------------- #


async def test_an_admin_invites_with_any_roles_admin_included(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)

    body, token = await _invite(client, shop, "Lena.Park@Acme.com ", ["admin", "processor"])

    invite = body["invite"]
    # The form login looks up: domain lowercased, local part as typed (review finding 5).
    assert (invite["email"], invite["roles"], invite["expired"]) == (
        "Lena.Park@acme.com",
        ["admin", "processor"],
        False,
    )
    row = await db_session.get(UserInvite, UUID(invite["id"]))
    assert row is not None
    assert row.token_hash == hash_token(token)
    assert row.token_hash != token and len(row.token_hash) == 64
    assert (row.send_count, row.invited_by_user_id) == (1, shop.admin)
    assert (row.expires_at - row.last_sent_at) == timedelta(days=7)
    assert await _audit_actions(db_session, shop.company_id) == ["invite_sent"]


async def test_no_roles_is_refused(client: AsyncClient, db_session: AsyncSession) -> None:
    shop = await _shop(db_session)
    resp = await client.post(
        f"{API}/invites", json={"email": "a@b.com", "roles": []}, headers=_as(shop.admin)
    )
    assert resp.status_code == 422


async def test_an_address_already_on_the_team(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    await _person(db_session, shop.company_id, "here@acme.com", UserRole.PROCESSOR)
    await _person(db_session, shop.company_id, "gone@acme.com", UserRole.PROCESSOR, active=False)

    active = await client.post(
        f"{API}/invites",
        json={"email": "HERE@acme.com", "roles": ["processor"]},
        headers=_as(shop.admin),
    )
    inactive = await client.post(
        f"{API}/invites",
        json={"email": "gone@acme.com", "roles": ["processor"]},
        headers=_as(shop.admin),
    )

    assert (active.status_code, active.json()["error"]["message"]) == (409, "Already on your team")
    assert (inactive.status_code, inactive.json()["error"]["message"]) == (
        409,
        "Deactivated — reactivate them from the People list",
    )


async def test_an_address_in_another_company_is_refused_generically_and_audited(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    shop = await _shop(db_session)
    beta = await _shop(db_session, "Beta")
    gamma = await _shop(db_session, "Gamma")
    await _person(db_session, beta.company_id, "b@elsewhere.com", UserRole.PROCESSOR)
    await _person(db_session, gamma.company_id, "g@elsewhere.com", UserRole.ADMIN)

    # The refusal's audit row must be COMMITTED: in production the request's session rolls back on
    # the 409, and this shared test session would keep a merely flushed row and hide that.
    commits: list[None] = []
    real_commit = db_session.commit

    async def _counting_commit() -> None:
        commits.append(None)
        await real_commit()

    monkeypatch.setattr(db_session, "commit", _counting_commit)
    first = await client.post(
        f"{API}/invites",
        json={"email": "b@elsewhere.com", "roles": ["processor"]},
        headers=_as(shop.admin),
    )
    second = await client.post(
        f"{API}/invites",
        json={"email": "g@elsewhere.com", "roles": ["processor"]},
        headers=_as(shop.admin),
    )

    assert first.status_code == second.status_code == 409
    assert first.json()["error"]["message"] == "This address can't be invited; contact support"
    assert first.content == second.content  # byte-identical whatever the other company is
    assert len(commits) == 2
    db_session.expunge_all()
    rows = list(
        await db_session.scalars(
            select(CompanyAuditLog).where(
                CompanyAuditLog.company_id == shop.company_id,
                CompanyAuditLog.action == "invite_refused_foreign_email",
            )
        )
    )
    assert len(rows) == 2
    for row in rows:
        stored = f"{row.summary} {row.detail}"
        assert "Beta" not in stored and "Gamma" not in stored
        assert str(beta.company_id) not in stored and str(gamma.company_id) not in stored
    assert (
        await db_session.scalar(
            select(UserInvite.id).where(UserInvite.company_id == shop.company_id)
        )
        is None
    )


async def test_inviting_an_open_address_again_resends_it_under_the_throttle(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    body, first_token = await _invite(client, shop)
    invite_id = body["invite"]["id"]

    too_soon = await client.post(
        f"{API}/invites",
        json={"email": "new@person.com", "roles": ["processor"]},
        headers=_as(shop.admin),
    )
    await _age_last_sent(db_session, invite_id)
    again = await client.post(
        f"{API}/invites",
        json={"email": "new@person.com", "roles": ["processor"]},
        headers=_as(shop.admin),
    )

    assert (too_soon.status_code, too_soon.json()["error"]["message"]) == (
        429,
        "Try again in a minute",
    )
    assert again.status_code == 200
    assert again.json()["invite"]["id"] == invite_id
    assert again.json()["invite"]["send_count"] == 2
    lookup_old = await client.post(f"{API}/invites/lookup", json={"token": first_token})
    assert lookup_old.status_code == 404


async def test_fifty_open_invitations_is_the_limit(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    now = utcnow()
    for n in range(50):
        db_session.add(
            UserInvite(
                company_id=shop.company_id,
                email=f"p{n}@many.com",
                roles=["processor"],
                token_hash=hash_token(f"t{n}-{uuid4()}"),
                expires_at=now + timedelta(days=7),
                last_sent_at=now,
                send_count=1,
            )
        )
    await db_session.flush()

    resp = await client.post(
        f"{API}/invites",
        json={"email": "one@more.com", "roles": ["processor"]},
        headers=_as(shop.admin),
    )

    assert (resp.status_code, resp.json()["error"]["message"]) == (
        409,
        "At most 50 open invitations",
    )


@pytest.mark.parametrize("state", ["expired", "revoked"])
async def test_an_expired_or_revoked_invitation_is_reused(
    client: AsyncClient, db_session: AsyncSession, state: str
) -> None:
    shop = await _shop(db_session)
    body, old_token = await _invite(client, shop)
    invite_id = UUID(body["invite"]["id"])
    if state == "expired":
        await db_session.execute(
            update(UserInvite)
            .where(UserInvite.id == invite_id)
            .values(
                expires_at=utcnow() - timedelta(days=1), last_sent_at=utcnow() - timedelta(days=8)
            )
        )
    else:
        await client.post(f"{API}/invites/{invite_id}/revoke", headers=_as(shop.admin))

    again, new_token = await _invite(client, shop, roles=["loan_officer"])

    assert again["invite"]["id"] == str(invite_id)
    assert again["invite"]["send_count"] == 1
    assert again["invite"]["roles"] == ["loan_officer"]
    assert new_token != old_token
    assert (
        await client.post(f"{API}/invites/lookup", json={"token": new_token})
    ).status_code == 200


# --------------------------------------------------------------------------- #
# Resend, revoke, list
# --------------------------------------------------------------------------- #


async def test_resend_issues_a_new_link_and_the_old_one_stops_working(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    body, old = await _invite(client, shop)
    invite_id = body["invite"]["id"]

    throttled = await client.post(f"{API}/invites/{invite_id}/resend", headers=_as(shop.admin))
    await _age_last_sent(db_session, invite_id)
    resent = await client.post(f"{API}/invites/{invite_id}/resend", headers=_as(shop.admin))
    new = _token(resent.json())

    assert throttled.status_code == 429
    assert resent.status_code == 200
    assert (await client.post(f"{API}/invites/lookup", json={"token": old})).status_code == 404
    assert (await client.post(f"{API}/invites/lookup", json={"token": new})).status_code == 200
    assert await _audit_actions(db_session, shop.company_id) == ["invite_sent", "invite_resent"]


async def test_an_expired_invitation_can_be_resent(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    body, _ = await _invite(client, shop)
    await db_session.execute(
        update(UserInvite)
        .where(UserInvite.id == UUID(body["invite"]["id"]))
        .values(expires_at=utcnow() - timedelta(days=1), last_sent_at=utcnow() - timedelta(days=8))
    )

    listed = await client.get(f"{API}/invites", headers=_as(shop.admin))
    resent = await client.post(
        f"{API}/invites/{body['invite']['id']}/resend", headers=_as(shop.admin)
    )

    assert listed.json()[0]["expired"] is True
    assert resent.status_code == 200
    assert resent.json()["invite"]["expired"] is False


async def test_revoke_ends_the_link(client: AsyncClient, db_session: AsyncSession) -> None:
    shop = await _shop(db_session)
    body, token = await _invite(client, shop)

    revoked = await client.post(
        f"{API}/invites/{body['invite']['id']}/revoke", headers=_as(shop.admin)
    )
    again = await client.post(
        f"{API}/invites/{body['invite']['id']}/revoke", headers=_as(shop.admin)
    )

    assert revoked.status_code == 200
    assert again.status_code == 404
    assert (await client.post(f"{API}/invites/lookup", json={"token": token})).status_code == 404
    assert (await client.get(f"{API}/invites", headers=_as(shop.admin))).json() == []


async def test_the_list_holds_pending_invitations_newest_first(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    await _invite(client, shop, "first@x.com")
    await _invite(client, shop, "second@x.com")
    _, token = await _invite(client, shop, "accepted@x.com")
    await client.post(
        f"{API}/invites/accept",
        json={"token": token, "first_name": "A", "last_name": "B", "password": GOOD_PASSWORD},
    )

    listed = (await client.get(f"{API}/invites", headers=_as(shop.admin))).json()

    assert [row["email"] for row in listed] == ["second@x.com", "first@x.com"]
    assert listed[0]["invited_by_name"] is not None
    assert "token" not in str(listed) and "hash" not in str(listed)


async def test_another_companys_invitation_cannot_be_resent_or_revoked(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    mine = await _shop(db_session)
    theirs = await _shop(db_session, "Other")
    body, token = await _invite(client, theirs)
    invite_id = body["invite"]["id"]
    await _age_last_sent(db_session, invite_id)

    resend = await client.post(f"{API}/invites/{invite_id}/resend", headers=_as(mine.admin))
    revoke = await client.post(f"{API}/invites/{invite_id}/revoke", headers=_as(mine.admin))

    assert (resend.status_code, revoke.status_code) == (404, 404)
    assert (await client.post(f"{API}/invites/lookup", json={"token": token})).status_code == 200
    assert await _audit_actions(db_session, mine.company_id) == []


# --------------------------------------------------------------------------- #
# The public link: lookup and accept
# --------------------------------------------------------------------------- #


async def test_lookup_shows_the_company_inviter_email_and_roles(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    _, token = await _invite(client, shop, roles=["loan_officer"])

    resp = await client.post(f"{API}/invites/lookup", json={"token": token})

    assert resp.status_code == 200
    body = resp.json()
    assert (body["company_name"], body["email"], body["roles"]) == (
        "Acme",
        "new@person.com",
        ["loan_officer"],
    )
    assert body["invited_by_name"].endswith("Test")


async def test_accept_creates_the_account_and_signs_in(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    _, token = await _invite(client, shop, roles=["loan_officer", "processor"])

    resp = await client.post(
        f"{API}/invites/accept",
        json={
            "token": token,
            "first_name": " Lena ",
            "last_name": "Park",
            "password": GOOD_PASSWORD,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["user"]["email"] == "new@person.com"
    assert body["user"]["roles"] == ["loan_officer", "processor"]
    assert "loan.create" in body["user"]["permissions"]
    assert REFRESH_TOKEN_COOKIE in resp.headers.get("set-cookie", "")
    db_session.expunge_all()
    user = await db_session.scalar(select(User).where(User.email == "new@person.com"))
    assert user is not None
    assert (user.company_id, user.first_name, user.is_active) == (shop.company_id, "Lena", True)
    granted = set(
        await db_session.scalars(
            text("SELECT granted_by_user_id FROM user_roles WHERE user_id = :u"), {"u": user.id}
        )
    )
    assert granted == {shop.admin}
    invite = await db_session.scalar(select(UserInvite).where(UserInvite.email == "new@person.com"))
    assert (
        invite is not None and invite.accepted_user_id == user.id and invite.accepted_at is not None
    )
    accepted = await db_session.scalar(
        select(CompanyAuditLog).where(
            CompanyAuditLog.action == "invite_accepted",
            CompanyAuditLog.company_id == shop.company_id,
        )
    )
    assert accepted is not None and accepted.actor_user_id == user.id
    # The new person can use the app at once.
    me = await client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200


async def test_a_token_works_once(client: AsyncClient, db_session: AsyncSession) -> None:
    shop = await _shop(db_session)
    _, token = await _invite(client, shop)
    payload = {"token": token, "first_name": "A", "last_name": "B", "password": GOOD_PASSWORD}

    first = await client.post(f"{API}/invites/accept", json=payload)
    second = await client.post(f"{API}/invites/accept", json=payload)

    assert first.status_code == 200
    assert (second.status_code, second.json()) == (404, INVALID)


@pytest.mark.parametrize(
    "body",
    [
        {"password": "short"},  # pragma: allowlist secret  (a test value, deliberately weak)
        {"first_name": " "},
        {"last_name": ""},
    ],
)
async def test_accept_refuses_a_weak_password_or_a_blank_name(
    client: AsyncClient, db_session: AsyncSession, body: dict[str, str]
) -> None:
    shop = await _shop(db_session)
    _, token = await _invite(client, shop)
    payload = {
        "token": token,
        "first_name": "A",
        "last_name": "B",
        "password": GOOD_PASSWORD,
        **body,
    }

    resp = await client.post(f"{API}/invites/accept", json=payload)

    assert resp.status_code == 422
    assert (await client.post(f"{API}/invites/lookup", json={"token": token})).status_code == 200


async def test_accept_fails_like_an_invalid_link_if_the_address_became_a_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    _, token = await _invite(client, shop)
    other = await _shop(db_session, "Late")
    await _person(db_session, other.company_id, "new@person.com", UserRole.PROCESSOR)

    resp = await client.post(
        f"{API}/invites/accept",
        json={"token": token, "first_name": "A", "last_name": "B", "password": GOOD_PASSWORD},
    )

    assert (resp.status_code, resp.json()) == (404, INVALID)


async def _invalid_tokens(client: AsyncClient, db: AsyncSession, shop: Shop) -> dict[str, str]:
    """One token per way a link stops working."""
    _, expired = await _invite(client, shop, "e@x.com")
    await db.execute(
        update(UserInvite)
        .where(UserInvite.email == "e@x.com")
        .values(expires_at=utcnow() - timedelta(seconds=1))
    )
    body, revoked = await _invite(client, shop, "r@x.com")
    await client.post(f"{API}/invites/{body['invite']['id']}/revoke", headers=_as(shop.admin))
    _, used = await _invite(client, shop, "u@x.com")
    await client.post(
        f"{API}/invites/accept",
        json={"token": used, "first_name": "U", "last_name": "S", "password": GOOD_PASSWORD},
    )
    return {"expired": expired, "revoked": revoked, "used": used, "garbage": "not-a-token"}


async def test_every_dead_link_looks_the_same(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    tokens = await _invalid_tokens(client, db_session, shop)

    for why, token in tokens.items():
        lookup = await client.post(f"{API}/invites/lookup", json={"token": token})
        accept = await client.post(
            f"{API}/invites/accept",
            json={"token": token, "first_name": "A", "last_name": "B", "password": GOOD_PASSWORD},
        )
        assert (lookup.status_code, lookup.json()) == (404, INVALID), why
        assert (accept.status_code, accept.json()) == (404, INVALID), why


async def test_accept_is_all_or_nothing(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure after the user insert leaves no user and the invitation still open."""
    shop = await _shop(db_session)
    _, token = await _invite(client, shop)
    original = invite_service._audit

    async def _fail_on_accept(*args: Any, **kwargs: Any) -> None:
        if args[3] == invite_service.AuditAction.INVITE_ACCEPTED:
            raise RuntimeError("after the user insert")
        await original(*args, **kwargs)

    monkeypatch.setattr(invite_service, "_audit", _fail_on_accept)

    with pytest.raises(RuntimeError):
        await invite_service.accept_invite(db_session, token, "A", "B", GOOD_PASSWORD)

    assert await db_session.scalar(select(User.id).where(User.email == "new@person.com")) is None
    db_session.expunge_all()
    invite = await db_session.scalar(select(UserInvite).where(UserInvite.email == "new@person.com"))
    assert invite is not None and invite.accepted_at is None and invite.is_open


# --------------------------------------------------------------------------- #
# The token appears nowhere but the link
# --------------------------------------------------------------------------- #


async def test_the_raw_token_is_in_no_table_audit_row_or_log_line(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    shop = await _shop(db_session)
    with structlog.testing.capture_logs() as logs:
        body, token = await _invite(client, shop)
        await client.post(f"{API}/invites/lookup", json={"token": token})
        await _age_last_sent(db_session, body["invite"]["id"])
        resent = await client.post(
            f"{API}/invites/{body['invite']['id']}/resend", headers=_as(shop.admin)
        )
        token2 = _token(resent.json())
        await client.post(
            f"{API}/invites/accept",
            json={"token": token2, "first_name": "A", "last_name": "B", "password": GOOD_PASSWORD},
        )

    for raw in (token, token2):
        assert raw not in str(logs)
        for table in ("user_invites", "company_audit_log", "users", "user_roles"):
            dump = await db_session.scalar(
                text(f"SELECT coalesce(string_agg(t::text, ' '), '') FROM {table} t")
            )
            assert raw not in dump, table


# --------------------------------------------------------------------------- #
# With a mail transport: the link goes by email, never back to the admin
# --------------------------------------------------------------------------- #


async def test_with_a_transport_the_link_is_emailed_not_returned(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import invites as invites_api

    queued: list[tuple[str, str]] = []
    monkeypatch.setattr(settings, "mail_transport", "smtp")
    monkeypatch.setattr(invites_api.send_invite_email, "delay", lambda *a: queued.append(a))
    shop = await _shop(db_session)

    resp = await client.post(
        f"{API}/invites",
        json={"email": "mail@me.com", "roles": ["processor"]},
        headers=_as(shop.admin),
    )

    assert resp.status_code == 201
    assert resp.json()["accept_url"] is None
    assert len(queued) == 1
    invite_id, token = queued[0]
    assert invite_id == resp.json()["invite"]["id"]
    row = await db_session.get(UserInvite, UUID(invite_id))
    assert row is not None and row.token_hash == hash_token(token)


# --------------------------------------------------------------------------- #
# Review fixes (after e2beeadc)
# --------------------------------------------------------------------------- #


async def test_a_capitalised_address_can_sign_in_as_typed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Finding 5: the account is stored in the form login looks up, and duplicates ignore case."""
    shop = await _shop(db_session)
    _, token = await _invite(client, shop, "Alice.Smith@Corp.com")
    again = await client.post(
        f"{API}/invites",
        json={"email": "alice.smith@corp.com", "roles": ["processor"]},
        headers=_as(shop.admin),
    )
    await client.post(
        f"{API}/invites/accept",
        json={"token": token, "first_name": "A", "last_name": "S", "password": GOOD_PASSWORD},
    )

    login = await client.post(
        f"{API}/auth/login", json={"email": "Alice.Smith@corp.com", "password": GOOD_PASSWORD}
    )

    assert again.status_code == 429  # the same person, so a resend (too soon), not a second invite
    assert login.status_code == 200


async def test_re_inviting_with_new_roles_changes_them(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Finding 2: a corrected re-invite is not silently ignored."""
    shop = await _shop(db_session)
    body, _ = await _invite(client, shop, roles=["processor"])
    await _age_last_sent(db_session, body["invite"]["id"])

    again = await client.post(
        f"{API}/invites",
        json={"email": "new@person.com", "roles": ["admin"]},
        headers=_as(shop.admin),
    )

    assert again.status_code == 200
    assert again.json()["invite"]["roles"] == ["admin"]
    db_session.expunge_all()
    resent = await db_session.scalar(
        select(CompanyAuditLog).where(CompanyAuditLog.action == "invite_resent")
    )
    assert resent is not None
    assert resent.detail["changes"] == [{"field": "roles", "from": ["processor"], "to": ["admin"]}]


async def test_a_bad_link_origin_saves_nothing(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 3: the link is built before the commit, so a misconfiguration leaves no orphan."""
    from app.services.upload_links import LinkOriginNotConfigured

    def _refuse() -> str:
        raise LinkOriginNotConfigured("misconfigured")

    monkeypatch.setattr(invite_service, "usable_link_origin", _refuse)
    shop = await _shop(db_session)
    commits: list[None] = []
    real_commit = db_session.commit

    async def _counting_commit() -> None:
        commits.append(None)
        await real_commit()

    monkeypatch.setattr(db_session, "commit", _counting_commit)

    # Unhandled, so a 500 in production; this test client re-raises it instead.
    with pytest.raises(LinkOriginNotConfigured):
        await client.post(
            f"{API}/invites",
            json={"email": "x@y.com", "roles": ["processor"]},
            headers=_as(shop.admin),
        )

    assert commits == []


async def test_a_queue_that_refuses_the_email_is_a_clear_503(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 3: the invitation is saved, the admin is told, and Resend recovers it."""
    from app.api import invites as invites_api

    def _down(*_: Any) -> None:
        raise ConnectionError("broker down")

    monkeypatch.setattr(settings, "mail_transport", "smtp")
    monkeypatch.setattr(invites_api.send_invite_email, "delay", _down)
    shop = await _shop(db_session)

    resp = await client.post(
        f"{API}/invites", json={"email": "q@x.com", "roles": ["processor"]}, headers=_as(shop.admin)
    )

    assert resp.status_code == 503
    assert "Use Resend" in resp.json()["error"]["message"]
    listed = (await client.get(f"{API}/invites", headers=_as(shop.admin))).json()
    assert [row["email"] for row in listed] == ["q@x.com"]


async def test_resending_an_expired_invitation_respects_the_cap(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Finding 7: reopening an expired invitation adds an open one."""
    shop = await _shop(db_session)
    now = utcnow()
    for n in range(50):
        db_session.add(
            UserInvite(
                company_id=shop.company_id,
                email=f"p{n}@many.com",
                roles=["processor"],
                token_hash=hash_token(f"t{n}-{uuid4()}"),
                expires_at=now + timedelta(days=7),
                last_sent_at=now,
                send_count=1,
            )
        )
    expired = UserInvite(
        company_id=shop.company_id,
        email="old@many.com",
        roles=["processor"],
        token_hash=hash_token(f"old-{uuid4()}"),
        expires_at=now - timedelta(days=1),
        last_sent_at=now - timedelta(days=8),
        send_count=1,
    )
    db_session.add(expired)
    await db_session.flush()

    resp = await client.post(f"{API}/invites/{expired.id}/resend", headers=_as(shop.admin))

    assert (resp.status_code, resp.json()["error"]["message"]) == (
        409,
        "At most 50 open invitations",
    )


async def test_accepting_records_a_sign_in(client: AsyncClient, db_session: AsyncSession) -> None:
    """Finding 8: the new person is signed in, so People does not say "Never"."""
    shop = await _shop(db_session)
    _, token = await _invite(client, shop)
    await client.post(
        f"{API}/invites/accept",
        json={"token": token, "first_name": "A", "last_name": "B", "password": GOOD_PASSWORD},
    )
    db_session.expunge_all()
    signed_in = await db_session.scalar(
        select(User.last_login_at).where(User.email == "new@person.com")
    )
    assert signed_in is not None


async def test_two_admins_inviting_the_same_new_address_at_once(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 1: the loser of the race hears "Try again in a minute", not a 500.

    The race is staged: the open invite exists, but this request's lookup is made to miss it, as it
    would if the other admin's insert committed between the lookup and this insert.
    """
    shop = await _shop(db_session)
    await _invite(client, shop, "race@x.com")
    real = invite_service._same_address

    def _miss_invites(column: Any, address: str) -> Any:
        return UserInvite.id.is_(None) if column is UserInvite.email else real(column, address)

    monkeypatch.setattr(invite_service, "_same_address", _miss_invites)

    resp = await client.post(
        f"{API}/invites",
        json={"email": "race@x.com", "roles": ["processor"]},
        headers=_as(shop.admin),
    )

    assert (resp.status_code, resp.json()["error"]["message"]) == (429, "Try again in a minute")


async def test_an_address_taken_at_the_moment_of_accepting_is_a_dead_link(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 6: two companies' invitations accepted at once; the second is the usual 404.

    Staged like the test above: the address is already a user, but the check is made to miss it.
    """
    shop = await _shop(db_session)
    _, token = await _invite(client, shop)
    other = await _shop(db_session, "Late")
    await _person(db_session, other.company_id, "new@person.com", UserRole.PROCESSOR)
    real = invite_service._same_address

    def _miss_users(column: Any, address: str) -> Any:
        return User.id.is_(None) if column is User.email else real(column, address)

    monkeypatch.setattr(invite_service, "_same_address", _miss_users)

    resp = await client.post(
        f"{API}/invites/accept",
        json={"token": token, "first_name": "A", "last_name": "B", "password": GOOD_PASSWORD},
    )

    assert (resp.status_code, resp.json()) == (404, INVALID)
    db_session.expunge_all()
    invite = await db_session.scalar(select(UserInvite).where(UserInvite.email == "new@person.com"))
    assert invite is not None and invite.accepted_at is None
