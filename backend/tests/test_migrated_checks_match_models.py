"""A MIGRATED database's CHECK constraints must say what the models say (LP-912 review).

THE BLIND SPOT THIS CLOSES. The suite builds its schema with `Base.metadata.create_all` (ADR-039), and
every other migration guard here reads migration files as TEXT (`test_activity_type_migrations.py`).
Neither ever sees a database that `alembic upgrade head` produced. LP-912 found what lives in that gap:

- LP-904 declared its CHECKs as `sa.CheckConstraint(name="ck_conditions_...")` inside `create_table`,
  and `Base.metadata`'s naming convention prefixed them AGAIN, so a migrated database holds
  `ck_conditions_ck_conditions_...` while the suite's holds `ck_conditions_...`.
- LP-909's swap then added the single-prefixed event-kind constraint beside the doubled one. A
  column's CHECKs are ANDed, so `round_reparse_requested` was rejected on every migrated database, and
  the whole suite was green. Measured by this review: at `b6d1e93f57ac`, `condition_events.kind` carries
  two CHECKs and only one of them admits that value.

So this migrates a scratch database for real and compares it with the suite's own `create_all`
database, COLUMN BY COLUMN, and since LP-932 by NAME as well. When this was written, 24 names differed,
and the value comparison was deliberately keyed on the column rather than the name. LP-932 renamed
all 24, so the third check below now holds too:

1. **No column carries two CHECKs** in the migrated database. That is the LP-909 shape exactly, and it
   is also what the next swap by the "wrong" spelling of a doubled name would produce.
2. **Every column the models constrain is constrained the same way** after migrating, and vice versa:
   the same value set for an enum CHECK, the same expression otherwise. A missing migration, a swap
   that revoked a value, or a CHECK that exists only in the suite all fail here.
3. **Every CHECK carries the name the models give it** (LP-932). A swap is written against a name, so
   a name that differs between the two databases is where the next LP-909 comes from: dropping the
   model's name on a migrated database drops nothing, and the new CHECK lands beside the old one.

It costs one `alembic upgrade head` (about 13 s on the slowest machine this runs on). That is the price
of the only check in the suite that reads what production actually has.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from tests.conftest import _test_database_url

_BACKEND = Path(__file__).resolve().parent.parent

#: Every CHECK on a `public` table, with the column(s) it constrains, read from the catalog rather
#: than parsed out of its name.
_CHECKS = text(
    """
    SELECT t.relname AS table_name,
           array_agg(a.attname ORDER BY a.attname) AS columns,
           c.conname AS name,
           pg_get_constraintdef(c.oid) AS definition
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
    WHERE c.contype = 'c' AND n.nspname = 'public'
    GROUP BY t.relname, c.conname, c.oid
    """
)

#: CHECKs the models declare that NO migration ever created. Empty since LP-931, which created the
#: three this test found on its first run (`communications.body_format`, `users.mail_client`,
#: `validation_verdicts.kind`). Kept as the place to record the next one as a decision rather than a
#: silent gap; the test fails on a stale entry.
#:
#: AN ENTRY HERE HIDES THE COLUMN FROM BOTH COMPARISONS, not just the value one (LP-932 review). The
#: value test subtracts this set, and the name test skips any column constrained on one side only, so a
#: parked column's name is not checked either. Say so in the entry's comment when adding one.
_KNOWN_MISSING: frozenset[tuple[str, tuple[str, ...]]] = frozenset()


def _shape(definition: str) -> object:
    """What a CHECK permits: its quoted literals as a set for an enum, else the whole expression.

    A set, because a swap may list the values in any order (`test_activity_type_migrations.py` makes
    the same allowance) and Postgres renders `IN (...)` and `= ANY (ARRAY[...])` alike.
    """
    literals = re.findall(r"'([^']*)'", definition)
    return frozenset(literals) if literals else definition


async def _checks(engine: AsyncEngine) -> list[tuple[str, tuple[str, ...], str, str]]:
    async with engine.connect() as conn:
        rows = (await conn.execute(_CHECKS)).all()
    return [(row.table_name, tuple(row.columns), row.name, row.definition) for row in rows]


def _by_column(
    checks: list[tuple[str, tuple[str, ...], str, str]],
) -> dict[tuple[str, tuple[str, ...]], list[tuple[str, object]]]:
    grouped: dict[tuple[str, tuple[str, ...]], list[tuple[str, object]]] = defaultdict(list)
    for table, columns, name, definition in checks:
        grouped[(table, columns)].append((name, _shape(definition)))
    return grouped


@pytest_asyncio.fixture(scope="module")
async def migrated_engine() -> AsyncIterator[AsyncEngine]:
    """A scratch database built by `alembic upgrade head`, dropped afterwards.

    Named after the test database, never the dev one, and created through the same maintenance
    connection `conftest` uses. Alembic runs in a subprocess because `alembic/env.py` reads the URL
    from settings at import time; `DATABASE_URL` in the child's environment is how it is pointed here.
    """
    test_url = _test_database_url()
    url: URL = test_url.set(database=f"{test_url.database}_migrated")
    admin = create_async_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}"'))
        await conn.execute(text(f'CREATE DATABASE "{url.database}"'))

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_BACKEND,
        env={**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"alembic upgrade head failed:\n{result.stderr[-4000:]}"

    engine = create_async_engine(url, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}"'))
        await admin.dispose()


async def test_no_column_carries_two_checks_after_migrating(migrated_engine: AsyncEngine) -> None:
    """The LP-909 defect, stated as the property it broke: one CHECK per column.

    Two CHECKs on one column are ANDed, so the narrower one silently wins. That is how
    `round_reparse_requested` became unwritable while its own migration added it.
    """
    grouped = _by_column(await _checks(migrated_engine))

    doubled = {key: [name for name, _ in found] for key, found in grouped.items() if len(found) > 1}

    assert not doubled, (
        f"these columns carry more than one CHECK on a migrated database, and Postgres ANDs them: "
        f"{doubled}. Usually a swap dropped one spelling of a constraint name while another survived "
        "(LP-904's names are doubled by the naming convention on a migrated database)."
    )


async def test_every_check_the_models_declare_is_what_migrating_installs(
    migrated_engine: AsyncEngine, test_engine: AsyncEngine
) -> None:
    """Column by column, the migrated database permits exactly what `create_all` permits."""
    migrated = {
        key: shapes[0][1] for key, shapes in _by_column(await _checks(migrated_engine)).items()
    }
    modelled = {key: shapes[0][1] for key, shapes in _by_column(await _checks(test_engine)).items()}

    missing = sorted(set(modelled) - set(migrated) - _KNOWN_MISSING)
    only_migrated = sorted(set(migrated) - set(modelled))
    differ = sorted(
        (key, sorted(map(str, modelled[key])), sorted(map(str, migrated[key])))
        for key in set(modelled) & set(migrated)
        if modelled[key] != migrated[key]
    )
    stale = sorted(key for key in _KNOWN_MISSING if key in migrated or key not in modelled)

    assert not missing, (
        f"the models constrain these columns and no migration does, so a migrated database accepts "
        f"anything there: {missing}"
    )
    assert not only_migrated, (
        f"a migration constrains these columns and the models do not: {only_migrated}"
    )
    assert not differ, f"(column, models permit, migrated permits) disagree: {differ}"
    assert not stale, f"_KNOWN_MISSING lists entries that are no longer missing: {stale}"


async def test_every_check_carries_the_name_the_models_give_it(
    migrated_engine: AsyncEngine, test_engine: AsyncEngine
) -> None:
    """Column by column, the migrated CHECK is NAMED what `create_all` names it (LP-932).

    Compared per column rather than as two sets of names, so a failure says which column and both
    names, which is what a fixing migration needs. A column constrained on one side only is left to
    the test above, which already reports it as missing or extra.
    """
    migrated = _by_column(await _checks(migrated_engine))
    modelled = _by_column(await _checks(test_engine))

    misnamed = []
    for (table, columns), found in sorted(modelled.items()):
        if (table, columns) not in migrated:
            continue
        model_names = sorted(name for name, _ in found)
        migrated_names = sorted(name for name, _ in migrated[(table, columns)])
        if migrated_names != model_names:
            misnamed.append((table, columns, migrated_names, model_names))

    assert not misnamed, (
        "(table, column, migrated name, model name) differ, so a swap written against the model's name "
        f"would miss the migrated constraint and add a second CHECK beside it: {misnamed}. Rename it "
        "with raw ALTER TABLE ... RENAME CONSTRAINT, as LP-932 did."
    )


@pytest.mark.parametrize(
    ("definition", "expected"),
    [
        ("CHECK (((kind)::text = ANY ((ARRAY['b'::character varying, 'a'::character varying])::text[])))", frozenset({"a", "b"})),
        ("CHECK (((confidence >= (0)::numeric) AND (confidence <= (1)::numeric)))", "CHECK (((confidence >= (0)::numeric) AND (confidence <= (1)::numeric)))"),
    ],
)  # fmt: skip
def test_shape_compares_enum_checks_as_sets_and_others_whole(
    definition: str, expected: object
) -> None:
    assert _shape(definition) == expected
