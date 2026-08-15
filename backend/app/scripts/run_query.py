"""Run ONE read-only SELECT against the deployed database and print the result (C7).

Usage (as a one-off ECS task; see ``./scripts/deploy <env> query``)::

    QUERY_SQL='select count(*) from loan_files' uv run python -m app.scripts.run_query

Environment variables:

    QUERY_SQL         REQUIRED. A single SELECT or WITH statement.
    QUERY_MAX_ROWS    optional, default 100. Caps printed rows.

⚠️ **SQL arrives by ENVIRONMENT, never argv.** A task's argv is readable from
``ecs describe-tasks`` for about an hour after it stops, and the whole
``RunTask`` call is recorded in the CloudTrail event. The same reasoning as
``add_user``'s password hash.

WHAT PROTECTS THE DATA IS THE DATABASE, NOT THIS FILE
-----------------------------------------------------
This connects as ``mbai_readonly``, a role that (C7 migration):

* has NO privileges in schema ``public`` — every base table is unreachable
* sees only ``readonly.*``, a view per table with PII dropped or scrubbed
* runs with ``default_transaction_read_only``, a 30s ``statement_timeout``
  and a 2-connection cap

The single-statement / SELECT-only check below is **defence in depth**, not the
control. It exists so a mistake reads "only a single SELECT is permitted"
instead of a Postgres permission error four layers down. Do not be tempted to
relax the database grants because this check looks sufficient — it is a string
check, and string checks lose.

Raw SSNs and TINs cannot be returned through this path. That is a property of
the view layer, not of anything here.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# A statement is accepted only if it STARTS with SELECT or WITH, after LEADING comments
# and whitespace are stripped. Leading comments are stripped rather than rejected so a
# documented .sql file still runs.
#
# ⚠️ ANCHORED, and the repetition is INSIDE the pattern. Without the `^` this matches
# whitespace anywhere, and stripping it repeatedly collapses `select status` into
# `selectstatus` — which then fails the `\b` below and refuses a perfectly good query.
# That is not hypothetical: it is the bug this comment replaced.
_LEADING_NOISE = re.compile(r"^(?:\s+|--[^\n]*(?:\n|$)|/\*.*?\*/)+", re.DOTALL)
_ALLOWED_START = re.compile(r"^(select|with)\b", re.IGNORECASE)

_MAX_ROWS_DEFAULT = 100
#: A cell longer than this is truncated in the printed table. A single wide JSON column
#: can otherwise bury the result — and every printed line lands in CloudWatch.
_MAX_CELL = 400


class QueryRefused(Exception):
    """The SQL was rejected before any connection was opened."""


def _strip_leading_noise(sql: str) -> str:
    """Drop LEADING whitespace and comments so the first keyword can be checked.

    One anchored substitution, not a loop: the pattern already repeats, and looping over
    an unanchored pattern is what broke this before.
    """
    return _LEADING_NOISE.sub("", sql, count=1)


def validate_sql(raw: str) -> str:
    """Return the statement, or raise :class:`QueryRefused`.

    Rejects anything that is not a single SELECT/WITH. Semicolons are the interesting
    case: one TRAILING semicolon is normal and allowed, but a semicolon with anything
    after it means a second statement, which is refused rather than silently truncated
    — silently running only the first half of what someone wrote is worse than an error.
    """
    sql = raw.strip()
    if not sql:
        raise QueryRefused("QUERY_SQL is empty.")

    body = sql.rstrip().rstrip(";").rstrip()
    if ";" in body:
        raise QueryRefused(
            "Only a single statement is permitted — found a ';' with content after it. "
            "Run the statements separately."
        )

    if not _ALLOWED_START.match(_strip_leading_noise(body)):
        raise QueryRefused(
            "Only a single SELECT (or WITH ... SELECT) is permitted. "
            "This path is read-only by database grant; write statements will also be "
            "rejected by PostgreSQL."
        )
    return body


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    s = str(value)
    return s if len(s) <= _MAX_CELL else f"{s[:_MAX_CELL]}… [truncated]"


def render_table(columns: list[str], rows: list[tuple[Any, ...]]) -> str:
    """A fixed-width table. No dependency on a formatting library for one script."""
    if not columns:
        return "(no columns)"
    cells = [[_fmt(v) for v in row] for row in rows]
    widths = [
        max(len(col), *(len(r[i]) for r in cells)) if cells else len(col)
        for i, col in enumerate(columns)
    ]
    sep = "-+-".join("-" * w for w in widths)
    head = " | ".join(col.ljust(widths[i]) for i, col in enumerate(columns))
    body = [" | ".join(c.ljust(widths[i]) for i, c in enumerate(row)) for row in cells]
    return "\n".join([head, sep, *body])


async def _run() -> int:
    raw_sql = os.getenv("QUERY_SQL")
    if raw_sql is None:
        print("QUERY_SQL is not set.", file=sys.stderr)
        return 2

    try:
        sql = validate_sql(raw_sql)
    except QueryRefused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2

    try:
        max_rows = int(os.getenv("QUERY_MAX_ROWS", str(_MAX_ROWS_DEFAULT)))
    except ValueError:
        print("QUERY_MAX_ROWS must be an integer.", file=sys.stderr)
        return 2
    if max_rows < 1:
        print("QUERY_MAX_ROWS must be >= 1.", file=sys.stderr)
        return 2

    # Echoed BEFORE running, so a query that times out or errors is still attributable
    # in CloudWatch — the log is the audit record for this path.
    print("--- SQL ---")
    print(sql)
    print("--- RESULT ---")

    url = _readonly_database_url()
    engine = create_async_engine(url, poolclass=None, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            result = await session.execute(text(sql))
            columns = list(result.keys())
            # +1 so "more rows exist" is detectable without a second count query.
            rows = result.fetchmany(max_rows + 1)
            truncated = len(rows) > max_rows
            rows = rows[:max_rows]

            print(render_table(columns, [tuple(r) for r in rows]))
            print()
            if truncated:
                print(f"({max_rows} rows shown; more exist — raise QUERY_MAX_ROWS to see them)")
            else:
                print(f"({len(rows)} row{'' if len(rows) == 1 else 's'})")
    except Exception as exc:
        # Deliberately not re-raised: a traceback buries the one line that matters.
        print(f"Query failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()

    return 0


def _readonly_database_url() -> str:
    """The connection URL for the read-only role.

    ``QUERY_DATABASE_URL`` wins when set (local testing, and the escape hatch if IAM
    auth is ever unavailable). Otherwise the URL is derived from the task's own
    ``DATABASE_URL`` by swapping in the read-only user and an IAM auth token, so the
    task definition needs no second secret.
    """
    override = os.getenv("QUERY_DATABASE_URL")
    if override:
        return override

    base = os.getenv("DATABASE_URL")
    if not base:
        raise RuntimeError("Neither QUERY_DATABASE_URL nor DATABASE_URL is set.")

    from sqlalchemy.engine import make_url

    url = make_url(base)
    user = os.getenv("QUERY_DB_USER", "mbai_readonly")
    token = _iam_auth_token(host=url.host or "", port=url.port or 5432, user=user)
    return str(url.set(username=user, password=token))


def _iam_auth_token(*, host: str, port: int, user: str) -> str:
    """A 15-minute RDS IAM auth token for ``user``.

    Requires ``rds-db:connect`` on the dbuser resource ARN for the task role, and
    ``GRANT rds_iam`` on the role (both in C7). No password is stored anywhere.
    """
    import boto3

    session = boto3.Session()
    client = session.client("rds")
    return str(client.generate_db_auth_token(DBHostname=host, Port=port, DBUsername=user))


def main() -> None:
    try:
        sys.exit(asyncio.run(_run()))
    except KeyboardInterrupt:  # pragma: no cover - operator interrupt
        sys.exit(130)


if __name__ == "__main__":
    main()
