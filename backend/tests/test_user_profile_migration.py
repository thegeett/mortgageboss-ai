"""The LP-MB-Admin-03 migration on a database built by migrations: existing users take the defaults."""

from uuid import uuid4

from sqlalchemy import text
from tests.conftest import MigratedDb

_BEFORE = "0a7332974687"  # pragma: allowlist secret  (Alembic revision id)
_THIS = "c5874fbee899"  # pragma: allowlist secret  (Alembic revision id)


async def test_existing_users_take_the_new_defaults(migrated_db: MigratedDb) -> None:
    migrated_db.alembic("downgrade", _BEFORE)
    company, user = uuid4(), uuid4()
    try:
        async with migrated_db.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO companies (id, name, slug, settings, is_active, created_at, "
                    "updated_at) VALUES (:id, 'Acme', :slug, '{}', true, now(), now())"
                ),
                {"id": company, "slug": f"acme-{company.hex[:6]}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO users (id, company_id, email, hashed_password, first_name, "
                    "last_name, is_active, created_at, updated_at) VALUES (:id, :c, :e, 'x', 'F', "
                    "'L', true, now(), now())"
                ),
                {"id": user, "c": company, "e": f"u-{user.hex[:6]}@example.com"},
            )

        migrated_db.alembic("upgrade", _THIS)

        async with migrated_db.engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT phone, title, nmls_id, licensed_states, sees_all_loans, "
                        "last_login_at FROM users WHERE id = :id"
                    ),
                    {"id": user},
                )
            ).one()
            view_columns = set(
                (
                    await conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = 'readonly' AND table_name = 'users'"
                        )
                    )
                ).scalars()
            )
        assert tuple(row) == (None, None, None, [], False, None)
        assert {"title", "licensed_states", "sees_all_loans", "last_login_at"} <= view_columns
        assert not {"phone", "nmls_id", "email", "first_name"} & view_columns
    finally:
        async with migrated_db.engine.begin() as conn:
            await conn.execute(text("TRUNCATE companies, users CASCADE"))
        migrated_db.alembic("upgrade", "head")
