"""The LP-MB-Admin-01 migration, run for real: backfill, owner, and the way back.

`create_all` cannot test a backfill (the old column never holds data there), so this uses
`migrated_db`: it steps back to the previous revision, seeds users with the OLD `users.role`, and
migrates forward. Revisions are named, not `-1`, so a later migration on top does not move the test.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.conftest import MigratedDb

_BEFORE = "e3a9d4c7b512"  # pragma: allowlist secret  (Alembic revision id)
_THIS = "0a7332974687"  # pragma: allowlist secret  (Alembic revision id)
_T0 = datetime(2026, 1, 1, tzinfo=UTC)


async def _seed(db: MigratedDb) -> dict[str, UUID]:
    """Two companies, four users. Acme: an inactive admin (earliest), then two active admins.
    Beta: one processor and no admin."""
    ids = {name: uuid4() for name in ("acme", "beta", "gone", "first", "second", "proc")}
    async with db.engine.begin() as conn:
        for key in ("acme", "beta"):
            await conn.execute(
                text(
                    "INSERT INTO companies (id, name, slug, settings, is_active, created_at, "
                    "updated_at) VALUES (:id, :slug, :slug, '{}', true, :t, :t)"
                ),
                {"id": ids[key], "slug": f"{key}-{ids[key].hex[:6]}", "t": _T0},
            )
        for i, (key, company, role, active) in enumerate(
            [
                ("gone", "acme", "admin", False),
                ("first", "acme", "admin", True),
                ("second", "acme", "admin", True),
                ("proc", "beta", "processor", True),
            ]
        ):
            await conn.execute(
                text(
                    "INSERT INTO users (id, company_id, email, hashed_password, first_name, "
                    "last_name, role, is_active, created_at, updated_at) VALUES (:id, :company, "
                    ":email, 'x', 'F', 'L', :role, :active, :t, :t)"
                ),
                {
                    "id": ids[key],
                    "company": ids[company],
                    "email": f"{key}-{ids[key].hex[:6]}@example.com",
                    "role": role,
                    "active": active,
                    "t": _T0 + timedelta(days=i),
                },
            )
    return ids


async def _view_columns(conn: AsyncConnection, view: str) -> set[str]:
    rows = await conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'readonly' AND table_name = :v"
        ),
        {"v": view},
    )
    return set(rows.scalars())


async def test_backfill_owner_and_downgrade(migrated_db: MigratedDb) -> None:
    migrated_db.alembic("downgrade", _BEFORE)
    ids = await _seed(migrated_db)
    try:
        output = migrated_db.alembic("upgrade", _THIS)

        async with migrated_db.engine.begin() as conn:
            roles = dict(
                (await conn.execute(text("SELECT user_id, role FROM user_roles"))).tuples().all()
            )
            assert roles == {
                ids["gone"]: "admin",
                ids["first"]: "admin",
                ids["second"]: "admin",
                ids["proc"]: "processor",
            }
            owners = dict(
                (await conn.execute(text("SELECT id, owner_user_id FROM companies"))).tuples().all()
            )
            # The earliest ACTIVE admin: `gone` is earlier but inactive, `second` is later.
            assert owners == {ids["acme"]: ids["first"], ids["beta"]: None}
            assert f"({ids['beta']}) has no active admin" in output
            assert f"({ids['acme']})" not in output
            audited = (
                await conn.execute(
                    text(
                        "SELECT company_id FROM company_audit_log WHERE action = 'role_backfilled'"
                    )
                )
            ).scalars()
            assert sorted(audited) == sorted([ids["acme"], ids["beta"]])
            # The staging window: roles come from `readonly.user_roles`, and `readonly.users` no
            # longer offers the frozen column.
            assert "role" not in await _view_columns(conn, "users")
            assert await _view_columns(conn, "user_roles") == {
                "id",
                "user_id",
                "role",
                "granted_by_user_id",
                "created_at",
            }

            # After the migration the app writes roles only: beta's processor gains ADMIN, and a
            # new user holds only LOAN_OFFICER with `users.role` NULL. Both must come back.
            lo = uuid4()
            await conn.execute(
                text(
                    "INSERT INTO users (id, company_id, email, hashed_password, first_name, "
                    "last_name, is_active, created_at, updated_at) VALUES (:id, :c, :e, 'x', 'F', "
                    "'L', true, now(), now())"
                ),
                {"id": lo, "c": ids["beta"], "e": f"lo-{lo.hex[:6]}@example.com"},
            )
            await conn.execute(
                text(
                    "INSERT INTO user_roles (id, user_id, role, created_at) VALUES "
                    "(gen_random_uuid(), :lo, 'loan_officer', now()), "
                    "(gen_random_uuid(), :proc, 'admin', now())"
                ),
                {"lo": lo, "proc": ids["proc"]},
            )

        migrated_db.alembic("downgrade", _BEFORE)

        async with migrated_db.engine.begin() as conn:
            restored = dict((await conn.execute(text("SELECT id, role FROM users"))).tuples().all())
            assert restored == {
                ids["gone"]: "admin",
                ids["first"]: "admin",
                ids["second"]: "admin",
                ids["proc"]: "admin",
                lo: "processor",
            }
            nullable = await conn.scalar(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'users' AND column_name = 'role'"
                )
            )
            assert nullable == "NO"
            left = await conn.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns WHERE "
                    "(table_name = 'companies' AND column_name = 'owner_user_id') "
                    "OR table_name IN ('user_roles', 'company_audit_log')"
                )
            )
            assert left == 0
            assert "role" in await _view_columns(conn, "users")
            assert await _view_columns(conn, "user_roles") == set()
    finally:
        # Leave the shared fixture where it was found: empty and at head.
        async with migrated_db.engine.begin() as conn:
            await conn.execute(text("TRUNCATE companies, users CASCADE"))
        migrated_db.alembic("upgrade", "head")
