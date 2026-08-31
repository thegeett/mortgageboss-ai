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


#: JSON documents whose NUMBERS previously took the whole view down. ``scrub(v::text)::json``
#: rewrote a 9+ digit run inside a number to a bare ``[REDACTED-ID]`` token and the cast back
#: raised — for the SELECT, not the cell — so one such row anywhere returned nothing at all.
#: The second element is the value that must still be readable afterwards.
_JSON_NUMBER_CASES: tuple[tuple[str, str], ...] = (
    ("a big integer", '{"tokens_used": 123456789}'),
    ("an epoch-millisecond timestamp", '{"epoch_ms": 1755212345678}'),
    ("a float repr with 16 fraction digits", '{"confidence": 0.8500000000000001}'),
    ("a round hundred million", '{"n": 100000000}'),
    ("a negative identifier-length integer", '{"delta": -123456789}'),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("label", "payload"), _JSON_NUMBER_CASES)
async def test_scrub_json_survives_numbers(
    test_engine: AsyncEngine, label: str, payload: str
) -> None:
    """A number in the document must not make the JSON unparseable."""
    module = _migration_module()
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("CREATE SCHEMA IF NOT EXISTS readonly"))
        await conn.execute(sa.text(module._SCRUB_FN))  # type: ignore[attr-defined]
        await conn.execute(sa.text(module._SCRUB_JSON_FN))  # type: ignore[attr-defined]
        await conn.execute(sa.text(module._SCRUB_JSONB_FN))  # type: ignore[attr-defined]

        for fn, cast in (("scrub_json", "json"), ("scrub_jsonb", "jsonb")):
            got = await conn.scalar(
                sa.text(f"SELECT readonly.{fn}(CAST(:v AS {cast}))::text"), {"v": payload}
            )
            assert got is not None, f"{label}: {fn} returned NULL"


@pytest.mark.asyncio
async def test_scrub_json_keeps_debugging_numbers_and_redacts_numeric_identifiers(
    test_engine: AsyncEngine,
) -> None:
    """Numbers are kept, EXCEPT an identifier-shaped integer.

    A number cannot hold the marker and stay a number, so a 9+ digit integer becomes the
    string marker — the redaction the text-based version intended, without the broken JSON.
    Fractional values are left alone: no identifier is fractional, and the digit-run pattern
    would otherwise eat the fraction digits of an ordinary float.
    """
    module = _migration_module()
    payload = (
        '{"cost": 0.02, "confidence": 0.8500000000000001, "tokens": 12345,'
        ' "tin_as_number": 123456789, "amount": 350000.00}'
    )
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("CREATE SCHEMA IF NOT EXISTS readonly"))
        await conn.execute(sa.text(module._SCRUB_FN))  # type: ignore[attr-defined]
        await conn.execute(sa.text(module._SCRUB_JSON_FN))  # type: ignore[attr-defined]
        got = await conn.scalar(
            sa.text("SELECT readonly.scrub_json(CAST(:v AS json))::text"), {"v": payload}
        )

    assert got is not None
    assert "0.8500000000000001" in got, "a float repr was mangled"
    assert "0.02" in got and "12345" in got, "ordinary numbers must survive"
    assert "350000.00" in got, "an amount was redacted"
    assert "123456789" not in got, "a numeric identifier leaked"
    assert "[REDACTED-ID]" in got


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
    # document_name (LP-636) joins summary/generic_analysis for the same reason: model
    # prose over the document, and the scrub matches identifier shapes, not names.
    "documents": frozenset(
        {"full_text", "generic_analysis", "summary", "storage_path", "document_name"}
    ),
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
    # LP-636. Listing it in EXCLUDED only RECORDS the decision: a later migration that adds
    # it to a view would pass both drift tests and silently turn that entry into a stale
    # comment. This asserts absence from every view, so the decision cannot be undone
    # quietly. It is here rather than only in EXCLUDED because the argument for excluding it
    # is the strong form — the scrub matches identifier SHAPES, and a person's name is not
    # digit-shaped, so a name in this column would cross a view intact.
    ("documents", "document_name"),
    ("mismo_imports", "catch_all"),
    ("borrowers", "ssn"),
    ("users", "hashed_password"),
    ("loan_files", "inbox_token"),
    ("findings", "source_snippet"),
    ("communications", "body"),
)


def _later_view_redefinitions() -> dict[str, str]:
    """``{table: view text}`` for views a migration AFTER C7 recreates (LP-509-B1).

    A view is not frozen at C7. A later migration that adds a column has to rebuild the view to
    expose it, and reading only C7 would then check the drift guard against a definition the
    database no longer has — reporting the new column as unexposed when it is exposed, or worse,
    passing while a rebuilt view quietly dropped one.

    Scanned as TEXT across the versions directory rather than by importing: these modules import
    `alembic.op`, which is only bound inside a migration run. Later revisions win, and among them
    the last by filename — the versions are date-prefixed, so filename order is apply order.
    """
    bodies: dict[str, str] = {}
    for path in sorted(_MIGRATION.parent.glob("*.py")):
        if path.name <= _MIGRATION.name:
            continue
        # The schema is written either literally or as the `{_SCHEMA}` placeholder of an f-string —
        # C7 uses the placeholder and so do its successors, and this reads the file as TEXT, so the
        # placeholder is never substituted. Both spellings are accepted rather than requiring one,
        # so a migration that follows C7's own style is not silently skipped by this scan.
        # Only the UPGRADE body describes the live database. A downgrade that recreates the
        # previous shape is also a `CREATE ... VIEW` in the same file, and reading the whole file
        # let the ROLLBACK definition win — reporting a freshly exposed column as unexposed.
        text = path.read_text(encoding="utf-8")
        # ANCHORED TO THE START OF A LINE. Splitting on the bare substring let a DOCSTRING that
        # quoted the marker truncate the slice above the file's own SQL — the migration then
        # contributed nothing and the guard silently kept checking C7's definition. A function
        # definition is at column 0 and a docstring mention is indented, so anchoring removes that
        # trap at the root rather than detecting it afterwards.
        upgrade_body = re.split(r"^def downgrade\(", text, maxsplit=1, flags=re.MULTILINE)[0]
        seen_here: set[str] = set()
        for view in re.findall(
            # LP-568: `CREATE OR REPLACE VIEW` counts too. Appending a column is the one view
            # change Postgres allows without a drop, so it is the natural way to expose a new
            # column — and matching only the bare `CREATE VIEW` spelling made those rebuilds
            # INVISIBLE here. That is the failure this scanner exists to prevent, in reverse: a
            # replace that quietly dropped a column would have passed the guard unnoticed.
            r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:readonly|\{_SCHEMA\})\.\w+\s+AS\s+"
            r"(SELECT.*?FROM\s+public\.\w+)",
            upgrade_body,
            re.DOTALL | re.IGNORECASE,
        ):
            match = re.search(r"FROM\s+public\.(\w+)", view)
            assert match, f"view without a public.<table> source in {path.name}"
            table = match.group(1)
            # THE OTHER TRAP, caught precisely. Hoisting both statements to module constants puts
            # the ROLLBACK one above the split too, where it overwrites the live definition and the
            # guard reports a freshly scrubbed column as bare. A legitimate upgrade never defines
            # one view twice above the split, so a repeat is unambiguous — unlike a whole-file
            # search, which also fires on a migration that only recreates a view in its DOWNGRADE
            # and on prose that merely quotes the SQL.
            if table in seen_here:
                raise AssertionError(
                    f"{path.name} defines readonly.{table} twice above its rollback function. "
                    "That is usually view SQL hoisted to module constants: the rollback statement "
                    "lands in the slice this scan reads as live and wins, so the drift guard "
                    "checks a definition the database does not have. Keep each statement inside "
                    "the function that runs it."
                )
            seen_here.add(table)
            bodies[table] = view

    return bodies


def _view_bodies() -> dict[str, str]:
    """``{table: the SELECT ... FROM public.<table> text}`` as the database has it TODAY.

    C7 defines the 32 views; a later migration may recreate one, and that later definition is the
    live one (see :func:`_later_view_redefinitions`).
    """
    module = _migration_module()
    bodies: dict[str, str] = {}
    for view in module._VIEWS:  # type: ignore[attr-defined]
        match = re.search(r"FROM\s+public\.(\w+)", view)
        assert match, f"view without a public.<table> source: {view[:80]}"
        bodies[match.group(1)] = view
    bodies.update(_later_view_redefinitions())
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
    """The highest-consequence columns, asserted against EVERY view.

    Every one, not just the view sourced from that table: a column reaches a result set
    through whichever view selects it, so a join, a renamed table or a second view over
    the same base table would carry it past a per-table check.
    """
    bodies = _view_bodies()
    assert table in bodies, f"no readonly view for {table}"

    exposed_by = [
        source
        for source, body in bodies.items()
        if re.search(rf"\b{re.escape(column)}\b", body.split("FROM")[0]) is not None
    ]
    assert not exposed_by, (
        f"{table}.{column} is exposed by the readonly view(s) for {sorted(exposed_by)}. "
        "This column can carry a raw identifier; it must never be selectable."
    )


# --------------------------------------------------------------------------- #
# 4. The connection URL — the IAM token must reach asyncpg intact
# --------------------------------------------------------------------------- #

#: The shape of a real RDS IAM auth token: a host, then a signed query string carrying
#: `%2F`, `=`, `+` and `/`. Every one of those is a character a URL round trip can re-quote.
_FAKE_TOKEN = (
    "mbai-staging.c45amqau4ov5.us-east-1.rds.amazonaws.com:5432/?Action=connect"
    "&DBUser=mbai_readonly&X-Amz-Algorithm=AWS4-HMAC-SHA256"
    "&X-Amz-Credential=ASIA123%2F20260815%2Fus-east-1%2Frds-db%2Faws4_request"
    "&X-Amz-Signature=ab+cd/ef=gh"
)


def test_readonly_url_carries_the_token_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    """The token must survive as the password, uncensored and unmangled.

    This is the regression that made the query stage unusable: the function ended with
    ``str(url.set(password=token))``, and ``URL.__str__`` hides the password by default —
    so asyncpg was handed the literal ``***``. PostgreSQL answered ``PAM authentication
    failed``, which looks exactly like a rejected token or a missing ``rds-db:connect``
    grant, and cost an investigation to tell apart (docs/findings/query-stage-auth.md).
    """
    from app.scripts import run_query

    monkeypatch.delenv("QUERY_DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://mbai_admin:secret@db.example.com:5432/mortgageboss"  # pragma: allowlist secret
        "?ssl=verify-full",
    )
    monkeypatch.setattr(run_query, "_iam_auth_token", lambda **_: _FAKE_TOKEN)

    url = run_query._readonly_database_url()

    assert url.password == _FAKE_TOKEN, "the IAM token was altered on the way to asyncpg"
    assert url.password != "***", "the token was replaced by the hidden-password marker"
    assert url.username == "mbai_readonly"
    assert url.host == "db.example.com", "the token is signed over the host — it must match"
    assert url.port == 5432
    assert dict(url.query) == {"ssl": "verify-full"}, "IAM auth requires SSL"

    # And it survives a render/parse cycle, so passing it on as a string stays safe.
    from sqlalchemy.engine import make_url

    assert make_url(url.render_as_string(hide_password=False)).password == _FAKE_TOKEN


def test_readonly_url_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """QUERY_DATABASE_URL is the escape hatch; it must not go near the IAM path."""
    from app.scripts import run_query

    monkeypatch.setenv(
        "QUERY_DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d"
    )  # pragma: allowlist secret
    monkeypatch.setattr(
        run_query,
        "_iam_auth_token",
        lambda **_: pytest.fail("the override must not generate an IAM token"),
    )

    url = run_query._readonly_database_url()
    assert url.username == "u"
    assert url.password == "p"  # pragma: allowlist secret
    assert url.host == "h"


# --------------------------------------------------------------------------- #
# 5. run_query's statement guard (defence in depth, not the control)
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
        # A ';' inside a string literal or a comment is not a second statement. Reading
        # the raw text refused these, and the operator had to work around the guard.
        "select id from findings where message like '%;%'",
        "-- count things; fast\nselect 1",
        "select 1 /* a; b */",
        "select 'it''s here; really' as quoted",
        # Write VERBS inside a literal or an identifier are equally not writes.
        "select id from rules where rule_id like '%delete%'",
        # ...and a column whose name merely starts with one is untouched by \\b.
        "select created_at, updated_at, deleted_at from findings",
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
        # A data-modifying CTE starts with a legal `with`, so only the verb scan catches it.
        "with x as (delete from findings returning 1) select * from x",
        "with x as (insert into findings (id) values (gen_random_uuid()) returning id)"
        " select * from x",
        "with x as (update loan_files set status = 'x' returning id) select * from x",
    ],
)
def test_validate_sql_refuses_everything_else(sql: str) -> None:
    from app.scripts.run_query import QueryRefused, validate_sql

    with pytest.raises(QueryRefused):
        validate_sql(sql)


# --------------------------------------------------------------------------- #
# LP-635 — a run's failure reason is scrubbed like every other free-text column
# --------------------------------------------------------------------------- #
def test_a_runs_error_detail_is_scrubbed() -> None:
    """C7 scrubs `error_detail` on `readonly.communications` and selected the identically-named
    column BARE on `readonly.verifications`.

    That was defensible while only this repo's own composed strings reached it. LP-635 widened who
    writes it: `_failure_detail` asks an exception to explain itself through `user_detail` and writes
    the result verbatim, so the column's safety became a promise about every exception that might
    ever define that attribute — the shape we removed from `AiBackendUnavailable`'s constructor,
    reappearing one level up at the protocol.
    """
    view = _view_bodies()["verifications"]
    assert re.search(r"scrub\(\s*error_detail\s*\)", view), (
        "verifications.error_detail is selected bare; a reason written from an exception would "
        "reach a transcript unredacted"
    )


def test_scrubbing_does_not_damage_the_reasons_a_processor_reads() -> None:
    """The other half, and why this was close to free: `scrub` redacts identifier SHAPES, so the
    failure messages LP-635 composes pass through untouched.

    READ FROM THE SHIPPED VALUES, not from copies. The first version of this test hand-copied the
    three strings, and one had already drifted — a third sentence was added to the timeout message
    in a later round and the copy never grew it. So the untested tail could acquire something
    scrub-shaped ("raise it with support (ref 8005551234)") and be redacted in the one field a
    processor reads, while this test went on passing. A test that names a mechanism has to exercise
    the real thing.
    """
    from app.tasks.verification_rules import _FAILURE_DETAIL, _failure_detail
    from app.verification.tag_materialization.breaker import AiBackendUnavailable

    messages = (
        *_FAILURE_DETAIL.values(),
        str(AiBackendUnavailable(consecutive=5)),
        _failure_detail(RuntimeError("anything")),  # the generic fallback line
    )
    assert len(messages) >= 3, "the failure messages moved — this test is no longer reading them"

    ssn_like = re.compile(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b|\b\d{9,}\b")
    for message in messages:
        assert not ssn_like.search(message), f"scrub would redact part of: {message!r}"


def test_an_extractions_error_detail_is_scrubbed() -> None:
    """THE SIBLING OF THE COLUMN ABOVE, and the one carrying the most sensitive text of the three.

    There are three `error_detail` columns in the readonly schema. C7 scrubbed exactly one
    (`communications`); round 4 fixed `verifications`; this is `extractions`, and it is written from
    `failure_detail(status, reasoning)` — the model's FREE TEXT for why an extraction failed.

    The codebase already knows what that can contain. `document_processing.py` refuses to put it in
    the document's `processing_error` because "for an all-null-parse FAILED it is the model's
    free-text reasoning and can quote document details", and sends it here instead as "THE
    ACCESS-CONTROLLED PLACE FOR IT". That reasoning only holds if it is actually access-controlled;
    through this view it was not, and the query stage returns rows into a terminal and a transcript.
    """
    view = _view_bodies()["extractions"]
    assert re.search(r"scrub\(\s*error_detail\s*\)", view), (
        "extractions.error_detail is selected bare — it holds model prose the pipeline deliberately "
        "keeps out of the UI-shown column, so it must not reach a transcript unredacted"
    )


def test_every_error_detail_in_the_readonly_schema_is_scrubbed() -> None:
    """The property, so the next one is not found one at a time.

    Three columns share this name and three separate migrations decided about them independently —
    which is how two ended up bare while the third was scrubbed. A fourth table with an
    `error_detail` should fail here rather than wait to be noticed.
    """
    unscrubbed = []
    for table, body in _view_bodies().items():
        select_part = body.split("FROM")[0]
        if not re.search(r"\berror_detail\b", select_part):
            continue
        if not re.search(r"scrub\(\s*error_detail\s*\)", select_part):
            unscrubbed.append(table)

    assert not unscrubbed, (
        f"these views select error_detail without scrubbing it: {sorted(unscrubbed)}. It is a "
        "free-text column and free text is where identifiers hide."
    )
