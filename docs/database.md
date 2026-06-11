# Database & Migrations

How the database schema is defined, versioned, and evolved in mortgageboss-ai.

The **database is the source of truth** for application data; the AI never
touches it directly (only typed tools). Schema changes are made through
**Alembic migrations** — versioned, reversible, and reviewed.

## Stack

- **PostgreSQL 16** (local via Docker Compose)
- **SQLAlchemy 2.x** (async) — modern `Mapped[...]` / `mapped_column()` models
- **Alembic** — migrations, configured for async (`async_engine_from_config` +
  `connection.run_sync`)

## Declarative base, mixins & naming convention

All models live under `backend/app/models/` and inherit from a single
declarative `Base` (`app/models/base.py`). Common patterns are mixins you
compose onto a model:

| Class / helper | Purpose |
| --- | --- |
| `Base` | Declarative base. Carries the `MetaData` with the constraint **naming convention**. |
| `TimestampMixin` | `created_at` + `updated_at` (tz-aware `timestamptz`, UTC). `updated_at` auto-bumps on update. |
| `SoftDeleteMixin` | `deleted_at` column + `is_deleted` property. Records are marked deleted, not physically removed. |
| `UUIDMixin` | `uuid4` UUID primary key. (loan_files is the exception — see ADR-034/036.) |
| `utcnow()` | Returns a timezone-aware UTC `datetime`. Use this, never naive `datetime.now()`. |

Example model (lands in LP-11+):

```python
from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class Company(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "companies"
    # columns...
```

### Constraint naming convention

`Base.metadata` is created with a naming convention so every constraint gets a
readable, predictable name instead of a database-generated one:

| Type | Template | Example |
| --- | --- | --- |
| Index | `ix_%(column_0_label)s` | `ix_companies_name` |
| Unique | `uq_%(table_name)s_%(column_0_name)s` | `uq_companies_slug` |
| Check | `ck_%(table_name)s_%(constraint_name)s` | `ck_users_role` |
| Foreign key | `fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s` | `fk_users_company_id_companies` |
| Primary key | `pk_%(table_name)s` | `pk_companies` |

This **must** be set before any tables are created — retrofitting it means
migrating every constraint. See **ADR-032**.

### Timestamps are UTC

All timestamps are timezone-aware (`timestamptz`) and stored in UTC. Use the
`utcnow()` helper in Python; convert to local time only at display time (in the
frontend). See **ADR-033**.

## Shared column types

`app/models/types.py` provides annotated column types so precision, scale, and
string lengths stay consistent across the schema. Use them as the `Mapped[...]`
parameter:

```python
from app.models.types import Money, ShortStr

class Account(Base):
    name: Mapped[ShortStr]    # String(64)
    balance: Mapped[Money]    # Numeric(14, 2) → Decimal
```

| Type | Backing column | Use for |
| --- | --- | --- |
| `Money` | `Numeric(14, 2)` | Any currency amount — up to ~1 trillion with cents |
| `ShortStr` | `String(64)` | Names, short codes, slugs |
| `MediumStr` | `String(256)` | Emails, titles, single-line addresses |
| `LongStr` | `String(1024)` | Descriptions, notes, URLs |

> **Money is always `Decimal`, never `float`.** Floats cannot represent decimal
> currency exactly. Handle money as `Decimal` end-to-end. See **ADR-038**.

## Enums

Database-backed enums are Python `StrEnum` subclasses, stored as their **string
value** (`"active"`), not as integers or the member name. Map them with the
`str_enum()` helper from `app/models/enums.py`:

```python
from app.models.enums import RecordStatus, str_enum

status: Mapped[RecordStatus] = mapped_column(
    str_enum(RecordStatus),
    default=RecordStatus.ACTIVE,
    nullable=False,
)
```

`str_enum()` configures the column as a bounded `VARCHAR` with a CHECK
constraint (`native_enum=False`) rather than a PostgreSQL native `ENUM`, so
adding a value needs no `ALTER TYPE` migration. It also sets `values_callable`
so the enum **value** is persisted (SQLAlchemy would otherwise store the member
*name*). Each enum lives next to the model that owns it; only genuinely shared
enums (like `RecordStatus`) live in `enums.py`. See **ADR-037**.

## Soft-delete helper

`SoftDeleteMixin` adds `deleted_at` but does **not** filter automatically —
excluding deleted rows is explicit per query. Use `only_active()` from
`app/models/helpers.py`:

```python
from sqlalchemy import select
from app.models.helpers import only_active

stmt = only_active(select(Company), Company)   # adds WHERE deleted_at IS NULL
rows = (await session.scalars(stmt)).all()
```

V1 has **no generic repository/CRUD layer** — services write explicit queries;
small helpers like this cover the few genuinely repeated patterns (**ADR-040**).

## Writing a model test

Database tests use a dedicated **test database** (`<dev_db>_test`,
auto-created, separate from dev) and the **transaction-rollback isolation**
pattern: each test runs in a transaction that is rolled back, so tests never
commit and never see each other's data (**ADR-039**). Just depend on the
`db_session` fixture:

```python
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

async def test_company_create(db_session: AsyncSession) -> None:
    company = Company(name="Acme")
    db_session.add(company)
    await db_session.flush()                    # flush, NOT commit
    fetched = await db_session.get(Company, company.id)
    assert fetched is not None
```

Notes:
- Use `flush()` (not `commit()`) to push changes within the test's transaction;
  a commit would defeat the rollback isolation.
- The schema is built once per session via `Base.metadata.create_all` — tests
  do **not** run migrations (those are verified separately).
- Override the test database with the `TEST_DATABASE_URL` env var if needed.

## Alembic configuration

- `backend/alembic.ini` — does **not** hardcode the database URL. `env.py`
  injects it from the app settings.
- `backend/alembic/env.py` — imports `settings` and `Base`, sets
  `sqlalchemy.url` from `settings.database_url` (asyncpg driver), sets
  `target_metadata = Base.metadata`, and runs migrations through an async
  engine. `compare_type` and `compare_server_default` are on for better
  autogenerate accuracy.
- Migration files are timestamp-prefixed
  (`YYYYMMDD_HHMM_<rev>_<slug>.py`) so they sort chronologically.

The model package (`app/models/__init__.py`) re-exports `Base` and every
concrete model, so importing it registers all tables on the metadata for
autogenerate to discover.

## Common commands

Run from `backend/`:

| Action | Command |
| --- | --- |
| Create an **autogenerated** migration | `uv run alembic revision --autogenerate -m "description"` |
| Create an **empty** migration | `uv run alembic revision -m "description"` |
| Apply all pending migrations | `uv run alembic upgrade head` |
| Roll back one migration | `uv run alembic downgrade -1` |
| Roll back everything | `uv run alembic downgrade base` |
| Show the current revision | `uv run alembic current` |
| Show migration history | `uv run alembic history` |

## Adding a new model

1. Define the model in `app/models/<name>.py`, inheriting `Base` + the mixins
   you need.
2. Import/re-export it in `app/models/__init__.py` (so autogenerate sees it).
3. Generate a migration: `uv run alembic revision --autogenerate -m "add <name>"`.
4. **Review the generated migration** — autogenerate is not perfect (it misses
   some changes, e.g. certain constraint/`server_default` edits, and can
   mis-render renames). Edit as needed. See **ADR-031**.
5. Apply it: `uv run alembic upgrade head`.
6. Confirm reversibility: `uv run alembic downgrade -1` then `upgrade head`.

> **Always review autogenerated migrations before applying them.** Establish
> the habit even for trivial ones.

## First migration

The initial migration (`..._enable_postgres_extensions.py`) enables the
PostgreSQL extensions the schema relies on:

- **pgcrypto** — column-level encryption for sensitive PII (SSN, account
  numbers), used from LP-14. See **ADR-035**.
- **uuid-ossp** — database-side UUID generation (we generate UUIDs in Python via
  `uuid4`, but this keeps the DB-side option available).

## Related ADRs

- **ADR-031** — Alembic for database migrations
- **ADR-032** — Constraint naming convention
- **ADR-033** — Timezone-aware timestamps in UTC
- **ADR-034** — UUID primary keys (with loan_files exception)
- **ADR-035** — pgcrypto extension for encryption
- **ADR-037** — Database-backed enums as VARCHAR with CHECK (`native_enum=False`)
- **ADR-038** — Money stored as Numeric/Decimal, never float
- **ADR-039** — Test database isolation via transaction rollback
- **ADR-040** — No generic repository/CRUD abstraction in V1
