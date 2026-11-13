"""The LP-MB-Admin-04 migration on a database built by migrations: one OPEN invite per address."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.conftest import MigratedDb

_INSERT = text(
    "INSERT INTO user_invites (id, company_id, email, roles, token_hash, expires_at, last_sent_at, "
    "revoked_at, created_at, updated_at) VALUES (gen_random_uuid(), :c, 'a@b.com', '[\"processor\"]', "
    ":h, now() + interval '7 days', now(), :revoked, now(), now())"
)


async def test_one_open_invite_per_address_per_company(migrated_db: MigratedDb) -> None:
    company = uuid4()
    try:
        async with migrated_db.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO companies (id, name, slug, settings, is_active, created_at, "
                    "updated_at) VALUES (:id, 'Acme', :slug, '{}', true, now(), now())"
                ),
                {"id": company, "slug": f"acme-{company.hex[:6]}"},
            )
            await conn.execute(_INSERT, {"c": company, "h": uuid4().hex * 2, "revoked": None})
            # A revoked row for the same address sits beside the open one.
            await conn.execute(
                _INSERT,
                {"c": company, "h": uuid4().hex * 2, "revoked": datetime(2026, 1, 1, tzinfo=UTC)},
            )
        with pytest.raises(IntegrityError):
            async with migrated_db.engine.begin() as conn:
                await conn.execute(_INSERT, {"c": company, "h": uuid4().hex * 2, "revoked": None})
        async with migrated_db.engine.connect() as conn:
            send_count = await conn.scalar(
                text("SELECT send_count FROM user_invites WHERE company_id = :c LIMIT 1"),
                {"c": company},
            )
        assert send_count == 0
    finally:
        async with migrated_db.engine.begin() as conn:
            await conn.execute(text("TRUNCATE companies, users, user_invites CASCADE"))
