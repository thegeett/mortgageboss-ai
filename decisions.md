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

---

## ADR-053: Document type as a flexible string, category as an enum

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** A document has two classification facets: a broad **category** (one
of the processor's eight library buckets) and a specific **document type** (pay
stub, W-2, bank statement, … — a large set, finalized in Phase 2 at ~100 types).
Each needs a storage choice on the `documents` table.

**Decision:** `category` is a `DocumentCategory` `str_enum` with a DB CHECK
constraint (ADR-037). `document_type` is a plain, indexed `VARCHAR` string with
**no** CHECK — its valid values are governed at the application layer (the
classifier and the Phase 2 type registry), not the database.

**Rationale:** Categories are a small, stable, organizational set — exactly what
a DB-enforced enum is for; an out-of-range category is a bug worth rejecting at
the database. Document types are large and **evolving**: encoding them as an enum
would mean a schema migration (and a coordinated deploy) every time a type is
added or refined during Phase 2 and beyond. A flexible string decouples type
evolution from schema changes while still being indexed for filtering.

**Consequences:** There is no DB-level guarantee that `document_type` holds a
"known" value — acceptable, because the classifier only ever writes registry
values and the type set is an app-layer concern. `category` remains DB-enforced.
If a stable, closed type vocabulary ever emerges, it could be promoted to an enum
later via a normal migration.

---

## ADR-054: Document processing lifecycle status

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** A document is processed asynchronously after upload (classification,
then extraction — Epic 5 / Phase 2). The system needs to know where each document
sits in that pipeline to drive the UI and to surface failures and low-confidence
results for processor attention.

**Decision:** A `DocumentStatus` `str_enum` (VARCHAR + CHECK, ADR-037) with
`PENDING → CLASSIFYING → CLASSIFIED → EXTRACTING → COMPLETED`, plus `FAILED`
(with the reason in `processing_error`) and `NEEDS_REVIEW` (low-confidence
classification awaiting processor correction). Defaults to `PENDING`.

**Rationale:** Async tasks transition documents through these states; the status
drives UI affordances (spinners on in-flight states, a review flag on
`NEEDS_REVIEW`, an error surface on `FAILED`). Splitting `CLASSIFYING`/`EXTRACTING`
from their completed counterparts lets the UI distinguish "working" from "done"
per stage.

**Consequences:** Transitions are **not** enforced by a state machine in V1 —
tasks set the status directly (mirrors the loan-file lifecycle, ADR-049). Keeping
it VARCHAR + CHECK means adding a future state is a simple migration. `FAILED`
pairs with `processing_error`; `NEEDS_REVIEW` is the hook for the human-correction
flow built later.

---

## ADR-055: Document storage path in the database, bytes in the storage backend

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Every document has binary content (the uploaded PDF/image). It has to
live somewhere, and the `documents` record has to reference it.

**Decision:** The `documents` row stores **metadata** (`original_filename`,
`mime_type`, `file_size_bytes`) and a `storage_path` pointing at the bytes in the
storage backend (local filesystem in dev, S3 in production — LP-35). The binary
is **never** stored in the database.

**Rationale:** Storing large binaries in Postgres bloats the database, slows
backups and replication, and wastes the relational engine on opaque blobs. A
path plus external object storage is the standard pattern and lets the storage
backend scale and be served independently. `storage_path` is `VARCHAR(1024)` so
S3 keys and nested local paths fit comfortably.

**Consequences:** The database and the storage backend must be kept consistent —
an orphaned path (row without a file) or an orphaned file (bytes without a row)
is possible and is handled in the upload/cleanup flow (Epic 5). Soft-deleting a
document does not destroy the bytes, preserving the original for audit; physical
cleanup of storage is a separate, deliberate operation.

---

## ADR-056: Document upload provenance

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** A document can enter the system three ways: a processor uploads it, a
borrower emails it to the file's inbox (ADR-036), or it arrives via a MISMO
import. Audit and UI both benefit from knowing which.

**Decision:** An `UploadSource` `str_enum` (`USER_UPLOAD`, `BORROWER_INBOX`,
`MISMO_IMPORT`; VARCHAR + CHECK) records the channel, plus a **nullable**
`uploaded_by_user_id` FK to `users` (`ondelete=RESTRICT`) that is set only for
`USER_UPLOAD` — the other two sources have no user actor.

**Rationale:** The source is first-class audit/UI metadata ("uploaded by Jane" vs
"received from borrower"). `uploaded_by_user_id` is null when there is no user
behind the upload, rather than inventing a synthetic system user. `RESTRICT`
matches the soft-delete approach to users (ADR-044): a user who uploaded
documents cannot be hard-deleted out from under them.

**Consequences:** `uploaded_by_user_id` is nullable, so any query or UI that
attributes a document to a user must handle the null case (inbox/MISMO). The
source enum and the uploader column are independent but correlated — the
application sets `uploaded_by_user_id` only alongside `USER_UPLOAD`.

---

## ADR-057: Extracted data stored as JSON, typed at the application layer

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Extracted data varies by document type — a pay stub has different
fields than a bank statement, across a ~100-type set finalized in Phase 2. The
`extractions` table needs a storage strategy that holds any document type's
fields without sacrificing type safety.

**Decision:** A single `extractions` table with one `extracted_data` **JSON**
column. The *structure* of that JSON is governed by document-type-specific
**Pydantic schemas at the application layer** (Phase 2), not by the database.

**Alternatives considered:**
- *Typed columns / a table per document type* (~100 rigid tables) — a schema
  migration for every new or refined type; unworkable at the Phase 2 cadence.
- *EAV generic field rows* (the POC's `ExtractedField` bag) — an anti-pattern:
  loses all structure and type information, every read reassembles a record from
  key-value rows.

**Rationale:** One flexible table keeps the schema stable while document types
evolve. Type safety is recovered in Python: the extraction task validates and
serializes a typed Pydantic model into `extracted_data`, and readers parse it
back. This is **deliberately different** from the POC's generic field bag — V1
stores document-type-specific *structured* data that merely happens to be
persisted as JSON.

**Consequences:** There is no DB-level schema enforcement on `extracted_data`
contents — correctness is a Python concern (the Phase 2 schemas). Querying
*inside* the JSON at the DB level is not done in V1: we read the whole extraction
and parse it. If cross-extraction field querying is ever needed, Postgres
JSON(B) operators or a projection table can be added later.

---

## ADR-058: Extraction versioning with one current per document

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** A document can be extracted more than once — re-classification, an
improved prompt, a model upgrade. We want the latest result *and* the history,
without ever losing a prior extraction.

**Decision:** Extractions are **versioned**: a `version` integer (sequential per
document, from 1) plus an `is_current` boolean. A **partial unique index**,
`uq_extractions_document_id_current` = `UNIQUE (document_id) WHERE is_current`,
guarantees exactly one current extraction per document while permitting any
number of historical (`is_current = false`) rows. New versions are created
through `app.services.extractions.create_extraction_version`.

**Rationale:** Re-extraction creates a new version and keeps the prior ones for
audit and comparison. The invariant "one current per document" is enforced at the
**database** level by the partial index, not merely by application convention —
so a bug can't silently leave two current rows. A partial index is the precise
tool: full uniqueness on `document_id` would forbid history; uniqueness on
`(document_id, is_current)` would still allow two `false` rows but only one
`true`, which is *almost* right but allows no historical duplicates of `false`
semantics cleanly — the `WHERE is_current` form expresses the intent exactly.

**Consequences:** Creating a new version must **demote the old current first**
(set `is_current = false` and flush) **before inserting** the new current row, or
the insert violates the partial index. `create_extraction_version` encapsulates
that ordering. Queries for "the current data" filter `is_current = true` (or use
the `Document.current_extraction` convenience). Version numbers are taken over all
rows (including soft-deleted), so they never repeat.

---

## ADR-059: Bank-statement transactions stored in extracted_data JSON (no table in V1)

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** A bank statement contains a list of transactions — a sub-structure
within the extracted data. We could model transactions as their own table or keep
them inside the extraction JSON.

**Decision:** Transactions live **inside** the extraction's `extracted_data` JSON
as a nested list in V1. There is no separate `transactions` table.

**Rationale:** V1 reads transactions only as part of the owning extraction (to
display or verify a single statement); there is no requirement yet to query or
aggregate *across* transactions (e.g. "all large deposits across every file").
A separate table would add a join, a model, and migration surface for no current
benefit, and it would duplicate the versioning concern (transactions belong to a
specific extraction version).

**Consequences:** Cross-transaction querying/aggregation at the DB level is not
possible in V1 — acceptable for the current scope. If such a need emerges (search,
analytics, large-deposit flags spanning files), a `transactions` projection table
fed from the current extraction can be introduced in a later phase without
changing how extractions are stored.

---

## ADR-060: Finding status (red/yellow/green) and resolution lifecycle

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** The verification engine (Phase 3) produces results against a loan
file. Each result needs a representation of its severity and of where it sits in
the processor's resolution workflow.

**Decision:** Two enums per finding. `FindingStatus` captures **severity** —
`RED` (blocking), `YELLOW` (review / may need a compensating factor), `GREEN`
(passed). `FindingResolutionStatus` captures the **resolution lifecycle** —
`OPEN`, `RESOLVED`, `ACCEPTED_RISK`, `WAIVED`. A resolution **trail**
(`resolved_by_user_id`, `resolved_at`, `resolution_note`) records who resolved
it, when, and why. Both enums are VARCHAR + CHECK (ADR-037).

**Rationale:** Red/yellow/green matches how processors actually triage a file
(blocking vs. review vs. passed). The resolution lifecycle captures the real
workflow, including `ACCEPTED_RISK` — accepting a yellow flag with a compensating
factor — which a pure boolean "resolved?" could not express. The trail makes
verification auditable.

**Consequences:** Two enums per finding plus three trail columns. Resolution is
always written through `resolve_finding` so the trail stays consistent. Resolution
state must survive re-verification — see ADR-061.

---

## ADR-061: Findings belong to the loan file; resolution persists across runs

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Verification runs repeatedly over a file's life. A finding has
resolution state (a processor accepted a risk, waived an item) that must not be
lost when verification re-runs and produces "the same" finding again.

**Decision:** Findings belong to the **loan file** (a durable parent, owned child
with FK `ondelete=CASCADE`), not to a verification run. They *reference* the run
that produced them (`verification_id`), but their resolution state lives on the
finding and persists. Matching a new run's findings to existing ones to carry
resolution forward is Phase 3 logic, not part of this model.

**Rationale:** The loan file is the stable anchor; a processor who accepted a
yellow flag should not have to re-accept it on every run. Storing resolution on
the finding (owned by the file) makes that persistence natural. Decoupling the
finding's lifetime from a single run is what allows cross-run carry-forward later.

**Consequences:** Findings are not per-run throwaway records. Phase 3 must
implement run-to-run matching (by `rule_id` + target, say) to decide which
existing finding a new result corresponds to and carry its resolution forward.
Until then, each run simply creates findings.

---

## ADR-062: rule_id as a flexible dotted-namespace string

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Each finding is produced by a verification rule. The rule catalog is
large (60–80+) and finalized in Phase 3. The finding needs to identify its rule.

**Decision:** `rule_id` is an indexed `VARCHAR` string using a **dotted-namespace**
convention — e.g. `income.paystub_recency`, `fha.mip_required`,
`cross_source.income_consistency` — not an enum. Valid values are governed by the
Phase 3 rule registry at the application layer, not a DB CHECK.

**Rationale:** Same reasoning as document_type (ADR-053): a large, evolving set
where an enum would force a migration per rule added or refined. Dotted namespaces
are human-readable and group rules by area (the prefix mirrors `FindingCategory`),
which is convenient for filtering and display.

**Consequences:** No DB-level constraint on `rule_id` values — correctness is an
app-layer concern. `rule_id` is indexed for filtering findings by rule.

---

## ADR-063: verification_id column added before its FK target exists

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** A finding references the verification run that produced it, but the
`Verification` model and its `verifications` table do not exist until LP-18.
LP-17 still wants the column so the two tickets can be built independently.

**Decision:** Add `verification_id` as a **nullable, indexed UUID column with no
foreign-key constraint** in LP-17. LP-18 adds the FK constraint via a migration
once the `verifications` table exists.

**Rationale:** The column is ready for verification runs to populate (Phase 3)
without coupling LP-17 to LP-18's table. Adding only the constraint later is a
small, safe migration. Nothing writes `verification_id` until verification runs
exist, so the interim lack of referential integrity is harmless.

**Consequences:** Between LP-17 and LP-18 there is no DB-enforced referential
integrity on `verification_id` (it is just a UUID). LP-18 must remember to add
the FK constraint (`fk_findings_verification_id_verifications`). The column is
indexed now, so the eventual constraint and lookups are cheap.

---

## ADR-064: Verification run groups findings; findings reference but are not owned by it

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** The verification engine (Phase 3) runs as a batch that produces many
findings. We need a record of each run — to group its findings and keep run
history — without making findings dependent on the run's lifetime.

**Decision:** A `Verification` record represents one run and **groups** its
findings via `findings.verification_id`. But findings belong to the **loan file**
(ADR-061), so the FK on `findings.verification_id` is **`ondelete=SET NULL`**:
deleting a run **preserves** its findings and just nulls their reference. The
`Verification.findings` relationship has **no destructive cascade** and uses
`passive_deletes=True` so the database's SET NULL does the work. The run *itself*
is an owned child of the loan file (FK `ondelete=CASCADE`, ADR-052).

**Rationale:** Runs provide history and run-level metadata and group the findings
they produced, but a finding's resolution state is durable and tied to the file —
it must survive run deletion (and re-runs). SET NULL expresses exactly that: the
grouping is severable, the finding is not. `passive_deletes=True` is required so
the async ORM defers to the DB-level SET NULL instead of trying to load and null
the children itself on delete.

**Consequences:** Deleting a run nulls its findings' `verification_id` and leaves
the findings intact; deleting the loan file removes both runs and findings (they
are its owned children). The asymmetry — runs cascade from the file, findings do
*not* cascade from runs — is the whole point and is covered by tests.

---

## ADR-065: Denormalized summary counts on verification runs

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Run history wants at-a-glance summaries — how many red / yellow /
green findings a run produced — shown in lists without re-aggregating findings
each time.

**Decision:** Store `red_count`, `yellow_count`, `green_count` directly on the
`Verification` run (denormalized), defaulting to 0 and populated by the engine in
Phase 3 when the run completes.

**Rationale:** Cheap reads for run-history summaries without a `GROUP BY` over
findings on every view. The engine that produces the findings is the single
writer, so it can set the counts atomically as part of completing the run.

**Consequences:** The counts are denormalized and must be kept consistent with
the actual findings by their single writer (the engine). Minor denormalization is
accepted for read convenience; if drift is ever a concern, the counts can be
recomputed from findings.

---

## ADR-066: findings.verification_id FK added in LP-18 (deferred from LP-17)

- **Date:** 2026-06-11
- **Status:** Accepted (completes ADR-063)

**Context:** LP-17 created `findings.verification_id` as a bare nullable UUID
(ADR-063) because the `verifications` table did not exist yet. LP-18 creates that
table.

**Decision:** LP-18 adds the FK constraint
(`fk_findings_verification_id_verifications`, `ondelete=SET NULL`) now that the
target exists, in the same migration that creates `verifications` — so the
migration touches **two** tables (a `CREATE TABLE` plus an `ALTER` adding the FK).
The `finding.py` model is updated to declare the `ForeignKey` and a `verification`
relationship.

**Rationale:** Completes the deferred linkage cleanly once both tables exist,
keeping the create and the wiring in one atomic migration. SET NULL matches
ADR-064 (deleting a run preserves findings).

**Consequences:** The migration's downgrade must drop the findings FK **before**
dropping the `verifications` table (reverse order). Referential integrity on
`verification_id` is now enforced.

---

## ADR-067: NeedsItem as the loan file's requirement checklist

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** A processor needs to track outstanding requirements — "what am I
still waiting on?" — distinct from documents that have arrived and from
verification findings. This is the workflow checklist that drives document
collection and borrower communication.

**Decision:** A first-class `NeedsItem` model owned by the loan file, with a
lifecycle (`OUTSTANDING` → `REQUESTED` → `RECEIVED`, or `WAIVED`), an `origin`
(`MANUAL` / `FINDING` / `CONDITION` / `TEMPLATE`), a `priority`
(`BLOCKING`/`STANDARD`/`LOW`), an optional target borrower, and an optional
satisfying document. Transitions go through service helpers
(`create_needs_item`, `request_needs_item`, `satisfy_needs_item`).

**Rationale:** The needs list is the central workflow artifact, not a byproduct of
findings. Modeling it as its own entity lets processors add **manual** needs now,
and lets findings (Phase 3), lender conditions (Phase 4.5), and file-creation
templates (later) generate needs in future phases — the `origin` enum already
distinguishes the source. Driving transitions through helpers keeps the status
and its timestamps (`requested_at`, `satisfied_at`) consistent.

**Consequences:** Needs items are durable workflow state owned by the file
(cascade from the file, ADR-052). Generation from findings/conditions/templates is
later-phase logic; the schema supports every origin now. Lifecycle moves should
use the helpers rather than mutating fields directly.

---

## ADR-068: NeedsItem category reuses DocumentCategory; needs_type is a flexible string

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** A needs item has to say *what* it is for — broadly (a category) and
specifically (a type). The same tension as documents applies (ADR-053).

**Decision:** `category` **reuses** the existing `DocumentCategory` enum (the
stable 8-value set, DB CHECK) — imported, not redefined. `needs_type` is a
flexible, indexed app-layer string (e.g. `"w2"`, `"loe_large_deposit"`), not an
enum.

**Rationale:** Mirrors ADR-053: categories are stable and worth enforcing at the
database; specific types are a large, evolving set governed at the app layer.
**Reusing** `DocumentCategory` (rather than a parallel needs-category enum) means
a need and the document that satisfies it share one categorization vocabulary, so
the UI can group the needs list exactly like the document list.

**Consequences:** No DB constraint on `needs_type` values. Needs categorization is
deliberately coupled to the document category set — if document categories change,
needs categories change with them (intended). The migration's CHECK on `category`
is named `ck_needs_items_documentcategory` (it shares the enum's name).

---

## ADR-069: NeedsItem document and borrower links use SET NULL

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** A needs item points at the document that satisfied it
(`satisfied_by_document_id`) and optionally at the borrower it is for
(`borrower_id`). What should happen to the needs item if that document or borrower
is deleted?

**Decision:** Both FKs are nullable with `ondelete=SET NULL`. Deleting the
referenced document or borrower **nulls the link** and **preserves** the needs
item.

**Rationale:** A needs item is durable workflow state owned by the loan file
(ADR-067), not by the document or borrower it references. Losing a referenced row
should sever the link, not destroy the checklist item — the requirement still
conceptually exists. (Contrast the loan-file FK, which is CASCADE: the item has no
meaning without its file.)

**Consequences:** After a satisfying document is removed, the item remains with a
null `satisfied_by_document_id`; in V1 its `status` is left unchanged (a later
phase may re-open a satisfied item to `OUTSTANDING` — that re-opening logic is not
in this ticket). Same for a removed borrower: the item survives, file-level.

---

## ADR-070: Communication and ActivityLog as separate models

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Both a communication (a message in/out of a file) and an activity-log
entry (something happened on the file) are event records owned by the loan file.
We could model them as one table or two.

**Decision:** Two separate models. `Communication` carries **message** fields —
`direction`, `channel`, `sender`/`recipient`, `subject`/`body`, send status, a
needs-item link. `ActivityLog` records **any event** — an `activity_type`, an
optional actor, a human `summary`, and type-specific JSON `detail`.

**Rationale:** The two have little column overlap: a communication needs message
fields an activity entry doesn't, and the activity log covers non-message events
(status changes, uploads, verification runs) that have no sender/recipient. One
combined table would be mostly-null and semantically muddy. A *sent* communication
can also produce an activity-log entry (`COMMUNICATION_SENT`) — they reference the
same event from two angles, which is fine.

**Consequences:** Two tables, both owned children of the loan file (cascade,
ADR-052), both company-scoped transitively. Some conceptual overlap (a sent
message is both a communication and an activity), handled by writing both records
where it matters. Clear separation of message data vs. event data.

---

## ADR-071: ActivityLog is append-only in spirit; instrumentation is incremental

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** The activity log is the file's audit trail and timeline. Two
questions: are entries mutable, and how comprehensively do we log from day one?

**Decision:** Activity-log entries are **append-only in spirit** — written, never
edited or deleted in normal operation (the shared soft-delete columns exist for
consistency but entries aren't deleted in normal flow). A single
`log_activity` helper is the standard way to record an event. Wiring it into every
operation happens **incrementally** as operations are built — not all at once in
this ticket.

**Rationale:** An audit trail is only trustworthy if history is immutable.
Instrumenting every existing service now would touch all of them and balloon this
ticket; establishing the helper and the pattern lets adoption be incremental and
deliberate.

**Consequences:** Early operations may not all log activities until they are
instrumented. `log_activity` is the one standard entry point (don't construct
`ActivityLog` ad hoc). Entries are not deleted in normal flow even though the
columns allow it.

---

## ADR-072: Communication channel enum limited to EMAIL in V1

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Discovery noted several borrower-communication channels — email,
phone, text, portal. V1's communication module is email-based (enabled by the loan
file's inbox token, LP-13).

**Decision:** The `CommunicationChannel` enum includes **only** `EMAIL` in V1.
Other channels are added later as new VARCHAR + CHECK values when the sending
integration for them is actually built.

**Rationale:** Listing unbuilt channels would imply capabilities that don't exist.
Because enums are VARCHAR + CHECK (ADR-037), adding a channel later is a trivial
one-value migration plus the integration — there is no cost to deferring.

**Consequences:** Non-email communications can't be represented in V1 (the CHECK
rejects them — verified by test). Adding a channel later is a small migration. The
single-value CHECK renders as `channel = 'email'` rather than an `IN (...)` list,
which is correct.

---

## ADR-073: bcrypt (via the `bcrypt` library) for password hashing

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Authentication (Epic 3) needs secure password storage. The
`User.hashed_password` column (LP-11) has awaited a hashing scheme; LP-22 supplies
it. Mortgage data is GLBA-covered PII, so passwords must be salted, slow-to-brute,
and never stored or logged in plaintext.

**Decision:** Hash passwords with **bcrypt**, using the maintained `bcrypt`
library **directly** rather than passlib. The hashing/verification functions live
isolated in `app/core/security.py` (`hash_password`, `verify_password`,
`validate_password_strength`).

**Alternatives considered:** passlib + bcrypt (recent passlib releases have a known
runtime incompatibility with modern bcrypt — the version-detection code raises on
import/use; avoided); Argon2id / scrypt (fine and more modern, but bcrypt is the
pragmatic universal default and adequate here); hand-rolled hashing (never).

**Rationale:** bcrypt is slow-by-design, auto-salted (a per-password salt, so equal
passwords yield different hashes), and battle-tested. `checkpw` compares digests in
constant time. Using the library directly avoids the passlib/bcrypt friction
entirely.

**Consequences:** bcrypt only considers the first 72 bytes of input; rather than let
it silently truncate, `validate_password_strength` rejects passwords over 72 UTF-8
bytes so the behaviour is explicit. Because hashing is isolated in `security.py`,
swapping to Argon2 later is a localized change. The legacy `passlib[bcrypt]` /
`python-jose` entries (and their type stubs) in `pyproject.toml` are now superseded
by `bcrypt` + `pyjwt` and can be removed in a later cleanup.

---

## ADR-074: JWT auth with minimal, identity-only claims

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** After login, requests must be authenticated statelessly. We need a
token format and a claim policy before building the login endpoint (LP-23) and the
current-user dependency (LP-24).

**Decision:** Use **PyJWT**, **HS256**, signed with `settings.jwt_secret_key`. Issue
both **access** and **refresh** tokens. Claims are limited to the minimal standard
set: `sub` (user UUID as a string), `type` (`access`/`refresh`), `exp`, and `iat`.
The token carries **NO** role, email, company, `is_active`, or other PII. Tokens are
created/verified by pure functions in `app/core/jwt.py`; `verify_token` returns a
typed `TokenPayload` (subject + token_type).

**Rationale:** A JWT is *signed, not encrypted* — the payload is readable by anyone
holding it, and access tokens are relatively long-lived. Encoding authorization data
(role, active status) would let a stale token assert outdated permissions. Carrying
identity only and looking up authorization **live from the database** (LP-24) means
every request acts on current truth: deactivating a user or changing a role takes
effect on the next request. HS256 (shared secret) suits a single backend service; no
public-key distribution is needed.

**Consequences:** Each authenticated request does a user lookup (acceptable — it is
needed for `is_active`/`role` anyway). Token verification distinguishes three failure
modes via distinct exception classes (`TokenExpiredError`, `InvalidTokenError`,
`WrongTokenTypeError`) so LP-24 can map each to the correct HTTP status. All token
timestamps are timezone-aware UTC.

---

## ADR-075: Stateless JWT — no revocation/blocklist in V1

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Whether to support server-side token revocation (a blocklist /
deny-list) so an issued token can be invalidated before its `exp`.

**Decision:** V1 uses **stateless JWT with no revocation store**. We rely on a
bounded access-token lifetime (`jwt_access_token_expire_minutes`, default 24h) and
defer revocation and refresh-token rotation to a later hardening pass.

**Rationale:** A revocation store adds stateful infrastructure (a Redis/DB blocklist
checked on every request) and operational complexity. For a pilot, a short access
lifetime bounds the exposure window; the refresh token can be made short-lived or
rotated when revocation is built. Full revocation is a V2 concern.

**Consequences:** A stolen, unexpired access token remains valid until it expires —
this is a known, documented V1 limitation. Mitigations are the bounded lifetime now
and refresh-token rotation / a blocklist later. Because authorization is looked up
live (ADR-074), *deactivating* a user already blocks new actions immediately even
without token revocation; revocation only matters for cutting off an
already-authenticated session mid-token-life.

---

## ADR-076: Hybrid token transport — access in body, refresh in an httpOnly cookie

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** LP-23 ships the login flow. The two tokens from LP-22 (a short-lived
access token, a long-lived refresh token) must reach the browser. Where each is
stored determines its exposure to XSS, CSRF, and interception.

**Decision:** Use a **hybrid** transport. The **access** token is returned in the
JSON response body; the SPA holds it in memory and sends it as
`Authorization: Bearer`. The **refresh** token is set as a `Set-Cookie` with flags
`httponly=True`, `secure=settings.is_production`, `samesite="lax"`,
`path="/api/v1/auth/refresh"`, and `max_age` = the refresh-token lifetime. The
refresh token is **never** in any response body.

**Alternatives considered:** both tokens in `localStorage` (readable by any XSS —
rejected for the powerful long-lived credential); both tokens in cookies (the access
token would ride along on every request and need CSRF handling on all of them);
refresh token in the body (would force JS storage, the very thing we're avoiding).

**Rationale:** The refresh token is the high-value, long-lived credential, so it gets
the strongest containment — an httpOnly cookie an XSS payload can't read, scoped by
path so the browser only sends it to the refresh endpoint. The access token is
short-lived and must be read by JS to attach it, so memory (not disk) is the
pragmatic place; it dies with the tab. `secure` is environment-conditional so the
cookie works over plain-HTTP `localhost` in dev but is HTTPS-only in prod —
hardcoding either value would break dev or be insecure in prod.

**Consequences:** Login sets the cookie and returns the access token in the body;
refresh reads the cookie; logout clears it with the **same path/flags** (or the
browser won't remove it). Dev cross-origin (`:3000` ↔ `:8000`) relies on CORS
`allow_credentials=True` (LP-6) plus credentialed requests; `secure=False` +
`samesite=lax` is the dev-working combination. CSRF posture is SameSite-only in V1.

---

## ADR-077: Anti-enumeration authentication failures

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** A login endpoint that distinguishes "no such email" from "wrong
password" lets an attacker enumerate which emails are registered.

**Decision:** `authenticate_user` raises a single generic `AuthenticationError` with
an identical message for **both** an unknown email and a wrong password; the endpoint
maps it to a generic `401 "Invalid email or password"`. To also close the *timing*
side-channel, the unknown-email path runs one bcrypt comparison against a throwaway
hash so it isn't measurably faster than the wrong-password path. An inactive account
raises a distinct `InactiveUserError` → `403`.

**Rationale:** Identical responses (and comparable timing) prevent account
enumeration. The inactive case is *not* an enumeration leak: it only occurs after the
correct password is supplied, so the caller already knows the account exists — and a
clear `403` is more useful to a legitimate, locked-out user than a generic `401`.

**Consequences:** A single generic credential-failure path. The `403` for inactive
accounts is a deliberate, documented exception to the "always generic" rule, justified
by the password-already-proven condition.

---

## ADR-078: Refresh-token rotation-lite; no server-side reuse detection in V1

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** A static refresh token reused for the life of the session is weaker than
one that rotates. Full rotation-with-reuse-detection (invalidating a refresh token's
whole family if an already-used one reappears) needs server-side state.

**Decision:** **Rotation-lite** — every successful `POST /auth/refresh` issues a new
refresh token (a sliding window) and sets it as the cookie, but V1 keeps **no**
server-side store of issued/used refresh tokens and so does **no** reuse detection.
This is consistent with the stateless-JWT posture (ADR-075).

**Rationale:** Rotating on each refresh is strictly better than a static token at no
infrastructure cost. Reuse-detection requires a stateful store and family-tracking
that isn't warranted for the pilot; it is a V2 hardening item alongside revocation.

**Consequences:** A stolen, unexpired refresh token is usable until it expires, and a
replayed old token is not detected in V1. Mitigations are `httpOnly` (hard to steal)
and the bounded lifetime. Documented as a known V1 limitation.

---

## ADR-079: No public registration; no login rate limiting in V1

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Two adjacent hardening questions for the auth surface: should there be a
public signup endpoint, and should login be rate-limited?

**Decision:** V1 has **no public registration** — users are admin/seed-provisioned —
and **no login rate limiting**; rate limiting is deferred to Phase 7 hardening.

**Rationale:** V1 is an invite/admin tool for a known set of processing-company users,
so self-service signup isn't needed and a signup endpoint would be attack surface with
no product value yet. Rate limiting is genuine hardening but needs a shared counter
(Redis) and a considered policy; bcrypt's deliberate slowness is a partial brute-force
mitigation in the meantime.

**Consequences:** New users are created out-of-band (seed/admin tooling). Brute-force
protection is a known V1 gap until Phase 7; the generic-error/timing work (ADR-077)
and bcrypt slowness reduce but do not eliminate the risk.

---

## ADR-080: Auth via per-route dependencies, not global middleware

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** LP-24 adds route protection. The ticket is titled "dependencies and
middleware", but the two are different enforcement models: global middleware runs on
every request and must carve out exemptions for public routes; per-route dependencies
attach only where declared.

**Decision:** Implement authentication/authorization as **FastAPI dependencies**
declared per-route (`get_current_user`, `require_role(...)`). Public routes (login,
refresh, logout, health) opt out simply by not declaring them. No global auth
middleware. (Global request-logging/request-ID middleware is a separate Phase 7
concern.)

**Rationale:** Dependencies keep the auth logic in one reusable place, make each
route's protection explicit and greppable, and avoid the brittle "exempt these paths"
list that global middleware needs. They compose naturally (`require_role` depends on
`get_current_user`) and integrate with OpenAPI.

**Consequences:** Each protected route must declare the dependency; *forgetting* to
leaves a route public. Mitigated by review, by `CurrentUser`/`require_role` being the
obvious convention, and by Epic 4 endpoint tests. If a blanket default-deny is ever
wanted, a router-level `dependencies=[...]` can apply one to a whole router.

---

## ADR-081: Live-user lookup on every authenticated request (deactivation cutoff)

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** The access token carries only identity (`sub`); it deliberately omits
role/company/active-status (ADR-074). Something must turn that identity into an
authorization context on each request.

**Decision:** `get_current_user` looks up the **live** user by `sub` and reads
`role`, `company_id`, and `is_active` from the current DB record. A user that no
longer exists or is inactive is rejected with `401`.

**Rationale:** This realizes the minimal-claims design: deactivation and role changes
take effect on the user's next request, with no stale token able to assert outdated
authority. It is the V1 substitute for a token-revocation store (ADR-075) — `is_active`
plus the live lookup is the cutoff mechanism.

**Consequences:** One DB lookup per authenticated request — but the request needs the
`User` object anyway, so it's not extra work. A deactivated user is locked out
immediately on their next call (verified by test). A *stolen, unexpired* access token
still works until expiry as long as the user stays active — the documented stateless
limitation.

---

## ADR-082: Tenant context derives from the authenticated user

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Epic 2 built multi-tenancy (`company_id` scoping, `scope_to_company`) but
nothing yet supplies the *current* company at runtime. LP-24 closes that gap.

**Decision:** The request's tenant scope is **`current_user.company_id`**, exposed as
`get_current_company_id` / `CurrentCompanyId`. Every business endpoint (Epic 4+) scopes
its company-owned queries with `scope_to_company(stmt, Model, current_user.company_id)`.

**Rationale:** The scoping `company_id` comes from the validated token plus the live
user record, so a caller cannot present another company's id — the scope is
**non-forgeable**. This is what activates the Epic 2 multi-tenancy at runtime and makes
tenant isolation actually enforced rather than merely modelled.

**Consequences:** Every company-owned query must scope to `current_user.company_id`; a
missed scope is a tenant data leak. Mitigated by the single greppable helper, the
convention, and Epic 4 cross-tenant tests. No cross-company access in V1 (no "switch
company"); a user belongs to exactly one company.

---

## ADR-083: Role-based authorization via `require_role` (403 vs 401)

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Some routes (e.g. user/lender administration) must be limited to admins.
V1 needs role-level gating, not per-resource permissions.

**Decision:** A `require_role(*roles)` dependency factory depends on
`get_current_user` and checks the live user's role: it raises **403** when the user is
authenticated but lacks an allowed role, distinct from the **401** an unauthenticated
request gets. Multiple roles may be permitted (`require_role(ADMIN, PROCESSOR)`).

**Rationale:** Clear, conventional HTTP semantics — 401 = "who are you?", 403 = "I know
who you are, you can't do this". Building on `get_current_user` guarantees
authentication always precedes authorization. V1's two roles (PROCESSOR/ADMIN) need
nothing finer.

**Consequences:** Authorization is coarse (role-level); per-resource ACLs are out of
scope for V1. The 401-vs-403 distinction is verified by test (a PROCESSOR on an
admin-only route gets 403, not 401; an anonymous request gets 401).

---

## ADR-084: Access token kept in memory only (client half of hybrid transport)

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** LP-25 builds the frontend auth. The backend's hybrid transport (LP-23)
returns the access token in the login/refresh response body; the client must decide
where to keep it.

**Decision:** The access token lives **only in memory** — a Zustand store
(`lib/stores/auth-store.ts`) — never `localStorage`, `sessionStorage`, or a JS-set
cookie. It is intentionally volatile: a full page reload wipes it, and the on-load
silent refresh re-establishes it from the httpOnly refresh cookie.

**Alternatives considered:** `localStorage`/`sessionStorage` (readable by any XSS —
rejected for an auth credential); a JS-readable cookie (same exposure plus CSRF
surface). Memory plus silent refresh gives persistence-across-reload UX without
persisting the credential to JS-readable storage.

**Rationale:** Keeping the token out of persistent JS storage limits what an XSS
payload can exfiltrate, and the powerful long-lived refresh token is never reachable
from JS at all (httpOnly cookie). The reload cost is hidden by silent refresh.

**Consequences:** Every full reload triggers one `/auth/refresh` round-trip before the
app is usable (covered by a loading gate). Multiple tabs each maintain their own
in-memory token but share the refresh cookie. There is no offline/persisted session.

---

## ADR-085: Axios interceptors — single-flight auto-refresh with loop protection

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Access tokens expire; the client should recover transparently without the
user re-logging in, and without stampeding the refresh endpoint when several requests
401 at once.

**Decision:** A response interceptor (`lib/api/client.ts`) auto-refreshes on `401`:
the first 401 starts one `refreshAccessToken()` promise, concurrent 401s **await the
same in-flight promise** (single-flight), then all retry once with the new token.
**Loop protection:** `/auth/login` and `/auth/refresh` are exempt from auto-refresh,
and a `_retry` flag caps each request at one retry. If the refresh itself fails, the
store is cleared and the user is redirected to `/login`. The request interceptor reads
the token via `getState()` so it's always current, never a stale closure.

**Rationale:** Single-flight avoids N parallel refreshes (which would also fight over
the rotating refresh cookie). The exemptions and retry cap prevent infinite
refresh→401→refresh loops. Reading live state keeps a just-refreshed token from being
missed by an in-flight request.

**Consequences:** Transparent session continuation for the user. A genuinely expired
session ends in one clean redirect to login. The interceptor holds a small module-level
in-flight promise (reset in `finally`).

---

## ADR-086: Frontend route protection is UX, not security

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** The app needs to keep unauthenticated users out of authenticated areas,
but client-side checks can always be bypassed.

**Decision:** Client route protection (`hooks/use-require-auth.ts` + the
`app/(app)/layout.tsx` protected layout) is treated as **UX only**: it redirects
unauthenticated users to `/login` and avoids flashing authenticated chrome. It is
**never** relied on for security — the backend (LP-24) is the real boundary, verifying
the Bearer token and live user on every protected request. Public routes live outside
the `(app)` group.

**Rationale:** Anything the browser enforces, the browser can be made to skip; data is
only ever as protected as the API that serves it. Keeping this explicit prevents a
false sense of safety and keeps authorization logic where it's enforceable.

**Consequences:** No sensitive data may be embedded in client bundles or fetched
without the API's own authz. The protected layout is a convenience/UX layer; Epic 4
pages still rely on the backend to reject unauthorized access.

---

## ADR-087: Vitest for frontend unit tests

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** LP-25 introduces the first frontend logic worth unit-testing (the auth
store and the login zod schema). The frontend had no test runner.

**Decision:** Adopt **Vitest** (`pnpm test` → `vitest run`) for frontend unit tests,
with a `node` test environment and the `@/*` path alias mirrored in `vitest.config.ts`.
Scope for now: pure, non-React logic (store reducers/selectors, schema validation);
interceptor/flow behaviour is verified manually against the running backend.

**Rationale:** Vitest is fast, Vite/ESM-native, needs minimal config, and shares
Jest-style APIs. It fits TS strict and the existing toolchain without a heavy setup.
Component/E2E testing (Testing Library / Playwright) can be added later if needed.

**Consequences:** A new dev dependency and `test` script. CI wiring of `pnpm test`
into the frontend pipeline is a small follow-up (the frontend CI currently runs
biome/tsc/build, per LP-8); until then tests run locally.

---

## ADR-088: Company-centric, invite-only tenancy (no public self-registration)

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** How companies and users are onboarded, and where tenant isolation comes
from. The product is an internal tool for processing companies handling GLBA-covered PII.

**Decision:** Each **company is a tenant**, onboarded by the platform; the company
**admin** provisions processors; invited users **inherit the inviting admin's company**.
There is **no public self-registration**. `Company.slug` is the (future) subdomain
identifier, but **tenant isolation is enforced via the authenticated user's
`company_id`** (LP-24), independent of subdomains.

**Rationale:** Public self-signup means *uncontrolled* tenant assignment — a user could
end up in the wrong company, an isolation breach. Invite-only with admin-controlled
assignment fits an internal PII tool. Isolation already works via `company_id` from the
token, so subdomains are branding/UX, not the security mechanism.

**Consequences:** Company creation is a platform function (a script in V1); users are
admin/seed-provisioned. The full onboarding flow (invitation email + set-password) and
subdomain routing are staged for later phases. Documented in
`docs/onboarding-and-tenancy.md`.

---

## ADR-089: Minimal dev seed now; staged onboarding build

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Epic 4 (file CRUD) needs working, tenant-scoped accounts to build and test
against. The full onboarding flow depends on infrastructure that doesn't exist yet:
email (Phase 4), capability-token machinery (unbuilt), and DNS/TLS for subdomains
(Phase 7).

**Decision:** Build a **minimal, idempotent seed script** now
(`app/scripts/seed_dev.py`): one company + one admin + one processor with real
bcrypt-hashed passwords. Document and **stage** the full onboarding system — admin
user-management after Epic 4; invitation/set-password capability-token flow after Phase 4
email exists; subdomain routing in Phase 7. The comprehensive seed is LP-48.

**Rationale:** Unblocks the core product without prematurely building features whose
dependencies don't exist, while recording the full plan so it isn't lost. A standalone
script **commits its own transaction** (unlike services, which flush and let a request
handler commit).

**Consequences:** Seeded accounts use dev-default passwords (env-overridable, documented
DEV-ONLY, not secrets). The real onboarding UX arrives when its dependencies are ready,
tracked in `docs/onboarding-and-tenancy.md`. Default seed emails use a normal TLD
(`.com`) because the login endpoint's `EmailStr` rejects reserved TLDs like `.test`.

---

## ADR-090: Invitation and password-reset links are capability tokens (deferred)

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** The future invitation flow ("set your own password" link) and password reset
both deliver an emailed link that authorizes setting a password.

**Decision:** Both are **capability-token** flows (ADR-036): a cryptographically random,
single-use, expiring token generated with `secrets` (never sequential/derived). They
**share one mechanism**, and both are **deferred** until email (Phase 4) and the
capability-token infrastructure are built.

**Rationale:** Possession of the link grants the ability to set a password / activate an
account — a capability, which must be unguessable. This mirrors the loan-file
`inbox_token` design and keeps a single, audited token mechanism rather than two ad-hoc
ones.

**Consequences:** When built, invitations and password reset reuse the same capability
machinery. Until then, the seed script sets passwords directly. No password-bearing email
is sent in V1.

---

## ADR-091: Protected route group with a shared shell layout (structural protection)

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** The authenticated app needs consistent chrome and a single place that
enforces "you must be signed in", without per-page boilerplate or a login-screen flash
on reload (the access token is in memory, so reload starts unauthenticated until the
silent refresh resolves).

**Decision:** Authenticated pages live in a Next.js **`(protected)` route group** whose
`layout.tsx` (a) performs the auth check — redirecting to `/login` only **after** the
silent-refresh check resolves as unauthenticated (showing a loader while
`isInitializing`), and (b) renders the app shell (sidebar/header) around `{children}`.
The `/login` page stays in `(auth)`, **outside** the group, and renders with no shell.
This consolidates LP-25's protection into the layout (the `useRequireAuth` hook remains
the reusable utility; pages no longer each guard themselves).

**Rationale:** Protection and chrome are applied **once, structurally**, to everything
authenticated — the frontend analog of the backend's "auth as a declared dependency"
(LP-24). Adding a page = dropping a file in the group; it inherits both. Coordinating the
redirect with the loading state prevents flicker and premature redirects on refresh.

**Consequences:** Pages in the group must not assume they render without the shell. The
layout must keep coordinating with the silent-refresh state. Frontend protection remains
**UX, not security** — the backend is the boundary (ADR-086).

---

## ADR-092: App shell composition (sidebar + header + content), role-aware nav

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Authenticated users need a calm, consistent daily frame, and the nav must
grow as Epic 4+ ships pages and must be able to gate admin-only destinations.

**Decision:** The shell is a **sidebar** (wordmark + role-filtered nav with active-route
state) + **header** (section title, mobile nav menu, account menu with logout) +
**content** area, built on shadcn/ui and the LP-5 design tokens. Navigation is a single
config (`lib/navigation.ts`, `NAV_ITEMS`) shared by the desktop sidebar and the mobile
menu; an item may set `requiredRole`, and `visibleNavItems(role)` filters it.

**Rationale:** One cohesive, polished frame reused everywhere; a single nav config keeps
desktop/mobile in sync and makes adding a destination a one-line change; `requiredRole`
gives role-aware nav without bespoke logic. Reusing shadcn + tokens keeps it on-brand,
not a generic template.

**Consequences:** New features add a `NAV_ITEMS` entry (and a page in the group).
Role-gated items use the live user's role from the store; the gating is UX (the page and
the backend enforce real access). Far-future destinations are not pre-added. Deep mobile
polish is deferred — the sidebar collapses into the header menu below `md`, which is
sufficient for V1.
