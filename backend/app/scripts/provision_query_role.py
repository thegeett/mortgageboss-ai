"""Create (or drop) the read-only query role in a deployed environment (C7).

Usage (as a one-off ECS task; see ``./scripts/deploy <env> query-setup``)::

    uv run python -m app.scripts.provision_query_role
    PROVISION_QUERY_ROLE_DROP=1 uv run python -m app.scripts.provision_query_role

Environment variables:

    PROVISION_QUERY_ROLE_ENVIRONMENTS   comma-separated, defaults to "staging"
    PROVISION_QUERY_ROLE_ENVIRONMENT    the environment this run is against, REQUIRED
    PROVISION_QUERY_ROLE_DROP           set to drop the role instead of creating it

WHY THIS IS NOT IN THE MIGRATION
--------------------------------
Migrations run in EVERY environment. The C7 migration therefore creates only the
``readonly`` schema and its views — safe everywhere, because a view with no grantee
grants nothing to anyone. The LOGIN ROLE is the part that must not exist in production,
so it lives here, behind an environment allowlist, and is created only where someone
deliberately runs this.

In an environment where this has never run, ``readonly.*`` exists and nothing can select
from it. That is the intended resting state for production.

⚠️ The role has NO PASSWORD, in any environment. On RDS it authenticates with a
15-minute IAM token, which requires ``rds-db:connect`` on its dbuser ARN — a permission
Terraform grants only where ``db_instance_resource_id`` is wired. Two independent gates,
neither of which is this script.
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

ROLE = "mbai_readonly"
SCHEMA = "readonly"

_DEFAULT_ENVIRONMENTS = "staging"

# Applied in order. Every statement is idempotent, so a re-run repairs drift rather than
# failing — this is the script someone reaches for when something looks wrong.
_GRANTS: tuple[str, ...] = (
    f"GRANT CONNECT ON DATABASE {{database}} TO {ROLE}",
    f"GRANT USAGE ON SCHEMA {SCHEMA} TO {ROLE}",
    f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {ROLE}",
    f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} GRANT SELECT ON TABLES TO {ROLE}",
    # THE LOAD-BEARING PAIR. Without these the role reaches base tables directly through
    # public.<table> and every view is decoration. The search_path pin matters as much as
    # the revoke: it is what makes an unqualified `SELECT ... FROM extractions` resolve to
    # the VIEW rather than the table.
    f"REVOKE ALL ON SCHEMA public FROM {ROLE}",
    f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE}",
    f"ALTER ROLE {ROLE} SET search_path = {SCHEMA}",
    # Belt and braces: a write fails even if a grant above is wrong, a runaway query is
    # bounded, and a stuck session cannot eat the connections the application needs.
    f"ALTER ROLE {ROLE} SET default_transaction_read_only = on",
    f"ALTER ROLE {ROLE} SET statement_timeout = '30s'",
    f"ALTER ROLE {ROLE} CONNECTION LIMIT 2",
)


def _allowed_environments() -> list[str]:
    raw = os.getenv("PROVISION_QUERY_ROLE_ENVIRONMENTS", _DEFAULT_ENVIRONMENTS)
    return [e.strip() for e in raw.split(",") if e.strip()]


def _require_allowed_environment() -> str:
    env = (os.getenv("PROVISION_QUERY_ROLE_ENVIRONMENT") or "").strip()
    if not env:
        raise SystemExit(
            "REFUSED: PROVISION_QUERY_ROLE_ENVIRONMENT is not set. This script will not "
            "guess which environment it is running against."
        )
    allowed = _allowed_environments()
    if env not in allowed:
        raise SystemExit(
            f"REFUSED: the read-only query role is not enabled for environment {env!r}. "
            f"Permitted: {', '.join(allowed)}. This role exists so a debugging path can "
            "read loan data; the environments it may exist in are listed explicitly."
        )
    return env


async def _provision(drop: bool) -> int:
    env = _require_allowed_environment()
    url = str(settings.database_url)
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")

    try:
        async with engine.connect() as conn:
            database = await conn.scalar(text("SELECT current_database()"))
            assert isinstance(database, str)

            if drop:
                exists = await conn.scalar(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": ROLE}
                )
                if not exists:
                    print(f"{ROLE} does not exist in {env}. Nothing to drop.")
                    return 0
                # Privileges must come off before a role can be dropped.
                await conn.execute(text(f"REVOKE ALL ON SCHEMA public FROM {ROLE}"))
                await conn.execute(
                    text(
                        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} "
                        f"REVOKE SELECT ON TABLES FROM {ROLE}"
                    )
                )
                await conn.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA {SCHEMA} FROM {ROLE}"))
                await conn.execute(text(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM {ROLE}"))
                await conn.execute(text(f"REVOKE CONNECT ON DATABASE {database} FROM {ROLE}"))
                await conn.execute(text(f"DROP ROLE {ROLE}"))
                print(f"Dropped {ROLE} in {env}.")
                return 0

            schema_exists = await conn.scalar(
                text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"),
                {"s": SCHEMA},
            )
            if not schema_exists:
                print(
                    f"REFUSED: schema {SCHEMA!r} does not exist. Run the migration first "
                    "(./scripts/deploy <env> migrate) — the role is useless without the "
                    "views, and creating it now would leave a login role with nothing to "
                    "read.",
                    file=sys.stderr,
                )
                return 1

            # NOLOGIN would be safer still, but RDS IAM authentication requires LOGIN.
            # There is no password: authentication is the IAM token alone.
            await conn.execute(
                text(f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                            CREATE ROLE {ROLE} LOGIN;
                        END IF;
                    END
                    $$;
                """)
            )

            for statement in _GRANTS:
                await conn.execute(text(statement.format(database=database)))

            # RDS only. ``rds_iam`` does not exist on a plain PostgreSQL, and the same
            # script has to work in both places.
            granted_iam = await conn.scalar(
                text("SELECT 1 FROM pg_roles WHERE rolname = 'rds_iam'")
            )
            if granted_iam:
                await conn.execute(text(f"GRANT rds_iam TO {ROLE}"))

            print(f"Provisioned {ROLE} in {env} (database {database}).")
            print(f"  IAM authentication : {'enabled' if granted_iam else 'not available'}")
            print("  password           : none, deliberately")
            print(f"  reachable schemas  : {SCHEMA} only (no privileges in public)")
    finally:
        await engine.dispose()

    return 0


def main() -> None:
    drop = bool(os.getenv("PROVISION_QUERY_ROLE_DROP"))
    try:
        sys.exit(asyncio.run(_provision(drop)))
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
