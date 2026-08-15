"""C7 — the read-only query path: the redaction, and the guards that keep it honest.

Three things are worth pinning here, and one thing deliberately is not.

WHAT IS TESTED
    1. ``readonly.scrub`` — the security-critical SQL. Run against a real PostgreSQL,
       because a regex that behaves in Python's engine and not in Postgres's would pass a
       pure-unit test and fail in production. The cases that matter are the two the key-
       based approach misses: a value under a key in NO registry, and a value nested
       inside a list row.
    2. Column drift — every column of every model is either exposed by its view or named
       in this file's exclusion set. A new column on a model fails this test until someone
       decides which it is. Without it, views rot quietly and the pressure is to "just
       grant the base table".
    3. Sensitive columns never appear in a view at all.

WHAT IS NOT TESTED HERE, AND WHY
    The role's privileges. ``mbai_readonly`` is a PostgreSQL ROLE, which is CLUSTER-scoped,
    not database-scoped — creating or dropping it from a test would reach outside the test
    database and race any other connection to the same cluster. The privilege boundary
    (``REVOKE ALL ON SCHEMA public``) is verified manually against the local database and
    recorded in ``docs/tickets/C7-query-stage-result.md``; the drift guards below are what
    keep the *view definitions* honest between those runs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import sqlalchemy as sa
from app.models.base import Base
from sqlalchemy.ext.asyncio import AsyncEngine

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260814_2300_d4e8a1c05b73_c7_readonly_query_schema.py"
)


def _migration_source() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


def _migration_module() -> object:
    """Import the migration module so the tests read the SHIPPED SQL, not a copy."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("c7_migration", _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# 1. The scrub, against a real PostgreSQL
# --------------------------------------------------------------------------- #

# (label, input, expected-to-survive?) — `False` means the value must be redacted.
_SCRUB_CASES: tuple[tuple[str, str, bool], ...] = (
    ("dashed SSN", "123-45-6789", False),
    ("spaced SSN", "123 45 6789", False),
    ("bare 9-digit TIN", "987654321", False),
    ("16-digit card/account", "4111111111111111", False),
    ("10-digit account", "0123456789", False),
    # Survivors: the debugging signal. An amount with cents must not be eaten by the
    # 9+ digit rule — that is what the negative lookahead is for.
    ("dollar amount", "6028.02", True),
    ("large amount with cents", "123456789.01", True),
    ("ISO date", "2025-04-04", True),
    ("percentage", "6.125", True),
    ("8-digit run (below the bar)", "12345678", True),
    ("uuid", "c6047d32-8b38-4ecc-b1ab-0abd0351c851", True),
)


@pytest.mark.asyncio
async def test_scrub_redacts_identifier_shapes_and_keeps_the_rest(
    test_engine: AsyncEngine,
) -> None:
    """The scrub function, exercised in PostgreSQL exactly as shipped."""
    module = _migration_module()
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("CREATE SCHEMA IF NOT EXISTS readonly"))
        await conn.execute(sa.text(module._SCRUB_FN))  # type: ignore[attr-defined]
        await conn.execute(sa.text(module._SCRUB_JSON_FN))  # type: ignore[attr-defined]

        for label, value, should_survive in _SCRUB_CASES:
            got = await conn.scalar(sa.text("SELECT readonly.scrub(:v)"), {"v": value})
            if should_survive:
                assert got == value, f"{label}: {value!r} was redacted but should survive"
            else:
                assert value not in (got or ""), f"{label}: {value!r} survived the scrub"
                assert "[REDACTED-ID]" in (got or ""), f"{label}: no redaction marker"


@pytest.mark.asyncio
async def test_scrub_reaches_unregistered_keys_and_nested_list_rows(
    test_engine: AsyncEngine,
) -> None:
    """The two cases a key-denylist cannot cover.

    ``_PII_FIELDS`` documents its own gap — PII inside a captured LIST row is not routed
    through it — and no key list can cover a field that does not exist yet. Shape matching
    covers both, which is the entire reason the scrub works on serialized text.
    """
    module = _migration_module()
    payload = (
        '{"brand_new_field_in_no_registry": {"value": "555443333"},'
        ' "tradelines": [{"creditor": "CITI", "account_number": "4111111111111111"}],'
        ' "gross_pay": {"value": "6028.02"}}'
    )
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("CREATE SCHEMA IF NOT EXISTS readonly"))
        await conn.execute(sa.text(module._SCRUB_FN))  # type: ignore[attr-defined]
        await conn.execute(sa.text(module._SCRUB_JSON_FN))  # type: ignore[attr-defined]
        got = await conn.scalar(
            sa.text("SELECT readonly.scrub_json(CAST(:v AS json))::text"), {"v": payload}
        )

    assert got is not None
    assert "555443333" not in got, "a field in no registry leaked"
    assert "4111111111111111" not in got, "PII inside a nested list row leaked"
    assert "6028.02" in got, "the debugging signal was destroyed"
    assert "CITI" in got, "a non-identifier value was redacted"


def test_scrub_patterns_match_the_at_rest_guard() -> None:
    """The scrub and the LP-209 at-rest guard must agree by construction.

    They defend the same property from two sides — the guard refuses to WRITE an
    unmasked identifier, the scrub refuses to RETURN one. If the guard's patterns are
    tightened and the scrub's are not, the query path becomes the weaker of the two
    silently. Pinning them together makes that a failing test instead.
    """
    from app.verification.snapshot import persistence

    source = _migration_source()
    assert persistence._RAW_SSN.pattern == r"\b\d{3}-\d{2}-\d{4}\b"
    assert persistence._LONG_DIGITS.pattern == r"\b\d{9,}\b(?!\.\d)"
    # Postgres spells the word boundary \m ... \M; the digit classes must still match.
    assert r"\\d{{3}}-\\d{{2}}-\\d{{4}}" in source or r"\d{3}-\d{2}-\d{4}" in source
    assert r"\\d{{9,}}" in source or r"\d{9,}" in source


# --------------------------------------------------------------------------- #
# 2 + 3. Drift guards over the view definitions
# --------------------------------------------------------------------------- #

#: Columns deliberately kept out of the readonly views, per table. Adding a column to a
#: model and NOT listing it here (or in its view) fails ``test_no_model_column_drifts``.
#: The reason for each is in the migration next to the view.
EXCLUDED: dict[str, frozenset[str]] = {
    "loan_files": frozenset({"inbox_token", "loan_officer_name", "loan_officer_email"}),
    "borrowers": frozenset(
        {
            "first_name",
            "middle_name",
            "last_name",
            "ssn",
            "date_of_birth",
            "email",
            "phone",
            "declarations",
        }
    ),
    "properties": frozenset({"address_line", "address_line_2", "postal_code"}),
    "documents": frozenset({"full_text", "generic_analysis", "summary", "storage_path"}),
    "mismo_imports": frozenset({"catch_all", "raw_file_path"}),
    "findings": frozenset({"source_snippet"}),
    "companies": frozenset({"settings"}),
    "users": frozenset({"hashed_password", "email", "first_name", "last_name"}),
    "lenders": frozenset({"contact_email", "contact_phone"}),
    "communications": frozenset({"sender", "recipient", "subject", "body"}),
}

#: Columns that must NEVER appear in any view, whatever else changes. A belt-and-braces
#: assertion over the whole migration text rather than per table.
NEVER_EXPOSED: tuple[tuple[str, str], ...] = (
    ("documents", "full_text"),
    ("mismo_imports", "catch_all"),
    ("borrowers", "ssn"),
    ("users", "hashed_password"),
    ("loan_files", "inbox_token"),
    ("findings", "source_snippet"),
    ("communications", "body"),
)


def _view_bodies() -> dict[str, str]:
    """``{table: the SELECT ... FROM public.<table> text}`` from the shipped migration."""
    module = _migration_module()
    bodies: dict[str, str] = {}
    for view in module._VIEWS:  # type: ignore[attr-defined]
        match = re.search(r"FROM\s+public\.(\w+)", view)
        assert match, f"view without a public.<table> source: {view[:80]}"
        bodies[match.group(1)] = view
    return bodies


def test_every_view_targets_a_real_table() -> None:
    tables = set(Base.metadata.tables)
    for table in _view_bodies():
        assert table in tables, f"readonly view over unknown table {table!r}"


def test_no_model_column_drifts() -> None:
    """A model column must be exposed by its view or explicitly excluded — never neither.

    This is the test that stops silent rot. When someone adds a column, it fails here
    until they decide, which is exactly when the decision is cheap and reviewable.
    """
    bodies = _view_bodies()
    problems: list[str] = []

    for table_name, view_sql in bodies.items():
        table = Base.metadata.tables[table_name]
        excluded = EXCLUDED.get(table_name, frozenset())
        # The column list is everything before FROM; a bare name or one inside scrub(...).
        select_part = view_sql.split("FROM")[0]
        for column in table.columns:
            name = column.name
            mentioned = re.search(rf"\b{re.escape(name)}\b", select_part) is not None
            if not mentioned and name not in excluded:
                problems.append(f"{table_name}.{name}")

    assert not problems, (
        "These model columns are neither exposed by a readonly view nor listed in "
        "EXCLUDED. Decide for each: expose it, or exclude it and say why in the "
        "migration.\n  " + "\n  ".join(sorted(problems))
    )


def test_excluded_columns_are_real() -> None:
    """An exclusion naming a column that no longer exists is stale — and hides drift."""
    stale: list[str] = []
    for table_name, columns in EXCLUDED.items():
        table = Base.metadata.tables.get(table_name)
        assert table is not None, f"EXCLUDED names unknown table {table_name!r}"
        for name in columns:
            if name not in table.columns:
                stale.append(f"{table_name}.{name}")
    assert not stale, f"EXCLUDED names columns that do not exist: {sorted(stale)}"


@pytest.mark.parametrize(("table", "column"), NEVER_EXPOSED)
def test_never_exposed_columns_are_absent_from_every_view(table: str, column: str) -> None:
    """The highest-consequence columns, asserted against the whole migration text."""
    body = _view_bodies().get(table)
    assert body is not None, f"no readonly view for {table}"
    select_part = body.split("FROM")[0]
    assert re.search(rf"\b{re.escape(column)}\b", select_part) is None, (
        f"{table}.{column} is exposed by the readonly view for {table}. "
        "This column can carry a raw identifier; it must never be selectable."
    )


# --------------------------------------------------------------------------- #
# 4. run_query's statement guard (defence in depth, not the control)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "sql",
    [
        "select 1",
        "SELECT count(*) FROM loan_files",
        # The regression that motivated these tests: an unanchored strip collapsed
        # `select status` to `selectstatus` and refused a valid query.
        "select status, count(*) from verifications group by status order by 2 desc",
        "  \n  select 1",
        "-- why is IN-3 firing?\nselect count(*) from findings",
        "/* a block comment */ select 1",
        "with x as (select 1 as n) select n from x",
        "select 1;",  # one trailing semicolon is fine
    ],
)
def test_validate_sql_accepts_a_single_select(sql: str) -> None:
    from app.scripts.run_query import validate_sql

    assert validate_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "   ",
        "update loan_files set status = 'x'",
        "delete from findings",
        "insert into findings (id) values (gen_random_uuid())",
        "drop view readonly.findings",
        "create table x (i int)",
        "grant select on all tables in schema public to mbai_readonly",
        "select 1; drop table findings",  # a second statement
        "truncate findings",
    ],
)
def test_validate_sql_refuses_everything_else(sql: str) -> None:
    from app.scripts.run_query import QueryRefused, validate_sql

    with pytest.raises(QueryRefused):
        validate_sql(sql)
