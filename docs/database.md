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
constraint (`native_enum=False`, `create_constraint=True`) rather than a
PostgreSQL native `ENUM`, so adding a value needs no `ALTER TYPE` migration. The
CHECK is named by the convention (e.g. `ck_users_userrole`) and rejects
out-of-range values at the database level. It also sets `values_callable` so the
enum **value** is persisted (SQLAlchemy would otherwise store the member
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

## Multi-tenancy

The system is multi-tenant: the **tenant is a `Company`** (a processing
company — the customer). Multi-tenancy is built in from the first business
table so isolation is a habit everywhere, not a dangerous retrofit (**ADR-041**).

- **Every business entity belongs to a company** — directly via a `company_id`
  foreign key, or transitively through a parent that has one.
- **Each `User` belongs to exactly one company** (`users.company_id`, FK
  `ondelete=RESTRICT`). A user's **email is globally unique**, not unique
  per-company: email is the login identity and alone determines the user's
  company (**ADR-042**). Most *other* "unique" fields in tenant-owned tables
  should instead be unique **per company** — global uniqueness is the exception,
  reserved for login identity.
- **Companies and users are soft-deleted**, never hard-deleted in normal
  operation; the users→companies FK is `RESTRICT` and there is **no destructive
  ORM cascade** (**ADR-044**).

### The scoping rule

Every query that touches company-owned data **MUST** be scoped to the current
user's company. Forgetting to scope is a tenant data leak (one company seeing
another's PII). Scoping is **explicit**, not magic session-level filtering, so
the rule is greppable and debuggable (**ADR-043**). Use `scope_to_company()`
from `app/models/helpers.py`:

```python
from sqlalchemy import select
from app.models.helpers import only_active, scope_to_company

stmt = select(User)
stmt = scope_to_company(stmt, User, current_user.company_id)  # WHERE company_id = :id
stmt = only_active(stmt, User)                                # AND deleted_at IS NULL
rows = (await session.scalars(stmt)).all()
```

The helper accepts any model that carries a `company_id` (enforced at type-check
time via the `CompanyScoped` protocol); the tenant root `Company` has no
`company_id` and so is — correctly — not scopeable. It composes with
`only_active()`. This is the core security pattern; the tenant-isolation test
(`tests/models/test_tenant_isolation.py`) guards it.

### Per-company uniqueness (the default for tenant-owned tables)

In a multi-tenant system, **most "unique" fields are unique *per company*, not
globally** — globally-unique fields (like user email, a login identity) are the
exception (**ADR-045**). Enforce per-company uniqueness with a **composite
unique constraint** on `(company_id, <field>)`, named explicitly because the
naming convention's `uq` template only uses the first column:

```python
__table_args__ = (
    UniqueConstraint("company_id", "slug", name="uq_lenders_company_id_slug"),
)
```

This lets two different companies each have a record with slug `"uwm"` while
preventing one company from having two. Uniqueness checks in application code
must likewise be company-scoped.

## Lender model

A **`Lender`** (e.g. UWM, Sun-West) is an institution that loan files are
submitted to. It **belongs to a company** (`company_id` FK, `ondelete=RESTRICT`)
— each processing company configures its own lenders.

- **`slug` is unique per company** (composite unique on `company_id` + `slug`,
  per the pattern above) — *not* globally unique, in contrast with user email.
- **Contact fields** (`contact_email`, `portal_url`, `contact_phone`, `notes`)
  are designed for **direct underwriter communication** — processors work
  directly with underwriters, not account-executive intermediaries.
- **`lender_overlays`** (JSON object) holds lender-specific rule overrides. It
  defaults to `{}` and is **left unstructured in V1** — the overlay schema is a
  Phase 3 design decision, validated at the application layer then (**ADR-046**).
  The column exists now so adding overlays later needs no migration.
- **`supported_programs`** (JSON list) holds which programs the lender handles,
  e.g. `["conventional", "fha"]`, using `LoanProgram` enum values (**ADR-047**).
  Stored as a JSON list (not a join table) since it's a tiny set read with the
  lender (**ADR-046**).

`LoanProgram` (`CONVENTIONAL`, `FHA`) is defined in `app/models/lender.py` and
is the single source of truth for program values, reused by loan files in LP-13.

## Loan file model

A **`LoanFile`** is the **central entity** of the system: borrowers, properties,
documents, extracted data, verification findings, and conditions all reference
it. It belongs to a company (`company_id` FK, `ondelete=RESTRICT`) and may
reference a lender (`lender_id` FK, **nullable**, `ondelete=RESTRICT`) — the
lender can be unassigned when a file is first created.

Optional loan attributes are **nullable** because a file can be created manually
before its details are known and filled in later (e.g. from a MISMO import or by
the processor): `lender_id`, `loan_program`, `loan_purpose`, and `loan_amount`
(`Money`, `NUMERIC(14,2)`) may all be unset at creation. The originating loan
officer is stored as free text (`loan_officer_name`, `loan_officer_email`) — the
LO is an external party, not a system user.

### The three-identifier design (ADR-036)

Every loan file carries **three distinct identifiers**, each with its own
purpose and security posture. Mixing them up is a security bug, so they are kept
strictly separate:

| Identifier | Example | Purpose | Exposure | Generation |
| --- | --- | --- | --- | --- |
| `id` (UUID PK) | `7f3a8b2c-…` | FKs, joins, internal references | Never exposed | `uuid4` (from `UUIDMixin`) |
| `display_id` | `LF-7K3M` | Human reference in UI, conversation, email subjects | Authenticated users only | Non-sequential random, collision-checked |
| `inbox_token` | `a7k4nq2x9m3p` | Borrower inbox email address | Public (in the address) | `secrets.token_urlsafe(12)`, ~96 bits |

- **`display_id`** is an *identifier*: it merely names a file. Access is gated by
  auth + company scoping, so its predictability is low-risk. It uses an
  **unambiguous alphabet** `23456789ABCDEFGHJKMNPQRSTUVWXYZ` (no `0/O`, `1/I/L`)
  and is **globally unique** (**ADR-048**), collision-checked at creation with a
  unique DB index as the safety net.
- **`inbox_token`** is a *capability*: possession grants the ability to send
  documents into a file, so it must be **cryptographically unguessable** and is
  **never derived from the display ID** (independent generation). It builds the
  borrower address `lf-{inbox_token}@inbox.mortgageboss.ai` via
  `get_inbox_address()`.
- Both the display ID's random characters and the inbox token use the `secrets`
  module — **never `random`**. Generation lives in `app/services/loan_file_ids.py`
  and is wired in by `app/services/loan_files.create_loan_file` (**ADR-050**);
  the model only holds the columns.

### Status lifecycle (ADR-049)

`status` is a `LoanFileStatus` enum (VARCHAR + CHECK, **ADR-037**) defaulting to
`DRAFT`. The happy path is:

```
DRAFT → IN_PROCESSING → READY_TO_SUBMIT → SUBMITTED
      → IN_CONDITIONS → CLEAR_TO_CLOSE → CLOSED
```

plus `WITHDRAWN`, a terminal exit reachable from any earlier state. `loan_purpose`
is a `LoanPurpose` enum (`PURCHASE`, `REFINANCE`). Transitions are **not** enforced
by a state machine in V1 (any-to-any is allowed at the model level); workflow
enforcement can come later (**ADR-049**).

> Create loan files through `create_loan_file`, not by constructing `LoanFile`
> directly — only the service generates correct, collision-checked identifiers.
> It uses `flush` (not `commit`), so the caller controls the transaction.

## Borrower and property models

A loan file owns the **people** and **real estate** attached to it:

- **`Borrower`** — a borrower or co-borrower. A file has **one or more**
  (one-to-many): a primary borrower plus zero or more co-borrowers. Names are
  required; everything else (SSN, DOB, contact, `marital_status`) is nullable
  because details arrive incrementally. `is_primary` flags the primary borrower
  and `borrower_position` (1-based) orders them — `loan_file.borrowers` is
  returned ordered by position.
- **`Property`** — the **subject property**. A file has **exactly one** in V1
  (one-to-one, `loan_file.property`), enforced by a **unique constraint** on
  `properties.loan_file_id`; a second property on the same file fails at the
  database. Address, `property_type`, `occupancy_type`, and the `Money` valuation
  fields (`estimated_value`, `purchase_price`) are all nullable (a purchase is
  often "TBD" early).

Both are **owned by the loan file**: a `loan_file_id` FK with `ondelete=CASCADE`,
so a hard delete of a file removes them (normal flow soft-deletes via
`deleted_at`). Both also expose `marital_status` / `property_type` /
`occupancy_type` as VARCHAR + CHECK enums (**ADR-037**).

### SSN encryption at rest (ADR-051)

The borrower **SSN is encrypted at rest**, encrypted/decrypted in the
**application** (not pgcrypto), so the key never reaches the database and a
database-only compromise yields only ciphertext:

- `app/core/encryption.py` — Fernet (authenticated AES-128-CBC + HMAC) cipher
  built from the required `ENCRYPTION_KEY` setting, with `encrypt_value` /
  `decrypt_value` (None/empty → None).
- `app/models/encrypted_types.py` — `EncryptedString`, a `TypeDecorator` over
  `TEXT` that encrypts on write and decrypts on read. Declared like a normal
  column: `ssn: Mapped[str | None] = mapped_column(EncryptedString, ...)`. The
  raw column is plain `TEXT` holding ciphertext.
- Encryption is **non-deterministic** (fresh IV per write), so an encrypted
  column **cannot** be queried by equality, indexed, or made unique. Fine for SSN
  (never queried by it).
- The SSN never reaches a log/repr/error: `Borrower.__repr__` identifies by
  position + `loan_file_id` only, and `Borrower.masked_ssn` returns `***-**-1234`
  for display. **Date of birth is sensitive but unencrypted in V1** (lower risk,
  needed for matching); broadening the encrypted set is a later decision.

### Transitive company scoping (ADR-052)

Neither `borrowers` nor `properties` carries a `company_id`. They are
company-scoped **transitively** through their loan file. Scope the file and join
the child:

```python
# Borrowers reachable only through the owning company's loan files.
stmt = scope_to_company(
    select(Borrower).join(LoanFile, Borrower.loan_file_id == LoanFile.id),
    LoanFile,
    current_user.company_id,
)
```

There is intentionally no `scope_to_company(select(Borrower), Borrower, …)` —
`Borrower` has no `company_id`, so the `CompanyScoped` protocol rejects it. One
scoping anchor (the loan file) avoids a denormalized `company_id` drifting out of
sync. Tenant-isolation tests assert a query scoped to company A never surfaces
company B's borrowers.

## Document model

A **`Document`** is one uploaded file attached to a loan file (pay stub, bank
statement, W-2, …). The row holds **metadata and a `storage_path`** — never the
bytes. The binary lives in the storage backend (local in dev, S3 in prod —
LP-35); Postgres holds the record, the backend holds the file (**ADR-055**).
Storage metadata: `original_filename`, `mime_type`, `file_size_bytes`,
`storage_path` (`VARCHAR(1024)` for long S3 keys / nested paths).

Like borrowers and properties, a document is an **owned child** of the loan file
(`loan_file_id` FK, `ondelete=CASCADE`) with **no `company_id`** — scoped
transitively through the file (**ADR-052**). `loan_file.documents` is the
one-to-many; `document.uploaded_by` is the (optional) uploader.

### Classification: category (enum) vs document_type (string)

A document carries two classification facets, both set later by the classifier
(Epic 5 / Phase 2):

- **`category`** — one of **eight** stable buckets from the processor's library:
  `assets`, `borrower_info`, `credit`, `disclosures`, `income_employment`,
  `property`, `misc`, `custom`. A small, stable set → a `str_enum` with a DB
  CHECK constraint.
- **`document_type`** — a **flexible indexed string** (`"pay_stub"`, `"w2"`, a
  custom type, …). The full ~100-type set is finalized in Phase 2 and evolves,
  so it is **not** an enum — an enum would force a migration on every new type.
  Valid values are governed at the app layer, not the DB (**ADR-053**).
- **`classification_confidence`** — a nullable float in `[0.0, 1.0]`.

### Processing lifecycle (ADR-054)

`status` is a `DocumentStatus` enum (VARCHAR + CHECK) defaulting to `PENDING`.
Async tasks (Epic 5) move a document through:

```
PENDING → CLASSIFYING → CLASSIFIED → EXTRACTING → COMPLETED
```

plus `FAILED` (reason in `processing_error`) and `NEEDS_REVIEW` (low-confidence
classification awaiting processor correction). Transitions are **not** enforced
by a state machine in V1 — tasks set the status directly. `status` is indexed
(dashboards filter by it).

### Upload provenance (ADR-056)

`upload_source` is an `UploadSource` enum (`USER_UPLOAD`, `BORROWER_INBOX`,
`MISMO_IMPORT`). `uploaded_by_user_id` is a **nullable** FK to `users`
(`ondelete=RESTRICT`), set **only** for `USER_UPLOAD` — borrower-inbox and MISMO
imports have no user actor, so it is null. Any query that attributes a document
to a user must handle that null. `RESTRICT` keeps an uploader from being
hard-deleted out from under their documents (consistent with **ADR-044**).

## Extraction model

An **`Extraction`** is the structured data AI pulled out of a document (gross pay
from a pay stub, the transaction list from a bank statement). `document.extractions`
is the one-to-many; an extraction is an **owned child** of the document
(`document_id` FK, `ondelete=CASCADE`) with **no `company_id`** — scoped
transitively through `document → loan_file` (**ADR-052**). It also records AI
**provenance** for cost tracking and debugging: `model_used`, `tokens_used`,
`cost_estimate` (a `Float`, not `Money` — per-extraction costs are sub-cent
estimates), and `error_detail` (set on a `FAILED` run). `extraction_status` is a
`str_enum` (`succeeded` / `failed` / `partial`, VARCHAR + CHECK).

### JSON data, typed at the application layer (ADR-057)

`extracted_data` is a single **JSON** column. Its structure is **not** a generic
field bag and **not** DB-enforced — it is governed by document-type-specific
**Pydantic schemas at the application layer** (Phase 2). The extraction task
validates a typed model and serializes it into the column; readers parse it back.
This is the deliberate difference from the POC's generic `ExtractedField` rows
(an EAV anti-pattern): V1 stores document-type-specific *structured* data that
merely happens to be persisted as JSON. The tradeoff: no querying *inside* the
JSON at the DB level in V1 — we read the whole extraction and parse it.

**Bank-statement transactions live inside `extracted_data`** as a nested list in
V1 — there is no separate transactions table (**ADR-059**). Cross-transaction
querying isn't needed yet; a projection table can be added later if it is.

### Versioning: one current per document (ADR-058)

A document can be re-extracted (re-classification, prompt improvements). Each run
is a new **`version`** (sequential per document, from 1); **`is_current`** marks
the active one. A **partial unique index** enforces exactly one current per
document at the database level:

```
uq_extractions_document_id_current  UNIQUE (document_id) WHERE is_current
```

Any number of historical (`is_current = false`) versions coexist; history is
preserved. Create new versions through
`app.services.extractions.create_extraction_version`, which **demotes the old
current (and flushes) before inserting the new one** — otherwise the insert would
collide with the still-current row on the partial index. Read the active data via
`is_current = true` or the `Document.current_extraction` convenience (a Python
property over the loaded `extractions` collection — load it with
`selectinload(Document.extractions)`).

## Finding model

A **`Finding`** is one verification result against a loan file (Phase 3's engine
produces them): "pay stub is stale", "stated income differs from documents by
15%", "missing 2023 W-2". `loan_file.findings` is the one-to-many; a finding is an
**owned child** of the loan file (`loan_file_id` FK, `ondelete=CASCADE`) with
**no `company_id`** — scoped transitively through the file (**ADR-052**).

### Red / yellow / green, and categories

`status` is a `FindingStatus` enum — **`red`** (blocking), **`yellow`** (review /
may need a compensating factor), **`green`** (passed) — matching how processors
triage. `category` is a `FindingCategory` enum (`income`, `assets`, `credit`,
`property`, `documentation`, `cross_source`, `regulatory`). Both are VARCHAR +
CHECK and indexed. `message` is the human-readable text; `details` is a JSON dict
of structured supporting data (e.g. `{"stated": 16400, "verified": 14200,
"variance_pct": 0.15}`).

`rule_id` identifies the rule that produced the finding. It is a **flexible
indexed string** using a dotted namespace (`income.paystub_recency`,
`fha.mip_required`), **not** an enum — the rule catalog (60–80+) is finalized in
Phase 3 and governed at the app layer (**ADR-062**).

### Resolution lifecycle (persists across runs)

`resolution_status` is a `FindingResolutionStatus` enum (`open` → `resolved` /
`accepted_risk` / `waived`), defaulting to `open`, with a **trail**:
`resolved_by_user_id` (FK to users, `SET NULL`), `resolved_at` (timezone-aware),
`resolution_note`. `accepted_risk` captures accepting a yellow flag with a
compensating factor — something a boolean "resolved?" couldn't express
(**ADR-060**).

Because findings belong to the **durable loan file** (not to a verification run),
their resolution state **persists across verification runs** (**ADR-061**): a
processor who accepts a risk doesn't lose that on the next run. Cross-run matching
of new findings to existing ones (to carry resolution forward) is Phase 3 logic.

Set resolution through `app.services.findings.resolve_finding(db, *, finding,
resolution_status, user_id, note=None)` — it writes the status + trail together
(or, for `OPEN`, clears the trail to re-open) and flushes. Don't mutate the
resolution fields directly.

### Linkages

`source_document_id` (FK to documents, nullable, `SET NULL`) ties a finding to the
document that triggered it, or is null for a file-level finding — the finding
survives if the document is removed. `verification_id` references the verification
run that produced it, but is a **nullable UUID with no FK constraint yet**: the
`verifications` table arrives in **LP-18**, which adds the constraint (**ADR-063**).

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

- **pgcrypto** — database-side cryptographic functions. Originally intended for
  PII encryption (**ADR-035**), but LP-14 chose **application-level** encryption
  for the SSN instead (**ADR-051**), so pgcrypto is currently unused. It stays
  enabled in case a future deterministic / DB-side need arises.
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
- **ADR-041** — Multi-tenancy via `company_id` scoping from day one
- **ADR-042** — Email globally unique (not per-company)
- **ADR-043** — Explicit company-scoping helper (no automatic query filtering)
- **ADR-044** — Companies and users soft-deleted, FK `ondelete RESTRICT`
- **ADR-045** — Per-company unique slugs (composite uniqueness)
- **ADR-046** — Lender overlays and supported programs as JSON
- **ADR-047** — `LoanProgram` enum (Conventional, FHA) shared across models
- **ADR-036** — Loan file identifier strategy (three decoupled identifiers)
- **ADR-048** — Display ID globally unique
- **ADR-049** — Loan file status lifecycle
- **ADR-050** — ID generation in the service layer, not the model
- **ADR-051** — Application-level encryption for SSN, not pgcrypto
- **ADR-052** — Borrowers and properties are company-scoped transitively
- **ADR-053** — Document type as a flexible string, category as an enum
- **ADR-054** — Document processing lifecycle status
- **ADR-055** — Document storage path in the database, bytes in the backend
- **ADR-056** — Document upload provenance
- **ADR-057** — Extracted data stored as JSON, typed at the application layer
- **ADR-058** — Extraction versioning with one current per document
- **ADR-059** — Bank-statement transactions in `extracted_data` JSON (no table in V1)
- **ADR-060** — Finding status (red/yellow/green) and resolution lifecycle
- **ADR-061** — Findings belong to the loan file; resolution persists across runs
- **ADR-062** — `rule_id` as a flexible dotted-namespace string
- **ADR-063** — `verification_id` column added before its FK target exists
