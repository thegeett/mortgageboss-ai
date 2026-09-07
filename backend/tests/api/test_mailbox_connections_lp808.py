"""LP-808 at the layer a caller reaches — the guided flow, and who may use it.

Two things are only true here:

* **Connecting is admin-gated; reading is not.** Minting an address creates a credential that
  accepts mail into every one of a company's files, so it is administration. The staleness banner is
  for the processor whose documents stopped arriving, and gating the read would hide the outage from
  the person it affects.
* **The token never leaves except inside the address.** ADR-397's shape: the address contains the
  token, so returning it IS handing over the capability — what the rule buys is that it leaves in
  the one form meant to leave, rather than as a field on an unrelated payload.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest_asyncio
from app.core.database import get_db
from app.main import app
from app.models import Company, User, UserRole
from app.services.mailbox_connections import create_connection
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

API = "/api/v1/mailbox-connections"


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
    """BOTH ROLES, so the gate can be measured in each direction. One with only an admin cannot tell
    a working gate from an absent one."""
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


# --------------------------------------------------------------------------------------------- #
# The gate, in both directions
# --------------------------------------------------------------------------------------------- #
async def test_an_admin_connects_a_mailbox(client: AsyncClient, db: AsyncSession) -> None:
    _company, tokens = await _company_with_users(db, slug="acme")
    await db.commit()

    resp = await client.post(
        API,
        json={"provider": "google", "source_address": "docs@herco.example"},
        headers=_auth(tokens["admin"]),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["address"].startswith("co-")
    assert body["verification"] == "not_verified"
    assert body["status"] == "connected"


async def test_a_processor_cannot_connect_one(client: AsyncClient, db: AsyncSession) -> None:
    """It mints a credential that accepts mail into every one of the company's files."""
    _company, tokens = await _company_with_users(db, slug="acme")
    await db.commit()

    resp = await client.post(API, json={"provider": "google"}, headers=_auth(tokens["processor"]))

    assert resp.status_code == 403


async def test_a_processor_can_read_them(client: AsyncClient, db: AsyncSession) -> None:
    """THE STALENESS BANNER IS FOR THE PROCESSOR. Gating this read would hide the outage from the
    person whose documents stopped arriving."""
    company, tokens = await _company_with_users(db, slug="acme")
    await create_connection(db, company_id=company.id)
    await db.commit()

    resp = await client.get(API, headers=_auth(tokens["processor"]))

    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["is_stale"] is False


async def test_a_processor_cannot_revoke_or_send_steps(
    client: AsyncClient, db: AsyncSession
) -> None:
    company, tokens = await _company_with_users(db, slug="acme")
    connection = await create_connection(db, company_id=company.id)
    await db.commit()

    revoked = await client.delete(f"{API}/{connection.id}", headers=_auth(tokens["processor"]))
    mailed = await client.post(
        f"{API}/{connection.id}/email-steps",
        json={"admin_email": "it@herco.example"},
        headers=_auth(tokens["processor"]),
    )

    assert revoked.status_code == 403
    assert mailed.status_code == 403


# --------------------------------------------------------------------------------------------- #
# Tenancy
# --------------------------------------------------------------------------------------------- #
async def test_another_companys_connection_is_a_404(client: AsyncClient, db: AsyncSession) -> None:
    theirs, _their_tokens = await _company_with_users(db, slug="theirs")
    _mine, my_tokens = await _company_with_users(db, slug="mine")
    their_connection = await create_connection(db, company_id=theirs.id)
    await db.commit()

    steps = await client.get(
        f"{API}/{their_connection.id}/steps", headers=_auth(my_tokens["processor"])
    )
    revoked = await client.delete(f"{API}/{their_connection.id}", headers=_auth(my_tokens["admin"]))
    missing = await client.delete(f"{API}/{uuid4()}", headers=_auth(my_tokens["admin"]))

    assert steps.status_code == 404
    assert revoked.status_code == missing.status_code == 404
    assert revoked.json() == missing.json()


async def test_the_list_holds_only_this_companys(client: AsyncClient, db: AsyncSession) -> None:
    theirs, _their_tokens = await _company_with_users(db, slug="list-theirs")
    mine, my_tokens = await _company_with_users(db, slug="list-mine")
    await create_connection(db, company_id=theirs.id)
    mine_connection = await create_connection(db, company_id=mine.id)
    await db.commit()

    resp = await client.get(API, headers=_auth(my_tokens["processor"]))

    assert [row["id"] for row in resp.json()] == [str(mine_connection.id)]


# --------------------------------------------------------------------------------------------- #
# The token, and the steps
# --------------------------------------------------------------------------------------------- #
async def test_the_raw_token_field_never_appears(client: AsyncClient, db: AsyncSession) -> None:
    """ADR-094 as amended by ADR-397: the ADDRESS is exposed and the FIELD is not. The address
    contains the token, so this is a narrowing rather than a preservation — the capability leaves in
    one shape through one accessor, never as a field on a payload."""
    company, tokens = await _company_with_users(db, slug="token")
    connection = await create_connection(db, company_id=company.id)
    await db.commit()

    resp = await client.get(API, headers=_auth(tokens["processor"]))

    assert "token" not in resp.json()[0]
    # The address is present, and it is the only thing carrying the token.
    assert resp.json()[0]["address"] == connection.get_ingest_address()


async def test_the_google_steps_say_admin_routing_rule_not_user_forward(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The distinction is the whole reason Route B works without a per-user confirmation: a
    user-level forward makes the TARGET confirm a mailed code, which nobody here can do. The
    admin-level routing rule does not."""
    company, tokens = await _company_with_users(db, slug="google")
    connection = await create_connection(db, company_id=company.id, provider="google")
    await db.commit()

    resp = await client.get(f"{API}/{connection.id}/steps", headers=_auth(tokens["processor"]))

    joined = " ".join(resp.json()["steps"]).lower()
    assert "routing rule" in joined
    assert "x-gm-original-to" in joined
    # And the address is substituted into the steps, not left as a placeholder for somebody to fill.
    assert connection.get_ingest_address() in " ".join(resp.json()["steps"])
    assert "{address}" not in " ".join(resp.json()["steps"])


async def test_the_microsoft_steps_say_mail_flow_rule_not_inbox_rule(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Automatic external forwarding via INBOX rules is blocked by default for tenants created after
    2021 (`550 5.7.520 … AS(7555)`). Telling an admin to make an inbox rule sends them to a dead end
    and then to us to ask why."""
    company, tokens = await _company_with_users(db, slug="ms")
    connection = await create_connection(db, company_id=company.id, provider="microsoft")
    await db.commit()

    joined = " ".join(
        (
            await client.get(f"{API}/{connection.id}/steps", headers=_auth(tokens["processor"]))
        ).json()["steps"]
    ).lower()

    assert "mail flow" in joined
    assert "not an inbox rule" in joined


async def test_an_unknown_provider_still_gets_steps(client: AsyncClient, db: AsyncSession) -> None:
    """A provider we have no click-path for is a real answer, not an error — the generic steps say
    what the rule must do without naming a console."""
    company, tokens = await _company_with_users(db, slug="unknown")
    connection = await create_connection(db, company_id=company.id, provider="fastmail")
    await db.commit()

    resp = await client.get(f"{API}/{connection.id}/steps", headers=_auth(tokens["processor"]))

    assert resp.status_code == 200
    assert resp.json()["steps"]


async def test_sending_the_steps_moves_it_to_awaiting_first_message(
    client: AsyncClient, db: AsyncSession
) -> None:
    company, tokens = await _company_with_users(db, slug="steps")
    connection = await create_connection(db, company_id=company.id)
    await db.commit()

    resp = await client.post(
        f"{API}/{connection.id}/email-steps",
        json={"admin_email": "it@herco.example"},
        headers=_auth(tokens["admin"]),
    )

    assert resp.status_code == 200
    assert resp.json()["verification"] == "awaiting_first_message"


async def test_resending_the_steps_does_not_unverify_a_working_connection(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Re-sending the steps is an ordinary thing to do on a working connection — asking a colleague
    to check the rule. A state machine that reset it would make a help request look like an outage."""
    from app.services.mailbox_connections import record_arrival

    company, tokens = await _company_with_users(db, slug="resend")
    connection = await create_connection(db, company_id=company.id)
    await record_arrival(db, connection=connection)
    await db.commit()

    resp = await client.post(
        f"{API}/{connection.id}/email-steps",
        json={"admin_email": "it@herco.example"},
        headers=_auth(tokens["admin"]),
    )

    assert resp.json()["verification"] == "verified"


async def test_revoking_shows_as_revoked(client: AsyncClient, db: AsyncSession) -> None:
    company, tokens = await _company_with_users(db, slug="revoke")
    connection = await create_connection(db, company_id=company.id)
    await db.commit()

    resp = await client.delete(f"{API}/{connection.id}", headers=_auth(tokens["admin"]))

    assert resp.json()["status"] == "revoked"
