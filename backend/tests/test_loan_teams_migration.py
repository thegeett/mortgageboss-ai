"""The LP-MB-Admin-05 migration's backfill, on a database built by migrations.

A file's creator (its FILE_CREATED actor) joins as processor only if still active, not deleted, and
holding PROCESSOR. A file whose creator does not qualify, or with no FILE_CREATED row, stays unassigned.
"""

from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.conftest import MigratedDb

_BEFORE = "6316da7fe522"  # pragma: allowlist secret  (Alembic revision id)
_THIS = "14e94a531fce"  # pragma: allowlist secret  (Alembic revision id)


async def _user(
    conn: AsyncConnection, company: UUID, role: str, *, active: bool = True, deleted: bool = False
) -> UUID:
    uid = uuid4()
    await conn.execute(
        text(
            "INSERT INTO users (id, company_id, email, hashed_password, first_name, last_name, "
            "is_active, deleted_at, created_at, updated_at) VALUES (:id, :c, :e, 'x', 'F', 'L', "
            ":active, CASE WHEN :deleted THEN now() END, now(), now())"
        ),
        {
            "id": uid,
            "c": company,
            "e": f"u-{uid.hex[:8]}@x.com",
            "active": active,
            "deleted": deleted,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO user_roles (id, user_id, role, created_at) VALUES (gen_random_uuid(), :u, :r, now())"
        ),
        {"u": uid, "r": role},
    )
    return uid


async def _file(conn: AsyncConnection, company: UUID, creator: UUID | None) -> UUID:
    fid = uuid4()
    await conn.execute(
        text(
            "INSERT INTO loan_files (id, company_id, display_id, status, inbox_token, created_at, "
            "updated_at) VALUES (:id, :c, :d, 'draft', :t, now(), now())"
        ),
        {"id": fid, "c": company, "d": f"LF-{fid.hex[:6].upper()}", "t": fid.hex},
    )
    if creator is not None:
        await conn.execute(
            text(
                "INSERT INTO activity_logs (id, loan_file_id, activity_type, actor_user_id, summary, "
                "detail, created_at, updated_at) VALUES (gen_random_uuid(), :f, 'file_created', :u, "
                "'created', '{}', now(), now())"
            ),
            {"f": fid, "u": creator},
        )
    return fid


async def test_the_creator_becomes_a_processor_only_if_still_eligible(
    migrated_db: MigratedDb,
) -> None:
    migrated_db.alembic("downgrade", _BEFORE)
    company = uuid4()
    try:
        async with migrated_db.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO companies (id, name, slug, settings, is_active, created_at, "
                    "updated_at) VALUES (:id, 'Acme', :s, '{}', true, now(), now())"
                ),
                {"id": company, "s": f"acme-{company.hex[:6]}"},
            )
            pat = await _user(conn, company, "processor")
            gone = await _user(conn, company, "processor", active=False)
            deleted = await _user(conn, company, "processor", deleted=True)
            admin = await _user(conn, company, "admin")
            files = {
                "pat": await _file(conn, company, pat),
                "gone": await _file(conn, company, gone),
                "deleted": await _file(conn, company, deleted),
                "admin": await _file(conn, company, admin),
                "none": await _file(conn, company, None),
            }

        migrated_db.alembic("upgrade", _THIS)

        async with migrated_db.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT loan_file_id, user_id, team_role, added_by_user_id FROM loan_teams"
                    )
                )
            ).all()
            view = (await conn.execute(text("SELECT count(*) FROM readonly.loan_teams"))).scalar()
        assert [(r.loan_file_id, r.user_id, r.team_role, r.added_by_user_id) for r in rows] == [
            (files["pat"], pat, "processor", None)
        ]
        assert view == 1
    finally:
        async with migrated_db.engine.begin() as conn:
            await conn.execute(text("TRUNCATE companies, users, loan_files CASCADE"))
        migrated_db.alembic("upgrade", "head")
