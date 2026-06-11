# Architecture Decision Record (ADR) Log

This file is a lightweight Architecture Decision Record log for the MortgageBoss
AI V1 build. It captures the significant technical and structural decisions made
during development, so that the reasoning behind them is preserved for future
contributors (and our future selves).

## Format

Each decision is recorded as an entry with the following structure:

- **ADR-NNN: Title** — a short, descriptive title.
- **Date** — when the decision was made.
- **Status** — Proposed | Accepted | Superseded.
- **Context** — the situation and forces that led to the decision.
- **Decision** — what was decided.
- **Consequences** — the resulting trade-offs, both positive and negative.

## Index

| ADR | Title | Epic |
| --- | ----- | ---- |
| [001](#adr-001-use-a-monorepo-for-v1) | Use a monorepo for V1 | 1 |
| [002](#adr-002-use-docker-compose-for-local-development-services) | Use Docker Compose for local development services | 1 |
| [003](#adr-003-postgresql-16-over-17) | PostgreSQL 16 over 17 | 1 |
| [004](#adr-004-mailhog-for-local-email-capture) | MailHog for local email capture | 1 |
| [005](#adr-005-hardcoded-development-database-credentials) | Hardcoded development database credentials | 1 |
| [006](#adr-006-use-colima-as-docker-runtime) | Use Colima as Docker runtime | 1 |
| [007](#adr-007-python-312-for-the-backend) | Python 3.12 for the backend | 1 |
| [008](#adr-008-uv-as-the-python-package-manager) | uv as the Python package manager | 1 |
| [009](#adr-009-fastapi-as-the-backend-framework) | FastAPI as the backend framework | 1 |
| [010](#adr-010-sqlalchemy-2x-with-async-support) | SQLAlchemy 2.x with async support | 1 |
| [011](#adr-011-ruff-for-linting-and-formatting) | Ruff for linting and formatting | 1 |
| [012](#adr-012-mypy-in-strict-mode-for-type-checking) | mypy in strict mode for type checking | 1 |
| [013](#adr-013-nextjs-15-with-app-router-for-frontend) | Next.js 15 with App Router for frontend | 1 |
| [014](#adr-014-typescript-strict-mode-for-frontend) | TypeScript strict mode for frontend | 1 |
| [015](#adr-015-shadcnui-for-the-component-library) | shadcn/ui for the component library | 1 |
| [016](#adr-016-biome-for-linting-and-formatting) | Biome for linting and formatting | 1 |
| [017](#adr-017-pnpm-for-node-package-management) | pnpm for Node package management | 1 |
| [018](#adr-018-tanstack-query-for-server-state-zustand-for-client-state) | TanStack Query + Zustand for state | 1 |
| [019](#adr-019-system-font-stack-instead-of-custom-web-fonts) | System font stack instead of custom web fonts | 1 |
| [020](#adr-020-pydantic-settings-for-configuration-management) | Pydantic Settings for configuration management | 1 |
| [021](#adr-021-structured-logging-with-structlog) | Structured logging with structlog | 1 |
| [022](#adr-022-async-only-database-access) | Async-only database access | 1 |
| [023](#adr-023-three-tier-health-checks-basic-liveness-readiness) | Three-tier health checks | 1 |
| [024](#adr-024-connection-pool-sizing) | Connection pool sizing | 1 |
| [025](#adr-025-github-actions-for-ci) | GitHub Actions for CI | 1 |
| [026](#adr-026-pre-commit-hooks-for-local-checks) | Pre-commit hooks for local checks | 1 |
| [027](#adr-027-path-based-ci-triggering) | Path-based CI triggering | 1 |
| [028](#adr-028-skip-integration-tests-in-ci-for-v1) | Skip integration tests in CI for V1 | 1 |
| [029](#adr-029-coverage-as-a-metric-not-a-gate) | Coverage as a metric, not a gate | 1 |
| [030](#adr-030-documentation-structure-and-conventions) | Documentation structure and conventions | 1 |
| [031](#adr-031-alembic-for-database-migrations) | Alembic for database migrations | 2 |
| [032](#adr-032-constraint-naming-convention) | Constraint naming convention | 2 |
| [033](#adr-033-timezone-aware-timestamps-in-utc) | Timezone-aware timestamps in UTC | 2 |
| [034](#adr-034-uuid-primary-keys-with-loan_files-exception) | UUID primary keys (with loan_files exception) | 2 |
| [035](#adr-035-pgcrypto-extension-for-encryption) | pgcrypto extension for encryption | 2 |
| [037](#adr-037-database-backed-enums-as-varchar-with-check-native_enumfalse) | Database-backed enums as VARCHAR with CHECK | 2 |
| [038](#adr-038-money-stored-as-numericdecimal-never-float) | Money stored as Numeric/Decimal, never float | 2 |
| [039](#adr-039-test-database-isolation-via-transaction-rollback) | Test database isolation via transaction rollback | 2 |
| [040](#adr-040-no-generic-repositorycrud-abstraction-in-v1) | No generic repository/CRUD abstraction in V1 | 2 |
| [041](#adr-041-multi-tenancy-via-company_id-scoping-from-day-one) | Multi-tenancy via company_id scoping from day one | 2 |
| [042](#adr-042-email-globally-unique-not-per-company) | Email globally unique (not per-company) | 2 |
| [043](#adr-043-explicit-company-scoping-helper-no-automatic-query-filtering) | Explicit company-scoping helper (no automatic query filtering) | 2 |
| [044](#adr-044-companies-and-users-soft-deleted-fk-ondelete-restrict) | Companies and users soft-deleted, FK ondelete RESTRICT | 2 |
| [045](#adr-045-per-company-unique-slugs-composite-uniqueness) | Per-company unique slugs (composite uniqueness) | 2 |
| [046](#adr-046-lender-overlays-and-supported-programs-as-json) | Lender overlays and supported programs as JSON | 2 |
| [047](#adr-047-loanprogram-enum-conventional-fha-shared-across-models) | LoanProgram enum (Conventional, FHA) shared across models | 2 |

---

## ADR-001: Use a monorepo for V1

- **Date:** 2026-06-09
- **Status:** Accepted

**Context:** V1 consists of a Python/FastAPI backend and a Next.js/TypeScript
frontend that are developed in lockstep by a small team (effectively a solo
developer for now). We need to decide whether to keep these in a single
repository or split them into separate repositories.

**Decision:** Use a single monorepo containing both the backend (`backend/`) and
the frontend (`frontend/`), along with shared documentation, scripts, and CI
configuration.

**Consequences:**

- _Positive:_ A single source of truth simplifies cross-cutting changes (e.g.,
  an API contract change that touches both backend and frontend can land in one
  commit/PR). One clone, one set of issues, one CI pipeline, and shared docs and
  decision log. This is simpler to manage for a solo developer.
- _Positive:_ Atomic commits keep backend and frontend in sync, avoiding
  version-mismatch drift between separate repos.
- _Negative:_ The repository mixes two toolchains (uv/Python and pnpm/Node),
  which requires path-scoped tooling and CI jobs.
- _Reversible:_ If the project grows and the boundaries harden, the `backend/`
  and `frontend/` directories can be split into separate repositories later with
  history preserved via `git subtree`/`filter-repo`.

---

## ADR-002: Use Docker Compose for local development services

- **Date:** 2026-06-09
- **Status:** Accepted

**Context:** Local development needs PostgreSQL (application database), Redis
(Celery broker and cache), and a mail catcher (to test email-sending code).
Installing and version-managing these natively on each developer's machine is
error-prone and inconsistent across operating systems.

**Decision:** Use Docker Compose to orchestrate all local services from a single
`docker-compose.yml` at the repo root.

**Consequences:**

- _Positive:_ A single command (`docker compose up -d`) starts the full local
  stack; environments are consistent across machines; no native installation of
  Postgres/Redis is required; tear-down is clean.
- _Negative:_ Requires Docker Desktop (or an equivalent Docker Engine + Compose
  v2) to be installed and running.

---

## ADR-003: PostgreSQL 16 over 17

- **Date:** 2026-06-09
- **Status:** Accepted

**Context:** We must pin a PostgreSQL major version for the project.

**Decision:** Use PostgreSQL 16 (the `postgres:16-alpine` image).

**Rationale:** Version 16 is more mature and battle-tested than 17; it is widely
supported by managed hosting providers (Render, Railway, Supabase); it has
strong async driver support via `asyncpg`; and it offers excellent JSON column
performance for our document/metadata use cases.

**Consequences:** We will evaluate an upgrade path to PostgreSQL 17 in V2 if
warranted. The Alpine variant keeps the image small.

---

## ADR-004: MailHog for local email capture

- **Date:** 2026-06-09
- **Status:** Accepted

**Context:** We need to test email-sending code locally without delivering mail
to real recipients.

**Decision:** Use MailHog as the development SMTP server, capturing outbound mail
and exposing it through a web UI.

**Alternatives considered:** Mailpit (a newer fork with similar capability) and
Mailtrap (a cloud service that requires an account).

**Rationale:** MailHog is established, runs entirely locally, requires no account,
and provides a simple web UI for inspecting captured messages.

**Consequences:** The backend will be configured to send SMTP to `localhost:1025`
in development, with the captured mail viewable at <http://localhost:8025>.

---

## ADR-005: Hardcoded development database credentials

- **Date:** 2026-06-09
- **Status:** Accepted

**Context:** `docker-compose.yml` sets `POSTGRES_USER`, `POSTGRES_PASSWORD`, and
`POSTGRES_DB` for the local Postgres service, and this file is checked into git.

**Decision:** Hardcode development-only credentials directly in
`docker-compose.yml`.

**Rationale:** This is a development-only file; the local database is only
reachable from the developer's machine; hardcoding removes a setup step and
simplifies onboarding. Production credentials will be injected via environment
variables by the hosting platform (e.g. Render) in Phase 7.

**Security note:** Because `docker-compose.yml` is committed to git, these
credentials are intentionally development-only and must never be used in any
production or shared environment.

**Consequences:** Production deployment in Phase 7 will rely on
environment-injected credentials rather than values from this file.

---

## ADR-006: Use Colima as Docker runtime

- **Date:** 2026-06-09
- **Status:** Accepted

**Context:** ADR-002 commits us to Docker Compose for local services, which
requires a Docker runtime on each developer machine. We must choose which
runtime to install.

**Decision:** Use Colima with the `docker` CLI (and the `docker compose` plugin),
installed via Homebrew (`brew install colima docker docker-compose`) — no Docker
Desktop.

**Rationale:**

- Free for commercial use (Docker Desktop requires a paid license for larger
  organizations / commercial use).
- Lighter resource footprint than Docker Desktop.
- No GUI overhead — runs headless from the CLI.
- Identical CLI compatibility: `docker` and `docker compose` work unchanged.

**Alternatives considered:**

- _Docker Desktop_ — licensing concerns for eventual commercial use and heavier
  resource usage.
- _Podman_ — less mature Docker Compose support.

**Consequences:** The startup flow has one extra step compared to Docker Desktop
— `colima start` must run before `docker compose up -d` (and `colima stop` when
done). This is documented in the README "First-time Colima setup" subsection.

---

## ADR-007: Python 3.12 for the backend

- **Date:** 2026-06-09
- **Status:** Accepted

**Context:** We must pin a Python major version for the backend.

**Decision:** Use Python 3.12, pinned via `backend/.python-version`.

**Rationale:** 3.12 is the current stable release with significant performance
improvements over 3.11 and mature async support; it is widely supported by cloud
platforms. 3.13 is too new for full ecosystem/stub support at the time of this
decision.

**Consequences:** We cannot use 3.13-only features; an upgrade can be revisited
in V2 if warranted.

---

## ADR-008: uv as the Python package manager

- **Date:** 2026-06-09
- **Status:** Accepted

**Context:** We need a Python package/dependency manager for the backend.

**Decision:** Use [uv](https://docs.astral.sh/uv/) (from Astral).

**Alternatives considered:** Poetry, pip-tools, pdm, pipenv.

**Rationale:** Significantly faster than the alternatives; modern design centered
on `pyproject.toml`; a built-in lock file (`uv.lock`) for reproducible installs;
actively developed by Astral (the makers of Ruff, keeping our toolchain
cohesive).

**Consequences:** Slightly less mature than Poetry but stabilizing rapidly; the
team must learn uv commands (`uv sync`, `uv add`, `uv run`).

---

## ADR-009: FastAPI as the backend framework

- **Date:** 2026-06-09
- **Status:** Accepted

**Context:** We must choose a Python web framework.

**Decision:** Use FastAPI.

**Alternatives considered:** Django (too heavy, sync-first), Flask (no native
async), Starlette (lower level).

**Rationale:** Native async support is critical for AI workloads (concurrent LLM
calls); automatic OpenAPI docs save documentation effort; first-class Pydantic
integration aligns with our validation approach; high performance; a type-first
philosophy that matches our use of type hints throughout.

**Consequences:** Smaller ecosystem than Django; the team must understand async
patterns; the framework evolves quickly, requiring us to stay current.

---

## ADR-010: SQLAlchemy 2.x with async support

- **Date:** 2026-06-09
- **Status:** Accepted

**Context:** We must choose an ORM.

**Decision:** Use SQLAlchemy 2.x in async mode with the `asyncpg` driver for
PostgreSQL.

**Alternatives considered:** Tortoise ORM (async-native but smaller community),
Django ORM (sync, tied to Django), raw `asyncpg` (no ORM abstractions).

**Rationale:** The most mature Python ORM; v2 has a clean async API; a large
ecosystem; Alembic migrations integrate naturally; it is widely understood by
Python developers.

**Consequences:** A steeper learning curve than simpler ORMs; we must use the
2.0 `Mapped` style consistently.

---

## ADR-011: Ruff for linting and formatting

- **Date:** 2026-06-09
- **Status:** Accepted

**Context:** We need code-quality tooling (lint + format).

**Decision:** Use Ruff, replacing black, isort, flake8, autoflake, and pylint.

**Rationale:** A single tool replaces 4–5 separate ones; it is orders of
magnitude faster; actively developed; configured in one place (`pyproject.toml`).

**Consequences:** Some plugins from older tools are not yet supported; Ruff
evolves quickly, so occasional breaking changes between versions are possible.

---

## ADR-012: mypy in strict mode for type checking

- **Date:** 2026-06-09
- **Status:** Accepted

**Context:** We need a static type-checking strategy.

**Decision:** Use mypy in strict mode (`strict = true`).

**Rationale:** Catches bugs at development time; documents code intent; works
well with FastAPI's type-first design; enforces consistent type hints across the
codebase.

**Consequences:** More upfront typing work; some libraries lack stub files
(handled by `ignore_missing_imports` during V1); the team must understand Python
typing well.

---

## ADR-013: Next.js 15 with App Router for frontend

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Choosing the frontend framework for the web UI.

**Decision:** Use Next.js 15 with the App Router (not the Pages Router).

**Alternatives considered:** Vite + React, Remix, plain React with React Router.

**Rationale:** Server Components reduce client bundle size for data-heavy pages;
file-based routing reduces boilerplate; built-in TypeScript and Tailwind support;
production-grade with excellent DX; widely adopted with a strong community.

**Consequences:** Learning curve for App Router patterns (Server vs Client
Components); some libraries don't yet fully support Server Components.

---

## ADR-014: TypeScript strict mode for frontend

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Choosing a TypeScript configuration philosophy for the frontend.

**Decision:** Enable `strict` mode plus `noUncheckedIndexedAccess` and
`noImplicitOverride`.

**Rationale:** Matches the backend's mypy strict-mode philosophy; catches more
bugs at compile time; documents code intent.

**Consequences:** More upfront typing work; some libraries with poor type
definitions require workarounds.

---

## ADR-015: shadcn/ui for the component library

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Choosing a component library for the frontend.

**Decision:** Use shadcn/ui (a copy-into-codebase approach built on Radix UI
primitives).

**Alternatives considered:** Material UI (too opinionated, heavy), Chakra UI
(smaller community, runtime CSS-in-JS), Mantine (good but less customizable),
build from scratch (too much work).

**Rationale:** We own the component code and can customize it freely; accessible
by default (Radix); pairs naturally with Tailwind; install components as needed
(no bloat); professional look out of the box; very active maintenance.

**Consequences:** Slight learning curve for the install-via-CLI workflow;
component code lives in our repo (so we maintain it).

---

## ADR-016: Biome for linting and formatting

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Choosing code-quality tooling for the frontend.

**Decision:** Use Biome (replaces ESLint + Prettier).

**Alternatives considered:** ESLint + Prettier (the traditional choice).

**Rationale:** A single fast tool replaces two; Rust-based (orders of magnitude
faster than ESLint); modern; aligns with the backend choice of Ruff (also
Rust-based, also a single-tool approach).

**Consequences:** Smaller plugin ecosystem than ESLint; occasional
incompatibilities with niche tools; rapidly evolving.

---

## ADR-017: pnpm for Node package management

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Choosing a Node package manager.

**Decision:** Use pnpm.

**Alternatives considered:** npm (default), yarn, bun.

**Rationale:** Faster than npm; content-addressable storage (disk-efficient
across multiple projects); strict `node_modules` structure prevents phantom
dependencies; widely adopted in modern Next.js projects.

**Consequences:** Developers must install pnpm separately (not part of Node's
default); occasional incompatibilities with packages that assume npm.

---

## ADR-018: TanStack Query for server state, Zustand for client state

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Choosing a state-management strategy for the frontend.

**Decision:** Use TanStack Query for server state (data from the backend API) and
Zustand for client state (UI state, user preferences).

**Alternatives considered:** Redux Toolkit + RTK Query (heavier), SWR (less
feature-rich than TanStack Query), Jotai (atomic but adds complexity), Recoil
(Meta-maintained but uncertain future).

**Rationale:** Server state is fundamentally different from client state and
deserves dedicated tooling; TanStack Query handles caching, refetching, and
loading states declaratively; Zustand is the simplest modern client-state
library; the boundary gives a clear mental model.

**Consequences:** Two state libraries means two patterns to learn; works well
when the boundary is kept clear.

---

## ADR-019: System font stack instead of custom web fonts

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Choosing the typography approach for the frontend.

**Decision:** Use the system font stack (`-apple-system`, `BlinkMacSystemFont`,
`Segoe UI`, etc.) instead of loading custom web fonts.

**Alternatives considered:** Inter (popular modern sans-serif), Geist (Vercel's
font, the Next.js default).

**Rationale:** Zero font-loading delay (no FOUT/FOIT flash); native look on each
platform; smaller bundle; no licensing concerns; one less dependency.

**Consequences:** Slight visual variation across operating systems (a feature for
native feel); can switch to a custom font in V2 if branding needs evolve.

---

## ADR-020: Pydantic Settings for configuration management

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** We need a way to load and validate application configuration.

**Decision:** Use pydantic-settings (`BaseSettings`) for type-validated config
loaded from environment variables and an optional `.env` file.

**Alternatives considered:** python-dotenv directly, dynaconf, a custom config
class.

**Rationale:** We already use Pydantic for data validation; it is type-safe;
gives clear error messages on missing/invalid required config; supports `.env`
files for development; one library handles both app config and request
validation.

**Consequences:** Configuration is coupled to Pydantic version updates; the team
must understand Pydantic patterns.

---

## ADR-021: Structured logging with structlog

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** We need a logging strategy that works in both development and
production.

**Decision:** Use structlog with colored console rendering in development and
JSON rendering in production (selected via `LOG_FORMAT`).

**Alternatives considered:** Standard logging with custom formatters, loguru,
python-json-logger.

**Rationale:** Structured logs are essential for production observability;
structlog has excellent dev DX (colored, pretty-printed); JSON output works with
all log aggregators; it is performant.

**Consequences:** Slightly steeper learning curve than stdlib logging; structlog
patterns must be used consistently.

---

## ADR-022: Async-only database access

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Whether to support both sync and async database access.

**Decision:** Async only — asyncpg driver, `AsyncSession`, and async dependency
injection.

**Alternatives considered:** Sync SQLAlchemy with sync routes, or a mix of sync
and async.

**Rationale:** FastAPI is async; mixing sync and async in Python causes subtle
deadlocks and performance issues; concurrent LLM calls require async; it is a
cleaner mental model.

**Consequences:** Cannot easily use synchronous SQLAlchemy patterns; some
libraries (e.g. older Alembic helpers) require async wrappers.

---

## ADR-023: Three-tier health checks (basic, liveness, readiness)

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** How to design health check endpoints for monitoring and
orchestration.

**Decision:** Three endpoints — `/health` (overall status with detail),
`/health/live` (process alive), `/health/ready` (can serve traffic).

**Rationale:** Different orchestrators and monitoring tools need different
signals; liveness should **not** check dependencies (a failing DB shouldn't
restart the app); readiness **should** check dependencies (the orchestrator can
stop routing traffic); `/health` provides human-readable detail.

**Consequences:** Three endpoints to maintain, but the clear semantics make
production monitoring easier.

---

## ADR-024: Connection pool sizing

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** How to configure the database connection pool.

**Decision:** Use a small pool for development (`size=5`, `overflow=10`),
configurable via environment variables for production, with `pool_pre_ping`
enabled.

**Rationale:** Development doesn't need many connections; production can be tuned
per deployment; overflow allows burst capacity; `pool_pre_ping` verifies
connections before use, avoiding stale-connection errors.

**Consequences:** The default pool may be too small for high-traffic production;
monitoring will inform pool size in V2.

---

## ADR-025: GitHub Actions for CI

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** We need automated checking of code changes.

**Decision:** Use GitHub Actions.

**Alternatives considered:** CircleCI, GitLab CI, Travis CI, self-hosted runners.

**Rationale:** Already using GitHub for hosting (no separate vendor); generous
free tier (2000 min/month for private repos); large ecosystem of actions;
declarative YAML config; pay-per-use for overages.

**Consequences:** Vendor lock-in to GitHub Actions syntax; some advanced features
require paid plans for higher concurrency.

---

## ADR-026: Pre-commit hooks for local checks

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** We need fast feedback before commits.

**Decision:** Use the `pre-commit` framework to manage local hooks.

**Alternatives considered:** Husky (Node-specific), git-only hooks (no shared
config), no pre-commit checks at all.

**Rationale:** Industry standard; supports both Python and JS hooks from one
shareable YAML config; does not require Node like Husky does.

**Consequences:** Developers must install pre-commit
(`pipx install pre-commit && pre-commit install`); occasional false positives
need to be addressed.

> **Note on secret detection:** the ticket suggested gitleaks *or* detect-secrets.
> We chose **detect-secrets** (Yelp) because its pre-commit hook is pure-Python
> and installs with no external toolchain, whereas the gitleaks hook builds via
> Go (not available on the dev machine). A `.secrets.baseline` records known,
> intentional non-secrets (placeholders, test values, local dev credentials).

---

## ADR-027: Path-based CI triggering

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** We want to avoid running unnecessary CI jobs.

**Decision:** Backend CI triggers only on `backend/` changes; frontend CI only on
`frontend/` changes (each also triggers on its own workflow file).

**Rationale:** Saves CI minutes; faster feedback on the relevant pipeline;
cleaner status reporting.

**Consequences:** Cross-cutting changes to root files don't trigger either
pipeline (acceptable for now); will revisit if root files start affecting
backend/frontend behavior.

---

## ADR-028: Skip integration tests in CI for V1

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Some tests (e.g. the health checks) reach for Postgres and Redis.
Whether to stand those services up in CI.

**Decision:** For V1, run only unit tests in CI; tests that need real services
are written to tolerate their absence (health checks assert `200` or `503`), and
full service-backed integration testing is run locally.

**Alternatives considered:** Spin up services in GitHub Actions, use
testcontainers, mock everything.

**Rationale:** Standing up services in CI adds complexity and time; for V1 with a
solo dev, running integration checks locally before push is sufficient; CI still
catches the most common breakage (lint, types, unit logic, build).

**Consequences:** Integration breakage could escape to `main`; will revisit in
Phase 7 (production readiness) to add full service setup in CI.

---

## ADR-029: Coverage as a metric, not a gate

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Whether to require a minimum test coverage in CI.

**Decision:** Track coverage but do not fail the build for low coverage.

**Rationale:** Coverage gates encourage gaming (tests written for coverage rather
than correctness); V1 has a lot of scaffolding that is hard to meaningfully test;
pragmatic over dogmatic.

**Consequences:** Some areas may be under-tested; we will track coverage trends
and can introduce gates in V2 if needed.

---

## ADR-030: Documentation structure and conventions

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** As the project grows, documentation needs a coherent home and clear
ownership so it stays useful and doesn't drift from the code.

**Decision:** Use a centralized `docs/` folder with specific documents —
`architecture.md`, `glossary.md`, `project-structure.md`, `poc-learnings.md`,
`development-workflow.md`, an index at `docs/README.md`, and the phase plan under
`docs/phases/` — plus per-ticket records in `docs/tickets/LP-XXX.md`. Cross-cutting
concerns keep dedicated homes: ADRs in `decisions.md`, AI/assistant conventions in
`CLAUDE.md`, and setup/navigation in the root `README.md`.

**Alternatives considered:** A single large README; a wiki; docs colocated with
code only.

**Rationale:** Separation of concerns (setup vs architecture vs decisions vs
domain terms) keeps each document scannable; per-ticket records create an audit
trail; a glossary is essential in a jargon-heavy domain; an index aids navigation.

**Consequences:** Documentation must be maintained alongside code; several
documents to keep in sync; the `docs/README.md` index and this ADR define where
each kind of content belongs.

---

## ADR-031: Alembic for database migrations

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Epic 2 needs versioned, reversible management of the database
schema, integrated with our async SQLAlchemy stack.

**Decision:** Use Alembic — the standard migration tool for SQLAlchemy —
configured for async (the `async` template, `async_engine_from_config` +
`connection.run_sync`). The database URL and `target_metadata` come from the
app itself (`settings.database_url`, `app.models.Base.metadata`).

**Rationale:** Alembic pairs natively with SQLAlchemy; supports autogenerate;
migrations are reversible; it is the industry standard and integrates with
async engines.

**Consequences:** Autogenerated migrations must always be reviewed before
applying (autogenerate is not perfect — it misses some changes and mis-renders
others); the async configuration is more involved than the sync default.

---

## ADR-032: Constraint naming convention

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** By default, database constraints (foreign keys, indexes, unique
and check constraints) get cryptic, database-generated names, which makes
migrations and manual debugging painful.

**Decision:** Set an explicit `MetaData` naming convention on `Base` for every
constraint type — `ix`, `uq`, `ck`, `fk`, `pk` — so names are readable and
predictable (e.g. `fk_borrowers_company_id_companies`, `pk_companies`).

**Rationale:** Readable constraint names make migrations and debugging far
easier and keep names consistent across all tables. The convention **must** be
set before any tables are created — retrofitting it later means migrating every
constraint.

**Consequences:** All constraints follow the pattern automatically; changing
the convention later would require migrating every existing constraint.

---

## ADR-033: Timezone-aware timestamps in UTC

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** We need a single, unambiguous policy for storing timestamps.

**Decision:** All timestamps are timezone-aware (`DateTime(timezone=True)` →
`timestamptz` in Postgres) and always stored in UTC. A `utcnow()` helper
returns tz-aware UTC datetimes; mixins use it for `created_at` / `updated_at` /
`deleted_at`. Display-time conversion happens in the frontend.

**Rationale:** UTC + tz-aware avoids an entire category of timezone bugs; naive
datetimes are a well-known footgun. UTC is unambiguous for storage and
comparison.

**Consequences:** Code must always use tz-aware datetimes (the `utcnow` helper);
never `datetime.now()` without a timezone.

---

## ADR-034: UUID primary keys (with loan_files exception)

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** We must choose a primary-key strategy for the schema.

**Decision:** Use UUID primary keys for most tables via `UUIDMixin`
(`uuid4` default). `loan_files` is the deliberate exception: it carries
human-readable identifiers, handled in LP-13 per [ADR-036](#adr-036-loan-file-identifier-strategy-three-decoupled-identifiers).

**Rationale:** UUIDs avoid enumeration attacks, allow client-side ID
generation, and prevent collisions across distributed systems. Loan files
additionally need a human-friendly reference for processors in conversation and
email — a separate concern layered on top of (not replacing) the internal key.

**Consequences:** UUIDs are larger than integers (negligible storage/index cost
at our scale) and less human-friendly (mitigated by the readable loan-file
display ID).

---

## ADR-035: pgcrypto extension for encryption

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Sensitive PII (SSN, account numbers) will need column-level
encryption when the borrower model lands (LP-14).

**Decision:** Enable the `pgcrypto` PostgreSQL extension in the first migration
(alongside `uuid-ossp`), so encryption functions are available at the database
level before the columns that need them exist.

**Rationale:** `pgcrypto` is a standard Postgres extension providing
database-level encryption functions; enabling it early keeps the option ready
without a scramble later.

**Consequences:** Encryption/decryption logic must be implemented when those
columns are added; key management is a separate concern deferred to Phase 7.

---

## ADR-036: Loan file identifier strategy (three decoupled identifiers)

**Date:** 2026-06-10
**Status:** Accepted
**Context phase:** Phase 1, Epic 2 (applies when LP-13 builds the loan file model)

### Context

A loan file needs to be referenced in several different contexts: internal
database joins and foreign keys, human conversation between processors ("what's
the status on LF-7K3M?"), and the borrower-facing inbox email address that
documents are sent to.

An early draft of the plan used a single sequential ID (e.g. "LF-105") for both
human reference and the inbox address (lf-105@inbox.domain). This is insecure
for two reasons:

1. **Enumeration.** Sequential IDs let anyone who sees one valid ID guess
   others, leaking the count and existence of files.
2. **Capability exposure.** Deriving the public inbox address from a predictable
   ID means anyone can compute valid inbox addresses for files they have no
   relationship with — allowing them to inject documents or spam into other
   borrowers' loan files. The inbox address is a *capability* (possession grants
   the ability to send documents into a file), so it must not be predictable.

The underlying principle: an **identifier** merely names a thing (access is
controlled separately by auth), whereas a **capability** grants power by
possession alone (it must be unguessable).

### Decision

Each loan file has **three distinct identifiers**, each with a different purpose
and security posture:

| Identifier | Example | Purpose | Exposure | Generation |
|---|---|---|---|---|
| UUID primary key | `7f3a8b2c-...` | Internal references, foreign keys, joins | Never exposed | uuid4 (from UUIDMixin) |
| Display ID | `LF-7K3M` | Human reference in UI, conversation, email subjects | Authenticated users only | Non-sequential random readable code, collision-checked |
| Inbox token | `a7k4nq2x9m3p` | Borrower inbox email address | Public (in the email address) | Cryptographically secure random, ~80+ bits entropy |

**Display ID (Option C — non-sequential readable):**
- Format `LF-XXXX`, characters drawn from an unambiguous alphabet
  `23456789ABCDEFGHJKMNPQRSTUVWXYZ` (excludes 0/O, 1/I/L to avoid confusion
  when spoken or typed).
- Generated with the `secrets` module (not `random`).
- Collision-checked against existing display IDs at creation; regenerate on the
  rare collision.
- Non-sequential so that a leaked display ID does not let an attacker enumerate
  other files (defense in depth — the primary protection is still authentication
  and per-company query scoping).

**Inbox token (cryptographic capability):**
- Generated via `secrets.token_urlsafe(12)` (~16 chars, ~96 bits entropy).
- Used to construct the borrower inbox address:
  `lf-{inbox_token}@inbox.mortgageboss.ai`.
- **Never derived from the display ID** or any other predictable value.
- Stored with a unique constraint as a safety net (collision probability is
  negligible at this entropy).
- Inbound email is matched to a file by this token. As defense in depth, the
  sender is also validated against expected parties on the file; unexpected
  senders are flagged for processor review rather than auto-processed.

### Consequences

- The display ID being human-friendly does not weaken security, because its
  predictability is not the security mechanism (authentication and per-company
  scoping are).
- The inbox token being unguessable is the security mechanism for inbound email;
  it must always be generated with `secrets`, never `random`, and never derived
  from the display ID.
- Three identifiers add minor complexity to the loan file model and creation
  logic, but cleanly separate concerns.
- This same identifier-vs-capability distinction applies elsewhere and should be
  followed: password reset links, email verification links, and any future
  "share link" features are capabilities and must be cryptographically random;
  display IDs, usernames, and internal UUIDs are identifiers.

### Applies to

- LP-13 (loan file core model): implement display_id and inbox_token per this ADR.
- LP-22+ (auth): apply capability thinking to password reset / email verification.
- Any V2 share-link features.

---

## ADR-037: Database-backed enums as VARCHAR with CHECK (native_enum=False)

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Models need enum fields (status, type, etc.) stored in the
database. PostgreSQL offers a native `ENUM` type, but evolving one (adding a
value) requires an awkward `ALTER TYPE` migration.

**Decision:** Define enums as Python `StrEnum` and map them via the
`str_enum()` helper (`app/models/enums.py`), which builds a SQLAlchemy `Enum`
with `native_enum=False` (stored as `VARCHAR` + CHECK constraint) and a
`values_callable` so the enum **value** is persisted, not the member name.

**Rationale:** Adding a new value to a `VARCHAR`+CHECK column is a simple
migration, not an `ALTER TYPE`; the stored values are human-readable; `StrEnum`
is ergonomic in Python. Centralizing the mapping in `str_enum()` keeps every
enum column consistent and prevents the name-vs-value footgun (SQLAlchemy
stores the member *name* by default).

**Consequences:** Validation is a CHECK constraint rather than a native type
(slightly less strict at the DB level) in exchange for far easier evolution;
all enum columns must use the helper.

**Amendment (LP-11, 2026-06-10):** This ADR was written assuming `str_enum()`
emitted the CHECK constraint, but the original helper omitted
`create_constraint=True`. In SQLAlchemy 2.x that flag **defaults to `False`**,
so non-native enums were generated as a plain `VARCHAR` with **no** CHECK — the
column accepted any string. The gap surfaced when `User.role` became the first
enum column to reach a real migration (LP-11) and `pg_constraint` showed zero
CHECK rows. Fixed by adding `create_constraint=True` to `str_enum()`; the
constraint now follows the naming convention (e.g. `ck_users_userrole`, from
`ck_%(table_name)s_%(constraint_name)s` with the enum type name) and rejects
out-of-range values at the database level, as this ADR originally intended.
Enforcement is now at both the application (`StrEnum`) and database (CHECK)
layers.

---

## ADR-038: Money stored as Numeric/Decimal, never float

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** The application handles currency amounts (loan amounts, fees,
balances) that must be exact.

**Decision:** Store money in `Numeric(14, 2)` columns via the `Money` annotated
type (`app/models/types.py`) and always handle it as Python `Decimal`, never
`float`.

**Rationale:** Binary floats cannot represent decimal currency exactly, leading
to rounding errors; financial software must use exact decimal arithmetic.
`Numeric(14, 2)` supports amounts up to ~1 trillion with cents.

**Consequences:** Code must consistently use `Decimal`; developers must avoid
accidental `float` conversions (e.g. never `float(amount)` in calculations).

---

## ADR-039: Test database isolation via transaction rollback

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Database tests must be isolated from each other and must never
touch the development database.

**Decision:** Use a dedicated test database (`<dev_db>_test`, auto-created if
missing, separate from dev), build the schema once per session via
`Base.metadata.create_all`, and wrap each test in a transaction that is rolled
back at the end. Tests never commit.

**Alternatives considered:** create/drop tables per test (slower); truncate
between tests (more code); sharing the dev database (dangerous).

**Rationale:** Fast and fully isolated — tests cannot pollute each other or
leave residue, and a separate database protects dev data. The single
session-scoped event loop keeps the async engine, sessions, and tests on one
loop (asyncpg connections are loop-bound).

**Consequences:** Tests use `create_all`, not migrations, so they do not verify
migrations themselves (migrations are verified separately — manually now, in CI
in Phase 7); the transaction-rollback pattern is subtle but standard, and tests
must `flush` rather than `commit`.

---

## ADR-040: No generic repository/CRUD abstraction in V1

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** A common pattern is to build a generic repository / base-CRUD
layer shared by all models.

**Decision:** Do not build a generic repository abstraction in V1. Services
write explicit queries; a few small, targeted helpers (e.g. `only_active()`)
cover genuinely repeated patterns.

**Rationale:** Generic repository layers add indirection that is hard to
understand and debug; explicit queries are clearer for a solo developer
building understanding; it avoids premature abstraction.

**Consequences:** Some repetitive query code across services (acceptable); if
real duplication emerges, introduce targeted helpers rather than a framework.

---

## ADR-041: Multi-tenancy via company_id scoping from day one

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** The system will eventually serve multiple processing companies, and
each company's data (including borrower PII) must be isolated from every other's.

**Decision:** Build multi-tenancy from the very first business table. Every
business entity links to a `Company` (directly via `company_id` or transitively
through a parent), and queries are scoped with the `scope_to_company()` helper.

**Alternatives considered:** a separate database per tenant (operational
overhead, hard to manage at pilot scale); a schema per tenant (complexity);
adding multi-tenancy later (a catastrophic, error-prone retrofit).

**Rationale:** A shared database with `company_id` scoping is simplest for V1
scale; building it from day one makes isolation a habit and avoids a dangerous
retrofit. A single missed filter later would leak PII across tenants.

**Consequences:** Every query touching company-owned data must be scoped
(discipline required, helped by `scope_to_company()` and code review); a single
shared database is acceptable at pilot scale.

---

## ADR-042: Email globally unique (not per-company)

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** In a multi-tenant system, "unique" usually means unique *per
tenant*. The question is whether a user's email should be unique per-company or
globally.

**Decision:** User email is **globally unique** across the entire system
(enforced by a unique index on `users.email`).

**Alternatives considered:** unique per company (would allow the same email in
two different tenants, with company chosen separately at login).

**Rationale:** Email is the login identity — one email alone must identify the
user and determine their company, with no ambiguity. This matches the universal
expectation that one email = one account.

**Consequences:** A person working at two processing companies would need two
different emails (a rare edge case, acceptable for V1). Note this is the
**exception**: most other unique fields in tenant-owned tables should be unique
*per company*, not globally.

---

## ADR-043: Explicit company-scoping helper (no automatic query filtering)

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Tenant isolation must be enforced on every query that touches
company-owned data. The question is *how* — automatically or explicitly.

**Decision:** Provide an explicit `scope_to_company(stmt, model, company_id)`
helper that developers call. No automatic/magic session-level filtering in V1.

**Alternatives considered:** SQLAlchemy session/ORM events that auto-inject a
`company_id` filter (magic, surprising, hard to debug, easy to bypass
accidentally); hand-written `.where(Model.company_id == ...)` everywhere
(error-prone, no central named pattern).

**Rationale:** Explicit-but-helped balances safety and comprehensibility. A
single greppable helper name documents the rule and is easy to review for;
automatic filtering is hard to debug and can hide bugs. Aligns with the goal of
a codebase a solo developer can fully understand (see also ADR-040).

**Consequences:** Developers must remember to call the helper (mitigated by it
being the documented standard and enforced in review); the `CompanyScoped`
protocol makes misuse a type error. May revisit automatic scoping in V2 if the
explicit approach proves error-prone in practice.

---

## ADR-044: Companies and users soft-deleted, FK ondelete RESTRICT

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Deletion behavior must be defined for the first tenant tables
(`companies`, `users`), which anchor the audit trail.

**Decision:** Soft delete (`deleted_at`) for both companies and users. The
`users → companies` foreign key uses `ondelete=RESTRICT`, and the
`Company.users` relationship has **no destructive ORM cascade**.

**Rationale:** Soft delete preserves the audit trail (who did what, even after a
record is "removed"). We never hard-delete a company or user in normal
operation; `RESTRICT` prevents accidentally orphaning users by deleting their
company, and omitting the ORM cascade ensures the ORM never silently issues hard
deletes either.

**Consequences:** "Deleting" marks records inactive/deleted rather than removing
them; queries must filter deleted rows (the `only_active()` helper). A genuine
hard delete (e.g. GDPR erasure) would be a deliberate, separate operation, not
the default path.

---

## ADR-045: Per-company unique slugs (composite uniqueness)

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Lender slugs need to be unique, but the system is multi-tenant —
"unique" must mean unique within a tenant, not across the whole system.

**Decision:** A lender's `slug` is unique **per company** — a composite unique
constraint on `(company_id, slug)` — not globally unique. The constraint is
named explicitly (`uq_lenders_company_id_slug`) because the naming convention's
`uq` template only incorporates the first column.

**Rationale:** Two different processing companies may both work with UWM, and
each needs its own lender record with slug `"uwm"`. Per-tenant uniqueness is the
correct multi-tenant pattern. Contrast with user email, which is globally unique
(ADR-042) precisely because it is a cross-tenant login identity.

**Consequences:** Uniqueness checks in application code must be company-scoped.
This pattern repeats for most "unique" fields in tenant-owned tables; global
uniqueness is the exception, reserved for login identity.

---

## ADR-046: Lender overlays and supported programs as JSON

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** A lender carries lender-specific rule overrides ("overlays") and a
set of loan programs it handles. Both need a storage shape now, even though the
overlay structure is not yet designed.

**Decision:** Store `lender_overlays` as a JSON object (empty `{}` for now,
structured in Phase 3) and `supported_programs` as a JSON list of `LoanProgram`
values (e.g. `["conventional", "fha"]`).

**Alternatives considered:** a separate overlay-rules table (premature — the
structure is unknown until Phase 3); a join table for programs (over-engineering
for a tiny set read with the lender).

**Rationale:** The overlay structure is a Phase 3 design decision; creating the
column now avoids a later migration. `supported_programs` is a small list always
read together with the lender, so JSON is pragmatic.

**Consequences:** Less schema enforcement on overlay/program contents — the DB
does not constrain the JSON (acceptable for config data). Phase 3 will define and
validate the overlay structure at the application layer; program values are
validated against the `LoanProgram` enum in application code, not by the DB.

---

## ADR-047: LoanProgram enum (Conventional, FHA) shared across models

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Loan program is referenced by lenders (`supported_programs`) and
will be referenced by loan files (LP-13). It needs one canonical definition.

**Decision:** Define a `LoanProgram` enum (`CONVENTIONAL`, `FHA`) now, in the
lender module (`app/models/lender.py`), reusable by loan files in LP-13.

**Rationale:** A single source of truth for program values. V1 scope is
Conventional + FHA; Jumbo (and VA, USDA) are deferred to V2 per the plan.

**Consequences:** Adding programs later (Jumbo, VA, USDA) means adding enum
values. When the enum backs an actual column (e.g. on loan files), it is stored
as VARCHAR + CHECK via `str_enum()` (`native_enum=False`, ADR-037), so evolution
needs no `ALTER TYPE`. As JSON list values on lenders, program values are not
DB-constrained (ADR-046).

---

## ADR-048: Display ID globally unique

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** A loan file's `display_id` (the `LF-XXXX` human reference from
[ADR-036](#adr-036-loan-file-identifier-strategy-three-decoupled-identifiers))
could be unique per company or globally. Lender slugs are per-company
(ADR-045), so the question is genuine.

**Decision:** Display IDs are **globally unique**, enforced by a unique index on
`loan_files.display_id`.

**Rationale:** Display IDs are random and non-sequential, so global uniqueness is
cheap (no contention, no per-company sequence). It avoids any ambiguity in
cross-company support scenarios, email subjects, and logs — there is no scenario
where two files anywhere should share a display ID. This contrasts with lender
slugs, which are intentionally human-chosen and naturally collide across
companies (two companies both work with "uwm"), so those are per-company.

**Consequences:** Collision checking is global (already the case in
`generate_unique_display_id`, which queries all files). Collision probability is
negligible: 31**4 ≈ 924k codes with regeneration on the rare hit, and the unique
index is the final safety net.

---

## ADR-049: Loan file status lifecycle

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** The loan file needs a status enum capturing where it sits in the
processing workflow, to drive dashboard filtering and the actions available on a
file.

**Decision:** A `LoanFileStatus` enum with the lifecycle `DRAFT → IN_PROCESSING
→ READY_TO_SUBMIT → SUBMITTED → IN_CONDITIONS → CLEAR_TO_CLOSE → CLOSED`, plus
`WITHDRAWN` as a terminal exit reachable from any earlier state. Stored as
VARCHAR + CHECK via `str_enum()` (ADR-037), defaulting to `DRAFT`.

**Rationale:** Mirrors the real processing workflow — origination handoff
(`DRAFT`) through underwriting submission and condition resolution
(`IN_CONDITIONS`) to `CLEAR_TO_CLOSE` and `CLOSED`. `WITHDRAWN` covers files that
fall out at any point.

**Consequences:** Transitions are **not** enforced by a state machine in V1 — any
status can be set from any other at the model level. Workflow enforcement (valid
transitions, side effects) can be layered on later without a schema change.
Storing as VARCHAR + CHECK means adding a future status (e.g. `DENIED`) is a
simple migration, not an `ALTER TYPE`.

---

## ADR-050: ID generation in the service layer, not the model

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** The display ID and inbox token
([ADR-036](#adr-036-loan-file-identifier-strategy-three-decoupled-identifiers))
have to be generated somewhere. The options are a model default/`__init__`, or a
dedicated service called during file creation.

**Decision:** Generation lives in a dedicated service
(`app/services/loan_file_ids.py`), called by the file-creation service
(`app/services/loan_files.create_loan_file`). The `LoanFile` model only holds the
`display_id` and `inbox_token` columns.

**Rationale:** Generation involves real logic — cryptographically secure
randomness (`secrets`), an unambiguous alphabet, and async collision checking
against the database — none of which belongs in a declarative model. Keeping it
in a service keeps the model clean and lets the security-sensitive generation be
unit-tested in isolation (it is the first thing built and verified in LP-13).

**Consequences:** File creation must go through `create_loan_file` to obtain
correct identifiers; never hand-construct a `LoanFile` with manually-set
identifiers in normal flow (tests that do so are explicitly probing the unique
constraint). The model has no opinion on how its identifiers are produced.

---

## ADR-051: Application-level encryption for SSN, not pgcrypto

- **Date:** 2026-06-10
- **Status:** Accepted (reconsiders an LP-9 assumption)

**Context:** The borrower SSN is the most sensitive field in the system, covered
by GLBA, and must be encrypted at rest. LP-9 enabled the `pgcrypto` extension on
the assumption it would encrypt this kind of field inside the database. LP-14
revisits that choice before any encrypted column exists.

**Decision:** Encrypt at the **application** level, not in the database. A custom
SQLAlchemy `EncryptedString` type (`app/models/encrypted_types.py`) encrypts on
write and decrypts on read using Fernet (authenticated AES-128-CBC + HMAC) from
the `cryptography` library (`app/core/encryption.py`). The key lives in settings
(`ENCRYPTION_KEY`, from the environment), **never** in the database. The column
itself is plain `TEXT` holding ciphertext.

**Rationale:** With pgcrypto, the encryption key has to be presented to the
database (in SQL, a session GUC, or a function argument), so a database
compromise — a leaked dump, a read replica, a stolen backup — can expose both
ciphertext and the means to decrypt it. With application-level encryption the key
never reaches Postgres, so a database-only compromise yields **ciphertext only**.
Fernet is authenticated, so tampering is detected on decrypt rather than silently
returning garbage. Keeping the crypto in Python also makes it unit-testable in
isolation and portable if the storage backend changes.

**Consequences:**
- The `ssn` column is `TEXT` and stores ciphertext; verify-at-rest is part of the
  test suite (raw SQL read shows ciphertext, never the plaintext).
- Encryption is **non-deterministic** (a fresh IV per write), so an encrypted
  column cannot be used in a SQL `WHERE` equality, index, `ORDER BY`, or unique
  constraint. Fine for SSN (we never query by it); a future searchable-encrypted
  field would need a separate deterministic blind-index column.
- The SSN must never reach a log, repr, or error message — enforced by a
  PII-safe `Borrower.__repr__` and a `masked_ssn` (`***-**-1234`) for display.
- `ENCRYPTION_KEY` is a required setting (no default): the app refuses to start
  without it, like `JWT_SECRET_KEY`.
- **Scope:** only the SSN is encrypted in V1. Date of birth is sensitive but
  left unencrypted (lower risk, needed for matching); broadening the encrypted
  set is a deliberate later decision. **Key rotation** and **secret-manager**
  integration are Phase 7; V1 uses a single active key from settings. `pgcrypto`
  stays enabled (harmless) in case a future deterministic/DB-side need arises.

---

## ADR-052: Borrowers and properties are company-scoped transitively

- **Date:** 2026-06-10
- **Status:** Accepted

**Context:** Multi-tenancy (ADR-041) requires every piece of business data to be
isolated by company. Borrowers and properties are business data, so a query must
never surface another company's borrowers/properties. The question is whether
they carry their own `company_id` or inherit scoping through their loan file.

**Decision:** Neither `borrowers` nor `properties` has a `company_id`. They are
owned by a loan file (FK `loan_file_id`, `ondelete=CASCADE`) and are scoped to a
company **transitively** through that file. Tenant-isolated queries scope the
loan file (`scope_to_company(stmt, LoanFile, company_id)`) and reach borrowers/
properties by joining on `loan_file_id`.

**Rationale:** The loan file is the single owning aggregate root for everything
attached to a processing engagement. A denormalized `company_id` on every child
would be redundant, could drift out of sync with the file's company, and would
invite a query that scopes the child's `company_id` while joining a file from a
different company. One scoping anchor (the loan file) is simpler and safer. A
loan file never changes company, so the transitive relationship is stable.

**Consequences:**
- Queries for borrowers/properties **must** join through the loan file and scope
  that file; there is no `scope_to_company(select(Borrower), Borrower, ...)`
  because `Borrower` has no `company_id` (the `CompanyScoped` protocol correctly
  rejects it). Tenant-isolation tests assert this end-to-end.
- Hard-deleting a loan file cascades to its borrowers and property; normal flow
  soft-deletes (`deleted_at`), so the cascade only bites on a true hard delete.
- The same pattern will apply to other file-owned children (documents, extracted
  data, conditions) as they land.
