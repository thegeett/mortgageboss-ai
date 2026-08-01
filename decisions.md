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

---

## ADR-093: Tenant scoping enforced by scoped queries; company from the authenticated user

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Loan files (LP-28) are the first tenant-owned business resource exposed via
the API. Multi-tenancy was modelled in Epic 2 and the request's company made available in
LP-24; this is where it must actually be enforced on reads and writes.

**Decision:** Every loan-file query is **scoped to `current_user.company_id`** via
`scope_to_company` (and `only_active`). The company is **never** accepted from the request
body or query. Out-of-company access returns **`404`** (the scoped query finds nothing),
not `403`. Create derives `company_id` from the user; a `company_id` in the body is ignored
(it isn't in the schema).

**Rationale:** Scoping the **query** (rather than fetching then checking ownership) means
another tenant's row never enters the result set — there is no object to accidentally leak.
The scope is **non-forgeable**: it comes from the validated token + live user, so a caller
can't reach another company by sending its id. `404` (not `403`) avoids revealing that a
resource exists (anti-enumeration).

**Consequences:** Every company-owned endpoint must scope to the user's company; the
pattern repeats for documents/conditions/etc. A missed scope is a tenant data leak —
covered here by cross-tenant tests (A cannot list/get/update/delete B's files) and the
greppable `scope_to_company` helper.

---

## ADR-094: Summary vs detail response schemas; capabilities never exposed

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** List and single-file reads have different needs, and some model fields must
never reach a client.

**Decision:** List endpoints return a lean **`LoanFileSummary`**; single-file endpoints
return a richer **`LoanFileDetail`** that may nest borrowers and the property. **`inbox_token`
is never in any response** (it is a capability — the borrower inbox email), and **raw `ssn`
is never exposed** — borrowers carry **`masked_ssn`** only. `primary_borrower_name` is a
derived convenience on the summary (from the `is_primary` borrower).

**Rationale:** Lean lists keep payloads small; rich detail serves the file view. The
inbox token grants the ability to email documents into a file, so surfacing it would be a
capability leak; the raw SSN is GLBA-covered PII that must never leave the server.

**Consequences:** Exposing the inbox token (if ever needed) is a deliberate, separate
feature, not an accidental field. All borrower views use `masked_ssn`. Tests assert no
`inbox_token` / raw SSN appears in any response body.

---

## ADR-095: Loan files addressed by UUID or display_id; soft delete only

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Processors refer to files by their human `display_id` (`LF-XXXX`), while
internal references use the UUID. Deletion must preserve the audit trail.

**Decision:** The single-file endpoints (`GET`/`PATCH`/`DELETE`) accept **either** the
UUID **or** the `display_id` in the path; the service tries to parse the identifier as a
UUID and otherwise treats it as a display id. `DELETE` is a **soft delete** (sets
`deleted_at`), never a hard delete; soft-deleted files are excluded by `only_active` and
subsequently return `404`.

**Rationale:** Accepting the display id matches how processors reference files (from the
UI, conversation, email subjects) without a separate lookup. Soft delete preserves history
(the standing repo decision) and keeps related records intact.

**Consequences:** The identifier lookup is a try-UUID-then-display-id branch (both scoped
to the company). A deleted file is unreachable via the API but retained in the database;
"undelete" would be a deliberate later feature.

---

## ADR-096: Nested borrower/property endpoints; transitive tenant scoping via the file

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Borrowers and the subject property are owned children of a loan file and
have **no `company_id`** of their own (ADR-052/053). They need an API, and it must be
tenant-isolated.

**Decision:** Manage them under **nested routes** —
`/loan-files/{file_identifier}/borrowers[/{id}]` and `/loan-files/{file_identifier}/property`
— where every route first resolves the parent file scoped to the caller's company (a
shared `ScopedLoanFile` dependency / `get_loan_file(company_id=current_user.company_id,
...)`). If the file isn't the caller's, it returns **`404` before any child is
touched** (the tenant gate). `get_borrower` additionally matches `loan_file_id`, so a
borrower id from another file is `404` under this file.

**Rationale:** The parent file is the natural, non-forgeable scope for its children;
checking it first makes the tenant boundary **structural** and the nested URLs express
the ownership. Children never carry a company id to forge.

**Consequences:** Every child endpoint resolves the file first (one shared dependency);
a missed file-scope check would be a leak — covered by cross-tenant and cross-file
tests. Flat child endpoints (`/borrowers/{id}`) are avoided. The same pattern will
serve documents and other owned children.

---

## ADR-097: SSN in-but-masked-out at the API boundary

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Processors must enter borrower SSNs, but the SSN is the most sensitive
GLBA-covered field and must never leave the server or appear in logs (LP-14: encrypted
at rest, masked for display).

**Decision:** Borrower create/update accept a **raw `ssn`** as input, written to the
`EncryptedString` column (encrypted at rest). **No response schema has a raw `ssn`
field** — borrowers are returned with **`masked_ssn`** (`***-**-1234`) only. The raw
SSN is never returned and never logged (no logging of borrower request bodies).

**Rationale:** Input must accept the real value (you can't store what you can't
receive), but output and logs must only ever see the masked form. Separating the
request (`BorrowerCreate`/`Update`, with `ssn`) from the response
(`BorrowerResponse`, with `masked_ssn`) makes the raw value unserializable on the way
out — it's structurally impossible to leak via the response model.

**Consequences:** Response schemas deliberately omit `ssn`; masking maps from the model
property. Tests assert no raw SSN in any response body and that it's encrypted at rest
(raw-column read). Any future SSN-bearing surface must repeat the masked-out discipline.

---

## ADR-098: Property is a per-file singleton (409 on duplicate); minimal primary-borrower logic

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** A V1 loan file has exactly one subject property (LP-14: DB
`unique(loan_file_id)`), and "which borrower is primary" needs *some* handling without
a full rules engine.

**Decision:** The property endpoints use **singleton** semantics: `GET`/`PATCH`/`DELETE`
operate on the one property (`404` when none), and a second `POST` returns **`409`**
(the service raises `PropertyExistsError`). Primary-borrower handling is **minimal**:
the first borrower defaults to primary at position 1; later borrowers default to
non-primary at the next position; creating/updating a borrower to `is_primary=True`
demotes the others (one primary). Otherwise it's client-managed.

**Rationale:** Matches the one-property-per-file constraint and keeps V1 simple.
Multi-property files and rich primary-borrower rules (URLA validation, mandatory single
primary) are deferred (Phase 1.5 / later).

**Consequences:** Re-creating a property after soft-delete is a separate concern (the DB
unique constraint still holds for the soft-deleted row; a partial unique index would be
a later model change). Primary-borrower consistency is largely client-managed; revisit
if the workflow needs stricter enforcement.

---

## ADR-099: Loan file creation is orchestrated (file + initial needs list + activity)

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Creating a loan file is a **workflow**, not just a row insert: a new file
should arrive with a starting needs list and a recorded creation event. The minimal
`create_loan_file` (LP-13: ids + DRAFT) does only the row.

**Decision:** Add `create_loan_file_with_setup` to `services/loan_files.py` (do **not**
fork a parallel module), composing the existing `create_loan_file` with
`generate_initial_needs_list` and one `FILE_CREATED` `log_activity` call, all in the
caller's transaction. The minimal `create_loan_file` stays for internal/test reuse; the
POST endpoint now calls the orchestration. The external response contract is unchanged —
the needs list and activity are internal side-effects.

**Rationale:** Creation behaviour belongs in one cohesive workflow function; composing
existing pieces avoids duplicating id-generation or listing logic. Keeping the minimal
creator lets services/tests make a bare file when that's all they need.

**Consequences:** Creating a file now also writes needs items + an activity (tests that
assert related-row counts were updated). The needs count is folded into the activity
detail rather than logging one activity per item (no spam).

---

## ADR-100: Initial needs list is a provisional program-based template (pending domain capture)

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** A new file needs a starting needs list, but the authoritative program- and
lender-specific requirements come from the domain expert (Priya) and have **not** been
captured yet (a Phase 0 closeout item).

**Decision:** `generate_initial_needs_list` uses a **modest, clearly-provisional**
per-program starter template (`services/needs_templates.py`): a universal baseline
(government ID, recent pay stubs, bank statements, W-2s) plus a placeholder FHA extra,
created with origin `TEMPLATE`. It is a simple, easily-extended data structure marked
`PROVISIONAL` with a `TODO(domain)`.

**Rationale:** We need a working baseline now without prematurely encoding guessed-at
requirements as authoritative (the premature-commitment trap). Being explicitly
provisional keeps it honest and signals where domain refinement is required.

**Consequences:** The template **will** be refined with Priya; downstream features treat
it as a starting point, not a source of truth. Expanding it is a one-place data edit.

---

## ADR-101: Activity logging adopted for loan file operations (first use of log_activity)

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** `log_activity` was built in LP-20 but, per ADR-071/ADR-073, **not yet wired
into any operation** — adoption is incremental. The loan-file lifecycle is the
highest-value place to start populating the audit trail.

**Decision:** Loan file create/update/delete now record activities (the first adoption):
`FILE_CREATED` on create; on update, `STATUS_CHANGED` with `{from, to}` for a status
transition else `FILE_UPDATED` with the changed field names; `FILE_DELETED` on soft
delete. The actor is the current user, threaded from the endpoint as `actor_user_id`. The
pure mutators stay logging-free; thin `*_with_activity` wrappers (which the endpoints
call) add the logging, mirroring the `create_loan_file` / `create_loan_file_with_setup`
split. Two enum values — **`FILE_UPDATED`** and **`FILE_DELETED`** — were **added to
`ActivityType`** (a VARCHAR + CHECK swap migration, the cheap evolution ADR-037 designed
for) so updates/deletes log semantically-correct types rather than reusing an ill-fitting
one.

**Rationale:** Starting the audit trail on the loan-file lifecycle is the natural first
adoption; using correct activity types (rather than overloading `NOTE_ADDED`) keeps the
trail meaningful. The wrapper split keeps the pure functions usable internally/in tests
without forcing an actor.

**Consequences:** Activities accumulate per file (create/update/delete). Other operations
get instrumented incrementally later (ADR-073 still holds). The activity-timeline UI is a
later frontend concern. The two new enum values required a migration (and are reflected in
tests via `create_all`).

---

## ADR-102: Keep LP-27's `(protected)` route group and `/loan-files` paths over the plan's `(app)`/`/files`

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** The Phase-1 plan text says the Epic-4 frontend lives under `app/(app)/` with
`/dashboard` and `/files`. LP-27 actually built a `(protected)` route group with
`/dashboard` and `/loan-files` (matching the API resource and the nav).

**Decision:** The dashboard and all Epic-4 frontend use LP-27's **`(protected)` group**
and **`/loan-files`** paths, not the plan's `(app)`/`/files`. LP-31 replaces the
`/dashboard` stub with the real dashboard; "New file" → `/loan-files/new` (LP-32), a row
→ `/loan-files/{display_id}` (LP-33). The plan's paths are treated as indicative.

**Rationale:** LP-27 made concrete, working choices the plan predates; renaming working
code for no benefit causes churn. `/loan-files` aligns the URL, the nav item, and the API
resource name.

**Consequences:** LP-32/LP-33 follow the same scheme. The plan's `(app)`/`/files` wording
is superseded.

---

## ADR-103: Small scoped extension to the loan-file list endpoint (search + summary fields + repeatable status)

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** The dashboard needs real server-side search and real columns (property
address, lender name) that the LP-28 summary lacked, and grouped filter pills that map to
several statuses at once.

**Decision:** Extend `GET /loan-files` *tightly* (not a redesign): an optional
company-scoped **`search`** (matches `display_id` or a borrower's name, case-insensitive);
add **`lender_name`** and **`property_address`** to `LoanFileSummary` (resolved via
eager-loaded `lender`/`property`, null when absent); and make **`status` repeatable** (a
list) so grouped pills filter to several statuses with correct pagination. Nothing else
changes; `inbox_token`/raw `ssn` remain absent.

**Rationale:** Faking these client-side (search over one page; "—" for lender/property;
client-side multi-status filtering that breaks pagination/counts) would degrade the core
screen and mislead. A tight, scoped extension keeps it honest. Search is always composed
with `scope_to_company`, so it can't cross tenants (tested).

**Consequences:** The summary resolves lender/property (eager-loaded to avoid N+1; the
detail endpoint also eager-loads lender now). `status` accepts one *or* several values
(single-value callers are unaffected). The endpoint is otherwise stable.

---

## ADR-104: Dashboard filter-pill status groupings

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** The dashboard pills (All / Active / Action needed / Completed) must map the
eight-value `LoanFileStatus` enum to a processor's mental model.

**Decision:** One source of truth (`lib/loan-files/status.ts`): **All** = no filter;
**Active** = `DRAFT`, `IN_PROCESSING`, `READY_TO_SUBMIT`, `SUBMITTED`, `CLEAR_TO_CLOSE`
(the in-progress statuses — `CLEAR_TO_CLOSE` is included so no status is orphaned);
**Action needed** = `IN_CONDITIONS` (a V1 proxy); **Completed** = `CLOSED`, `WITHDRAWN`.
The four non-"All" groups are disjoint and together cover all eight statuses (verified by
test). The same module also holds the single status → label/badge-colour mapping.

**Rationale:** A processor thinks in "what's active / what needs me / what's done", not in
eight raw statuses. Including `CLEAR_TO_CLOSE` in Active avoids a status that no pill
surfaces. "Action needed" starts as `IN_CONDITIONS` and will later also include files with
outstanding **blocking** needs once that's surfaced.

**Consequences:** Groupings live in one place (UI + the repeatable `status` query). Refine
"Action needed" when needs-surfacing exists. The plan's example Active set (four statuses)
is extended by one (`CLEAR_TO_CLOSE`) for completeness — documented here.

---

## ADR-105: Intake orchestration — sequential, file-first (Option A)

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** The new-file intake form captures borrower, property, loan, and lender info
across separate resources. It needs a submit strategy: one atomic call, or composed calls.

**Decision:** The form submits via **sequential** calls (Option A, file-first):
`POST /loan-files` → `POST .../borrowers` (primary) → `POST .../property`. **File creation
is the gate**: if it fails, show an error and stay on the form (retryable). If the file is
created but the borrower or property step fails, **navigate to the file anyway** with a
**non-blocking warning** (toast) that the part couldn't be saved and can be added on the
file. **No client-side rollback**, and no atomic `POST /loan-files/intake` endpoint in V1.

**Rationale:** A created DRAFT file with partial info is genuinely usable — files
legitimately start sparse (LP-13) — so a half-saved file is a usable result, not an error
dead-end. Composing existing endpoints needs no new transactional endpoint and matches how
processors actually start files (create, then enrich).

**Consequences:** A partial failure leaves a DRAFT missing its borrower/property, addable
on the detail page (LP-33). An atomic intake endpoint is a possible future refinement if
all-or-nothing creation ever matters. The dashboard list query is invalidated on success.

---

## ADR-106: Light, DRAFT-friendly intake validation

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** How much to require on the intake form. A loan file can be created empty/DRAFT
(LP-13); over-gating would fight that and the real workflow.

**Decision:** **Minimal** required fields — only the primary borrower's **first + last
name** — with **format validation only where a value is entered** (email, SSN pattern,
2-letter state, ZIP, non-negative amounts; empty = "not provided"). No heavy required-field
gate. Implemented with Zod (`z.union([z.literal(""), <format>])` for optional-with-format).

**Rationale:** Forcing fields would block the sparse starts the model supports; format
checks prevent bad data without blocking. Requiring the borrower name is the one real
anchor (you're creating a file *for* a borrower) and keeps the orchestration simple (the
primary borrower is always created).

**Consequences:** Files can be created with little info and enriched later. Richer guided
validation can be added if the workflow needs it.

---

## ADR-107: GET /lenders (company-scoped) for intake; primary-borrower-only intake in V1

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** The intake lender dropdown needs real data, and the borrower section needs a
scope decision (one borrower vs a repeatable co-borrower UI).

**Decision:** Add a small **company-scoped `GET /lenders`** (`LenderSummary` =
`{ id, name, supported_programs }`; `scope_to_company` + `only_active`; no pagination) to
populate the dropdown — an empty list is a graceful state until lenders are seeded (LP-48).
The V1 intake form captures the **primary borrower only**; co-borrowers are deferred
(the API already supports multiple borrowers, so they can be added on the detail page or a
later enhancement).

**Rationale:** A real dropdown needs real, scoped data (no faking). A repeatable
multi-borrower UI is complexity the first intake flow doesn't need; the primary borrower is
the essential one.

**Consequences:** Lenders appear once seeded; the dropdown shows "No lenders configured"
meanwhile. Co-borrowers are a later addition. The lenders endpoint is tested for tenant
scoping.

---

## ADR-108: File detail as a nested layout with a persistent header + route-based tabs

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** A single loan file is a workspace with several aspects (overview, documents,
verification, …). It needs structure that keeps the file's identity visible while moving
between those aspects, and a place future feature-views slot into.

**Decision:** Build it as a Next.js **nested layout** — `app/(protected)/loan-files/[id]/
layout.tsx` fetches the file once (`useLoanFile`) and renders a **persistent header**
(borrower name / `display_id` / status badge / dates) + **tab navigation**; each tab is a
**page** rendering into `{children}`, so the header/tabs persist across tab switches. Tabs
are **route-based links** (not ARIA tabs/tabpanels — each tab is a sub-route) with
`aria-current` on the active link, derived from `usePathname`. The URL uses the
**`display_id`** (`/loan-files/LF-XXXX`); the dashboard and intake already navigate by it.

**Rationale:** This is the standard App Router tabbed-detail pattern; the file context stays
on screen while you switch aspects; tabs map to the file's processing lifecycle; future
feature-views become tab pages without rebuilding chrome. Route-based links (vs ARIA tabs)
are the correct semantics when each tab is its own URL. The status→badge mapping is reused
from one shared module (`components/status-badge.tsx` over `STATUS_META`) — no second copy.

**Consequences:** Per-file features are added as tab pages (LP-34 fills Overview). The
header/tabs are defined once. A `404` (missing or out-of-company — tenant-safe) shows "File
not found".

---

## ADR-109: Show all file tabs now with clearly-labeled placeholders

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Most of the file's tabs lead to features built in later phases. Whether to show
only the built tabs or all of them.

**Decision:** Show **all six** tabs immediately; the not-yet-built ones render **unmistakable
"coming in Phase X"** placeholders (a dashed-border card with the phase badge).

**Rationale:** Unlike *top-level nav* — where phantom items mislead about what the app can do
(so LP-27/ADR-092 pre-adds nothing) — clearly-labeled *file tabs* honestly convey the file's
intended processing lifecycle and set expectations, **as long as each placeholder plainly
states it's upcoming**. This is the difference between "the app claims a capability it lacks"
and "this file will gain these aspects in these phases."

**Consequences:** Tabs resolve to placeholders until their phases land; each placeholder must
stay clearly *upcoming* (never a real-but-empty feature). The tab set + target phases live in
one config (`lib/loan-files/tabs.ts`). A leaner overview+documents-only shell was the
alternative.

---

## ADR-110: Overview surfaces needs + activity via small scoped reads

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** The file overview (LP-34) needs the file's **needs list** and **activity
feed** — data the LP-28 detail response doesn't carry.

**Decision:** Add two small, read-only, **transitively company-scoped** endpoints —
`GET /loan-files/{id}/needs` and `/activity` — rather than folding them into the detail
response. Both reuse the LP-29 `ScopedLoanFile` gate (resolve the parent file with the
caller's company **first** → `404` if it isn't theirs), so a file from another company
returns `404` (tested). `needs` is ordered blocking-first; `activity` is recent-first,
capped at 20. The overview composes these with the cached detail (borrower card uses the
existing LP-29 `/borrowers` read for the richer fields).

**Rationale:** The overview needs real needs/activity data; separate endpoints keep them
independently loadable and reusable for the fuller needs/activity views later, and keep
the detail response lean. Transitive scoping reuses the established pattern — no
`company_id` from the client.

**Consequences:** Two small endpoints added. The overview loads a few queries (detail +
borrowers + needs + activity), each with its own loading/empty/error state. Folding into
detail remains an option if ever preferred. The needs list is provisional template data
(ADR-100) — shown as-is.

---

## ADR-111: Overview phase placeholders (AI summary, key metrics) kept honest

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** The overview's intended full shape includes an AI summary and computed key
metrics (DTI/LTV), both built in later phases.

**Decision:** Show **clearly-labeled "coming in Phase X"** placeholders for the AI summary
(Phase 6) and key metrics (Phase 3) on the overview — small dashed-border cards with the
phase badge — alongside the real cards/needs/activity.

**Rationale:** Conveys the overview's intended shape and roadmap without faking content,
consistent with the honest-placeholder discipline (LP-33 tabs / ADR-109, the EMAIL-only
enum / ADR-072). The real content lands in the named phases.

**Consequences:** The placeholders remain clearly upcoming; the real AI summary (Phase 6)
and metrics (Phase 3) replace them when those phases land.

---

## ADR-112: Storage abstraction with a local backend; S3 deferred to production

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Uploaded document **bytes** need a home. The `Document` model (LP-15,
ADR-057) deliberately stores a `storage_path`, not the bytes — so something has to own
the bytes behind that path. In dev we want zero infrastructure; in production we want
durable, scalable object storage (S3). The upload endpoint (LP-36), PDF text extraction
(LP-40), and the processing tasks (LP-42) will all read/write bytes and must not care
where they live.

**Decision:** Introduce a `StorageBackend` interface (async `save` / `read` / `delete` /
`get_url`) with a `LocalStorageBackend` for dev (filesystem under a configured root). A
settings-driven factory (`get_storage_backend`, keyed on `storage_backend`) returns the
configured backend. An **S3 backend** is added in production (Phase 7) as a new
implementation plus an `"s3"` branch in the factory — calling code talks only to the
interface and does not change. Blocking file I/O is wrapped in `asyncio.to_thread` so the
interface is genuinely async.

**Rationale:** Decouples the application from where bytes live. Local keeps dev simple
(no S3/minio to run); object storage gives production durability and scale. Swapping is a
**config change, not a rewrite**. This realizes the LP-15 storage-path decision (ADR-057).

**Consequences:** All document byte I/O flows through the interface. Adding S3 is a new
class + config, no calling-code churn. `get_url` returns `None` for local (no direct URL);
presigned URLs are an S3-era capability. The factory is an `lru_cache` singleton.

---

## ADR-113: Tenant-prefixed UUID storage path; path-traversal safety

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** File and path handling is a classic vulnerability source (path traversal,
collisions, executing uploaded content). Storage paths must be safe to build from request
data and safe to resolve on disk.

**Decision:** Storage paths are `{company_id}/{file_id}/{document_id}.{ext}`, built from
**server-controlled UUIDs** (never user input); only the extension derives from the
filename, and it is **sanitized** (lowercased, stripped to alphanumeric, enforced against
an allowlist, falling back to `bin`). The `LocalStorageBackend` resolves every path and
**rejects anything that escapes the storage root** — `../`, absolute paths, escaping
symlinks — raising `StorageError` *before* any filesystem operation. The storage root
sits **outside any web-served/static directory**, so stored files are reachable only
through auth'd endpoints, and stored files are treated as **data, never executed**.

**Rationale:** UUID path components prevent collisions and remove attacker-controlled
strings from the path. The tenant prefix organizes bytes by company and leaves room for
per-tenant storage controls. Resolving-then-checking is the robust traversal defense
(it accounts for `..` and symlinks, not just string matching). Keeping the root out of
any served directory means there is no direct-URL bypass of authorization.

**Consequences:** Original filenames are kept on the `Document` record, not in the path.
Strong, tested path-handling safety (traversal rejection is a dedicated test). Direct-URL
access (`get_url`) is an S3-era feature (`None` for local — served via LP-36's endpoint).

---

## ADR-114: Document URL shape — nested upload/list, flat get/download/delete; flat routes scoped via document→file→company

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Documents are owned children of a loan file with no `company_id` of their own
(ADR-052/053). Some operations are inherently file-scoped (upload, list); single-document
operations (get, download, delete) only need the document id. We need both ergonomic URLs
and airtight tenant isolation.

**Decision:** Upload/list are **nested** under `/loan-files/{file_identifier}/documents`
and use the LP-29 `ScopedLoanFile` gate (resolve the parent file with the caller's company
first → `404`). Get-one/download/delete are **flat** under `/documents/{document_id}` and
resolve the document's company by **joining `Document → LoanFile`** in
`get_document_for_company`, filtering on `LoanFile.company_id == current_user.company_id`
(and `only_active` on both). A flat route returns `404` unless the document's file belongs
to the caller's company — never loading a document by id alone.

**Rationale:** Nested routes match how uploads/lists are scoped (per file); flat routes are
convenient for single-document actions whose id is globally unique. Because documents have
no own `company_id`, the join through the loan file is the tenant boundary. `404` (not
`403`) avoids revealing that a document exists in another company (anti-enumeration).

**Consequences:** Every flat-route handler MUST use the company-scoped lookup; this is
covered by cross-tenant tests (a Company A user cannot get/download/delete a Company B
document by id, nor upload to/list a Company B file). `company_id` is always taken from the
authenticated user, never the request.

---

## ADR-115: Upload validation (50 MB; PDF/JPEG/PNG by content-type + magic bytes); bytes served only via the auth'd download

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Uploads are an attack surface (resource exhaustion, type spoofing, serving
attacker content). The bytes carry tenant-sensitive borrower PII.

**Decision:** Uploaded files are limited to **50 MB** and to **PDF/JPEG/PNG**, validated by
a **content-type allowlist AND a magic-byte signature** whose detected type must match the
declared one (`%PDF`, `\x89PNG\r\n\x1a\n`, `\xff\xd8\xff`). The size check reads in chunks
and aborts at the cap, so an oversized upload is never fully buffered. A batch is
all-or-nothing: if any file fails validation the whole request is rejected and nothing is
persisted. Size failures map to `413`, type failures to `415`. Stored bytes are served
**only** through the auth'd `/documents/{id}/download` route (no direct URL); `get_url`
returns `None` for the local backend. This pairs with the LP-35 path/extension
sanitization (defense in depth).

**Rationale:** The size cap bounds resource use; the type allowlist restricts to
processable, lower-risk formats; magic bytes resist content-type spoofing (a `.txt`
labelled `application/pdf` is rejected). Serving only via the authenticated endpoint keeps
PII behind authorization and avoids any direct-URL bypass.

**Consequences:** Non-PDF/image types are rejected (revisit if more types are needed). A
defense-in-depth posture (endpoint validation + storage sanitization). Deep content
validation / virus scanning remains a later hardening item.

---

## ADR-116: Soft-delete preserves stored bytes; documents start at status PENDING

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Deleting a document and the lifecycle of a freshly uploaded one both need a
defined policy, consistent with the project's soft-delete and processing discipline.

**Decision:** Deleting a document is a **soft delete** (`deleted_at`) that **preserves the
stored file** — only the record is hidden from active reads; the bytes remain in the
storage backend for audit. Uploaded documents start at status **`PENDING`** (with
`upload_source = USER_UPLOAD`, `uploaded_by_user_id = current_user.id`), the signal the
processing pipeline (LP-42) picks up. Uploads also append a `DOCUMENT_UPLOADED` activity.

**Rationale:** Preserving originals supports the audit trail and any future undelete.
`PENDING` cleanly decouples upload from processing (triggered separately in LP-42),
consistent with the soft-delete-everywhere principle.

**Consequences:** Storage accumulates soft-deleted files — a retention/cleanup policy is a
later concern. Processing is not triggered here; an uploaded document sits `PENDING` until
the pipeline lands.

---

## ADR-117: A single Anthropic client wrapper for all AI calls

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** This is an AI-heavy product: classification (LP-38), extraction (LP-39), and
later verification all call Claude. Each call needs the same cross-cutting handling —
retries, observability, cost tracking — and we don't want that logic copy-pasted into every
feature or each feature talking to the SDK directly.

**Decision:** All Claude calls go through one wrapper (`app/ai/client.py`): a lazily
initialized singleton `AsyncAnthropic` (`get_anthropic_client`, LP-35 factory style), and an
async `complete(...)` that owns transient-only retry with exponential backoff + jitter and a
max-attempts cap, latency timing, structured metadata logging, and token-usage surfacing
(`AICompletion`). Cost estimation lives alongside in `app/ai/cost.py`. The wrapper owns
retries, so the SDK's built-in retries are disabled (`max_retries=0`). The missing-key error
fires at call time, not import, so the app and tests load without a key.

**Rationale:** Centralizing the AI concerns keeps the features focused on their own logic
and gives uniform retries/observability/cost with one place to evolve policy. A prompt-
agnostic wrapper is reusable by every AI feature.

**Consequences:** Features depend on `complete(...)`, not the SDK. The wrapper is the single
authority for retry/logging/timing/cost policy. Streaming is out of scope for V1 (standard
request/response).

---

## ADR-118: Retry transient errors only; log metadata, never content (PII)

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** API calls fail in two very different ways — transient (rate limits, server
blips, network) versus deterministic client errors (a malformed request, a bad key). And
the prompts/responses carry borrower PII (pay-stub and bank-statement data).

**Decision:** Retry **only transient** failures — 429, 5xx, and connection/timeout
(`APIConnectionError`/`APITimeoutError`) — with exponential backoff + jitter up to the
attempt cap; **fail fast** on every other 4xx (400/401/403/404/422). Structured logs record
**metadata only** — model, input/output tokens, latency, attempt, outcome, error type — and
**never** the prompt or response content. `_is_transient` classifies via the SDK's exception
hierarchy.

**Rationale:** Retrying a deterministic 4xx just wastes time and money and masks bugs;
backoff + jitter avoids thundering herds on a shared rate limit. Prompt/response content is
PII and must not leak into logs or aggregation; metadata is enough to operate and debug.

**Consequences:** A bad-request bug surfaces immediately rather than after N retries.
Debugging relies on metadata; any content logging would be a redacted, debug-only option,
never the default. Tests assert that captured logs exclude prompt/response content.

---

## ADR-119: Cost estimation via a maintained pricing table (estimate, not billing)

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Per-call cost visibility matters for an AI-heavy product, but model strings and
token prices change over time and must not be baked in as authoritative facts.

**Decision:** `estimate_cost(model, input_tokens, output_tokens)` uses a per-model pricing
table (`app/ai/cost.py::PRICING`, USD per token) that is **clearly marked as an estimate** to
keep current with Anthropic pricing (`TODO(pricing)`); the model identifiers in settings are
likewise marked `TODO(models)` to verify. An unknown model falls back to `DEFAULT_RATE`
(`0.0`) and logs `ai_cost_unknown_model`. The estimate feeds `Extraction.cost_estimate`
(LP-16) and `Verification.total_cost_estimate` (LP-18) — callers persist it.

**Rationale:** An estimate is sufficient for tracking and trend-watching; treating prices
and model strings as maintained configuration (not facts) keeps them honest as Anthropic's
offerings change. A visible warning on unknown models flags table gaps instead of silently
mis-costing.

**Consequences:** The pricing table and model strings must be kept current — they are
explicitly developer-verified. Output is an estimate, not a billing figure. Unknown models
contribute `0.0` (and warn) rather than guessing.

---

## ADR-120: Classification returns a typed result (type/confidence/reasoning); type is a flexible string

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Extraction (LP-39) is type-specific, so the document type must be determined
first. The type taxonomy is large (~100 types) and evolving (finalized in Phase 2), and the
pipeline needs a signal for when to route a document to human review.

**Decision:** `classify_document(text: str) -> ClassificationResult` where
`ClassificationResult` is `{ document_type: str, confidence: float in [0,1], reasoning: str }`.
`document_type` is a **flexible lowercase string** (consistent with the LP-15 Document model),
not an enum; `confidence` drives the downstream `NEEDS_REVIEW` decision; `reasoning` is a
short human-readable note for debugging and processor trust. The module returns a result —
persisting it onto the `Document` is the pipeline's job (LP-42).

**Rationale:** A string type avoids a DB migration every time the taxonomy changes (governed
at the app layer). Confidence lets the pipeline route low-confidence documents to review
rather than trusting a guess. Reasoning aids debugging without exposing raw content.

**Consequences:** Type validity is an app-layer concern, not enforced by an enum. The result
is decoupled from persistence (LP-42 writes it). `unknown` + low confidence is the
human-review signal.

---

## ADR-121: Prompts stored as files, loaded at runtime (starting with classification)

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Prompts are iterated, tuned content — not program logic — and the real
classification prompt is a POC asset that the developer pastes in. We want to edit prompts
without touching code, and to version/diff them.

**Decision:** Prompts live as files under `app/ai/prompts/**/*.txt` and are loaded at runtime
via `app/ai/prompt_loader.py::load_prompt(relative_path)` (resolved relative to the prompts
dir — CWD-independent — path-checked against escape, and cached). The classification prompt
is `classification/document_classifier.txt`; a clearly-marked **starter** ships until the POC
prompt replaces it. Extraction (LP-39) reuses the same loader.

**Rationale:** Files are versionable, diffable, and editable without a code change or
redeploy of logic; one loading pattern serves every AI feature. Keeping the prompt out of
Python means swapping in the POC prompt is a content edit, not a code edit.

**Consequences:** Prompt edits don't require code changes. The starter prompt must be
replaced with the POC's tuned prompt (flagged in the file and the ticket). The loader is the
shared entry point for all prompts.

---

## ADR-122: Graceful failure — classification never crashes the pipeline

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** AI is probabilistic and its dependencies fail (rate limits, malformed output,
empty/garbage text). A single document's classification failure must not take down the batch
processing pipeline (LP-42).

**Decision:** `classify_document` **never raises**. Empty/insufficient text short-circuits to
`ClassificationResult.unknown(...)` *without* an API call; an `AIClientError` or unparseable
output returns `unknown` too. JSON parsing is defensive — it extracts the first balanced
`{...}` object (tolerating ```` ```json ```` fences and surrounding prose), clamps
`confidence` to `[0,1]`, and treats a missing/empty `document_type` as `unknown`. The
pipeline (LP-42) treats unknown / low-confidence as `NEEDS_REVIEW`.

**Rationale:** "Needs review" is a far better outcome than an exception that fails the batch.
Defensive parsing is mandatory because model output is not guaranteed to be clean JSON.
Skipping the API call on empty text saves cost and latency.

**Consequences:** Callers always receive a `ClassificationResult`. Low-confidence/unknown is
the human-review signal. The defensive parser is part of the contract and is tested against
fenced/preambled/garbage input.

---

## ADR-123: Typed document-specific extraction (PayStubExtraction), not a generic field bag

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Extraction reads structured values out of a document. The POC used a generic
`ExtractedField` bag (arbitrary key/value rows); LP-16 deliberately rejected that in favor of
document-type-specific structure typed at the application layer and stored as JSON
(`Extraction.extracted_data`, ADR-057). LP-39 builds the first such type.

**Decision:** Extraction produces a typed, document-specific Pydantic schema —
`PayStubExtraction` — with named, typed, mostly-nullable fields (`gross_pay: Decimal | None`,
`pay_period_end: date | None`, …), wrapped in a `PayStubExtractionResult` (`data`, `status`,
`confidence`, `reasoning`). It serializes to JSON for `Extraction.extracted_data` (persisted
and versioned by LP-42, not here). `status` reuses LP-16's `ExtractionStatus`.

**Rationale:** Typed fields are what make extracted data **verifiable** downstream — Phase 3
compares `gross_pay` / `pay_period_end` as a `Decimal` / `date`, which a generic string bag
can't support cleanly. JSON storage plus app-layer typing is exactly the LP-16 design.

**Consequences:** Each document type needs its own schema + prompt + module — a per-type
pattern. LP-39 builds one (pay stub); Phase 2 replicates it. The `PayStubExtraction` field
set is a V1 starter to refine with the domain expert (Priya).

---

## ADR-124: Pay stub only for Phase 1; the per-type extraction pattern is the deliverable

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** There are ~100 document types (finalized in Phase 2). Building all of them now
would be premature; we first want to prove the full pipeline shape on one common type.

**Decision:** Implement extraction end-to-end for the **pay stub only** in Phase 1
(`extract_pay_stub`), establishing the module/schema/prompt pattern and the shared parsing
helpers (`app/ai/parsing.py`, factored out of LP-38). The other types come in Phase 2 by
replicating the pattern.

**Rationale:** Proving upload → text → classify → extract on one income-central type
de-risks the architecture before fanning out; the reusable **pattern** (and the shared
defensive-parsing primitives) is the real asset, not the single type.

**Consequences:** Only pay stubs extract in V1. The pattern + the shared `app/ai/parsing.py`
helpers are reused by every future type. Classification (LP-38) was refactored to use the
shared helpers (no behavior change).

---

## ADR-125: Honest nulls, no hallucination; extraction reads, it does not judge

- **Date:** 2026-06-11
- **Status:** Accepted

**Context:** Extracted values feed deterministic verification (Phase 3). The
AI-extracts / deterministic-verifies separation only holds if extraction is faithful — a
fabricated value would corrupt every downstream check.

**Decision:** Missing/illegible values are `null` — the prompt explicitly forbids guessing or
inventing. Extraction reports what's on the document (including absences) and does **not**
verify, compute, or judge plausibility (Phase 3's job). Value coercion is **tolerant**: a
single uncoercible field drops to `None` and marks the run `PARTIAL` rather than failing the
whole extraction. `extract_pay_stub` never raises; any AI/parse failure or empty text returns
`PayStubExtractionResult.failed(...)`. The document text, raw response, and extracted values
are never logged (PII) — only metadata (status, confidence, non-null field count).

**Rationale:** A hallucinated income figure could falsely pass verification — far worse than
a missing one that simply routes to review. Tolerant per-field coercion preserves the good
fields when one is malformed. Logging values would leak borrower PII.

**Consequences:** Downstream must handle nulls; low confidence / many nulls / `FAILED` →
`NEEDS_REVIEW` (pipeline, LP-42). Per-field confidence is deferred (one overall confidence in
V1). The defensive/tolerant parser is part of the contract and is tested against
fenced/garbage input and bad field values.

---

## ADR-126: AI wrapper supports native document/image input (full-document reading)

- **Date:** 2026-06-11
- **Status:** Accepted
- **Revises:** the LP-37 wrapper (ADR-117/118/119); updates the planned LP-40

**Context:** The original plan had a deterministic PDF text-extraction step (LP-40) feed
pre-extracted **text** to classification (LP-38) and extraction (LP-39). Architecture update:
the AI features now send the **full document** (PDF / image bytes) to the model for native
reading — text-layer PDFs, scanned images, and photos are handled uniformly, with no OCR
step, mirroring the POC's full-document approach.

**Decision:** Extend the LP-37 wrapper to accept document/image content blocks.
`build_document_block(*, content: bytes, media_type: str)` builds a base64 `document` block
for `application/pdf` and an `image` block for `image/jpeg` / `image/png` (`image/jpg`
normalized to `image/jpeg`); unsupported types raise `ValueError`. `build_document_message`
assembles a `user` message of `[<block>, optional text]`. The block shape is **verified
against the installed anthropic SDK (0.109.1)**. `complete(...)` forwards `messages` to the
SDK **unchanged**, so document-bearing messages flow through the same retry/logging/timing
path — no signature break, text-only callers unaffected. All existing behavior (transient-only
retry + backoff + jitter + cap, fail-fast on 4xx, `AICompletion` usage, `AIClientError`,
cost.py) is preserved.

**Rationale:** Native document reading is more capable and uniform than OCR-then-text and
matches the POC. Keeping `complete` a pass-through for `messages` means one retry/observability
path for all input shapes.

**Consequences:** Document bytes are token-heavy → **higher per-document cost and latency**
(tracked via cost.py). Per-request **page/size limits** exist — *verify against current
Anthropic docs*; multi-page/size guarding is **deferred** (Option A: send the whole document),
a documented known concern. Logging stays metadata-only and must **never** include document
bytes, base64, message content, or response text (tested). Deterministic PDF text extraction
(LP-40) is repositioned as a **dev-only comparison tool**, not a pipeline step. Model strings
(`anthropic_model_classification` Haiku-class, `anthropic_model_extraction` Sonnet-class)
remain placeholders to verify.

---

## ADR-127: Classification reads the full document natively (Haiku), not pre-extracted text

- **Date:** 2026-06-11
- **Status:** Accepted
- **Revises:** ADR-120/121/122 (LP-38); follows ADR-126 (LP-37 revision)

**Context:** LP-38 originally classified from a pre-extracted **text** string. Following the
full-document AI decision (ADR-126), classification should read the actual document — text-
layer PDFs, scans, and photos alike — rather than depend on a separate OCR/text step.

**Decision:** `classify_document` changes signature from `(text: str)` to
`(content: bytes, media_type: str)`. It sends the **full document** to the Haiku-class model
as a document/image content block built with the LP-37 `build_document_message`. Supported
media types are `application/pdf`, `image/jpeg`, `image/png` (`image/jpg` normalized); an
empty or unsupported document short-circuits to `ClassificationResult.unknown(...)` **without
an API call**. Everything else is **unchanged** — the `ClassificationResult` shape, the
defensive JSON parser, the graceful-failure contract (any AI error / unparseable output →
`unknown`, never raises), the file-based prompt (still a starter), the Haiku model, and
metadata-only logging (now explicitly never logging document bytes/base64).

**Rationale:** Native reading is more capable and uniform than OCR-then-text and keeps the
Haiku/Sonnet split (cheap classify, capable extract). Reusing the LP-37 helper means one
verified content-block shape and one retry/logging path.

**Consequences:** Document bytes are token-heavy (cost tracked via cost.py); the per-request
page/size concern and the deferred multi-page/size guarding are inherited from ADR-126.
The typed result, defensive parsing, and graceful-failure contract are preserved (tests
adapted to bytes + media type). Extraction (LP-39) gets the same treatment next. The Haiku
model string remains a placeholder to verify.

---

## ADR-128: Extraction reads the full document natively (Sonnet), not pre-extracted text

- **Date:** 2026-06-11
- **Status:** Accepted
- **Revises:** ADR-123/124/125 (LP-39); follows ADR-126 (LP-37 revision) and ADR-127 (LP-38)

**Context:** LP-39 originally extracted from a pre-extracted **text** string. Following the
full-document AI decision (ADR-126) and the matching classification change (ADR-127),
extraction should read the actual document — text-layer PDFs, scans, and photos alike — with
no separate OCR/text step.

**Decision:** `extract_pay_stub` changes signature from `(text: str)` to
`(content: bytes, media_type: str)`. It sends the **full document** to the Sonnet-class model
as a document/image content block built with the LP-37 `build_document_message`. Supported
media types are `application/pdf`, `image/jpeg`, `image/png` (`image/jpg` normalized); an
empty or unsupported document short-circuits to `PayStubExtractionResult.failed(...)`
**without an API call**. Everything else is **unchanged** — the `PayStubExtraction` typed
schema, honest nulls / no hallucination, the tolerant currency/date coercion (a single bad
field → `None`, marking `PARTIAL`, not a whole-extraction failure), the defensive JSON parser,
the graceful-failure contract (any AI error / unparseable output → `failed`, never raises),
the file-based prompt (still a starter), the Sonnet model, and metadata-only logging (now
explicitly never logging document bytes/base64; it already never logged extracted values).

**Rationale:** Native reading is more capable and uniform than OCR-then-text; Sonnet is used
for accuracy because extraction feeds loan decisions. Reusing the LP-37 helper means one
verified content-block shape and one retry/logging path; the change mirrors ADR-127 for
consistency across the AI features.

**Consequences:** Document bytes are token-heavy (cost tracked via cost.py); the per-request
page/size concern and the deferred multi-page/size guarding are inherited from ADR-126. The
typed schema, honest nulls, tolerant coercion, and graceful-failure contract are preserved
(tests adapted to bytes + media type). Pay stub remains the only type in Phase 1; the schema
and prompt remain starters (Priya / POC). The Sonnet model string remains a placeholder to
verify.

---

## ADR-129: Deterministic PDF text extraction repositioned as a dev-only comparison tool

- **Date:** 2026-06-12
- **Status:** Accepted
- **Supersedes:** the original LP-40 plan (text extraction as a pipeline step)

**Context:** The original plan fed deterministic PDF text into classification/extraction. The
LP-37 revision (ADR-126) + LP-38/39 changes mean the pipeline now reads documents with AI
**directly** (full-document native reading). So a deterministic text step is no longer needed
in the pipeline — but the developer still wants to evaluate text-layer-vs-AI on real documents.

**Decision:** Build the deterministic PDF text-layer extractor (`app/services/pdf_utils.py`)
as a **dev-only comparison tool**, exposed through a production-gated endpoint (ADR-130), not
as a pipeline step. It extracts a PDF's embedded text layer (multi-page, no OCR) and returns
it for the developer to compare against the AI's reading, informing a possible future hybrid
(deterministic text for cheap/easy cases, AI for the rest). `has_text` is **informational**
(empty layer → likely a scan), **not** a routing signal — scans are the AI's job now.

**Rationale:** Keeping it dev-only avoids committing the pipeline to a path still under
evaluation, while preserving the option to promote the utility into a hybrid later. The
utility code is reusable as-is if the hybrid is adopted.

**Consequences:** No production dependency on text extraction; it never feeds the AI, updates
the `Document`, or routes to `NEEDS_REVIEW`. OCR/scanned handling stays the AI's job. Whether
to adopt a hybrid is an open question this tool informs.

---

## ADR-130: Dev-gated endpoints — present only in non-production

- **Date:** 2026-06-12
- **Status:** Accepted

**Context:** Experiment/diagnostic affordances (like the text-layer comparison endpoint)
shouldn't exist in production, but still touch real, tenant-scoped data.

**Decision:** Development endpoints live on a dedicated dev router (`app/api/dev.py`) that is
included in `main.py` **only when `not settings.is_production`**. In production the router is
not mounted, so its routes are absent (404). Dev endpoints remain **auth'd** (`CurrentUser`)
and **tenant-scoped** (`get_document_for_company`) — touching real documents is no excuse to
skip isolation; `company_id` still comes from the user, never the request.

**Rationale:** Router-level gating is simple and absolute — there is no production code path to
the route, not merely a flag check inside it. Keeping auth + tenant scoping on dev tools means
they can't become a tenant-isolation bypass even while they exist in dev.

**Consequences:** The text-layer endpoint (and future dev tools) are non-prod only; a dev-only
UI button (LP-43) will call it. Production gating is verified by a test that applies the same
mount condition with `is_production` forced true and asserts the route is absent / 404s.

---

## ADR-131: PDF library — PyMuPDF for deterministic text extraction

- **Date:** 2026-06-12
- **Status:** Accepted

**Decision:** Use **PyMuPDF** (`pymupdf` / fitz) for the deterministic PDF text-layer
extractor, wrapped behind `app/services/pdf_utils.py` so the rest of the app never imports it
directly.

**Rationale:** PyMuPDF is fast, robust, reads from an in-memory byte stream
(`open(stream=..., filetype="pdf")`), exposes `page_count` / `needs_pass` for graceful
handling of encrypted files, and extracts per-page text simply (`page.get_text()`). A single
dependency covers our needs; test PDFs are generated with the same library, so no extra
fixture/`reportlab` dependency is needed.

**Consequences:** PyMuPDF ships incomplete type hints, so a few narrowly-scoped, documented
`# type: ignore[no-untyped-call]` comments are needed under mypy strict; its SWIG bindings emit
harmless `DeprecationWarning`s that are filtered in pytest config. Richer layout/table
extraction (and any OCR) can be added behind the same utility later if a hybrid is adopted.

---

## ADR-132: Celery + Redis for background document processing

- **Date:** 2026-06-12
- **Status:** Accepted

**Context:** Document processing — read the bytes, classify (Haiku), extract (Sonnet) — is
far too slow to run inside the upload HTTP request (multiple seconds, two AI calls). It must
run asynchronously so upload returns quickly and the UI polls for status. Redis was already
provisioned for this (LP-2).

**Decision:** Use **Celery** with a **Redis** broker and result backend (from settings,
defaulting to the existing `REDIS_URL` — not duplicated). The worker is a **separate process**
from the API, run locally (`celery -A app.tasks.celery_app worker`) and as a Compose `worker`
service (behind a profile so the default `docker compose up` stays infra-only). Serialization
is **JSON only** (`accept_content=["json"]`, no pickle), times are UTC, and the Celery app
object is import-safe (no live broker needed to create it). LP-41 is infrastructure only; the
real tasks are LP-42.

**Rationale:** Offloading slow work to a worker keeps the request fast. Redis is already
running and is a standard, simple Celery broker. JSON/no-pickle removes a remote-code-execution
vector. Import-safety lets the API process and the test suite import the app without Redis.

**Consequences:** A worker process must run alongside the API (documented; Compose profile +
local command). LP-42 adds the document-processing tasks and enqueues them from upload. Task
**status is tracked via `Document.status`** (the DB is the source of truth); Celery's result
backend is available but secondary. Flower/Beat (monitoring/periodic) are not set up yet.

---

## ADR-133: Sync Celery tasks run async code via a per-task event loop

- **Date:** 2026-06-12
- **Status:** Accepted

**Context:** Celery tasks are traditionally **sync**, but this codebase is **async**
throughout (async SQLAlchemy, the async AI wrapper, async storage). LP-42's tasks must call
that async code from within a sync worker.

**Decision:** A task base (`app/tasks/base.py`) bridges the two. `run_async(coro)` runs a
coroutine to completion with `asyncio.run` — **a fresh event loop per task**. `task_session()`
yields an async SQLAlchemy session from a **fresh engine created inside that per-task loop**
with `NullPool`; the app's module-level `engine` is bound to the loop that first used it, so
reusing it across per-task loops would raise "attached to a different loop" (asyncpg
connections are loop-bound) — a per-task engine sidesteps that and is disposed when the task
finishes. The `db_ping` validation task runs a real async `SELECT 1` to prove the bridge.

**Rationale:** A per-task event loop is the simplest **correct** bridge for V1 — no shared
mutable loop/engine state across tasks, no cross-loop connection reuse. Proving it with
`db_ping` (not assuming it) catches lifecycle mistakes early.

**Consequences:** A new event loop and new DB connections per task — acceptable at V1 volume;
**revisit loop/pool reuse** if task throughput grows (a documented caveat). Tasks must do their
async work inside a `run_async`-driven coroutine and use `task_session()` (not the API's
request-scoped `get_db`). `asyncio.run` can't be called from an already-running loop, so tasks
stay sync at the Celery boundary.

---

## ADR-134: Documents tab — live status via poll-while-non-terminal

- **Date:** 2026-06-12
- **Status:** Accepted

**Context:** Document processing (LP-42) runs in the background and changes `Document.status`
over seconds (PENDING → … → COMPLETED / NEEDS_REVIEW / FAILED). The Documents tab (LP-43)
must reflect that progress without a manual refresh, but shouldn't poll forever.

**Decision:** `useLoanFileDocuments` uses a **function `refetchInterval`** that returns
~2500ms while *any* document is in a non-terminal status (`hasInProgressDocuments`) and
`false` once every document is terminal. After a successful upload the documents query is
invalidated so the new PENDING docs appear and polling resumes. `Document.status` (set by the
LP-42 pipeline) is the source of truth — not Celery's result backend; no websockets in V1.

**Rationale:** Polling gives near-real-time progress with trivial infrastructure; stopping
when settled avoids hammering the server indefinitely. A function `refetchInterval` keyed on
the data is the idiomatic TanStack Query way to express "poll until settled".

**Consequences:** The UI is live during processing and quiet once done. The terminal-vs-
in-progress rule lives in one helper (`isTerminalStatus`/`hasInProgressDocuments`), unit-
tested and reused by the spinner treatment. (Note: until LP-42 lands, documents stay PENDING,
so the list polls without settling — the logic is correct; it just has nothing to advance.)

---

## ADR-135: Documents grouped by category; NEEDS_REVIEW surfaced honestly; override deferred to LP-44

- **Date:** 2026-06-12
- **Status:** Accepted

**Context:** A file accumulates many documents of different kinds; the processor thinks in
terms of categories. The AI classification is probabilistic and sometimes uncertain
(low-confidence / unknown / failed extraction → `NEEDS_REVIEW`).

**Decision:** Documents are displayed **grouped by their (AI-assigned) category** — the eight
`DocumentCategory` values in a sensible order, plus a "Processing / uncategorized" group for
not-yet-classified docs. `NEEDS_REVIEW` renders as an **amber attention state** ("the AI
wasn't sure — look at this"); `FAILED` as red. The ability to **correct** the type/category is
a distinct next step (**LP-44**); LP-43 only *displays* the state.

**Rationale:** Category grouping matches the processor's mental model. Honestly surfacing AI
uncertainty (rather than hiding it behind a confident-looking guess) is core to the
AI-in-the-loop design. Separating display (LP-43) from correction (LP-44) keeps each ticket
focused.

**Consequences:** V1 shows the needs-review state without the correction action. Category
reflects the AI's classification (the provisional map, LP-42). The status→treatment map is a
single source (`DOCUMENT_STATUS_META`, design tokens), mirroring the LP-31 loan-file pattern.

---

## ADR-136: Dev-only text-layer comparison button (non-production)

- **Date:** 2026-06-12
- **Status:** Accepted

**Context:** The LP-40 deterministic PDF text-layer endpoint is a dev-only comparison tool
(ADR-129), present only in non-production. The drawer is the natural place to surface it.

**Decision:** The document drawer renders a small **"Extract text layer (dev)"** button
**only in non-production** (`process.env.NODE_ENV !== "production"`, which Next.js inlines and
dead-code-eliminates from a production build), calling the LP-40 dev endpoint and showing the
returned text (+ has_text / page_count) for comparison against the AI extraction. In
production the button is absent and the endpoint 404s anyway — defence in depth.

**Rationale:** Lets the developer compare deterministic text-layer output against the AI's
reading on real documents, informing the possible future hybrid (ADR-129), while never
shipping the affordance to production.

**Consequences:** A dev affordance only; gated client-side to match the server gating. The
shown text is dev-only and never logged.

---

## ADR-137: Document processing pipeline — classification routes extraction; status drives the UI

- **Date:** 2026-06-12
- **Status:** Accepted

**Context:** Extraction is type-specific (LP-39), so the document type must be known first;
and document processing (read + up to two AI calls) is too slow for the upload request.

**Decision:** An async Celery task (`documents.process_document`) chains, per document:
read bytes → **classify** (Haiku) → **route by type** → **extract if pay stub** (Sonnet) →
persist a **versioned `Extraction`** (with token usage + `estimate_cost`) → satisfy a
matching need → log activity → set a terminal status. **Classification routes extraction**:
the type selects the extractor; Phase 1 has only the pay-stub branch, and every other type is
**classified-only** (no extraction). The task transitions and **commits `Document.status`** at
each stage (`PENDING → CLASSIFYING → CLASSIFIED → [EXTRACTING] → terminal`), which is the
source of truth the UI polls (LP-43). It runs via the LP-41 sync→async bridge + worker
session, and is enqueued from the upload endpoint (fire-and-forget, after commit).

**Rationale:** Type-specific extraction requires the type first (hence separate classify +
extract calls). Background processing keeps upload fast; committed status transitions give the
UI real-time progress. Versioned extraction + cost tracking reuse LP-16/LP-37.

**Consequences:** Phase 2 fans the routing out to more types; non-pay-stub types classify-only
in V1. Cost/tokens are recorded per extraction (`PayStubExtractionResult` was minimally
extended to surface usage). Status is DB-driven, not Celery's result backend.

---

## ADR-138: Per-document resilience — every document reaches a terminal status; failures isolated

- **Date:** 2026-06-12
- **Status:** Accepted

**Context:** Real uploads are messy (scans, corrupt PDFs, ambiguous content, transient infra
errors). A batch must process the good documents and flag the bad ones, never crash, and never
leave a document stuck mid-pipeline.

**Decision:** Each document is processed independently. **Graceful** classify/extract results
(`unknown` / `failed`) and low confidence (< 0.5) → **`NEEDS_REVIEW`** (an *expected* outcome,
the human-review signal). Any **unexpected** exception (storage/DB/etc.) → **`FAILED`** with a
*safe* `processing_error` (e.g. `"processing error"` — never raw document content). One
document's failure never crashes the worker or affects others, and **every handled path
reaches a terminal status** (COMPLETED / NEEDS_REVIEW / FAILED) — never left in
CLASSIFYING/EXTRACTING. The FAILED path sets the status on the loaded document and commits;
only if that fails (a broken transaction) does it roll back, re-load, and retry once, logging
and giving up if even that can't complete.

**Rationale:** Separating *expected* AI uncertainty (review) from *unexpected* errors (failed)
gives the processor an accurate signal. Reaching a terminal status keeps the polling UI honest
(it settles). Isolation means a batch upload is robust to one bad file.

**Consequences:** `processing_error` holds only safe messages. A document interrupted mid-task
(worker killed) may sit in a transient state until **reprocessed** — the V1 recovery path;
re-processing is safe (ADR-137: versioned extraction; needs not double-satisfied).

---

## ADR-139: Provisional type→category map and pay-stub needs-matching (refine with Priya / Phase 2)

- **Date:** 2026-06-12
- **Status:** Accepted

**Context:** Closing the document→needs loop (a pay stub satisfies an income need) is valuable
now, but the full type taxonomy and the needs model firm up with domain input (Priya) and
Phase 2.

**Decision:** A simple, clearly-marked **PROVISIONAL** document-type → `DocumentCategory` map
(e.g. `pay_stub`/`w2`/… → `INCOME_EMPLOYMENT`, `bank_statement` → `ASSETS`, …; unknown → no
category), and a simple **PROVISIONAL** needs rule: a processed pay stub marks the first
`OUTSTANDING` `INCOME_EMPLOYMENT` need on the file `RECEIVED` (+ `satisfied_by_document_id`,
`satisfied_at`) and logs a `NEEDS_ITEM_SATISFIED` activity. Only `OUTSTANDING` needs are
touched (no double-satisfy). No match → no-op.

**Rationale:** Demonstrates the end-to-end loop for the common pay-stub case without
over-engineering; the real taxonomy/matching is a domain decision deferred to Priya / Phase 2.

**Consequences:** V1 matching is basic (one income need per pay stub, by category); both the
map and the rule are documented as provisional and will be refined. The category shown in the
UI reflects this provisional map.

---

# Phase 3 Verification — design decisions (recorded in advance)

ADR-140…144 were settled during Phase 1 (Epic 5) while shaping document
extraction, and define how the **Phase 3 verification engine** will behave.
Recorded now so they are settled, not re-litigated later. They are **forward-
looking**: the extraction-shape foundation they depend on (per-field page +
snippet; typed core + grouped catch-all — ADR-144) is **not yet implemented** —
the current LP-39 `PayStubExtraction` is flat typed fields only. That shape is
built in **LP-39a** (pay stub), then replicated for W-2 (LP-39b) and bank
statement (LP-39c).

---

## ADR-140: Two-layer verification — AI surfaces facts/discrepancies, deterministic code judges thresholds

- **Date:** 2026-06-12
- **Status:** Accepted (Phase 3 design, recorded in advance)

**Context:** Verification has two distinct kinds of work, suited to different tools: reading
documents and spotting cross-source discrepancies (open-ended, including ones nobody
pre-enumerated), versus applying a finite set of regulatory thresholds (DTI, LTV, recency,
loan limits, overlays from Fannie/FHA/lender guidelines).

**Decision:** Split verification into two layers with a **structured handoff** (never prose):

  * **AI (perception/annotation)** — reads documents, extracts structured values, and performs
    **open-ended cross-source discrepancy detection** as a *single general capability* (NOT a
    method-per-finding). It emits **structured findings** (typed fields: type, amount,
    source_doc, page, snippet, confidence, reasoning), catching known *and* novel discrepancies
    (e.g. an undisclosed support obligation in a divorce decree) because it reads and compares
    rather than executing pre-written checks.
  * **Deterministic Python (judgment)** — a finite, enumerable set of regulatory rules, **one
    function per rule**, consuming **structured data** (extracted values + human-confirmed
    AI-surfaced corrections) and emitting auditable pass/fail findings against thresholds.

The AI writes typed records; deterministic rules read typed fields. **There is no step where
Python interprets AI prose.** AI fallibility (a missed or false flag) is **acceptable by
design** because findings are surfaced for the **processor to resolve, not used as the final
decision** — the same human-in-the-loop principle as document classification; threshold
decisions remain deterministic and auditable.

**Rationale:** Auditability (threshold calls are defensible to underwriters/regulators);
consistency (rules give the same answer every run); regulatory faithfulness (guidelines *are*
rules — encode them as rules); scalability (open-ended detection is ONE AI capability, not N
hand-written methods, so it catches discrepancies nobody pre-enumerated). You cannot write a
Python method to catch a discrepancy you didn't foresee — open-ended detection MUST be AI;
"method per rule" applies only to the finite, specified regulatory rules.

**Consequences:** The handoff is always structured data. Phase 3 builds the deterministic rule
set incrementally; the AI cross-source layer is one capability over the full extracted material
(hence ADR-144's catch-all). A human confirms AI corrections before they feed the deterministic
recompute.

---

## ADR-141: Findings are blocking — APPLIED or OVERRIDDEN, nothing silently ignored

- **Date:** 2026-06-12
- **Status:** Accepted (Phase 3 design, recorded in advance)

**Context:** Surfacing discrepancies is only useful if they can't be quietly dropped before
submission.

**Decision:** Every in-scope finding MUST be resolved before a file can be "ready to submit":

  * **APPLIED** — incorporated into the file/numbers (e.g. an $800 decree obligation added to
    liabilities, which feeds the deterministic DTI recompute), or
  * **OVERRIDDEN** — explicitly dismissed by the processor **with a recorded reason**.

No finding may be silently ignored; **OPEN findings block submission**. While any in-scope
finding is OPEN, affected calculations (DTI/LTV, …) display an **alert** ("findings unresolved
— this calculation may be incomplete"); the calculator queries open in-scope findings for the
file.

**Rationale:** A blocking, reason-required resolution makes the file's integrity auditable —
every surfaced concern was either incorporated or explicitly judged not to matter, by a named
processor. Alerting affected calculations prevents trusting a DTI/LTV that an unresolved
finding might change.

**Consequences:** Submission gating depends on the open-findings query (scoped by ADR-142's
threshold). Resolution state (APPLIED/OVERRIDDEN + reason + actor) is recorded. "Resolve all
findings" means "resolve all findings at the chosen thoroughness" (ADR-142).

---

## ADR-142: Aggression dial is a confidence threshold gating BOTH display and blocking

- **Date:** 2026-06-12
- **Status:** Accepted (Phase 3 design, recorded in advance)

**Context:** Open-ended detection produces findings of varying confidence; processors want to
tune thoroughness without paying to re-run the AI.

**Decision:** The AI cross-source layer **detects and stores ALL findings, each with a
confidence**. A per-file **aggression** setting (user-level default, per-file override) sets a
confidence **cutoff applied at read time**: Conservative → high threshold (only high-confidence);
Balanced (default) → medium; Thorough → low (almost everything, incl. low-confidence hunches).
**Decision (2a.i): the threshold gates BOTH display AND blocking** — a finding below the active
cutoff is neither shown nor blocking; one at/above is shown AND must be resolved. The **active
aggression level at submission is recorded on the file** (auditable: what threshold was in
effect when submitted).

**Rationale:** Storing everything with confidence and filtering at read time means changing the
dial **re-filters instantly — no AI re-run, no new cost**. Gating display and blocking together
keeps "resolve all findings" coherent at the chosen thoroughness. Recording the level makes the
submission defensible.

**Consequences:** Detection persists all findings + confidence; display/blocking is a filtered
view. A more thorough setting surfaces (and requires resolving) more findings. The submitted
file carries the threshold in effect.

---

## ADR-143: Cross-source verification runs on-demand with a staleness flag (V1)

- **Date:** 2026-06-12
- **Status:** Accepted (Phase 3 design, recorded in advance)

**Context:** Cross-source verification is heavy and needs multiple documents present together
(the divorce-decree case requires the decree AND the stated liabilities), so it shouldn't fire
piecemeal per upload.

**Decision:** When any document changes (upload, type override, re-extraction), verification is
marked **STALE** ("documents changed — verification out of date"). The processor **manually
triggers** the heavy cross-source pass, so the comparison fires when the full material is
present. **V1 is manual-trigger + staleness indication**; later phases automate verification on
document change.

**Rationale:** Manual trigger avoids redundant expensive passes on incomplete material and lets
the processor decide when the file is ready to verify; the staleness flag keeps them honest
about whether the current findings reflect the current documents.

**Consequences:** A `stale` indicator on the file's verification state; a processor-initiated
run. Automation is deferred.

---

## ADR-144: Extraction shape — typed core + grouped catch-all, with per-field source location

- **Date:** 2026-06-12
- **Status:** Accepted (Phase 3 design) — **implemented for the pay stub in LP-39a (ADR-145)**

**Context:** Deterministic rules need typed fields to consume, but the AI cross-source layer
(ADR-140) needs the *full* document material to catch discrepancies nobody pre-enumerated — and
processors use all fields, not just the decision-driving ones. Trust requires showing *where* a
value came from.

**Decision:** Extraction captures **everything** on a document while keeping decision-driving
fields **typed**:

  * **Typed core** — the mortgage-decision-relevant fields, named and typed (e.g. pay stub
    `gross_pay: Decimal`, `pay_period_end: date`). Defined by what the verification **rules**
    consume; grows in Phase 3 as rules need fields (promoted from the catch-all). NOT a generic
    field bag.
  * **Grouped catch-all** — everything else, captured as sections → `{label, value, page,
    snippet}`. Nothing is lost; the processor sees the full document; the AI cross-source layer
    has the full material (the catch-all is what makes the divorce-decree obligation catchable
    even when it isn't in the typed core).

**Per-field source location** — every extracted field (typed and catch-all) carries **where it
was read from**: a **page number** and a **verbatim snippet**, so a processor can click a
finding and see the exact supporting line (the trust/audit mechanism). Visual bounding-box
highlighting is deferred; **page + snippet is the V1 form**.

**Rationale:** Typed core keeps deterministic rules consuming clean fields; the catch-all keeps
the material complete for open-ended AI detection and for the processor; page+snippet makes
findings traceable to the source. This is the foundation ADR-140/141/142 depend on.

**Consequences:** Built for the pay stub in **LP-39a** (ADR-145) — `PayStubExtraction` is now a
typed core (`TypedField` with source) + grouped catch-all. Then replicated for
then replicated for **W-2 (LP-39b)** and **bank statement (LP-39c)**. The typed core grows in
Phase 3 by promoting catch-all fields as rules require them. Until LP-39a lands, the verification
engine's foundation is incomplete.

---

## ADR-145: Pay-stub extraction realizes the typed-core + grouped-catch-all + source shape (LP-39a)

- **Date:** 2026-06-12
- **Status:** Accepted — **implements ADR-144**

**Context:** ADR-144 settled the extraction shape (typed core + grouped catch-all + per-field
source) as a Phase 3 foundation, recorded in advance. LP-39a builds it concretely on the pay
stub — the shape W-2 (LP-39b) and bank statement (LP-39c) reuse.

**Decision:** Reusable shape types live in `app/ai/extraction/shape.py`:

  * `SourceLocation { page: int | None, snippet: str | None }`,
  * `TypedField[T] { value: T | None, source: SourceLocation | None }` (PEP 695 generic; a
    present-but-uncoercible value → ``value=None`` but ``source`` is kept),
  * `CatchAllField { label, value: str | None, source }` and
    `CatchAllSection { section, fields: [...] }`.

`PayStubExtraction` is reshaped to a **typed core** (each of the 11 decision fields a
`TypedField` with source) + **`additional_sections: list[CatchAllSection]`** (everything else,
by section). The result wrapper (`data/status/confidence/reasoning` + `.failed()`) and its
behaviour are unchanged: full-document Sonnet reading, honest nulls, **tolerant coercion**
(typed core only; catch-all values stay strings), defensive parsing, graceful failure (never
raises), metadata-only logging (now counts: `core_fields_present`, `catch_all_sections`). The
model returns a documented JSON contract (`typed_core` + `additional_sections`); the parser is
tolerant (fences/prose, a flat fallback, bad sections/fields skipped). The richer JSON is
stored unchanged in mechanism via `create_extraction_version` (LP-42); the LP-43 drawer shows
the typed core + collapsible catch-all sections + a click-to-source affordance (page + snippet).

**Rationale:** Realizes ADR-144 on a real type so the deterministic engine has typed fields,
the AI cross-source layer has the full material, and findings are traceable to source — while
preserving every LP-39 guarantee.

**Consequences:** Status is derived from the **typed core** (catch-all doesn't affect it). The
typed core is a V1 starter that grows in Phase 3 (promote catch-all fields as rules need them).
The prompt + field set remain starters (Priya / POC). `_MAX_TOKENS` raised (4096) for the
richer output. Reused as-is by LP-39b/LP-39c.

---

## ADR-146: W-2 extraction on the typed-core + grouped-catch-all shape (LP-39b)

- **Date:** 2026-06-12
- **Status:** Accepted

**Context:** LP-39a established the extraction shape on the pay stub. The W-2 is the first
replication — and a deliberately different case: a fixed federal form whose decision fields are
**annual** figures (not the pay stub's period figures), proving the shape generalizes to a
different typed core (what Phase 2's ~100-type fan-out needs).

**Decision:** `extract_w2(content, media_type)` mirrors `extract_pay_stub` and reuses the
LP-39a shape (`shape.py`) and the shared parser (`app/ai/extraction/parsing.py`, refactored out
of the pay stub so there's no duplication — field coercers, the typed-core loop, catch-all
pass-through, status rule). The **W-2 typed core** = `tax_year` (int) + employee/employer
identity (`employee_name`, `employee_ssn`, `employer_name`, `employer_ein`) + the federal
wage/withholding boxes 1-6 (`Decimal`) — the fields feeding income verification and cross-source
identity/employer checks. **Everything else** (state/local Boxes 15-20, Box 12 codes, Box 13
checkboxes, Box 14, control number, addresses) → the grouped catch-all. Every field carries
page + snippet. All LP-39a behaviours are kept (full-document Sonnet reading, honest nulls,
tolerant coercion, defensive parsing, graceful failure, metadata-only logging). The LP-43
drawer renders W-2s with the same generic typed-core + catch-all + source view.

**Rationale:** Proves "different typed core, same shape." The W-2's standardized boxes map
cleanly to a typed core; the catch-all captures the full form for the Phase 3 cross-source
layer. Refactoring the shared parser keeps the two (soon three) type modules DRY.

**Consequences:** The typed core is a V1 starter that grows in Phase 3. `tax_year` is an int
(new `coerce_int` helper); the boxes are `Decimal`; names/SSN/EIN are strings. **Not yet wired
into the LP-42 pipeline** — routing the fan-out to all three types is LP-39c. Bank statement
(LP-39c) reuses the same shape + shared parser.

---

## ADR-147: W-2 SSN — extracted for the identity cross-check, masked in display, never logged

- **Date:** 2026-06-12
- **Status:** Accepted

**Context:** A W-2 contains the employee SSN. The Phase 3 identity cross-source check wants to
compare the W-2 SSN against the borrower SSN — but a full SSN must never be logged or shown in
full (the existing borrower `masked_ssn` discipline, LP-29/ADR-097).

**Decision:** **Extract** `employee_ssn` into the W-2 typed core (so the cross-check can compare
actual values), but treat it as **sensitive**: it is **never logged** (the metadata-only logging
records only status/confidence/counts — never values, and the test asserts the SSN value is
absent from logs), and it is **displayed masked** (last-4, e.g. `•••-••-6789`) in the LP-43
drawer via a `maskSsn` helper, consistent with the borrower `masked_ssn` discipline. The raw
value lives only in the tenant-scoped, access-controlled extraction JSON.

**Rationale:** The identity cross-check needs the value; masking-in-display + never-logging
keeps a full SSN from ever appearing in logs or the UI. (Alternative considered: not extracting
the SSN at all and relying on the borrower model — rejected, so the cross-check can compare the
W-2's actual SSN.)

**Consequences:** A frontend `maskSsn` helper + a `MASKED_FIELD_KEYS` set (currently
`employee_ssn`) the drawer masks. The no-values logging rule explicitly covers the SSN. Flagged
for the user to confirm the extract-but-mask choice over not-extracting.

---

## ADR-148: Bank statement extraction — typed core + typed transactions list (ADR-061) + grouped catch-all

- **Date:** 2026-06-12
- **Status:** Accepted

**Context:** The bank statement is the hardest of the three Phase 1 types: its decision-relevant
content is a **list of transactions** (often dozens, across multiple pages) plus balances, not
a flat field set. ADR-061 settled that transactions live in the extraction JSON as a nested
structure; this implements it.

**Decision:** `extract_bank_statement` reuses the LP-39a shape, extended with a **first-class
typed transactions list**: `BankStatementExtraction` = a typed core (account/balance fields,
each a `TypedField` with source) + `transactions: list[Transaction]` (each `{date, description,
amount, transaction_type, running_balance, source}`, money→`Decimal`/date→`date`) +
`additional_sections` (catch-all). Capture **all** transactions across **all** pages (Option A,
whole document). **Never hallucinate a transaction** — unreadable → skip/null (a fabricated
transaction corrupts asset/deposit analysis); the parser drops fully-empty rows and nulls bad
fields while keeping the row. `max_tokens` is generous (8192) for long lists, and a
**truncated/malformed** response fails gracefully (`.failed()`), never crashing. Status counts
transactions as content (a statement may be mostly its list).

**Rationale:** Transactions must be **structured** for the Phase 3 verification/cross-source
layer (deposits, ending balance, fees), not loose catch-all. Honest extraction (no invented
rows) is critical because the figures feed asset/reserve analysis.

**Consequences:** The multi-page/token concern (LP-37 revision) is most acute here — generous
cap + graceful truncation handling. Transaction **analysis** (large-deposit flags, NSF,
sourcing) is Phase 3, not here. The typed core grows in Phase 3. Completes the Phase 1
extraction set (pay stub + W-2 + bank statement).

---

## ADR-149: Type→extractor dispatch registry (pipeline fan-out to all types)

- **Date:** 2026-06-12
- **Status:** Accepted — supersedes LP-42's single-branch routing

**Context:** LP-42 routed extraction with `if document_type == "pay_stub"`. With three types
(and ~100 in Phase 2) that single branch doesn't scale.

**Decision:** A registry `EXTRACTORS: dict[str, Extractor]` (`app/ai/extraction/__init__.py`)
maps `document_type` → its async extractor (`pay_stub` / `w2` / `bank_statement`). The pipeline
(`_process_document`) and the reprocess core (`reprocess_document_extraction`, the reusable
function LP-44's override calls) both route via `EXTRACTORS.get(...)`: present → run it +
`create_extraction_version(result.data.model_dump(mode="json"), ...)` + terminal status;
absent → classified-only. The result types share a structural `ExtractionResult` Protocol
(`data` with `model_dump`, `status`, `confidence`, `reasoning`, token usage) so any extraction
is stored uniformly. Adding a Phase 2 type = write an extractor + register it.

**Rationale:** The type-routed design always meant to fan out; a registry is the clean,
scalable form. A shared result Protocol lets the pipeline stay type-agnostic.

**Consequences:** One place to register extractors. All LP-42 resilience/retry-safety + the
needs/activity behavior are preserved (the needs rule generalized: a document satisfies an
OUTSTANDING need in **its** category — income for pay stub/W-2, assets for bank statement).
The account-number/SSN masking patterns travel with their types. The LP-44 override **endpoint/
UI** is not built here — only the reprocess core that uses the registry.

---

## ADR-150: Bank account number — captured masked, never logged, displayed masked

- **Date:** 2026-06-12
- **Status:** Accepted

**Decision:** `account_number_masked` follows the LP-39b SSN pattern (ADR-147): captured as
printed (usually already masked), **never logged** (metadata-only logging records status /
confidence / counts — never values, transactions, or the account number; tested), and
**displayed masked** to last-4 (`maskLast4`, generalizing `maskSsn`) in the LP-43 drawer. The
raw value lives only in the tenant-scoped extraction JSON.

**Rationale:** Same as the SSN: downstream may need the value, but a full account number must
never appear in logs or the UI.

**Consequences:** `MASKED_FIELD_KEYS` (frontend) now covers `employee_ssn` + `account_number_masked`;
the masking pattern is reusable for future sensitive fields.

---

## ADR-151: Manual type override — PATCH that reuses the LP-39c re-extraction core

- **Date:** 2026-06-12
- **Status:** Accepted

**Decision:** The human-correction half of human-in-the-loop is a single **`PATCH
/api/v1/documents/{id}`** endpoint (`document_type`). It is tenant-scoped via
`get_document_for_company` (out-of-company → `404`, anti-enumeration), sets the new type,
**re-derives** the category from the existing type→category map (`category_for_type`, factored
out of `_process_document`), marks the classification **human-overridden**
(`classification_confidence = 1.0`), clears any stale `processing_error`, logs a
**`DOCUMENT_TYPE_OVERRIDDEN`** activity, commits, then **fire-and-forget enqueues the existing
LP-39c re-extraction** (`reprocess_document.delay`). A thin Celery task wrapper
(`reprocess_document` → `reprocess_document_extraction(db, document)`) was added; the **core was
reused unchanged** — registry-based, skips classification, new version, resilient.

**Rationale:** LP-39c deliberately built the reprocess core ahead of this ticket ("the function
LP-44's override calls"). Reusing it keeps a single re-extraction path (no duplicated
classification-skipping / resilience logic). Pinning confidence to `1.0` makes the human type
authoritative so the re-extraction isn't immediately re-flagged `NEEDS_REVIEW` for low
confidence. Re-deriving the category (not trusting a client-supplied one) keeps the type→category
mapping server-owned.

**Consequences:** Adding `DOCUMENT_TYPE_OVERRIDDEN` to the `ActivityType` VARCHAR+CHECK enum
required an Alembic constraint-swap migration (raw-SQL drop/add, per the LP-30 pattern, to avoid
naming-convention re-prefixing). The endpoint is PATCH (partial update of one field). Extractable
types (`pay_stub`/`w2`/`bank_statement`) re-extract; any other type relabels **classified-only**
(no API call) — surfaced in the drawer via `typeReExtracts`. Enqueue failure can't lose the
override (already committed); it's logged (`reprocess_enqueue_failed`, metadata-only) and the doc
can be reprocessed.

---

## ADR-152: Integration test strategy — real stack, mock only AI + Celery dispatch

- **Date:** 2026-06-12
- **Status:** Accepted

**Decision:** The API integration suite (LP-45, `backend/tests/integration/`) exercises the
**real stack**: real HTTP (httpx `AsyncClient` via `ASGITransport`), real DB (the session-scoped
`test_engine` + a commit-safe savepoint session), real auth (real JWTs), real
routing/DI/services/tenant-scoping, and real local storage (a temp dir). **Only** the AI
(`classify_document` / `extract_*`) and Celery dispatch (`.delay`) are mocked — they are
slow/costly/non-deterministic/external. An upload test asserts `.delay` was *called*; a pipeline
test calls the processing core directly with the AI mocked. Tenant isolation is verified
**systematically**: every enumerated company-scoped route is asserted `404` cross-company, and
lists are asserted not to leak. Target ~70% of `app/` overall with **complete** coverage of the
company-scoped routes.

**Rationale:** Integration tests catch the seam bugs unit tests mock away — an unscoped route, a
leaked field, a wrong status code. Multi-company data isolation is security-critical and must be
proven against a real request→DB→response path, route by route, not spot-checked. Reusing the
existing `test_engine` + savepoint pattern (rather than a parallel harness) keeps one DB story.

**Consequences:** A fast (~10s for the integration module), deterministic suite that needs no API
key and no broker. Reusable, composable fixtures (`client`, `auth_client`, `company_a`/`company_b`,
entity factories, AI/dispatch mocks) are the foundation for the rest of Epic 6 (LP-46/47). AI
behavior stays unit-tested in `tests/ai` + `tests/tasks`; the integration suite complements, not
replaces, the unit suites. CI already runs a Postgres service container, so the suite runs in CI
unchanged.

---

## ADR-153: Coverage must trace SQLAlchemy's greenlet context (`concurrency`)

- **Date:** 2026-06-12
- **Status:** Accepted

**Decision:** Configure `coverage` with `concurrency = ["greenlet", "thread"]` (in
`[tool.coverage.run]`), plus `source = ["app"]` and standard report excludes.

**Rationale:** SQLAlchemy's async engine runs DB work inside greenlet-spawned contexts
(`greenlet_spawn`). With the default thread-only tracer, coverage silently **drops every line
executed during async request handling** — route handlers and services ran (the integration tests
got real `200`/`201` responses) yet showed as *uncovered*, under-counting the API layer by ~20
points (e.g. `app/api/loan_files.py` measured 60% but is actually exercised end-to-end). This was
surfaced by LP-45 and is a *measurement* defect, not a test gap.

**Consequences:** Coverage now reflects what the suite actually exercises (API layer ~99–100% on
most routers; **93%** of `app/` overall). The fix is global (helps all existing endpoint tests
too). No product code changed — the bug was in how coverage was measured, exactly the kind of gap
the LP-45 coverage AC exists to expose.

---

## ADR-154: Consistent API error envelope + global exception handler (safe by default)

- **Date:** 2026-06-12
- **Status:** Accepted

**Decision:** Every API error returns one envelope —
`{"error": {"type": str, "message": str, "details"?: [{"field", "message"}]}}` — with the correct
status code (LP-46, `app/core/errors.py`). A global handler (`register_exception_handlers`) maps:
unhandled `Exception` → a SAFE generic 500 (`"An unexpected error occurred. Please try again."`),
`HTTPException` → the envelope with its (already-safe) detail and a `type` derived from the status,
and `RequestValidationError` → 422 with field-level `details`. The full detail of an unhandled
error is logged server-side as PII-safe **metadata only** (error type, request path/method) — never
the request body, an extracted value, an SSN, or a stack trace.

**Rationale:** A single shape lets the frontend handle every error uniformly (one normalizer, one
set of states). Safe messages protect internals (security — no stack trace / internal path / DB
text) and borrower data (privacy — no PII in responses or logs). A catch-all `Exception` handler
guarantees a raw 500 / framework HTML never reaches a client. The endpoint `detail` strings were
audited and are already safe, generic messages ("Loan file not found"), so passing them through
leaks nothing.

**Consequences:** The response shape changed from FastAPI's default `{"detail": ...}` to the
envelope (one auth test updated; the frontend reads `error.message` with a legacy `detail`
fallback). Validation messages describe the *constraint*, not the submitted value, so no input is
echoed. Debugging relies on server-side logs, not client responses. The envelope is the contract
the rest of Epic 6 (and the frontend error UX) builds on.

---

## ADR-155: Frontend error UX — axios normalization, error boundary, specific states + retry

- **Date:** 2026-06-12
- **Status:** Accepted

**Decision:** The frontend turns failures into clear, recoverable states (LP-46):

- **Normalization** (`lib/errors/api-error.ts`): `normalizeError()` maps any throw — axios error,
  network failure, stray `Error` — into one `{ kind, status, message, details }`, reading the
  LP-154 envelope (with a legacy `detail` fallback and a safe generic default). The UI never shows
  a raw status or stack.
- **Global 401 / session expiry**: the existing axios refresh-retry layer, on a truly-dead session,
  clears auth and redirects to `/login?...&reason=session_expired`; the login form shows a "your
  session expired" notice (a query param survives the navigation that a toast would not).
- **Error boundary** (`components/error-boundary.tsx`): a top-level class boundary (in `Providers`)
  plus one around the app-shell content — a render crash shows a friendly "Something went wrong" +
  Try again (remounts the subtree; clears the query cache on the top-level reset), **never a white
  screen**. The raw error/stack is console-only, never rendered.
- **Specific states + retry** (`components/ui/error-state.tsx`): a consistent inline error panel
  (and compact inline variant) with a Retry that re-runs the failed query — applied to the
  documents list, the document drawer's extraction, and the overview sections; the file-level 404
  state stays "doesn't exist or no access".
- **Consistent mutation feedback**: upload / override / delete / create surface success and a
  safe normalized failure message via sonner.

**Rationale:** Graceful, informative failure is core to a professional tool's trustworthiness — no
blank screens, no infinite spinners, no console-only errors. The user always sees a message and a
way forward. Mechanisms (normalizer, boundary, standard states) over a bespoke message per error;
a few high-value specifics (session expired, no access, network, processing failed).

**Consequences:** One error shape and a small set of reusable components handle errors app-wide;
transient failures recover via Retry without a full reload. Component tests required a jsdom + React
Testing Library setup (opt-in per file via a `// @vitest-environment jsdom` docblock; a vite React
plugin transforms `.tsx` tests). The mechanisms are reused by the rest of Epic 6.

---

## ADR-156: Loading states — skeletons for content, spinners for actions, coordinated four states

- **Date:** 2026-06-12
- **Status:** Accepted

**Decision:** A small set of reusable loading primitives applied app-wide (LP-47), driven entirely
by **consuming TanStack Query's** states (`isPending` for queries, `isPending` for mutations) — no
new loading machinery:

- **Content loads → shape-matching skeletons.** `Skeleton` (base, `aria-hidden`) plus
  `SkeletonText` (line blocks) and `SkeletonRows` (row stacks) in `components/ui/skeleton.tsx`. The
  skeleton occupies the same box as the content (matched dimensions: stat-card number, document
  rows `h-[58px]`, table per-column widths, header title/subtitle) so content arrival causes **no
  layout shift**.
- **Actions → button spinners that disable.** One `Spinner` (`components/ui/spinner.tsx`); every
  mutation button shows it + is `disabled` while `isPending`, which both signals work and
  **prevents double-submit** (login, create file, upload, override, delete, logout).
- **Navigation → route `loading.tsx`** shells for the dashboard and the file workspace (mirroring
  each page's layout) so a transition reads as progress, not a frozen click.
- **Four-state coordination.** Every async surface resolves to exactly one state at a time:
  **loading** (skeleton) → **content** | **empty** (friendly empty state) | **error** (LP-46 state
  + retry). No ambiguous blanks, no skeleton-then-blank.
- **Accessibility.** Loading regions carry `aria-busy` + a visually-hidden `<output>` (role=status)
  cue; the skeleton shapes are `aria-hidden`; disabled loading buttons convey state via their label.

**Rationale:** Clear loading states are core to perceived quality and trust — no blank-then-pop, no
frozen-looking screens, no accidental double-submits. Skeletons preserve layout and read faster
than spinners for content; the four-state coordination means the user is never staring at an
ambiguous blank. Consuming the query/mutation states (not inventing machinery) keeps it simple and
consistent.

**Consequences:** The reusable primitives replace the bespoke per-surface skeletons. The document
**processing** status (LP-43, status-driven polling — a different, longer wait) is left untouched: a
card may show a load skeleton (LP-47) and then a processing indicator (LP-43). Consistent with the
LP-46 error states (the shared four-state model). Component tests reuse the LP-46 jsdom + RTL setup.

---

## ADR-157: Dev-only idempotent seed script with pre-canned extractions and fake PII

- **Date:** 2026-06-12
- **Status:** Accepted

**Decision:** `backend/app/scripts/seed_dev_data.py` (run via
`uv run python -m app.scripts.seed_dev_data [--reset]`) seeds realistic demo data — one company,
an admin + a processor user, the UWM and Sun-West lenders, and **three loan files in various
workflow states** (fresh / mid / near-submission) with fake-PII borrowers, properties, loan
details, documents in various processing states (COMPLETED with extractions, COMPLETED
classified-only, and NEEDS_REVIEW — all terminal, so seeded files never poll without a worker),
needs, and activity. It is **idempotent** (check-and-skip by stable identifiers — company slug, user email,
lender slug; loan-file seeding skips if the company already has files), with a `--reset` that
**hard-clears** the seeded company (DB cascade + its local storage subtree) and recreates it.
**Dev-only**: a production guard refuses to run (exit 1, writes nothing) when
`settings.is_production`. Documents get **pre-canned** extractions inserted directly — **no AI
calls**: the extracted JSON is produced by building the real LP-39a Pydantic models
(`PayStubExtraction` / `W2Extraction` / `BankStatementExtraction`) and serializing with
`model_dump(mode="json")`, so the stored shape can't drift from a live run. All PII is **synthetic**
(never-issued `900-` SSNs written through the encrypted `EncryptedString` column; fake
names/addresses). A small valid placeholder PDF is stored per document so download works.

**Rationale:** A populated, realistic DB is required to demo the product (LP-49) and review it with
the domain expert (LP-50), and makes day-to-day development easier. Pre-canning extractions keeps
the seed fast, deterministic, and keyless; building them from the real models avoids hand-written
JSON drifting from the schema. Fake PII + a production guard + check-and-skip keep it safe to run
and re-run anywhere but production.

**Consequences:** The script needs occasional updates as the schema evolves (expected for a dev
utility). Known dev credentials (`admin@summit-demo.com` / `priya@summit-demo.com`, password
`DevPassword123!`) are dev-only and documented in the README. The earlier minimal seed
(`app.scripts.seed_dev`, company `demo`) is kept for a quick two-user setup; `seed_dev_data` is the
comprehensive demo seed. Emails use a real `.com` TLD because Pydantic `EmailStr` rejects reserved
`.test`/`.example` TLDs and the login endpoint must accept the seeded accounts.

---

## ADR-158: Documents live-poll has a backstop (stop polling a stuck document)

- **Date:** 2026-06-12
- **Status:** Accepted

**Decision:** The documents-list live poll (LP-43, `useLoanFileDocuments`) keeps a hard cap:
`documentsRefetchInterval(documents, fetchCount)` polls every 2.5s while any document is
non-terminal, but stops once **either** all documents are terminal **or** the fetch count exceeds a
backstop (`MAX_STATUS_POLLS` ≈ 40 fetches ≈ 100s). A page refresh resumes polling.

**Rationale:** A document only leaves a non-terminal state (`pending`/`classifying`/`extracting`)
when a Celery worker processes it. With no worker running — common in local dev and demos — a
document sits `PENDING` forever, and the unbounded poll hammered the endpoint indefinitely
(observed on a seeded/uploaded doc with no worker). Normal processing settles in a few polls, far
under the cap, so live updates are unchanged; the backstop only bounds the pathological "stuck doc"
case.

**Consequences:** Worst case, a genuinely stuck document stops auto-refreshing after ~100s (the
documents stay visible — only the background refresh stops; refresh to resume). The function is
extracted and unit-tested. Separately, the LP-48 seed was adjusted so its documents are all in
**terminal** states (no perpetually-`PENDING` seeded doc), so seeded files don't rely on the
backstop at all.

---

## ADR-159: Deterministic MISMO parsing (lxml/XPath) — typed core + catch-all, tolerant + exact

- **Date:** 2026-06-12
- **Status:** Accepted

**Decision:** MISMO 3.4 application files are parsed **deterministically** with lxml/XPath
(`app/mismo/parser.py` → `parse_mismo(content) -> ParsedMismo`), not by AI. The result is a
**typed core** (borrowers — name/DOB/SSN/contact/address/income/employers/1003 declarations; loan;
property; liabilities; assets — the stated data needed for file creation and Phase-3 verification)
plus a **catch-all** of every other leaf in the deal, grouped by section, so nothing is lost.
Values are read **exactly** (`Decimal` for money/rates, `date` for dates, SSN verbatim). The parser
is **tolerant**: a missing/optional element becomes `None`/`[]` with a `parse_warning` for
needed-now fields, never a crash. It accepts raw XML **and** HTML-wrapped XML (the embedded
`<MESSAGE>…</MESSAGE>` island is sliced out first; `source_format` records which). Validation
failures (not XML / not MISMO / no DEAL) raise `MismoParseError` with a safe message; missing data
yields a partial parse + warnings rather than failing. **AI-fallback** for non-compliant files is a
documented **future** option, not built.

**Rationale:** MISMO is a standardized, machine-parseable schema and the sister's LOS emits
compliant MISMO, so deterministic parsing is exact, free, fast, and auditable. The stated financial
data is the source-of-truth baseline (the *stated* side of stated-vs-verified) and must be read
exactly — an AI misread of stated income/amounts would corrupt that baseline. The typed-core +
catch-all shape mirrors document extraction (LP-39a) and guarantees no field is dropped. lxml is
configured XXE-safe (`resolve_entities=False`, `no_network=True`).

**Consequences:** The catch-all tracks which leaves the typed core consumed (via stable element
paths) so it captures exactly "everything else" — and the **SSN is consumed**, so it never lands in
the catch-all. Logging is **metadata-only** (counts, source format, warning count) — never the SSN,
names, amounts, or raw content. The next ticket consumes `ParsedMismo` to map to DB models, encrypt
the SSN, and create a loan file. A real sample
(`backend/tests/fixtures/mismo/MISMO16940192.xml`) anchors correctness with exact-value tests; the
typed core grows as later phases need more fields, and more real files will harden tolerance.

---

## ADR-160: Stated-financials data model — Phase-3-shaped, one-to-many, tenant-scoped via the file

- **Date:** 2026-06-12
- **Status:** Accepted

**Decision:** MISMO stated financials are persisted as new **one-to-many** models
(`app/models/stated_financials.py`): `StatedIncomeItem` + `StatedEmployer` (FK → **borrower**),
`StatedLiability` + `StatedAsset` (FK → **loan_file**). They are typed for **Phase-3 deterministic
comparison** — `Decimal` amounts (exact, summable) and the MISMO category (`income_type` /
`liability_type` / `asset_type`) as a **flexible string** (the MISMO enumerations are large/evolving,
so they are *not* CHECK-enums — ADR-037). The existing `Borrower` / `Property` / `LoanFile` models
are **extended** (not duplicated) with the MISMO core fields they lacked, all **nullable** (manual
creation leaves them empty): Borrower `dependent_count` / `citizenship` / `declarations` (JSON);
Property `valuation_amount` / `attachment_type` / `construction_method` / `financed_unit_count`;
LoanFile `note_amount` / `note_rate_percent` (Numeric(7,4)) / `lien_priority` / `amortization_type` /
`amortization_months` / `application_received_date`. Tenant-scoped **transitively** via the loan
file (ADR-053) — no own `company_id` — with `ON DELETE CASCADE` from the parent.

**FK placement** is by what Phase-3 needs: income/employers are per-borrower (MISMO nests them under
the borrower role; income verification is per-borrower); liabilities/assets are per-file (MISMO
carries them at the deal level; DTI and reserves are file-level).

**Reuse vs add** (gap analysis): MISMO `birth_date`→`date_of_birth`, `marital_status`,
`classification`→`is_primary`, `usage_type`→`occupancy_type`, `sales_contract_amount`→`purchase_price`,
`base_loan_amount`→`loan_amount`, `mortgage_type`→`loan_program`, `loan_purpose` all already existed
and are reused; only the genuinely-missing fields were added.

**Rationale:** the stated financials are multi-row structured data (many incomes/liabilities/assets)
that Phase-3 must compare against document-extracted values, so they must be typed/summable/queryable
rows, not loose JSON. The same core entities serve manual + MISMO creation (they converge), so
MISMO's extra fields extend them rather than forking a parallel model.

**Consequences:** the shape is a **starter**, refined with Priya / as Phase-3 rules firm up. LP-53
maps `ParsedMismo` into these. Soft-delete + the tenant-isolation/CHECK test conventions apply; each
new model has a per-model tenant-isolation test.

---

## ADR-161: MISMO catch-all + raw-file + import-record storage (capture-all + audit)

- **Date:** 2026-06-12
- **Status:** Accepted

**Decision:** A `MismoImport` model (`app/models/mismo_import.py`, FK → loan_file, cascade) is the
home for everything an import produces beyond the typed core: LP-51's **catch_all** (every non-core
MISMO leaf, grouped) as JSON; the **parse_warnings**; a **raw_file_path** reference to the original
MISMO file preserved in the storage layer for **audit**; and `source_format` + a `status`
(`MismoImportStatus` — COMPLETED/PARTIAL/FAILED, a small stable CHECK-enum). One row per import;
`imported_at` is `created_at`.

**Rationale:** the "extract all fields" decision means nothing is lost — the catch-all is queryable
later without re-parsing. The source-of-truth baseline must be **auditable**, so the original file is
preserved. The import record is the audit trail and the foundation for future re-import / versioning
(deferred). Putting all import-derived data on `MismoImport` (rather than scattering it onto
`LoanFile`) keeps the file model lean and groups the audit data.

**Consequences:** PII in the catch-all / raw file is access-controlled (tenant-scoped via the file)
and never logged. The bytes of the raw file are written by the upload path (LP-53/54); this ticket
provides the column/reference. Re-import/versioning builds on the import record.

---

## ADR-162: MISMO import service — the mapping seam; converges with manual creation; transactional; partial-parse create+warn

- **Date:** 2026-06-12
- **Status:** Accepted

**Decision:** `create_loan_file_from_mismo(db, *, parsed, company_id, raw_content, source_format=None,
actor_user_id=None)` (`app/mismo/import_service.py`) is the single seam that maps a `ParsedMismo`
(LP-51) into the LP-52 models and creates a populated `LoanFile`. It **reuses Epic 4's
`create_loan_file` and `create_property`** so a MISMO file is the *same* `LoanFile` (same model, same
downstream) as a manually-created one — they **converge**. Borrowers are constructed directly
(rather than via `create_borrower`) so they can carry the MISMO-only fields, tolerate a
non-`EmailStr` email, and position multiple borrowers; the resulting `Borrower` is identical. It maps
the stated financials into `StatedIncomeItem`/`StatedEmployer` (per borrower) and
`StatedLiability`/`StatedAsset` (per file), stores the catch-all + a stored raw MISMO file (audit) +
a `MismoImport` record, and logs a `FILE_CREATED` activity. The service **flushes**; the caller (the
LP-54 endpoint) **commits**, so the whole creation is one **all-or-nothing** transaction. MISMO
category strings are mapped to our small domain enums (marital / program / purpose / occupancy) with
**unknown → None** (the file is still created); large/evolving categories stay flexible strings.

**Partial-parse (import-directly):** a parse with missing optional fields still creates the file
(missing → `None`); `parse_warnings` are stored on the `MismoImport` (status `PARTIAL`) and surfaced
later (LP-55/56). **Floor:** if there is *no* borrower **and** no loan at all, raise
`MismoImportError`; anything above that (a borrower **or** loan present) creates the file.

**Rationale:** isolating the mapping keeps the parser and the models ignorant of each other.
Convergence keeps one kind of file. Import-directly + tolerant parsing means a partial file is
created and corrected later, not blocked. Exact `Decimal` mapping preserves the source-of-truth
baseline. The SSN is stored only through the existing encrypted Borrower column and is **never
logged**; logging is metadata-only (ids + counts); the raw file is tenant-scoped and never logged.

**Consequences:** LP-54 (endpoint) calls this service and owns the commit. Known gap: the MISMO
*borrower* address has no typed column on `Borrower` (only the subject property has an address), so
it's parsed but not persisted to a typed field — a later model change. The import record + raw file
set up future re-import/versioning.

---

## ADR-163: MISMO upload endpoint — inline (not Celery), thin orchestration, graceful error mapping

- **Date:** 2026-06-12
- **Status:** Accepted

**Decision:** `POST /api/v1/loan-files/import-mismo` (in the loan-files router) accepts a multipart
MISMO file (XML or HTML-wrapped) and runs **parse (LP-51) → create (LP-53) inline** (synchronously,
in-request), then commits and returns the created file plus parse warnings (`MismoImportResponse =
{ loan_file: LoanFileDetail, warnings: [...] }`, status `201`). The endpoint is **thin** — boundary
concerns only: it reads the bytes with a size cap (`413` over ~10 MB), rejects an empty upload
(`422`), and takes `company_id` from the authenticated user (never the body). Content validation is
`parse_mismo`'s job (don't over-restrict content-type). Failures map to safe **LP-46 envelope**
errors: `MismoParseError` (not-XML / not-MISMO) → `400`; `MismoImportError` (the floor — no borrower
and no loan) → `422`; an unexpected error → the global safe `500`. A **partial parse** is *not* an
error — it returns `201` with the created file and the warnings (success-with-warnings). It reloads
+ returns via `LoanFileDetail` exactly like the manual create endpoint (converges).

**Rationale:** MISMO parsing is **fast, deterministic** work (lxml on a ~60 KB file + a few inserts,
**no AI**) — unlike document processing, which is slow/AI-bound and therefore uses Celery (LP-41/42).
So inline is appropriate, simpler (no enqueue/poll/status-lifecycle), and the response *being* the
created file matches **import-directly** (the frontend navigates straight to the populated file).
The endpoint stays thin because the work lives in the services; graceful errors reuse LP-46.

**Consequences:** no background job for MISMO import; if a real file ever proved slow it could move
to background later. The SSN is masked in the response (existing `LoanFileDetail`) and never logged;
logging is metadata-only (file id, source format, warning count). LP-55 (the upload UI) calls this
endpoint.

---

## ADR-164: MISMO upload as the primary create-file path; import-directly; honest non-blocking warnings

- **Date:** 2026-06-12
- **Status:** Accepted

**Decision:** The "New file" screen leads with **Upload MISMO** (a prominent drag-and-drop zone for
XML/HTML, `components/intake/mismo-upload.tsx`); the manual Epic 4 intake form is **reused** and
repositioned as the secondary fallback (revealed via "Create manually"). On a successful upload the
populated file **opens immediately** (import-directly — `router.push` to the created file, plus a
success toast); there is no preview/confirm step. The imported **stated financials** are displayed
on the file's Overview ("Application data (stated)" — income/employers per borrower, the file's
liabilities and assets, the extended loan terms), **display-only** (editing is LP-56). Parse
warnings (a partial import) are surfaced **honestly and non-blocking** ("Imported — a few fields
need your attention … you can fill these in"), not as a failure. Upload failures show the LP-54 safe
envelope message friendly (via the LP-46 normalizer); the upload trigger disables while pending
(LP-47, double-submit prevention).

To display the stated financials the frontend needs them exposed, so a **minimal read-only,
tenant-scoped** endpoint was added — `GET /api/v1/loan-files/{id}/stated-financials`
(`StatedFinancialsResponse`: borrowers with income/employers, liabilities, assets, extended
loan/property fields, and the latest import record's warnings). It's a read of already-stored data
(no pipeline/model change); the import's warnings persist there, so the opened file shows them even
after navigation. SSN is masked throughout.

**Rationale:** the processor receives loan applications as MISMO from the loan officer, not by
typing — the product should match how the work actually happens. Import-directly + opening the
populated file is the payoff ("upload and it's filled in"); displaying the stated financials is the
visible proof the import worked; honest non-blocking warnings keep a partial import usable (and set
up editing in LP-56).

**Consequences:** file creation is reoriented around MISMO (manual is the fallback). The
stated-financials read is the seam later phases extend (Phase-3 cross-checks against documents will
show alongside the stated values). LP-56 adds editing of the imported data. Composes existing
patterns (drag-drop LP-43, errors LP-46, loading LP-47, the Epic 4 form, the detail view).

## ADR-165: Imported data is editable in place — reuse Epic-4 PATCH for core fields, add stated-financials CRUD; audited, SSN-safe

- **Date:** 2026-06-13
- **Status:** Accepted

**Decision:** MISMO-imported data is **reviewable and editable** (not read-only), completing the
import-directly safety net: a parse gap or wrong value (flagged by the LP-55 warnings) is corrected
on the opened file rather than by re-importing. Editing splits along the existing seam:

- **Core fields → reuse Epic-4 PATCH.** The borrower/property/loan-file PATCH endpoints already apply
  fields generically (`model_dump(exclude_unset=True)` → `setattr`), so editing the MISMO-specific
  core fields needed only **extending the Update schemas** (`BorrowerUpdate`: `dependent_count`,
  `citizenship`, `declarations`; `PropertyUpdate`: `valuation_amount`, `attachment_type`,
  `construction_method`, `financed_unit_count`; `LoanFileUpdate`: `note_amount`, `note_rate_percent`,
  `lien_priority`, `amortization_type`, `amortization_months`, `application_received_date`) — no new
  core-edit endpoints or UI. **SSN** is replaced through the existing `BorrowerUpdate.ssn` encrypted
  re-enter path (re-encrypted, masked in the response, never edited masked-in-place, never echoed).
- **Stated financials → add multi-row CRUD.** New tenant-scoped endpoints
  (`app/api/stated_financials.py`): POST under the file/borrower, PATCH/DELETE by row id, for the four
  LP-52 kinds (income, employers, liabilities, assets). Scoping is transitive (row → [borrower →]
  file → company; cross-company → **404**, anti-enumeration). Add builds `Model(**model_dump())`;
  update setattrs `model_dump(exclude_unset)`; delete is **soft** (`deleted_at`). All four edit
  actions are **audited** via the existing `FILE_UPDATED` activity type with a human summary
  ("Edited/Added/Removed a stated …") — chosen over a new `ActivityType` enum value to avoid a
  migration for a within-file edit.
- **Read carries ids.** The LP-55 stated-financials read was extended to include each row's `id` and
  to return employers as objects (`{id, employer_name, is_current}`) so the editor can target rows;
  this rippled to the frontend types and the display.
- **Frontend:** the "Application data (stated)" card flips display ⇄ edit via an Edit/Done toggle
  (`StatedFinancialsEditor`); a single generic `EditableRow` drives all kinds from a `FieldDef[]`
  config, sends only changed fields (empty → `null`), and per-group Add/Remove. One hook
  (`useStatedFinancialsEdit`) owns the mutations + cache invalidation.

**Rationale:** the original MISMO (raw file + `MismoImport` record) is preserved, so editing corrects
the *derived* application data without losing the source of truth. Reusing the generic PATCH path is
the smallest correct change for core fields; CRUD is genuinely new only for the multi-row stated
financials. Auditing every edit and scoping by company keep the file submission-grade and tenant-safe.

**Consequences:** the import flow is now end-to-end usable (upload → opens populated → fix what the
warnings flagged). Extending an Update schema automatically makes that field editable through the
existing endpoint — the pattern to follow for future fields. Reusing `FILE_UPDATED` keeps edit
provenance coarse (summary text, not a typed diff); a finer field-level audit, if needed, is a later
change. Scope is **correct + add/remove rows**, not a from-scratch application builder.

## ADR-166: Phase-1.5 consolidation — parser hardened against synthetic variants (one real file), with an honest limitation

- **Date:** 2026-06-13
- **Status:** Accepted

**Decision:** Close Phase 1.5 by making the MISMO feature durable: full-flow integration tests
(upload → parse → create → store → read → edit, real stack), a systematic tenant-isolation pass
across every new MISMO endpoint (each 404 cross-company), parser hardening against MORE files, MISMO
flow polish, a MISMO seed file, and docs. Two substantive choices are recorded here:

1. **Hardening against synthetic variants, stated honestly.** No additional real MISMO files were
   supplied (checked `/mnt/user-data/uploads/` and the repo — only `MISMO16940192.xml` exists). Rather
   than overclaim robustness, the parser is hardened against **synthetic variants derived from the one
   real file** (FHA mortgage type, a genuine distinct second borrower, missing optional sections, an
   unsupported mortgage type, a zero-income deal, HTML-wrapped) via a small builder
   (`tests/mismo/synthetic.py`). These **confirm** the LP-51 tolerance claims hold for those specific
   variations (multi-borrower income/employers attribute to the correct borrower; FHA/VA/unknown types
   are tolerated; dropped sections degrade to empty + warnings, never a crash). They **do not** exercise
   real-LOS variation (different element ordering/namespaces, FHA-specific sections like UFMIP/MIP/case
   number, true co-borrower layouts). The ticket states this limitation plainly: a real FHA file and a
   real multi-borrower file are still needed to fully harden. No parser **fix** was required because no
   real second file exposed a gap — only a proactive hardening was added (see #2).

2. **One proactive needed-now warning — zero-income deals.** The probe surfaced that a deal with no
   stated income for any borrower parsed silently (no warning). Income drives DTI, so a zero-income
   parse is almost always an incomplete file or a parse gap. The parser now appends a non-blocking
   `parse_warning` ("No income was found for any borrower.") in that case — consistent with the
   existing needed-now warnings (missing borrower name, base loan amount, property value) and the
   honest, non-blocking warnings philosophy (ADR-164). It does not fire on the real fixture (which has
   income), so existing exact-value tests are unchanged.

**Rationale:** a parser validated against a single example is fragile; the synthetic variants test the
tolerance claim against structural variation now, and the honest limitation note keeps the robustness
claim truthful. The seed gains a MISMO-imported file (the real fixture scrubbed to fully-synthetic PII,
run through the real LP-53 import service) so dev data exercises the MISMO path end to end without
storing any real person's data.

**Consequences:** Phase 1.5 is documented complete with explicit deferred items (re-import/versioning,
smart-needs/LP-58, AI-fallback, core-field edit UI). When real files arrive, drop them into
`tests/fixtures/mismo/` and add assertions — the synthetic builder and the full-flow/isolation tests
are the harness they slot into. Otherwise this is testing/polish/hardening; no architectural change.

## ADR-167: Three-tier document model — a catalog-driven, tier-aware pipeline that extends (not rebuilds) the extractor registry

- **Date:** 2026-06-18
- **Status:** Accepted

**Context:** Phase 1 handled 3 document types (`pay_stub` / `w2` / `bank_statement`) with full structured
extraction via the `EXTRACTORS` registry. Phase 2 scales the document set to ~80-100 types. Giving every
type full field-level extraction is infeasible and wasteful — most types are low-value or rarely seen, and
each extractor is real engineering (a schema, a prompt, tests). But the long-tail still has to be
*recognized* and *handled*, not dropped. The pipeline (`process_document`) already classifies (Haiku) then
routes; we needed a way to invest extraction effort where it pays off without rebuilding that pipeline.

**Decision:** Introduce a **three-tier model** keyed on a document's type, with handling routed by tier
*after* classification:

- **Tier 1 — first-class (~18 types):** full structured extraction via the **existing** `EXTRACTORS`
  registry. The 3 Phase-1 types *are* Tier 1 and are unchanged. The registry **is** the Tier-1 mechanism.
- **Tier 2 — recognized (~60-80 types):** classified + categorized + (later) a short AI summary; no deep
  extraction.
- **Tier 3 — long-tail:** anything not matching a known type → a generic analyzer produces a structured
  summary.

The single source of truth for *which* tier (and which filing category) a type gets is a **catalog**
(`app/documents/catalog.py`): a maintainable `document_type -> (tier, category)` dict with
`get_tier` / `get_category` helpers and a default of `(Tier 3, Misc)` for uncataloged types. The catalog —
**not** the database, **not** scattered `if/elif` — owns this knowledge, so adding/refining a type is a
one-line edit (no migration, ADR-053). It replaces the Phase-1 provisional `_TYPE_TO_CATEGORY` map, so tier
and category can never drift apart. A `tier` column is added to `documents` (VARCHAR + CHECK, ADR-037,
nullable until classified) recording how each document was *handled*; the type→tier *mapping* stays in the
catalog, not the DB.

`process_document` consults the catalog after classification and branches by tier — Tier 1 → the registry;
Tier 2 → a summarize path; Tier 3 → a generic-analyzer path — with the pre-existing low-confidence/`unknown`
gate still routing those to `NEEDS_REVIEW` first. **Every document takes exactly one path and reaches a
terminal status** (the resilience discipline). Two specific choices:

1. **A Tier-1 type whose extractor isn't built yet** (the LP-60..64 types, cataloged now) has no registry
   entry → handled as **classified-only / `COMPLETED`** (no crash), exactly as Phase 1 already handled a
   type with no extractor. Its extractor simply registers later and the same path runs extraction. Chosen
   over `NEEDS_REVIEW` because the document is *correctly recognized* — nothing for a human to fix — and this
   keeps the existing "unregistered type" behavior unchanged.
2. **Tier 2 and Tier 3 are clean stubs** (`_tier2_summarize_stub` / `_tier3_analyze_stub`) that record the
   document at its tier and reach `COMPLETED`. LP-65/66 fill the real summary/analyzer *in place* without
   restructuring the routing — the seam is complete now.

**Rationale:** tiering concentrates extraction engineering on the docs whose exact data drives Phase 3
verification (Tier 1), while still recognizing and filing the rest (Tier 2/3) — the level-of-investment
matches the value. A catalog centralizes the type→tier+category knowledge in one readable place that grows
(LP-59 adds all ~80 types) and refines with the domain expert (Priya), with no schema churn. Extending the
existing registry + classification pipeline — rather than building a parallel one — means the 3 existing
types keep working byte-for-byte and the new machinery is purely additive.

**Consequences:** LP-59 fills the full ~80-type catalog + the matching comprehensive classification; LP-60..64
add Tier-1 extractors (each just registers in `EXTRACTORS`; the catalog already lists them); LP-65 fills the
Tier-2 summary stub; LP-66 fills the Tier-3 analyzer stub. The catalog and the tier/category sets are
expected to evolve with Priya. Because the stubs currently set `COMPLETED`, a Tier 2/3 (or
extractor-pending Tier 1) document reads as "completed" with no extraction — honest for the foundation
(the doc *is* handled as far as this tier goes today), and the later tickets add the summary/analysis
without a status redesign.

## ADR-168: Comprehensive ~80-type classification — catalog-synced prompt, confidence-gated, industry-standard starter

- **Date:** 2026-06-18
- **Status:** Accepted

**Context:** LP-58 built tier-aware routing but seeded the catalog with only a starter set, and the Phase-1
classification prompt knew ~3 types — so most real documents would classify as `unknown` and default to
Tier 3, never reaching their correct tier/category. To make the three-tier model real across breadth, the
classifier needs the knowledge to recognize the full document set. The resident domain expert's (Priya's)
real document library is not yet available, so the taxonomy has to start from somewhere defensible.

**Decision:** Expand the catalog to the **full ~80-type taxonomy** (88 types: 18 Tier 1, 70 Tier 2, across
all seven categories) drawn from an **industry-standard** US residential mortgage document set, and rewrite
the classification prompt to recognize all of them. Specifics:

- **One taxonomy, two artifacts, kept in sync by construction.** The catalog (`app/documents/catalog.py`)
  is the structural source of truth (type → tier + category). The recognition knowledge — each type's
  **distinguishing indicators** — lives in `DOCUMENT_TYPE_INDICATORS` (`app/ai/classification_prompt.py`).
  The prompt's *type list is derived from the catalog*: `render_classification_prompt()` iterates the
  catalog (grouped by category) and injects each type + indicator into a template (the framing/output rules
  stay an editable `.txt`). A test asserts the indicator set exactly equals the catalog set, so the two
  cannot drift — adding a type to the catalog without describing it fails CI.
- **The classifier returns type + category + confidence.** Category is **advisory** (parsed for
  observability); the authoritative category persisted on the document is the **catalog's** `get_category` —
  one source of truth (ADR-167), so a model/catalog disagreement can't mis-file a document.
- **Confidence gates routing, and the `unknown` slug alone does not.** The pipeline now branches on
  *confidence*, not on `document_type == "unknown"`: **low confidence** (the model is unsure *which* known
  type — it could be one) → `NEEDS_REVIEW` (a human confirms via the LP-44 override); **high-confidence
  `unknown`** (the model is sure it is *none* of the known types) → falls through to tier routing, where the
  catalog maps it to **Tier 3** (the generic analyzer — that is its purpose). The graceful error fallback
  still returns `unknown` at **zero** confidence, so AI failures land in `NEEDS_REVIEW`, not Tier 3. The
  threshold stays `0.5` (LP-42).
- **Industry-standard starter, honestly scoped.** The taxonomy + indicators are explicitly a starting
  point to **refine with Priya**; per-type accuracy is to be validated against real labeled documents over
  time. Tests verify the *mechanism* + a representative spread, not exhaustive per-type accuracy (real
  labeled documents for all ~80 types are not available).

**Rationale:** deriving the prompt's type list from the catalog removes the single biggest drift risk of a
large taxonomy (a prompt that lists types the system can't route, or routes types it never describes).
Confidence-gating keeps uncertain classifications human-checked rather than confidently mis-filed, while
letting genuinely-novel documents flow to the generic analyzer instead of clogging review. An
industry-standard taxonomy is a strong, reviewable starting point while the real library is pending.

**Consequences:** LP-60..64 add the Tier-1 extractors (a Tier-1-classified type without an extractor yet is
still handled gracefully per ADR-167); LP-65/66 fill the Tier-2/3 handlers; the taxonomy + indicators refine
with Priya and tune against real documents over time. Accuracy is honestly scoped: the mechanism + a
representative spread are tested now; full per-type accuracy is an ongoing, real-document-dependent effort.

## ADR-169: Tier 1 income/employment extractors (1099/VOE/P&L/income-LOE) — the established pattern, with 1099 subtypes folded into one extractor

- **Date:** 2026-06-18
- **Status:** Accepted

**Context:** LP-58/59 route a Tier-1 document to its registered extractor, but only the 3 Phase-1 extractors
(pay_stub/w2/bank_statement) existed — the other Tier-1 types fell through to classified-only. LP-60 is the
first batch of new extractors: the income/employment cluster (1099, VOE, P&L, income LOE), the income side
of Phase 3 DTI. This is repetitive application of an established pattern, not new architecture — but one
shape question (the 1099 series) and one honesty question (no sample documents) are worth recording.

**Decision:** Add four extractors, each following the LP-39a shape exactly (a typed core of
``TypedField``\\ s with ``SourceLocation`` + a grouped ``additional_sections`` catch-all, the shared tolerant
parser, ``derive_status``, graceful ``.failed()``, the same result interface, metadata-only logging) and
registered in ``EXTRACTORS`` so the Tier-1 routing reaches them. Specific choices:

- **1099 — one extractor for the whole series, not five.** The 1099 is a series (NEC/INT/DIV/MISC/R) with
  different relevant boxes. Rather than a separate extractor/type per subtype, the typed core carries a
  ``form_subtype`` slug + a single ``income_amount`` (the primary figure *for that subtype*, selected by the
  prompt); every specific box lands in the catch-all. One catalog type (``1099``), one extractor, the
  subtype preserved for Phase 3 (NEC ≈ self-employment income; INT/DIV ≈ asset income).
- **LOE — prose-light typed core.** A Letter of Explanation has no fixed form, so its typed core is
  deliberately minimal (``subject`` + ``explanation_summary`` + a single primary referenced
  employer/date/amount); additional references go to the catch-all. Capture *what is explained*, not rigid
  fields. (The same type also appears in the LP-63 borrower-info context; the extractor is shared.)
- **Sensitive TINs follow the W-2 SSN discipline (ADR-147).** The 1099 ``recipient_tin`` (an SSN for an
  individual) is extracted into the typed core for the Phase 3 identity cross-check but is **never logged**
  (only counts + the non-PII subtype) and is masked in display.
- **Typed cores are V1 starters, refined with Priya; accuracy is honestly scoped.** No sample 1099/VOE/P&L/
  LOE documents were available, so the tests verify the **mechanism/shape** (the extractor returns the
  typed-core + catch-all shape, coerces types, carries source locations, fails gracefully, the 1099 subtype
  variation, the routing reaches each) — **not** extraction accuracy against real forms. The catch-all is
  the safety net: a missing field is captured, not lost, and can be promoted to the typed core later.

**Rationale:** following the established pattern keeps every extraction uniform downstream (the pipeline,
``create_extraction_version``, the detail drawer handle them identically). Folding the 1099 subtypes into one
extractor matches how the catalog/classifier treat ``1099`` as a single type and avoids five near-duplicate
modules, while the subtype slug keeps the income-vs-asset distinction. Honest accuracy scoping avoids
claiming per-form correctness we can't demonstrate without real documents.

**Consequences:** LP-61..64 extend Tier 1 to the asset/property/borrower-info/tax-return clusters the same
way; the field sets refine with Priya; the detail drawer (LP-72) renders these like the existing three;
real samples validate accuracy over time. Sensitive TINs/SSNs are masked in display + never logged.

## ADR-170: Tier 1 asset extractors (investment/retirement/gift-letter) — the established pattern, with the vested-vs-total and gift-attestation nuances

- **Date:** 2026-06-18
- **Status:** Accepted

**Context:** LP-61 is the second Tier-1 extractor batch — the asset/reserves cluster. Bank statements (the
most common asset doc) are already Tier 1 (LP-39c); this adds the other major asset documents: an investment
statement, a retirement statement, and a gift letter. Assets prove the borrower has the funds for the down
payment, closing costs, and reserves (the lender-required cushion), and these typed cores are cross-checked
in Phase 3 against the stated assets imported from the MISMO (Phase 1.5 — e.g. a file's stated
"RetirementFund $243,000, Stock $19,000, GiftOfCash $56,000"). Repetitive application of the established
pattern, with two nuances worth recording.

**Decision:** Add three extractors, each following the LP-39a shape exactly (typed core of ``TypedField``\\ s
with ``SourceLocation`` + grouped ``additional_sections`` catch-all, the shared tolerant parser, graceful
``.failed()``, the uniform result interface, metadata-only logging), modeled on the **bank statement**
extractor (the closest template — an asset doc with a masked account, a statement period, and balances), and
registered in ``EXTRACTORS``. Specific choices:

- **Investment + retirement are flat (typed core + catch-all), not transactional.** Unlike the bank
  statement, the decision figure is a single balance/value, not a transaction list, so holdings (if
  itemized) go to the catch-all rather than a first-class list. ``total_value`` (investment) and the two
  retirement balances are the typed-core figures.
- **Retirement tracks vested AND total balances separately.** ``vested_balance`` is the portion the borrower
  actually owns/can access (unvested employer funds aren't available; even vested funds carry early-withdrawal
  penalties), so it is the reserves-relevant number — but the prompt is told **not** to assume
  ``vested == total``: if only one balance is shown and vesting isn't mentioned, it fills ``total_balance``
  and leaves ``vested_balance`` null. Both are captured for Phase 3 to use the right one.
- **The gift letter is attestation-oriented (prose-aware), like the LOE.** Its typed core captures the
  parties + ``gift_amount`` + property + a ``no_repayment_attestation`` — the statement that the funds are a
  genuine gift with no expectation of repayment. That attestation is what distinguishes a gift (an asset)
  from undisclosed debt; it is captured as text (present/absent + wording), left **null** when the letter
  doesn't state it (never fabricated). No account number is present.
- **Account numbers follow the bank-statement masking discipline (ADR-149).** ``account_number_masked``
  (investment, retirement) is captured masked (last 4), **never logged**, and masked in display.
- **V1 starters, refined with Priya; accuracy honestly scoped.** No sample investment/retirement/gift-letter
  documents were available, so tests verify the **mechanism/shape** (the typed-core + catch-all shape, source
  locations, type coercion, graceful failure, the vested-vs-total distinction, the gift attestation, the
  routing reaches each) — **not** per-document accuracy, validated as real documents flow through.

**Rationale:** following the established pattern keeps every extraction uniform downstream. The
vested-vs-total separation and the no-fabrication rule keep the reserves figure honest (over-counting
unvested funds, or assuming vesting, would inflate reserves). Capturing the gift attestation cleanly is the
single most important thing about a gift letter — without it, gifted funds could be mistaken for an
undisclosed liability. These cores are exactly the values Phase 3 cross-checks against the stated MISMO
assets.

**Consequences:** LP-62..64 extend Tier 1 to the property/borrower-info/tax-return clusters; the field sets
refine with Priya; the detail drawer renders these like the others; account numbers are masked + never
logged; accuracy is validated with real samples over time.

## ADR-171: Tier 1 property extractors — the established pattern, spanning subject-property facts and other-property obligations

- **Date:** 2026-06-18
- **Status:** Accepted

**Context:** LP-62 is the third Tier-1 extractor batch — the property cluster: purchase agreement,
homeowner's insurance, mortgage statement, property tax bill, HOA statement. Property documents serve two
distinct verification purposes, and one of them creates a matching problem worth recording.

**Decision:** Add five extractors, each following the LP-39a shape exactly (typed core of ``TypedField``\\ s
with ``SourceLocation`` + grouped ``additional_sections`` catch-all, the shared tolerant parser, graceful
``.failed()``, the uniform result interface, metadata-only logging), and register them in ``EXTRACTORS``.
Key points:

- **The cluster spans two contexts.** *Subject-property facts* drive LTV and housing expense: the purchase
  agreement's ``sales_price`` (the LTV basis, cross-checking the stated MISMO ``SalesContractAmount``) and
  the insurance binder's ``coverage_amount`` + ``annual_premium`` (housing expense). *Other-property
  obligations* drive DTI: the mortgage statement's ``monthly_payment``, the tax bill's ``annual_tax_amount``,
  and the HOA statement's ``dues_amount`` — each cross-checking the stated MISMO liabilities.
- **Capture the property address; do NOT decide subject-vs-other.** A mortgage statement / tax bill / HOA
  statement may be for the subject property OR another property the borrower owns. Each extractor captures
  ``property_address`` in its typed core, and the prompts are explicit that the model must **not** decide
  which property it is — Phase 3 matches the address to the subject property. Keeping the matching out of the
  extractor avoids guessing and keeps the extraction a faithful read.
- **``due_dates`` (tax bill) stays a string.** A property tax bill commonly has two installment due dates;
  capturing them verbatim as a string loses nothing (vs. forcing a single ``date``), and Phase 3 can parse.
- **V1 starters, refined with Priya; accuracy honestly scoped.** No sample property documents were available,
  so tests verify the **mechanism/shape** (typed-core + catch-all, source locations, type coercion, graceful
  failure, the address capture, the routing reaches each) — **not** per-document accuracy.
- **The appraisal is deliberately NOT extracted here.** The appraisal's appraised value also feeds LTV, which
  might argue for Tier-1 extraction, but the catalog currently classifies ``appraisal`` as **Tier 2**
  (recognized, not extracted). This ticket honors the catalog and does not extract it. **Flagged** as a
  candidate for Tier-1 promotion in a future catalog refinement with Priya — noted, not acted on here.

**Rationale:** following the established pattern keeps every extraction uniform downstream. Capturing the
address (without deciding subject-vs-other) is what lets Phase 3 correctly separate the borrower's housing
expense on the subject property from obligations on other properties — getting that wrong would mis-state
DTI. These typed cores are exactly the values Phase 3 cross-checks against the stated MISMO property +
liabilities.

**Consequences:** LP-63/64 extend Tier 1 to the borrower-info and tax-return clusters; the field sets refine
with Priya; the detail drawer renders these like the others; the appraisal's Tier-1 promotion is an open
question for the catalog/Priya; accuracy is validated with real samples over time.

## ADR-172: Tier 1 borrower-info/legal extractors — heightened ID PII, divorce-decree obligations captured (findings sequenced to LP-66/67), the LOE reused

- **Date:** 2026-06-18
- **Status:** Accepted

**Context:** LP-63 is the fourth Tier-1 extractor batch — the borrower-info/legal cluster: the driver's
license / government ID (identity, KYC), the divorce decree (legal obligations/awards), and the general
Letter of Explanation. Two things make this batch different from the prior extractor batches: the ID is the
most PII-dense document in the product, and the divorce decree produces *findings* whose infrastructure
isn't built yet.

**Decision:** Add the ID and divorce-decree extractors (following the LP-39a shape exactly) and **reuse** the
existing LOE extractor; register the two new types in ``EXTRACTORS``. Key choices:

- **Heightened ID PII — the W-2 SSN discipline (ADR-147), at its strictest.** The whole ID is PII.
  ``id_number_masked`` is captured masked (last 4, the model masks it), ``date_of_birth`` is captured for the
  Phase 3 identity cross-check — and **no extracted value is ever logged** (only status / confidence /
  counts). The raw values live only in the tenant-scoped extraction JSON (ID number masked, DOB masked in
  display). A dedicated test asserts the DOB, the ID number, the name, and the address never appear in logs.
  All ID test data is **synthetic** — never a real identity document.
- **The ID expiration is captured.** An expired ID is invalid; ``expiration_date`` feeds validity / staleness
  (LP-71).
- **Divorce-decree obligations captured now; formal findings sequenced to LP-66/67.** The support
  obligations (alimony / child support) are the canonical undisclosed-obligation feedstock Phase 3
  cross-checks against the stated liabilities. Because a decree can set more than one obligation, they are
  captured as a **first-class typed list** (``support_obligations`` — type/amount/frequency/payer, each with
  source), alongside a ``property_awards`` list — the same structured-rows extension the bank statement uses
  for transactions (ADR-061), **not** a new shape. **Surfacing them as formal findings** (the structured
  observations the implications engine + Phase 3 read) is **wired when the findings infrastructure exists
  (LP-66/67)** — this ticket captures the data without building findings infrastructure prematurely. Nothing
  is lost: the obligations are in the typed list today.
- **The general LOE is reused, not duplicated.** LP-60 already built the ``letter_of_explanation`` extractor
  with a general ``subject`` + ``explanation_summary`` + referenced facts, and the catalog files it under
  ``borrower_info``. It already serves the general variant; this ticket reuses it (only the prompt was
  lightly broadened to enumerate general subjects — no schema/registry change), so there is one LOE
  extractor, not two.
- **V1 starters, refined with Priya; accuracy honestly scoped.** No sample documents were available, so the
  tests verify the **mechanism/shape** (incl. the critical PII no-logging check and the obligation-list
  capture) — not per-document accuracy.

**Rationale:** identity and legal documents establish who the borrower is and what legal obligations affect
the loan. The ID's PII density demands the strictest no-logging discipline in the codebase. Capturing the
decree's obligations now (as structured rows) means the cross-check feedstock exists the moment the findings
infrastructure lands, without a re-extraction — and capture-now/wire-later avoids building findings
infrastructure out of order. Reusing the LOE keeps one extractor for one catalog type.

**Consequences:** LP-64 completes Tier 1 (tax returns); LP-66/67 build the findings infrastructure that
surfaces the divorce-decree obligations as findings and cross-checks them (Phase 3); the ID expiration feeds
staleness (LP-71); accuracy is validated with real (synthetic / redacted — never real) samples; field sets
refine with Priya.

## ADR-173: Nested tax-return extraction — a 1040 core + typed income-critical schedules + catch-all (Tier 1 complete)

- **Date:** 2026-06-18
- **Status:** Accepted

**Context:** LP-64 is the final and hardest Tier-1 extractor. A tax return is **not one form** — it is Form
1040 plus a **variable** set of schedules (Schedule C self-employment, Schedule E rental, K-1 partnership,
plus B/D/1/2/3 and attachments), and which schedules are present depends on the borrower. The single-form
typed-core+catch-all shape (LP-39a) doesn't fit a variable, nested bundle. Crucially, **the self-employed
case is the point**: for a W-2 employee the return is largely redundant, but for a self-employed borrower the
return is THE primary income document — Schedule C ``net_profit`` is the qualifying-income figure (the real
MISMO sample borrower had self-employment income from multiple LLCs — exactly this case).

**Decision:** Extract the tax return as a **nested** bundle that extends — not replaces — the established
shape: a **1040 typed core** + **typed income-critical schedule sub-structures** + the grouped catch-all.

- **Type the income-critical schedules; catch-all the rest.** ``schedule_c`` (a **list** — a borrower can
  have several businesses; ``net_profit`` is the heart), ``schedule_e`` (present-or-null, with a
  ``properties`` list + ``total_net_rental_income`` + ``depreciation``), and ``k1s`` (a list) are typed.
  Every other schedule (B/D/1/2/3, W-2s/1099s included in the bundle, attachments) goes to
  ``additional_sections`` — captured, not deeply typed. Which schedules/figures to promote to typed is a
  refine-with-Priya question.
- **Variable composition, no hallucination.** A schedule absent → an empty list / ``null`` (never assumed); a
  fully-empty schedule entry is dropped (no invented schedules). Each schedule field is a ``TypedField`` with
  ``SourceLocation`` parsed through the **same** shared typed-core parser, so the nesting reuses the existing
  machinery rather than inventing new parsing. Status is derived from the 1040 core **and** the schedules (a
  self-employed return may be mostly its schedules).
- **Generous token budget.** A multi-page, multi-schedule bundle is the most content of any extractor, so
  ``max_tokens`` is 16384 (vs 4096 for single-form extractors); a truncated/malformed response still fails
  gracefully (``.failed()``).
- **Same result interface despite nested data.** ``TaxReturnExtractionResult`` exposes the same
  ``data`` / ``status`` / ``confidence`` / ``.failed()`` / ``model_dump`` interface as every other extractor,
  so the pipeline + ``create_extraction_version`` + the detail drawer handle the nested data uniformly.
- **Captures figures for Phase 3; does NOT compute income.** The qualifying-income derivation (combining
  Schedule C net profit + add-backs, the two-year comparison) is Phase 3. This ticket extracts one return's
  figures accurately.
- **SSN masked + never logged** (ADR-147). Tax returns are among the most sensitive documents; metadata-only
  logging (counts + which-schedules-present), no return values or SSN in logs.

**Rationale:** the nested typed-core+catch-all handles the variable composition while typing exactly the
high-value schedules that drive the self-employed income picture — the case where the return matters most.
Reusing the shared parser for each schedule keeps the nesting from being a new shape. The figures are the
feedstock for Phase 3's income math.

**Accuracy — honestly (emphatically) scoped.** A tax return is the most varied, multi-schedule document of
any extractor here. With **no real sample returns available**, the tests verify the nested **mechanism/shape**
(the 1040 core, Schedule C ``net_profit``, the present-or-null + repeatable schedules, the catch-all, the
SSN no-logging, graceful failure) — **NOT** extraction accuracy against real returns. A multi-schedule
extractor tested only against constructed inputs is **especially unproven**; accuracy must be validated
against real (synthetic/redacted) **self-employed** returns over time and the field set refined with Priya.

**Consequences:** **Tier 1 breadth is complete** (LP-60..64 — every Tier-1 catalog type now has an
extractor, asserted by a test). Phase 3 derives qualifying income from the captured figures + does the
two-year comparison; which schedules/figures to type refines with Priya; tax-return accuracy needs
real-return validation most acutely of any extractor. Phase 2 now moves to the Tier 2/3 handlers (LP-65/66).

## ADR-174: Tier 2 shared summary path — one lightweight mechanism for ~60-80 recognized types

- **Date:** 2026-06-19
- **Status:** Accepted

**Context:** Tier 2 is the bulk of the taxonomy — the ~60-80 *recognized* document types that need to be
classified, filed, and glanceable, but whose individual field values nobody computes on (unlike Tier 1's
income/asset/property figures). LP-58 stubbed the Tier 2 routing path; this fills it. The whole point of the
tier model is efficiency: ~18 extractors + **1** Tier-2 path + 1 Tier-3 analyzer, not ~80 extractors.

**Decision:** Handle every Tier 2 document through **one shared path** (`_tier2_summarize`, filling the LP-58
stub) — **no per-type logic** (no `flood_certification.py` / `credit_report.py`). The document arrives
already classified + categorized (LP-59); the path adds a single lightweight AI **summary** and finalizes:

- **A gist, not extraction.** The summary is a 1-2 sentence human-readable answer to "what is this document,
  briefly?" (what it is + a key identifying detail) — **not** structured data, **not** typed fields, **not**
  source locations. The sharp contrast with Tier 1: Tier 1 extracts precise values that *drive decisions*;
  Tier 2 summarizes for *human reference*.
- **Cheap.** `summarize_document` uses the **Haiku-class** (classification) model, capped at 256 tokens —
  low cost-per-document is the point of Tier 2 (one cheap call across ~80 types). A response cap guards a
  rambling answer without failing it.
- **Forgiving / low-stakes.** A slightly-off gist is fine (human reference, not a calculation) — accuracy is
  proportionately light and refine-able, unlike a wrong Tier-1 figure.
- **Graceful.** `summarize_document` never raises and returns `None` on any failure; a failed summary still
  finalizes the document (recognized + categorized, `summary` null) — never stuck, never a crash (the
  resilience discipline). The summary text is **never logged** (it can quote document PII) — only a length /
  presence flag.
- **Normal, package-eligible documents.** A Tier 2 doc is a first-class file document — it appears in the
  Documents tab under its category with its summary, and is part of the file (package groundwork is LP-72;
  assembly is Phase 6). Not second-class.
- **Stored + minimally visible.** A nullable `summary` TEXT column on `documents` (migration `b344317498a5`,
  up/down) holds the gist; the frontend shows it lightly (a subtle line in the document list + a "Summary"
  block in the existing drawer). The **full tier-aware detail view** (Tier 1 fields / Tier 2 summary / Tier 3
  findings) is **LP-72** — this ticket only makes the summary visible.

**Rationale:** the ~60-80 recognized types must be handled, but giving each its own extractor (or even its own
summary logic) is exactly the waste the tier model avoids. One shared recognize-and-summarize path gives broad
coverage cheaply; a forgiving summary is the right level of investment for documents whose exact field values
no rule consumes.

**Consequences:** LP-66 fills the Tier 3 stub (the generic analyzer + findings); LP-72 builds the full
tier-aware detail view + package groundwork; the summary is refine-able and low-stakes; Tier 2 docs appear in
the Documents tab and (later) the lender package. The summary is best confirmed against real documents over
time, but the stakes are low.

## ADR-175: Tier 3 generic analyzer + the document-findings infrastructure (uniform across tiers)

- **Date:** 2026-06-19
- **Status:** Accepted

**Context:** Two related needs. (1) **Tier 3** — the long-tail: documents no predefined schema anticipates (a
court order, a trust, a personal-loan agreement, a handwritten letter). Without handling they are opaque
files. (2) **Findings** — multiple earlier tickets deferred to "when the findings infrastructure exists":
LP-63's divorce-decree obligations are captured but not yet surfaced as findings, and the implications engine
(LP-67) + Phase 3's cross-source verification both need a structured place to read document observations
from. This ticket builds both, and they meet: the Tier 3 analyzer is the first big *producer* of findings.

**Decision:**

- **One generic analyzer for all Tier 3 docs** (`app/ai/generic_analyzer.py`, filling the LP-58 stub). No
  per-type logic: a single flexible analysis produces **generic slots** that work for any document —
  `document_type_guess`, `key_parties`, `key_dates`, `key_amounts`, `key_findings`, `summary`, `full_text`.
  **Sonnet** (it is *understanding*, not a cheap one-liner) with a generous budget. Like the other AI
  helpers it never raises (`None` on failure); a failed analysis still finalizes the document. The analysis +
  the **full text** are stored on the document, and the full text gets a **GIN full-text index** (Tier 3 docs
  can't be found by type, so search matters most for them — the data + index now; the search UI is future).
- **A `DocumentFinding` model — single-document observations, uniform across tiers.** A finding is something a
  *single* document asserts that may affect the loan (an obligation, a property interest, an income item, a
  discrepancy candidate). Shape: `finding_type` + `description` + common typed fields (`amount`, `frequency`)
  + a flexible `details` JSON catch-all (findings vary — an obligation has amount+frequency, a property
  finding has an address) + `status`, source-linked to its `document` and **tenant-scoped transitively**
  (`document -> loan_file -> company`, no own `company_id`, ADR-052). **One shared recording mechanism**
  (`create_document_finding`) is used by *both* the Tier 3 analyzer's `key_findings` **and** the Tier 1
  divorce-decree extractor's obligations, so LP-67 + Phase 3 consume findings identically regardless of which
  tier surfaced them.
- **Distinct from the Phase 3 verification `Finding`.** The existing `Finding` (table `findings`) is a Phase 3
  *verification result* (a rule's red/yellow/green flag against the whole loan file, with a resolution trail).
  A `DocumentFinding` (table `document_findings`) is an *input observation* from one document; Phase 3 reads
  these and may *produce* a verification `Finding`. Two genuinely different concepts → two models / two
  tables, **not** an overload of `Finding` (which would conflate input observations with verification
  results). The ticket said "Finding model"; the pre-existing `Finding` made `DocumentFinding` the honest name.
- **The LP-63 loop is closed.** The divorce decree's captured support obligations are wired into findings via
  `record_findings_from_extraction` (in `_extract_branch`, on a successful extraction) → the same
  `create_document_finding`. A divorce decree's `$1,200/mo` obligation becomes the same kind of finding a
  Tier 3 court order's judgment does.
- **Visible + recorded.** Findings are persisted (the Phase 3 / LP-67 feedstock) and surfaced via a
  tenant-scoped read endpoint (`GET /loan-files/{id}/findings`, `ScopedLoanFile` → 404 cross-company). The
  full tier-aware *display* (Tier 1 fields / Tier 2 summary / Tier 3 analysis + findings) is LP-72.
- **Moderate accuracy stakes.** Findings are **surfaced for a human to assess** (human-in-the-loop) — more
  than a Tier 2 summary, less than Tier 1 extraction. They are *not* silently fed to calculations; Phase 3
  does the cross-check.

**Rationale:** a single flexible analyzer makes the long-tail legible without ~80 more schemas; findings need
one structured home so the implications engine + Phase 3 read them uniformly regardless of source tier;
recording findings *structurally* (not just as text) is what lets Phase 3 cross-check them; the divorce-decree
wiring closes the "capture now, wire later" deferral with no re-extraction.

**Consequences:** the **three-tier handling is complete** (Tier 1 extract / Tier 2 summarize / Tier 3
analyze). LP-67 reads `DocumentFinding`s to suggest needs; Phase 3 cross-checks them against the stated data
and may produce verification `Finding`s; LP-72 builds the full tier-aware detail + the findings display; the
full-text **search UI** is future (the index exists now). Accuracy is refine-able with real/varied documents
(human-in-the-loop), and the finding-type set refines with Priya.

## ADR-176: Implications engine — findings → suggested needs (surface + suggest, not act; findings-scoped, feeding LP-69)

- **Date:** 2026-06-19
- **Status:** Accepted

**Context:** Findings (LP-66) are passive observations — "this document asserts a $500/mo child support
obligation." They are only useful if they become actionable. The implications engine is the **first consumer
of findings**: it turns each into a *suggestion* for the processor ("→ consider a need to document this
obligation") — the bridge from findings (what documents say) to the needs list (what the file still requires).
The needs-list model/engine itself is LP-68 and the holistic AI needs reasoning is LP-69, so LP-67 must
produce a clean intermediate that feeds them without depending on them.

**Decision:**

- **Surface + suggest, do NOT act (the locked constraint).** The engine produces `SuggestedNeed`s the
  processor disposes of — it **never** mutates the financial picture (no silent debt-adding, no DTI change),
  **never persists anything**, and **never creates a needs-list item**. Acting on findings is Phase 3
  (human-confirmed); disposing of suggestions is the LP-68/70 needs flow. The functions are pure
  (`suggest_needs_for_finding`) or read-only (`suggest_needs_for_loan_file` does a single `SELECT`). A test
  asserts that running the engine creates no `NeedsItem` and mutates no finding.
- **A bounded, explainable, findings-scoped mapping.** Each `DocumentFindingType` maps to a sensible
  suggested need: `obligation` → payment history / obligation documentation; `income_related` → VOE / income
  explanation; `property_interest` → property documentation review; `discrepancy_candidate` → review
  (Phase 3 does the cross-check); `other` → **no suggestion** (a sensible "none", not a noisy generic). The
  mapping is **deterministic** (no AI) — bounded and testable; the heavy holistic reasoning is LP-69. (A
  small AI call to phrase suggestions could be added later, but the core is a bounded mapping.)
- **Explainable + traceable.** Every `SuggestedNeed` carries `reasoning` (the human-readable *why*, e.g.
  "Because document X asserts a $500.00/monthly obligation, the file should document this recurring
  obligation") plus `source_finding_id` + `source_document_id` — the machine-traceable chain
  *suggestion → finding → document*. Trustworthy, not mysterious.
- **An on-demand intermediate, not a new table.** `SuggestedNeed` is a Pydantic structure produced **on
  demand** — a pure projection over the persisted findings (no table, no migration, recomputed when needed).
  Persisting would risk staleness and a premature schema LP-68 would reshape. LP-68 (the needs engine) and
  LP-69 (the AI needs reasoning) ingest these suggestions as ONE input source and decide how/whether each
  becomes a real needs-list item.
- **Findings-scoped, NOT file-scoped.** LP-67 maps *one finding → its implied need(s)*. The holistic,
  whole-file reasoning (the complete needs list from stated data + documents + findings + these suggestions)
  is **LP-69**, which consumes these among everything else. LP-67 does not duplicate that — it is a focused,
  composable mapper that *feeds* it.

**Rationale:** turning passive observations into active suggestions is what makes findings useful;
surface-not-act keeps the human in control of what affects the financial picture (the human-in-the-loop
spine); a bounded findings-scoped mapping keeps LP-67 small and composable, feeding LP-69's holistic
reasoning without duplicating it; explainability makes suggestions actionable; an on-demand intermediate
avoids a premature schema.

**Consequences:** LP-68 builds the needs model/engine that ingests these suggestions (deciding which become
needs-list items); LP-69 does the holistic AI needs reasoning (consuming findings + these suggestions among
everything else); LP-70 surfaces needs in the UI; Phase 3 acts on findings (cross-source) with the human in
the loop. The mapping refines as the needs work + Priya input land.

## ADR-177: Needs-list engine — five states, deterministic type-level matching, per-file serialization, a thin floor (AI is LP-69)

- **Date:** 2026-06-19
- **Status:** Accepted

**Context:** The needs list — the file's living checklist of what it still requires — is the highest-value
differentiator and must be **solid** before the AI layers on. It is stateful (a need moves through a
lifecycle) and concurrent (real processing dumps batches of documents for a file). LP-68 builds the
DETERMINISTIC engine (states, satisfaction-matching, serialization, a thin floor); LP-69 adds the
case-by-case AI reasoning; LP-70 builds the UI.

**Decision:**

- **Five-state arrival lifecycle** (on the existing LP-19 `NeedsItem`): `PENDING` → `RECEIVED` → `VERIFIED`
  | `REJECTED`; any → `WAIVED`. Driven by **document arrivals + processor actions, not AI**. (`OUTSTANDING`
  was renamed to `PENDING`; `VERIFIED`/`REJECTED` added. The LP-19 `REQUESTED` borrower-outreach state is
  kept as an orthogonal pre-existing value — a need awaiting arrival may be `PENDING` or `REQUESTED`, and
  both are satisfiable.) Transitions are guarded by a valid-transition map (an invalid transition raises).
  `"Verified" = the document passed (extraction succeeded)`; Phase 3 adds cross-source rules later.
- **Deterministic, type-level satisfaction-matching.** When a document reaches a terminal status, the engine
  advances the oldest open need whose `needs_type` equals the document's `document_type`: Received → Verified
  (the document `COMPLETED`) | Rejected (it `NEEDS_REVIEW`/`FAILED`). No false matches; no AI.
  Quantity/recency-granular matching ("2 pay stubs", "within 30 days") is a documented future refinement.
- **Per-file serialization (the race fix).** The needs update runs as a **separate Celery task**
  (`needs.update_for_document`, enqueued after a document is terminal) that acquires a **per-loan-file Redis
  lock** before applying the matching. Concurrent arrivals for the SAME file apply one at a time (no lost
  update / double-satisfaction on the shared needs state); DIFFERENT files (different lock keys) update in
  PARALLEL. The lock auto-expires (`timeout`) so a crashed worker never deadlocks a file. A naive inline
  "doc arrives → update needs" within each per-document task would race under batch arrivals — hence the move
  out of the pipeline into a serialized task.
- **A thin deterministic floor.** A small set of **near-certain** needs seeded from the **stated MISMO data**
  (employment income → pay stubs + W-2; a purchase → purchase agreement; stated assets → a bank statement),
  wired into the MISMO import. Floor needs are `origin=FLOOR`, `disposition=CONFIRMED` (near-certain), and
  the seeder is idempotent. Thin by design — the bulk of the intelligence is LP-69's AI reasoning, which
  augments this baseline.
- **Source-agnostic + disposition groundwork.** A need carries its `origin` (the source-agnostic provenance:
  `floor` / `suggestion` / `ai_reasoning` / …) and a `disposition` (the human-confirmation lifecycle:
  proposed / confirmed / waived / dismissed — AI proposes in LP-69, the processor confirms in LP-70), plus
  `reasoning` + `source_finding_id` for explainability. `ingest_suggested_need` turns an LP-67 `SuggestedNeed`
  into a need (carrying the reasoning + the source-finding link); LP-69's proposals ingest the same way.

**Rationale:** the needs list must be correct under concurrency before the AI layers on, so the deterministic
engine is built + tested on its own (states, matching, serialization, floor). Per-file serialization is a
hard requirement — without it, batch document arrivals corrupt the shared needs state. The thin floor
guarantees the obvious needs deterministically (the reliable baseline AI augments). Source-agnostic +
disposition groundwork lets LP-67/69/70 plug in cleanly. Separating the deterministic engine (LP-68) from the
AI intelligence (LP-69) keeps each well-tested.

**Consequences:** LP-69 adds the holistic AI-reasoned needs (the bulk of the intelligence), ingesting via the
same source-agnostic path; LP-70 builds the UI (the dashboard + the confirm/waive flow, which the disposition
groundwork supports); Phase 3 adds cross-source rules to "Verified"; quantity/recency-granular matching is a
future refinement; the floor + the finding→need mapping refine with Priya. The needs migration (`93a861456e2f`)
renames `outstanding`→`pending`, adds `verified`/`rejected`, the new origins, and the disposition/reasoning/
source columns.

## ADR-178: AI needs reasoning — holistic propose-with-reasoning + confirm + improve (the differentiator)

- **Date:** 2026-06-19
- **Status:** Accepted

**Context:** The needs list's value is in proposing the RIGHT documents for a *specific* file — which is
inherently case-by-case and unenumerable (a static rule table can't cover "self-employed across two
businesses → two years of returns + a P&L; recently divorced with a support obligation → payment history;
gift from a relative → gift letter + sourcing"). LP-68 built the deterministic engine (states, matching, a
thin floor); LP-69 adds the intelligence — the highest-value, most distinctive capability in the product, and
the most Priya-dependent (the reasoning quality is her domain knowledge).

**Decision:** The needs list's intelligence is **AI reasoning over the WHOLE file** (the stated MISMO data +
the documents present + the findings + LP-67's suggestions) → **proposed** needs, each with **file-specific
reasoning** — holistic and file-scoped (contrast LP-67's findings-scoped *one finding → its implied need*).

- **The two guardrails (what makes AI-driven needs trustworthy).** (1) **Explainability** — every proposed
  need carries reasoning grounded in *this* file's data (not boilerplate); the parser **rejects** a proposal
  with no reasoning. (2) **Confirmation** — proposals are ingested as `disposition=PROPOSED` (NOT
  authoritative), `origin=ai_reasoning`, with the reasoning; the processor confirms/adjusts/dismisses (LP-70).
  The AI proposes (smart) but **never disposes** (the human controls).
- **Reconciliation — no duplication.** LP-69 is the *culminating* reasoner: it is told (and deterministically
  filters by) what's already covered — the floor (LP-68), LP-67's suggestions, the documents present, and the
  existing needs (incl. dismissed ones) — and proposes only what's NOT already there. It does not re-propose
  the floor's needs.
- **Two triggers, both through LP-68's per-file serialization.** (1) At **MISMO file creation**, reason over
  the stated data → the initial proposed needs (the "upload a MISMO → a tailored checklist appears" payoff —
  this **absorbs the deferred smart-needs-from-MISMO** from Phase 1.5). (2) **Re-proposed** as documents /
  findings arrive (the picture changed). Both run as needs-updates under the per-file Redis lock — no race.
- **Improves from corrections (V1: capture + simple use).** A processor's confirm/adjust/dismiss is captured
  as the **disposition on the need** (`confirm`/`adjust` → CONFIRMED; `dismiss` → DISMISSED + waived). The
  simple V1 *use*: the reasoning folds existing needs (incl. dismissed) into "already covered", so a dismissed
  proposal is **not re-proposed**. A richer corrections store + a full learning loop is a documented future
  evolution — V1 is the capture-mechanism + simple use, not sophisticated learning.
- **A sensible starter, refined with Priya (EMPHATIC).** The prompt encodes "reason like a loan processor"
  on a **sensible starter** understanding. The reasoning QUALITY is **the highest-value Priya input** ("walk
  me through a real file: what do you chase, and why?") and is sharpened by the correction signal. A real AI
  reasoning call (Sonnet, substantial context — cost + latency + eval apply). The assembled context carries
  PII and is **never logged** (counts only).

**Rationale:** required documents are case-by-case and unenumerable, so reasoning over the file (like a
processor) is the right mechanism, not a static table; the two guardrails make AI-driven needs trustworthy
(explainable + human-confirmed) — the AI is smart but not unilateral; reconciliation keeps the floor
(deterministic baseline) + LP-67 (findings-implications) + LP-69 (holistic) composing cleanly without
duplication; running at MISMO creation delivers the headline payoff and absorbs the deferred
smart-needs-from-MISMO.

**Accuracy — honestly scoped.** V1 proposes **reasoned, explainable, improvable** needs the processor
confirms — **NOT perfect out of the gate**. The quality improves via the correction signal + refinement with
Priya. Do not read the (mock-based) tests as proposal-quality validation — they verify the *mechanism* + the
*guardrails*; real-file quality is an ongoing, Priya-dependent effort.

**Consequences:** LP-70 builds the UI (the dashboard + the confirm/adjust/dismiss/waive flow + the reasoning
display — the disposition + reasoning groundwork supports it); the reasoning quality refines with Priya + the
correction loop; real AI cost/latency/eval; the re-reasoning on every document arrival is a cost to watch
(debouncing is a future optimization); Phase 3 acts on findings (cross-source) with the human in the loop.

## ADR-179: Needs-list dashboard — the self-maintaining checklist (reasoning surfaced; disposition flow; subtle updating, not a queue meter)

- **Date:** 2026-06-19
- **Status:** Accepted

**Context:** LP-68 built the needs ENGINE (states, satisfaction, per-file serialization, the thin
floor) and LP-69 the AI REASONING (holistic propose-with-reasoning + the correction-capture) — all
backend. The needs list is the product's highest-value differentiator, but its VALUE is only realized
in the UI: the processor's at-a-glance "what's outstanding, and why". LP-70 is that face — the first
major Phase-2 UI ticket and the screen most worth demoing to Priya.

**Decision:** The needs-list dashboard (on the loan-file overview) surfaces LP-68/69 as a
**self-maintaining checklist** — open the file → a tailored checklist appears (the MISMO floor + the
AI reasoning produce it; LP-70 displays it).

- **The five states made visual + action-oriented.** Each `status` carries a colored dot + pill and
  rolls up into one of four groups, rendered top-to-bottom: **Needs action** (pending / requested /
  rejected) → **In review** (received) → **Complete** (verified) → **Set aside** (waived). "What needs
  action" sits apart from "done" and "in flight" so the processor sees what to do next at a glance.
- **The AI reasoning surfaced — explainability made visible (the trust-making element).** Every need
  shows its LP-69 "why" ("Needs tax returns because the borrower has self-employment income…") in an
  inset note. This is what makes the AI proposals trustworthy/evaluable rather than a mysterious
  checklist — the distinctive element vs. a dumb checklist, and the signature of the screen.
- **The disposition flow — the AI proposes, the processor disposes (the human-in-the-loop guardrail,
  made interactive).** A PROPOSED need leads with a one-click **Confirm**; an overflow menu offers
  **Adjust** (edit), **Waive** (with a reason), and **Dismiss** (with a reason); a header control
  **Adds** a need the AI missed. Every action calls a tenant-scoped, **audited** write API and feeds
  LP-69's correction-capture (confirm/adjust → CONFIRMED; dismiss → DISMISSED + waived; add → a
  CONFIRMED manual need). The processor controls; the AI did the heavy lifting.
- **Live updates as documents arrive.** The dashboard reads the (already-polling) documents query to
  know when any document is in-flight and feeds that to the needs query as a `live` flag, so the list
  polls while a document processes and settles once it's done — a satisfied need visibly moves
  Pending → Received → Verified with no manual refresh. A backstop stops the poll if a pipeline stalls.
- **A subtle "updating" cue — NOT a queue-depth meter.** While the list is settling, a soft "Updating…"
  cue shows the OUTCOME (the list keeping current). It is deliberately **not** an "engine running" /
  "N files queued" indicator: the per-file serialization is a fast internal mechanism, not a
  user-facing batch job, so it stays invisible. (Per the prior decision.)
- **Tenant-scoped read + write APIs.** All routes nest under the loan file (the LP-29 file gate →
  `404` cross-company); a per-need action additionally `404`s a need not in the path file. The needs
  response carries only the need's own fields (titles / types / reasoning / the satisfying document's
  filename) — no raw borrower PII. Four new `activity_type` values audit the dispositions
  (confirm / adjust / dismiss / waive; add reuses `needs_item_created`).

**Rationale:** the needs list's value lives in the UI, so the dashboard is where the differentiator
becomes tangible; surfacing the reasoning makes the AI proposals trustworthy (explainable) and
evaluable; the disposition flow keeps the human in control and feeds the LP-69 improvement loop; the
action-oriented grouping answers "what do I do next?" at a glance; the subtle-updating-not-queue-meter
respects that the serialization is a fast internal mechanism, not a batch job to expose.

**Consequences:** LP-71 (document versioning / AI staleness) and LP-72 (the tier-aware document detail)
build the remaining Phase-2 UI; the dashboard is the screen most worth demoing to Priya, and the
disposition → correction signal matures with use + her input; Phase 3 adds cross-source rules to
"Verified". The old provisional `NeedsSection` (LP-34, the compact list) is replaced by this dashboard;
the needs read hook moved into its own data layer (`lib/api/needs.ts`) with live polling + the
disposition mutations.

## ADR-180: Floor seeds after a flush + AI-needs reasoning state is visible (LP-71.5)

- **Date:** 2026-06-24
- **Status:** Accepted

**Context:** A real MISMO import (employment income + self-employment + a gift + several assets,
Conventional Purchase) produced a needs list with only **"Purchase agreement"** — the deterministic
floor's purchase rule — instead of the expected rich list (pay stubs, W-2, tax returns, gift letter,
asset statements, …). A read-only diagnostic found two independent defects.

**Defect 1 — the floor's stated-data rules were dead-on-arrival in the import path.** The session runs
``autoflush=False`` (chosen so flush timing is explicit). In ``create_loan_file_from_mismo`` the stated
``StatedIncomeItem`` / ``StatedAsset`` rows were ``db.add``-ed but **not flushed** before
``seed_floor_needs`` ran. The floor's ``_has_stated_employment_income`` / ``_has_stated_assets`` run
SELECTs — which, with autoflush off and no preceding flush, **could not see the pending rows** → the
employment (→ pay stubs + W-2) and asset (→ bank statements) rules returned False. Only the purchase
rule fired, because it reads ``loan_file.loan_purpose`` (an in-memory attribute), not a query. (Proof:
imported files had the income/assets committed in the DB, yet only ``purchase_agreement`` was seeded;
the DB had **zero** ``ai_reasoning`` needs ever.)

**Defect 2 — the import silently "promised" AI needs.** LP-69's reasoning runs as an async Celery task
(enqueued after commit). With no worker running, the task sits in the queue and the AI needs never
appear — with **no signal** to the processor. And ``propose_needs`` swallows ``AIClientError`` → returns
``[]`` with only a warning log, so an AI failure also yields a floor-only list silently. In a
loan-processing tool, a short list silently presented as complete is a real safety gap (a processor may
not chase documents they actually need).

**Decision:**

- **Fix 1 (the bug):** ``seed_floor_needs`` now ``await db.flush()``es **first**, so it always sees a
  caller's just-added stated rows regardless of the session's autoflush setting. Placed inside the floor
  function (not just at the call site) so every caller is protected. The floor's **rules are unchanged** —
  they were correct; they just couldn't see the data. The deterministic floor now fires the
  employment/asset needs on import **independent of the AI/worker**.
- **Fix 2 (visibility, minimal):** a nullable ``ai_needs_status`` column on ``loan_files``
  (``pending`` / ``completed`` / ``failed``; NULL = not triggered). The MISMO import sets ``PENDING``
  (reasoning enqueued); the task entrypoint flips it to ``COMPLETED`` on a successful run; a swallowed
  ``AIClientError`` records ``FAILED`` (no longer silent). The needs dashboard surfaces it — "AI is still
  reviewing — more needs may appear" (pending) / "AI review didn't finish — this list may be incomplete"
  (failed) — so a floor-only list is **never silently presented as complete**. It is **informational,
  never blocking**: the import and the floor succeed regardless.

**Out of scope (operational):** the Celery worker not running is fixed by starting it
(``docker compose --profile worker up -d worker``), not by code. This ticket ensures (a) the floor works
without the worker and (b) the worker's absence/failure is visible, not silent.

**Consequences:** the deterministic floor is now reliable on import; the async AI reasoning's state is
legible end-to-end; existing files default to ``ai_needs_status = NULL`` (no backfill). A future, richer
"retry AI reasoning" affordance (vs. re-importing) and a fuller corrections/learning loop remain future
work (LP-69's noted evolution).

## ADR-181: Per-loop async Redis client for Celery tasks (LP-68 serialization-infra fix)

- **Date:** 2026-06-24
- **Status:** Accepted

**Context:** LP-68's per-file needs serialization uses a Redis lock
(``loan_file_needs_lock`` → ``get_redis_client()``). ``get_redis_client`` returned a
**process-global** ``redis.asyncio`` client whose connections bind to the event loop
that created them. Celery runs each task on a **fresh** loop (``run_async`` =
``asyncio.run`` per task — see :mod:`app.tasks.base`). So the first needs task created
the client on loop A; once loop A closed, every subsequent task (loop B, C, …) reused
that client and crashed with ``RuntimeError: Event loop is closed`` the moment it
touched the lock — **before** any need was created or status updated. The bug stayed
latent until the worker actually ran LP-69 needs tasks (the unit tests masked it with
a ``_loop_bound_redis`` fixture that hands out a per-loop client). The companion DB
path was already correct: ``task_session`` builds a **fresh engine per task loop** for
exactly this reason (asyncpg connections are loop-bound).

**Decision:** Make ``get_redis_client()`` **loop-aware** — cache the client keyed on
the running event loop and rebuild it when the loop changes. Under the API's single
long-lived loop the same client is reused (no behaviour change, connection reuse
preserved); under a Celery worker each per-task loop gets its own loop-local client,
so a client bound to a closed loop is never reused. This mirrors ``task_session``'s
per-loop engine — the Redis client now follows the same rule the DB engine already
did.

**Rationale:** keying the singleton on the loop is the minimal, root-cause fix; it
preserves the desired single-client reuse in the API while making the worker correct,
and it keeps the lock/redis call sites unchanged. Alternatives considered: a fresh
client per ``loan_file_needs_lock`` call (more churn, extra connects on a hot path) or
a synchronous redis client for the lock (diverges from the async-first stack).

**Consequences:** the per-file needs serialization (and any other async-Redis use)
now works under the worker's per-task loops; LP-69's AI reasoning tasks run to
completion (create the proposed needs + settle ``ai_needs_status``). A regression
test (``tests/core/test_redis_loop.py``) drives two ``asyncio.run`` loops and pings in
each — it reproduces the exact ``Event loop is closed`` crash without the fix. The
running worker image must be rebuilt to pick this up
(``docker compose --profile worker up -d --build worker``).

## ADR-182: The floor covers universal needs (borrower ID, per-borrower) — universal → floor, situation-specific → AI

- **Date:** 2026-06-24
- **Status:** Accepted

**Context:** A real MISMO import produced a needs list with no **borrower identification**
(driver's license / government ID) — a near-universal requirement on every loan file (lenders
verify identity per Patriot Act / KYC). The ID was expected to come from LP-69's AI reasoning,
but didn't: the AI reasons about what's *distinctive* about a file (self-employment → tax returns;
a gift → a gift letter), and a universal requirement like an ID is the **opposite** of distinctive,
so the AI under-proposes it (too "obvious" to surface as situation-specific). The floor (LP-68) had
only conditional rules (employment → pay stubs + W-2; assets → bank statements; purchase → purchase
agreement) and no universal baseline.

**Decision:** The deterministic floor (`seed_floor_needs`) now includes **universal needs** —
always-required on every file regardless of the borrower's situation — starting with a borrower
**Government ID**, seeded **per borrower** (co-borrowers each get their own ID need, the title +
`borrower_id` identifying which borrower; `needs_type=drivers_license`, the catalog's Tier-1 ID type).
The universal needs are a clearly separated, commented section (`_PER_BORROWER_UNIVERSAL` /
`_PER_FILE_UNIVERSAL`) so adding another always-required need is a one-line change. **The full
universal-needs list refines with Priya** — the ID is the first/clearest; she'll likely confirm
others (e.g. a credit authorization, certain disclosures).

**Rationale:** universal needs belong in the **floor**, not the AI:
- An ID is required on every file regardless of situation — it's *universal, not distinctive*, so the
  AI reasoning (which surfaces what's special about a file) may under-propose it. The right home for
  always-true needs is the deterministic floor.
- The floor being "thin" should not mean *missing its universal baseline* — thin means few
  conditional rules, but the always-true needs must be reliably present.
- The floor fires **immediately on import**, independent of the AI/worker (so the ID appears even
  when the worker is down, and even when the AI omits it). It reads the borrowers (visible post-flush,
  LP-71.5).
- **Per-borrower** because each borrower needs their own ID; **extensible** because Priya will name
  more universal needs.

**Division of labor (clarified):** **universal → floor** (deterministic, always-true); **situation-specific
→ AI** (LP-69, what's distinctive about the file).

**Consequences:** every imported file reliably gets a Government ID need per borrower from the floor;
the universal-needs list grows with Priya's input via a one-line addition; LP-63's `drivers_license`
extractor handles the ID once uploaded; the floor's conditional rules and LP-69's reasoning are
unchanged. (Manually-created files still get their template needs via the LP-30 setup path, not the
MISMO floor.)

## ADR-183: Document versioning (Model C) + date-driven staleness detection (LP-71)

- **Date:** 2026-06-25
- **Status:** Accepted

**Context:** Documents change over a file's life — a corrected statement supersedes an erroneous
one (versioning), and a document ages out of a lender's recency window (staleness). Both are about
document FRESHNESS over time and both feed whether a document belongs in the lender package. The needs
list and pipeline already existed; documents had only *extraction* versioning (re-extraction), not
*document* versioning.

**Decision (two paired capabilities):**

- **Versioning — Model C (the locked hybrid).** New uploads are NORMAL: each is CURRENT + standalone
  with **no replacement assumption** — multiples are normal (a set of pay stubs / months of statements
  are not replacements), so a same-type upload is never auto-treated as a replacement (no
  over-prompting). Replacement is **explicit**: the processor supersedes a specific (current) document
  with a new upload — the old → HISTORICAL (`is_current=False`), the new → CURRENT, BOTH kept for audit
  in a shared `version_group`, the new linked via `supersedes_document_id`, and the need the old
  satisfied **re-opens to re-evaluate** against the new current version (through the new document's
  pipeline, LP-68 serialized). **Gentle duplicate surfacing** is informational ("you have N other pay
  stubs", derived client-side), never a blocking prompt. An **email-ingested** document (which can't be
  click-replaced) carries a `possible_duplicate` flag for the processor to resolve (the mechanism; email
  ingestion is later).

- **Staleness — deterministic, date-driven (a threshold, like DTI).** Staleness is computed, not a new
  AI call: the AI's contribution is the *date extraction* (the Tier 1 extractors already capture pay
  date / statement period / ID expiration); the logic compares that date to a **configurable recency
  window** (pay stub ~30 days, bank statement ~60 days) or an **expiration** (ID / insurance past its
  date) → flagged with a reason. A superseded version (a newer one is current) is the versioning side of
  "a newer version exists". The processor RESOLVES a flag (replace / waive / accept — stored on the
  document); auto-resolution is **V2**. The recency windows are **sensible industry-standard starters —
  REFINE WITH PRIYA** (her lenders' [UWM, Sun-West] exact windows vary by program); they are a plain
  config dict (`RECENCY_WINDOWS` / `EXPIRATION_RULES`), so editing them is the whole knob.

- **Package fitness (groundwork).** Versioning (current vs. historical) + staleness (fresh vs. stale)
  combine into a document's fitness for the lender package: current + not-stale → fit; historical
  (superseded) or stale-unresolved → flagged (not silently included). The package itself is Phase 6 and
  the qualified status is partly LP-72 — this is the data.

- **Warnings are helpful, not blocking.** The UI surfaces version history ("v2 of N", the chain), the
  explicit Replace control, calm staleness warnings (the reason + resolve options), and the gentle
  duplicate hint — clear-but-calm; the processor decides.

**Rationale:** multiples are normal in mortgage files, so a same-type upload isn't a replacement —
explicit replace + gentle surfacing handles real replacement without false prompts; staleness as a
threshold fed by the AI-extracted dates keeps it deterministic + auditable ("AI extracts, deterministic
logic judges"); recency windows are domain knowledge (refine with Priya); surfacing both keeps
stale/superseded documents out of the package; helpful-not-blocking respects the processor's judgment.

**Consequences:** LP-72 builds the tier-aware detail + the qualified package status (using the
current/historical + staleness data); Phase 6 assembles the package from fit documents; the recency
windows refine with Priya; auto-resolution is V2; the `possible_duplicate` flag activates when email
ingestion is built. The main document list shows current versions only (historical reached via the
drawer's version history) so it stays uncluttered.

## ADR-184: Share the storage directory with the Dockerized Celery worker (host writes / worker reads)

- **Date:** 2026-06-25
- **Status:** Accepted

**Context:** Document processing (classify → extract) runs in the Celery worker, which reads the uploaded
file's bytes from the storage backend. In local dev the API runs on the **host** and writes uploads to
`STORAGE_LOCAL_PATH=./storage` → the host's `backend/storage`. The worker runs in **Docker** (`build:
./backend`, WORKDIR `/app`), so its `./storage` resolves to `/app/storage` **inside the container**. The
worker service had no volume for storage, so `/app/storage` was empty: every document failed at the
file-read step with `StorageError` (`backend/app/storage/local.py:70`) — ~0.03s, before classification, so
`document_type` stayed NULL and all documents failed uniformly. (Not a code regression; surfaced when the
worker moved into Docker during LP-71.x verification. AI-reasoning tasks were unaffected because they read
only the DB, never a file.)

**Decision:** Mount the host's `backend/storage` into the worker container at the path it resolves
`./storage` to: `volumes: ["./backend/storage:/app/storage"]` on the `worker` service. The host API and the
Docker worker then share one storage root. Only the worker needs the mount (the API is on the host and sees
`backend/storage` directly).

**Rationale / trap:** the **relative** `./storage` is the underlying trap — it resolves to different real
directories on the host (`backend/storage`) vs. in the container (`/app/storage`). The minimal local-dev fix
is the shared mount. An absolute `STORAGE_LOCAL_PATH` + the shared mount, or **object storage (S3/MinIO —
already supported via `storage_backend`)** so host + worker share a *network* store, is the robust
production-correct direction (Phase 7) — not implemented now.

**Consequences:** Dockerized document processing reads the uploaded files; classify/extract/needs work
end-to-end (verified: a previously-failed pay stub reprocessed → `completed`, extracted, need satisfied).
Already-failed documents don't auto-retry — re-upload (or reprocess) after the fix. The pipeline /
extractors / LP-71 code are unchanged (purely infra/config).

## ADR-185: Tier-aware document detail + standard naming + package-qualification groundwork (LP-72)

- **Date:** 2026-06-25
- **Status:** Accepted

**Context:** The tier model (LP-58..66) scales document handling — Tier 1 (full structured extraction),
Tier 2 (recognize + summarize), Tier 3 (generic analysis). LP-71 added the freshness signals (current /
fresh). The last Phase-2 feature ticket surfaces all of it in the UI and adds the two pieces that make a
document **package-ready**: a consistent name and a computed fitness. (Surfaces existing work — no
re-extraction, no package assembly.)

**Decision (three pieces):**

- **Tier-aware document detail.** The detail view ADAPTS to the document's tier — the proportional-investment
  philosophy made visible: **Tier 1** → the structured extracted fields (deep, type-specific); **Tier 2** →
  the recognition summary + category (light); **Tier 3** → the generic analyzer's findings (parties / dates /
  amounts / findings) + summary (flexible). It extends the LP-43 drawer (branches on `tier`), not a rebuild;
  pending/failed states degrade gracefully; PII stays masked.

- **Standard naming.** A derived `{Type}_{KeyIdentifier}_{Date}` display name (no spaces) from the type +
  extracted data (e.g. `Pay-Stub_Thermofisher-PPD_2026-05-22`, `Bank-Statement_Bank-of-America_2026-04-30`),
  with a sensible `{Type}_{UploadDate}` fallback for sparse data (Tier 2/3 / extraction pending / missing
  identifier). It is a **display/derived** name — the stored file is untouched. Only non-PII fields feed it
  (never SSN / account number / DOB). Per-type rules are a plain config (`app/documents/naming.py`); they
  refine with use / Priya.

- **Package-qualification groundwork.** Each document computes a `package_qualification`: **qualified** =
  CURRENT (LP-71 versioning) + FRESH (LP-71 staleness) + TYPED (recognized) + EXTRACTED (processing succeeded,
  terminal `COMPLETED`). It consumes LP-71's signals + the extraction state and reports the first failing
  criterion (superseded / stale / untyped / not_extracted). **Groundwork** — LP-72 makes each document KNOW
  its readiness; **Phase 6** assembles the package from qualified documents. A subtle "Package-ready"
  indicator surfaces it (informational), but nothing assembles/renders a package.

**Rationale:** the tier model's value is realized when the detail shows the appropriate depth per tier; a
derived consistent name makes lists scannable and the eventual lender package professionally named
(underwriters expect consistent naming — a package of `scan1.pdf` is unprofessional); qualification consumes
LP-71's current/fresh signals so Phase 6 can filter to qualified documents — LP-72 lays the groundwork
without building the package.

**Consequences:** LP-73 closes Phase 2 (testing/hardening). Phase 6 assembles the lender package from
package-qualified documents (filtering on the qualification LP-72 computes) using the standard naming. Phase 3
adds cross-source verification. The naming convention + qualification rules refine with Priya / use. The
standard name is display-only (the stored file is never renamed).

## ADR-186: Operational robustness — worker by default + bounded-retry with a visible terminal-failed (LP-73)

- **Date:** 2026-06-26
- **Status:** Accepted

**Context:** Two Phase-2 footguns were operational, not logical: (1) the Celery **worker was
behind a Docker Compose profile**, so a normal `docker compose up` left it OFF — the async/AI
features (document processing, the AI needs reasoning) silently did nothing, and it was hard to
diagnose. (2) A **transient task failure** (a DB/Redis blip, an AI timeout) had **no retry** — it left
the file permanently in a non-terminal state with no signal (the "stuck pending" case, LF-VNC4).

**Decision:**

- **Worker by default.** The `worker` service no longer has a `profiles:` gate — `docker compose up -d`
  brings it up. Async/AI features can't silently break because no worker is consuming. (Rebuild after a
  code change: `docker compose up -d --build worker`.)
- **Bounded retry with a visible terminal-failed.** A shared `retry_or_terminal` (`app/tasks/retry.py`)
  wraps the needs + document tasks: on a transient error it retries up to `MAX_RETRIES` (3) with capped
  exponential backoff (5/10/20s…); on **exhaustion** it records a **visible terminal-failed state**
  (`ai_needs_status=FAILED` for needs, `status=FAILED` for documents — consistent with LP-71.5's
  visibility) and the task fails — **never a silent permanent pending**. A scheduled `Retry` propagates
  untouched (not double-handled).

**Rationale:** a worker that's off by default is a recurring diagnosis trap; making it default removes
the footgun. A transient blip shouldn't strand a file, and an exhausted failure must be *visible* (the
phase already learned that silence is the enemy). The document pipeline already reaches its own terminal
status internally, so the retry there guards the infra *around* it; the needs tasks are where the
stuck-pending actually occurred.

**Consequences:** the full stack comes up with one command; transient failures self-heal; permanent
failures are visible and (per LP-71.5) surfaced in the UI. The retry counts/backoff are sensible
starters — tune with real task latencies.

## ADR-187: Real-stack integration testing + de-patched concurrency test + consistent dev model (LP-73)

- **Date:** 2026-06-26
- **Status:** Accepted

**Context:** Phase 2 shipped four bugs that **all passed unit tests and broke on the real stack** — a
flush-timing bug (the floor couldn't see stated data), a Redis per-loop event-loop crash (every worker
task died), a silent AI-failure swallow (a floor-only needs list looked complete), and a host/worker
**storage split** (the Docker worker couldn't read host-written files). Every one lived in a **seam
between components** and was invisible to mocked-component unit tests.

**Decision:**

- **Real-stack integration tests that exercise the seams.** `tests/integration/test_phase2_real_stack.py`
  drives the REAL storage backend (an actual write **then** read — the storage-split catcher), the real
  DB, the real pipeline orchestration, and the real needs-satisfaction matching — mocking **only the AI
  model boundary** (classify / extract / summarize / analyze). It covers Tier 1/2/3 processing, a
  missing-file → graceful FAILED, the upload → satisfies-need seam, and the MISMO → floor + AI-reasoning
  seam. A consolidated **tenant-isolation sweep** (`test_phase2_tenant_isolation.py`) asserts every
  Phase-2 endpoint 404s cross-company.
- **De-patched the LP-68 concurrency test.** It used to monkeypatch a fresh per-loop Redis client — which
  is exactly what *hid* the per-loop bug. It now runs against the **real loop-aware `get_redis_client`**
  (resetting the module singleton around the test), so a regression of the loop fix surfaces here; the
  cross-loop regression itself is guarded by `tests/core/test_redis_loop.py`.
- **One consistent local-dev model: all-in-Docker with a shared storage volume.** The host-API /
  Docker-worker split caused the storage bug; the chosen model is the worker in Docker (now default)
  sharing `backend/storage` via the volume mount (the storage fix). Documented in
  `docs/development-workflow.md`. **The S3 storage backend is NOT yet implemented** (`get_storage_backend`
  raises for `"s3"`) — it's **Phase-7** work; validating it against MinIO is deferred with it (no
  overclaim that the production storage path is tested).

**Rationale:** the phase's lesson is that green unit tests are not enough when the bugs live in the
seams; the integration tests must exercise the assembled system, mocking only the model boundary. The
de-patched test removes the fixture that masked a real bug. Resolving the dev-model asymmetry removes the
storage footgun's root.

**Consequences:** the seams are now under test; future seam regressions (storage, loop, flush, silent
failure) are far more likely to be caught in CI. The S3 backend + its MinIO validation are honestly
deferred to Phase 7.

## ADR-188: Verification rule engine — uniform structure, three-layer composition, deterministic evaluation (LP-74)

- **Date:** 2026-06-27
- **Status:** Accepted

**Context:** Phase 3 builds the verification engine. The *first* ticket is the engine itself — the
mechanism before the ~60 Conventional + ~50 FHA rule content (LP-82..85), mirroring LP-68's
"engine before content". The structural decisions here determine whether the rest of Phase 3
(overlays, calculators, the aggression dial, the findings) compose cleanly or require an impossible
retrofit. Verification rules come from three sources that must **compose**: regulatory (Layer 1, all
loans), investor (Layer 2, per program — Fannie for Conventional, HUD for FHA), and lender overlay
(Layer 3, per lender).

**Decision:**

- **One uniform rule structure for all three layers**, carrying a **stable `rule_id`** (e.g.
  `conv.dti.back_end_max`), a `layer`, an `applicability` (all_loans / program / lender), the typed
  `reads` field path(s), a **threshold-as-data** `condition` (`{op, value, unit}`), a `severity`
  (red/yellow), a finding `category`, a `description`, and a structured `source` citation. Rules are
  **definitions** (config-like, declared in code, seedable), not per-file rows.
- **The two linchpins are airtight.** (1) Every rule has a **stable `rule_id`** — overlays reference
  rules *by id*. (2) The **threshold is data** the fixed logic reads, never hardcoded — so an overlay
  can supply a different value and the *same* `satisfies()` evaluates against it. Rule **logic is
  fixed; thresholds are data**.
- **Three-layer composition resolves a flat effective set per file.** Base = all regulatory rules +
  the investor rules for the file's program (Conventional **or** FHA, never both). Patch with the
  lender's overlay applied as a **diff**: an override replaces the base rule's threshold *by `rule_id`*
  (identity/logic unchanged — only the `condition`); a custom rule is appended. **The investor rule is
  the default** — un-overridden rules fall through; no overlay → all investor defaults. Overlays are
  **diffs, not full per-lender copies** (small, maintainable, auditable).
- **Evaluation is deterministic.** For each rule in the effective set: read the file's typed field →
  compare to the (possibly overlay-patched) threshold → emit a pass/fail finding. **No AI** (the AI's
  role is upstream extraction); the handoff is **structured data** — rules read typed fields, never
  prose. A datum the file does not carry yet → the rule is *not evaluated* (the engine never invents a
  verdict). The pure engine takes a `FileFacts` snapshot; the DB-facing service builds facts, resolves
  rules, evaluates, and persists — per file, **tenant-scoped** (loan_file → company).
- **Two generators, one findings model.** The engine emits into the shared LP-66 `Finding` model in a
  **uniform shape** (rule_id, observed value, severity-derived status, the condition, structured
  source, source-location placeholder, reasoning), marked with a new minimal `origin` field
  (`deterministic_rule`). The Phase-3 AI cross-source layer (LP-78) feeds the **same** model as
  `ai_cross_source`. The findings path is **not** engine-exclusive. LP-75 does the fuller findings-model
  extension (confidence / resolution / blocking / source-location); `origin` is the minimal field
  needed to emit in the uniform shape now.
- **Built and proven with SAMPLE rules + a SAMPLE overlay.** A regulatory AML rule, Conventional/FHA
  DTI caps, a pay-stub-recency rule, and a sample lender overlay (overriding the Conventional DTI to 45
  and adding a reserves custom rule). The overlay-patched threshold (45) produces a finding where the
  investor default (50) would not — proving the patch reaches evaluation. The real content is LP-82..85;
  the real overlays LP-80.

**Rationale:** the rule structure determines whether all of Phase 3 composes. Stable ids let overlays
*reference* rules; thresholds-as-data let overlays *override* them — so an overlay is a clean patch, not
a retrofit. Investor-default + overlay-as-diff keeps overlays small, visible, and maintainable.
Deterministic evaluation is what makes verification **auditable and defensible** — a threshold check is
correct by construction, not "probably right per the AI" (the locked "AI surfaces, deterministic code
judges" principle). The two-generator accommodation lets LP-78's AI findings share the model without a
later migration of the engine's emit path. Engine-before-content (sample rules) mirrors LP-68: a solid,
tested mechanism first; the domain content later.

**Consequences:** LP-75 extends the findings model (confidence / resolution / blocking /
source-location); LP-76/77 add the transparent DTI/LTV calculators (and the real fact computations the
engine's `build_file_facts` currently stubs as sample calcs); LP-78 adds the AI cross-source layer
(feeding the shared model) + the APPLY → recompute loop; LP-79 the aggression dial; LP-80 the real UWM /
Sun-West overlays (via this mechanism); LP-82..85 the real rule content (via this engine, promoting
typed-core fields as rules need them). The engine is per-file (shared definitions, per-file runs).

## ADR-189: Findings model extension — confidence, resolution, blocking, source location (the uniform verification finding) (LP-75)

- **Date:** 2026-06-27
- **Status:** Accepted

**Context:** LP-74 built the deterministic rule engine, emitting into the LP-66 `Finding` model. The
locked Phase-3 architecture rests on **one** findings model that *both* generators (LP-74
deterministic, LP-78 AI cross-source) feed and the human resolves *uniformly* — plus the Phase-2
document findings (LP-66). LP-75 turns that model into the full verification finding by adding the four
dimensions verification needs, **extending** the existing model rather than forking it.

**Decision:**

- **Extend the LP-66 `Finding`, do not build a new model.** Add four dimensions in place:
  - **Confidence** (`confidence: float` in [0, 1], DB CHECK) — how sure the system is the finding is
    real; the **aggression dial**'s substrate (LP-79) and the blocking input. Deterministic threshold
    findings are **certain** (`DETERMINISTIC_CONFIDENCE = 1.0` — the math is exact); AI cross-source
    findings (LP-78) **vary**. Defaults to 1.0 so a finding without an explicit value reads as trusted.
  - **Resolution states** — extend the existing `FindingResolutionStatus` with **APPLIED** and
    **OVERRIDDEN** (the two verification resolutions) alongside the default **OPEN**. APPLIED
    *incorporates the finding into the structured data*; OVERRIDDEN *dismisses it with a recorded
    reason* (reused `resolution_note`, required, enforced in the service). The legacy LP-17 states
    (RESOLVED / ACCEPTED_RISK / WAIVED) remain for the document-finding flow; any non-OPEN state is
    *resolved* for blocking. **No finding is silently ignored** — every one is applied or
    overridden-with-reason, and the resolution is activity-logged.
  - **Blocking** — a computation (`is_file_blocked`): a file is blocked from *ready to submit* while it
    has any **open in-scope** finding, where *in-scope* = an actionable (red/yellow) open finding whose
    **confidence ≥ the active cutoff**. LP-75 owns the computation and a standalone Balanced default;
    **LP-79's dial sets the cutoff**. Wired into the ready-to-submit transition (a 409 at the endpoint);
    green findings (passes) never block.
  - **Source location** — `source_page` + `source_snippet` (a page number + a **verbatim** snippet):
    the trust/audit anchor (click a finding → the exact document line), building on extraction's
    per-field source. Bounding-box highlighting deferred; page + snippet is V1.
- **One uniform shape across all three generators.** `FindingOrigin` gains `DOCUMENT_ANALYSIS`, so
  deterministic_rule / ai_cross_source / document_analysis findings share **one** shape — type,
  amount, source document, page, snippet, confidence, reasoning, severity (`status`), resolution, and
  the origin provenance marker. The dial, the UI (LP-81), and the resolution flow treat findings
  **uniformly** — they don't care *how* a finding was generated. "Two generators, one findings model"
  made concrete in the data. The LP-74 engine now emits in this full shape (certain confidence + source
  location).
- **APPLY → recompute hook.** APPLYING a finding *changes the structured data* (e.g. an undisclosed
  obligation is **added to liabilities**) — the trigger point of the AI↔deterministic interlock. LP-75
  builds the hook: `apply_finding` performs the structured-data change (the canonical `add_liability`
  case), records it on `applied_record`, and calls `mark_recompute_needed` (the explicit seam). The
  **full** recompute loop is LP-78 (cross-source + the loop) + the calculators (LP-76/77); the
  observable signal today is the structured-data change itself.

**Rationale:** the locked architecture is one findings model both generators feed and the human
resolves uniformly — so *extend* the uniform-feedstock model, never fork it. Confidence is the dial's
substrate; the two resolutions + no-silent-ignore make findings blocking and auditable;
APPLIED-incorporates-into-structured-data is the interlock that lets an AI-surfaced correction feed the
deterministic recompute (the human-in-the-loop loop); source location is the trust mechanism. Reusing
`resolution_note` for the override reason and the existing `resolution_status` enum (rather than a
parallel resolution field) honours "extend, don't duplicate".

**Consequences:** LP-79 builds the aggression dial (filters on confidence; gates display + blocking;
records the active level at submission); LP-81 the findings UI + resolution flow; LP-78 the AI
cross-source generator (feeding this model) + the full APPLY→recompute loop; LP-76/77 the DTI/LTV
calculators (recompute on applied changes; the unresolved-findings alert). Bounding-box highlighting is
deferred (page + snippet is V1).

## ADR-190: DTI calculator — transparent, auto-populated, override-able, deterministic, findings-coupled (LP-76)

- **Date:** 2026-06-28
- **Status:** Accepted

**Context:** DTI (debt-to-income) is THE mortgage-qualification number and the sister's most acute
ChatGPT pain — a black box she can't fully trust, with no auto-population (she re-enters everything) and
no audit trail. LP-76 is the headline "replace ChatGPT" win of Phase 3: it must beat ChatGPT on
transparency, auto-population, and trustworthiness.

**Decision:**

- **Pure deterministic math, fully broken down.** Front-end DTI = housing ÷ income; back-end DTI =
  (housing + monthly debts) ÷ income. Computed in a pure module (`app/verification/dti.py`) — **no AI**;
  the monthly principal+interest is amortized from the loan terms (it is not stored). The response is
  **fully itemized**: every income line, every housing component (PITI + MI + HOA), and every debt, each
  with its auto value, any override, the effective value, and a source tag — plus the **explicit
  formula**. The transparency *is* the feature; a black-box DTI is untrustworthy, one that shows every
  input and the formula is trustworthy. Money is `Decimal`; ratios round half-up to 2 dp.
- **Program limits side-by-side, the effective limit.** The computed back-end DTI is shown against the
  **effective** limit for the file's program + lender — LP-74's investor rule (Conv 50 / FHA 57)
  patched by any lender overlay (e.g. the sample overlay's 45), via the same registry the rules engine
  uses — with a pass/over status. The number alone is meaningless; the number against the limit is the
  answer.
- **Auto-populated from the structured data.** The calculator opens **already filled** — income from
  stated income, debts from stated liabilities, P&I computed from the loan terms, taxes / insurance /
  HOA from the current document extractions. It reads the *same* structured data the rules engine
  evaluates. Review + adjust, not enter from scratch (the "better than ChatGPT").
- **Override any field, with an audit log.** A `DtiOverride` row (one per `(file, field_key)`, unique;
  clearing soft-deletes) holds the override amount; the override **takes precedence** over the auto
  value and **persists**. Every set/clear is audited (`ActivityType.DTI_OVERRIDDEN`, with the prior
  value, by whom). The auto values are a trustworthy starting point, not a cage.
- **Real-time recalculation.** The override endpoints return the **recomputed** calculation in the
  response, so the UI updates from one round-trip (the mutation primes the query cache).
- **Coupled to findings (LP-75).** (1) The **unresolved-findings alert**: the calculation queries open
  in-scope findings (LP-75's `open_in_scope_findings`, Balanced default) and warns when the numbers may
  be incomplete. (2) **Recompute on applied findings**: because the calculation reads the structured
  data live, applying a finding (LP-75's hook adds a liability) makes the next calculation recompute
  higher — LP-76 is a recompute consumer of the apply hook (the AI↔deterministic interlock landing in
  the calculator).

**Rationale:** the value is transparency (every input + the formula visible) + auto-population (no
re-entry) + deterministic correctness (correct by construction, not "probably right per the AI"). The
findings coupling realizes the interlock at the calculator — AI surfaces an obligation → human applies →
it changes the structured data → the DTI recomputes — and warns when open findings might make the calc
incomplete. Override-with-audit keeps the human in control and the file defensible.

**Consequences:** LP-77 builds the LTV calculator on the same model (auto-populate → itemize →
deterministic compute → override-with-audit); LP-79's dial sets the in-scope cutoff the alert (and
blocking) use; LP-81's verification tab surfaces the calculator prominently (it already lives there);
LP-82/83 encode the real DTI rules (the calculator computes DTI; the rules judge it — shown as the
limit); the effective limit reflects overlays today; the other calculators (MI / self-employed income /
reserves / max loan) are LP-87. Housing taxes/insurance/HOA are read from document extractions when
present and are override-able otherwise (no dedicated property fields yet).

## ADR-191: LTV calculator — LTV/CLTV/HCLTV, refinance-aware, reusing the DTI calculator model (LP-77)

- **Date:** 2026-06-28
- **Status:** Accepted

**Context:** LTV (loan-to-value) is the second qualification pillar — where DTI asks "can the borrower
afford the payment?", LTV asks "how much equity is in the deal?" (the lender's risk exposure). The
vertical slice needs both. LP-76 proved a transparent / auto-populated / override-able / findings-coupled
/ deterministic calculator; LP-77 applies that model to LTV, with the LTV-specific substance done
correctly.

**Decision:**

- **Reuse LP-76's calculator model, applied to LTV.** Same transparent itemized breakdown + explicit
  formulas, auto-population from the structured data, per-field override with an audit log, real-time
  recalc (the override endpoints return the recomputed result), the findings coupling (unresolved-findings
  alert + recompute-consumer), and pure deterministic math. The framework is reuse; the new substance is
  the three ratios + refinance handling. A parallel `LtvOverride` table + `ltv_overridden` activity type
  mirror the DTI ones (rather than disturbing LP-76).
- **Three deterministic ratios, the subtleties correct + made visible.**
  - **LTV = first loan ÷ the LESSER OF** purchase price and appraised value (for a purchase) — the lender
    won't lend against a price above the appraisal. The basis (and which value won) is shown explicitly.
  - **CLTV = (first + second + HELOC drawn balance) ÷ value.**
  - **HCLTV = (first + second + HELOC CREDIT LIMIT) ÷ value** — the most conservative measure: a $0-balance
    HELOC with a $100k line could be drawn tomorrow, so the full line counts. These two subtleties
    (lesser-of, credit-limit-not-balance) are the trust mechanism — exactly what a processor wants verified
    and what ChatGPT fumbles.
- **Refinance-aware.** The loan purpose drives the denominator **and** the limit: a purchase uses the
  lesser-of; a rate/term refinance uses the appraised value (no purchase price); a cash-out refinance uses
  the appraised value with a **stricter** limit. A nullable `refinance_type` (rate_term / cash_out) on the
  loan file carries the cash-out distinction.
- **Program limits side-by-side, the effective + purpose-varying limit.** Sample LTV rules
  (`conv/fha.ltv.purchase_max`, `conv/fha.ltv.cash_out_max`) are added to LP-74's registry; the calculator
  selects the rule matching the program + purpose and reads the effective threshold (overlay-patchable),
  with a pass/over status. (Real limits are LP-82/83; these are samples like LP-74's.)
- **The appraised value is graceful.** It auto-populates from the MISMO valuation (else the estimated
  value) and is **override-able** where neither is present — the appraisal isn't a Tier-1 extraction yet,
  so the override is the graceful fallback. The appraisal is **not** promoted to Tier 1 here.

**Rationale:** LTV's correctness subtleties (lesser-of, credit-limit) are precisely what a deterministic
tool should nail; refinance-awareness is required because the denominator and limit depend on the loan
purpose. Reusing LP-76's model keeps the two calculators consistent and trustworthy rather than
reinventing — the processor learns one interaction and trusts both.

**Consequences:** LP-79's dial sets the in-scope cutoff the alert uses; LP-81's verification tab surfaces
both calculators (they already live there, side-by-side); LP-82/83 encode the real LTV rules (the
calculator shows the limits; the rules judge); the appraisal may be promoted to Tier 1 later (its value
feeds LTV); the other calculators (MI / self-employed / reserves / max loan) are LP-87. The sample LTV
rules carry `reads` paths with no engine fact yet, so the rule engine skips them (the calculator resolves
the limit directly) — they wire up with the real rules.

## ADR-192: AI cross-source layer — one general capability, structured findings, the APPLY→recompute loop (LP-78)

- **Date:** 2026-06-28
- **Status:** Accepted

**Context:** LP-74 built the deterministic *judge* (rules evaluate thresholds). The "AI surfaces" half of
the locked two-layer principle was still missing — the capability that reads the borrower's stated
claims (MISMO) against what the documents prove and surfaces discrepancies, including ones no
pre-written rule would catch. LP-78 adds that *perceiver* and closes the APPLY→recompute loop that
LP-75's hook + LP-76/77's calculators set up.

**Decision:**

- **One general AI capability, not a rule per check.** The cross-source layer (`app/ai/cross_source.py`)
  is a single open-ended perception task: the AI reads the stated data vs. the verified document
  extractions and surfaces whatever "doesn't line up" — guided toward high-value comparisons (income
  variance >10%, employer, gift) but **not limited** to them. Because it reads and compares, it catches
  **known and novel** discrepancies alike — the undisclosed obligation in a divorce decree that no rule
  was written for. The starter set is **prompt guidance**; the full ~15-20 is LP-86.
- **Structured findings only.** The AI emits **typed** findings (type, amounts, source document + page +
  snippet, confidence, reasoning) — never prose the deterministic layer interprets. They enter LP-75's
  **shared, uniform** Finding model with `origin=ai_cross_source` — *generator two* of "two generators,
  one findings model" (LP-74 was generator one). Parsing is defensive (a malformed response yields no
  findings — nothing invented).
- **AI fallibility is acceptable.** Findings are **for human review**, confidence-scored — the AI
  *surfaces candidates*, it does not decide. They land **OPEN**, never auto-applied. A miss is backstopped
  by the processor; a false flag is overridden with a reason.
- **The APPLY→recompute loop closes.** For recognized remediable types the emit attaches an **apply
  spec**; applying a finding (LP-75's hook) changes the structured data → the DTI/LTV calculators
  (LP-76/77), which read the data live, recompute. The interlock works end-to-end: an undisclosed
  obligation → apply → added to liabilities → the DTI recomputes **higher**; an income variance → apply →
  the stated income corrected (lower) → the DTI recomputes **higher**. LP-78 extends the apply hook with
  `correct_income` and makes `mark_recompute_needed` mark verification stale (applying changed the data).
- **Manual trigger + staleness.** The pass runs on a **manual trigger** (a "Run verification" button →
  the worker runs the AI call) — cross-source compares two sides (meaningful only when both are
  assembled) and is an AI cost, so it runs deliberately. A `verification_stale` flag is set on any
  document change (upload / type override / replace) and when a finding is applied, and cleared when the
  pass re-runs — a visible "re-run" indicator. **Auto-re-run is deferred** (the dial re-filters
  already-computed findings without re-running — LP-79).

**Rationale:** required-document discrepancies are open-ended and unenumerable — a general AI
read-and-compare catches what pre-written rules can't. Structured-findings-only keeps the AI's fuzzy
perception contained as typed data the deterministic layer consumes cleanly (the handoff is structure,
never prose). AI fallibility is acceptable precisely because findings are human-reviewed, not decisions.
The APPLY→recompute loop is the system's core interlock — AI perception → human confirmation →
deterministic recomputation. Manual-trigger + staleness matches that cross-source needs both sides
assembled and is a real AI cost (a Sonnet pass over substantial context).

**Consequences:** LP-79's dial filters these confidence-scored findings by thoroughness (re-filtering
without re-running); LP-81 builds the rich findings UI + resolution flow (this ships a minimal trigger +
staleness panel with a read-only findings list); LP-86 adds the full ~15-20 cross-source set (this
capability, more guidance). The recompute lands in LP-76/77; auto-re-run and bounding-box source
highlighting are later phases. PII is assembled for the AI call and **never logged** (counts/tokens
only); the worker must be running for the pass to execute.

## ADR-193: Cross-source result caching by input fingerprint (LP-78.1)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** "Run verification" (LP-78) re-ran the AI cross-source pass every click, even on an
unchanged file. Because the pass is an open-ended AI task (non-deterministic even at temperature 0), the
processor saw the *same* discrepancies described and counted slightly differently each run — which erodes
trust ("the tool can't even agree with itself") and wastes AI cost/latency. This is the back half of the
staleness model: the front half (LP-78) marks verification STALE when documents change; this adds the
complement — when *not* changed, don't re-ask the AI.

**Decision:**

- **Input fingerprint.** Compute a stable SHA-256 over the verification *inputs* — the assembled
  stated-vs-verified context (stated income/assets/liabilities/employers/borrowers + loan/property core,
  and the current document extractions' values). Canonical serialization: dict keys sorted and **lists
  sorted by their canonical form**, so row order does not change the hash; the hash is over the compared
  substance (no timestamps / run ids). Same inputs → same fingerprint; any value change → a new
  fingerprint.
- **Store it on the completed run.** `verifications.input_fingerprint` is set when a cross-source pass
  completes, alongside the findings.
- **Cache on trigger.** "Run verification" computes the *current* input fingerprint (a cheap DB read, no
  AI) and compares it to the last completed run's stored fingerprint. **Match** → return that run's
  cached findings, **no AI call** (instant, free, byte-identical — the same stored rows). **Differ** →
  create a RUNNING run and enqueue the AI pass (there is genuinely new data to compare), which stores the
  new findings + the new fingerprint.
- **Reconciled with staleness.** The fingerprint is the precise mechanism behind "changed": a document
  change (which marks STALE) changes the fingerprint, so stale ⇔ fingerprint differs. On a cached return
  with a matching fingerprint the stale flag is cleared (matching inputs ⇒ not stale), so the two never
  disagree.
- **Force-rerun escape hatch.** `POST …/verification/run?force=true` (a "Re-run anyway" affordance)
  bypasses the cache and re-runs the AI even on unchanged inputs — available but not the default.

**Rationale:** the fix is not to make the AI deterministic (impossible for an open-ended perception task)
but to **stop re-asking it when there is nothing new to compare**. Fingerprinting the exact compared
substance makes "unchanged" precise and order-independent; returning the stored findings is identical by
construction. This eliminates the "click repeatedly, get different results" problem at the source and
removes wasted AI cost/latency on unchanged files.

**Consequences:** this is a caching layer in front of the existing pass — the cross-source capability and
the findings model are unchanged. A re-run still happens automatically when inputs change (a document
added/changed, stated data edited) or when forced. LP-79's dial still re-filters already-computed
findings without re-running. The fingerprint hashes a hash, not raw PII beyond what the findings already
hold; the assembled context is never logged.

## ADR-194: Aggression dial — confidence-threshold gating (display + blocking), instant re-filter, per-file + user default (LP-79)

- **Date:** 2026-06-28
- **Status:** Accepted

**Context:** LP-78 produces all cross-source findings in one (expensive, non-deterministic) AI pass, each
carrying a **confidence** (LP-75); the blocking computation already takes a confidence cutoff. Processors
need to control *how thorough* verification is — a clean refinance wants only high-signal findings, a
tricky file wants every hunch surfaced — without paying for (or waiting on) another AI run, and without
the system silently re-deciding what blocks. The cutoff levels (Conservative 0.8 / Balanced 0.5 / Thorough
0.0) and the cutoff-taking blocking computation shipped with LP-74/75; LP-79 supplies the cutoff via a
dial and wires it into the read path.

**Decision:**

- **Three levels = confidence cutoffs.** Conservative (0.8, high bar — only findings the system is very
  sure about), Balanced (0.5, the default), Thorough (0.0, almost everything incl. low-confidence hunches).
  A finding is **in-scope** at/above the active cutoff. The values are config (`CONFIDENCE_CUTOFFS`), tunable
  over use. Deterministic findings (confidence 1.0) are in-scope at every level.
- **The cutoff gates BOTH display AND blocking.** Below the cutoff → hidden *and* non-blocking; at/above →
  shown *and* (if open) must be resolved to submit. LP-79 supplies the active cutoff to LP-75's blocking
  computation (`is_file_blocked` / `open_in_scope_findings`) and to the DTI/LTV calculators' unresolved-
  findings alert. "Resolve all" therefore means "resolve all **at the chosen thoroughness**" — a more
  thorough setting surfaces *and requires resolving* more findings.
- **Never recolors.** The dial filters by **confidence**, never **severity**. A finding's red/yellow is
  intrinsic (set by the rule/generator) and unchanged by the dial; the dial only changes which findings are
  in scope. Confidence (how-sure) and severity (how-bad) are orthogonal axes, kept separate.
- **Instant re-filter, no AI re-run.** The dial is a **read-time view filter** over LP-78's already-stored
  findings. Changing it (`PUT …/verification/aggression`) re-filters instantly — it never enqueues the
  cross-source AI and incurs no cost. One expensive pass; free thoroughness adjustment.
- **Per-file + user default + per-file override.** `users.default_aggression_level` is the user's general
  preference; `loan_files.aggression_level_override` (null = use the default) dials a specific file up/down.
  The active level = the override if set, else the user default.
- **Recorded at submission.** On the (gated) transition into `READY_TO_SUBMIT` the active level is recorded
  on `loan_files.submitted_aggression_level` — "cleared at <level> thoroughness" — so the clearance is
  honest and auditable (clear is relative to thoroughness).
- **The legible consequence.** Moving the dial can flip a file clear↔blocked (Thorough surfaces new
  findings; Conservative drops borderline ones). The UI communicates the change ("Thorough surfaced N more
  to resolve" / "now clear at Conservative" / the new blocked status) so the processor reads it as "I asked
  for more/less scrutiny and got it", not a surprise.

**Rationale:** one AI pass produces every confidence-scored finding (LP-78); the dial is the cheap, instant
way to match scrutiny to a file's risk without re-running (or paying for) the AI. Gating display + blocking
by the same cutoff keeps "resolve all" meaningful at the chosen thoroughness. Conflating confidence with
severity would be wrong (a low-confidence red is *uncertain*, not *less severe*), so the dial never
recolors. Per-file + user-default fits real use; recording the level keeps "clear" honest; the legible
consequence avoids the jarring "my clear file is suddenly blocked" surprise.

**Consequences:** LP-81 surfaces the dial + the in-scope findings list + the calculators' alert (all using
the active cutoff). The cutoff values tune over use. The recorded submission-level supports audit. The
`str_enum` helper gained an optional `name` so the two `AggressionLevel` columns on `loan_files` get
distinct CHECK-constraint names. The dial is the free thoroughness control over LP-78's single expensive
pass — it is **not** a trigger to re-run it.

## ADR-195: Loan-file deletion — soft-delete for processors now, hard-delete (purge) admin-only future (LP-79.5)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** There was no UI affordance to delete a loan file — files (especially test/duplicate ones)
accumulated with no way to remove the clutter. The backend already supported soft-delete (the
`SoftDeleteMixin` / `deleted_at`, `DELETE /loan-files/{id}` → `soft_delete_loan_file_with_activity`,
`only_active` exclusion, `FILE_DELETED` audit); what was missing was the front-end action. The question
this ADR settles is *what kind* of delete a processor gets.

**Decision:**

- **Processors get soft-delete, not hard-delete.** `DELETE /loan-files/{id}` sets `deleted_at` (it never
  removes the row or its children), logs `FILE_DELETED` with the actor, and the file drops out of every
  processor-facing view (dashboard, lists, search, counts) via `only_active`. The data + the audit trail
  survive and are recoverable. Any processor (or admin) in the **owning** company may do it; a cross-company
  id is a `404` (existence never revealed). Deleting an already-deleted file is a clean `404` (it's invisible
  to its owner) — idempotent in effect, never a crash. A soft-deleted file is unreachable through the normal
  detail route (`GET` → `404`).
- **Hard-delete (permanent purge) is deferred, admin-only future work.** A processor must not be able to
  truly destroy a mortgage record — compliance, audit, and "deleted the wrong file" recovery all demand the
  data survive. Permanent destruction is a deliberate, privileged action; **nothing is built for it now**,
  and the soft-delete design does not foreclose it.
- **The UI requires a named confirmation.** The delete action (a dashboard row overflow menu + the
  file-header menu) opens a confirmation dialog that **names the file** (borrower + display id) and **what's
  affected** (the file and its documents/data/findings leave the dashboard; recoverable by an admin) — never
  a silent one-click destroy. On confirm the list query is invalidated so the file disappears, with a toast;
  cancel is a no-op.
- **No restore/trash view yet.** Deferred — soft-delete preserves the data, so a restore surface can come
  later without loss.

**Rationale:** soft-delete fixes the real usability gap (remove clutter) while honoring that mortgage
records shouldn't be destroyed by a processor. The soft-vs-hard split puts the reversible, everyday action in
the processor's hands and reserves the irreversible one for a future privileged path. The named confirmation
makes a list-clearing action deliberate and legible, not accidental.

**Consequences:** the capability was almost entirely backend-complete (LP-79.5 is mostly the UI + a couple
of hardening tests for the already-deleted and children-preserved cases). A future admin hard-delete +
restore/trash view can build on the preserved rows. Soft-deleted children remain in their tables, reachable
only by a future restore or an admin tool — acceptable (they're scoped through the file, which is invisible).

## ADR-196: Starter lender overlays (UWM + Sun-West) + overlay enforcement (LP-80)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** LP-74 built the rule engine's overlay-application *mechanism* (override an investor rule's
threshold by `rule_id` + add a custom rule + investor-default fall-through) and proved it with one SAMPLE
overlay. The third layer had no real content, so lender-specificity was not yet tangible and the DTI/LTV
calculators' "effective limit" was always the generic program default. LP-80 supplies starter UWM +
Sun-West overlays and makes enforcement demonstrable.

**Decision:**

- **Starter overlays as code config, keyed by lender slug.** `app/verification/overlays/starter.py` defines
  `UWM_OVERLAY` (slug `uwm`) and `SUNWEST_OVERLAY` (slug `sun-west`), merged into `default_registry()`
  alongside the LP-74 sample. Because the calculators **and** the engine already resolve through
  `default_registry().resolve(program, lender_slug)` with the file's lender slug, a file's target lender now
  selects its overlay automatically — no call-site rewiring.
- **Overlays are diffs.** UWM = one override (`conv.dti.back_end_max` → 45, tighter than the investor 50) +
  one custom rule (a reserves minimum). Sun-West = one override (`conv.ltv.purchase_max` → 95) and
  deliberately **no DTI override**. Everything un-mentioned falls through to the investor default; the overlay
  value wins where specified. Each `ThresholdOverride` now carries a `reason` (auditable + editable).
- **The enforcement proof.** The SAME file at 48%% back-end DTI **flags under UWM** (48 > 45) but **clears
  under Sun-West** (48 ≤ the investor 50) — same data, different lender, different findings. Proven at the
  engine layer (pure facts) and the calculator layer (`limit.status` over vs pass; `limit.source` overlay vs
  program_default). Sun-West still differs (a tighter purchase-LTV cap), so each lender is a genuine diff.
- **The effective limit is lender-specific.** A UWM Conventional file's DTI calculator shows 45 (source
  `overlay`, `lender_slug=uwm`); a Sun-West file shows 50 (source `program_default`) and a 95 purchase-LTV cap.
- **HONEST scoping — the values are starter placeholders.** The thresholds are NOT authoritative UWM /
  Sun-West requirements (that knowledge isn't available yet). They are a small, plausible set for the domain
  expert (Priya) to validate and correct — marked `STARTER PLACEHOLDER` in the module, every `reason`, and the
  docs. The MECHANISM is real; the VALUES are starter.

**Rationale:** LP-74 built the mechanism with a sample; supplying real content makes lender-specificity
concrete — the same file flagging differently for UWM vs. Sun-West is both the proof the three layers compose
per-file and a compelling demo (Priya works with both lenders, who differ). Overlays-as-diffs keep them
small, maintainable, and auditable (the `reason`). Honest placeholder scoping avoids fabricating authoritative
lender thresholds — she validates and extends them.

**Consequences:** LP-87 adds the admin UI to edit overlays without code; until then they are hand-edited
config. Per-company *custom* overlays (the `lenders.lender_overlays` JSON column, currently unused) are also
LP-87 — the starter overlays are universal config keyed by slug, which is the right representation for shared
placeholders. LP-82–85 supply the real investor rules these overlays patch. The calculators' effective limit
is now lender-specific. Precedence: the overlay value wins where specified; un-overridden rules use the
investor default.

## ADR-197: Editable Subject Property + Loan on the Overview + the target lender (LP-80.5)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** The Overview's Subject Property and Loan sections were display-only, and there was no obvious
control to set a file's **target lender** — which selects the LP-80 overlay. That blocked LP-80 (overlay
enforcement needs the lender on the file) and left a real usability gap.

**Decision:**

- **Reuse the stated-financials editing pattern.** The inline `EditableRow` (dirty-tracking, save-only-
  changed-fields) is extracted to a shared module and given a `select` kind (for the property/loan enums +
  the lender picker). The Property and Loan cards gain an Edit/Done toggle and render an editor that PATCHes
  the **existing** endpoints (`PATCH /loan-files/{id}/property`, `PATCH /loan-files/{id}`) — no new editing
  mechanism.
- **The target lender** is the file's existing `lender_id` (already on `LoanFileUpdate` + `LoanFileDetail`):
  processor-editable via a lender picker (the company's `lenders`), displayed on the Loan card, with a "Set
  lender" affordance when unset. MISMO does **not** carry the target wholesale lender (the 3.4 application
  export has only a LoanOriginationCompany/broker + LoanOriginator — verified against the real file), so the
  import leaves it null and it is a processing decision set on the Overview.
- **Changing the program (Conv ↔ FHA) is confirmed** — it swaps the entire rule set + overlay, so a dialog
  guards it; other fields save inline.

**Rationale:** one editing mechanism across stated/property/loan keeps the UX consistent and the code small;
the endpoints already existed. Putting the lender on the file is the concrete LP-80 prerequisite. The
program confirmation prevents a casual mis-click from silently changing which rules apply.

**Consequences:** LP-80's overlay enforcement is unblocked. Borrower editing remains out of scope (still
display-only). The note rate / amortization stay in the stated-data editor (not duplicated on the Loan card).

## ADR-198: Audit posture change — record from→to values for stated/loan/property edits (LP-80.5)

- **Date:** 2026-06-29
- **Status:** Accepted (supersedes the LP-56 value-free posture for these edits)

**Context:** LP-56 audited stated-data edits **value-free** (`detail = {}`, a safe summary only); property
edits were not audited at all. That gives "who touched what, when" but not "what changed from what to what" —
no real field-level change history.

**Decision:** edits to **stated financials, loan terms, and the subject property** now record the actual
**from→to values** in the activity_log `detail` (`{section, action, changes: [{field, from, to}]}`, values
encoded exactly via a shared `audit_value`/`field_changes` helper). Property edits — previously silent — are
now audited with values. This is a deliberate change that **supersedes the LP-56 value-free stance** for
these edits (the DTI/LTV overrides + status changes already recorded from→to, so there is precedent). The
generic `FILE_UPDATED` type is kept (the `detail.section` distinguishes the kind) — no new enum values, no
migration.

**Rationale:** a true change history is worth more than a value-free trail for correcting imported data and
for audit. Reusing one `FILE_UPDATED` type with a structured `detail` keeps it consistent and migration-free.

**Consequences (PII):** the activity_log now holds **financial / PII-adjacent values** (amounts, an address,
loan terms). It therefore **inherits the stated data's PII posture** — it is exposed only through the same
auth + tenant-scoped surfaces that already show the stated data, never a less-protected one. SSNs and similar
high-sensitivity fields are **not** in scope here (borrower editing is excluded), so no raw SSN enters the
log. Any future surface that renders the activity log must apply the same masking/access control.

## ADR-199: Verification staleness on baseline edits — both sides of the comparison (LP-80.5)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** `mark_verification_stale` fired only on **document** changes (+ finding-apply). Editing the
**stated** data, loan terms, target lender, or property — the *other* side of the cross-source comparison and
the DTI/LTV inputs — changed the verification baseline silently: no "out of date — re-run" prompt. LP-78.1's
input fingerprint already includes the stated/loan/property data, so a manual re-run after such an edit is
genuinely real (not a stale cache hit) — what was missing was the **prompt**.

**Decision:** stated-financials, loan-baseline (loan terms / program / purpose / lender), and property edits
now call `mark_verification_stale` — the same as a document change. A baseline change on **either side** of
the cross-source comparison now sets the staleness flag, so the verification panel shows the "re-run" cue.
Lifecycle/contact fields (status, loan officer) do **not** mark stale. The frontend mutations for these edits
also invalidate the `dti` / `ltv` / `verification` query keys, so an open calculator or verification panel
refreshes after an edit. The stale banner copy is generalized from "Documents changed" to "The file changed".

**Rationale:** the staleness model is only honest if every baseline change triggers it; the LP-78.1
fingerprint already guarantees the re-run is real, so this purely adds the missing prompt + refresh. DTI/LTV
are read-time derived, so they are already correct on the next GET — the invalidation just refreshes
already-open panels.

**Consequences:** the staleness model is now complete (document changes + finding-apply + baseline edits).
The LP-78.1 cache + fingerprint are unchanged. Editing a baseline field after a verification run prompts a
re-run rather than leaving a silently-outdated result.

## ADR-200: Minimal verification tab — the Arc A demo surface (composition; minimal-not-full) (LP-81)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** Every Phase 3 capability (the engine LP-74, findings LP-75, DTI/LTV LP-76/77, AI cross-source
LP-78/78.1, the dial LP-79, overlays LP-80, editable property/loan + lender LP-80.5) was a capability with no
single coherent screen. LP-81 is the surface the domain expert (Priya) actually uses — the capstone of Arc A.

**Decision:** the Verification tab composes the existing capabilities into ONE coherent demo-quality screen:
the **DTI/LTV calculators prominent** at the top (transparent, lender-specific limits via LP-80), then the
cross-source panel — the **run trigger + staleness banner**, the **needs-completeness indicator**, the
**aggression dial** filtering the findings, and the **interactive findings list** (severity, type, confidence,
source location [click → page + verbatim snippet], with the core resolution actions Apply / Override-with-
reason / Add note; APPLY fires the recompute interlock). It is **MINIMAL by design** — NOT the full Wireframe
5: the stats row, filter pills, version selector, and the full per-finding action set (Request docs / Accept
risk) are **LP-88**. The findings list handles deterministic + cross-source findings uniformly (the origin
distinguishes provenance). The resolution endpoints (`POST …/findings/{id}/{apply,override,note}`) wrap the
existing LP-75 services; each returns the re-filtered status so the calculators refresh in one round-trip.

**Rationale:** composing the capabilities is what makes the slice DEMONSTRABLE end-to-end (open a file →
transparent DTI/LTV → run cross-source → resolve findings → tune thoroughness → lender-specific results);
minimal-not-full keeps the demo focused on the core value rather than the complete tab.

**Consequences:** LP-88 builds the full tab; Arc A is COMPLETE — the demonstrable verification slice is ready
to show Priya. LP-82–85 supply the real rule content the engine evaluates.

## ADR-201: Re-run stability — stable identity, merge-not-replace, templated wording (LP-81)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** the tab is where re-runs become visible. Without stability, a re-run would churn the displayed
findings — re-worded (the AI's free-form description varies run to run), re-ordered, and resolutions lost —
undermining the trust the tab builds.

**Decision:**

- **Stable substance-based identity.** A cross-source finding's identity is its canonical type
  (`rule_id = cross_source.<type>`), so the same discrepancy is recognized across re-runs.
- **Merge-not-replace (resolutions survive).** A re-run supersedes only the prior pass's **OPEN** cross-source
  findings (soft-delete) and emits the fresh set; **RESOLVED** findings (APPLIED / OVERRIDDEN) are never
  touched — the processor's work survives. The tab keeps resolved findings in a separate **"Resolved"** group
  (history), so a finding is never silently dropped, and the dial filters only the OPEN list.
- **Templated wording for known types.** The user-facing headline for a known/canonical type is rendered
  **deterministically** from its type (reads IDENTICALLY every run); the AI's free-form description shows only
  as secondary detail. Novel ("other") and deterministic-rule findings keep their own (already deterministic)
  message.

**Rationale:** stable identity + preserve-resolved + a deterministic headline are the minimum that makes a
re-run trustworthy — the processor sees the same findings worded the same way, and never loses a resolution.

**Consequences:** the deeper "promote reliable checks to deterministic" consistency work is **LP-86** (beyond
this near-term stability). Templating is a display concern (a frontend helper over the structured fields), so
no finding rows change shape.

## ADR-202: Needs-completeness indicator — sparse ≠ clean; indicator not gate (LP-81)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** verification compares documents against the stated application. On an under-documented file a
**sparse** result could be mistaken for a **clean** file — a false-confidence failure mode. The needs list
(Phase 2) comes first; verification is meaningful once documents are collected.

**Decision:** the verification tab shows a **needs-completeness indicator** — the outstanding-needs count + a
non-blocking message ("verification compares documents against the stated application; N outstanding document
needs — results may be incomplete until they're collected"). It is an **indicator, NOT a gate**: the
processor can still run verification (needs-first → verification-second is the ordering, not a hard block). It
hides when nothing is outstanding (a sparse result there is genuinely clean).

**Rationale:** the indicator prevents the false-confidence reading of a sparse result and reflects the
needs-first ordering, without blocking a processor who wants to run verification early.

**Consequences:** the indicator reuses the existing outstanding-needs count; no new backend. A hard gate (if
ever wanted) is a future policy decision, not this.

## ADR-203: Conventional income & asset rules as GROUNDED STARTERS (LP-82)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** Arc A built + surfaced the verification engine; Arc B fills the rule CONTENT. LP-82 is the first
content ticket — ~20 Conventional income + asset rules (~10 each). The rules' authoritative source is the
domain expert (Priya, an active Conventional/FHA processor) and her validation against real files; her
priority list is not yet available.

**Decision:** encode ~20 Conventional income/asset rules into the LP-74 engine as **GROUNDED STARTERS** —
researched against the *current* Fannie Mae Selling Guide (retrieved 2026-06) with **real B-section
citations** + current values, but **clearly marked starter / validate-with-Priya** throughout (every rule
carries `starter=True` + a `notes` caveat; the module header says so; the docs say so). They are NOT
presented as authoritative final rules. Specifics:

- **Uniform structure (LP-74):** each rule is a `VerificationRule` — stable `rule_id` (e.g.
  `conv.income.self_employment_present`, `conv.assets.large_deposit_source`), `layer=investor`,
  `program=conventional`, the typed field(s) it `reads`, a **threshold-as-data** `Condition` (so an overlay
  overrides it by `rule_id`, LP-80), `severity`, and a **structured `RuleSource`** (`{type, citation,
  section, retrieved, to_verify}`). The schema gained `section`/`retrieved`/`to_verify` on `RuleSource` and
  `starter`/`notes` on `VerificationRule`.
- **Grounded values that correct folk-knowledge:** document age is **4 months** on the note date (B1-1-03),
  NOT 30 days; base income is the **most recent W-2 + pay stub** (the chapter B3-3 rewrite of 03/2026), NOT
  two years of W-2s — explicitly marked recently-changed; self-employment needs a **2-year history**
  (B3-3.5-01); gift/asset/retirement verification (B3-4.x). The **large-deposit threshold** and **reserves**
  are marked **DU-message-driven / program-driven STARTER placeholders**, NOT fixed Selling-Guide constants.
- **Citations are researched, not invented:** where a subsection is uncertain the source carries
  `to_verify=True` rather than fabricating a number (AI-assisted-but-human-reviewed encoding).
- **Deterministic evaluation, no AI:** the engine reads the typed field → compares to the threshold → emits
  a finding into LP-75's model at certain confidence. A few rules are **evaluable today** from stated data
  (self-employment income, gift, retirement, large deposit, reserves — via **typed-core promotions** in
  `build_file_facts`); the rest read a canonical typed-field path whose fact isn't produced yet, so they are
  recorded **not-evaluated** (graceful) until the fact is promoted — the "typed core grows as rules need it"
  design.

**Rationale:** grounding the starters in current research (not memory) makes them a *useful* first cut and
corrects stale folk-knowledge, while the starter marking is honest about what they are — content pending the
expert's validation, subject to Selling-Guide updates, DU automation, and lender overlays. The engine is real
and tested; the content is grounded-but-starter.

**Consequences:** LP-83 the Conventional credit/DTI/property/doc rules; LP-84/85 FHA; Priya validates +
extends these against the live guide for her lenders. The promotion-pending rules wire up as the typed
extraction grows. The `to_verify` flag + `starter` marker can drive a future "rules to validate" view.

## ADR-204: Conventional credit/DTI + property + documentation rules as grounded starters (LP-83)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** The second Arc B content ticket (LP-82 did income/asset). LP-83 adds ~30 Conventional rules across
credit/DTI, property/appraisal, and documentation. This category is higher-stakes — credit-score minimums and
the DTI ceiling are the most-cited Conventional values and the most prone to folk-knowledge error.

**Decision:** encode ~30 Conventional rules into the LP-74 engine as **GROUNDED STARTERS** (same shape +
posture as LP-82: real B-section citations, `starter=True`, validate-with-Priya), reusing LP-82's `conv_rule`
/ `sg` builders (extracted to `conventional/_base.py`). Specifics:

- **The credit-score minimum is encoded LAYERED, not flat-620 (the headline correction).** Through DU Version
  12.0 (11/2025) minimum scores no longer apply (DU decides); manually underwritten loans still require 620
  (`conv.credit.min_score_manual`, **gated** to manual); a sub-620 representative score is ineligible for
  delivery (`conv.credit.min_score_delivery_floor`, ungated). B3-5.1-01, marked recently-changed. A hardcoded
  "min 620 always" would be wrong.
- **DTI** is DU-50% / manual-36%→45% (B3-6-02): the DU ceiling is the existing `conv.dti.back_end_max` (LE 50);
  LP-83 adds the **manual-gated** `conv.dti.back_end_max_manual` (LE 45). Both **consume LP-76's computed
  `dti.back_end_pct`** — they read it, never recompute.
- **Property/appraisal:** appraisal age > 4 months (B4-1.2-04, parallel to doc age); general eligibility
  (B2-3-01); value-acceptance/appraisal-waiver marked **DU-driven** (B4-1.4-11); occupancy marked
  **Eligibility-Matrix-driven** — none of the Matrix/DU logic is hardcoded.
- **Documentation:** 4-month doc age (B1-1-03); application package (B1-1-01); condo project review
  (B4-2.1-01, **gated** to condo properties); tax-transcript/4506-C (B3-3.1, cross-links LP-82).
- **Applicability gating (new mechanism):** a small `RuleGate` (a fact + a `Condition`) added to
  `VerificationRule`, checked by the engine before evaluation — a manual-only or condo-only rule applies only
  when its gate fact holds; absent gate → not-applicable (conservative). This is the minimal extension the
  "manual-vs-DU / property-type" gating requires; the rest reuses LP-82.
- **Cross-links (not duplicated):** the re-underwrite-on-undisclosed-debt rule is noted as the deterministic
  counterpart to LP-78's cross-source undisclosed-obligation finding (the interlock exists).
- **Typed-core promotions:** `build_file_facts` derives `property.present` / `property.is_condo`; credit /
  appraisal / underwriting-method facts are promotion-pending (recorded not-evaluated until they land).
- **Citations researched, not invented:** uncertain subsections (derogatory-credit waiting periods, several
  property/doc sections) carry `to_verify=True` rather than asserting a number.

**Rationale:** grounding the high-stakes values in current research and encoding the *nuanced* credit-score
state (rather than the stale flat-620) is exactly why grounded-research-then-starter matters; the starter
marking keeps it honest (content pending the expert's validation, subject to Selling-Guide updates, DU
automation, the Eligibility Matrix, and lender overlays).

**Consequences:** LP-84/85 the FHA rules; Priya validates + corrects these. The gate mechanism is reusable
for future applicability-gated rules. The promotion-pending rules wire up as the typed extraction grows.

## ADR-205: FHA income/asset/credit-DTI/MIP rules as GROUNDED STARTERS (LP-84)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** The third Arc B content ticket and the **first FHA** one (LP-82/83 were Conventional). LP-84 adds
~31 FHA rules across credit/DTI, income, assets, and MIP. FHA is genuinely different from Conventional — a
separate program (`program=fha`) with its own source (HUD Handbook 4000.1, **not** the Fannie Selling Guide)
and structures with no Conventional analog: a tiered minimum-decision-credit-score (MDCS), a compensating-
factors DTI model, and MIP (mortgage insurance premium). It must NOT be a clone of the Conventional rules.

**Decision:** encode ~31 FHA rules into the LP-74 engine as **GROUNDED STARTERS** (same shape + posture as
LP-82/83: real HUD section citations, `starter=True`, validate-with-Priya — Priya works FHA with Sun-West),
under a new `rules/fha/` package with its own `fha_rule` / `hud` builders (`_base.py`). Program-gating is the
existing `registry.investor(program)` filter — no new mechanism. Specifics:

- **MDCS is encoded TIERED to the down payment, NOT a flat min (the FHA headline).** 580+ → 3.5% down (96.5%
  LTV); 500-579 → 10% down (90% LTV); below 500 → ineligible. Encoded as an eligibility floor
  (`fha.credit.mdcs_eligibility_floor`, ≥500, RED), the 3.5%-tier threshold (`…mdcs_minimum_down_3_5_tier`,
  ≥580, YELLOW), and a **gated** low-tier rule (`…mdcs_low_tier_down_payment`, requires 10% down, gate
  `credit.mdcs < 580`). A hardcoded "min 580 always" would be wrong.
- **Manual-underwriting triggers (the "conservative flag"):** a score below 620 (and/or DTI above 43%) routes
  to manual underwriting where compensating factors apply (vs the TOTAL Mortgage Scorecard AUS) — encoded as a
  YELLOW routing flag, II.A.5, AUS-vs-manual distinction marked.
- **DTI is the COMPENSATING-FACTORS mitigable model, NOT a hard DU-style ceiling (the plan's FHA requirement).**
  Baseline 31% front / 43% back is encoded YELLOW (a flag **resolvable by documenting a compensating factor**
  via LP-75's resolution — OVERRIDDEN-with-reason / APPLIED); the uplifted ceiling 40% front / 50% back is a
  separate RED rule (hard, compensating factors cannot rescue it). A gated
  `fha.dti.compensating_factors_required` (applies only when back-end > 43%) makes the "≥1 documented factor"
  requirement explicit. This contrasts with Conventional's hard DU ceiling. The DTI rules **consume LP-76's
  computed `dti.front_end_pct` / `dti.back_end_pct`** (read, never recompute). These SUPERSEDE the LP-74 sample
  `fha.dti.back_end_max` (a 57% placeholder).
- **MIP (no Conventional analog):** UFMIP 1.75% (175 bps) of the base loan amount + present-check (Appendix
  1.0); annual MIP rate-as-data table (~15-75 bps, most 55; the ≤75 bps starter upper bound marked to-verify);
  the **LTV-90% duration rule** — LTV > 90% → annual MIP for life; LTV ≤ 90% → 11 years (132 months) — encoded
  as two LTV-gated rules **reading LP-77's `ltv.ltv_pct`**; a missing-MIP RED finding (an FHA loan must carry
  MIP). MIP rules use the `DOCUMENTATION` category: there is **no dedicated `MORTGAGE_INSURANCE` category** and
  adding one would require a migration (the category column is a CHECK-constrained VARCHAR) — a dedicated MI
  category is a deferred promotion.
- **Overlay-overrideable (especially apt for FHA — overlays are common):** an FHA minimum (e.g. the MDCS floor
  500→620) and the MIP rate are overridden by `rule_id` (LP-80). Most lenders set 580-640 floors over FHA's
  500/580.
- **Typed-core reuse + promotion:** the FHA income/asset rules read the SAME promoted paths as LP-82
  (`assets.gift.total_amount`, `assets.retirement.total_amount`, `income.self_employment.monthly_amount`,
  `assets.largest_deposit_amount`, `dti.back_end_pct`) — evaluable today on an FHA file (program-gating selects
  the FHA variant), no new promotion needed. The FHA-specific facts (`credit.mdcs`, `down_payment.pct`,
  `dti.front_end_pct`, `ltv.ltv_pct`, the MIP fields) are promotion-pending (recorded not-evaluated until they
  land).
- **Citations researched, not invented:** uncertain values (derogatory waiting periods, the MIP rate table,
  the 60% retirement-reserve haircut, FHA document recency, AUS-vs-manual routing) carry `to_verify=True`.

**Rationale:** FHA's tiered MDCS, compensating-factors discretion, and MIP are exactly the structures a
Conventional clone would get wrong; encoding them FHA-specifically (with HUD citations) and marking them
starter keeps the engine real while the content stays honestly pending the expert's validation.

**Consequences:** LP-85 the FHA property/doc rules (stricter safety/security/soundness standards) extend
`FHA_RULES`. The promotion-pending FHA facts (credit/down-payment/LTV/MIP) wire up as the typed extraction
grows. A dedicated `MORTGAGE_INSURANCE` finding category is a future migration if MIP findings warrant it.

## ADR-206: FHA property + documentation rules as GROUNDED STARTERS; the rule content is complete (LP-85)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** The fourth and LAST Arc B content ticket. LP-85 adds ~18 FHA rules across property (the Minimum
Property Requirements — safety/security/soundness) and documentation. FHA property is the most distinctively-FHA
content of all and has **no Conventional analog**: a Conventional appraisal targets market value, while an FHA
appraisal ALSO verifies the property meets the MPR/MPS for the **three S's** — a failing property needs repairs
before FHA insures the loan. After this ticket the Conventional + FHA rule content (LP-82..85) is complete.

**Decision:** encode ~18 FHA property/doc rules into the LP-74 engine as **GROUNDED STARTERS** (same shape +
posture as LP-82/83/84: real HUD II.D / II.A citations, `starter=True`, validate-with-Priya), in
`rules/fha/property_docs.py`, reusing LP-84's `fha_rule`/`hud` builders, program-gating, and conditional/
mitigable finding pattern. Specifics:

- **The three S's MPR/MPS framework + the deficiency checklist:** a three-S's umbrella rule plus individual
  deficiency rules (lead-based paint pre-1978, functional heating/plumbing/electrical, roof, water intrusion,
  handrails/safe-access, bedroom egress, well/septic, defective structural conditions) + MPR-vs-MPS by
  construction status (24 CFR 200.926). II.D.
- **The "subject-to-repair" CONDITIONAL model (reuses LP-84's compensating-factors mitigable pattern):** MPR
  findings are MITIGABLE — a subject-to-repair YELLOW finding resolvable by documenting the repair/re-inspection
  via LP-75's resolution (most deficiencies are CORRECTABLE) — NOT silent hard blocks. Only un-correctable issues
  (a no-egress bedroom, serious structural failure) are RED. Severity = correctable-vs-uncorrectable.
- **TIER-2 HONESTY (the critical posture, same as LP-77's appraised value):** most MPR conditions are observed by
  the appraiser and live in the appraisal document (manual / not deterministically extracted). The rules do NOT
  pretend to detect physical deficiencies — they check (a) the FHA appraisal is present (the RED Tier-2 anchor),
  (b) whether it is "subject to" repairs, and (c) surface the MPR checklist for human/appraiser confirmation;
  each deficiency rule reads an appraiser-provided fact and is recorded not-evaluated until that datum is
  captured. We don't fake what the system can't see.
- **MPRs are POLICY-IN-FLUX:** FHA's 2026 Request for Information to modernize the MPRs (no comprehensive update
  in 20+ years) means the content is not only overlay-subject but actively under revision — the rules carry a
  "subject to the pending MPR modernization" caveat in addition to the starter marker.
- **Eligibility + condo:** 1-4 unit residential (`property.unit_count`, newly promoted from the financed unit
  count → evaluable); condo project FHA approval (HRAP/DELRAP — **gated** to condo via the promoted
  `property.is_condo`); the appraisal validity period (Tier-2, to verify).
- **Documentation:** the FHA appraisal present (RED), the subject-to-repair completion/re-inspection (gated to
  subject-to status), the FHA case number + Amendatory Clause, the pre-appraisal sales contract, document
  recency (FHA's own — to verify).
- **Applicability-gated:** construction status (new → MPS), property type (condo), well/septic presence,
  pre-1978 (lead paint), subject-to-repair status. **Overlay-overrideable** (e.g. the appraisal validity window
  180→120) by `rule_id` (LP-80). **Program-gated** (FHA-only).
- **Citations researched, not invented:** uncertain values (appraisal validity period, well/septic distances,
  exact subsection numbers, the handrail/egress standards) carry `to_verify=True`.

**Rationale:** FHA property is exactly where a Conventional clone fails — the three S's, the subject-to-repair
discretion, and the Tier-2 appraiser-observed nature have no Conventional equivalent. Encoding the conditional
model honestly (mitigable, correctable-vs-uncorrectable) and refusing to fake deterministic deficiency detection
keeps the engine trustworthy; the in-flux note keeps it current with the pending MPR modernization.

**Consequences (the content arc is COMPLETE):** with LP-82..85 the engine now holds a full grounded-starter
Conventional + FHA rule set across income, assets, credit/DTI, property, documentation, and (FHA) MIP — ~50
Conventional + ~49 FHA rules. The mechanism is real + tested; the specific content is grounded-but-starter,
pending Priya's validation (and, for FHA MPRs, the pending modernization). LP-86 and onward consume this rule
set; the promotion-pending property/appraisal facts (subject-to-repair, the MPR deficiency flags, year built,
construction status, well/septic) wire up as the Tier-2 appraisal extraction grows.

## ADR-207: Cross-source checks — reliable, enumerable discrepancies PROMOTED from AI-discovery to DETERMINISTIC rules (LP-86)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** The AI cross-source layer (LP-78) is a DISCOVERY engine — it catches novel, unenumerable
discrepancies, but at the cost of non-determinism (recall variance: a genuine finding appears on one run, not
the next). The diagnostic signal during the cross-source debugging was the "driver's-license-address-equals-
subject-property" finding FLICKERING between runs — because it is actually DETERMINISTIC LOGIC the AI merely
*thought* to apply (compare two addresses), not open-ended perception. The plan's §3.8 locked the structural
answer: known, enumerable cross-checks GRADUATE from the AI layer into deterministic rules; the AI narrows to
genuinely novel discovery.

**Decision:** encode ~18 reliable, enumerable cross-source checks as a NEW DETERMINISTIC rule category (a pure
engine in `app/verification/cross_source/`: `facts.py` / `rules.py` / `engine.py`), distinct from the
single-source rules (LP-82..85) because a cross-source rule reads MULTIPLE fields ACROSS sources (not one
threshold against one field). Each `CrossSourceRule` has a stable `rule_id` (`xsrc.*`), the canonical finding
type it OWNS (the de-dup key), category + severity, TEMPLATED wording (fixed, identical every run), a pure
`check` over `CrossSourceFacts`, optional threshold-as-data (the income-variance %, overlay-overrideable), and
is program-agnostic (`program=None` — most cross-source checks apply to both Conventional and FHA). The rules
emit into LP-75's shared model with `origin=deterministic_rule` + `confidence=DETERMINISTIC_CONFIDENCE`.

- **The rules (~18):** identity (name/SSN[RED]/DOB/current-address consistency), address red-flags
  (`dl_equals_subject` — THE GRADUATE; employer-equals-subject), income (`stated_vs_documented` variance,
  employer-name, employer-count-vs-items), liability (`undisclosed_debt` — the deterministic detection
  counterpart to LP-83's re-underwrite rule; stated-not-on-report), asset (`stated_missing_document` [kept per
  the over-flagging decision], large-deposit-unsourced, gift-without-letter), terms/property (price-vs-contract,
  loan-vs-documented, subject-address consistency, occupancy-vs-evidence).
- **The internal research:** unlike LP-82..85 (external Fannie/HUD guides), the promotion candidates came from
  THIS system — the canonical finding types the AI layer already emits (`_TYPE_CATEGORY` / the prompt) and the
  over-flagging decisions. The external mortgage-QC cross-check set was the completeness checklist.
- **DE-DUPLICATION (the graduation mechanics):** the deterministic pass runs first inside `run_cross_source` and
  returns the set of canonical types it FIRED this run; the AI layer then DEFERS — drops any raw finding whose
  type is in that set (run-scoped, so the AI still surfaces a type the deterministic pass was silent on — e.g.
  when its Tier-2 facts aren't loaded — and always keeps the novel "other" bucket + co_borrower_discrepancy).
  No double-reporting of a fired discrepancy; the stable, templated deterministic finding is the one shown.
- **THE CONSISTENCY PAYOFF (option D — the deepest fix):** the promoted checks now run EVERY time, identically,
  no AI, no recall variance, no flicker — completing the consistency arc with LP-78.1 (caching) + LP-81 (stable
  identity / merge / templated wording). The driver's-license finding fires on every run as a rule.
- **Cross-links (wired, not rebuilt):** the undisclosed-debt rule carries the same `add_liability` apply spec as
  the AI path → applying it feeds the APPLY→recompute interlock (LP-75/76) and parallels LP-83's re-underwrite
  rule; the missing-document check is kept (it + the needs list both surface it — intentional redundancy); the
  asset/gift/deposit checks cross-link LP-82's single-source rules (single-source = one field; cross-source =
  across sources). The cross-source rules surface DATA discrepancies, never computed DTI/LTV (the calculators').
- **The absent-data guard (honesty):** a set-difference check (stated-not-on-report; undisclosed-debt) only
  fires when the other side (the credit report) is actually present — an empty side is "not loaded", not a
  discrepancy. Many facts (credit-report liabilities, contract price, documented income, occupancy evidence)
  are Tier-2 / promotion-pending; their checks produce nothing until the fact lands (graceful, as LP-83..85).

**Rationale:** the reliable checks were deterministic logic all along — making them rules removes the recall
variance at its root (option D), and the run-scoped de-dup lets the AI keep its real value (the novel frontier)
without re-litigating the known checks under a flickering label. The graduation is honest: the rules consume the
same assembled context the AI reads, the comparison is exact, and absent facts simply do not fire.

**Consequences:** the AI cross-source layer = the discovery frontier; the deterministic `xsrc.*` rules = the
enumerable known, stable + templated. As the typed/Tier-2 extraction grows (credit-report liabilities, contract
price, documented income), more checks become live and more of the AI's load shifts to genuinely novel
discovery. The `starter=True` thresholds + normalization remain a validate-with-Priya item.

## ADR-208: Four additional calculators (MI/MIP, self-employed, reserves, max loan) — extend the LP-76/77 pattern (LP-87)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** LP-76/77 shipped the DTI + LTV calculators (transparent / auto-populated / overrideable /
findings-coupled / deterministic — the "show the math, beat ChatGPT's black box" win). LP-87 adds four more —
mortgage insurance (MI/MIP), self-employed income, reserves, and max loan — that processors need checked.

**Decision:** build the four as pure deterministic modules (`app/verification/{mortgage_insurance,self_employed,
reserves,max_loan}.py`) behind ONE shared transparent response shape (`CalculatorView`) and ONE shared,
calculator-discriminated override table (`calculator_overrides`), reusing the LP-76/77 service/override/audit/API
pattern exactly. One generic frontend component (`calculator-card.tsx`) renders all four. Specifics:

- **MI/MIP is PROGRAM-AWARE.** Conventional = PMI (required above 80% LTV, terminates at 78% per the HPA — exact;
  the annual rate is a credit/LTV rate-card, a grounded-starter). FHA = MIP, which **CONSUMES LP-84's MIP rules**
  (the service reads `fha.mip.ufmip_rate` = 175 bps from the registry) — UFMIP 1.75%, the annual rate (starter
  0.55%, LP-84's rule is the cap), and the **LTV-90% duration** (≤ 90% → 11 years, > 90% → life). It reads LP-77's
  LTV. The arithmetic is exact; the rates are passed in, not duplicated.
- **Self-employed income is Form-1084-grounded + FEEDS DTI.** Net profit + non-cash add-backs (depreciation,
  depletion, amortization/casualty, business-use-of-home), averaged across two years; a declining trend is
  flagged (not silently averaged). The derivation is shown line by line; the methodology is a grounded-starter
  (the exact add-backs + averaging-vs-most-recent judgment is domain expertise). The qualifying monthly figure
  feeds the DTI income side (the seam is surfaced + documented).
- **Reserves consume the FHA 60% retirement haircut (LP-84).** Eligible reserves = liquid + (vested retirement ×
  factor) − down payment − closing costs (gifts/borrowed excluded); months = eligible ÷ PITI (consumed from the
  DTI calc). Available vs required; the required months are rule/DU/overlay-driven (starter).
- **Max loan INVERTS the constraints.** The DTI ceiling (income × max-DTI → max payment → invert amortization to
  max principal), the LTV limit (value × max-LTV), and the program loan limit (FHFA conforming, a grounded-starter
  — changes annually + county-specific). The binding (lowest) constraint wins and is named. It consumes LP-76's
  DTI ceiling + LP-77's LTV limit.
- **Methodology honesty:** the MECHANISM (transparent/overrideable/recompute/findings-coupled/deterministic) is
  real + tested; the domain-judgment methodology (PMI rate, self-employed add-backs, required reserves, loan
  limits) is `methodology.starter=True` (grounded in the real source — Form 1084, FHA/FHFA limits — + validate
  with Priya). The deterministic arithmetic (MIP from LP-84, the max-loan inversion) is solid.
- **One shared override table** (`calculator_overrides`, calculator-discriminated) instead of four near-identical
  tables — the LP-76/77 override semantics are unchanged (unique active row per (file, calculator, field);
  soft-delete to revert; every set/clear audited as `CALCULATOR_OVERRIDDEN` with from→to values).

**Rationale:** the four calculators are the same transparent/deterministic value proposition as DTI/LTV; reusing
the pattern (and consuming the sibling calculators + the LP-84 rule values rather than duplicating) keeps them
correct-by-construction, and the starter marking keeps the domain-judgment methodology honest.

**Consequences:** LP-88 surfaces them in the full verification tab (LP-87 places them on the existing tab). The
starter methodology (PMI rate, loan limits, reserves, add-backs) is Priya's to validate. The shared
override-table + generic-view + generic-component pattern is reusable for future calculators.

## ADR-209: Overlay admin UI — edit lender overlays without code (LP-87)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** Since LP-80, lender overlays (a lender's deviations from the investor default) were hand-edited JSON
on the `lenders.lender_overlays` column. LP-87 closes that deferral with an admin UI.

**Decision:** build a thin admin UI + API OVER LP-80's existing storage (not a new mechanism). The backend
(`services/overlay_admin.py`, `api/overlay_admin.py`) reads/writes the same `lender_overlays` JSON, and the
frontend (`/admin/lenders` + `/admin/lenders/[id]`) views/edits it. Specifics:

- **ADMIN-gated** — the router carries `Depends(require_role(UserRole.ADMIN))` (overlays are company config, not
  per-processor); the frontend also role-gates (UX only — the backend is the boundary).
- **TENANT-scoped** — a lender is fetched within the caller's company (`scope_to_company`); cross-company → 404.
- **Reason REQUIRED** — the change `reason` is `min_length=1` (rejected otherwise, 422); each override also
  carries its own reason. Auditable WHY, per LP-80.
- **AUDITED** — every edit's from→to values are recorded (reusing LP-80.5's `field_changes` / `audit_value`)
  in the overlay's OWN audit trail (stored in the `lender_overlays` JSON as an `audit` list). This avoids an
  `activity_logs` schema change (that table is loan-file-scoped; overlay edits are company/lender-scoped).
- **EFFECT-LEGIBLE** — the view composes each override against the investor base rule (by `rule_id`, from the
  sample + Conventional + FHA rule index) to show the investor default → the lender's effective threshold. An
  unknown `rule_id` is rejected (422).

The persisted JSON shape is `{"overrides": [{rule_id, value, reason}], "audit": [{at, actor_user_id, reason,
changes}]}`. **Seam (honest):** the live verification engine + calculators currently resolve the *in-code*
STARTER_OVERLAYS (keyed by lender slug); wiring the live engine to prefer a company's DB overlay is a follow-on
(LP-88+). The admin UI manages + makes legible the per-company overlay store, which is the closing of the LP-80
hand-edited-JSON deferral.

**Rationale:** editing overlays in a UI (with a required reason + a from→to audit trail + the effect made
legible) is far safer than hand-editing JSON, and storing the audit in the overlay's own JSON keeps the change
contained without a schema migration to the loan-file-scoped activity log.

**Consequences:** admins manage overlays without code. LP-88 can wire the live engine to read the DB overlay so a
company's edits drive enforcement (same file → different findings) end-to-end; the effect-legibility already
shows what an edit produces. The `LENDER_OVERLAY_UPDATED` activity type is reserved for that wire-up.

## ADR-210: The full verification tab — extends LP-81 to the complete Wireframe 5 (LP-88)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** LP-81 built the minimal verification tab (the Arc A demo surface): the composition, the findings
list (severity/type/confidence/source-location/resolution), the aggression dial, the cross-source trigger +
staleness, the needs indicator, and re-run stability. Since then the capabilities multiplied — the full
Conventional + FHA rule set (LP-82..85), the deterministic cross-source rules (LP-86), all six calculators
(LP-76/77/87), the overlays + admin (LP-80/87). LP-88 builds the PRODUCTION tab Priya uses daily by EXTENDING
LP-81 (not rebuilding it) with the deferred Wireframe-5 richness + surfacing what landed.

**Decision:** extend the existing tab in place. Added ON TOP of LP-81:

- **Stats row** (`verification-stats.tsx`) — total / blocking (red) / warnings (yellow) / resolved / outstanding
  needs, at the active dial cutoff (so they agree with the list + blocking).
- **Filter pills** (`finding-filters.tsx` + `lib/verification/finding-filters.ts`) — severity (all/red/yellow)
  + category (the categories present), ORTHOGONAL to the dial: the dial sets the confidence floor, the pills
  slice severity + category within it. Pure client-side, instant.
- **Version selector** (`version-selector.tsx` + a `GET …/verification/runs` endpoint) — the run history
  (newest-first, counts + timestamp, current marked). Runs were already versioned in the DB; this exposes the
  history. Findings live on the file (not a run), so the history compares run summaries; resolutions persist
  (LP-81 merge semantics).
- **The full per-finding action set** (`finding-card.tsx`) — LP-81's Apply / Override / Note PLUS **Accept-risk**
  + **Request-docs** (see ADR-211).
- **All six calculators with PROGRESSIVE DISCLOSURE** (`calculators-section.tsx`) — a scannable strip of six
  summary tiles (title + headline + status dot) that expands exactly ONE into its full transparent/overrideable
  calculator. Replaces the six always-expanded cards (the complexity-management core). Summary hooks share the
  query cache with the full components (no refetch).
- **Source-origin distinction (LP-86)** — each finding shows `deterministic` (stable/certain) vs `AI · novel`
  (the frontier); the **lender overlay** that adjusted it (LP-80, from `details.overlay_applied`) is shown; the
  tab header shows the **program** (Conv/FHA, a new `program` field on the status).

**Complexity management (the real design work):** the tab stays scannable despite the richness via hierarchy
(stats → calculators strip → dial → pills → findings), progressive disclosure (one calculator expanded; findings
filtered; stats summarizing), and reuse of the established card/badge/pill idiom. The frontend-design skill's
"manage complexity" guidance applied throughout; loading/error/empty preserved (LP-46/47); PII masked.

**Rationale:** extending (not rebuilding) preserves LP-81's hard-won re-run stability + resolution flow while
adding the Wireframe-5 completeness; progressive disclosure is what lets six calculators + ~120 rules' findings
coexist on one usable screen.

**Consequences:** this is the daily production tab. LP-89 is the Priya validation/hardening. The version selector
can grow into a full run-diff; wiring the live engine to a company's DB overlay (LP-87's seam) would make the
lender-specific results reflect admin edits end-to-end.

## ADR-211: Accept-risk resolution + Request-docs from a finding (LP-88)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** LP-81's per-finding actions were Apply / Override / Note. The FHA conditional findings
(compensating-factors, LP-84; subject-to-repair, LP-85) need a way to ACKNOWLEDGE a real finding the processor
proceeds with — distinct from Override (which dismisses a finding as not-applicable). And a finding often needs a
document request to resolve.

**Decision:**

- **Accept-risk** reuses the EXISTING `FindingResolutionStatus.ACCEPTED_RISK` state (already in the model — no
  migration). New service `accept_risk_finding` + endpoint `POST …/findings/{id}/accept-risk` (optional reason —
  the compensating factor / rationale). It is a terminal resolution (like override) but semantically "a real
  finding, accepted" — for the FHA mitigable conditional model. Activity-logged as `FINDING_RESOLVED` with
  `resolution=accepted_risk`.
- **Request-docs** reuses `create_needs_item(origin=FINDING)` (no migration). New service
  `request_docs_for_finding` + endpoint `POST …/findings/{id}/request-docs` (optional note): creates a needs item
  (priority from the finding severity — RED→blocking) the borrower must satisfy, and marks the finding
  (`details.docs_requested`) so the tab shows the linkage. The finding stays OPEN (the request doesn't resolve
  it). Activity-logged as `NEEDS_ITEM_CREATED`. The needs list + Phase-4 communication act on the needs item.

Both return the re-filtered `VerificationStatusPublic` (one round-trip; the tab + the needs list refresh). The
needs item carries the finding linkage in its reasoning (no `source_finding_id` FK to verification findings yet —
that's a future model addition if direct traceability is needed).

**Rationale:** both reuse existing model states/services (no migration), keeping the change to two thin endpoints
+ service wrappers; accept-risk vs override is a real semantic distinction the FHA conditional findings require.

**Consequences:** the full disposition vocabulary is now Apply / Override / Accept-risk / Request-docs / Note.
A `source_finding_id` FK from needs to verification findings + a live request→communication wire-up are future
seams.

## ADR-212: Phase-3 hardening capstone — the stuck-RUNNING watchdog, real-stack worker testing, performance, error paths (LP-89)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** the verification system is built (LP-74..88) but carries known loose ends from the build history
that would break a real demo: a run could spin RUNNING forever with no recovery; the worker-seam bugs all passed
unit tests but failed in the real stack; the engine now evaluates ~120 rules; edge-case files shouldn't crash.

**Decision:** harden (don't rebuild):

- **The stuck-RUNNING watchdog** — a read-time reconcile in `GET …/verification`: a run RUNNING past a 5-minute
  timeout (above the Celery hard limit of 180s + slack) is marked FAILED with a legible error, so the UI never
  spins forever and can re-run. No Celery-beat needed; the task already has time-limits + retry→FAILED.
- **Real-stack worker integration testing** — `tests/integration/test_cross_source_worker.py` invokes the actual
  task body (`app.tasks.cross_source._run`) end-to-end (the AI stubbed, the session pointed at the test DB) and
  asserts the run COMPLETED + the findings persisted; paired with the standing task-registration guard. This is
  the standing answer to the worker-seam lesson (unit tests missed those bugs). (`run_cross_source` now resolves
  its reasoner at call time so the worker path is stubbable.)
- **Performance** — a test bounds the deterministic engine under the full rule load (< 3s on a real file); the
  deterministic pass is sub-second, the AI cross-source pass is the async/expected-slow part.
- **Error-path robustness** — tests confirm a file with no data / no docs / FHA / partial extraction doesn't
  crash: the calculators show "—" (cannot compute), the engine records absent-fact rules not-evaluated.

**Consequences:** the demo runs solidly. A periodic beat-sweep watchdog (for never-read files) is a small V2
follow-up; the read-time reconcile covers the demo + the normal path.

## ADR-213: The validation aid + the grounded_starter → validated state model (LP-89)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** every rule (LP-82..86) + calculator methodology (LP-87) is GROUNDED-STARTER — researched against the
real sources but NOT validated by the domain expert (Priya). Her session is the validation. Claude Code cannot do
that validation (it requires her judgment on real files). What's buildable is a tool that captures her verdicts.

**Decision:** build a validation aid (Option B) that CAPTURES verdicts; it does NOT validate:

- **The starter inventory** — a service enumerates every grounded-starter item (Conventional + FHA + cross-source
  rules + the calculator methodologies) with its program, category, description, value/op/unit, citation, source
  type, and the `to_verify` marker. ~123 items, grouped/filterable (program / category / status).
- **The verdict capture** — a new `validation_verdicts` table (company-scoped, self-audited: actor + timestamps +
  the corrected value ARE the LP-80.5 value-recording trail) records the verdict per item: VALIDATED / CORRECTED
  (a new value + note) / FLAGGED_REMOVE (+ why) / ADD_NEW (a missing rule's description). Admin-gated, tenant-scoped.
- **The validation_status state** — each item's status is derived: `grounded_starter` (the DEFAULT — no verdict),
  `validated`, `corrected`, or `flagged_remove`. The grounded-starter→validated transition is explicit + queryable
  ("what still needs validation" = the grounded_starter count).
- **The honesty rule** — a corrected value applies because PRIYA said so (recorded with attribution), not because
  the system decided. The aid never auto-validates; until a verdict exists, the item is grounded-starter. Nothing
  is claimed "validated" on the strength of the grounding alone.

**Rationale:** the aid makes her session systematic + lossless without overstepping — it records her judgment, it
does not fabricate it. The default-grounded_starter state keeps the system honest about what's actually validated.

**Consequences:** after her session, the recorded verdicts drive the follow-up corrections. The verdict store is
company-scoped (each company validates for its own lenders); a future step applies validated/corrected verdicts
back into the rule definitions.

## ADR-214: V1 boundaries — the explicit V2 deferrals (LP-89)

- **Date:** 2026-06-29
- **Status:** Accepted

**Context:** an honest V1 records what it deliberately does NOT do, so the boundaries are explicit rather than
gaps discovered later.

**Decision:** document the deferrals (`docs/v2-deferrals.md`): the domain validation of the rules/methodologies
(grounded-starter pending Priya — the aid captures, doesn't validate); auto-detected FHA compensating factors
(the human documents them); auto-re-run of verification (manual trigger by design); the live engine reading DB
overlays (the admin UI manages the store; wiring enforcement is V2); bounding boxes (page+snippet, not pixel); a
needs→finding FK; S3/MinIO validation-before-deploy; the hard-delete admin + restore/trash (LP-79.5 deferral);
and the full Phase-4 communication (Request-docs is the seam).

**Consequences:** Phase 4 (communication) + the V2 list are the named next work. The boundaries are legible to the
team + to Priya.

## ADR-215: Expose valuation_amount on the Overview + make the LTV appraised-value source explicit (LP-90)

- **Date:** 2026-06-30
- **Status:** Accepted

**Context:** the LTV calculator's appraised-value basis reads `appraised = valuation_amount or estimated_value`
(`valuation_amount` wins). But `valuation_amount` (the MISMO `PropertyValuationAmount`) was NOT in the property
read schemas (`PropertyResponse`, the loan-file detail's `PropertyPublic`) and NOT in the Overview editor — only
`PropertyUpdate` accepted it. So it was a **hidden field that silently shadowed** the editable `estimated_value`:
a processor who edited "Estimated value" on the Overview saw the LTV not move (whenever `valuation_amount` was
non-null, e.g. on any MISMO-imported file), with no on-screen explanation of why.

**Decision:** a focused fix — expose the field, don't restructure the model.

1. **Expose `valuation_amount` (read).** Add it to `PropertyResponse` and to the loan-file detail's
   `PropertyPublic` so the Overview can read it. The PATCH/audit/mark-stale path is already generic (LP-80.5), so
   editing it is recorded from→to and marks verification stale with no new endpoint work.
2. **Make it editable on the Overview.** Add it to the Subject Property card (displayed read-only) and the inline
   `PropertyEditor` (an EditableRow `money` field). The existing `useUpdateProperty` mutation already invalidates
   the `dti`/`ltv`/`verification` query keys, so the edit flows straight through to the LTV — **this is the core
   fix**: the field the LTV reads is now the field the processor can edit.
3. **Make the LTV basis source explicit.** Add `appraised_value_source` to `LtvCalculation`
   (`"valuation_amount"` | `"estimated_value"` | `null`), computed alongside the auto value-lines. The calculator
   renders a plain-language sub-line under the value basis ("Appraised value *from valuation amount*" /
   "*from estimated value*") with the literal logic `appraised = valuation_amount or estimated_value` in a tooltip.
   No hidden field, no mystery about which number drives the basis.

**Explicitly NOT done (flagged for Priya / deferred):**
- **Did not rename "Appraised value."** Whether `valuation_amount` (an AVM/stated valuation) should be labeled
  "appraised value" at all is a domain-naming question for Priya — the basis label is unchanged here.
- **Did not collapse `valuation_amount` + `estimated_value`** into one field. Whether the model should carry two
  distinct subject-property values, and which is authoritative, is a data-model decision deferred + flagged.
- **Did not change the LTV computation** (the lesser-of basis, the `valuation_amount or estimated_value`
  precedence) or touch the MISMO parser (it correctly scopes `valuation_amount` to the subject property).

**Consequences:** editing the subject-property valuation on the Overview now moves the LTV, and the processor can
see which value the basis came from. The naming + model-collapse questions are recorded for Priya rather than
silently resolved.

### ADR-215 addendum (LP-90.1): the source transparency, finished

A screenshot review of LP-90 found the transparency was only half-wired:

1. **The tooltip was dead.** The "(?)" in the Value basis row was an `aria-hidden` glyph with no handler; the
   literal logic was only in a native HTML `title` attribute on the parent div — unreliable (long delay, never
   fires on touch, unstyled) and lacking the plain explanation. The codebase had no tooltip primitive.
2. **The editable row had no source clarity.** The PROPERTY VALUE section's *editable* "Appraised value" row —
   the one the processor actually interacts with — carried no source label/tooltip at all.
3. **The "Stated" sublabel was a mislabel.** That row's sublabel read "Stated", but the appraised value is sourced
   from `valuation_amount`/`estimated_value`, not borrower-stated.

**Decision (a small follow-up, no model/computation change):**
- Add a real, accessible tooltip primitive (`components/ui/tooltip.tsx`, shadcn/Radix —
  `@radix-ui/react-tooltip`) and use it in **both** places. The content is the literal logic
  `appraised = valuation_amount or estimated_value` **plus** a plain explanation ("uses the property valuation
  amount; if absent, falls back to the estimated value; no appraisal document is on file yet").
- The PROPERTY VALUE editable "Appraised value" row now shows the same `from valuation amount` / `from estimated
  value` source label + the working tooltip, mirroring the Value basis row.
- That row's sublabel is corrected from "Stated" to the real provenance (the source label; falls back to the
  humanized source — "Manual" — only when neither value is present). The "Purchase price" row stays "Stated" (it
  *is* stated from `SalesContractAmount`).

This is a UI/labeling fix only: the LTV computation, the lesser-of logic, the "Appraised value" **main** label,
and the field bindings (all set by LP-90/LP-77) are unchanged; the valuation/estimated model-collapse and the
main-label naming question remain flagged for Priya.

## ADR-216: The DTI consumes the MI calculator — fixing MI omitted from PITI (LP-91)

- **Date:** 2026-06-30
- **Status:** Accepted

**Context:** the DTI calculator's PITI **mortgage-insurance** line (`housing.mortgage_insurance`) was a
*manual-only* line — auto value `None`, source `"manual"` — so unless a processor hand-entered it, MI contributed
`$0`. But MI is **mandatory**: every FHA loan carries monthly MIP, and every Conventional loan with LTV > 80%
carries PMI. So by default the DTI **omitted a mandatory monthly obligation**, understating the front-end DTI for
every FHA file and every low-down Conventional file — and understating it in the **qualifying (dangerous)
direction**: a borrower truly at 44% DTI could show ~41% (missing ~$300/mo MI) and appear to pass a lender ceiling
they'd actually fail. This is a correctness gap in the headline "transparent DTI that beats ChatGPT" surface, and
visibly wrong on the first real FHA file. Meanwhile the LP-87 MI calculator already computes the correct,
program-aware monthly premium — but nothing consumed it (separate namespaces; a two-source-of-truth gap, the same
shape as the LP-90 appraised-value binding).

**Decision:** wire the DTI's MI line to **consume** the MI calculator's `monthly_premium` as its auto value —
single source of truth, live.

1. **Extract one shared MI computation** into `app/services/mi.py` (`compute_loan_mi`) — the program-aware
   dispatch (sources LP-77's LTV, the base loan, the persisted MI overrides, LP-84's FHA UFMIP rule; calls the pure
   `compute_conventional_pmi` / `compute_fha_mip`). It imports neither `dti` nor `calculators`, so **both** consume
   it with no import cycle. `build_mi_view` (the MI calculator) is refactored to delegate to it (output unchanged);
   `dti._auto_housing_lines` consumes its `monthly_premium`.
2. **Program-aware, inherited:** Conventional → monthly PMI when LTV > 80% (`$0`/not-required at ≤ 80%); FHA →
   monthly annual-MIP always. No PMI/MIP logic is duplicated in the DTI.
3. **Auto-populated but overrideable:** the consumed premium is the *auto* value (source `manual` → `computed`); a
   `DtiOverride` on `housing.mortgage_insurance` still wins (the processor enters the real MI quote).
4. **Upfront MIP stays financed:** only `monthly_premium` enters PITI; the FHA UFMIP (1.75%) is financed into the
   loan, never a monthly DTI item.
5. **Recompute on MI change:** the DTI reads MI live, so an LTV change (→ PMI on/off), a program change, or an MI
   override flows through; the frontend MI-override mutation now also invalidates the DTI query.

**Grounded-starter (validate with Priya):** the **mechanism** (the DTI must include mandatory MI) is not in
question — omitting it is wrong regardless. But the Conventional **PMI rate** is a grounded-starter (it varies by
credit / LTV / MI provider — a rate card, not a clean formula); the auto-computed PMI is a starting point the
processor overrides with the real quote, surfaced via the MI calculator's `methodology.starter` note. The FHA MIP
rates (HUD via LP-84) are more deterministic.

**Consequences:** the FHA and low-down-Conventional DTIs are no longer understated; the MI calculator and the DTI
share one number (no divergence). The two-source-of-truth lesson — calculators must **consume** one source, not
omit or duplicate — is now applied to MI as it was to the appraised value. The PMI rate is recorded for Priya.

## ADR-217: Readable finding labels — teach the finding-display layer about the `xsrc.` namespace (LP-92)

- **Date:** 2026-06-30
- **Status:** Accepted

**Context:** deterministic cross-source findings displayed an ugly raw-rule-id meta-label — e.g. "Xsrc Income
Employer Count Matches Items" — that means nothing to a processor. Root cause: the LP-81 finding-display layer
(`frontend/lib/verification/finding-display.ts`) was keyed on the **`cross_source.`** prefix (the LP-78 AI
cross-source namespace). `findingType` stripped only that prefix, and `findingTypeLabel` fell back to prettifying
the **raw rule_id** when `findingType` returned null. The LP-86 **deterministic** cross-source rules use the
**`xsrc.`** prefix, so they never matched → the meta-label degraded to the prettified full rule path. (The
**headline** was already fine: for `xsrc.*` it falls through to `finding.message`, which the backend renders
readably, e.g. "Stated employer count (2) does not match the income-item count (3)." So this was the secondary
gray meta-label only.)

**Decision (frontend-only — the backend message was already readable):**
- `findingType` now recognizes + strips **both** namespaces (`cross_source.` and `xsrc.`), so an `xsrc.*` finding
  resolves to a type instead of null (the headline/detail behavior is unchanged — the stripped `xsrc.` remainder
  is not a TEMPLATES key, so the headline stays `finding.message`).
- `findingTypeLabel` is now readable and category-based, and **never** returns a raw rule_id:
  - AI cross-source (`cross_source.*`): the canonical type, e.g. "Income Variance" (unchanged — no regression).
  - Deterministic cross-source (`xsrc.*`): the finding's **category** + a descriptor, e.g.
    "Income · Cross-source check".
  - Anything else (single-source `conv.*` / `fha.*`, document findings): the readable **category** label ("Income"
    / "Credit" / …), with a generic "Verification check" fallback for an unknown category — never "Conv Dti …".

**Consequences:** no finding shows a raw-rule-id-derived meta-label anywhere; the deterministic cross-source
findings read as clean category checks; the AI-layer labels and the headline are untouched. This is the first,
quick-win ticket of the finding-presentation epic (LP-92..98) — later tickets cover dedup/re-run (LP-93/94), the
card restructure (LP-95), the AI why/fix (LP-96), View-fix (LP-97), and Undo (LP-98).

## ADR-218: Normalized-substance finding identity + dedup (LP-93)

- **Date:** 2026-06-30
- **Status:** Accepted

**Context:** the same discrepancy worded two ways showed as **two** Open findings. The live case:
`xsrc.income.employer_name_consistency` fires once per documented-employer string, and two documents carried the
SAME employer differing only in case + dash — "Thermofisher Life Science **–** PPD Development LP." vs
"THERMOFISHER LIFE SCIENCE **—** PPD DEVELOPMENT LP." The rule's own comparison key (`_norm`) folds case +
whitespace but NOT the en-dash/em-dash, so the two were distinct subjects → two findings for one employer. More
broadly, both cross-source emission paths (deterministic `xsrc.*` and AI) supersede-open + preserve-resolved and
re-emit, but had **no normalized-substance dedup at emission** — so within-run wording variants (and a re-detected
resolved finding) duplicated.

**Decision:** give every finding a **normalized-substance identity** and dedup on it at emission
(`app/services/finding_identity.py`):
- **Identity** = `(canonical type/rule, normalized subject)`. The subject is the deterministic rules'
  `details.subject_key`, else the AI layer's `stated_value`/`document_value`. `normalize_text` is **deterministic
  textual only**: NFKC, dash variants → `-`, curly quotes → straight, case-fold, whitespace-collapse. **No
  fuzzy/semantic matching.**
- **Dedup at emission** (both the deterministic and the AI loops): seed a `seen` set from the file's live findings
  (`existing_identities`) — which after supersede includes the preserved RESOLVED ones — and skip a fresh finding
  whose identity is already present. So the same substance is emitted **once** (the first kept, with its wording),
  and a re-detected resolved finding is skipped → its resolution is **preserved**, not reopened or duplicated.
- **Uniform** across origins; **conservative** — a genuine textual difference ("Thermofisher" vs "Thermo Fisher
  Scientific"), a different employer/amount/document, or a different type stays a **separate** finding (the subject
  disambiguates; normalization never over-collapses).

This **refines** LP-81's stable-identity/preserve-resolved emission — it adds subject normalization + an
emission-time dedup; it is not a parallel identity system. The deterministic rules still fire (their canonical type
still marks the AI defer) — only persistence dedups.

**Consequences:** the Thermofisher duplicate collapses to one; distinct subjects stay separate; resolutions survive
re-detection. Scope boundary: the **drop-when-no-longer-detected** re-run change is LP-94 (next) — the merge/
supersede behavior is otherwise unchanged. Part of the finding-presentation epic (LP-92..98).

## ADR-219: Re-run reconciliation — merge currently-detected, DROP no-longer-detected (open) (LP-94)

- **Date:** 2026-07-01
- **Status:** Accepted

**Context (a trace correction):** the plan framed this as "reverse LP-81's *mark as no-longer-detected*." The trace
found there was **no mark mechanism** — the live re-run (`run_cross_source`) *superseded* (soft-deleted) every OPEN
cross-source finding and re-emitted the fresh set. That already *dropped* no-longer-detected open findings and
*retained* resolved ones (supersede was open-only), and the LP-78.1 input-fingerprint cache short-circuits the pass
entirely on unchanged inputs, so a no-op re-run touched nothing. The real gap vs the locked Q4 design was the
opposite: supersede+recreate **churned still-detected OPEN findings** — each run deleted and re-created them as NEW
rows, losing their id and any `details["notes"]`/history. So "merge keeps history" (LP-81's stated intent) was not
actually true.

**Decision:** replace supersede+recreate with an explicit **reconcile-in-place** (`app/services/finding_reconcile.py`,
`reconcile_findings`), compared by LP-93's normalized identity, used by both cross-source emission paths:

1. **still-detected OPEN → MERGE:** keep the *existing row* (id, notes/history, resolution preserved); the fresh
   duplicate is discarded. (Now a true merge — previously churned.)
2. **no-longer-detected OPEN → DROP** (soft-delete): the issue is gone, so the finding is gone — the list stays
   honest to the current state (the Q4 decision, made explicit and intentional rather than an incidental effect of
   supersede).
3. **still-detected RESOLVED → resolution preserved** (kept, not reopened, not duplicated — LP-93).
4. **no-longer-detected RESOLVED → RETAINED** (the careful case): a resolved finding is a *completed processor
   action*, not clutter. Its `resolution_status` + `applied_record` + audit trail survive — an APPLIED finding's
   data change and LP-98's Undo depend on the record. "Drop" targets OPEN findings only.
5. **genuinely-new → ADD.**

Within-run duplicates collapse (LP-93). The AI pass reconciles its own AI-origin findings and dedups against the
deterministic set via `external_identities` (never dropping findings another pass owns). An unchanged re-run drops
nothing (the LP-78.1 cache returns the prior run without a pass).

**Consequences:** the findings list reflects the current state (stale open findings drop), while completed actions
and their Undo/audit records persist. Still-detected findings keep their identity + notes across runs (the churn +
note-loss are fixed). This subsumes LP-93's emission-time dedup + LP-81's supersede into one coherent reconcile; no
UI marker was needed (dropped findings simply leave the tab query). Part of the finding-presentation epic
(LP-92..98); the Resolved-section UI (LP-95) and Undo (LP-98) build on resolved findings being retained here.

## ADR-220: Finding card restructure — four-part layout + progressive disclosure (LP-95)

- **Date:** 2026-07-01
- **Status:** Accepted

**Context:** a finding communicates four things authored by two sources: **What we found** + **Source** (the
trustworthy deterministic core — already stored: `message`, `details.reasoning`, `source_page`/`source_snippet`)
and **Why it matters** + **Suggested fix** (fallible AI help — added/populated in LP-96). The old card mixed the
description, meta, and a source-gated expander in one block, and the AI help was not yet slotted.

**Decision:** restructure `finding-card.tsx` into the four-part layout with **progressive disclosure**:

- **Collapsed (default):** headline (`finding.message`) + a one-line "what we found" (the AI specifics / a summary,
  omitted for deterministic findings whose headline already carries the specifics — no duplication) + the readable
  meta (LP-92's `findingTypeLabel` · confidence · origin badge · overlay · docs-requested) + the action buttons.
  Understandable + actionable **without expanding** — the list stays scannable.
- **Expanded (a single "Details" affordance — no longer source-gated):** the four clearly-headed sections —
  **What we found** (`details.reasoning`), **Why it matters** (slot), **Suggested fix** (slot), and **Source** (the
  document page + verbatim snippet view-source, plus the authority = the LP-92 label + origin). The fallible AI
  why/fix live **on expand**, behind a deliberate open — not inline by default.
- **Graceful degradation (the critical constraint):** the Why-it-matters / Suggested-fix slots render **only when
  populated**. LP-96 hasn't added them, so today they're absent — no empty boxes, placeholders, or gaps. The card
  looks complete + intentional with just What-we-found + Source, and LP-96 drops its content into the ready slots
  with no rework.
- **Resolved findings render compact** — headline + disposition + a what-was-done line (reason / "Applied …"); no
  expander, no four-part. (The Resolved-section placement + Undo are LP-98.)

**Consequences:** the card is the display foundation for LP-96 (AI why/fix), LP-97 (View fix), and LP-98 (Undo). It
reuses existing stored data (no backend/model change) and preserves LP-92's readable labels and LP-93/94's
identity/re-run. Part of the finding-presentation epic (LP-92..98).

## ADR-221: AI-generated "why it matters" + "suggested fix" — the guard-railed AI-boundary relaxation (LP-96)

- **Date:** 2026-07-01
- **Status:** Accepted

**Context:** a finding already explains WHAT fired + WHY-it-fired deterministically. LP-96 adds an AI-authored
**why it matters** (the consequence) + **suggested fix** (the remediation) to fill LP-95's slots. This is the ONE
deliberate relaxation of the project's "AI never touches authoritative output" principle — AI-generated prose enters
the finding — so it is decision-SUPPORT, not automation, made safe by guardrails.

**Decision (implement ALL the guardrails):**

1. **Generated once, stored, NEVER per-run.** Guidance is keyed **per canonical finding type** (the key both the
   deterministic `xsrc.*` rules and the AI findings share), in a grounded-starter store
   (`app/verification/finding_guidance.py` `GUIDANCE_BY_TYPE`), resolved by a **plain dict lookup at read time**
   (`FindingPublic.from_model` → merged into `details` for LP-95's slots). Novel AI findings generate their guidance
   **once at discovery** (best-effort, stored on the finding); LP-94's reconcile keeps the row on re-run, so it is
   never regenerated. Rendering a card / re-running verification makes **no model call** and yields identical text
   (no flicker, no per-view cost) — the A+C combination (AI writes it once; it's stored + shown deterministically).
2. **Grounded in the rule's facts.** The generator (`generate_guidance`, reusing the app's `complete()` at
   temperature 0.0) is given the type + category + description + threshold and asked to EXPLAIN them — not to invent
   facts or cite regulations it wasn't given.
3. **Grounded-starter, validate-with-Priya.** `starter=True` — researched-and-grounded, NOT authoritative; the
   domain expert confirms/corrects it, exactly like the rule thresholds.
4. **Warned** — the block carries a clear-but-calm "AI-generated — verify before relying on this; it may be wrong."
5. **Visually distinct** — the why/fix block is tinted + bordered + iconned (a `Sparkles` amber block), set apart
   from the deterministic core (What we found + Source), so the processor always knows fact from AI explanation.
6. **Overrideable** — the existing Override action still wins; the guidance is advisory.

**Honesty note:** the committed `GUIDANCE_BY_TYPE` is the **grounded-starter** content (authored deterministically
from each type's meaning). The AI-authoring *mechanism* — `generate_guidance` + the one-time idempotent pass
(`app/scripts/generate_finding_guidance.py`) — produces the richer, lender-specific prose when run with an API key;
its output is reviewed + validated by Priya before it lands (same grounded-starter → validated posture as the rule
content). Generation failure is graceful: no guidance → the card still renders (LP-95).

**Consequences:** findings now explain why-it-matters + how-to-fix, without any per-run AI cost or flicker, and
without letting the AI decide anything — the deterministic core + human judgment still rule. This is the one
sanctioned place the AI-boundary is relaxed; the guardrails are what make it safe. Part of the finding-presentation
epic (LP-92..98); LP-97 (View fix) + LP-98 (Undo) build on it.

## ADR-222: View fix — the dry-run itemized before/after impact preview (LP-97)

- **Date:** 2026-07-01
- **Status:** Accepted

**Context:** applying a finding changes structured data → the DTI/LTV recompute (LP-75/76/77). Before committing,
the processor should see EXACTLY what will change — especially a limit crossing — not a bare "Apply". Findings that
carry an **apply-spec** (`details.apply`; currently ~the undisclosed-debt `add_liability` → DTI-recompute) get a
"View fix" impact preview; findings without one keep Override / Accept-risk / Request-docs / Add-note (they change
no numbers — nothing to preview).

**Decision:** a **dry-run** that REUSES the real apply→recompute — one source of truth, never a parallel
computation that could diverge.

- **The dry-run** (`app/services/finding_impact.py` `preview_finding_apply`): snapshot the DTI/LTV **before**; open a
  **savepoint**; run the **real** `apply_finding` (which performs the structured-data change + fires the recompute);
  snapshot the DTI/LTV **after**; **roll the savepoint back** + refresh the objects → nothing persists. So the
  preview MATCHES what Apply actually does. Served read-only at `GET …/findings/{id}/apply-preview` (never commits;
  a 400 for a finding with no apply-spec).
- **The itemized preview** reuses the existing, already-line-itemized calculator schemas (`DtiCalculation` before +
  after) — so the dialog shows the change, each affected debt line (the **new** one highlighted, `NEW`), the totals
  with deltas, the qualifying income, the recomputed **back-end DTI** (before → after), and the **limit-status
  crossing** ("Within limit → Over limit"). Only the calculator(s) the apply moves are returned.
- **Confirm / cancel:** "Apply fix" runs the EXISTING real apply endpoint (`apply_finding` → APPLIED +
  `applied_record` + the real recompute) — what was previewed is what happens; Cancel is a no-op.
- **Reversibility (for LP-98):** the real apply already records enough before-state to reverse — `applied_record`
  carries the created `liability_id` (add) / the `from`→`to` (income). Verified here; Undo is built in LP-98.

**Consequences:** the processor sees the new math (esp. a limit crossing) before committing, and the preview can't
drift from the apply (same code, dry-run vs. commit). Apply-specs are currently rare (~undisclosed-debt); the flow
is general (any apply-spec). Part of the finding-presentation epic (LP-92..98); LP-98 (Undo + the Resolved-section
placement) builds on the reversible apply.

## ADR-223: Undo for resolved findings + the Resolved section (LP-98) — the epic's close

- **Date:** 2026-07-01
- **Status:** Accepted

**Context:** LP-97 made Apply previewable (View fix); a processor's resolutions should also be reversible. Resolved
findings sit in a **Resolved section** below the open findings (LP-94 retains them across re-runs), each compact
(what-was-done + effect). This ticket adds **Undo** — and Undo of an APPLIED finding must reverse a *data change*
and recompute, the epic's highest-risk piece.

**Decision:** a type-specific reversal (`app/services/finding_resolution.py` `undo_finding`), reusing the recorded
before-state — exact, not approximated.

- **Undo-APPLIED** → reverse the data change by RESTORING the recorded pre-apply state from `applied_record` (LP-97
  verified it captures enough — the one source of truth): `add_liability` → soft-delete the *exact* liability that
  was added (by its `liability_id`); `correct_income` → restore the income item to its recorded `from` value. Then
  `mark_recompute_needed` — the DTI/LTV read live, so they recompute back to their **exact** pre-apply values. The
  finding returns to OPEN (its `applied_record` cleared). We restore the recorded row/value rather than subtracting
  an amount, so the reversal is exact even if other things changed.
- **Undo-OVERRIDDEN / Undo-ACCEPTED_RISK** → just flip to OPEN (they made no data change).
- **Audited** — `ActivityType.FINDING_UNDONE` (a new activity type + a CHECK-constraint migration), recording who /
  when / the reversal. Tenant-scoped (the reversal only touches the finding's own file). A non-resolved finding →
  `CannotUndoError` (400).

**Composition with LP-94:** resolved findings are retained → they populate the Resolved section → undoable. After
Undo-Applied the data is reversed and the finding is OPEN, so the (now un-applied) issue **re-detects** on the next
run — correct. After Undo-Accept/Override it's a normal open finding again. No conflict.

**Consequences:** nothing a processor does is one-way — **View fix previews before Apply (LP-97), Undo reverses
after (LP-98)**. `FindingPublic` now exposes `applied_record` (the Resolved-card effect + the Undo basis). This
**completes the finding-presentation epic (LP-92..98)**: readable labels (92), normalized-substance identity +
dedup (93), re-run reconcile (94), the four-part card (95), AI why/fix (96), View fix (97), and Undo + the Resolved
section (98).

## ADR-224: Populate `refinance_type` from MISMO + surface the undetermined refi (LP-99)

- **Date:** 2026-07-01
- **Status:** Accepted

**Context:** `refinance_type` (`rate_term` | `cash_out`) exists on `LoanFile` and the LTV engine already resolves the
cash-out limit from it correctly — but **nothing populated it**. A cash-out refi imported from MISMO landed
`refinance_type = NULL`, and the LTV treats null-as-rate/term → the **looser** limit. So a cash-out refi (whose max
is *stricter*) silently got the rate/term max — a permissive-direction safety bug. First ticket of the refinance
epic (LP-99..101).

**Decision:** parse the MISMO cash-out determination at import and fill `refinance_type`, so the LTV's *existing
correct* path auto-triggers — the engine is untouched.

- **Source:** `LOAN/REFINANCE/RefinanceCashOutDeterminationType` (`CashOut` → `CASH_OUT`; `NoCashOut` /
  `LimitedCashOut` → `RATE_TERM`), with `RefinanceCashOutAmount` as a fallback (positive ⇒ cash-out, zero ⇒
  rate/term). `LimitedCashOut → RATE_TERM` (agency LCOR carries rate/term limits) is a **grounded starter, pending
  expert review**, alongside the LP-74 LTV thresholds it feeds.
- **Undetermined ⇒ SURFACE, never silently looser.** A refi with no cash-out signal keeps `refinance_type = NULL`
  and is surfaced two ways: a **parse warning** on the `MismoImport` and a **FLOOR needs item** ("Confirm refinance
  type"). It is never defaulted to the looser limit behind the processor's back. (The LTV still reads
  null-as-rate/term for a not-yet-corrected file — we don't block the calculator — but the ambiguity is now visible
  and actionable.)
- **Correction path made real.** The needs item directs the processor to "set it on the Overview," but
  `refinance_type` was in `_VERIFICATION_BASELINE_FIELDS` (editing marks verification stale) yet **absent from
  `LoanFileUpdate`** — unsettable. LP-99 adds it to `LoanFileUpdate` (PATCH) and `LoanFileDetail` (read), and the
  Overview loan editor shows a **Refinance type** select **only for refinances**.
- **Only refinances.** Purchases are entirely unaffected — no field set, no needs item, no warning, no UI control.

**Scope boundary:** the LTV engine is deliberately unchanged (it was already correct — the bug was an unfilled
field). Purpose-gating rules (LP-100) and a real refi MISMO fixture + e2e (LP-101) are the rest of the epic; LP-99's
refi variant is *constructed* from the one real (purchase) fixture, so the cash-out mapping is validated
structurally, not against a real refi export.

**Consequences:** cash-out refis now get their stricter LTV limit automatically; an ambiguous refi is caught and
corrected instead of silently mis-limited. `LoanFileDetail`/`LoanFileUpdate` gain `refinance_type`; editing it marks
cross-source verification stale (a baseline change, same as any LTV input).

## ADR-225: A PURPOSE dimension in the rules applicability framework (LP-100)

- **Date:** 2026-07-01
- **Status:** Accepted

**Context:** the rules applicability framework had no PURPOSE dimension — `ApplicabilityScope` is
`ALL_LOANS | PROGRAM | LENDER` only, and `RuleGate` keys on typed numeric facts (is_manual, property type), not
`loan_purpose`. So a rule could not be declaratively scoped purchase-only / refi-only. The visible consequence: the
purchase-agreement doc rule (`conv.docs.purchase_agreement_present`) — whose description says "(purchase
transactions)" but nothing ENFORCED it — **fired on refinances**, flagging a missing purchase agreement a refi
legitimately doesn't have → a spurious YELLOW finding. Second ticket of the refinance epic (LP-99/100/101);
consumes LP-99's parsed `refinance_type`.

**Decision:** add a PURPOSE dimension to the applicability framework — don't special-case one rule.

- **`PurposeScope`** (`purchase` / `refinance` / `cash_out` / `rate_term`) is a new field on `Applicability`,
  ORTHOGONAL to `scope` — it COMPOSES with the program/lender scope + `RuleGate` (a rule can be "Conventional AND
  purchase-only"). `None` = every purpose (the default — the ~110 existing rules are unchanged).
- **Enforced per-rule in the engine**, parallel to `RuleGate` (not at `registry.resolve`, so the LTV/DTI calculators
  that resolve through the registry are untouched). `engine.evaluate` + `cross_source.engine.evaluate_cross_source`
  take `loan_purpose` + `refinance_type` (from the `LoanFile`, LP-99) and SKIP a purpose-mismatched rule
  (`evaluated=False`, never a finding) via the pure `purpose_applies`.
- **UNDER-GATE, not over-gate (the safe direction):** `purpose_applies` skips a rule ONLY on a *known* mismatch; an
  unknown purpose (or unknown `refinance_type`) errs toward APPLYING the rule. Wrongly gating a rule OFF could HIDE a
  real finding (dangerous); an extra over-flag is safe. Only CLEARLY purpose-specific rules were gated:
  `conv.docs.purchase_agreement_present`, `fha.doc.pre_appraisal_sales_contract`, and the cross-source
  `xsrc.terms.price_vs_contract` → PURCHASE-only. Ambiguous rules stay ALL-purpose + flagged: e.g.
  `fha.doc.case_number_and_amendatory_clause` keys on the case number (which ALL FHA loans, incl. refis, need) —
  only its amendatory-clause sub-part is purchase-specific, so it stays ungated (splitting it is a Priya follow-up).
- **`conv.ltv.purchase_max` / `fha.ltv.purchase_max` deliberately NOT gated** — they are the "purchase / rate-term"
  maximum a rate-term refi SHARES (LP-99); gating them purchase-only would wrongly drop the limit for rate/term refis.
- **DTI stays program-based** — refinance doesn't change DTI limits; DTI rules are never purpose-gated.
- **Refi need-set:** the needs floor gained the refi analog of the purchase-agreement need — a REFINANCE seeds the
  **existing mortgage statement** + **payoff statement** (grounded starter; subordination for a 2nd lien flagged,
  not built).

**Grounded-starter:** which rules are purpose-scoped + the refi need-set are domain judgments — flagged
validate-with-Priya on each gated rule + the need-set.

**Consequences:** purchase-specific rules no longer fire on refinances (the spurious purchase-agreement finding is
gone); the framework can now scope any rule by purpose declaratively; rate-term refis keep the shared LTV limit; DTI
is unaffected. LP-101 (a real refi MISMO fixture + e2e) will validate this end-to-end.

## ADR-226: The extraction/reasoning AI tier runs on Opus 4.8

- **Date:** 2026-07-01
- **Status:** Accepted

**Context:** the app uses two Claude tiers (LP-37 wrapper): a cheap high-volume `anthropic_model_classification`
(Haiku) for document classification/summarization, and a more capable `anthropic_model_extraction` for the work
where quality matters — document data **extraction**, **cross-source reasoning**, and **needs/guidance** generation.
The extraction tier had been Sonnet.

**Decision:** move the extraction tier to **Opus 4.8** (`claude-opus-4-8`), the highest-capability model, for better
extraction accuracy and reasoning. The classification/summarization tier **stays on Haiku** (Opus there would be
wasteful for little gain). Both remain CONFIGURATION — env-overridable via `ANTHROPIC_MODEL_EXTRACTION` /
`ANTHROPIC_MODEL_CLASSIFICATION` — so a deployment can dial the tier without a code change. The `app/ai/cost.py`
`PRICING` table gains a `claude-opus-4-8` row (~$15/$75 per M in/out, ~5× Sonnet) so cost estimates stay meaningful
(an unpriced model silently estimates $0 + logs a warning).

**Consequences:** higher per-call cost on the extraction tier (~5× Sonnet on its high-token calls — full documents +
cross-source context), traded for better perception/reasoning quality. This affects **perception only**: the locked
Phase-3 principle is unchanged — the AI classifies/extracts, and the deterministic engine (LTV/DTI/rules/findings)
does the judging. Model strings stay TODO(models)/TODO(pricing) to verify against current Anthropic docs.

## ADR-227: Refi MISMO fixtures + an end-to-end refinance correctness SWEEP (LP-101)

- **Date:** 2026-07-01
- **Status:** Accepted

**Context:** the refi path (import → LTV → rules → findings → calculators) had NEVER run end-to-end through a real
import — only unit tests constructed `loan_purpose=REFINANCE` directly, and the one real MISMO fixture is a
Conventional PURCHASE (Mahesh). The project's recurring bug class is SEAMS between the import/model and the
calculators (the appraised-value, MI-in-DTI, and refinance_type binding bugs were all this shape, all biased
permissive), and the refi path had more such seams untested. Final ticket of the refinance epic (LP-99/100/101).

**Decision:** create two SYNTHETIC/de-identified refi MISMO fixtures + an end-to-end test that is a deliberate
**correctness sweep**, not a happy-path smoke test — its job is partly to FIND what's still broken on the refi path.

- **Fixtures** (`scripts/generate_refi_fixtures.py` → `tests/fixtures/mismo/refi_{rate_term,cash_out}.xml`): derived
  from the purchase fixture with all personal PII scrubbed to obviously-synthetic values, purpose flipped to
  Refinance, `SalesContractAmount` dropped (a refi has none), and a `REFINANCE` cash-out determination added (what
  LP-99 parses). Loan amounts chosen so each exercises its LTV limit: rate/term at 80% (passes the 97% cap), cash-out
  at 85% (**over** the stricter 80% cash-out cap — proving LP-99's populated `refinance_type` makes the stricter
  limit bind; it would pass the 97% cap). Grounded-starter test artifacts — a real refi export may differ.
- **Asserts LP-99** (refinance_type parsed → correct stricter cash-out limit; appraised-value-only basis) and
  **LP-100** (the purchase-agreement rule is skipped on a refi even with the doc fact present; the refi need-set
  seeds; DTI fires regardless of purpose), then **probes DTI / MI / reserves / max-loan** for refi-correctness.
- **Two seams surfaced, both CONSERVATIVE direction** (they over-state risk — never make a file look more qualified;
  handled honestly, never asserting a wrong value as correct):
  - **GAP-2 (reserves) — FIXED inline (small/safe/obvious):** the reserves down-payment default was `value − loan`
    (home equity), wrongly subtracted from a refi's eligible reserves. A refi has no down payment → now `0` for a
    refinance (purchase path unchanged). Direction of the old bug: conservative (understated reserves → spurious
    "insufficient").
  - **GAP-1 (DTI) — documented + `xfail(strict)`, follow-up LP-102:** the back-end DTI counts the existing first
    mortgage being paid off by the refi (we don't parse the MISMO payoff indicator), double-counting it against the
    new PITI. Direction: conservative (DTI over-stated → possible spurious over-DTI). NOT a safe inline fix — it needs
    payoff-indicator parsing + purpose-aware debt exclusion (a borrower's OTHER mortgages must still count). The
    xfail asserts the DESIRED behavior so the bug is never baked in as "correct".
- **MI ✓** computed on the refi (appraised-only) LTV, program-aware; **max-loan ✓** uses the appraised basis
  (inherits GAP-1 via its DTI ceiling); **LTV ✓** appraised-only + stricter cash-out limit.

**Consequences:** the refinance epic (LP-99/100/101) is COMPLETE. Refinance is proven end-to-end for what the
fixtures exercise; the reserves refi down-payment is fixed; and the ONE remaining gap (GAP-1, DTI double-count) is
KNOWN and tracked (xfail + a follow-up ticket), not hidden behind a falsely-green suite. The fixtures + refi
need-set + cash-out thresholds remain grounded-starters (validate-with-Priya).

## ADR-228: Silent extraction truncation → right-size the budget + a shared truncation guard (LP-102)

- **Date:** 2026-07-02
- **Status:** Accepted

**Context:** documents classified "Pay stub" extracted EMPTY (all fields blank → NEEDS_REVIEW) while W-2 / investment
succeeded on the same file. Root cause (confirmed against LF-6T3N: all 4 pay-stub extractions stored
`error_detail = "could not parse extraction"`, `tokens_used = None`): pay-stub extraction OVERFLOWED its 4096
`max_tokens`. A pay stub enumerates many earnings/deduction/tax line items (current + YTD), each emitted with a
verbatim snippet → the JSON response exceeded 4096 output tokens → the model TRUNCATED it mid-object
(`stop_reason == "max_tokens"`). No extractor checked `stop_reason`, so the cut-off body flowed into
`extract_json_object` (which needs a *balanced* `{…}`) → `None` → the extractor returned `failed("could not parse
extraction")` — misreporting a self-inflicted truncation as an unreadable document. It failed on both 9 KB and 204 KB
stubs (output verbosity, not input size). `investment_account` (also 4096) truncated on its densest doc too — the gap
was already systemic; Opus 4.8's more-thorough transcription makes any verbose type more likely to hit it.

**Decision:** two fixes.

- **Fix A — right-size the budget:** `pay_stub._MAX_TOKENS` 4096 → **8192** (matching `bank_statement`, the same
  "capture every line item" verbosity). The other verbose types were already bumped (bank_statement 8192, tax_return
  16384, divorce_decree 6144); pay stub had been left at the LP-39 scaffold value.
- **Fix B — a SHARED truncation guard (the primary, systemic fix):** a single
  `app.ai.extraction.model_call.run_extraction_completion` that every extractor now calls instead of `complete()`
  directly. It detects `stop_reason == "max_tokens"`, logs it **distinctly** (`extraction_truncated`, not a parse
  failure), retries **exactly once** at a high ceiling (16384 — one decisive jump), and if it STILL truncates surfaces
  an **honest** status/`error_detail` — `"response truncated - document too dense to extract in full"`, never the
  misleading "could not parse extraction". The retry fires **only** on truncation (never on other stop reasons, parse
  failures, or AI errors — more budget can't fix those); at most 2 attempts. A successful retry is transparent (the
  fields populate). This covers ALL ~18 extractors via the one shared path — pay stub was just the first to hit it.

**Rejected (Fix C):** dropping the per-field verbatim snippets to shrink the response — they are source provenance
for verification / the LP-43 drawer. We fixed the budget, not the provenance.

**Consequences:** pay-stub extraction succeeds on the previously-failing docs; a genuinely too-dense document
(overflowing even 16384) now fails HONESTLY (truncation labeled as truncation) and lands in NEEDS_REVIEW with an
accurate reason — the same honest-failure-mode principle the project applies everywhere. All extractors now benefit
from the guard; none silently mis-parse a truncated body. Each extractor's model call moved from a direct
`complete()` to the shared runner (no per-type behavior change otherwise).

## ADR-229: Right-size extraction budgets by output shape (LP-103) — not a blanket raise

- **Date:** 2026-07-03
- **Status:** Accepted

**Context:** LP-102's pay-stub truncation was one instance of a class — an UNBOUNDED "capture every X" catch-all
output still at the 4096 LP-39 scaffold budget. An audit across all ~18 extractors found the same shape on more
types. Most consequentially, **`investment_account` (4096) was already truncating on LF-6T3N** — a silently-empty
ASSET document. Assets feed reserves / down-payment verification, so a truncated brokerage statement UNDERSTATES a
borrower's assets: a live "wrong in a way that matters" bug, not just cleanup.

**Decision:** right-size by OUTPUT SHAPE, raising only the unbounded-catch-all-at-4096 types to **8192**:
`investment_account` (confirmed live failure — itemized holdings), `retirement_account` (same holdings shape),
`profit_and_loss` (revenue + each-expense lines), `purchase_agreement` (contingencies/concessions/addenda). The
already-right-sized types are left ALONE (tax_return 16384, bank_statement 8192, pay_stub 8192, divorce_decree 6144),
as are the bounded/semi-bounded fixed-form types (w2, voe, drivers_license 2048, letter_of_explanation,
homeowners_insurance, mortgage_statement, hoa_statement, property_tax_bill, form_1099 — all at their current budgets).

**Why NOT blanket-raise everything to a high ceiling:** a right-sized per-type budget encodes a useful size
EXPECTATION, so a truncation against it is a meaningful ANOMALY signal — that signal is exactly how the pay-stub and
investment-account bugs were found. A uniform high ceiling would blind the system to output size and let a runaway
output generate expensively before anything stopped it. The LP-102 shared guard is the backstop that makes
right-sizing (vs. over-provisioning) safe: a mis-sized type still fails HONESTLY (retry once at 16384, then an honest
truncated status), never silently. The per-type **sizing rule** (unbounded → generous 8192/16384; fixed-form →
small; guard as backstop) is documented in `app/ai/extraction/model_call.py` so the next extractor is right-sized
from the start.

**Consequences:** the confirmed investment-account asset-understatement bug is fixed and its three same-shape peers
are pre-empted; the bounded tail stays lean (no wasted budget, signal preserved), covered by the guard. No change to
the guard or the pay-stub fix. This is truncation/budget only — plausibility/misread checks are a separate concern.

## ADR-230: Surface document periods — server-derived, type-aware period + period in the name (LP-105)

- **Date:** 2026-07-03
- **Status:** Accepted

**Context:** 17 of 18 document types already extract a date/period, but it was poorly surfaced — only as
individual raw rows in the drawer, and reaching the card indirectly via `standard_name`, which only 8 types had a
naming rule for (the other ~10 fell back to `{Type}_{upload_date}` → undifferentiated names, the "8 identical
Pay-Stub cards" pain). This is a display/naming gap over already-extracted data, not an extraction gap.

**Decision:** two parts, both surfacing what's already extracted.

- **Consolidated period display, derived server-side.** A new `app/documents/period.py::document_period` maps each
  type to its period CONCEPT (range / tax year / single labeled date / expiry / verbatim) and returns one
  `{label, value}` (e.g. `Period: Jun 1 - Jun 15, 2026`, `Closes: Aug 15, 2026`). It is computed in the response
  builder (`_enrich`, alongside `standard_name`/staleness) and exposed as `DocumentResponse.period`, so BOTH the
  card and the drawer render ONE tested formatter rather than duplicating type-aware logic on the client. The card
  gets an at-a-glance distinguishing line; the drawer gets a consolidated line ABOVE the existing per-field raw rows
  (source snippets preserved — the period consolidates in addition, never replaces provenance). Graceful: `None`
  when the type has no period concept or the date isn't extracted yet.
- **Period in `standard_name` for all types.** Extended the LP-72 `NAME_RULES` (an existing config-dict pattern)
  with the ~10 missing types so the name uses the extracted date (investment/retirement→statement_period_end,
  P&L→period_end, voe→end_date, hoa→due_date, purchase_agreement→closing_date, divorce_decree→effective_date,
  LOE→referenced_date, drivers_license→expiration_date). The graceful `{Type}_{upload_date}` fallback is unchanged
  when the date isn't extracted.

**Boundaries:** display + naming only — NO new extraction (gift_letter's missing date and property_tax_bill's
verbatim-string normalization stay out; the tax bill's string is shown as-is in the display). Staleness/recency is a
separate follow-up (LP-106).

**Consequences:** same-type documents are now distinguishable by both the card's period line and their name; the
period is one consistent, server-tested string everywhere; the drawer keeps full provenance. Why server-side (not a
frontend formatter): the card is a lean list item without the raw extracted_data, and a single Python formatter is
unit-testable per concept and shared by card + drawer.

## ADR-231: Expand document staleness to types that already extract a period (LP-106)

- **Date:** 2026-07-03
- **Status:** Accepted

**Context:** the LP-71 staleness badge judges freshness from a document's extracted date against a per-type window
(`RECENCY_WINDOWS`), but was wired for only 4 types. `investment_account` / `retirement_account` already extract
`statement_period_end` (the same field bank_statement uses), yet a **stale asset statement was never flagged** — the
date existed but wasn't checked. Asset statements verify reserves / down-payment availability and must be recent, so
this is a correctness gap.

**Decision:** reuse the existing mechanism — add entries to `RECENCY_WINDOWS` (no parallel path). `investment_account`
+ `retirement_account` at **90 days** on `statement_period_end` (a bit wider than bank's 60 d because those statements
are often **quarterly** — 60 d would false-flag a normal current one); `profit_and_loss` at **120 days** on
`period_end` (a self-employed P&L should be reasonably current). The badge, `as_of_date`, and package-fitness pick
these up automatically. Windows are **grounded starters — validate-with-Priya**; the mechanism is the fix, the exact
day counts are hers.

**Under-vs-over (deliberately NOT wired):** `voe` (`end_date` is the employment *termination* date, null for a current
employee — not a verification/issue date, so no clean recency signal) and `mortgage_statement` (`due_date` is a
*future* obligation, not an as-of date). Forcing a window on either would produce a meaningless/false signal.

**Separate concern, flagged (not built here):** the verification engine's file-level recency FACTS —
`documents.income.most_recent_age_months` + `documents.asset_statement.most_recent_age_months` — are **read** by
Conventional + FHA rules but **never built** in `build_file_facts` (only the pay-stub age fact is), so those recency
rules are **inert**. That is a different code path; wiring the staleness badge does not build them. It needs a new
fact-builder (aggregate the newest income/asset-statement extraction date → months, like `_most_recent_paystub_age`)
and is flagged as a **fast-follow (LP-107)** — not silently left.

**Consequences:** a stale investment/retirement (asset) statement and an old P&L now flag "May be stale" and become
package-unfit, from the date already extracted; no new extraction, no parallel path, no frontend change (the badge is
type-agnostic). The FHA/Conventional recency rules remain inert until LP-107 builds their facts.

## ADR-232: Honest needs satisfaction — graded needs "attach, confirm coverage" (never a false-green) (LP-108)

- **Date:** 2026-07-03
- **Status:** Accepted

**Context:** the needs engine matched a document to a need at TYPE granularity (`needs_type == document_type`) and, on
a completed match, auto-advanced the need RECEIVED → VERIFIED. For a GRADED need — one whose requirement is inherently
more than "one document exists" (2 years of tax returns, 2 months of bank statements, "all asset accounts covering two
months") — this is a **dangerous FALSE-GREEN**: the first matching statement flips the whole requirement to
"satisfied", telling the processor asset/income documentation is COMPLETE when most of it is missing. Unlike the
project's other bugs (which fail loud/safe), this claims MORE verification than performed — the dangerous direction.
On LF-6T3N it was masked only by an unrelated pay-stub truncation (LP-102); fixing/reprocessing that would have
UNMASKED it, so the display and honesty fixes had to ship together.

**Decision (Option B — honest satisfaction, NOT Option A account-level coverage):**

- **Classify simple-presence vs graded.** A curated allowlist (`_SIMPLE_PRESENCE_NEEDS_TYPES`: drivers_license,
  purchase_agreement, gift_letter, letter_of_explanation, homeowners_insurance, title_commitment, appraisal,
  verification_of_employment, payoff_statement, existing_mortgage_statement) names the needs where ONE document IS the
  requirement. **Safe default: everything else — including every AI-proposed need and any unknown/None type — is
  GRADED.** Under-claiming (an extra confirm click) is a mild annoyance; over-claiming (a false-green) is the danger.
  Grounded starter — validate-with-Priya.
- **Honest transition.** A matched completed document → RECEIVED. Simple-presence → auto VERIFIED (the match IS the
  verification). Graded → **stops at RECEIVED = "documents attached — confirm coverage"** (no false-green); the
  processor confirms the coverage the system can't (all accounts / months / years) via a new
  `POST /needs/{id}/confirm-coverage` (RECEIVED → VERIFIED). RECEIVED was already a transient "arrived, not verified"
  state, so this needs NO new status/migration — a *persisting* RECEIVED now means "confirm coverage".
- **Always show the matched document.** Every matched need (attached or verified) surfaces the document by name (the
  card reads "Attached: X" for received, "Satisfied by X" for verified) plus the honest coverage note.
- **Umbrella needs match by category.** An AI umbrella need naming a category (`asset_statement`) matched no concrete
  document type, so it never attached. It now matches any document in the mapped category
  (`asset_statement → ASSETS`) — a coarse, category-level match that lands in the same honest RECEIVED state. This is
  NOT the account-level coverage matching (parse which account, N accounts × M months, a coverage grid) — that is
  **Option A / V2**.

**Consequences:** a graded need can no longer read "satisfied" on a single document; the LF-6T3N asset need shows the
honest "attached — confirm coverage" (or stays Pending) — never a false-green — even after reprocessing. The
processor makes the coverage judgment the system can't, with the evidence assembled and the gap stated honestly
("AI proposes, processor disposes", applied to satisfaction). Same honest-failure-mode principle as the rest of the
project — never claim more verification than performed. Account-level coverage verification is deferred to V2.

## ADR-233: Derive-on-read the full matching-document set for a need (LP-109)

- **Date:** 2026-07-03
- **Status:** Accepted

**Context:** LP-108 made graded needs show "documents attached — confirm coverage", but the data model stores a
single `satisfied_by_document_id` (one FK per need), so a graded need like "2 months of bank statements" displayed
only ONE of several matching documents — undercutting "confirm coverage" (the processor can't confirm coverage
against evidence that's mostly hidden). An investigation established the mitigating fact: the matcher's criteria is
**trivial deterministic equality** (`document_type == needs_type`, or the umbrella need's category == the document's
category) over fields **already stored** on every document — so the full matching set is a cheap display-time query.

**Decision:** **derive-on-read** — at response-build time, `documents_matching_need(need, documents)` returns ALL of
the file's completed documents matching the need's criteria (reusing the matcher's equality), and the response
carries that full `matching_documents` list. **No schema change, no matcher change, no migration.** The single
`satisfied_by_document_id` is KEPT as the "trigger" (the document that moved the need to RECEIVED); the derived list
is computed on read. The card shows all matching documents by name for a graded need (a simple-presence need keeps
its single satisfying document).

- **The over-inclusiveness is intentional.** For an umbrella need the derived set is coarse — the `asset_statement`
  need includes every ASSETS-category document (even an earnest-money withdrawal). That coarseness IS the
  "confirm coverage" honesty level: the system surfaces every candidate; the processor curates which count. We do
  NOT add narrowing/precision — precise, curated, per-need coverage (N accounts × M months) is the V2 coverage grid.
- **Known limitation (noted, not fixed):** derive-on-read shows the LIVE matching set, not a PERSISTED "processor
  confirmed these specific documents" decision. A persisted, curated, editable per-need document set (an explicit
  needs↔documents join + matcher accumulation) is the foundation for V2's Option A, built when its shape is known —
  NOT now.

**Consequences:** graded needs now show their full evidence set (LF-6T3N's asset need shows all 9 matching ASSETS
documents instead of 1), delivering LP-108's intent that the single-FK model couldn't. LP-108's false-green STATUS is
untouched and independent. No new storage, no migration, no matcher change — the cheapest correct delivery, with the
explicit one-to-many storage deferred to V2/Option A.

## ADR-234: Every need shows its SOURCE — per-origin provenance, honestly attributed (LP-110)

- **Date:** 2026-07-03
- **Status:** Accepted

**Context:** A need carried its REASONING (the AI's argument, LP-67/69) but NOT its SOURCE — the specific data that
triggered it. Extractions and findings are provenance-backed (source page + snippet; click → see the document line),
but needs — **the most AI-driven, least-deterministic part of the system** — were not: a processor could not verify
the AI hadn't hallucinated or MISREAD. A need proposed on a misread carries plausible-but-wrong reasoning; without the
source the human has nothing to check it against. One structured link existed (`source_finding_id`, LP-67) but was
populated only for suggestion needs AND was not exposed in the API (`NeedsItemPublic` omitted it), so even it never
reached the UI.

**Decision:** capture and display a **per-origin source** on every need, GROUNDED to verifiable data wherever possible
and HONESTLY ATTRIBUTED so the processor knows how much to trust it — making a need's reasoning **FALSIFIABLE**.

- **AI-reasoned (`ai_reasoning`) — capture at generation.** Extend the model's output (`ProposedNeed.triggered_by`, a
  list of `{kind, label, ref?}`) so the AI CITES the specific FileContext fact(s) it reasoned over — it already sees
  them, so this is a low-risk output-schema + prompt extension. Finding ids are added to the context so a citation can
  `ref` a real, linkable record. Parsed defensively (unknown-kind / empty-label facts dropped; a need is never dropped
  for lacking a source), persisted to the new `needs_items.source_facts` (JSON). Attributed **ai_identified** (the AI's
  reading — verify) and marked as such in the UI.
- **Floor (`floor`) — derive from the rule.** The rule already evaluates the data, so the source is derived
  DETERMINISTICALLY at seed time (pay_stub/w2 ← "Employment income is stated"; bank_statement ← "Assets are stated";
  purchase_agreement ← "Loan purpose is Purchase"; refi statements ← "Loan purpose is Refinance"; drivers_license ←
  per borrower) and stored in `source_facts`. Attributed **deterministic** (certain).
- **Suggestion (`suggestion`) — expose the existing chain.** Surface `source_finding_id → the finding → its source
  document` through the API (`source_finding` relationship, eager-loaded). Attributed **finding**, linked to the
  finding + document (previously captured but hidden).
- **Manual** — no structured source (the origin "Added" is the source) → `source` is null.
- **Unified display.** `NeedsItemPublic.source` (a `NeedSource` = attribution + facts) renders one "Source" affordance
  per need, mirroring the finding "Source" section + the extraction Quote provenance vocabulary so it looks native. The
  deterministic pill (primary/certain) is visually distinct from the AI-identified pill (info/verify) — an AI reading
  is NEVER presented as certain fact. Composes with LP-108 (status) + LP-109 (matching documents) — purely additive; no
  change to need GENERATION logic.

**Grounded-starter (validate-with-Priya):** the AI-cited sources are AI-generated (as reliable as the AI's reading), so
they are marked AI-identified and linked to verifiable data — the open quality question ("does the AI cite the RIGHT
triggering fact?") is flagged for Priya. Floor + finding sources are deterministic.

**Consequences:** every need now grounds its reasoning to a checkable fact, closing the gap where extractions/findings
were provenance-backed but needs weren't — the human can verify a misread on the most AI-driven surface. One nullable
JSON column + one relationship; no change to matching, satisfaction, or generation. A persisted "the processor
confirmed this source" record and clickable deep-links into the underlying records are natural future refinements, not
built here.

## ADR-235: Needs consolidation — deterministic collapse (source + substance) + AI flags the residue (LP-111)

- **Date:** 2026-07-04
- **Status:** Accepted

**Context:** One real situation multiplied into 3-4 needs. A single fact (a $20,000 "due diligence fee" wire) became
TWO findings (an ``obligation`` + a ``discrepancy_candidate``); each finding implied an LP-67 suggestion; and the LP-69
AI reasoner independently free-formed more needs citing the same fact — with ``needs_type=null`` and reworded wording
every run. Nothing merged by shared source, and the only dedup (``reconcile`` / ``apply_ai_needs``) matched on exact
``needs_type`` or exact ``.lower()`` title — so reworded free-form variants slipped through and ACCUMULATED across the
per-document-arrival re-runs. Meanwhile the findings subsystem already had the missing mechanism: a normalized-substance
identity (LP-93, ``finding_identity``).

**Decision:** consolidate needs with a **deterministic safe floor + an AI layer that only FLAGS**, under one discipline:
**never silently delete a need.** A duplicate is a minor annoyance; a wrongly-dropped need is a major failure (a
required document never gets collected → the file goes to the lender incomplete). These are asymmetric, so we
**UNDER-merge** — when unsure, keep both.

- **Layer 1 — collapse-by-source (certain).** Two PROPOSED needs of the SAME ``needs_type`` that share a source finding
  (via ``source_finding_id`` or the ``source_facts`` finding ref, LP-110) are the same ask (the suggestion + the AI
  proposal for one finding) → merged deterministically. Same idea as ``ingest_suggested_need``'s per-finding idempotency.
- **Layer 2 — substance-identity (certain).** REUSE LP-93's ``normalize_text`` (NFKC + case-fold + dash/quote +
  whitespace) for a ``(intent, title)`` identity — REPLACING the exact ``.lower()`` match that let cosmetic variants
  through. Textual only, no fuzzy matching (conservative).
- **Layer 3 — AI flag (never deletes).** The genuinely-reworded residue the deterministic layers can't be SURE of
  (different words, ``needs_type=null``) is only FLAGGED (``duplicate_of_id``) for the processor to confirm (merge) or
  dismiss (keep both, ``duplicate_reviewed`` so it's never re-flagged). Conservative, high-confidence only, cheap
  classification model, gated by a setting. This is the safe version of "AI dedup" — its semantic strength used, its
  silent-delete danger contained.
- **Generation-time reconciliation.** The existing needs (title + type) are fed into the reasoner's context so it stops
  REWORDING them into new duplicates — attacking the accumulation at the source, not just post-hoc.
- **Safety boundary.** Only a ``PROPOSED`` + ``PENDING`` need may be merged AWAY; a confirmed / waived / adjusted /
  received need is a fixed point (a proposed duplicate merges INTO it). Merges preserve provenance (the survivor keeps
  the UNION of both ``source_facts``), composing with LP-108/109/110.

**Upstream finding-multiplication — investigated, NOT collapsed.** One fact → an ``obligation`` + a
``discrepancy_candidate`` finding maps (``implications.py``) to genuinely distinct purposes: the obligation feeds
recurring-debt/DTI ("request payment history"); the discrepancy is a "reconcile this mismatch" flag (Phase 3). Collapsing
them upstream would lose that signal, so we **consolidate at the needs layer** (default) and preserve the findings.
Noted separately: typing a one-time wire as ``OBLIGATION`` (a recurring type) is an extraction misclassification — a
follow-up, not fixed here.

**Scope.** Consolidation only. The separate NOISY-SOURCE problem (the AI attaching a tangential fact as a source — e.g.
the homeowner's-insurance need citing the wire when its real trigger is "Loan purpose = Purchase") is source RELEVANCE,
a prompt-quality fix, deferred to **LP-112** (different mechanism). Need generation (what's proposed) is unchanged.

**Consequences:** the wire cluster collapses toward ~1 LOE + the distinct sales-contract need (deterministic where
certain; AI-flagged where reworded; processor-confirmed) — not over-merged into one, not left at 3-4. Two columns +
one service + a small flag UI; no change to matching/satisfaction/generation. Persisted "these are the same" learning
and a stronger free-form subject key are future refinements.

## ADR-236: Findings name their SOURCE DOCUMENT — capture the id we already compute, expose + display (LP-114)

- **Date:** 2026-07-04
- **Status:** Accepted

**Context:** A finding showed "source p.N" + a snippet but not WHICH document — so a processor couldn't easily verify the
AI/rule judgment against the actual document (the findings analog of LP-110's gap for needs). The `Finding` model already
had a `source_document_id` FK (+ a `source_document` relationship), but it was **hidden AND empty**: not exposed in
`FindingPublic`, and never populated at creation — worse than needs' `source_finding_id`, which was populated-but-hidden.
Crucially, the id was **already computed and thrown away**: deterministic findings' `source_location` often carries a
`document_id` (a fact read from a document's extraction), but `_source_location_fields()` extracted only page + snippet
and dropped it. AI cross-source findings only carry a document TYPE string ("W2"), not an id.

**Decision:** capture + expose + display the source document, mirroring LP-110.
- **Capture = stop dropping what we compute.** `_source_location_fields()` now also forwards the `document_id` →
  `source_document_id` on deterministic findings (null for file-level/computed rules). AI cross-source findings resolve
  their type string to a concrete id **only when it maps to exactly ONE document** on the file
  (`_unique_type_document_map`, normalized); 0 or 2+ → NULL. Never guess a wrong document — a null source is honest, a
  wrong link is not.
- **Expose.** `FindingPublic` gains `source_document_id` + `source_document_filename` (the readable `original_filename`,
  eager-loaded — no N+1); the frontend `VerificationFinding` type mirrors it.
- **Display.** The finding card NAMES its source document ("Source: {filename}, p.{N}") at a glance and in the Details
  "Source" section, replacing the bare "source p.N". Graceful when null (keep page/snippet; never a broken empty
  "Source:").
- **Clickable — the lightweight nav was cheap, so it's built.** Verification and Documents are separate routes, and the
  Documents page already opens a drawer from local state; so the source-doc name links to `/loan-files/[id]/documents?doc=<id>`
  and the Documents tab reads `?doc` to open that document's existing drawer (then strips the param). No new store, no
  viewer — a `<Link>` + a small `useSearchParams` effect.

**Coverage is partial by design.** Naming populates mostly for deterministic findings that read a specific document
field; file-level/computed rules and multi-doc-type AI findings stay null (graceful). No heavier snippet-search fallback
— honest over exhaustive.

**No migration.** The `source_document_id` column already existed. Existing findings stay null until re-verified (no
backfill).

**Deferred to V2 (documented in the plan):** an in-app document VIEWER (PDF.js / embedded PDF), PAGE deep-linking ("open
to page N"), and TRANSACTION HIGHLIGHTING (needs the bbox/position data deferred in LP-75). V1 is name + link-to-open;
the viewer/page/highlight staircase is V2.

**Consequences:** a finding now names (and opens) the document that grounds it — verifiable, mirroring LP-110 for needs.
Small surface: two schema fields, a capture tweak in each generator, a card display + a `?doc=` param; no finding
generation change; composes with LP-110/LP-113.

## ADR-237: Findings show ALL their source documents — multi-document provenance, honest by construction (LP-114.1)

- **Date:** 2026-07-04
- **Status:** Accepted

**Context:** LP-114 gave a finding a single ``source_document_id`` and nulled out whenever a cited value spanned several
same-type documents. But a cross-source finding is inherently derived from MULTIPLE documents — an employer appears on a
pay stub AND a W-2; a discrepancy compares stated data against one-or-more documents. The single-FK shape is both
incomplete (a partial story) and the source of most nulls (it refused to pick one among several). Showing ALL the source
documents completes the provenance AND dissolves the ambiguity — show every document that genuinely contains the value,
no wrong pick.

**Decision:** represent a finding's source as a SET (the LP-109 analog for findings). A new ``findings.source_document_ids``
JSON array (Option A — mirrors needs' ``source_facts``, no join table); ``source_document_id`` stays as the
primary/trigger (back-compat). ``FindingPublic.source_documents: [{id, filename}]`` names the whole set (the file's
document names loaded once — no N+1); the finding card lists all of them ("Sources: doc1, doc2"), each clickable to open
via LP-114's ``?doc=<id>`` nav.

- **Derived by value-matching (uniform, exact enough).** A ``populate_finding_source_documents`` pass at the end of a run
  (and re-derived on the backfill) matches each finding's cited value(s) to every document that contains them. This is
  uniform across all three generators (deterministic engine, deterministic cross-source, AI) without wiring each.
- **Honest by construction — the precision discipline.** The match keys on the finding's SPECIFIC distinctive cited value
  (its ``document_value``; an amount / address / account-fragment in the snippet) — NOT generic tokens (a lone common
  word is dropped). AND a document is eligible only if its CATEGORY is compatible with the finding's (an INCOME/employer
  finding matches only INCOME_EMPLOYMENT documents, not a savings statement that merely repeats the bank name).
  Cross-cutting finding categories (cross-source / documentation / regulatory) are unconstrained. So a common institution
  name in an off-category document does NOT over-include it — the exact over-inclusion the single-value match risked.
  The category compatibility is a **grounded starter — validate-with-Priya**.

**Consequences:** on LF-6T3N the named findings jumped from a handful to 16/19 — the employer-mismatch findings now show
their pay-stub + W-2 sources (precisely — no coincidental savings statements), and the balance/license findings show
their one document. Empty when no distinctive locatable value (graceful). One JSON column + a matching service + a card
list; no migration on the primary FK; ``source_document_id`` kept. Composes with LP-114 (generalizes single → set) /
LP-109 / LP-110 / LP-113. The viewer + page deep-link + transaction highlight remain V2 (no viewer, no bbox data).

## ADR-238: Extraction confidence — honest, never fabricated; per-field number in JSON, doc-level in a CHECK-constrained column (LP-201)

- **Date:** 2026-07-09
- **Status:** Accepted

**Context:** LP-201 threads a confidence signal from the document extractors to storage as a prerequisite for the Stage-1
snapshot work (nothing consumes it yet). Two questions had to be answered honestly, because a *fabricated* confidence is
worse than none — a downstream trust gate that reads a made-up ``1.0`` or a defaulted ``0.0`` mislabelled as a real model
rating makes exactly the wrong call. (a) **Per-field**: the LP-39a extraction shape (``TypedField`` = ``{value, source}``,
governed by ADR-144/145) carried no per-field confidence, and the only honest source of a per-field number is the model
self-rating each field. (b) **Document-level**: the model already returns one overall ``confidence`` used for the review
gate (LP-42), but it was dropped at storage; the ``coerce_confidence`` coercer collapses a *missing/garbage/failed* value
to ``0.0``, so a persisted ``0.0`` cannot be distinguished from a genuine model ``0.0``.

**Decision:**

- **Per-field confidence: extend the extraction prompts (overrides the ticket's "no prompt redesign" default).** Each of
  the 18 extraction prompt files now asks the model for one top-level ``field_confidence`` map (``field name → 0.0–1.0 |
  null``) — a single uniform per-prompt edit, robust to the heterogeneous (some nested) prompt shapes, rather than
  interleaving a key into every field object. ``parse_typed_core`` reads that map and stores a nullable ``confidence``
  number **inside ``extracted_data``** (additive JSON key — no column; consumers still read ``value``). This deliberately
  overrides the ticket's "no prompt redesign" guidance (explicitly approved), because the model self-rating is the only
  genuine per-field signal available today.
- **Honesty over completeness — never fabricate.** ``coerce_optional_confidence`` returns ``None`` (not ``0.0``) for a
  missing / non-numeric / boolean / non-finite (``NaN``/``Infinity``) / out-of-range value — a field the model did not
  honestly rate in ``[0, 1]`` is "no confidence", never a fake number. This is distinct from the document-level
  ``coerce_confidence`` (the review gate), which keeps its legacy behavior — default to ``0.0`` and **clamp** an
  out-of-range number — because classification, cross-source, and the gate all depend on a plain clamped float. Both share
  one private ``_parse_confidence`` primitive; the only fix to the gate coercer is that ``NaN``/``Infinity`` now collapse
  to ``0.0`` instead of a fabricated ``1.0``.
- **The provenance tag is DERIVED, never stored beside the number.** A ``confidence_source`` is
  ``model_self_reported`` iff a number is present, else ``not_provided`` — a pure function of the number. Storing both
  invites a contradictory ``confidence=0.9 / source=not_provided`` record with no source of truth, so per-field storage
  keeps only the number and readers derive the tag via ``ConfidenceSource.for_confidence``. The enum has exactly the two
  states that exist; no speculative ``structural`` / ``field_presence`` values are reserved until the ticket that first
  emits them.
- **Document-level: rescue the signal into a CHECK-constrained column, honestly.** Nullable ``extractions.confidence``
  (Float) + ``confidence_source`` (a ``str_enum(ConfidenceSource)`` VARCHAR+CHECK, ADR-037 — not a free string, so the
  vocabulary can't drift and a bad literal can't persist). ``ConfidenceSource`` lives next to the model that owns the
  column (``app/models/extraction.py``, beside ``ExtractionStatus``); the AI layer imports it (an already-permitted
  ``ai → models`` direction). The pipeline stores the value through ``document_confidence_provenance``: only a **positive**
  confidence is a genuine self-report — a failed extraction or a defaulted/garbled ``0.0`` is stored as ``NULL`` /
  ``not_provided``, so a defaulted 0.0 is never mislabelled ``model_self_reported``.

**Consequences:** additive & non-breaking — the extraction shape stays backward-compatible (consumers read ``value``); old
rows and failed/low-signal extractions carry honest ``NULL`` / ``not_provided``. Because the prompts changed, extracted
*values* are no longer guaranteed byte-identical going forward (LLM output isn't deterministic once the contract changes);
the regression guarantee is shape-compat + no fabrication, not identical values. Trade-off: the document-level path cannot
distinguish a genuine model ``0.0`` from a defaulted ``0.0`` (``coerce_confidence`` is lossy for the gate), so a
non-positive doc-level confidence is conservatively stored as ``not_provided`` — the safe, never-fabricate direction; the
per-field path *does* distinguish them (explicit ``0.0`` kept, absence → ``None``). Extends ADR-144/145 (the extraction
shape) and reuses ADR-037 (str_enum) / ADR-057 (JSON storage). Deferred: consuming the confidence (Stage-1 snapshot),
prompt calibration, and any structural/field-presence signal; the 18 identical prompt blocks → a shared injected partial is
a follow-up refactor.

## ADR-239: Document→borrower link — deterministic (not AI) name matching into a separate one-to-many table (LP-202)

- **Date:** 2026-07-09
- **Status:** Accepted

**Context:** The Stage-1 snapshot (and later ``belongsTo``, LP-206) needs to know which borrower(s) a document is about.
On this branch a ``Document`` has no borrower link at all (the equivalent ``document_borrower_links`` built on
``phase3_5_1`` is deliberately not in use here). Documents already assert a person's name — a pay stub's ``employee_name``,
a bank statement's ``account_holder_name``, etc. Resolving that asserted name to a file's borrowers is **enumerable,
reproducible logic**, exactly the kind of thing that must NOT be AI: a flickering, non-deterministic link is worse than
none (the same lesson as the cross-source "graduation", ADR — known cross-checks belong in deterministic code).

**Decision:**

- **Deterministic, not AI.** A pure ``normalize + score`` matcher (``app/services/borrower_name_matching.py``): accents
  stripped, ``"Last, First"`` reordered, suffixes/connectors dropped, tokenized; the **last name is the anchor** (no
  surname match → no link, a shared first name is never enough), then the first name matches by exact / nickname (a small,
  high-precision common-nickname map) / fuzzy (stdlib ``difflib``). Same inputs → same links, every run. (See the
  post-review amendment below: bare initials no longer match, short names require exact match, and a failed component
  scores zero.)
- **A configurable no-match threshold.** ``NAME_MATCH_THRESHOLD = 0.80``, a named, documented constant. Below it **zero
  links** are emitted — a low-similarity near-miss (a one-letter surname typo, a same-surname different person) is a
  correct no-match, never forced to the "closest" borrower. Precision over recall by design.
- **One-to-many via a link table, not a ``Document.borrower_id`` column.** ``document_borrower_links`` with
  ``UNIQUE (document_id, borrower_id)`` + a ``[0,1]`` CHECK on ``confidence`` (cf. the findings confidence guard). A joint
  document (joint bank statement, joint tax return) links **both** borrowers — the asserted string is scored against each
  borrower independently.
- **Raw name on the document, resolved link in a separate table.** The asserted name stays inside the document's
  extraction (``extracted_data``); the *correlation* — borrower id + ``confidence`` + ``method`` (``exact`` /
  ``normalized`` / ``fuzzy``) — lives ONLY in ``document_borrower_links``. This keeps the document facts raw and
  uncorrelated (the snapshot's document section stays honest); the resolved link is a separate, recomputable artifact.
- **Honest no-match = zero rows**, never an error and never a null-borrower row. Re-matching replaces a document's links
  wholesale (idempotent).
- **Name extraction added only where a document clearly asserts a borrower name but didn't capture it:**
  ``homeowners_insurance.named_insured``, ``mortgage_statement.borrower_name``, ``property_tax_bill.owner_name``,
  ``hoa_statement.owner_name`` — ordinary extracted fields carrying LP-201's nullable per-field confidence. The 10 types
  that already extract a usable name are untouched. Counterparties (a gift letter's ``donor_name``, a purchase
  agreement's ``seller_name``) are **excluded** from the borrower-name registry so they never mislink.

**Consequences:** additive & non-breaking; nothing consumes the link yet (LP-206). Deterministic + thresholded means
precision over recall — the honest cost is that a genuine borrower whose name is badly mangled on a document yields no
link rather than a guessed one. Known limits (documented in the ticket): the nickname map is small and high-precision (not
exhaustive); a compound/hyphenated surname anchors on its last token (a simplification); ``property_tax_bill`` /
``hoa_statement`` name the current *owner*, who on a purchase is the seller — the threshold simply won't link a seller to
a borrower, so extracting the owner name stays honest. No pipeline trigger is wired — links are recomputed on demand via
``assign_document_borrower_links``; auto-invocation on document processing is deferred to the consuming ticket. Reuses
ADR-052 (transitive company scope via document → loan file) and ADR-057. Implemented fresh on this branch, mirroring the
concept on ``phase3_5_1`` but not depending on it.

**Amendment (2026-07-09, post code-review — precision hardening before LP-206 wires this up).** A review found the matcher
produced FALSE links between same-surname family members (the common mortgage case); a wrong link is a fabricated fact
that would propagate into ``belongsTo``. Precision fixes applied:

- **A non-matching name component now contributes ZERO, not a partial score.** Previously a component that failed its own
  bar still fed its raw ``difflib`` ratio into ``0.5·last + 0.5·first``, so a strong surname dragged a failed first name
  over the threshold. ``_best_token_match`` now returns ``0.0`` / ``"none"`` for a non-match, so a failed component can
  neither clear the surname anchor nor pad the combined score. Concretely: ``John Smith`` no longer links to a document
  asserting ``"Johnson Smith"``.
- **A bare initial confers no match.** The single-letter "initial" branch (score 0.8) was removed: a stray middle initial
  (``"Robert A. Smith"``) no longer links co-borrower ``Andrew Smith``, and a first name given only as an initial
  (``"A. Patel"``) no longer links ``Akash Patel``. An initial is not evidence that two full names are the same person.
- **Short surnames must match exactly, not fuzzily** (``_FUZZY_MIN_LEN``). ``difflib`` inflates the ratio of short
  near-misses (Han/Hahn, Lee/Li) above the anchor on a single edit, so fuzzy only counts when both tokens are ≥ 5 chars.
- **Nicknames map to a SET of canonicals.** A nickname shared by two canonicals (``steve`` → {steven, stephen}; ``kate`` →
  {katherine, catherine}) previously dropped the second (a ``setdefault`` collision), so ``Stephen``/``Catherine`` never
  matched ``Steve``/``Kate``. Two names now nickname-match iff their canonical sets intersect.
- **The honest cost is recall, in the safe direction.** These all trade recall for precision — a genuinely ambiguous or
  badly-mangled document now yields no link (``belongsTo: null``, a safe miss) rather than a fabricated one.
- **``method`` is now a CHECK-constrained ``str_enum`` (``MatchMethod``: exact/normalized/fuzzy), mirroring LP-201's
  ``confidence_source`` and ADR-037** — the value LP-206 branches on can't drift or typo silently. ``MatchResult.method``
  is typed ``Literal["exact","normalized","fuzzy"]`` so mypy enforces the three literals at every assignment.
- **Soft-deleted parents no longer leak links.** ``DocumentBorrowerLink`` has no soft-delete of its own and its
  ``ondelete=CASCADE`` FKs never fire on a soft delete, so a borrower removed from a file after matching would strand a
  link. ``get_document_borrower_links`` now joins the (soft-delete-aware) document + borrower via ``only_active``, so a
  link to a soft-deleted parent is never returned. (Read-filter chosen over adding ``SoftDeleteMixin`` because the link
  table is hard-delete-and-replace by design.)
- **``BORROWER_NAME_FIELDS`` is a deliberate parallel list — and a known fragility root cause.** It had already drifted:
  the 1099 mapping was keyed ``"form_1099"`` while ``Document.document_type`` holds the ``EXTRACTORS``/catalog slug
  ``"1099"``, so **every 1099 silently produced zero links**. Fixed the key, and added a test asserting
  ``set(BORROWER_NAME_FIELDS) ⊆ set(EXTRACTORS)`` so the drift can't recur. The map stays explicit (rather than derived
  from the registry) because it also encodes the counterparty-exclusion knowledge the registry doesn't have, and keeping
  the matcher import-pure (no AI dependency) is worth more than eliminating the parallel list; the drift-guard test is the
  chosen safety net.

Deferred (recorded in the ticket): compound/hyphenated surnames still anchor only on the last token (a safe miss, left
until precision is proven); three small helper duplications (typed-cell accessor, current-extraction query dropping
``only_active``, active-borrowers query) route through existing helpers as a follow-up; per-borrower normalization is
recomputed in the inner loop (hoist as a follow-up).

## ADR-240: Snapshot field primitives — absent≠empty marker + an app-secret-keyed PII match-hash (LP-203)

- **Date:** 2026-07-09
- **Status:** Accepted

**Context:** The Stage-1 snapshot needs a shared field shape for every fact plus a way to carry PII (SSNs, account
numbers) without ever storing the raw value, while still letting deterministic rules match same-value fields (a bank
statement's account == a MISMO asset's account). Two decisions are load-bearing and must be made here: (a) how to
distinguish a fact *no source supplied* (absent) from a fact a source supplied as null/empty (present-but-empty), and
(b) the match-hash construction — because SSNs (~10^9) and account numbers are **low-entropy**, a naive hash of a
low-entropy value keyed only by the non-secret ``loan_file_id`` is trivially brute-forced by anyone holding the hash.

**Decision:**

- **Two frozen, closed Pydantic v2 models** (``model_config = {"frozen": True, "extra": "forbid"}``), in
  ``app/verification/snapshot/``. ``Field`` = ``{value, confidence, source}``; ``PiiField`` = ``{display, match_hash,
  confidence, source}`` with **no raw-value field** — ``extra="forbid"`` structurally prevents attaching one, and the
  ``PiiField.from_raw(...)`` factory masks + hashes internally so a caller never hand-stores the raw value.
- **Reuse LP-201's confidence model exactly (ADR-238).** ``confidence: float | None`` (never a fabricated default;
  ``None`` is the honest state) and the provenance tag is **derived, not stored** — a ``confidence_source`` property over
  ``ConfidenceSource.for_confidence`` — so the number and its tag can never disagree.
- **Absent ≠ empty via an explicit ``absent`` marker**, not a null value. ``Field.missing()`` (absent: no source, no
  value, no confidence) is structurally distinct from ``Field.present(None, source=…)`` (a source supplied an explicit
  null/empty). A model validator enforces the two states never blur (an absent field carries nothing; a present field
  must carry a source). Chosen over a sentinel object (awkward to JSON-serialize) and over "absence = key omitted"
  (can't record an *explicit* "we looked, nothing there"); the boolean serializes cleanly and is unambiguous.
- **``source`` (``FieldSource`` = parsed | extracted)** is the fact's DATA ORIGIN — distinct from ``confidence_source``
  (the LP-201 confidence provenance). Two different "source" concepts, deliberately kept separate.
- **PII display: last-4 masking only**, honest on every edge — ``mask(value, kind)`` returns ``***-**-1234`` (SSN) /
  ``****3312`` (account); a null / empty / malformed / too-short value returns a fully-masked placeholder
  (``***-**-****`` / ``****``), never the raw value, never a crash.
- **Match-hash construction (the security crux):**
  ``match_hash = HMAC-SHA256(key=K, msg=f"{loan_file_id}:{normalized_value}")`` where
  ``K = SHA256(b"snapshot-pii-match-hash-v1:" + settings.encryption_key)`` and ``normalized_value`` is the value's
  lowercased alphanumerics (so ``123-45-6789`` == ``123456789``). Properties: **per-loan-file salt** — ``loan_file_id``
  in the message means the same SSN in two files hashes differently (no cross-file correlation), while it stays
  consistent within a file so matching works; **application secret** — keying the HMAC with a secret derived from the
  existing Fernet ``encryption_key`` (ADR-051) makes the hash reproducible only by the system, so a low-entropy input
  can't be brute-forced by a party holding the hash + the (non-secret) ``loan_file_id``; **key separation** — ``K`` is a
  purpose-derived subkey (``SHA256(purpose ‖ encryption_key)``), not the raw Fernet key, so the HMAC key is
  cryptographically distinct from the encryption key and reuses no new secret store.

**Consequences:** pure primitives; nothing consumes them yet (the snapshot model is LP-204, assemblers later). The
match-hash is a **keyed pseudonym**, not encryption — it is one-way and un-reversible even by the system (there is no
"unhash"); its sole purpose is equality-matching within a loan file. Rotating ``encryption_key`` (or bumping the
``v1`` purpose label) changes all match-hashes — acceptable because nothing persists them yet and a snapshot is rebuilt
per run; a future ticket that persists snapshots must treat a key rotation as a rebuild trigger. The key is derived per
call (not cached) so rotation and tests both see the current secret. Reuses ADR-051 (Fernet ``encryption_key`` / secret
management) and ADR-238 (the LP-201 nullable-confidence model + derived source); no new secret store is introduced.
Deferred: which fields *are* PII (per-assembler, later tickets), the snapshot model + persistence, and any UI.

**Amendment (2026-07-09, post code-review — the match-hash fabricated "these two values match" facts).** A review
found the primitive minted a real, matchable hash for empty/absent inputs and collided values across kinds — the same
fabricated-fact / absent≠empty class of bug as LP-201/LP-202. Fixes:

- **Empty/absent → NON-matchable.** ``match_hash`` returns ``None`` when the value normalizes to fewer than
  ``_MIN_MATCH_LEN`` (4) characters (``""`` / whitespace / punctuation / ``None`` — and ``None`` now normalizes to ``""``,
  not the token ``"none"``). Two blank/absent PII values can never "match". ``PiiField.match_hash`` is now ``str | None``.
- **Kind-bound.** The ``PiiKind`` is folded into the HMAC message (``f"{kind}:{loan_file_id}:{value}"``), so an SSN and
  an account that share a digit-string (``123-45-6789`` / ``123456789``) no longer collide into a cross-kind match.
- **``loan_file_id`` canonicalized + empty rejected.** Parsed to canonical UUID form (so ``str(uuid)`` and an upper-cased
  rendering of the same id match), and an empty/falsy id raises — it would collapse the per-file salt and reintroduce the
  cross-file correlation the salt exists to prevent.
- **Versioned output.** The hash carries its version (``v1:<hex>``), so once snapshots persist (LP-204) a construction
  bump is an incremental, detectable migration rather than a silent global match failure. Supersedes the original
  "rotation = full rebuild" deferral.
- **``PiiField.missing()`` — absent PII, first-class.** No display, no hash — distinct from a source-supplied blank
  (present-but-empty: a masked placeholder display + ``None`` hash). PII now honors the absent≠empty distinction ``Field``
  already enforced, via an ``absent`` marker + validator mirroring ``Field``.
- **Raw value structurally rejected.** A validator rejects an unmasked ``display`` (must start with a mask shape), so
  ``PiiField(display=raw_ssn, …)`` fails — the "never stores the raw value even by accident" guarantee is now enforced,
  not just documented. This also corrects the earlier "un-reversible even by the system" overstatement: the hash is
  un-computable by any party *without* the secret, but a holder of the snapshot AND the secret could still brute-force a
  low-entropy input — no weaker than the encryption-at-rest boundary, but not absolutely irreversible.
- **Key access centralized (ADR-051).** The purpose-separated subkey is derived via a new
  ``app.core.encryption.derive_key(purpose)`` — all ``encryption_key`` access stays in ``encryption.py``.
- **``Field.value`` rejects non-JSON-scalars.** A ``Decimal`` (money) or ``date`` now raises at the primitive instead of
  silently coercing to ``float`` (precision loss); assemblers must stringify first, and a violation fails loudly here.
- **Also:** ``mask()`` masks an exactly-4-character value (``> 4`` to reveal last-4, was ``>= 4``), and its kind→shape
  dispatch uses ``assert_never`` so a new ``PiiKind`` is a hard failure, not a silent account-shape fallthrough.

Deferred (follow-ups, in the ticket): a shared ``mask_last4``/``mask_ssn`` helper (``mask()``'s SSN branch duplicates
``Borrower.masked_ssn``); a shared ``ConfidenceCarrier`` base (the confidence + derived ``confidence_source`` is
copy-pasted across ``Field`` / ``PiiField`` / ``TypedField`` — relates to ADR-238).

## ADR-241: Snapshot container — frozen three-section model, un-linkable by construction, resolved belongsTo (LP-204)

- **Date:** 2026-07-09
- **Status:** Accepted

**Context:** The Stage-1 snapshot needs a container the assemblers code against and that persists as a JSON blob
(LP-209). It must hold the three sections (MISMO facts, extracted documents, the four calculators' output) built on
LP-203's ``Field``/``PiiField`` primitives, reference LP-202's resolved document→borrower links, and — the load-bearing
constraint — keep the sections **independent** so no cross-section correlation can be baked in (that is a deliberate
downstream job; a snapshot must present raw, uncorrelated facts).

**Decision:**

- **Frozen Pydantic v2 models, top to leaf** (``model_config = {"frozen": True}``): ``Snapshot`` →
  ``MismoSection`` / ``DocumentsSection`` / ``CalculationsSection`` → ``DocumentEntry`` / ``CalculationEntry`` /
  ``CalcBreakdownLine`` / ``BorrowerLink``, over LP-203 ``Field``/``PiiField``. Attribute reassignment at any level
  raises. (Caveat, documented: ``frozen`` does not deep-freeze a contained ``dict``/``list`` — Pydantic can't; the maps
  are immutable by construction, built once by the builder and never mutated. A ``frozendict`` would fight JSON
  round-trip and is not worth it.)
- **The ``Field | PiiField`` union needs no discriminator.** LP-203's ``extra="forbid"`` makes the two structurally
  mutually exclusive (``value`` only on ``Field``; ``display``/``match_hash`` only on ``PiiField``), so a dumped cell
  validates back to exactly one — round-trip is lossless without adding a ``kind`` tag to the primitives (which would
  have meant re-touching LP-203).
- **``belongsTo`` = the RESOLVED link, list-capable, ``None`` when unresolved; the raw name stays in ``fields``.** A
  ``DocumentEntry`` carries ``belongs_to: list[BorrowerLink] | None`` where ``BorrowerLink`` = ``(borrower_id,
  confidence, method)`` from LP-202 (self-describing, no DB join at read time); ``None`` = no borrower resolved, a
  **non-empty** list = one (or many, for a joint document). A validator rejects ``[]`` so "resolved to nobody" can't
  masquerade as empty. The document's raw asserted name is an ordinary ``Field`` in ``fields`` — the resolved reference
  and the raw claim are kept separate (mirrors ADR-239's raw-name-vs-resolved-link split). ``belongs_to`` references a
  borrower *entity*, not another snapshot section, so it is not a cross-section link.
- **No cross-section correlation — enforced structurally, not by convention.** There is simply no field anywhere that
  references another section's keys/entries, so a MISMO↔document correlation cannot even be *expressed* in the type. The
  MISMO map's keys are free strings, not anchors anything else can point at.
- **Absent ≠ empty at the section level too.** Each section carries an ``absent`` marker with ``present()`` / ``missing()``
  factories and a validator (mirroring LP-203's ``Field``), so "no documents yet" (present, empty ``entries``) is
  distinct from "documents section not built/failed" (``absent``). Both survive JSON round-trip.
- **Calculations shaped to FIT, not call.** Each of dti/ltv/mi/reserves is a ``CalculationEntry`` = ``{value:
  dict[str, str|bool|None], breakdown: list[CalcBreakdownLine]}`` where ``CalcBreakdownLine.source`` is a **free string**
  (the calculator vocabulary ``stated``/``computed``/``extracted``/``manual``/``override`` — distinct from
  ``FieldSource``), so any calculator line round-trips with its tag. Money is stringified for exact JSON. Cash-to-close
  is deliberately absent (not a field).
- **Versioned + extensible.** ``snapshot_version`` (an int; ``SNAPSHOT_VERSION = 1``) is stored so a reader always knows
  the shape. The field maps are open ``dict[str, …]`` (new keys need no schema change) and container models keep
  Pydantic's default ``extra`` (not ``forbid``) so a future field is forward-compatible for an older reader — only the
  ``Field``/``PiiField`` primitives forbid extras (needed for the union).

**Consequences:** pure schema — nothing populates it yet (assemblers LP-205/206/207, builder LP-208, persistence LP-209).
JSON round-trip is lossless (the acceptance bar for LP-209), preserving PII as ``display`` + versioned ``match_hash``
(``str | None``, no raw value), nullable confidence + derived source, calculator source tags, and the absent≠empty
distinction at field and section level. Reuses ADR-240 (LP-203 primitives), ADR-239 (LP-202 links + raw-vs-resolved
split), and ADR-238 (LP-201 confidence). Deferred: the collection deep-immutability caveat above; populating any section;
and everything downstream (assemblers/builder/persistence/UI).

## ADR-242: MISMO section assembler — stable dotted-key flattening + null-omits-absent (LP-205)

- **Date:** 2026-07-09
- **Status:** Accepted

**Context:** The first Stage-1 assembler (LP-205) reads the already-parsed, persisted 1003/MISMO data and reshapes it
into LP-204's flat ``mismo`` section (``dict[str, Field | PiiField]``). It does not parse MISMO. Two real decisions:
the flat-key convention (and its *stable* index basis — the same fact must land at the same key across runs) and which
MISMO fields are PII.

**Decision:**

- **Stable dotted-key convention:** ``loan.<field>``, ``property.<field>``, ``borrower.<n>.<field>``,
  ``borrower.<n>.income.<m>.<field>``, ``borrower.<n>.employer.<m>.<field>``, ``borrower.<n>.declaration.<slug>``,
  ``liability.<k>.<field>``, ``asset.<k>.<field>`` — a flat map (no nesting) as LP-204 requires.
- **Indices derive from a deterministic ordering, never raw list position:** borrowers by ``borrower_position``
  (tie-break on id); nested (income/employer) and file-level (liability/asset) collections by ascending row ``id``.
  The same *input rows* always produce the same keys — deterministic **within** a run. The order is deterministic, not
  semantic (``income.1`` is the lowest-id item, not "the base income") — a rule reads a *set* of ``borrower.N.income.*``
  keys, not "the first" one. **Correction (post-review):** the positional index is NOT a durable per-row identity across
  runs — soft-deleting or inserting a lower-ordered sibling shifts every later index (``income.3`` → ``income.2``), so a
  cross-run key diff would misattribute. A per-run snapshot doesn't rely on cross-run key identity today; if that need
  arises, key by the immutable row id. (The original "same fact → same key on every run" overstated this.)
- **``NULL`` → absent → OMIT the key.** A value the MISMO didn't carry (a null column or a missing sub-entity) is
  absent: its key simply doesn't appear. A non-null value is present, *including an empty string* (present-but-empty).
  So "not in MISMO" (key absent) is structurally distinct from "carried as blank" (key present, value ``""``), honoring
  LP-203's absent≠empty without emitting a present-null placeholder. An index gap is legitimate and stable — e.g. an
  all-null asset row (LF-6T3N's known silently-empty asset) yields no ``asset.3.*`` keys, an honest absence.
- **``source = parsed``; ``confidence = null`` on every field.** The MISMO parse is deterministic — ``source=parsed``
  conveys the certainty and confidence stays ``None`` (never a fabricated ``1.0``), reusing LP-201/ADR-238's rule.
- **PII = borrower SSN only, via ``PiiField.from_raw(kind=ssn, loan_file_id=…)``** — masked display + per-file
  match-hash, raw never stored. On this branch the Stated asset/liability tables carry **no account-number column**, so
  there is no account PII to route (a documented completeness gap — a fuller MISMO would). Contact PII (email/phone) is
  deliberately **not surfaced** (not a verification fact; avoids unnecessary PII surface); DOB *is* surfaced (identity
  cross-checks; already plaintext at rest).
- **Values are stringified to JSON scalars** (``Decimal`` → exact string, ``date`` → ISO, ``StrEnum`` → its value)
  because LP-204 hardened ``Field.value`` to reject ``Decimal``/``date`` (no silent precision loss).

**Consequences:** a pure read + reshape (``build_mismo_section`` over loaded ORM rows; ``load_mismo_section`` queries
with ``only_active``); no mutation, no correlation with other sections. Verified on the real file LF-6T3N (122 keys, both
SSNs masked, all ``parsed``/null-confidence, the empty asset correctly absent). Reuses ADR-240 (Field/PiiField), ADR-238
(confidence). **Documented completeness gaps (not backfilled here):** account-number PII, borrower ``current_address_*``
and property ``county`` (parsed-but-dropped store-everything fields that live only on ``phase3_5_1``), and any raw
MISMO catch-all; there is also no transaction data in persisted typed MISMO (transactions live in bank-statement
extractions), so no ``transaction.*`` keys. Deferred: those gaps, and the other sections (documents LP-206,
calculations LP-207), the builder (LP-208), and persistence (LP-209).

**Amendment (2026-07-10, post code-review).** Fixes applied to the assembler:

- **Cross-run key stability was overstated** — corrected to "deterministic within a run" (see the indices bullet above);
  positional indices shift on a sibling soft-delete/insert.
- **Uniform soft-delete filtering.** ``build_mismo_section`` is pure + public, but only filtered income/employers via
  ``_active()`` while trusting the caller's SQL ``only_active`` for borrowers/liabilities/assets — a leak if a caller
  built from unfiltered rows. It now applies ``_active()`` to *every* child collection, and ``_active`` uses the shared
  ``SoftDeleteMixin.is_deleted`` (not a hand-rolled ``getattr(deleted_at)``).
- **Absent ≠ empty for the SSN.** The SSN was gated by truthiness (``if borrower.ssn:``), dropping a present-but-empty
  SSN as absent. It now routes through the ``put`` PII path, whose absent test is ``value is None`` — a blank SSN stays
  present-but-empty (masked placeholder, non-matchable hash).
- **PII is declared per key.** PII routing moved from a bespoke ``if borrower.ssn`` branch into ``put(key, value,
  pii=PiiKind.…)``, so a future sensitive column (an account number) is one ``pii=`` argument away and can't be emitted
  as a plaintext ``Field`` by pattern-matching.
- **Unhandled types fail loud.** ``_scalar`` now *raises* on an unanticipated type instead of ``str()``-fabricating a
  Python repr (which defeated ``Field.value``'s guard).
- **Malformed declarations degrade gracefully.** A non-dict ``declarations`` JSON value is skipped (no declarations)
  rather than raising ``AttributeError`` on ``.items()`` and failing the whole section.
- **Cleanup:** the four child loaders collapse to a ``_by_loan_file`` helper; ``load_mismo_section`` documents that the
  caller must pass a company-scoped ``loan_file`` (transitive scope, ADR-052).

Deferred follow-ups: ``_slug`` declaration-name collisions (two names → one key, last wins) — left as-is; and extracting
the cross-module duplicates (``_slug`` vs ``documents.naming._slug``, ``_scalar`` money vs ``cross_source._money``) into
shared helpers.

## ADR-243: Documents section assembler — option-2 belongsTo (resolved id+name) + LP-204 amendment (LP-206)

- **Date:** 2026-07-10
- **Status:** Accepted

**Context:** The second Stage-1 assembler (LP-206) reads each ACTIVE document's already-extracted facts (LP-201
confidence) and its already-stored borrower links (LP-202) into the ``documents`` section. It does not extract and does
not run matching. The load-bearing decision is the ``belongsTo`` shape; reality also forced two corrections to the
ticket's premises (recorded below).

**Decision:**

- **belongsTo = option-2: a resolved-reference list of ``{borrower_id, name}``, read from the stored links.** Amends
  LP-204: ``DocumentEntry.belongs_to`` changes from ``list[BorrowerLink]`` (``{borrower_id, confidence, method}``, the
  LP-204 shape) to ``tuple[BorrowerRef, ...] | None`` where ``BorrowerRef = {borrower_id, name}``. A ``tuple`` so a
  built entry's resolved list is itself immutable (LP-204's nested-freeze lesson). ``None`` = no borrower resolved
  (appraisal / no-match / unprocessable); a non-empty tuple = one (or many, joint). A validator still rejects an empty
  tuple and a repeated ``borrower_id``. The **match provenance (confidence/method) is dropped** from the snapshot
  reference — it stays in the ``document_borrower_links`` row; the snapshot carries the resolved *identity*. The RAW
  asserted name the document printed stays as an ordinary ``fields["asserted_name"]`` entry — resolved reference and raw
  claim are kept separate (mirrors ADR-239/241).
- **Soft-delete honesty:** only active, current documents are assembled; ``belongsTo`` reads via LP-202's
  ``get_document_borrower_links`` (which already excludes a link to a soft-deleted document/borrower), and a ref is
  emitted only for a borrower still active on the file — a borrower removed after matching drops out of ``belongsTo``.
- **Confidence surfaced FAITHFULLY:** each extracted field carries LP-201's nullable ``confidence`` exactly — a genuine
  number stays, ``None`` stays ``None``; the assembler never fabricates one (a non-numeric confidence coerces to
  ``None``, not a default). This is the first place confidence reaches the snapshot; it stays honest end to end.
- **Absent ≠ empty:** an extracted field whose ``value`` is null (or absent) is omitted; a present empty string is kept.
  Nested/non-scalar extracted values (e.g. bank-statement transaction lists) are not surfaced as fields here (deferred).

**Corrections to the ticket's premises (reality, flagged in Phase 0):**

- **belongsTo was NOT ``str|None``.** LP-204 (post its own review) already typed it ``list[BorrowerLink] | None``; the
  amendment is a *reshape* to ``BorrowerRef`` id+name, not a widening from a string.
- **PII is routed through ``PiiField`` per an explicit ``_PII_FIELDS`` registry — never a plain ``Field``.** Two cases:
  a field the extractor stored **already masked** (``account_number_masked`` / ``id_number_masked`` /
  ``taxpayer_ssn_masked``) → ``PiiField.pre_masked`` (canonical last-4 display, ``match_hash=None``); a field the
  extractor stored **RAW** ("as written" — W-2 ``employee_ssn``, 1099 ``recipient_tin``) → ``PiiField.from_raw`` (masked
  here + a per-file match-hash; the raw is discarded). ``social_security_wages`` / ``_tax_withheld`` are dollar amounts,
  not SSNs. Institution tax ids (W-2 ``employer_ein`` / 1099 ``payer_tin``) — an employer/payer id, not borrower PII —
  ARE routed too (``PiiKind.ACCOUNT`` → ``****NNNN`` + per-file hash): a 9-digit tax id is exactly what the LP-209
  at-rest guard treats as a possible unmasked SSN, so masking them keeps that guard strong instead of exempting a tax
  id (see the 2026-07-10 amendment). The registry is drift-guarded by a test (any ``# SENSITIVE`` extractor field must
  be routed, except the date-typed ``date_of_birth``).
  **[Corrected post-review — see the amendment; the original claim "extraction PII is already masked, no raw to route"
  was FALSE for W-2/1099, which store the SSN/TIN raw.]**

**Consequences:** a pure read + reshape (``build_documents_section(db, loan_file)``; ``build_document_fields`` pure).
Covered by a DB-backed pytest suite (test DB via ``create_all`` = this branch's schema) exercising single / joint /
no-match belongsTo, soft-deleted document + soft-deleted borrower exclusion, honest confidence, PII masking, and
absent≠empty. Reuses ADR-238 (confidence), ADR-239 (LP-202 links), ADR-240 (Field/PiiField), ADR-241 (the container).
**Known limitations / divergences (documented, not resolved here):** (a) **JSON key casing** — the target example is
camelCase (``documentType`` / ``borrowerId`` / ``matchHash``) but the committed snapshot (LP-203/204/205) is
snake_case; a wholesale camelCase pass touches the LP-203 primitives + serialization config, so LP-206 stays snake_case
for consistency and the pass is deferred to its own cross-cutting change (the *structure* matches the target). (b)
**Real-file smoke** — LF-6T3N has zero stored links (the LP-202 matcher was never run — out of scope) and the dev DB is
stamped at a ``phase3_5_1`` Alembic revision lacking LP-201's ``extractions.confidence`` columns, so
``documents_section_smoke`` can't run there; the schema-correct coverage is the DB-backed test suite. Deferred:
nested/non-scalar extracted values, catch-all fields, and the camelCase pass.

**Amendment (2026-07-10, post code-review).** The review found a **raw-PII leak**: the PII allowlist was
``{account_number_masked, taxpayer_ssn_masked}``, but W-2 stores ``employee_ssn`` and 1099 stores ``recipient_tin`` RAW
("as written" per the prompts), so those fell through to ``Field.present(raw_ssn)`` — a plaintext SSN/TIN in the
snapshot blob. Fixes:

- **Complete, typed PII routing.** ``_PII_FIELDS`` now maps each sensitive field to ``(PiiKind, pre_masked)``: raw fields
  (``employee_ssn`` / ``recipient_tin``) go through ``PiiField.from_raw`` (masked + per-file hash, raw discarded);
  pre-masked fields (incl. ``id_number_masked``, previously mis-typed as a plain ``Field``) through the new
  ``PiiField.pre_masked`` classmethod (which owns the last-4 display shape + ``assert_never`` on kind, replacing the
  assembler's hand-rolled copy). ``build_document_fields`` now takes ``loan_file_id`` to salt the raw-PII hash.
- **Drift guard.** A test scans the extractors for ``# SENSITIVE`` typed fields and asserts each is PII-routed
  (``date_of_birth`` excluded — a date, surfaced as an ordinary field as MISMO does); a new raw-SSN/account field can no
  longer be missed silently. The PII test now seeds a raw ``employee_ssn`` / ``recipient_tin`` and asserts no raw value
  (dashed or undashed) appears; the smoke/test tripwire regex now also catches an SSN-shaped ``\d{3}-\d{2}-\d{4}``.
  **(Amended 2026-07-10 — see the EIN/TIN follow-up below: the guard originally scraped ``# SENSITIVE`` + ``TypedField``
  on ONE line, so a ruff-wrapped multi-line field (``employer_ein`` / ``payer_tin``) slipped it silently. It now
  attributes the comment to the nearest preceding ``<name>: TypedField`` declaration, and self-checks that those fields
  are detected — a comment-scrape guard, still deferring the structural fix of a typed ``PiiKind`` marker on the field.)**
- **Confidence honesty.** ``_confidence`` was replaced by ``coerce_optional_confidence`` (LP-201), restoring the ``[0,1]``
  guard the hand-rolled copy dropped.
- **N+1 fixed.** Borrower links are loaded in ONE ``document_id IN (…)`` query and grouped, replacing a per-document call.
  The eager extraction load is filtered to the current version (``selectinload(...).and_(Extraction.is_current)``).
- **``asserted_name`` de-duplicated.** It now aliases the SAME already-built name Field (a pointer, not a second copy
  re-normalized with ``.strip()`` — the two could disagree on whitespace) and never clobbers a real extracted field.

**Resolved (2026-07-10): keep ``belongs_to=None``.** The earlier deferral — that ``None`` can't distinguish
"matched borrowers later removed" from "never resolved" (nor no-match from never-attempted) — is decided as
**keep-``None``, accepted lossy-by-design**. ``None`` means "no borrower attached"; ``fields.asserted_name`` already lets
a consumer split "named someone but unresolved" from "named no one," which is the only distinction any consumer needs
today. The finer reasons (no-match / not-attempted / removed) are intentionally NOT represented — the root cause is
LP-202 storing positive links only (zero rows = both "no match" and "never ran"), so surfacing the distinction would
need an upstream match-attempt record. No consumer requires it, so no marker is added; revisit only if a verification
rule concretely needs it (YAGNI).

Deferred: schema-declared PII (annotate ``PiiKind`` on the extraction ``TypedField`` so the assembler reads
it instead of a parallel registry) — the drift-guard test is the interim; and the ``_scalar`` naming/dedup across the two
assemblers.

**Amendment (2026-07-10): mask employer EIN / payer TIN (surfaced by real-file smokes).** Reconciling the dev DB let the
Stage-1 smokes run on real LF-6T3N, which caught W-2 ``employer_ein`` and 1099 ``payer_tin`` (9-digit business tax ids)
landing as plaintext ``Field``s and tripping the LP-209 PII-at-rest guard. Decision (overriding the original "institution
ids not routed"): route both through ``PiiField.from_raw`` (``PiiKind.ACCOUNT`` → ``****NNNN`` + per-file hash) in
``_PII_FIELDS`` and mark them ``# SENSITIVE`` in the extractors so the drift-guard keeps them synced. A 9-digit tax id is
indistinguishable from a bare SSN to the guard, so masking preserves the strong guard rather than exempting it. Verified
on real LF-6T3N (``employer_ein`` → ``****NNNN``; whole snapshot builds + persists + loads with no raw PII at rest).
**(Follow-up review, 2026-07-10 — the drift guard did NOT actually keep them synced at first: ruff wrapped both fields
across lines, putting ``# SENSITIVE`` on the closing ``)`` where the same-line scrape couldn't see it, so the guard was
silently blind to the two fields this decision added. Fixed the guard to attribute the comment to the nearest preceding
``TypedField`` declaration + self-check those fields; the module docstring was reconciled; the EIN/TIN test now strips
``match_hash`` and checks the dashed form too. Held for a later decision: whether match-hashing a shared institution id
under ``ACCOUNT`` kind is meaningful, and whether the LP-209 at-rest guard should learn to tell an EIN from an SSN rather
than have this layer mask a non-borrower id.)**

## ADR-244: Calculations section assembler — invoke-and-map, source-tags passed through, not-computed=None (LP-207)

- **Date:** 2026-07-10
- **Status:** Accepted

**Context:** The third Stage-1 assembler (LP-207) fills the ``calculations`` section by CALLING the four existing
calculators (DTI/LTV/MI/reserves) and mapping each native return shape into LP-204's uniform ``CalculationEntry
{value, breakdown}``. Lighter than the prior assemblers (it's a mapping), but three choices are worth recording.

**Decision:**

- **Invoke, don't reimplement.** ``build_calculations_section`` awaits ``build_dti_calculation`` /
  ``build_ltv_calculation`` / ``compute_loan_mi`` / ``build_reserves_view`` and maps their results — **zero calculation
  math is duplicated** (the calculators are the source of truth; a re-derivation would be a divergence bug). A test mocks
  the four entry points and asserts they are invoked.
- **Source tags are passed through verbatim, never re-derived.** Each breakdown line copies the calculator's own
  ``source`` (``stated`` / ``computed`` / ``extracted`` / ``manual`` / ``override``) straight onto
  ``CalcBreakdownLine.source``. Because that field is a **free string** (LP-204), the calculator's ``override`` tag — a
  5th value beyond the four the ticket named — survives losslessly with no enum coercion. (The ticket's premise of a
  ``CalcSource`` enum / a ``CalculationLine`` type does not match the committed model, which is ``CalcBreakdownLine`` with
  a string ``source``; reused as-is.)
- **Not-computed = ``None``, never a fabricated 0.0.** When a calculator can't produce its headline it maps to ``None``
  (LP-204: ``CalculationEntry | None``): DTI when ``back_end_dti`` is ``None`` (no income); LTV when ``ltv`` is ``None``
  (no value basis — the refi/no-valuation case); reserves when the view's ``computed`` flag is ``False``
  (``months_available`` ``None`` — no PITI divisor; see the post-review amendment — this was originally a fragile
  ``headline == "—"`` display-string match). **MI is always present** — ``required`` is always determined, and a
  "not required / premium ``None``" answer is *computed*, not missing.
- **DTI uses STATED (MISMO) income — surfaced transparently.** The calculators compute DTI from stated income; the income
  breakdown line carries ``source=stated``, making the input visible. LP-207 does NOT pick a different income or reconcile
  a stated-vs-extracted disagreement — that is a downstream finding; the snapshot shows the calc + its source tag.
- **Money is stringified exactly** (``Decimal`` → string) for both ``value`` headline numbers and breakdown ``amount``,
  honoring LP-204's guard against a silent float. Reserves' ``value`` is the calculator's formatted ``headline`` string
  (the ``CalculatorView`` doesn't expose the raw months number).

**Consequences:** a pure invoke + map (``build_calculations_section(db, loan_file) -> CalculationsSection``; ``map_dti`` /
``map_ltv`` / ``map_mi`` / ``map_reserves`` pure). Covered by mapper unit tests (source pass-through, no line dropped,
not-computed=None, money precision), an invoke-mock test (entry points called), and DB-backed tests running the real
calculators (all-four map; LTV=None on a refi with no valuation). Reuses ADR-241 (the container) and the LP-76/77/87/91
calculators. Cash-to-close is deliberately **out** (not a field). **Limitations (documented):** the real-file smoke
can't run on the dev DB (DTI reads extractions; the dev DB lacks LP-201's ``extractions.confidence`` columns) — the
**Amendment (2026-07-10, post code-review).** The reserves not-computed detection was fragile — it string-matched the
view's display placeholder (``headline == "—"``) to recover ``months_available is None``, coupling across a module
boundary with no shared constant and no real test (the unit test hardcoded the same ``"—"``). Fixes:

- **Structured not-computed signal.** ``CalculatorView`` gains ``computed: bool`` (default ``True``); ``build_reserves_view``
  sets ``computed = result.months_available is not None``. ``map_reserves`` now branches on ``not view.computed`` — a
  placeholder/format change can no longer turn a not-computed reserves into a fabricated present entry, and a ``None``
  headline no longer slips through the old ``== "—"`` check.
- **Typed reserves mapper.** ``map_reserves(view: CalculatorView)`` replaces ``view: object`` + ``getattr`` + a
  ``# type: ignore``, restoring the mypy coverage its three sibling mappers already had.
- **Real coverage.** A DB-backed test seeds a no-loan-terms loan (no P&I → no PITI divisor) and asserts
  ``section.reserves is None`` through the REAL ``build_reserves_view``, so the coupling is exercised end-to-end.
- **Cleanup:** ``_CalcLineItem`` is now a ``Protocol`` (drops the 3-schema union import).

Deferred: the four calculators transitively recompute each other (per snapshot: LTV ×5, MI ×3, DTI ×2 — an existing
calculator-layer coupling; the fix is threading precomputed inputs, not the assembler); ``map_dti`` returns ``None`` for
the whole entry when there is no income (drops the visible housing/debt obligations too — a design choice per this ADR);
``_money`` is a 5th copy of the Decimal→str helper; and the hand-listed ``value`` dicts can drift from the calculator
schemas (a parity test would guard it).

DB-backed suite is the schema-correct coverage. Deferred: cash-to-close; the stated-vs-extracted reconciliation (a
downstream finding, by design); exposing reserves' raw months number if a future need arises.

## ADR-245: Snapshot builder — resilient + honest partial-failure policy; run_id received, not minted (LP-208)

- **Date:** 2026-07-10
- **Status:** Accepted

**Context:** LP-208 stitches the three Stage-1 assemblers (LP-205 MISMO, LP-206 documents, LP-207 calculations) into one
frozen LP-204 ``Snapshot``, stamping metadata. The real decision is how to behave when a section can't be fully built —
the snapshot must be resilient (one section failing can't lose the whole thing) yet honest (a failure is never swallowed
or faked), consistent with the absent≠empty invariant that governs the whole snapshot.

**Decision:**

- **Three-state, honest section outcome:**
  - **present + populated** — the assembler built it;
  - **present + empty** — a genuinely empty section (e.g. a file with no documents) is a *valid, present* empty section
    (empty ``entries`` tuple), NOT an error and NOT absent;
  - **absent + reason** — an assembler that **raises** yields ``Section.failed(reason)``: the section is absent and
    carries a PII-safe explanation, never a fabricated empty section and never a whole-snapshot failure.
- **Minimal LP-204 amendment (recorded here):** each section model (``MismoSection`` / ``DocumentsSection`` /
  ``CalculationsSection``) gains ``reason: str | None`` + a ``failed(reason)`` factory; a validator enforces that a
  *present* section never carries a reason (reason is failure metadata, only valid alongside ``absent``). ``missing()``
  (absent, no reason) and ``failed(reason)`` (absent, with reason) are distinct — "not built" vs "couldn't build".
- **The reason is PII-safe by construction** — the exception's *class name only* (``"documents assembler raised
  ProgrammingError"``), never ``str(exc)`` (which could carry borrower data). The failure is also ``logger.warning``-ed
  with metadata only.
- **Resilience is broad but bounded:** each of the three sections is built in its own ``try/except Exception`` (so
  ``KeyboardInterrupt`` / ``SystemExit`` still propagate). A missing *loan file* (precondition) is a hard
  ``LoanFileNotFound`` — that is not a section failure, it's "there is nothing to snapshot".
- **``run_id`` is RECEIVED, not minted.** ``build_snapshot(db, *, loan_file_id, run_id)`` stamps the ``run_id`` it is
  given; the builder never creates run identity (a verification run supplies it later — the ``Verification`` model exists
  but is not touched here). ``created_at`` is a tz-aware UTC ``utcnow()``; ``snapshot_version = SNAPSHOT_VERSION`` (the
  real constant name; the ticket's ``SNAPSHOT_SCHEMA_VERSION`` does not exist).
- **Stateless, no side effects.** Rebuilt from scratch each call — no caching, no mutation of source data, no DB writes
  (persistence is LP-209). Verified deterministic (two builds of the same state produce equal sections, modulo
  ``created_at``).

**Consequences:** the builder is a thin, resilient orchestrator; the assemblers own all logic (not reimplemented). The
policy shows itself on the real file: the ``snapshot_smoke`` on the dev DB (which lacks LP-201's ``extractions.confidence``
columns) builds a snapshot with **MISMO present (122 facts)** and **documents + calculations absent-with-reason** — an
honest partial snapshot instead of a crash. The COMPLETE all-three-present case is covered by the DB-backed happy-path
test (test DB via ``create_all``). Reuses ADR-241 (the container) and ADR-242/243/244 (the assemblers). The
``belongs_to=None`` "matched-then-removed vs never-resolved" ambiguity is **resolved: keep ``None``, lossy-by-design**
(see the ADR-243 resolution note — no consumer needs the finer reasons; revisit only if a rule does). Deferred:
persistence (LP-209); and triggering / run-creation. Amends LP-204 (ADR-241) with the section ``reason``/``failed``
addition.

**Amendment (2026-07-10, post code-review).** The partial-failure policy was correct for pure failures but broke for DB
errors — the three sections shared one ``AsyncSession`` with no rollback, so a DB error in one section poisoned the
transaction and cascade-failed the later ones with misleading reasons. (The real-file run above likely exhibited this:
``calculations absent (DBAPIError)`` was probably collateral from documents' ``ProgrammingError`` poisoning the session,
not an independent failure.) Fixes:

- **Savepoint per section.** Each section now builds inside ``async with db.begin_nested()`` (a shared ``_build_section``
  helper that collapsed the three copy-pasted wrappers). A DB error rolls back to that section's savepoint only, so the
  outer transaction and the loaded ``loan_file`` stay valid and the next section runs cleanly and fails (or succeeds) on
  its own merits. (A full ``db.rollback()`` was avoided — it would expire ``loan_file`` and break the next section's
  attribute reads.) Failures now log at **ERROR** (a degraded section is alert-worthy), not WARNING.
- **Company-scoped load.** ``build_snapshot`` now requires ``company_id`` and ``_load_loan_file`` filters by it — the
  builder is the tenant boundary (it resolves the id itself, so the "caller passes a scoped loan_file" precondition the
  assemblers assume is now enforced here), closing a cross-tenant leak before LP-209 wires it up.
- **Dead eager-loads removed.** ``selectinload(borrowers/property/lender)`` were never read (the assemblers re-query;
  the calculators reach the lender via ``db.get``), so ``_load_loan_file`` is now a bare scoped row fetch.
- **Nil ``run_id`` rejected** (an un-attributable run is a caller error); the redundant ``snapshot_version=`` kwarg was
  dropped (the model defaults it).

Deferred: whether a *non-DB* assembler exception (a code bug) should propagate (fail loud) rather than degrade to
absent-with-reason — kept the broad ``except Exception`` (the tested resilience contract) plus ERROR logging; narrowing
to fail-loud-on-bugs is a design decision. Also deferred: a shared ``_AbsentableSection`` base for the now-4× absent/
present/missing/failed pattern (LP-204's deferral, stronger now).

## ADR-246: Snapshot persistence — one immutable JSONB blob per run; write-once; PII-clean-at-rest guard (LP-209)

- **Date:** 2026-07-10
- **Status:** Accepted

**Context:** The final core Stage-1 ticket persists a built LP-204 ``Snapshot`` (LP-208) as a durable per-run artifact and
reads it back. Four decisions matter: the storage shape, immutability enforcement, the duplicate-run policy, and — because
this is the moment the snapshot lands at rest — a PII-clean-at-rest guard.

**Decision:**

- **One full JSONB blob per run, NOT shredded.** A ``snapshot_records`` row stores the whole snapshot verbatim in a single
  ``snapshot_json`` JSONB column (via ``Snapshot.model_dump(mode="json")``; load reconstructs with
  ``Snapshot.model_validate`` — proven lossless, preserving PII display+hash, null confidence, source tags, and
  absent≠empty through the DB). Shredding into per-fact columns / dedup / diffing is explicitly rejected for V1: the blob
  is simple, the round-trip is guaranteed, and a snapshot is small. **JSONB (not the app's usual ``JSON``)** is chosen
  deliberately — it validates real JSON at write and stays queryable if a future need arises; the divergence from the
  ``JSON`` convention (ADR-057) is intentional for this queryable artifact.
- **Immutable, append-only — enforced in code.** The row has **no ``updated_at`` and no soft-delete** (a ``TimestampMixin``
  would add ``updated_at``; a ``SoftDeleteMixin`` would allow a mutating delete) — the shape itself is append-only. There
  is **no update method**; the write path is insert-only. The repo has no DB-level append-only trigger/REVOKE pattern to
  reuse, so enforcement is in code (documented). Append-only history is the point: a NEW ``run_id`` → a NEW row, prior
  rows untouched — this is what lets a processor jump back to a previous run's state.
- **``run_id`` UNIQUE, and a bare UUID — not a FK to ``verifications``.** One snapshot per run (the UNIQUE constraint). It
  is not a FK because the builder (LP-208) *receives* ``run_id`` and never mints it from a verification row, so no matching
  row is guaranteed (mirrors how ``findings.verification_id`` began as a bare UUID, ADR-063). ``loan_file_id`` is an
  indexed FK to the owning loan file (CASCADE, ADR-052) — many runs per file.
- **Duplicate ``run_id`` → RAISE (``SnapshotAlreadyPersisted``), never overwrite.** Re-persisting a run is a programming
  error; the DB UNIQUE is the real guard, the raise is the clear signal. Chosen over a silent no-op so a double-write is
  surfaced, not hidden.
- **PII-clean-at-rest write guard (the last line of defense).** Before the insert, the serialized snapshot is scanned for
  RAW PII — a dashed SSN (``\b\d{3}-\d{2}-\d{4}\b``; a masked ``***-**-1234`` never matches) and a bare 9+-digit run
  (``\b\d{9,}\b`` — an unmasked SSN-without-dashes or account number). The word-boundary anchoring means it does **not**
  false-positive on a hex ``match_hash`` (digit runs there are surrounded by hex letters — no boundary) nor on money like
  ``"1160000.00"`` (a decimal breaks the run at 7 digits) — verified against a real built snapshot carrying a masked SSN,
  a hash, and money. If raw PII is found the write **fails loudly** (``RawPiiAtRestError``) and nothing is inserted: a raw
  SSN at rest is the worst outcome, so a leaking snapshot is never stored. The guard catches an upstream assembler bug; it
  does not re-mask (masking is the assemblers' job, LP-203/205/206).

**Consequences:** ``persist_snapshot(db, snapshot)`` (insert-only, flush-only, guard + dup-check) and ``load_snapshot(db,
run_id)`` / ``load_snapshots_for_loan_file`` reconstruct the frozen snapshot. New table + migration
(``c4e9a7f2b8d3``, single head; offline DDL verified). Covered by DB-backed tests: lossless round-trip, write-once
(dup raises, one row), append-only history (two runs → two rows, both loadable), PII-at-rest (masked snapshot stores
clean; a raw-SSN and a raw-account snapshot are both rejected), and a build→persist→load end-to-end through LP-208.
Reuses ADR-203 (PII), ADR-241 (the model), ADR-245 (the builder), ADR-052 (owned-child scoping). The real-file smoke
(``snapshot_persist_smoke``) needs this branch's migrations on the target DB; the dev DB is stamped at a ``phase3_5_1``
revision, so the DB-backed suite (test DB via ``create_all``) is the schema-correct coverage. **Deferred (future, only
if storage hurts):** dedup / diffing / delta-encoding across a file's runs — a full blob per run is the V1 decision;
and a DB-level append-only guard (trigger/REVOKE) if code-level enforcement ever proves insufficient.

## ADR-247: Rule-kind classification — the canonical Stage-2 routing table + Priya-validation gate (LP-301)

- **Date:** 2026-07-10
- **Status:** Accepted

**Context:** Stage 2 evaluates ~130 verification rules along three paths (architecture v2 §3C). Which path each rule
takes — and whether it gets the deterministic numeric bookend — must be *machine-readable* and *version-controlled*, not
locked in a human-facing spreadsheet. LP-301 formalizes the first-pass classification (``docs/stage2-rule-classification.xlsx``)
into that canonical artifact and stands up the Priya-validation gate. It is data + tracking; no engine logic (the
evaluator is LP-304+).

**Decision:**

- **Four kinds → routing (architecture v2 §3C):** ``calculative`` (deterministic pre-compute → AI selects inputs →
  deterministic re-verify — the *bookend*), ``structural`` (deterministic check; AI ONLY for fuzzy entity matches),
  ``judgmental`` (pure AI + human ratification), ``out_of_scope`` (not evaluated — external/LOS/post-submission/
  unsupported). Six ``evaluation_path`` values: ``deterministic_bookend+ai`` / ``deterministic_bookend`` (calc, with vs
  without AI input-selection) / ``deterministic_only`` (structural exact) / ``ai_fuzzy_match`` (structural fuzzy) /
  ``ai_judgment`` / ``static_filter``.
- **The structural exact-vs-fuzzy split is made EXPLICIT** — the xlsx prose didn't cleanly separate them. Rule:
  a structural rule whose eval-path mentions "AI" is **fuzzy** (``exact_match=False`` → ``ai_fuzzy_match``); otherwise it
  is **exact** (``exact_match=True`` → ``deterministic_only``, NO AI call). This encodes the design principle "AI is spent
  on judgment and fuzzy matching, not on exact checks (SSN/DOB/price)". Result: 60 structural = 32 exact + 28 fuzzy.
  ``exact_match`` is ``None`` for non-structural rules.
- **``calculative`` ⟺ ``numeric_check``.** Every calculative rule (29) gets the deterministic bookend; no other kind
  does. (Confirmed against the xlsx: 29 numeric-check = 29 calculative.)
- **Plain-text CSV artifact + thin loader, CSV is source of truth.** ``app/verification/rules/rule_kinds.csv`` (one row
  per rule, git-diffable line-by-line) is authoritative; ``app/verification/rules/kinds.py`` is a thin cached reader
  (``load_rule_kinds`` / ``kind_for`` / ``rules_by_kind`` / ``numeric_check_rules`` + gate helpers). **CSV, not YAML**:
  the schema is a flat 10-column table, stdlib ``csv`` needs no dependency (PyYAML is only transitive here), and a flat
  CSV diffs cleanly. ``docs/stage2-rule-classification.md`` is a companion table *generated from the CSV*
  (``app.scripts.generate_rule_kinds_md``), so future tickets read rule_id→kind→path without the xlsx, and it can't drift.
- **Priya-validation gate (tracking only — LP-301 signs off nothing):** every rule ships ``priya_validated=False``.
  A calculative rule carrying a **regulatory** threshold/window/limit/factor is ``threshold_needs_signoff=True`` and is a
  ship-blocker until validated (22 of 29 — DTI limit, conforming limit PE-1, seasoning CR-6, IPC PC-4, large-deposit
  AS-1, income-variance IN-1, …). Helpers ``unvalidated_rules`` / ``rules_needing_threshold_signoff`` /
  ``pending_threshold_signoff`` let a later ticket *block* shipping; here they only report.

**Formalization notes / re-tags (flagged for Priya, not silently chosen):**

- **Count is 133, not "130".** The xlsx is titled "130 Rules" but has 133 data rows (29+60+29+15). All 133 are
  formalized — dropping rows would be worse; the title mismatch is noted.
- **``threshold_needs_signoff`` defaulted FALSE for 7 self-consistency calculative rules** — CR-2 (HCLTV compute),
  AS-3 (cash-to-close sufficiency), DT-4 (tax vs assessed), DT-5 (premium vs binder), IH-4 (dup of DT-5), MI-2 (factor
  vs certificate), PR-2 (appraised vs price lesser-of): they are arithmetic but embed no *regulatory constant* to sign
  off (they compare two documented values / a min()). Flagged — flip to True if any hides an investor-specific value.
- **MI-1 kept Calculative** (xlsx tag) though it is a presence-gated-by-LTV check — borderline Structural/Calculative;
  flagged for Priya.
- **IH-4 is a literal duplicate of DT-5** (the xlsx "why" says "dup DT-5"); both kept in the 133, dup flagged.

**Consequences:** the CSV is the single source the Stage-2 orchestrator (later) routes from; the ``.md`` companion and the
loader read it, nothing re-derives from the xlsx at runtime (no openpyxl dependency). Covered by tests (all 133 present,
counts, structural exact_match explicit, calc⟺numeric, out-of-scope never AI, loader round-trip, gate helpers). No DB
table (rules-as-data-in-repo, mirroring the existing ``app/verification/rules/`` package). **Deferred:** rule specs
(LP-303+), the evaluator (LP-304), prompts, the orchestrator, and the actual Priya sign-offs (only the tracking exists).
The flagged re-tags/dup await Priya's validation pass.

## ADR-248: Surface bank-statement transactions in the snapshot (Option A) — a nested TransactionRecord list (LP-302a)

- **Date:** 2026-07-10
- **Status:** Accepted

**Context:** The LP-302 recon found a real Stage-1 completeness gap: bank-statement **transactions** (the per-deposit
inputs AS-1 large-deposit and later NSF/chaining/recurring-debit rules need) live only in the raw
``extraction.extracted_data`` JSON — the documents assembler skips nested lists (``documents_section.py`` ``_scalar``
returns ``None`` for a list). So a Stage-2 evaluator that reads *only the snapshot* (the §3C invariant) could not evaluate
a per-transaction rule. This ticket is **Option A** from that recon: surface transactions IN the snapshot rather than let
the evaluator read raw extraction (which would break "evaluator reads only the snapshot").

**Decision:**

- **Add a nested ``TransactionRecord`` list to ``DocumentEntry``.** ``DocumentEntry.transactions: tuple[TransactionRecord,
  ...] | None`` — a ``tuple`` for immutability (the LP-204 frozen-nested lesson). ``TransactionRecord`` is a frozen model
  whose four attributes are each an ordinary LP-203 ``Field`` (``source=extracted``, nullable confidence, absent≠empty):
  ``date``, ``amount``, ``direction`` (``credit``/``debit``), ``description``.
- **Absent ≠ empty for the list:** ``None`` = not surfaced/absent (a non-bank document, or a bank statement whose
  extraction carried no transaction list); an **empty tuple** = a statement present with **zero** transactions. The two
  are deliberately distinct and both round-trip.
- **``account`` on the record as a PRE-MASKED, non-matchable ``PiiField`` — display/context only (amended 2026-07-10;
  supersedes the original "no account on the record" decision).** Each ``TransactionRecord`` now carries ``account:
  PiiField`` = the parent statement's masked account (``display`` = ``****NNNN`` from ``account_number_masked``,
  ``match_hash=None``), resolved once per statement (every row shares it). It is built with ``PiiField.pre_masked`` — **not**
  ``from_raw``: on this branch the extractor only ever has a pre-masked account (no raw form), so there is nothing to hash,
  and the mask **must not** be hashed. Hashing ``****5667`` would produce a value that collides with **every** same-last-4
  account — the LP-203 colliding-hash bug — a false match worse than no match. ``match_hash=None`` is the **honest** value
  and it is **structurally non-matchable**: a new ``PiiField.matches()`` (added here) treats a ``None`` hash as
  never-equal, so two ``None``-hash accounts NEVER match each other (a bare ``==`` would wrongly return ``True`` for
  ``None == None``) and a ``None``-hash never matches a real hash — the absent-is-not-matchable invariant from LP-203, now
  enforced in one place instead of by every caller. The account is carried for **display/context only** (which account a
  deposit landed in), never as a cross-section match key.
  - *Why reversed from "no account":* the account is genuinely useful per-row context for AS-1's finding output ("a
    $8,076 deposit into ****5667"), and carrying it **honestly** (pre-masked, non-matchable) costs nothing and papers over
    nothing — the impossibility of the hash match is made explicit in the type (``match_hash=None`` + ``is_matchable``),
    not hidden by omission.
  - **KNOWN GAP — the deposit↔MISMO-asset account cross-section match is NOT achievable on this branch, and is not faked.**
    Two independent reasons: (a) extraction only ever holds a **pre-masked** account (no raw value to hash), and (b) MISMO
    ``StatedAsset`` has **no account column** (no ``asset.N.account`` fact to match against). Consequence: the
    deposit↔asset **sourcing-corroboration** path is unavailable — AS-1 still works (it evaluates deposit amount vs a
    threshold + the AI sourcing judgment; the account match was *corroboration*, not a core input). **Unblock condition:** a
    future ticket that (1) surfaces a RAW account in extraction and (2) adds a MISMO asset-account column can then produce a
    real ``match_hash`` (via ``from_raw``) and enable the match — **additive**: the ``PiiField`` shape already supports it and
    the None-is-unmatchable invariant is already enforced. We deliberately did **not** build speculative raw-account plumbing
    now (no synthetic-raw hash, no unused code path) — there is no consumer on this branch; that is the unblock ticket's job.
- **``description`` is redacted, not raw (deviation, forced by a hard constraint).** Real bank descriptions carry payroll
  IDs / confirmation #s / transfer IDs — on LF-6T3N **37 of 50** descriptions contain a 9+-digit run, exactly what the
  LP-209 PII-at-rest guard rejects. So "raw and faithful" (surface the description) and "persist/load round-trips" are
  *incompatible* on real data — a raw description makes the snapshot **unpersistable**. Resolution: surface the
  description with any ``\d{9,}`` run or ``\d{3}-\d{2}-\d{4}`` SSN pattern (the exact patterns the guard flags) redacted to
  ``[redacted]``, keeping the **sourcing signal** AS-1 needs (PAYROLL / TRANSFER / VENMO) and short identifiers (SAV 5683,
  dates, alnum codes). This is the PII-safe-at-rest invariant applied at the assembler (the right layer) rather than
  weakening the guard. ``direction`` is derived from ``transaction_type`` (deposit/interest → credit; withdrawal/fee →
  debit) with an amount-sign fallback.
- **``snapshot_version`` bumped 1 → 2** — the shape genuinely changed. The reader's strict version check (ADR-241) means a
  persisted **v1** blob no longer loads under the v2 reader; acceptable because nothing in production persists snapshots
  yet (the only v1 rows are dev/test artifacts). The change is otherwise **additive**: other sections and the round-trip
  are unaffected; non-bank documents simply carry ``transactions=None``.

- **Review amendment (2026-07-10, post-`150ce66`) — the per-row ``account`` was REMOVED (re-reversing back to the original
  "no account on the record").** A ``/code-review`` found the amended per-row account net-negative: the masked account is a
  **per-statement** fact already carried **once** on the parent ``DocumentEntry.fields["account_number_masked"]``, so a copy
  on every ``TransactionRecord`` duplicated it N× in ``snapshot_json`` (LF-6T3N: 50×) for a field **no consumer reads** (the
  cross-section match is the KNOWN GAP — impossible on this branch). A per-transaction rule reads the account from the entry
  it iterates; ``_statement_account`` was deleted. This also **removed a version-shape hazard**: the amendment had added a
  *required* field without bumping ``snapshot_version`` (still 2), which made a pre-``150ce66`` v2 blob fail to load; the
  shape now reverts to the transactions-only v2. ``PiiField.is_matchable`` / ``matches()`` are **kept** (general primitives)
  and ``matches()`` was hardened to return ``False`` (not ``AttributeError``) for a non-``PiiField`` argument. Also fixed in
  the same review pass: **direction** is now classified from ``transaction_type`` **only** — the old positive-amount →
  ``credit`` fallback forged a deposit on every unlabelled/ambiguous withdrawal (the extractor stores ``amount`` positive), a
  false AS-1 large-deposit; an unknown/ambiguous type now yields an **absent** direction (never a guess), tagged with a new
  ``FieldSource.DERIVED`` (not mislabelled ``extracted``). **Redaction** was broadened to also scrub space/dash-grouped
  accounts/cards (``1234 5678 9012 3456``). The **at-rest guard** now excludes decimal-money (``123456789.00`` no longer
  aborts a persist) while still flagging a bare-integer id. Supersedes the amended-account bullet and the ``direction …
  amount-sign fallback`` clause above.

**Consequences:** a pure read + reshape (``build_transactions`` is pure; the assembler surfaces transactions when
``document_type == "bank_statement"`` and the extraction carried a transaction list). A small **additive** helper landed on the LP-203 primitive — ``PiiField.is_matchable`` /
``PiiField.matches()`` — enforcing absent-is-not-matchable structurally so no caller re-implements a ``None``-safe hash
compare. Verified on real LF-6T3N: 50 transactions surfaced across 5 statements, each carrying the statement's ``****NNNN``
account (``match_hash=None``), descriptions redacted, the LP-209 at-rest guard passes, and persist→load == built (lossless
v2 round-trip). Reuses ADR-240 (Field), ADR-241 (the container + version discipline), ADR-243/246 (the documents assembler
+ PII-at-rest guard). **Scope note:** only bank-statement transactions are surfaced (the only nested list AS-1 + near-term
per-transaction rules need); other nested extraction structures are not surfaced (none seen beyond transactions).
**Deferred / KNOWN GAP:** the deposit↔MISMO-asset account-hash cross-section match — NOT achievable on this branch (needs
both a RAW account in extraction and a MISMO asset-account column; see the amended account bullet above), so the
sourcing-corroboration path is unavailable while AS-1's core (amount-vs-threshold + AI sourcing judgment) is unaffected.
Also deferred: surfacing any future nested list; and (should a real deployment ever hold v1 snapshots) a v1→v2
migration/back-compat reader.

## ADR-249: AS-1 rule spec + load_rule_spec interface — the first Stage-2 rule artifact (LP-303)

- **Date:** 2026-07-10
- **Status:** Accepted

**Context:** Stage 2 evaluates each rule by injecting rule-specific DATA into a shared evaluator prompt (the *spine*, with
slots ``rule.criteria`` / ``rule.applicability`` / ``rule.required_inputs`` / ``rule.reference_values`` /
``rule.evidence_required`` / ``rule.guideline_reference`` — ``docs/stage2-evaluator-prompts.md``). That data has to live
*somewhere* the evaluator can load, versioned and reviewable, separate from prompt-assembly code (architecture v2 §3C:
"rules live as files"). LP-303 writes the FIRST such artifact — AS-1 (large-deposit sourcing sweep) — and the
``load_rule_spec(rule_id)`` interface. Nothing consumes it yet (the evaluator is LP-304); this is the spec + loader only.

**Decision:**

- **The spec is a version-controlled YAML file** (``app/verification/rules/specs/AS-1.yaml``), one file per ``rule_id``,
  co-located with the LP-301 kinds table and diffable in review. YAML (pyyaml already a dep) over JSON for comments —
  the file self-documents the provisional-format caveat inline.
- **The spec shape was DISCOVERED from this one real rule, and is explicitly PROVISIONAL.** Fields: ``rule_id`` / ``name`` /
  ``category`` / ``kind`` / ``numeric_check`` / ``criteria`` / ``applicability`` {scope, trigger} / ``required_inputs`` (a
  structured list of {name, snapshot_path, description}) / ``reference_values`` {large_deposit_threshold, priya_validated,
  threshold_needs_signoff} / ``subject_enumeration`` / ``subject_key_fields`` / ``evidence_required`` /
  ``guideline_reference`` / ``spec_version``. It maps 1:1 to the spine slots plus the calculative-body needs (a threshold to
  surface as operand Y) and the LP-306 finding-identity needs (per-deposit subject key). We did **not** design a general
  multi-rule schema now — that is LP-308's job (the caveat is stated in the file header, the module docstring, and the
  ``RuleSpec`` docstring).
- **RESOLVED input source = the frozen SNAPSHOT, never raw extraction (LP-302 Option A).** Every ``required_inputs`` entry
  points at a snapshot path: deposits at ``documents.entries[document_type=="bank_statement"].transactions[…]`` (LP-302a
  ``TransactionRecord`` — amount/date/direction/description), the statement's pre-masked account at
  ``documents.entries[].fields["account_number_masked"]``, and monthly qualifying income at the mismo per-item fact
  ``mismo.facts["borrower.<n>.income.<m>.monthly_amount"]`` (computed aggregate available at
  ``calculations.dti.value["gross_monthly_income"]``). This keeps the LP-302 §3C invariant "the evaluator reads only the
  snapshot" — a test asserts no path names ``extracted_data``/``extraction``.
- **``load_rule_spec(rule_id) -> RuleSpec`` is the evaluator's ONLY entry point, and is swappable.** It reads the YAML
  today, but the signature promises nothing about a file — a DB-backed source later is a drop-in. Returns a frozen,
  ``extra="forbid"`` pydantic ``RuleSpec`` so a missing slot or an unknown/typo'd key **fails loud at LOAD time**, not deep
  in an evaluation. A four-exception hierarchy (``RuleSpecNotFound`` / ``RuleSpecInvalid`` / ``RuleSpecInconsistent`` under
  ``RuleSpecError``) makes each failure mode distinguishable. Cached (``functools.cache``) — specs are immutable artifacts;
  a private, directory-parameterized ``_load_spec_from(dir, rule_id)`` stays uncached so tests point it at a temp dir.
- **The spec must AGREE with ``rule_kinds.csv`` (LP-301) — the CSV stays the single gate of record.** ``load_rule_spec``
  cross-checks ``kind`` and ``numeric_check`` **and** the validation gate (``reference_values.priya_validated`` /
  ``threshold_needs_signoff``) against the rule's CSV row and raises ``RuleSpecInconsistent`` on any divergence. A spec can
  never mark a threshold "validated" while the CSV says it is not.
- **The threshold is recorded as DATA, honestly.** ``reference_values.large_deposit_threshold = "50% of total monthly
  qualifying income"`` lives in the spec (not in the AI's memory, not hardcoded in code — a test greps ``app/verification``
  to prove no ``.py`` carries the threshold prose). Its validation status is recorded **as it truly is**: the ticket draft
  suggested ``priya_validated: true``, but ``rule_kinds.csv`` has AS-1 ``priya_validated=false`` +
  ``threshold_needs_signoff=true`` — so the spec records ``false`` (the CSV cross-check would reject ``true`` anyway). The
  50% threshold is honest *proposed* data pending Priya sign-off, not a confirmed value.

**Contradictions resolved (flagged in Phase 0 before building):**

- **Account is no longer on ``TransactionRecord``.** A prior review (commit ``70fac7c`` "LP-302a review: remove per-row
  account") reverted the account-on-record change; the ticket's sketch (``subject_key_fields: [account, date, amount]`` and
  transactions "with account") assumed it was there. Resolution: ``required_inputs`` references the account at its ACTUAL
  location — the parent ``DocumentEntry.fields["account_number_masked"]`` (pre-masked, non-matchable) — and
  ``subject_key_fields``'s ``account`` resolves from the parent entry, not the transaction. The deposit↔MISMO-asset match
  remains unavailable (the LP-302a KNOWN GAP), which AS-1's core does not need.
- **``priya_validated`` true-vs-false.** Resolved in favor of the CSV (``false``) per the ticket's own "record honestly"
  instruction and the cross-check — see the threshold-as-data decision above.

**Consequences:** ``app/verification/rules/specs/AS-1.yaml`` + ``app/verification/rules/specs.py``
(``RuleSpec``/``Applicability``/``RequiredInput``/``ReferenceValues`` models, the exception hierarchy, ``load_rule_spec`` +
``_load_spec_from`` + ``_check_consistency``); 17 tests in ``tests/verification/rules/test_specs.py``. Reuses ADR-247
(kinds table + gate), ADR-248 (the snapshot transaction/account input path), and the §3C spine-slot contract. **Deferred to
LP-308:** generalizing the spec format across all ~133 rules (the AS-1 shape is provisional). **Out of scope (later
tickets):** the evaluator / AI call + prompt assembly (LP-304), the numeric bookend (LP-305), finding output + the four
states + per-deposit identity (LP-306), other rules' specs, and a DB-backed spec store.

## ADR-250: Rule + fact-tag storage — files-as-source-of-truth, DB-as-projection; retire phase3_5_1's verification_rules (LP-311)

- **Date:** 2026-07-13
- **Status:** Accepted

**Context:** The fact-tag architecture (§3D) needs rules and the tag vocabulary to be QUERYABLE (the engine must ask "which
tags does rule X require?", "which rules use tag Y?", "what is the DAG?"). Two forces pull apart. Compliance wants rule
SCHEMA/POLICY — the Priya-validated thresholds, the tag definitions — to live in git as files, because git history IS the
audit trail (§3D "Storage": "Files > DB for this"). Runtime wants those same facts in the DB to join and filter. A prior
attempt, ``verification_rules`` (LP-118 / ADR-238, branch phase3_5_1), made the DB table the primary store with a
version-controlled seed — but it was shaped for the ABANDONED per-rule code-evaluator engine (columns ``evaluator`` /
``applicability`` / ``canonical_type`` / ``message_template``), does not fit the tag architecture, and a dev DB migrated on
that branch carries the table + ``rule_change_audits`` as ORPHANS this branch's Alembic does not track (see LP-310 Phase 0).

**Decision — REPLACE, with files as the single source of truth and the DB a pure projection:**

- **Files are authoritative; the DB is a rebuildable PROJECTION, never hand-edited.** The version-controlled source files —
  ``rule_kinds.csv`` (identity + kind + the Priya gate, the gate of record), ``specs/<rule_id>.yaml`` (the full ``RuleSpec``),
  and the fact-tag machine-source CSVs (below) — are the truth. The LP-311 loader
  (``app.verification.rules.projection.project_files_to_db``) reconciles four DB tables to them (insert new / update changed /
  remove vanished), so a hand-mutated row is overwritten on the next run. This is the clean §3D separation: SCHEMA/POLICY in
  git, DATA/RESULTS (tag *values* in snapshots, findings) in the DB. The projection is a queryable read-copy of the policy,
  not a second source of it.
- **Vocabulary xlsx → committed machine-source CSVs, mirroring LP-301.** The human/Priya authoring form is
  ``docs/snapshot-fact-tags.xlsx``; a stdlib generator (``app.scripts.generate_fact_tags``) converts it, once, into committed
  ``fact_tags.csv`` / ``rule_tags.csv`` / ``tag_dependencies.csv`` under ``app/verification/rules/`` — exactly as LP-301
  converted a classification xlsx into the committed ``rule_kinds.csv`` that the loader reads (the xlsx is never read at
  runtime; no ``openpyxl`` runtime dependency). A CI ``--check`` mode guards drift.
- **Four GLOBAL, un-scoped tables** (reference data identical for every company; NO ``company_id`` — per-tenant overrides are a
  future ticket): ``rules`` (natural key ``rule_id``, kind/gate columns + a JSONB ``spec`` payload, null when no spec file),
  ``tags`` (natural key ``tag_id``, entity/value_type/allowed_values/description/produced_by + JSONB ``extras``),
  ``rule_tags`` (rule → required-tag edges), ``tag_dependencies`` (the tag DAG). UUID pk + natural-key UNIQUE, ``TimestampMixin``,
  no soft-delete (regenerated data), natural-key FKs on the edge tables. Nullable JSONB uses ``none_as_null=True`` so a missing
  spec / non-enum tag is SQL NULL, not a JSONB ``'null'``.
- **Load-time consistency checks fail loud** (``ProjectionError``) before any write: a rule requiring a tag absent from the
  vocabulary, a dependency edge to a non-existent tag, and a cycle in the tag DAG (topological check). Spec/CSV agreement is
  enforced by ``load_rule_spec`` itself (``RuleSpecInconsistent``), keeping the CSV the gate of record.
- **The AS-1 (and IN-1) validation contradiction resolves to the FILES.** LP-118's seed optimistically marked AS-1 and IN-1
  ``validated=TRUE`` (the only 2 of its 140 rows) — but Priya has not signed off in this branch's governance, so the files win:
  both stay ``priya_validated=false`` / ``threshold_needs_signoff=true``. The abandoned seed's TRUE is not adopted anywhere; the
  two threshold rules are flagged for Priya review in the ticket doc. General policy: the files' validation state is
  authoritative; a seed's TRUE is never auto-adopted.
- **Retire the orphans in this migration.** The LP-311 migration ``DROP TABLE IF EXISTS`` ``rule_change_audits`` then
  ``verification_rules`` (CASCADE) so a dev DB migrated on phase3_5_1 converges with a fresh one; on a fresh DB it is a no-op.
  ``downgrade`` does NOT recreate them (they were never part of this branch's schema). No Alembic fork exists on this branch —
  the LP-118 revision is absent here, so ``alembic heads`` is the single head ``c4e9a7f2b8d3`` and the new migration simply
  stacks on it (a merge migration would only be needed if phase3_5_1 were merged, which it is not).
- **``load_rule_spec`` stays FILE-BACKED, its signature preserved as the swap seam.** LP-311 mirrors the full spec into
  ``rules.spec`` and adds DB read accessors (``get_rule`` / ``get_tag`` / ``tags_for_rule`` / ``rules_using_tag`` /
  ``tag_dependencies``) alongside it, so a DB-backed ``load_rule_spec`` is a later drop-in without breaking callers.

**Salvage from the abandoned seed:** ``rule_kinds.csv`` already captures identity (``rule_id`` = playbook id, name, category)
for all 133 rules; the seed's remaining columns are evaluator-engine-shaped and deliberately NOT resurrected (SCOPE). The only
genuinely additive datum was IN-1's ``variance_pct=5`` threshold (recorded for the future IN-1 spec + Priya). The old→new
rule_id map and the 18 message templates are preserved as a reference appendix in ``docs/tickets/LP-311.md``, not in the DB.

**Consequences:** rules and tags are now queryable in the DB while remaining git-governed and Priya-signed in the files — the
drift ADR-238 warned about is structurally prevented, because there is exactly ONE source of truth (the files) and the DB is a
disposable projection. ``tag_dependencies`` is empty today (the vocabulary has no ``depends_on`` column yet — LP-311 Phase 0);
the table + cycle check exist so the DAG is a drop-in once authored. Cross-refs: §3D "Storage", LP-310 (the recon that surfaced
the orphan table), ADR-238 (LP-118's drift warning — now resolved by single-source-of-truth), ADR-247/248/249 (kinds table,
snapshot transactions, AS-1 spec). **Out of scope (later tickets):** tag PRODUCTION (Stage A/B), rule EVALUATION, the stable
content-id snapshot change (LP-312), per-tenant overrides, any hand-edit path to the DB, and a UI.

## ADR-251: The tag object model + two-layer snapshot + stable content-ids (LP-312)

- **Date:** 2026-07-14
- **Status:** Accepted

**Context:** The fact-tag architecture (§3D) structures raw facts into clean tags that deterministic code queries; a
tag cites the raw facts it relied on (``source_facts``) and a finding's identity (``subject_key``) is built from stable
tag values. All of that needs raw facts to be REFERENCEABLE by a stable id. The LP-310 recon flagged this as gap #1: the
snapshot's only ids were ``borrower_id`` / ``loan_file_id`` / ``run_id`` — transactions and documents were addressable
only by ARRAY POSITION, which is not stable because the snapshot is rebuilt from scratch each run (a document inserted or
removed shifts every later index). LP-312 is the load-bearing prerequisite for the whole tag layer: it adds stable
content-ids AND defines the tag object model + the tags layer — MODEL + SHAPE ONLY (no production, no evaluation).

**Decision:**

- **Stable, content-derived ids on raw facts.** ``TransactionRecord`` and ``DocumentEntry`` gain a required
  ``content_id`` derived by :mod:`app.verification.snapshot.content_id`: ``"doc"/"txn" + sha256(canonical-content)[:16]``.
  - *Content-derived, run-independent, position-independent:* the hash input is the fact's own content (a document's
    type + resolved borrowers + fields + an ORDER-INDEPENDENT fingerprint of its transactions; a transaction's four
    Fields scoped under its parent document's id), never its array index — so extraction order or an inserted/removed
    sibling elsewhere does not change another fact's id. Same content → same id, every run.
  - *Unique per real fact:* genuinely-duplicated content (two identical deposits) would collide, so a deterministic
    OCCURRENCE TIEBREAK (``#0``, ``#1`` … among byte-identical siblings) is mixed into the hash → distinct ids. Because
    identical siblings are indistinguishable, which one receives ``#0`` is immaterial — the *set* of ids is stable.
  - *PII-at-rest safe by construction:* the id is a letter-prefixed hex token with no internal separator, so in the
    serialized blob it is one ``\w`` run beginning with letters and can NEVER present a ``\b\d{9,}\b`` match to the
    persistence guard (deterministically, not probabilistically). Ids are hashes — they expose none of the content.
  - Field-cell ids are DEFERRED (scoped to transactions + documents, the recon's priority).
- **The tag object model (§3D).** A frozen ``Tag`` (``app/verification/snapshot/tag.py``):
  ``value`` (``JsonValue`` — any JSON value; its domain always includes ``"unknown"``; never fabricated),
  ``confidence`` (``float | None`` in [0,1] — null for parsed, a real number for AI, never invented), ``reasoning``,
  ``source_facts`` (``tuple[str, …]`` of content_ids — never array positions), ``produced_by`` (parsed|ai|derived|spec),
  ``tag_role`` (structural_fact|rule_judgment), ``tag_version``, ``stage`` (A|B). Type only — no production logic.
- **Two-layer snapshot, additively.** The existing three sections (``mismo`` / ``documents`` / ``calculations``) are the
  RAW layer and are UNCHANGED; a new top-level ``tags: TagsSection`` (present-empty, ``by_subject`` keyed by a raw fact's
  content_id) is the TAGS layer, produced over the raw layer by LP-313/314. Chosen additive (a new sibling section)
  rather than nesting the raw sections under a ``raw`` key: nesting would move every existing JSON path and ripple
  through every calculator/consumer, violating "existing content unchanged." ``CalcBreakdownLine`` gains
  ``from_tag: str | None`` (null now; LP-318 populates it) so a calculator line can trace to the tag behind it.
- **One version bump, 2 → 3.** Ids + the tags layer + ``from_tag`` ship under a single ``SNAPSHOT_VERSION`` bump (2 → 3)
  to avoid churn. **v2 is SUPERSEDED, not supported:** no production snapshot was ever persisted (LP-310), so the reader
  supports only v3; a stray dev-only v2 blob is rejected on load (``_known_snapshot_version``) and simply rebuilt.

**Consequences:** tags and findings can now reference raw facts by a stable id that survives a rebuild — the load-bearing
gap is closed. The tags layer is present-empty and round-trips losslessly at v3, ready for LP-313/314 to populate;
``from_tag`` is null, ready for LP-318. The content-id doubles as a content fingerprint (a changed fact → a changed id →
a dependent tag's cache key changes, §3D). Cross-refs: §3D (the tag contract + two-layer shape), LP-310 (gap #1), LP-204
(frozen snapshot model), ADR-248 (transactions in the snapshot). **Out of scope (later tickets):** tag PRODUCTION / any
AI call (LP-313/314), rule evaluation, populating the tags layer or ``from_tag`` (LP-318), findings/subject_key (LP-316),
field-cell content-ids.

## ADR-252: Stage-A tag production for transactions — structure-not-conclude, passthrough vs judged, fail-closed (LP-313)

- **Date:** 2026-07-14
- **Status:** Accepted

**Context:** LP-312 built the tags layer + the Tag object; this is the FIRST ticket where the AI actually produces
fact-tags. Stage A (§3D) turns a SINGLE transaction's raw facts into clean atomic tags — the pattern every later
production pass (Stage B, other entities) will follow. The original AS-1 bug (a hardcoded ``direction=="credit"`` filter
that silently dropped ambiguously-labelled deposits) is exactly what the tag architecture exists to prevent, so the
design must make that class of bug structurally impossible.

**Decision:**

- **Clone the cross-source two-file pattern.** ``ai/tag_production.py`` is the AI boundary (system prompt +
  ``reason_stage_a_transactions`` — the "perceiver"); ``services/tag_production.py`` is the deterministic orchestrator
  (context assembly, batching, caching, writing the tags layer — the "wiring"). Reuses ``complete()`` and the defensive
  array-parser shape (``extract_json_object`` / balanced-span / fenced / wrapped). Does NOT import the stale
  ``verification/evaluators/``.
- **"Structure, don't conclude."** The system prompt casts the model as a senior processor STRUCTURING raw facts into
  tags who does NOT evaluate rules or reach conclusions — north star accuracy + honesty, ``"unknown"`` always available,
  a wrong tag silently corrupts downstream. It asks only for facts (``txn.is_money_in`` resolved from MEANING tolerating
  any label; ``txn.apparent_category`` from the vocabulary), each with confidence + reasoning.
- **Passthrough vs AI-judged.** ``txn.amount`` / ``txn.date`` are already-parsed facts — carried through VERBATIM
  (``produced_by="parsed"``, ``confidence=None``); the AI never re-reads a number (that invites hallucinated digits).
  ``txn.is_money_in`` / ``txn.apparent_category`` are AI-judged (``produced_by="ai"``, the model's confidence,
  ``tag_role="structural_fact"``, ``stage="A"``). Every tag's ``source_facts`` = the transaction's stable ``content_id``
  (LP-312), never a position; content_ids never reach the AI (the batch addresses transactions by a 1-based index and
  the id is reattached deterministically).
- **The direction bug is structurally impossible.** The pass tags EVERY transaction — there is no ``direction=="credit"``
  filter anywhere; ``is_money_in`` is an AI judgment over meaning, so a "transfer"/"ACH"/unlabelled deposit still gets a
  proper tag (pinned by a test).
- **Bounded batches** (15 transactions/call) so position-degradation can't creep in on a long statement.
- **Honest, fail-closed parse.** An AI failure/timeout, a truncated response (``stop_reason=="max_tokens"``), an omitted
  transaction, or an off-vocabulary value all yield ``value="unknown"`` WITH a reason — NEVER a defaulted/fabricated
  value. A genuine AI ``"unknown"`` is preserved as-is (with its confidence + reasoning), distinct from the fallback.
  The passthroughs still succeed even when the AI call fails.
- **Timeout added.** ``complete()`` has no timeout; the reasoner wraps it in ``asyncio.wait_for`` (new
  ``settings.ai_request_timeout_seconds = 60``) → a hung call raises ``AIClientError`` → unknown-with-reason.
- **Cache-by-content-fingerprint.** AI judgments are keyed by a fingerprint of the transaction's four raw fields, so
  identical transactions share one call and an unchanged transaction reuses its judgment on a re-run. Only COMPLETE
  successes are cached (a failed/truncated/partial transaction retries next run). Cost + tokens are logged (metadata
  only, never content).

**Consequences:** the tags layer is now populated for transactions with honest, provenance-carrying atomic tags; the
production PATTERN (prompt → bounded batches → honest parse → cache → write-by-content_id) is established for LP-314 and
beyond. Cross-refs: §3D (staged production + the honesty rules), LP-310 (the cross-source clone target + the direction
bug), LP-312 (the Tag model + content_ids + the tags layer). **Out of scope:** Stage B / correlation tags
(``has_identified_source`` — LP-314), other entities, rules, findings, ``from_tag`` population, the discovery lane.

## ADR-253: Stage-B correlation tags via candidate-then-judge — the sourcing tag (LP-314)

- **Date:** 2026-07-14
- **Status:** Accepted

**Context:** Stage B (§3D) produces CROSS-ENTITY correlation tags — the ones that catch fraud, starting with
``txn.has_identified_source`` (is a deposit sourced, or an unexplained inflow?). Correlation is where the naive approach
breaks: asking the AI to search the whole file for a matching source does not scale and degrades on long files. This is
also the pattern every future correlation tag (undisclosed liability, retained REO) will follow, so the shape matters.

**Decision:**

- **Candidate-then-judge (the scaling split).** Deterministic code does the whole-file SEARCH; the AI only JUDGES a small
  set. ``services/tag_correlation.py`` (pure code) finds, for each money-in deposit, candidate sources across ALL
  transactions in ALL accounts; ``ai/tag_correlation.py`` (the judge, cloned from cross-source) sees ONE deposit + its few
  candidates and returns yes/no/unknown — it NEVER searches and NEVER sees the whole file. Candidate search is
  O(deposits×transactions) pure code (scales to any file size); AI calls scale with deposits, not (deposit×candidate)
  pairs and not with a whole-file AI scan.
- **Candidate-match criteria (PRIYA-CONFIRMABLE).** An own-account transfer = a money-out debit of EXACT amount
  (tolerance param, default \$0.00 — transfers move exact amounts) within a ±5-day window (param); plus a payroll
  self-source when the deposit's own Stage-A ``apparent_category == "payroll"`` (its own line is the evidence). The net is
  deliberately tight because the AI judges genuineness; the thresholds are parameters flagged for Priya. The candidate
  structure is typed + extensible (gift / liquidation / other-account kinds slot in later).
- **"No candidate → no, NOT unknown" (the fraud signal).** A money-in deposit with no candidate and no income signal is
  handed to the judge with an empty candidate set and returns a real ``"no"`` — "looked, found nothing", the
  unexplained-deposit signal AS-1 fires on. ``"unknown"`` is reserved for genuine can't-determine and is produced by DAG
  propagation, not by the judge softening a "no". This distinction is load-bearing and pinned by a test.
- **DAG ordering + confidence propagation.** Stage B runs AFTER Stage A and CONSUMES ``txn.is_money_in`` from the tags
  layer. ``"in"`` → judged; ``"unknown"`` → an ``"unknown"`` sourcing tag produced DETERMINISTICALLY (``produced_by="derived"``,
  no AI call — can't source what isn't confirmed money-in); ``"out"`` → not a sourcing subject (no tag). The sourcing
  confidence is capped at the ``is_money_in`` confidence (a tag is never more confident than its shakiest input).
- **content-id cross-provenance.** ``source_facts`` cite the deposit's ``content_id`` AND, when sourced by a transfer, the
  matched debit's ``content_id`` (LP-312 stable ids). content_ids never reach the AI: candidates are numbered 1..N, the
  model returns a ``source_index``, and the id is reattached here; an out-of-range index fails CLOSED (a "yes" citing a
  nonexistent candidate is untrustworthy → unknown), reusing the LP-313 index-mismapping hardening.
- **Fail-closed + cache.** AI failure/timeout/truncation/malformed → ``unknown``-with-reason, never a defaulted ``"yes"``
  (``complete()`` wrapped in the LP-313 timeout). Judgments are cached by (deposit + candidate-set) content, so an
  unchanged deposit reuses its verdict across runs; only successes are cached (a failure retries).

**Consequences:** the AS-1-critical sourcing tag now exists, with the fraud signal (unsourced = a real "no") intact, and
the candidate-then-judge PATTERN is established for all future correlation tags. Cross-refs: §3D (staged production, the
candidate-then-judge pattern, the honesty rules), LP-312 (content_ids + the Tag model + tags layer), LP-313 (Stage A +
the fail-closed/cache/index-hardening pattern this reuses). **Out of scope:** AS-1 rule evaluation / findings
(LP-315/316), other correlation tags, other entities, the discovery lane, ``from_tag`` population.

## ADR-254: Thin deterministic rule engine + fail-closed gate — AS-1 (LP-315)

- **Date:** 2026-07-14
- **Status:** Accepted

**Context:** The whole fact-tag pivot exists so a rule can be a THIN deterministic query over clean tags —
no AI in the rule, no ``direction==`` label matching, no drift. This is the payoff: AS-1 finally READS the tags
(LP-313/314) and produces a verdict. It also introduces the safety core — the fail-closed gate — that keeps a degraded
input from ever becoming a confident "satisfied". Engine + gate + AS-1 only; the result is in-memory (persistence is
LP-316).

**Decision:**

- **The generic fail-closed gate (``rule_engine/gate.py``).** Every rule runs it BEFORE its logic. Fixed decision
  order: (1) a required load-bearing tag ABSENT → ``couldnt_check`` (names the tag); (2) a load-bearing tag value
  ``"unknown"`` → ``couldnt_check`` (a DISTINCT reason — absent ≠ unknown); (3) a flagged contradiction → ``needs_review``;
  (4) min load-bearing confidence below the floor → ``needs_review``; (5) else PASS. A degraded input can NEVER reach a
  confident satisfied/fired. ``verdict_confidence = min`` of the load-bearing tags' NON-None confidences; parsed
  passthroughs carry ``confidence=None`` (effectively certain, §3D) and are ignored in the min and the floor check.
- **The thin AS-1 rule (``rule_engine/as1.py``) — query + arithmetic, no AI, no label filter.** Per transaction
  subject: applicability is decided from the ``txn.is_money_in`` TAG (absent/unknown → ``couldnt_check``; ``!= "in"`` →
  ``not_applicable``; ``"in"`` → proceed) — a TAG QUERY, never a raw ``direction==`` label, so the original bug cannot
  recur (a "transfer"/"ACH"/unlabelled deposit the AI judged money-in IS evaluated). After the gate passes, it fires iff
  ``amount > threshold AND has_identified_source != "yes"``. The comparison REUSES ``satisfies(Condition(GT, threshold),
  amount)`` — the one place a ``>`` lives (the calculators' re-implement-the-compare drift is not repeated). An
  ``has_identified_source == "unknown"`` never reaches the fire logic — the gate already routed it to ``couldnt_check``.
- **Threshold from the spec; income from the calculator.** The multiplier is extracted from the spec's prose
  ``reference_values.large_deposit_threshold`` ("50% of …" → 0.5) via ``load_rule_spec("AS-1")`` (file-backed, no DB);
  qualifying income comes from the DTI calculator (``calculations.dti.value["gross_monthly_income"]``). Missing income →
  ``couldnt_check`` (never a fabricated threshold). The prose threshold is a known spec-shape gap — a structured field
  would be cleaner (future).
- **Priya-pending handling.** AS-1's threshold is ``priya_validated=false``, so every AS-1 result is flagged
  ``gated_pending_signoff=true`` — a later orchestrator withholds it from "shipped"; the engine never silently ships an
  unvalidated threshold.
- **The result carries its load-bearing tags inline** (``RuleEvaluation.load_bearing_tags`` — tag id + value +
  confidence + reasoning), so a verdict never cites a bare number (§3D provenance move) and LP-316 can persist it.
- **Confidence floor default 0.5** (the spec has no floor field yet) — PRIYA-CONFIRMABLE, like the threshold.

**Consequences:** AS-1 is now a ~arithmetic rule over honest tags, guarded by a reusable fail-closed gate — the
architecture's payoff realized, and the direction bug made structurally impossible at the rule layer too. The gate +
result shape generalize to every future rule. Cross-refs: §3D (the thin rule + the armor/gate), LP-311 (the spec +
declared tags), LP-312/313/314 (the tags the rule reads), ``rules/schema.py`` (the reused ``satisfies``). **Out of
scope:** finding PERSISTENCE / four-state model / subject_key column / event log (LP-316), any AI, other rules, the
orchestrator (LP-321).

## ADR-255: Sourcing STRENGTH — matched paper-trail vs self-asserted claim vs intrinsic (LP-314a)

- **Date:** 2026-07-14
- **Status:** Accepted

**Context:** The LF-6T3N trace exposed that the Stage-B sourcing judge (LP-314) was too generous: it marked a deposit
``has_identified_source: yes`` when the deposit's OWN DESCRIPTION claimed a source ("ONLINE TRANSFER FROM PATEL A
BROKERAGE"), even with NO matching debit found — its reasoning literally said "no candidates were provided… the
description itself establishes this." For a fraud-catching system a description is the borrower's CLAIM, not a verified
paper trail: a $20k deposit matched to an actual same-day $20k own-account debit and a $12k deposit merely LABELLED
"transfer from my brokerage" are not the same evidential strength, yet both got ``yes``.

**Decision — a source STRENGTH, derived deterministically, drives the verdict:**

- **A companion tag ``txn.source_strength``** (produced by Stage B alongside ``has_identified_source``), value ∈:
  - ``verified`` — a matching debit/paper-trail candidate was found (the deterministic candidate-search surfaced an
    own-account transfer of the same amount within the window, and the judge cited it). Strong.
  - ``intrinsic`` — sourced by NATURE: payroll / interest / dividend. Legitimately needs no matching debit. Strong.
  - ``self_asserted`` — the description claims an own-account/gift source but NO matching debit was found. A CLAIM, not
    proof. Weak.
  - ``none`` — no source found. Unsourced.
- **``has_identified_source`` stays yes|no|unknown** and is consistent with the strength (verified/intrinsic/self_asserted
  → ``yes``; none → ``no``; the unknown/failed paths → ``unknown`` with no strength tag).
- **Strength is DERIVED deterministically in the orchestrator, NOT taken from the AI's word.** A cited
  ``own_account_transfer`` candidate ⇒ ``verified`` (a real matched debit is authoritative regardless of how the model
  phrased it); an intrinsic-income category (payroll/interest/dividend) ⇒ ``intrinsic``; any other ``yes`` with no matched
  debit ⇒ ``self_asserted`` (conservative default — a claim can never be upgraded to verified without a paper trail).
  This is exactly the distinction a fraudster exploits, so it does not rest on the AI self-classifying.
- **The judge PROMPT is updated** so the AI's reasoning is honest: a description-only claim must be reported as ``yes``
  with ``source_index`` null AND the reasoning must state plainly that no matching debit was found — never described as if
  a debit had been matched. (The deterministic candidate-search is unchanged; it already finds the debits, which is what
  makes ``verified`` verifiable.)
- **AS-1 (LP-315) reads the strength.** A SOURCED deposit AT OR OVER the large-deposit threshold whose strength is
  ``self_asserted`` → ``needs_review`` (not a clean ``satisfied``), with a how_to_fix telling the processor to obtain the
  named source account's statement showing the withdrawal — the "show me the debit" discipline. ``verified`` / ``intrinsic``
  at any size, and ``self_asserted`` UNDER threshold, → ``satisfied`` (a small self-asserted transfer is not worth a manual
  chase, but the strength is still recorded for audit). ``source_strength`` is an optional refinement input, NOT gated, and
  is absent-tolerant (older snapshots fall back to the prior sourced→satisfied behavior).

**Consequences:** on LF-6T3N this flips the two brokerage deposits ($12k under threshold → satisfied but recorded
self_asserted; a $12k-style deposit AT/OVER threshold would now be ``needs_review``) while keeping the $20k VERIFIED
(matched debit) satisfied and payroll/interest INTRINSIC satisfied — "correct by design" (the paper trail), not "correct
by luck" (a believable label). Cross-refs: §3D (the armor — provenance + honest evidence), LP-314 (candidate-then-judge),
LP-315 (the gate/rule). **Follow-up (documented, out of scope here):** register ``txn.source_strength`` in the fact-tag
vocabulary source of truth (``docs/snapshot-fact-tags.xlsx`` → ``fact_tags.csv``); it is produced but not yet in the
vocabulary registry.

## ADR-256: Finding output — evaluation-outcome axis + subject_key + provenance + event log (LP-316)

- **Date:** 2026-07-14
- **Status:** Accepted

**Context:** LP-315 (+ LP-314a) produces in-memory ``RuleEvaluation`` results; they must become durable findings. The
LP-310 Area-4 recon found the persisted ``Finding`` model has ``open`` but no ``satisfied`` / ``couldnt_check`` /
``no_longer_applies`` as states, no ``subject_key`` column (only ``details`` JSON), no ``(loan_file, rule, subject)``
uniqueness, and no per-finding event log; and the current ``reconcile_findings`` mutates-in-place / soft-deletes. This
persists the results by EXTENDING that model, single-run — cross-run reconciliation is LP-322.

**Decision:**

- **A NEW evaluation-OUTCOME axis, orthogonal to the two existing enums.** ``EvaluationOutcome`` (``open`` / ``satisfied``
  / ``needs_review`` / ``couldnt_check`` / ``no_longer_applies``) records what the CHECK CONCLUDED — distinct from
  ``FindingStatus`` (severity red/yellow/green) and ``FindingResolutionStatus`` (the human resolution lifecycle). FIVE
  states, not the originally-planned four: LP-314a's ``needs_review`` (a self-asserted large transfer) is a real outcome.
  Verdicts map fired→open, satisfied→satisfied, needs_review→needs_review, couldnt_check→couldnt_check;
  ``not_applicable`` subjects are NOT persisted. A new nullable column (existing cross-source/document findings leave it
  null). **``couldnt_check`` now PERSISTS a record** — "we looked and could not check this, here is why" — where before
  it left none. Severity is a coarse triage color DERIVED from the outcome (open→red, needs_review/couldnt_check→yellow,
  satisfied→green); the outcome axis carries the precise signal.
- **``subject_key`` as a first-class column, keyed on the stable content_id.** Promoted from ``details.subject_key`` to a
  column; for a per-deposit rule it is the deposit's ``content_id`` (LP-312) — NOT re-extracted amount/date, which drift
  across runs (§3D: subject_key from stable tag values). A PARTIAL unique index ``(loan_file_id, rule_id, subject_key)
  WHERE deleted_at IS NULL AND subject_key IS NOT NULL`` makes a subject ONE live finding, while leaving soft-deleted
  rows and legacy null-subject_key findings out of the constraint. ``details.subject_key`` is still written so LP-93's
  ``finding_identity`` substrate keeps working.
- **Provenance inline (§3D Move 1).** ``load_bearing_tags`` (JSONB) persists each tag the verdict rested on — ``{tag_id,
  value, confidence, reasoning, source_facts}`` (``LoadBearingTag`` was extended with ``source_facts`` — the cited LP-312
  content_ids). A human reading the finding sees WHY (e.g. the sourcing tag's "no matching debit, description-only"
  reasoning), never a bare number. Refuses to persist a finding with empty reasoning. The evaluation metadata
  (verdict_confidence, threshold_used, priya_validated, gated_pending_signoff, how_to_fix, and LP-314a's source_strength)
  lands in ``details``; ``confidence`` = the verdict confidence. Origin is ``deterministic_rule`` (AS-1's rule is
  deterministic; its tags were ai/derived — recorded faithfully in the inline tags).
- **An append-only per-finding event log.** New ``finding_events`` table (insert-only, no soft-delete: ``event_type`` in
  created / outcome_changed / resolved / retired, ``from_outcome`` / ``to_outcome``, ``detail``, ``occurred_at``). It is
  the substrate for the four-tab lifecycle + retirement + immortality (§3D). SINGLE-RUN: only the ``created`` event (with
  the initial outcome) is emitted here.
- **Coexistence with the current reconcile.** LP-316 persists via a direct INSERT service
  (``persist_evaluation_findings``), reusing ``FindingOrigin`` and keeping ``details.subject_key`` so ``finding_identity``
  still works; the partial-unique index tolerates soft-delete. It does NOT touch ``reconcile_findings``.

**Consequences:** AS-1's verdicts are now durable, identity-stable, provenance-carrying findings — including the
previously-recordless ``couldnt_check`` and LP-314a's ``needs_review``. **Deferred to LP-322:** cross-run reconciliation
(carry-forward / retire → ``no_longer_applies`` / outcome-change), which will drive persistence through
``reconcile_findings`` using the outcome axis + ``subject_key`` + the event log (this ticket lays all three). Cross-refs:
§3D (finding states + provenance + subject_key), LP-310 Area 4, LP-312 (content_ids), LP-314a (source strength +
needs_review), LP-315 (the evaluation result). Migration mirrors the LP-74 add-column+CHECK+index pattern; ``str_enum`` is
VARCHAR+CHECK so no ``ALTER TYPE``.

## ADR-257: A two-level golden eval harness (tag + finding) with calibration — the GO/NO-GO instrument (LP-317)

**Status:** Accepted. **Context:** Stage 2 (LP-310…316) built the fact-tag pipeline — per-entity tags (LP-313),
cross-entity sourcing with strength (LP-314/314a), the thin AS-1 rule + fail-closed gate (LP-315), and persisted
findings with outcome states (LP-316). Before that pipeline can be trusted as a fraud check it needs a labeled,
automatically-scored instrument that proves it works in BOTH directions — fires when it should, stays quiet when it
should not — and that the tags underneath are calibrated, not confidently wrong.

**Decision.**
1. **Score at TWO levels — tag AND finding.** A rule that passes can MASK a systematically-wrong tag underneath it
   (a mis-classified `is_money_in`, a `verified` strength that never had a matched debit). Scoring findings alone
   would green-light a broken tag. So the harness scores each per-transaction tag (`is_money_in`,
   `apparent_category`, `has_identified_source`, `source_strength`) AND the per-subject AS-1 outcome, independently.
2. **Both directions, explicitly.** The real fraud file (LF-6T3N) is a NO-FALSE-FIRE fixture — it structurally
   cannot prove the fires-when-it-should direction (it has no unsourced large deposit). So the golden set adds
   MUST-FIRE cases (1 unsourced large; 5 the regression — a non-`credit` label still fires, so the old
   `direction=='credit'` bug cannot recur; 7 the intrinsic-not-a-loophole — the word "PAYROLL" without markers is
   not auto-satisfied), and the harness asserts coverage of both directions.
3. **The source-strength distinction (LP-314a) is a first-class case.** `verified` (a real matched debit, cited by
   content_id) vs `self_asserted` (a description-only claim, no debit) vs `intrinsic` (payroll) vs `none` — the
   fraud-relevant line between a proven paper trail and a borrower's claim — is scored directly (cases 2/3/9/10).
4. **Calibration measures abstention, doesn't assume it.** Per dimension: the UNKNOWN rate (over-abstention → the
   tag is useless) and ACCURACY-WHEN-CONCRETE (under-abstention/fabrication → a confident wrong answer, the
   dangerous direction for a fraud check). Flags are gated to the dimensions where `unknown` is a true abstention.
5. **Keyless by default, live optional.** The harness injects the LP-313/314 reasoner stub seam and REPLAYS each
   fixture's labeled AI judgment, so CI scoring is deterministic and needs no API key; everything downstream of the
   model (candidate search, strength derivation, gate, rule arithmetic) runs for real. A `--live` mode runs the real
   model for calibration and skips cleanly without a key. The real file (case 12) is a FROZEN tagged snapshot
   captured from one live post-LP-314a run — deterministic at test time, faithful to the real trace (0 fired).
6. **Evaluate, don't fix.** The harness never edits rule/tag logic to make a case pass; a mismatch is a REPORTED
   regression and a revealed bug is a separate fix ticket. This keeps the instrument honest.

**Consequences.** A single `uv run python -m app.scripts.run_eval` (keyless, CI) or `--live` (calibration) prints a
PASS/FAIL-per-case + both-directions-coverage + calibration report ending in GO / NO-GO. The frozen LF-6T3N fixture
is committed as the real-data regression guard, but REDUCED + PII-SCRUBBED: the raw snapshot is a whole loan file (W2s
with SSNs, licenses with DOB/address, etc.), and the AS-1 scorer reads only the transaction-bearing documents' tags +
the DTI income, so the fixture is stripped to exactly that — the real trace (amounts, dates, tag VALUES, income; verdict
counts byte-for-byte real) with every identity/free-text surface removed (a name/SSN/DOB token sweep returns zero). The
set is AS-1-only by design; scaling to other rules is a later wave. Cross-refs: §3D (tag-level eval + calibration + fail-closed states),
LP-313/314/314a (tags + strength), LP-315 (rule + gate), LP-316 (finding outcomes + provenance).

## ADR-258: Calculators as structured tags — from_tag lineage + fail-closed THROUGH the calc (LP-318)

**Status:** Accepted. **Context:** The snapshot's four calculators (DTI / LTV / MI / reserves) each emit a
`{value, breakdown[]}` where every breakdown line carries a `source` (stated/extracted/computed/manual/override)
but nothing tracing it to the fact-tag behind it, and no confidence. Worse, each calculator collapses a
non-derivable input to `0` (`effective = override ?? auto ?? 0`) — the "absent≠0" trap the fact-tag vocab
explicitly warns about — so a DTI missing a hazard binder emits a confident, too-low ratio a rule would trust.
LP-312 added a null `from_tag` on `CalcBreakdownLine` for exactly this ticket to populate.

**Decision.**
1. **Wrap at the service/snapshot layer, never the pure arithmetic.** `calculations_section.map_*` / `_line`
   populate `from_tag` and compute gating/confidence; the pure calculators are untouched (they remain the single
   source of truth for the math).
2. **`from_tag` = the canonical fact-tag id (a lineage LABEL).** The referenced tags (`housing.insurance_monthly`,
   `dti.qualifying_income_monthly`, `loan.amount`, `asset.usable_value`, …) are a defined vocabulary in
   `fact_tags.csv` but are NOT materialized in the snapshot's tags layer (only `txn.*` Stage-A/B tags are). So
   `from_tag` names WHICH tag produced a line, keyed by the line's stable `key`. A computed subtotal / a line with
   no fact-tag behind it → `"derived"` — NEVER a fabricated tag id.
3. **Fail-closed THROUGH the calc.** An input is UNKNOWN when `auto_amount is None and not overridden` (the
   calculator couldn't derive it and defaulted to 0; an override means a human vouched for it). Such a line
   surfaces `amount=None` (honest, not a fabricated 0). If a REQUIRED feeding tag is unknown OR absent, the calc is
   `gated`: its headline ratio is nulled and `gate_reason` names the tag (unknown vs absent — distinct reasons),
   so it emits a couldnt_check-equivalent marker, NOT a confident-but-wrong number. For DTI the required set is
   `{housing.insurance_monthly, housing.taxes_monthly}` (a missing binder/tax understates the payment); `hoa`/`mi`
   are legitimately 0 → not required. LTV/MI/reserves already return `None` when their core input is missing.
   The canonical case: LF-6T3N has no binder → the insurance line is unknown → the DTI gates → couldnt_check.
4. **A rule reading a gated calc → couldnt_check.** AS-1's income read returns None when the DTI is gated (none of
   a gated calc's numbers are trusted), so it degrades exactly as it gates on any other unknown load-bearing input.
5. **`confidence` = min of feeding tags' confidences, ignoring parsed/derived passthroughs (LP-315 convention).**
   The mechanism is built and unit-tested, but is DORMANT today (`None`): every current calc input is
   parsed/extracted/computed/derived (no AI-confidence tag feeds a calc). It activates when Hybrid tags
   (`income.qualifying_monthly`, `liab.dti_payment`) are materialized and wired.
6. **Defer max_loan + self_employed.** They are API-only (LP-310 Area 3) — NOT in the snapshot, no rule reads them
   from it — so tagging them now would be dead lineage. Only the 4 in-snapshot calcs are tagged.

**Consequences.** `CalculationEntry` gains `gated` / `gate_reason` / `confidence`; `SNAPSHOT_VERSION` 3→4 (the frozen
LF-6T3N eval fixture re-stamped; new optional fields default, so old blobs stay readable in shape). A file missing a
required housing input now yields a gated DTI (couldnt_check) instead of a confident too-low ratio — a deliberate,
honest behavior change (the DB-backed calculators test now asserts the gated path on the incomplete seed). Cross-refs:
§3D (calculators as structured tags), LP-310 Area 3, LP-312 (from_tag), LP-315 (the gate + confidence convention).

**KNOWN LIMITATION (deferred).** The gating is LIVE for the ABSENT-input case but works via the calc's own
`auto_amount is None` presence signal, NOT the tag layer: `from_tag` is a label only (no consumer reads it),
`calc_confidence` is always None (`_no_tag_confidence`), and the `housing.*` input tags are never materialized/consulted.
The gap: gating fires on ABSENT inputs but NOT on PRESENT-BUT-LOW-CONFIDENCE ones (a low-confidence extraction →
`auto_amount` non-None → no gate). Deferred because the absent case is the common one (and is covered), and tag-driven
gating before LP-317 calibrates those confidences risks over-gating. Revisit once the input tags are materialized +
calibrated. Full write-up: [`docs/tickets/LP-318.md`](docs/tickets/LP-318.md) "Known limitation" + [LP-321a](docs/tickets/LP-321a.md)
(the fixture that had masked this).

## ADR-259: AI-at-rule-time judgment rules — procedural armor, proven with OC-2 (LP-319)

**Status:** Accepted. **Context:** ~36 of the rule set are JUDGMENT rules — their verdict cannot reduce to a
deterministic query over structural-fact tags; the AI IS the evaluator (e.g. OC-2 "is the stated occupancy
plausible?"). These are the highest-stakes AND least-structurally-armored rules: there is no arithmetic to check the
AI against. Left naive they would auto-ship an AI opinion as a verdict.

**Decision — give the judgment rules PROCEDURAL armor, enforced in the evaluator (not the prompt).**
1. **Two tag ROLES, made real.** A `structural_fact` tag is produced once (Stage A/B), shared/cached, read by many
   rules. A `rule_judgment` tag (`tag_role=rule_judgment`) is produced at rule-time for ONE rule, IS that rule's
   verdict in tag shape, carries the AI's value + confidence + reasoning + the structural subjects it reasoned over
   (`source_facts`), and NEVER auto-ships. OC-2 produces `occupancy.reasonable` as a `rule_judgment` tag.
2. **Reason over TAGS, not raw docs.** The judgment context is assembled ONLY from the loan's structural-fact tags
   (`occupancy.stated`, `occupancy.consistent_with_signals`, address signals) — no document is read — so the
   judgment is grounded in the same clean facts everything else uses and is reviewable. This is the discipline that
   keeps a judgment rule from becoming an opaque "ask the LLM about the PDF" call.
3. **MANDATORY human ratification.** A judgment rule's verdict is ALWAYS ratification-pending: its only terminal
   verdicts are `needs_review` (a judgment was reached — a human must confirm) and `couldnt_check` (couldn't judge).
   It NEVER reaches a confident `satisfied`/`fired`, regardless of the AI's yes/no or its confidence. Represented by
   reusing LP-316's `needs_review` + a new `RuleEvaluation.ratification_pending` flag (deterministic rules leave it
   False). This is the core armor: for the least-checkable rules, a human is always in the loop.
4. **Confidence-gated + fail-closed on the inputs (LP-315).** The generic gate runs over the load-bearing structural
   tags BEFORE the AI is called — absent/unknown → `couldnt_check` (we don't ask the AI to judge over a hole), shaky
   → needs_review. The AI's own low confidence folds into the needs_review reasoning. AIClientError / truncation →
   the judgment tag is absent-with-reason + `couldnt_check`; a malformed / off-vocabulary response → `unknown` →
   needs_review — never a defaulted verdict.
5. **Provenance for the ratifier.** The result carries the structural-fact tags it reasoned over inline, so the human
   sees WHY the AI judged as it did.

**Consequences.** OC-2 is the reference implementation; the other ~36 judgment rules follow the same shape — assemble
tag context → gate → AI judge (the reused Stage-A/B clone: injected Reasoner seam, truncation guard, honest parse) →
ratification-pending verdict + a `rule_judgment` tag. Only the prompt and the tag set change per rule. The occupancy
structural-fact tags OC-2 reads (`occupancy.stated`, etc.) are produced by OC-1/ID-4 (out of scope here) and land
under a loan-level subject (`by_subject["loan"]`) — a documented convention this ticket introduces; keyless tests
inject them. Cross-refs: §3D (rule_judgment role + the judgment-rule armor), LP-313/314 (the AI-call clone), LP-315
(the gate + result), LP-316 (needs_review as the ratification-pending outcome).

## ADR-260: The observation channel + graduation log — safety for the unbounded real world (LP-320)

**Status:** Accepted. **Context:** The tag vocabulary is finite; the real world is not. The AI constantly meets
documents/facts the vocabulary does NOT enumerate — a gift letter, a divorce decree, a trust agreement, an unusual
credit. Two failure modes must both be avoided: (a) DROPPING the information (a silent false-green — the file looks
clean because the system had no slot for what it saw), and (b) letting the AI INVENT a formal tag / resolve a finding
off an un-governed judgment (extensibility becomes a false-green vector — an ungoverned AI opinion silently clears a
red flag).

**Decision.**
1. **A structured-but-schemaless Observation.** When the AI can't map to a known tag, it records an `Observation`
   (envelope: about, type [a free AI-chosen label], value [natural language], structured [schemaless JSONB],
   relates_to [finding/subject], confidence, reasoning, needs_tag, run_id) instead of inventing a tag or dropping the
   fact. File-owned, append-only.
2. **The INFORM-not-RESOLVE boundary, enforced STRUCTURALLY.** An observation may INFORM (surface to a human, feed
   graduation) but can NEVER drive an automated finding resolution — only governed tags + rules resolve findings.
   This is enforced by construction: observations live in their own table + service, and the rule engine never reads
   them, so an observation physically cannot flip a verdict (the rules read the snapshot tags, a different data path).
   This is the line that keeps extensibility from becoming a false-green vector.
3. **Fail-closed to human review.** An observation that `needs_tag` or `relates_to` a finding surfaces via a query
   (`pending_review_observations`) — the processor sees the structured context even though no formal tag/rule handles
   it yet. A novel/unclassified document ALWAYS yields at least one observation (a fallback flagged `needs_tag` even
   when the AI call fails) — never silently dropped (§7 discovery output).
4. **A PII-safe graduation log — the self-improving loop.** Each observation bumps a `GraduationCandidate` tally by a
   normalized signature (case/space-insensitive type). `top_graduation_candidates` ranks by frequency — production
   frequency IS the signal for what the vocabulary is missing most, i.e. which unknowns a human (with Priya) should
   formalize next into a tag+rule. The candidate row holds type + signature + count + timestamps ONLY — never raw
   values — so it is safe as a system-wide (cross-file/tenant) signal.

**Consequences.** The gift-letter trace works day one: a gift letter (not yet a formal tag) → an observation that
relates to the AS-1 finding and FAILS CLOSED to human review — it does NOT auto-resolve AS-1 (only a future governed
`gift.*` tag+rule would). The graduation log accumulates the recurring unknowns for formalization. Deferred: the human
formalization WORKFLOW (turning a candidate into a committed tag+rule — a governed UI task), and the concrete wiring
of the channel into a document classifier (no producer of document-level tags exists yet; the channel + AI step +
`observe_unmapped` seam ship here). Cross-refs: §3D (the unbounded real world), §7 (the discovery lane), LP-313/314
(tag production — the channel runs alongside it), LP-316 (findings — attach, never resolve).

## ADR-261: The verification orchestrator + partial-snapshot semantics (LP-321)

**Status:** Accepted. **Context:** All the Stage-2 pieces exist independently — raw snapshot (LP-312), Stage-A/B tag
production (LP-313/314), calculators-as-tags (LP-318), the fail-closed gate + rules (LP-315), judgment rules
(LP-319), finding persistence (LP-316). Something must ASSEMBLE them into one full run, in dependency order, that
degrades gracefully and caches. This is that assembly — it owns ORDER, DEGRADATION, and CACHING only; it re-implements
none of the pieces.

**Decision.**
1. **Dependency-ordered stage sequence.** `run_verification` runs: raw snapshot (calculators built inside it) →
   Stage A (per-entity atomic tags) → Stage B (cross-entity sourcing, consuming A's `is_money_in`) → rules (the
   fail-closed gate + AS-1 deterministic + OC-2 judgment) → findings (persisted with outcome/subject_key/provenance).
   It CALLS each existing entry point; the DAG is honored by A-before-B (B reads A's tags).
2. **Partial-snapshot semantics — the system-level fail-closed.** A stage/step failure NEVER fails the whole run:
   the tag producers already fail-close per call (a bad AI response → unknown-with-reason tags, not a crash), and the
   orchestrator adds a BACKSTOP (a wholesale stage exception is caught, the pre-stage snapshot kept, a degradation
   recorded). Rules whose load-bearing tags are now degraded → the LP-315 gate routes them to couldnt_check; rules
   that do NOT depend on the failed tags STILL RUN (the orchestrator lets every rule run and gate — it never skips a
   rule silently). The run ALWAYS completes with a coherent result set.
3. **Degradation visibility.** What degraded is RECORDED on the result (`VerificationRun.degradations`): absent-with-
   reason raw sections, unknown-with-reason production markers scanned from the tags, and any backstopped stage
   exception — visible, never a silent gap.
4. **Cache-by-content-fingerprint reuse.** Tag production is cached (LP-313/314) via a `TagCaches` bundle threaded
   across runs: a tag whose source raw facts are unchanged (by fingerprint) is REUSED, not re-produced. The snapshot
   is rebuilt each run (stateless); only changed inputs re-produce. The run records the model + vocab version for
   reproducibility, and the frozen snapshot is persisted (best-effort).
5. **Assemble, don't reimplement.** No new tag/rule/calculator/finding logic. Two slots are intentionally inert
   today: the CALCULATORS run inside `build_snapshot` (their inputs are stated financials, not Stage-A/B tags, so they
   need no separate post-tag step), and the CONTRADICTION AUDIT has no deterministic cross-checks wired yet (the gate
   takes a `contradiction` flag; the orchestrator passes False — the audit itself is a future ticket).

**Consequences.** One entry point runs a full verification and returns the snapshot + findings + degradations +
reproducibility metadata. It runs ONE verification — matching findings ACROSS runs (carry-forward / retire) is
LP-322; re-running into the SAME loan file collides on the finding uniqueness index by design (that is the signal
LP-322 reconciles). The occupancy structural tags OC-2 needs are not produced by any stage yet (OC-1/ID-4), so OC-2
couldnt_checks on a snapshot lacking them (honest fail-closed). Cross-refs: §3A (pipeline stages / run model), §3D
(partial-snapshot semantics + fail-closed), LP-312/313/314/315/316/318/319.

## ADR-262: The LF-6T3N regression fixture asserted a fiction — corrected to live DTI gating (LP-321a)

**Status:** Accepted. **Context:** A read-only investigation of LP-318's calculator gating found that the
orchestrator's `test_lf6t3n_full_run_zero_fired` was GREEN on behavior that does not match the live pipeline. The
frozen LF-6T3N fixture's `calc.dti` had `gated=False` with `breakdown=[]` — a byproduct of LP-317's PII reduction,
which rebuilt calculations as `CalculationsSection.present(dti=CalculationEntry(value={"gross_monthly_income": …},
breakdown=[]))`, dropping the breakdown so `gated` fell back to its `False` default. With no breakdown to gate on and
income present, AS-1 evaluated normally and the test asserted "0 fired." But LIVE on the real LF-6T3N file (no
insurance binder → `housing.insurance_monthly` unknown → `auto_amount` None → LP-318 gates the DTI), `calc.dti` is
`gated=True` / `back_end_dti=None`, and AS-1's `_qualifying_income` returns None on a gated DTI → AS-1 couldnt_checks.
The fixture and the live pipeline disagreed; a green test on a fiction is worse than no test — it hides a future break
of the live gating.

**Decision.** The LIVE gating is correct; the FIXTURE was wrong (not the reverse). Corrected:
1. **Fixture** — spliced the LIVE gated `calc.dti` into the frozen snapshot (`gated=True`, the real
   `gate_reason` naming the insurance input, `front/back_end_dti=None`, the housing breakdown present with the
   insurance line `amount=None`). PII-safe: the DTI line KEYS were genericized and the LABELS (which live-produce
   borrower + creditor names) were replaced with generic `from_tag`-derived labels; amounts-without-identity are the
   fixture's established posture (LP-317 kept amounts, stripped names), and the gating signal is presence/None, not a
   raw value. A name/creditor sweep on the fixture returns zero.
2. **Test** — renamed to `test_lf6t3n_dti_gated_forces_as1_couldnt_check` and rewritten to assert the LIVE outcome:
   the DTI is gated (`back_end_dti` None, reason names insurance, insurance line `amount=None`); AS-1 subjects are
   COULDNT_CHECK — explicitly NOT satisfied and NOT fired (the deposits are unevaluated-for-threshold, not cleared);
   and the Stage-A/B sourcing distinction (verified / self_asserted) is asserted separately (unaffected by the DTI
   gate).
3. **Guard** — the test now asserts `dti.gated is True` + `back_end_dti is None`, so a future PII-reduction that
   silently strips the DTI back to `gated=False` FAILS instead of passing on a fiction.

**Consequences.** The regression test now matches what the live orchestrated run produces on real LF-6T3N. The
eval-harness case 12 (which shares the fixture) still passes — it asserts `fired==0` (couldnt_check is fail-closed, not
fired) + the strength-tag counts (unaffected by the gate), both still true. NOT changed here: the live calculator/gating
logic (it is correct), and the separate Caveat-A gap the investigation noted (the calc's tag-confidence propagation is
inert — `confidence` always None, the `housing.*` tags are never consulted; `from_tag` is a label only) — documented,
deferred. Cross-refs: LP-317 (the PII stripping that introduced the fiction), LP-318 (the gating), LP-321 (the
orchestrator + its test), and the LP-318-gating investigation.

## ADR-263: Cross-run finding reconciliation + the immortal lifecycle (LP-322)

**Status:** Accepted. **Context:** LP-321's orchestrator runs ONE verification; re-running the same loan file
COLLIDED on the `(loan_file, rule, subject_key)` uniqueness index by design — that collision is the signal this
ticket reconciles. §8 (the five outcome states / four tabs) and §9 (identity, immortality, reconciliation) require a
finding to have a stable identity, to persist across runs keeping its history, and to NEVER leave the surface silently.

**Decision.**
1. **Identity = `(rule_id, subject_key)`, resting on STABLE content-ids (LP-312).** Verified: identical raw facts →
   identical content_id (a re-run matches); a changed amount → a different content_id (a changed deposit is a new
   subject). Reconciliation is only sound because subject_key is stable; a re-extracted-but-unchanged transaction
   reconciles to the same finding.
2. **`reconcile_evaluation_findings` matches this run against the prior run and applies five transitions.**
   CARRY-FORWARD (detected both runs → same finding id + history, state refreshed), MINT (new subject → new finding),
   RETIRE (a prior open finding not detected this run → `no_longer_applies`), RESOLVE (a carried-forward finding whose
   outcome goes open→satisfied because a sourcing tag flipped — the gift-letter loop), REVIVE (a retired finding whose
   subject reappears by exact subject_key → the same row, back on the surface). It replaces the single-run insert in
   the orchestrator, so a re-run no longer collides.
3. **RESOLVE ≠ RETIRE — different states, different events, not collapsed.** RESOLVE = the subject is still here and
   the rule now PASSES (`satisfied`, a `resolved` event citing the flipped tag). RETIRE = the SUBJECT left the file (or
   the rule no longer applies to it), `no_longer_applies`, a `retired` event with a reason. One is "it was addressed,"
   the other is "it's not there anymore."
4. **Immortality (§9): never a silent delete.** A no-longer-detected finding is RETIRED to `no_longer_applies`
   (visible, labeled, reason + run_id + timestamp), `deleted_at` stays NULL — it is NOT soft-deleted. A retired finding
   stays retired until an exact subject_key match REVIVES it (keeping the original identity). A human-resolved finding
   (`resolution_status != OPEN`) is RETAINED, not retired (Undo/audit depend on it). Retiring subject X never suppresses
   the rule firing on a new subject Y (different subject_key → its own finding).
5. **Append-only cross-run event log.** LP-316's `finding_events` records each transition — `carried_forward` /
   `outcome_changed` / `resolved` / `retired` / `revived` (two new event types added via a CHECK-widening migration),
   each carrying the run_id in `detail`; a resolve also cites the flipped sourcing tag. History is never rewritten.
6. **Tag-flip resolves; an observation only surfaces (the LP-320 boundary).** RESOLVE is driven by the sourcing tag
   flipping (`has_identified_source` no→yes → the rule returns satisfied). An observation (a gift letter, LP-320) only
   informs a human — reconcile never reads observations, so an observation alone can never flip a finding's state.

**Consequences.** Re-runs are idempotent-safe and cumulative: the surface reflects the current state while preserving
every finding's identity + history. The four-tab UI that DISPLAYS this lifecycle is deferred (frontend). The old LP-94
`reconcile_findings` (normalized-substance identity, soft-deletes) is the pre-fact-tag pipeline's and is untouched;
this is the subject_key-keyed, retire-not-delete reconcile for LP-316 fact-tag findings. Cross-refs: §8, §9,
LP-312 (content-ids), LP-316 (finding + event log), LP-320 (observation boundary), LP-321 (the orchestrator).

## ADR-264: Generalize the rule engine — rules become SPECS run by GENERIC evaluators (LP-324)

**Status:** Accepted. **Context:** LP-323-ID-A's gate found the wave BLOCKED: AS-1 and OC-2 were per-rule Python
modules dispatched by two hardcoded calls, and `RuleSpec`/`ReferenceValues` were AS-1-shaped (a `large_deposit_threshold`
field; a PROSE `subject_enumeration`) — a spec literally could not express another rule. This is the deferred LP-308
debt: authoring ~125 more rules on that base would fork `as1.py`/`oc2.py` across the family and kill the tag
architecture's scalability. **The safety property of this ticket is EQUIVALENCE:** AS-1 + OC-2 must produce identical
results after the refactor as before — same verdicts, confidences, gate routing, provenance, threshold_used — but
driven by their SPECS through generic evaluators.

**Decision.**
1. **A machine-readable spec schema.** `RuleSpec` gains an `evaluation` body — `deterministic` (calculative/structural)
   or `judgment` (judgmental), exactly one per the kind; `out_of_scope` carries neither. `subject_enumeration` becomes
   an EXECUTABLE key (`per_deposit`/`loan`) resolved by an enumerator registry. `reference_values` gains a
   generically-keyed `values` mapping (AS-1's 50% → `large_deposit_threshold_pct`) + a `guideline_text` authority slot;
   the old `large_deposit_threshold` prose is retained but now optional. The deterministic body declares
   `load_bearing_tags` + `gated_tags`, a tag `applicability`, `operands` (tag / reference / calc / product — AS-1's
   `threshold = multiplier × qualifying_income` as DATA, the calc operand honoring the LP-318 gated flag), and ordered
   `outcomes` (each a guard of tag predicates + an optional declared `Comparison` run through `satisfies`, first match
   wins). **No schema gap:** AS-1's LP-314a self_asserted→needs_review nudge — including its GE-vs-GT boundary — is
   just an outcome whose guard is `has_source==yes ∧ source_strength==self_asserted ∧ observed ≥ threshold`.
2. **Two generic evaluators, reusing what was already generic.** `evaluate_deterministic_rule(spec, snapshot)` and
   `evaluate_judgment_rule(spec, snapshot, reasoner)` run ANY rule from its spec — reusing `evaluate_gate`,
   `satisfies`/`Condition`/`Operator`, `RuleEvaluation`, and (generalized to `reason_rule_judgment`) the LP-313/314 AI
   clone + LP-319's ratification armor, unchanged.
3. **A rule registry + generic dispatch.** `ACTIVE_RULE_IDS` + `evaluate_rules` dispatch the rule set by KIND; the
   orchestrator's two hardcoded calls are replaced by that loop. Adding a rule is a SPEC (+ a registry line + its
   tags), never new evaluation Python. Out-of-scope → not_applicable (no evaluation).
4. **AS-1 + OC-2 re-expressed as DATA, with EQUIVALENCE the proof.** `AS-1.yaml`'s `deterministic` block and a new
   `OC-2.yaml` `judgment` block carry the logic; `as1.py`/`oc2.py` keep only spec-derived identifiers + thin
   `evaluate_as1_rule`/`evaluate_oc2` wrappers (same signatures, so the eval harness/orchestrator/tests are unchanged).
   The former decision-tree + flow code is deleted. The existing AS-1/OC-2 suites + the frozen LF-6T3N trace pass
   unchanged; a synthetic brand-new deterministic rule runs from a spec ONLY (no Python) — the proof the waves can
   proceed.

**Consequences.** The deferred LP-308 debt is paid; the ~130-rule waves are unblocked (a rule = a spec + its tags).
NOT changed: rule/tag/finding BEHAVIOR (equivalence), and gate.py / satisfies / RuleEvaluation / LP-316/317/319's armor
(reused). Deferred (separate tickets): the CROSS-SOURCE consistency primitive (ID-1/2/3/4/7 — the third rule shape) and
`id.*` tag materialization. Cross-refs: §3D, LP-303 (the AS-1 spec), LP-308 (never landed — now paid), LP-311 (rule
kinds/projection), LP-315 (gate), LP-319 (judgment armor), LP-323-ID-A §0.

## ADR-265: The cross-source consistency primitive — the third rule shape (LP-325)

**Status:** Accepted. **Context:** LP-324 gave the engine two rule shapes: AS-1 (per-transaction,
deterministic) and OC-2 (loan-level, judgment). But LP-323-ID-A found a THIRD shape the ID family is
dominated by and neither existing evaluator models: *"gather fact T for subject S across ALL sources,
compare them, judge agreement"* (ID-1 name, ID-2 SSN, ID-3 DOB, ID-4 address, ID-7 marital/title; and
later IN-1/IN-3 stated-vs-documented income, CR-1 app-vs-credit-report liabilities, PC-3/PR-7 property
address). Building it as a third hardcoded evaluator would refork the per-rule trajectory LP-324 just
paid off.

**Decision.**
1. **A DECLARED spec shape, not a third evaluator** (LP-324's model preserved). `RuleSpec` gains a
   `consistency` evaluation block (mutually exclusive with `deterministic`/`judgment`; a STRUCTURAL
   rule may now carry either a `deterministic` OR a `consistency` body). It DECLARES: the `subject`
   (the `per_borrower` enumerator this ticket adds), the `gather_tag`, the `source_scope` (a gather
   registry key), a `gather_filter` (a `TagCondition` on each source), the `compare_mode`
   (`exact`|`fuzzy`), the `normalization` chain (DATA — declared normalizer keys, not code-per-rule),
   the fuzzy `judge` (prompt + `value_domain` + declared `consistent_value`/`inconsistent_value`), and
   `on_agree`/`on_disagree`/`on_cannot_tell` outcomes.
2. **THE EXACT BOOKEND → AI-FUZZY RESIDUE design** (mirrors LP-314 candidate-then-judge — the cost +
   certainty property). One generic `evaluate_consistency_rule` does the mechanical part
   deterministically: gather across sources → exact-compare after normalization → **all equal → AGREE,
   NO AI CALL** (most files match exactly — cheap and certain). Only when values DIFFER, and only in
   `fuzzy` mode, does the AI judge — and it sees **ONLY the small differing set** (the values + their
   sources), never the file. `exact`-only rules (ID-2 SSN, ID-3 DOB) NEVER call AI: a difference IS a
   discrepancy.
3. **ABSENT ≠ DISAGREEING, and a single source is not agreement.** A source that simply LACKS the fact
   is EXCLUDED from the compare (not a mismatch). After filtering, **fewer than two instances →
   couldnt_check** (one source cannot "agree"). An `"unknown"` gathered value → couldnt_check (never a
   value that agrees/disagrees). The declared `gather_filter` is the **mailing-vs-residence trap** fix
   (ID-4): compare residence↔residence only, so a driver's-licence prior/mailing address is not a
   false discrepancy. Reuses `evaluate_gate` (unknown/below-floor over the gathered instances) +
   `reason_rule_judgment` + the LP-319 armor — no new AI layer.
4. **The fuzzy leg is ratification-pending; the exact bookend is not.** A `consistency` verdict the AI
   produced (benign variance → satisfied, or real discrepancy → fired) is `ratification_pending` —
   an AI made the call. The exact bookend's satisfied and exact-mode's fired are NOT pending (a
   deterministic decision). This REFINES LP-319's invariant from universal to per-path: OC-2's judgment
   path forces every verdict to needs_review, but a consistency rule's deterministic bookend legitimately
   lands `satisfied`/`fired` while its fuzzy residue is pending. `result.py`'s docstring is updated to
   record this; nothing reads the flag yet (a future ratification consumer will), so no behavior changed.
5. **Registry dispatch by evaluation BLOCK, not bare kind** (a structural rule may be deterministic OR
   consistency). ID-2 (exact) and ID-4 (fuzzy) are re-expressed AS DATA (`ID-2.yaml`/`ID-4.yaml`) with
   ZERO per-rule Python — the proof the shape generalizes. They stay OUT of `ACTIVE_RULE_IDS` (the live
   set) until the `id.*` producers materialize (LP-323-ID-A §0) — else every run would couldnt_check them.

**Consequences.** The third rule shape is unblocked for the ID wave and every cross-source family (income
stated-vs-documented, credit app-vs-report, property address) as SPECS. NOT changed: AS-1/OC-2 behavior
(dispatch is byte-identical), and `evaluate_gate`/`satisfies`/`RuleEvaluation`/the LP-313/314 AI machinery
(reused). **No schema gap found** — the gather filter, normalization, exact/fuzzy split, and outcomes are
all DATA. **Gather model (a note for the -B materialization ticket):** the gather tag and its filter tag
are read from the SAME source subject (each document that states an address carries both its
`id.address_normalized` and that address's `id.current_address_type`) — the coherent shape the `id.*`
producers must target. Deferred (separate tickets): the `id.*` tag producers; the -B wave authoring the
remaining ID rules on this primitive; the consistency-verdict-tag modeling question (LP-323-ID-A §2).
Cross-refs: §3D; ADR-264; LP-314 (candidate-then-judge), LP-315 (gate), LP-319 (judgment armor), LP-324
(rules as specs), LP-323-ID-A §0/§2/§4.

## ADR-266: Generic vocabulary-driven tag materialization — production is a declaration (LP-326)

**Status:** Accepted. **Context:** the fact-tag vocabulary defines ~140 tags across 10 entities, but
the pipeline materialized ONLY the 4 ``txn.*`` Stage-A tags (via a bespoke producer). This systemic
gap — vocabulary ≠ production — has now blocked three tickets (LP-318's inert calculator ``from_tag``,
LP-319's occupancy tags, LP-323-ID-A's ``id.*``) and would block EVERY wave: a rule can require a tag
the pipeline never produces, so it uniformly ``couldnt_check``. Ten bespoke per-family producers would
reintroduce exactly the per-family Python coupling LP-324 eliminated for rules.

**Decision.** Production becomes a PROPERTY OF THE TAG, declared in the vocabulary and resolved by
GENERIC producers — adding a family's tags is declarations, never new producer Python (mirroring
LP-324's rules-as-data).

1. **The declaration** (``tag_production.yaml``, a companion to the vocabulary — ``fact_tags.csv`` is
   GENERATED from the xlsx, so a hand-edited column there would be overwritten). Each materialized tag
   declares its MODE (``parsed`` / ``derived`` / ``ai``), the SUBJECT it is keyed under (``transaction``
   / ``document`` / ``loan`` — distinct from the logical ``entity``), and mode DATA (a field / a recipe
   key / an AI-group key). A tag with no entry is not-yet-materialized; a declared tag that cannot
   resolve to a real producer FAILS LOUD at projection time (``ProjectionError`` — no
   silently-unproducible tag).
2. **The SUBJECT is the LP-325 keying lever.** ``id.ssn_hash`` / ``id.address_normalized`` /
   ``id.current_address_type`` are logically borrower/doc facts but are declared under the DOCUMENT
   subject so a source's gather-tag and its filter-tag CO-LOCATE on the same subject — ID-4's residence
   filter works only because the ``id_address`` AI group emits both address + type on the same document.
3. **Three generic producers, registry-resolved, ZERO per-family branches.** ``parsed`` maps a declared
   extraction field (``produced_by=parsed``, ``confidence=None``, NEVER AI-re-typed — LP-313's
   discipline; an ABSENT field → an ABSENT tag, absent≠unknown≠empty; a non-matchable hash → absent so a
   gather excludes it). ``derived`` resolves a recipe key to a deterministic function (recipe registry).
   ``ai`` reuses the LP-313 machinery — bounded ≤15 batches, index-echo integrity, honest/fail-closed
   parse ("unknown" always legal & never coerced; off-vocabulary → unknown; failure/truncation/omission
   → unknown-with-reason), cache-by-content-fingerprint, the injected Reasoner stub — parameterized by an
   AI-group declaration + a per-subject-type context-builder. A new AI family on an existing subject type
   is a declaration only.
4. **Equivalence (risk-controlled).** The live ``txn.*`` Stage-A/B producers are UNTOUCHED, so the
   LP-313/314 suites + the frozen LF-6T3N trace pass unchanged (zero regression by construction). The
   ``txn.*`` tags carry declarations and a ROUND-TRIP test proves the generic AI producer reproduces the
   legacy Stage-A tags byte-for-byte (value/confidence/reasoning/provenance/stage). Migrating the live
   ``txn`` path onto the generic producer is a noted low-risk follow-on.
5. **Wiring + activation.** A new orchestrator stage (after Stage B) materializes the declared ``id.*``
   families (document / loan subjects); ``only_subjects`` / ``only_groups`` scope it. With their tags now
   materialized, **ID-2 and ID-4 join ``ACTIVE_RULE_IDS``** (LP-325 held them out pending producers) and
   evaluate end-to-end.

**Consequences.** Every wave's tags are unblocked as declarations. NOT changed: the ``txn.*`` live path
(equivalence), rule/gate/evaluator logic, the LP-313/314 AI machinery (reused). **Schema gaps found:**
none — mode + subject + mode-data express every id.* tag. **LP-318 Caveat A** (inert calculator
``from_tag`` / ``calc_confidence``) is now newly WIREABLE — a calculator's input facts can be declared +
materialized as tags the calculators consume — but that wiring is deferred (out of scope here).
Deferred: the calculator ``from_tag`` wiring; migrating live ``txn`` onto the generic producer; the -B
ID rules; other families' declarations (income/credit/property — their waves). Cross-refs: §3D; ADR-266;
LP-311 (projection), LP-312 (Tag + content_ids), LP-313/314 (Stage A/B machinery), LP-318 (Caveat A),
LP-319 (occupancy gap), LP-324 (rules-as-data), LP-325 (the gather contract), LP-323-ID-A §0/§2.

## ADR-267: Cross-source consistency verdicts are RULE OUTPUTS, not verdict tags (LP-323-ID-B, D2)

**Status:** Accepted. **Context:** LP-325's consistency primitive gathers a fact across sources and
produces the agree/disagree verdict. The vocabulary is inconsistent about how a cross-source
consistency check is represented: some rules would compare RAW tags (`id.name_normalized`, `id.dob`),
while a few tags bake the verdict IN (`id.title_vesting_consistent`, `property.address_normalized_match`).
Authoring the ID family forced a decision: does a consistency rule read raw tags and produce the
verdict itself, or does it read a pre-computed `id.name_consistent` / `id.address_consistent` verdict tag?

**Decision — RAW-COMPARE-IN-RULE (no verdict tags minted).** The consistency evaluator (LP-325) already
performs the comparison; a verdict tag would DUPLICATE that machinery in two places that can disagree,
and it makes the compare IMPLICIT (buried in a producer prompt) rather than DECLARED (the spec's
`compare_mode` + `normalization` + `gather_filter`). So ID-1 gathers raw `id.name_normalized` and ID-3
gathers raw `id.dob`; NO `id.name_consistent` / `id.address_consistent` tags are minted. This keeps the
comparison declarative and single-sourced, and avoids inflating the (generated) vocabulary.

**Consequences.**
- Every cross-source family (income stated-vs-documented, credit app-vs-report, property address)
  follows the same pattern: gather the RAW fact, declare the compare — no per-family verdict tag.
- `id.title_vesting_consistent` and `property.address_normalized_match` are the ODD ONES OUT — a verdict
  baked into an AI tag. They are NOT collapsed into each other (borrower identity/title vs subject-property
  address are different facts). A rule reading them is a thin structural check, not a consistency gather.
- ID-7 (marital/title) would read `id.title_vesting_consistent` as-is (option i) rather than re-express
  the marital-vs-vesting reconciliation as a consistency gather — but ID-7 is deferred as a generalization
  gap (per-document structural rule with document-type applicability; see LP-323-ID-B.md).

Cross-refs: §3D; ADR-265 (the consistency primitive); LP-324 (rules as data), LP-325, LP-326;
LP-323-ID-A §2 (the verdict-modeling question this resolves).

## ADR-268: Judgment generalized to declared subject enumeration — multi-subject (LP-327, GAP-B)

**Status:** Accepted. **Context:** LP-323-ID-B's GAP-B: `judgment.py` was STRICTLY single-subject (it
failed loud on ≠1 subject — the OC-2 loan shape it was built for), so most of the ~36 judgment rules —
per-borrower (citizenship eligibility) and per-document (POA acceptability, altered-document detection,
appraisal condition) — were blocked. `judgment.py` was the ODD ONE OUT: its siblings `deterministic.py`
(LP-324) and `consistency.py` (LP-325) already enumerate subjects from the spec's executable
`subject_enumeration` via the enumerators registry.

**Decision.** Make `judgment.py` use the mechanism its siblings already use — DECLARED subject
enumeration — rather than invent a new one.
1. **Multi-subject loop.** `evaluate_judgment_rule` returns `list[JudgmentEvaluation]` — one per
   enumerated subject. The per-subject armor (`_evaluate_one_subject`) is the former single-subject body
   verbatim: gate the subject's load-bearing tags (fail-closed, BEFORE any AI call — no AI/no tag on a
   gated subject) → reason over that subject's declared TAGS (never raw docs) → emit the `rule_judgment`
   tag KEYED TO THAT SUBJECT (`source_facts=(subject_id,)`) → ALWAYS ratification-pending (LP-319) →
   one RuleEvaluation. The ≠1 fail-loud is removed.
2. **Per-subject fail-closed** (LP-321's partial-snapshot discipline, at the rule level). Each subject
   is self-contained: one subject's gate/AI failure/truncation/malformed degrades ONLY that subject
   (couldnt_check / unknown-with-reason); the others still evaluate. Never a wholesale rule failure.
3. **One AI call PER subject** (cost, stated honestly). A judgment is a reasoned verdict per subject;
   batching N subjects into one call risks the position-degradation LP-313 guards against. So a
   per-document rule over N docs = N AI calls. (The `_required_ai_groups` gating already prevents
   running AI families no active rule reads.)
4. **Per-subject tag keying.** The registry returns `{subject_id: {tag_id: Tag}}` and the orchestrator
   merges each verdict tag under ITS subject — OC-2's `loan` subject lands under `LOAN_SUBJECT` exactly
   as before.
5. **OC-2 equivalence is the proof.** OC-2 declares `subject_enumeration: loan` → exactly one subject →
   identical verdict/confidence/gate routing/provenance/ratification-pending/tag keying. `evaluate_oc2`
   keeps its single-return signature (returns the one-element list's `[0]`). The OC-2 suite passes
   UNCHANGED.

**Consequences.** Per-document and per-deposit judgments are unblocked (a rule = a spec). Added the
`per_document` enumerator (returns each doc's populated tag map). NOT changed: deterministic/consistency/
gate/producers; the LP-313/314 AI machinery + LP-319 armor (reused). **Two follow-on gaps surfaced (NOT
patched):** (i) **per-BORROWER judgment** — the `per_borrower` enumerator returns EMPTY tag maps (LP-325
consistency gathers across docs; borrower facts key under document content_ids), so a per-borrower
judgment reads nothing → needs a borrower-tag-keyed enumerator + producer (blocks ID-8); (ii) ID-9's
per-document POA rule needs GAP-C (document-type applicability) to avoid couldnt_check-flooding non-POA
docs, plus a NEW vocabulary output tag (the vocabulary CSV is generated from the xlsx). So ID-8/ID-9 are
authored-in-principle but UNACTIVATED; the new shape is proven data-only via a synthetic per-document
judgment. Cross-refs: §3D; ADR-268; LP-319 (armor), LP-321 (partial-snapshot), LP-324/325 (the sibling
evaluators), LP-326 (SUBJECT keying), LP-323-ID-B GAP-B.

## ADR-269: Typed operands (GAP-A) + a hand-editable vocabulary (GAP-E) (LP-328)

**Status:** Accepted. **Context:** two gaps blocking the waves.
- **GAP-A** (LP-323-ID-B): `deterministic.py` coerced EVERY operand to `Decimal`, so a date inequality
  between two fact-tags was inexpressible — blocking ID-5 and every date rule (IN-2, PR-6, CL-1, CR-6,
  CR-13).
- **GAP-E** (LP-326/LP-327): the vocabulary (`fact_tags.csv`) is GENERATED from a binary xlsx, so a wave
  could not add a tag in a reviewed PR (the generator would overwrite a hand-added row). It blocked twice.

**Decision — GAP-A: TYPED operands via a declared type + a registry** (the pattern that held for
enumerators / normalizers / production modes — NOT a date special-case). An `Operand` declares a `type`
(default `decimal`, new `date`); a COERCER registry (`{decimal: coerce_decimal, date: coerce_date}`)
resolves it, and ONE type-agnostic comparator serves every type — `compare_values(op, left, right)` in
`schema.py` applies the operator, which is already generic (`<=`/`<`/`==` work for Decimal, date, str).
`satisfies` is now a thin Decimal wrapper over `compare_values` (not forked). Adding a type = one
registry entry + one key in `KNOWN_OPERAND_TYPES`.
- **`decimal` is the default → every existing spec is unchanged** (AS-1's operands declare no type; the
  comparison is byte-identical to the former `satisfies(...)`). Equivalence proven by the AS-1/ID-3/ID-6
  suites + the frozen LF-6T3N trace passing UNCHANGED.
- **Coercion failure / absent operand → couldnt_check, never a fabricated value.** An absent tag → None →
  couldnt_check with that reason (ID-5's non-expiring-state-ID edge: no expiration ≠ expired). An
  unparseable/ambiguous date → None → couldnt_check — never a silent epoch/0.
- **ONE shared date parser.** The `date` coercer REUSES `coerce_date` — the SAME parser the LP-323-ID-B
  consistency normalizer uses, so the two evaluators can never disagree, and neither guesses an ambiguous
  date. A load-time validator rejects a comparison whose two operands are different types.

**Decision — GAP-E: a hand-editable vocabulary overlay** (`vocabulary_extra.yaml`). `fact_tags.csv` stays
the xlsx-generated bulk vocabulary; a NEW tag is ADDED to the overlay — a version-controlled YAML,
reviewed in a PR, that the generator NEVER touches (so it cannot silently overwrite a hand-added tag).
The projection merges the overlay (a tag_id already in the vocabulary fails loud); the LP-326 allowed-values
lookup reads it too, so a new tag also MATERIALIZES. This is the "otherwise reconciled" approach — small,
additive, zero-risk to the xlsx pipeline — that unblocks the waves NOW (and ID-9's output tag). **The
fuller inversion** (make ALL of `fact_tags.csv` hand-editable + retire the xlsx as a generated view) is a
larger migration recommended as its own ticket; the overlay meets the requirement without it.

**Consequences.** Every date rule is unblocked as data (ID-5 authored; IN-2/PR-6/CL-1/CR-6/CR-13 follow),
and every wave can add a tag in a PR. NOT changed: consistency/judgment/gate logic, the producers (GAP-A
touched only `deterministic.py` + the shared `compare_values`; the date parser is shared, not forked).
**ID-5 authored but UNACTIVATED:** it needs both date tags under ONE subject, but LP-326 keys
`id.id_expiration` + `contract.closing_date` under DOCUMENT subjects (a deterministic loan rule reads one
subject's map). Co-locating them under the loan subject (with a single-ID caveat) is a materialization
follow-on. **PRIYA:** ID-5's `>=` vs `>` at closing (encoded default `>=` — an ID valid ON the closing date
is valid) + any grace period. **New gap surfaced (reported):** cross-subject operands (a per-document/
borrower rule reading a loan-level fact) — the reason ID-5 can't yet be a per-borrower rule. Cross-refs:
§3D; ADR-269; LP-311 (projection), LP-324 (Operand/Comparison), LP-325 (the normalizer registry + date
discipline), LP-326 (tag_production.yaml + the CSV-from-xlsx problem), LP-327, LP-323-ID-A §3/§4, -ID-B GAP-A.

## ADR-270: Document-type applicability — not_applicable ≠ couldnt_check (LP-329, GAP-C)

**Status:** Accepted. **Context:** LP-323-ID-B's GAP-C: a per-document rule had to enumerate EVERY
document, flooding ``couldnt_check`` across every non-matching one (ID-7's title rule on a paystub;
ID-9's POA rule on a W-2) — because a non-title/non-POA document has no title/POA tag, so the gate
couldnt_checked it. This blocked ID-7 and left ID-9 unactivated (LP-327).

**Decision — a DECLARED subject predicate resolved by shared machinery** (the sixth application of
declared-key-resolved-generically, after LP-324 enumerators, LP-325 normalizers + gather filter,
LP-326 production modes, LP-328 operand types). A spec declares an ``applicability: TagCondition`` — a
predicate over the subject's own tags (e.g. ``document.document_type == "power_of_attorney"``); the
deterministic evaluator already had it, and it is added to ``JudgmentEval``. A shared
``resolve_applicability`` (extracted from the deterministic evaluator — behaviour-identical, so AS-1
and every existing rule are unchanged) is called by BOTH evaluators. **No document types in any
evaluator** — the value is spec data. The document's intrinsic type (``DocumentEntry.document_type`` —
the classifier's known vocabulary) is injected by the ``per_document`` enumerator as a structural
subject tag ``document.document_type`` (like the content_id), so the predicate is a plain tag compare.

**THE §8 HONESTY CONTRACT — the heart.** ``not_applicable`` (scope-false) must NEVER absorb
``couldnt_check`` (data-missing). The resolution is filter-BEFORE-gate, per subject:
- out-of-scope (a paystub for the POA rule) → **not_applicable** (Tab 4) — NO gate, NO AI call, NO tag
  emitted; and ``rule_findings`` DROPS not_applicable (no finding). Out-of-scope costs nothing and the
  flood is gone (29 non-POA docs → 29 not_applicable → zero findings, not 29 couldnt_check yellows).
- in-scope but degraded (a title commitment PRESENT, its tag ``"unknown"``) → the gate →
  **couldnt_check** (Tab 1) — which PERSISTS as a yellow finding. It IS a gap and it blocks.
- the predicate tag itself ABSENT/``"unknown"`` → couldnt_check (cannot tell if it applies), never
  not_applicable. These must never collapse — a false "not applicable" would hide a real gap.

**THE ABSENT-DOCUMENT decision.** Non-matching subjects each emit a not_applicable RuleEvaluation
(VISIBLE in results, dropped only at persistence — never a silent vanish). A file with zero documents
of the type → the existing docs are all not_applicable; the rule genuinely doesn't apply. The distinct
"a REQUIRED document is missing → couldnt_check (Tab 1)" case (e.g. a title commitment expected on a
purchase) is DECLARED-per-rule (whether title is required is itself a Priya question); it is
RECOMMENDED as a future ``expected: true`` flag and DEFERRED here (ID-7/ID-9 are not always-required —
POA/title absence is genuinely not_applicable), so no rule silently vanishes today.

**Consequences.** ID-7 (deterministic per_document, scoped to ``title_commitment``) and ID-9 (judgment
per_document, scoped to ``power_of_attorney``) are ACTIVATED as data; ID-9's output tag
``id.poa_acceptable`` was added via LP-328's hand-editable vocabulary overlay (proving that fix). Every
document-scoped rule is unblocked (condo questionnaire, appraisal condition, title). NOT changed: the
gate / producers / consistency evaluator; the LP-319/327 judgment armor (every ID-9 verdict stays
ratification-pending). **PRIYA:** ID-7's community-property + married-after-commitment nuances; ID-9's
investor POA acceptability rules. **Recommendation (not a gap):** persist not_applicable as a visible
Tab-4 finding (today it is dropped at persistence) — a separate UI/findings concern. Cross-refs: §8;
ADR-270; LP-324/325 (the declared-filter pattern), LP-326, LP-327 (per_document + the armor), LP-328
(GAP-E overlay), LP-323-ID-A §1/§4, -ID-B GAP-C.

## ADR-271: Declared absent-document resolution — should this document EXIST for this file? (LP-330)

**Status:** Accepted. **Context:** LP-329 (ADR-270) resolved EVERY zero-in-scope per_document rule to
`not_applicable`, justified as "a rule whose scope matched nothing was never in scope for that file."
That reasoning is CIRCULAR: ID-7's scope is "title documents"; the FILE is a purchase; title documents
ARE in scope for a purchase — what matched nothing is the DATA, not the scope. Consequence: ID-7 is
LIVE, so a purchase with NO title commitment sat in Tab 4 (`not_applicable`, doesn't block) instead of
Tab 1 (`couldnt_check`, blocks) — a live FALSE-GREEN. §8 is explicit: a missing document that the rule
applies to is LOST VISIBILITY (Tab 1), not scope-false (Tab 4); "visible in Tab 4 with a reason" is the
exact false-green §8 warns against (Tab 4 is the doesn't-block tab).

**Decision.** The question is NOT "did the filter match anything" — it is **"SHOULD this document exist
for this file?"**. Only the rule knows, so it is DECLARED (the seventh application of
declared-key-resolved-generically, after LP-324/325/326/328/329): `applicability_expected: bool` on the
eval block (a sibling of LP-329's `applicability`). A shared `absent_document_couldnt_check` resolves it:
- `expected` AND the applicability-scoped document is CONFIDENTLY ABSENT (every enumerated subject is
  clearly out of scope — all `not_applicable`; none in scope, none ambiguous `couldnt_check`-from-unknown-
  type) → **couldnt_check** (Tab 1, BLOCKS), a reason NAMING the missing type, under a stable
  `missing:<type>` subject id (for cross-run reconciliation).
- default `false` / any subject in scope (the document EXISTS) / any unknown-type subject (cannot claim
  absence) → **not_applicable** (LP-329's behavior). Default `false` → EVERY existing spec is unchanged
  (equivalence).
The three §8 "not firing" cases stay DISTINCT: in-scope-but-degraded (title present, tag `"unknown"`) →
`couldnt_check` "present but unreadable"; confidently-absent-but-expected → `couldnt_check` "no
title_commitment in file"; not-expected-absent (ID-9 POA) → `not_applicable`. Same mechanism, opposite
answers for ID-7 vs ID-9 — the DECLARATION is the only difference, no rule-id branch.

**Consequences.** ID-7 declares `applicability_expected: true` → the live false-green is CLOSED (a
title-less file now blocks). ID-9 keeps the default → a POA-less file stays `not_applicable` (unchanged).
**Conditional-on-purchase is NOT supportable yet (reported, not invented):** the general form
(`expected when loan.purpose == purchase`) needs a loan-purpose TAG; none exists (only the `LoanFile`
DB field, not a snapshot tag). So ID-7 is encoded UNCONDITIONALLY expected — defensible (a lender needs
title insurance on a purchase AND a refinance; a rare title-less refinance → `couldnt_check` is safe, not
a false-green) — with the conditional a follow-on + a Priya question. **The cross-cutting invariant:**
`absent ≠ empty` has now needed explicit handling at the TAG (LP-326), OPERAND (LP-328), GATHER (LP-325),
and RULE (this) levels — it is a structural principle, not a one-off. Cross-refs: §8; ADR-270 (the
decision this corrects); LP-325/326/328/329.

## ADR-272: Borrower-keyed facts for per-borrower judgment — declared-keying assembly (LP-331, GAP-D)

**Status:** Accepted. **Context:** LP-327's GAP-D: the `per_borrower` enumerator returned EMPTY tag maps
(it exists for LP-325 CONSISTENCY, which uses it as a grouping key and gathers document-keyed facts
itself). A per-borrower JUDGMENT reads the subject's tag map → empty → always couldnt_check. This blocks
ID-8 and every per-borrower judgment (~a large slice of the ~36 judgment rules). The choice propagates,
so it was argued on code evidence.

**The evidence that decided it.** ID-8's inputs are NOT document-sourced: `id.citizenship` is
`borrower.citizenship` (`models/borrower.py`) → MISMO `borrower.N.citizenship` (`mismo_section.py`) — a
borrower-level 1003/MISMO fact keyed by borrower INDEX; `program.type` is loan-level and unmaterialized.
NO consistency rule gathers `id.citizenship` (its only consumer is ID-8). And `consistency.py` DISCARDS
the enumerated tag map (it gathers via its own doc index).

**The design argument.**
- **Option 2 (judgment declares a gather over the borrower's documents) — REJECTED for ID-8.** Its facts
  are not on documents; gathering `belongs_to` documents would find neither. This is exactly the "some
  borrower facts are genuinely borrower-level from the 1003/MISMO" case the gap-owner flagged — verified.
- **Option 1 (borrower-keyed facts) — ADOPTED, its stated AGAINST rebutted by evidence.** The divergence
  objection ("the same fact in two keyings that can disagree, resolving which IS a consistency rule
  hidden in the producer") does NOT apply here: `id.citizenship` has ONE source per borrower and NO
  document-keyed consumer — no duplicate keying to diverge. (LP-326's `parsed/document` declaration for
  `id.citizenship` was aspirational and wrong; it never materialized. It must be re-keyed to a borrower
  subject when the producer lands.)
- **Third option (make ID-8 a loan-level judgment) — rejected:** collapses per-borrower eligibility into
  one loan verdict, wrong for multi-borrower files.

**Decision — a DECLARED-keying assembly (the eighth application of declared-key-resolved-generically).**
The `per_borrower` enumerator now ASSEMBLES each borrower's subject map: the borrower's OWN facts
(`by_subject[borrower_id]`) + the LOAN-LEVEL shared facts (`by_subject["loan"]`) merged in (borrower-own
overrides), each fact from its ONE declared keying (LP-326 production subject) — no duplication, no
divergence. This reconciles `per_borrower`'s two meanings with ONE enumerator: still a grouping key for
CONSISTENCY (which discards the map → ID-1/2/3/4 and LP-326's document keying are UNTOUCHED, equivalence
free), now a populated subject map for JUDGMENT. Per-subject fail-closed (LP-327), gate-before-AI, and the
ratification armor (LP-319) apply per borrower; borrower isolation holds (each map has only that
borrower's own tags + shared loan tags). Multiple values (the same document-sourced fact from N docs) is
NOT ID-8's case (one MISMO value per borrower); a FUTURE per-borrower judgment over a document-sourced +
multi-valued fact (e.g. income used by both a consistency rule and a judgment) would add the LP-325 gather
LEG reasoning over the SET (disagreement visible to the AI — resolving it is a consistency rule's job),
NOT built now (YAGNI, reported).

**Consequences.** Per-borrower judgment is unblocked; ID-8 is authored + its mechanism proven (its output
tag `id.residency_eligible` added via the LP-328 hand-editable overlay). **ID-8 is NOT activated:** a
producer that materializes `id.citizenship` under `borrower_id` from MISMO needs a `borrower_id ↔
MISMO-index` resolution, and `program.type` is unmaterialized — a **new reported gap** (not patched). The
cross-cutting invariant `absent ≠ empty` has now needed explicit handling at the TAG (LP-326), OPERAND
(LP-328), GATHER (LP-325), RULE (LP-330), and SUBJECT (this) levels — a structural principle. **PRIYA
(fair-lending-sensitive):** ID-8's non-permanent-resident / DACA eligibility + investor overlays are
UNSURE; the prompt encodes a defensible default, `priya_validated: false`; the authoritative rules are in
LP-331's list. Cross-refs: §3D/§8; ADR-272; LP-319/325/326/327/328/329/330, LP-327's GAP-D.

## ADR-273: Income arithmetic is a DERIVED TAG (loan-level), not a calculator or a new operand (LP-323-IN-B)

**Context.** Wave 2 (Income) needs three arithmetic checks the operand algebra cannot express (it is
`tag | reference | calc | product` — multiply only, no subtract/divide/abs): IN-1 stated-vs-documented
variance `(stated − documented)/stated`, IN-3 YTD-annualized shortfall, IN-4 employment-gap days. LP-323-IN-A
predicted a "calculator-operand primitive" gap; the recon REFUTED it (the `calc` operand already
generalizes) and recommended DERIVED TAGS. This ADR records the mechanism, confirmed in implementation, as
the pattern for every future family's arithmetic.

**Decision — the computed figure is a DERIVED TAG (LP-326), produced by a loan-level recipe.** Each
arithmetic check becomes a `derived` tag whose recipe (a registry entry in `tag_materialization/derived.py`,
like `_app_required_fields_present`) reads the snapshot, does the arithmetic, and **abstains to `"unknown"`
with a reason** when a feeding tag is absent/unknown (never a fabricated number). A rule then reads the
derived tag as a plain `tag` operand vs a `reference` threshold — all existing mechanisms, **ZERO engine
Python** (the generic producer, evaluators, and gate are untouched; only recipe entries are added). Two
properties follow:

* **Caveat A (LP-318) stays deferred.** A derived tag's confidence/abstention flows through the ordinary
  tag GATE (absent/unknown → couldnt_check; below-floor → needs_review), which already handles
  present-but-low-confidence. A CALCULATOR would have revived Caveat A (`_calc_operand` reads
  `entry.value` and ignores `entry.confidence`), so the calculator path is deliberately NOT taken.
* **SIGNED semantics, not abs.** IN-1's tag is a SHORTFALL `(stated − documented)/stated`, not an abs
  variance — a raise (documented > stated) is a NEGATIVE shortfall and must never fire (the domain edge).

**Constraint — the derived producer is LOAN-ONLY today.** `produce_derived_tags` supports only
`subject == "loan"` (a snapshot → one value), and `validate_declarations` rejects a non-loan derived
declaration at load. So the income arithmetic tags are **loan-level aggregates** (a recipe sums the file's
documents, exactly as the DTI calculator aggregates income). This HOLDS the zero-engine-Python criterion
(loan-level recipes are registry entries; per-borrower would have forced an edit to the generic producer,
which was NOT done). It is a v1 with a KNOWN LIMITATION: per-borrower granularity (catching one borrower's
inflated income in a multi-borrower file) needs a **per-borrower derived producer** — the same
`borrower_id ↔ MISMO-index` / borrower-keyed materialization work ID-8 waits on (a shared follow-on, not a
per-wave cost).

**Consequences.** Income authoring was pure DATA + recipe entries — the first wave to hold the
zero-engine-Python criterion, validating the ~3-tickets/wave steady-state claim. The pattern generalizes:
any future family's arithmetic is a derived recipe, not a new operand or calculator. Deferred by this
decision (their own tickets): the per-borrower derived producer; IN-6's set-coverage shape (needs LP-331's
multi-value gather leg); IN-11's set-membership operand or judgment reframe; IN-12's self-employment
calculator wiring. Cross-refs: §3D/§8; LP-323-IN-A (the recon), LP-318 (Caveat A), LP-324 (operands),
LP-326 (derived recipes — the extension point), LP-331 (borrower-keyed facts).

## ADR-274: Borrower-keyed materialization + the borrower_id ↔ MISMO-index resolution (LP-332)

**Context.** Per-borrower rules (ID-8 citizenship, IN-1 income shortfall, ~9 income rules) were authored +
evaluated but could not ACTIVATE: LP-331 built the JUDGMENT consumer (`_per_borrower` reads
`by_subject[borrower_id]`) but nothing PRODUCED borrower-keyed tags, and `produce_derived_tags` was
loan-only. LP-323-IN-C pinned the #1 false-green this causes: IN-1's loan-level aggregate MASKS
per-borrower income fraud (a 2-borrower file where borrower A's income is inflated 40% nets to ~0 → IN-1
satisfied). The prerequisite is a resolution: **no code mapped a `belongs_to` UUID to a MISMO
`borrower.{n}` index** — MISMO's `n` is a re-derived sort position and the snapshot carried no link back.

**Decision — three parts, all DECLARED, no rule-id/family branch:**

1. **The resolution (a schema FIX, not a work-around).** `mismo_section.py` now emits
   `borrower.{n}.borrower_id` (`str(borrower.id)`) — a deterministic, snapshot-internal, PII-safe (a UUID,
   not identity data) link from the `belongs_to` UUID back to the MISMO group. This is the ONLY
   non-name-matching resolution: `BorrowerRef`'s docstring explicitly rejects cross-section name-matching
   as an anti-pattern, so name-matching was NOT an option. **THE FAILURE MODE is the heart of the
   decision:** a borrower group with no id link, or a DUPLICATE/blank id, is SKIPPED — its borrower-keyed
   tags stay absent → the rule **couldnt_checks**, NEVER a guessed attribution. Misattributing a fact to
   the wrong borrower would fabricate a discrepancy (or hide one) — strictly worse than not attributing it.

2. **The mechanism — generalize `produce_derived_tags` to the declared subject (REUSE, not a parallel
   mechanism).** Evidence: the parsed/AI producers ALREADY enumerate the subject registry
   (`producer.py`); only the derived producer was loan-special-cased. So the derived producer now
   enumerates the declared subject via the SAME registry (mirroring how LP-327 generalized judgment from
   single-subject to declared enumeration). A new `borrower` subject type (`subjects.py`) enumerates
   borrowers by the id link, reads `borrower.{n}.*`, and lets a borrower recipe gather that borrower's
   `belongs_to` documents. Option (b) — a bespoke gather-for-recipes — was REJECTED: it invents a second
   mechanism where generalizing the existing one suffices (the divergence risk LP-331 rejected).

3. **The recipe contract** changed `(snapshot) → (v, r)` to `(snapshot, subject_id, subject_raw) → (v,
   r)`. Loan recipes accept + ignore the two new args — logic identical (`_app_required_fields_present`
   is the regression canary, asserted unchanged). Loan- and borrower-level recipes coexist.

**How it reconciles with LP-326's SUBJECT ≠ entity keying (WITHOUT breaking the consistency gather).** The
document keying is UNTOUCHED: `id.address_normalized` + its filter, `income.employer_normalized` still key
under the DOCUMENT subject, so ID-4's residence filter and IN-5's employer gather work identically
(asserted — equivalence held, the LF-6T3N trace unchanged). The crossing (a per-borrower DERIVED tag reads
DOCUMENT-keyed facts and emits a BORROWER-keyed tag) lives entirely in the borrower recipe: it gathers the
borrower's `belongs_to` documents' `income.documented_monthly` and its own MISMO stated income, emitting
one borrower-keyed shortfall. The consistency gather never sees a borrower-keyed tag.

**PIN #1 FIXED.** `income.documented_income_shortfall_pct` is now per-borrower: borrower A's 40% shortfall
FIRES; borrower B's raise is satisfied — no masking. LP-323-IN-C's pinned test now asserts FIRING (the one
place a pinned known-wrong SHOULD change — its fix ticket landed). **IN-1 and IN-3 are now PER-BORROWER
checks, not file-level screens** (IN-3's per-borrower re-key is a small reported follow-on; IN-2/IN-4 stay
legitimately loan-level — recency/gap are file-level).

**Consequences.** ACTIVATED (added to `ACTIVE_RULE_IDS`, and `borrower` added to the orchestrator's
`_MATERIALIZED_SUBJECTS`): **ID-8** (Wave-1's outstanding debt — its `id.citizenship` now materializes
under `borrower_id` from MISMO, `program.type` from `loan.program`) and **IN-1** (per-borrower shortfall).
Every FUTURE family's per-borrower rules now activate for free — the lever LP-323-IN-C named. Per-subject
fail-closed (LP-327) holds: one borrower's missing data abstains only that borrower. **PRIYA (unchanged):**
ID-8's non-permanent-resident / DACA eligibility + overlays remain UNSURE (`priya_validated: false`, the
conservative default, the armor). **New gap reported (not patched):** a `belongs_to` borrower not present
in MISMO (or vice versa) is not evaluated for per-borrower income — a borrower-set reconciliation edge, a
small follow-on. Cross-refs: §3D/§8; LP-325/326 (keying), LP-327 (the generalization pattern + per-subject
fail-closed), LP-331 (GAP-D, the consumer), LP-323-IN-B/-IN-C (PIN #1), LP-323-ID-B (GAP-D).

## ADR-275: Derived tags materialize LAST (data-flow), and IN-1 is de-activated pending calibration (LP-333)

**Context.** LP-333's diagnosis of the inert Income rules found two things the code — not the ticket text
— revealed. (1) A DATA-FLOW gap: `materialize_tags` ran derived recipes (step 2) against the ORIGINAL,
pre-materialization snapshot, so a recipe that AGGREGATES other materialized tags (all four income
recipes sum a borrower's documented income across its documents) read an EMPTY tags layer → every income
derived tag abstained → the rule couldnt_checked LIVE. (2) IN-1 — which LP-332 added to `ACTIVE_RULE_IDS`
— therefore couldnt_checked on every real file, AND its feed (`income.documented_monthly`) is an
UNCALIBRATED AI structuring tag not even wired into the orchestrator's `_required_ai_groups`.

**Decision 1 — derived runs LAST, against the freshly-materialized snapshot.** `materialize_tags` now
orders parsed → ai → DERIVED, and passes the derived producer a snapshot carrying the parsed + AI tags
built this run. A recipe that reads only raw MISMO (`id.app_required_fields_present`) is unaffected
(identical output either order — the regression canary, asserted). No AI group reads a derived tag, so the
reorder introduces no cycle; equivalence holds (the full suite + LF-6T3N trace unchanged). This is the
generic fix that unblocks EVERY aggregate-derived tag, not a per-rule patch.

**Decision 2 — activate ONLY what genuinely materializes AND is trustworthy; de-activate IN-1.** The
discipline (LP-325/326/331): a rule that uniformly couldnt_checks fills Tab 1 with noise and trains
processors to ignore the tab where real blockers live. IN-1 did exactly that live. Even with the data-flow
fix, activating IN-1 would require wiring its uncalibrated AI feed into a deterministic FRAUD verdict —
the precise "ship an uncalibrated tag into a live verdict" risk the wave has flagged since LP-317
(calibration is keyless — no income AI tag has been scored against real content). So **IN-1 is REMOVED
from `ACTIVE_RULE_IDS`**: its PIN #1 mechanism (LP-332) is proven and unchanged; live activation is
DEFERRED until `income.documented_monthly` is calibrated and its recipe dependency is declared/wired.
Correcting LP-332's premature activation is the honest call — the code is the gate of record.

**What activated instead: IN-2** (pay-stub recency). Its chain is `income.pay_date` (PARSED, a
deterministic passthrough — no calibration risk) → the loan-level `income.days_since_most_recent_pay`
(derived). With the data-flow fix it produces REAL verdicts end-to-end with ZERO AI groups run (asserted:
fires for a stale stub, satisfied for a recent one, couldnt_check with no pay date). Loan-level recency is
correct (the file's most-recent stub — no per-borrower masking, unlike IN-1/IN-3).

**Consequences.** A newly-surfaced generalization gap (REPORTED, not patched): `_required_ai_groups`
traces a rule's DIRECT load-bearing tags, so a DERIVED load-bearing tag's feeding AI groups are never
required — an UNDECLARED recipe dependency. This blocks the live wiring of IN-1/IN-3/IN-5/IN-10 (their
derived/AI feeds), and its fix is a declared `depends_on` on derived tags (a follow-on). Two spec data
fixes landed (bucket A): IN-8's applicability `verification_of_employment` → `voe` and IN-9's
`offer_letter` → `employment_offer_letter` (the classifier's `DOCUMENT_TYPE_INDICATORS` emits `voe` /
`employment_offer_letter`; the specs referenced types the classifier never produces, so the rules were
silently `not_applicable` on every file). The remaining Income rules stay INERT with precise causes (the
LP-333 bucket table): missing extraction fields (IN-4/7), uncalibrated AI feeds (IN-5/10), the
undeclared-recipe-dependency + calibration (IN-1/3), per-borrower-with-document-context AI (IN-7/13/14),
and PIN #2/#3 (IN-11/12). Cross-refs: LP-317 (calibration is keyless), LP-326 (the producers), LP-331/332
(borrower keying), LP-323-IN-B/-C (the rules + the PINs).

## ADR-276: Live calibration — the content source is a swappable seam; the activation bar is risk-weighted (LP-334)

**Context.** The architecture's thesis (§3D) is that AI structures messy reality into honest fact-tags and
deterministic code queries them. Every gate/floor assumes the structuring is good enough and honestly
abstaining — an assumption NEVER tested: calibration was keyless (labels replayed, trivially perfect). Five
Income rules are gated on this (LP-333), and ID-1/4/7/8/9 are LIVE producing verdicts on unmeasured tags.
LP-334 takes the first real measurement. Two decisions were forced but are NOT Claude Code's to settle.

**Decision 1 (recorded as a decision-to-be-made — awaits Geet's privacy call). The content source is a
SWAPPABLE SEAM.** A code finding reframes the privacy trade-off: the tag reasoners consume EXTRACTED
FIELDS, not raw scans (`_doc_context` sends `document.fields`), so "messy real scans" is an EXTRACTION-stage
risk, upstream of the tag reasoner. The harness (`live_calibration.calibrate(docs, reasoner=...)`) takes any
iterable of `LabeledDoc`; the in-repo `LABELED_DOCS` is clean-field content that measures the fields→tags
reasoning faithfully. Options for the truth set: (a) synthetic/labeled fields (safe, runnable now — this
ticket); (b) local Qwen over real files (measures Qwen, not production); (c) de-identified real → Anthropic
(real + production model, but LF-6T3N is a *tagged* snapshot with NO golden labels and rests on
de-identification trust). **Recommendation: a hybrid** — synthetic now for breadth/regression + a small
hand-labeled de-identified real set for truth, **pending Geet's privacy approval** (privacy-first: local
models for real PII, cloud for non-PII). The seam makes the source swappable without touching the harness.

**Decision 2 (recorded as a decision-to-be-made — a PRIYA question). The activation bar is RISK-WEIGHTED,
not one number.** Risk differs by what the tag FEEDS: `id.title_vesting_consistent` → ID-7's DETERMINISTIC
auto-shipping verdict (a wrong tag → a wrong confident finding) and `income.documented_monthly` → IN-1's
deterministic FRAUD verdict need a HIGH bar (proposal: ≥95% concrete-accuracy, ≤15% unknown-rate);
`id.name_normalized` → ID-1's fuzzy leg is RATIFICATION-PENDING (a human sees every verdict) → a lower bar.
The proposal is encoded in the doc and marked UNCONFIRMED: *"how often can this be wrong before you'd stop
trusting it?"* is a domain judgment, Priya's, not engineering's. This ticket MEASURES; activation decisions
follow separately with the numbers + Priya's bar in hand — no rule was activated/de-activated here.

**Consequences (the first real numbers, on clean synthetic fields — plumbing + obvious biases, NOT
real-scan messiness or true fuzzy-tag accuracy).** Enum tags scored well (title/poa/income.type 100%). Two
findings, REPORTED not fixed (evaluate-don't-fix — tuning a prompt to the eval destroys the measurement):
(1) `id.current_address_type` defaults a driver's-license address to `prior` ("DLs are often not current")
→ under-includes DL residences in ID-4's residence filter → couldnt_check — a live-rule bias, its own fix
ticket; (2) fuzzy free-text tags (`id.name_normalized` / `id.address_normalized`) CANNOT be scored by
string comparison (valid renderings differ: hyphen vs space, suffix retention) — the raw % under-measures
them; they need human review of the harness's failing-case DETAIL (which it records) or an AI-judge
comparison. The harness records predicted/golden/confidence/reasoning per case so a wrong tag is
inspectable. Cost: ~4s + ~270 tokens per call (claude-sonnet-4-5); keyless CI unchanged (live is gated on
an explicit `LP334_LIVE=1` flag, never the mere presence of a key). No rule/tag/engine/spec logic changed.
Cross-refs: LP-317 (DimensionCalibration + the live seam), LP-333 (calibration as the activation blocker),
LP-313/326 (the Reasoner seam + AI producers), LP-323-ID-C/-IN-C (the keyless family suites, unchanged).

## ADR-277: per_account is an ENUMERATION concern (not a keying one), with a fail-closed identity (LP-336)

**Context.** LP-323-AS-A found AS-6/AS-8/AS-10 group a borrower's bank-statement documents by ACCOUNT, but
no `per_account` enumerator exists. The account identity available today — `stmt.account_masked` — is
`fact_tags.csv`-flagged *"display only, non-matchable"*: `****1234` at Chase and `****1234` at Wells Fargo
look IDENTICAL. A guessed grouping is dangerous: MIS-GROUPING two accounts FABRICATES a statement-chaining
break (a false positive on fraud), and OVER-SPLITTING one HIDES a real break (a false-green) — PIN #1's
cousin at the account level, the same danger LP-332's `borrower_id ↔ MISMO-index` resolution guarded.

**Decision 1 — `per_account` is an ENUMERATOR, NOT a SubjectType.** LP-323-AS-A refuted the SubjectType
option with evidence: a bank statement IS a `document`, so `stmt.*` facts key under the existing DOCUMENT
subject; grouping by account is an ENUMERATION concern, not a second keying. **No fact keys under both
document and account** (the divergence risk LP-331/332 repeatedly rejected). So `per_account` is one
registry entry in `enumerators.py` (`subjects.py` is UNTOUCHED — no `account` SubjectType).

**Decision 2 — the identity is `(institution, masked-number)`, both DETERMINISTIC, and the resolution is
FAIL-CLOSED.** The masked number alone collides across institutions, so the institution is required. Both
are parsed extraction fields — `bank_name` (a `Field`) + `account_number_masked` (a `PiiField`, masked
last-4) — already landing in `DocumentEntry.fields` (`documents_section.py`). So **`stmt.institution` did
NOT need to be added** (no new tag, no declaration, no uncalibrated AI): the enumerator reads `bank_name`
directly, the same way `_per_borrower` reads `belongs_to`. **THE INVARIANT (mirroring LP-332):** a
statement missing EITHER identifier is UNRESOLVABLE — SURFACED as its own subject with an
`account.unresolved` marker (a non-vocabulary structural tag, the `DOC_TYPE_TAG` precedent), never grouped,
never dropped — so a per_account rule couldnt_checks it WITH A REASON. A guessed grouping is worse than
abstaining: abstaining says "I can't tell"; a guess makes a confident, wrong claim. The `account_key`
(`account:{institution.casefold()}:{masked-last4}`) is stable across runs (LP-312 spirit → LP-322
reconciliation) and carries only display-safe values (bank name + masked last-4, the AS-1 subject-key
precedent — no raw PII).

**Consequences.** Unblocks AS-6 (ownership), AS-8 (chaining — its enumerator; its pairwise-sequential
EVALUATOR is a DEFERRED shape, the IN-6 precedent, NOT built here), AS-10 (recency), and every future
per-account rule — from a spec's `subject_enumeration: per_account`, no new Python. `resolve_accounts` is
exported so AS-8's future evaluator gets the grouping (and the ordered statements it needs). `per_account`
was added to `_DOCUMENT_DERIVED_ENUMERATIONS` (zero accounts = no statements resolved, a degraded reason →
not retire-eligible). **NEW residual limitation REPORTED (not patched):** the identity is the MASKED
last-4, so two DISTINCT accounts at the SAME institution with the SAME last-4 mask identically → they would
mis-group, and this is UNDETECTABLE from the masked display (raw account numbers are never stored,
ADR-149). Rare, but real — a follow-on could add a fuller (still-masked) discriminator if extraction
surfaces one. Equivalence held (every live rule identical; the LF-6T3N trace unchanged; per_account is
additive). Cross-refs: LP-332 (the mirrored borrower_id resolution + its fail-closed failure mode),
LP-323-AS-A (the recon + the SubjectType refutation), LP-325/326 (keying + gather), LP-312 (stable
content-ids), ADR-149 (masked account numbers, never raw).

## ADR-278: A conditional (matrix) threshold is a DERIVED TAG, not a structured reference (LP-323-AS-B)

**Context.** AS-4 (reserves adequacy) compares reserve months available to a REQUIRED number that is a
MATRIX — occupancy × property-type × units × program (Fannie B3-4.1-01). `reference_values.values` is a
flat `dict[str, str]` and an operand reads ONE `reference` key, so it cannot do the CONDITIONAL lookup
(pick the cell). This recurs wherever agency requirements are a matrix (LTV tiers, MI factors, DTI limits).

**Decision — the conditional threshold is a DERIVED TAG whose recipe selects the cell from the loan's
attributes (the ADR-273 pattern extended).** `reserves.required_months` is a `derived` loan tag; its recipe
reads `property.occupancy` (MISMO) and returns the months for that cell. AS-4 then reads it as an ordinary
`tag` operand — no engine change, no schema addition. **Two properties, both critical:**
- **Un-encoded cells ABSTAIN, never guess.** The recipe encodes ONLY the agency-standard occupancy cells
  (investment 6 / second-home 2 / 1-unit primary 0, cited); any other cell (2-4 units, LTV tiers, multiple
  financed properties, FHA/VA overlays) returns `"unknown"` → the tag gate → AS-4 couldnt_checks. A wrong
  reserve requirement is a silent, permanent error; the full matrix is Priya's.
- **The recipe's confidence/abstention flows through the ordinary tag gate** (ADR-273) — a matrix in
  `reference_values` (the alternative, a schema addition) would need a new operand type AND would not
  degrade to couldnt_check on an un-encoded cell. The derived-tag route reuses everything.

**Consequences.** Any future matrix threshold is a derived recipe reading the conditioning facts +
abstaining on un-encoded cells — the pattern is set. **The Assets wave held the zero-engine-Python
criterion** (like Income): all 10 rules (AS-2..AS-12 minus the deferred AS-8) are DATA + declarations +
recipe registry entries; no evaluator/gate/producer-core changed. **NO Assets threshold is Priya-validated**
(AS-1's 50% is `priya_validated:false` — no validated precedent row exists, AS-A's correction confirmed);
everything is authored `priya_validated:false`. Cross-refs: ADR-273 (arithmetic as derived tags), LP-323-AS-A
(the recon + the matrix-shape question), LP-318/324 (the calc operand + its gate — AS-4's case-12 path),
LP-336 (per_account + resolve_accounts, used inside the AS-10 recency recipe).

## ADR-279: Calibrate the shipped path against de-identified real content via the Anthropic API — a bias hunt, not validation (LP-337)

**Context.** Calibration was keyless (labels replayed, trivially perfect — a plumbing check). LP-334 added a
LIVE seam and, at n=2, found a real systematic bias (`id.current_address_type` presumed a driver's-licence
address `prior` — *because our own prompt exemplar taught it*; LP-335 fixed it). Keyless calibration
STRUCTURALLY cannot catch that class (replayed labels agree with the prompt that produced them). LP-334's D1
left the content source open (option 1 synthetic-equivalent / option 2 hand-built real-shaped / **option 3
de-identified real content → the real API**). The AI tags feed LIVE AS-1 (whose accuracy had never been
checked) and gate the inert Assets rules; the `txn_stage_a` / sourcing / income / asset prompts are all
UNAUDITED — exactly the kind that taught the FINDING-1 bias.

**Decision — DECIDED by Geet: execute option 3. Calibrate against LF-6T3N (real, de-identified) through the
Anthropic production model**, because it measures the path actually shipped (real messiness + the real
model), not a proxy. **Privacy posture, recorded as a deliberate decision (not a drift):** LF-6T3N is
de-identified, and the SAME API already processes real files in production; the calibration adds no new data
exposure. Because LF-6T3N has NO ground-truth labels, the first deliverable is the INSTRUMENT — a labeling
worksheet a human fills in — generated deterministically from the snapshot (keyless), split MECHANICAL
(factual reads — Geet) vs JUDGMENT (domain calls — Priya), carrying document context and EXCLUDING the AI's
prediction (so a labeler cannot anchor). The scoring run reuses LP-317's `DimensionCalibration` and LP-334's
`ScoredTag`/`summarize` UNCHANGED; it is opt-in (`LP334_LIVE=1`), never key-presence gated.

**What this measurement CAN and CANNOT establish.** It finds **BIASES, not RATES** — one conventional
purchase file gives most tags n≤6. **The one exception is `txn.*`:** LF-6T3N's 5 statements carry 50
transactions, so `txn.is_money_in` / `txn.apparent_category` reach **n=50** — the system's first candidate
for a real rate measurement (scoped: on ONE conventional purchase). ~~Everything else (`id.*`, `income.*`,
`asset.*`) is n=0 UNMEASURABLE on this file~~ **[CORRECTED BY LP-338 / ADR-280: that was a bug + a stripped
fixture — the real LF-6T3N supports `id.*` n=2, `income.*` n=8, `asset.*` n=3, a bias hunt at n=2-8; only
`txn.*` reaches a rate at n=50].** **A clean result does NOT unblock the ~15 inert rules** — activation still requires n≥20 across VARIED files (FHA /
refi / condo / self-employed) + Priya's D2 bars. Free-text tags (`txn.counterparty` / `source_reference`)
are NOT string-scored (FINDING-2) — captured for human review, deferred to the fuzzy-scoring method.

**Consequences.** EVALUATE, DON'T FIX: a bad number is a reported finding + its own fix ticket — no prompt is
tuned in the measuring pass (LP-335's discipline: one principled change, measure once, never iterate against
the numbers). The worksheet generator + scoring live in the eval harness only; no rule/tag/engine/spec
behavior changed. Cross-refs: LP-334 (the harness + D1/D2 + FINDING-2), LP-335 (FINDING-1's fix + the
anti-fit-to-eval discipline), LP-317 (`DimensionCalibration`), LP-313/314 (the txn Stage-A + sourcing
producers being audited).

## ADR-280: The LF-6T3N eval fixture was a stripped subset; replace it + separate file-capacity from pipeline-yield in coverage (LP-338)

**Context.** LP-337 measured calibration coverage on `lf6t3n_tagged_snapshot.json` and concluded the
project's calibration ceiling on existing files was `txn.*`, and that an n≥20 rate for other families
"needs varied real files that don't exist in the repo yet." That conclusion was WRONG on two counts, and it
had begun to propagate (the plan briefly treated acquiring synthetic files as the blocker to ~15 rules):

1. **The fixture is a STRIPPED SUBSET.** `lf6t3n_tagged_snapshot.json` is 5 bank statements with empty
   `fields` — not the real ~30-document LF-6T3N (2 driver's licences, 4 pay-stubs, 4 W-2s, 3 investment
   accounts, a brokerage statement, mortgage statements, a purchase agreement, …). This is the LP-321a
   problem one layer up: the central eval fixture under-represented the real file, so a conclusion drawn
   from it was a fiction.
2. **The coverage function CONFLATED two numbers.** It statically hardcoded the `txn.*` family and declared
   `id.*` / `income.*` / `asset.*` "UNMEASURABLE" — reporting *what the wired pipeline + that fixture
   happened to yield* while LABELLING it the file's inherent *capacity*.

**Decision.**
- **Replace the fixture** with a representative, de-identified 30-document synthetic snapshot with POPULATED
  fields — built IN CODE by `build_lf6t3n_snapshot()` (`app/verification/eval/lf6t3n_fixture.py`), NOT a
  committed snapshot JSON (a deliberate constraint: no snapshot JSONs enter the repo). It reads the
  already-committed `lf6t3n_tagged_snapshot.json` for the 5 bank statements + 50 transactions verbatim (so
  `txn.*` labels/subject-ids are stable) and appends the other 25 documents in code. The OLD fixture stays
  for the frozen golden-eval trace (unchanged — the equivalence property).
- **Coverage reports THREE separate facts** per AI tag, never conflated (the *absent ≠ empty ≠ unwired*
  invariant this project already handles at the tag / operand / gather / rule / subject levels, now at the
  COVERAGE level): **file_capacity** (subjects + content the snapshot supports for the tag's declared
  subject — the labeling ceiling, independent of wiring) · **pipeline_yield** (what the wired pipeline
  produces today — a declared AI tag runs; a vocabulary tag with no declaration does not) · **content_empty**
  (a subject that exists but is field-empty — a brokerage_statement with `fields={}`). Status: `labelable` /
  `wiring_gap` (capacity>0, yield=0 — LP-333 bucket B, surfaced not hidden) / `content_empty` / `no_subject`.

**Consequences.** The honest calibration position: **LF-6T3N supports a BIAS HUNT across `id.*` (n=2) /
`income.*` (n=8) / `asset.*` (n=3) TODAY**, and a real RATE only for `txn.*` (n=50). Varied files (FHA /
refi / condo / self-employed) are still needed for RATES on the other families — that part of LP-337 stands;
the "n=0 / files don't exist" framing does not. LP-335's `id.current_address_type` fix can now be checked
against a REAL driver's licence (n=2) rather than the synthetic n=2 it was measured on. The corrected report
also surfaces the Stage-B sourcing tags as WIRING GAPS (capacity>0, yield=0) — reported, not fixed (their
own follow-in). EVALUATE, DON'T FIX held: no rule/tag/engine/spec behavior changed, `ACTIVE_RULE_IDS`
unchanged, the frozen trace unchanged. Corrects ADR-279 (which repeated the n=0 claim). Cross-refs: LP-337
(the bug's origin), LP-321a (the stripped-fixture-fiction precedent), LP-333 (bucket B wiring gaps), LP-334
(the harness + FINDING-2), LP-335 (FINDING-1).

## ADR-281: The `*_normalized` tag convention — normalize FORMAT not CONTENT; strip entity suffixes in the RULE (LP-340)

**Context.** LP-337's first real live calibration measured `income.employer_normalized` at 25% (6/8) and
`id.name_normalized` at 50% — but the model was NOT wrong. It stripped the entity suffix (`Acme Logistics`
vs the golden `Acme Logistics Inc`) and chose the fuller `asserted_name` over `full_name`, both consistent,
reasoned behaviours against a tag the vocabulary never defined. **The silence was the bug:** "normalized"
had no stated meaning, so the model chose one convention and the human labeler another. The `income_employer`
prompt even hedged — *"drop 'Inc'/'LLC' noise where it aids matching"* — smuggling a downstream MATCHING
concern into a tag exemplar (FINDING-1's exact class, LP-335).

**Decision.** Define the `*_normalized` convention once, for every such tag present and future:
- **General rule (D3): normalize FORMAT, not CONTENT.** A `*_normalized` tag reports the value the document
  STATES, canonicalized for format only (casing, whitespace, punctuation, abbreviation expansion). Content
  differences are the SIGNAL the consistency rules exist to catch — a tag must never erase them. The TAG
  reports; the RULE decides how to compare (LP-335's principle).
- **Recorded exception (D1, Geet's decision): strip the corporate ENTITY SUFFIX** (Inc/LLC/Corp/Co/Ltd) —
  declared to be FORMAT, not content, for employer matching (a suffix change is a restructuring, not an
  employer change). **Implemented in the RULE, not the tag:** a new declared normalizer `drop_entity_suffix`
  on IN-5's `normalization` chain (the LP-325 registry's sanctioned extension — a registry entry, like the
  LP-328 date coercer, not evaluator logic). The tag keeps reporting `Acme Logistics Inc` in full; IN-5
  strips at the exact bookend. **Scoped to IN-5 (INERT) only — ID-1 and ID-4 (LIVE) chains untouched.**
- **Name (D2): report the document's PRIMARY printed name of record** (not a fuller asserted/alternate
  form); ID-1's fuzzy judge reconciles genuine variants. Argued (not a Geet decision) — a defensible
  default, Priya-confirmable.
- **Scoring (D4):** genuine content variance (nicknames, maiden vs married) still can't be string-equality
  scored — FINDING-2's fuzzy-scoring method, its own ticket. Not this convention's job.

**Consequences.**
- **ACCEPTED TRADE-OFF (the PRIYA item):** IN-5's exact bookend now treats `Acme Logistics Inc` and
  `Acme Logistics LLC` as identical → they match, and the fuzzy leg never runs. Those are different legal
  entities; a real Inc→LLC change passes silently. Accepted because a suffix change on the same base name is
  a restructuring, not an employer change. **PRIYA:** *"Across a pay-stub and a W-2, is `Acme Inc` vs
  `Acme LLC` worth flagging as an employer change?"* If yes, **reverse by deleting the one `drop_entity_suffix`
  line from IN-5's chain** — the named test `test_in5_inc_vs_llc_matches_THE_ACCEPTED_TRADEOFF` flips and is
  the findable anchor. The countervailing benefit: no AI call + no ratification-pending finding on the COMMON
  benign `Inc`-vs-no-suffix formatting difference.
- **The golden labels' status flips:** Geet's `Acme Logistics Inc` labels are now CORRECT (the tag preserves
  the full stated form); the model's stripping became the RULE's job. So a better `employer_normalized`
  number after this is the GOLDEN matching the convention, NOT the model improving. No re-measure was done
  here (LP-335 discipline: one principled change, measure once — the re-run waits for the judgment CSV).
- Every FUTURE `*_normalized` tag (assets/credit/property waves) inherits this convention, recorded in the
  vocabulary overlay's header. No live rule changed; `ACTIVE_RULE_IDS` unchanged; the declared-normalizer
  registry is the DATA extension point (drift-guard `set(_NORMALIZERS) == KNOWN_NORMALIZERS` intact).

Cross-refs: LP-325 (the exact bookend + the declared-normalizer registry this extends), LP-328 (the date
coercer — the registry-entry precedent), LP-334 (FINDING-2), LP-335 (FINDING-1 + the tag-reports/rule-
compares principle), LP-337 (the measurement that found this).

## ADR-282: Fuzzy scoring for free-text calibration — declared per tag; normalize FORMAT; the ruler must fail things (LP-342)

**Context.** Calibration scored a tag by string equality (after a light `_norm`). That is correct for enums/
numbers and STRUCTURALLY WRONG for free text: LP-334's FINDING-2 measured `id.name_normalized` at 33% where
the "failures" were `Maria Garcia-Lopez` vs the golden `Maria Garcia Lopez` — a valid rendering. **The model
was right; the ruler was wrong.** ID-1 itself uses an AI FUZZY leg to compare names precisely because string
equality does not work — and then the harness scored names by string equality.

**Empirical finding that steered the method (the code beat the ticket).** The ticket proposed reusing the
consuming rule's declared normalizer chain, assuming `drop_punct` would make the hyphen case equal. It does
NOT: `drop_punct` DELETES the hyphen without a space (`Garcia-Lopez` → `garcialopez` ≠ `garcia lopez`), so
reusing ID-1's exact chain would STILL score the FINDING-2 headline wrong. The fix is to treat punctuation as
a WORD BOUNDARY, not as noise to delete.

**Decision.** A tag DECLARES its scoring method (in `calibration.py`, beside `_ABSTAINING_DIMENSIONS`); the
comparator dispatches by METHOD, never by tag-id (add a tag = one line):
- **`exact`** (default) — the enum/number path, BYTE-IDENTICAL to pre-LP-342 (numeric Decimal tolerance +
  `_norm` string equality). Every enum/number tag is unchanged (`txn.is_money_in` 98%/n=50,
  `income.documented_monthly` 100% do not move).
- **`normalized`** — casefold + every run of non-word chars → ONE space + strip, then equality. Reuses the
  registry's philosophy (casefold + collapse) but CORRECTS punctuation to a word boundary. Applied to
  `id.name_normalized` / `id.address_normalized`.
- **`human_review`** — a tag with NO defensible canonical golden (a free-form bank wire memo:
  `txn.counterparty`, `txn.source_reference`) — its cases are recorded with per-case detail and NEVER
  %-scored (a forced number would be a fiction). `DimensionCalibration` gained a `review` count (default 0).

**What the `normalized` score MEANS (say it plainly):** *"the tag matches the golden as the consuming rule's
DETERMINISTIC bookend would see it"* — NOT *"the tag is objectively correct."* It does NOT reproduce the
rule's AI fuzzy judge, so abbreviation/initial/generational variance (`Ave`↔`Avenue`, `M`↔`Marie`,
`Jr`↔`III`) is NOT collapsed — that residue is surfaced in the per-case detail (human review) and resolved at
SOURCE by LP-340's convention (expand abbreviations; report the name of record) + consistent golden labeling.
An AI-judge scorer (rejected: it puts a second, uncalibrated AI inside the measurement of an AI — who
calibrates the judge?) is the only thing that would collapse that residue; a validated distance threshold
(rejected: an unvalidated threshold is exactly the number this project refuses to guess) is the other
alternative. Deterministic normalized comparison + human-review residue is the chosen, free, defensible ruler.

**The leniency boundary (the heart of it).** A ruler that fails nothing is worthless. The method is proven
BOTH DIRECTIONS by MATCH/MISMATCH sets chosen INDEPENDENTLY of any tag's performance (never iterated against
the numbers — the LP-335 discipline applied to the scorer): valid renderings score EQUAL; genuinely different
values (`Jordan Rivera` vs `Taylor Nguyen`; right street/wrong number) score WRONG; a not-inert guard asserts
a wrong-by-construction distribution fires the fabrication flag.

**Interaction with LP-340 (no hidden leniency).** The name/address scorer must NOT strip entity suffixes —
`drop_entity_suffix` is IN-5's RULE-declared normalizer, deliberately scoped there. `Acme Inc` vs `Acme LLC`
scores WRONG under the name scorer (asserted), so the scorer never hides a difference the convention decides
elsewhere, keeping LP-340 testable.

**Consequences.** Two LIVE-rule free-text tags (`id.name_normalized` → ID-1, `id.address_normalized` → ID-4)
become honestly measurable; two provenance tags stay human-review. **Risk note:** all four feed
ratification-pending verdicts a human already reviews — lower-risk than a wrong enum feeding an auto-shipping
deterministic verdict; this makes them MEASURABLE, it does not imply they are the urgent risk. **No re-score
was run here** (LP-335: measure once, with Priya's judgment rows, LP-341). A better `id.name_normalized`
number under this scorer means the RULER now matches what the system cares about — NOT that the tag got
better. No rule/tag/engine/spec behaviour changed; `ACTIVE_RULE_IDS` unchanged. Cross-refs: LP-334
(FINDING-2), LP-337 (`_FREE_TEXT` / `calibrate_lf6t3n`), LP-340 (the convention + `drop_entity_suffix`),
LP-325 (the normalizer registry), LP-317 (`DimensionCalibration`, extended not replaced).

## ADR-283: Converge the two txn Stage-A prompts — one text, guarded; the calibration measured the wrong prompt (LP-344)

**Context.** LP-343's audit found TWO prompts producing the same `txn.*` tags: the standalone
`STAGE_A_TRANSACTION_SYSTEM_PROMPT` (`app/ai/tag_production.py`) that **LIVE AS-1 actually runs** (via
`produce_stage_a_transaction_tags`), and the generic `txn_stage_a` group (`tag_production.yaml`, LP-326's
re-implementation). **LP-337's live calibration (98%, n=50 on `txn.is_money_in`) measured the YAML group —
NOT the prompt AS-1 uses.** The two had already DRIFTED (the standalone defines `apparent_category`'s enum
values; the YAML listed them undefined — LP-343 F5). This is a measurement-validity bug: the audited,
measured, and shipped prompts were not guaranteed to be the same text, and were not.

**The code decided the direction (verified, not assumed).** A live run produces `txn.*` via a dedicated
`stage_a` step calling the standalone producer; `materialize_tags` (the generic path) is invoked with
`only_subjects={document, loan, borrower}` — deliberately EXCLUDING `transaction`. The generic path never
produces txn tags live. Migrating the live path onto the generic producer (option a) is blocked by the
two-stage txn flow (Stage-A → Stage-B sourcing is not a single generic group — exactly why LP-326 deferred
the migration), and would touch LIVE AS-1 for no measurement benefit.

**Decision — (c): one text, single-sourced by a guard; the live path untouched.**
- The **standalone constant is the canonical text** (it lives in `app/ai`, the clean lower layer;
  `app/ai` does NOT import `app/verification`, and must not). The generic `txn_stage_a` group's YAML
  `system_prompt` is set **byte-identical** to it.
- A **TEXT DRIFT GUARD** (`test_txn_stage_a_prompt_convergence`) fails if the two ever diverge — so the
  measured prompt and the shipped prompt can never silently differ again.
- The **PRODUCER equivalence is already guarded** (the pre-existing
  `test_txn_roundtrip_through_the_generic_producer_is_equivalent`: given identical judgments, the generic
  and standalone producers assemble IDENTICAL tags). Text-identical + producer-equivalent → the calibration
  (generic path) measures exactly what LIVE AS-1 (standalone path) ships. Rewiring `calibrate_lf6t3n` to
  literally call the standalone was REJECTED: it would break the keyless stub harness and cross the
  `app/ai ⊥ app/verification` layering, for a guarantee the two guards already give.
- The surviving TEXT is the standalone's — LP-343 called it exemplary (states the §3D principle, defines
  every category, anti-biases direction, makes `unknown` first-class). No text was IMPROVED here (the
  shipped standalone is unchanged); the thin YAML copy was converged UP to match it. One change at a time.

**D2 — LP-337's 98% is VOID and must be RE-EARNED.** It measured the OLD thin YAML `is_money_in`
instruction via the generic producer; AS-1 ships the richer standalone text (label-tolerant, anti-bias).
Different prompt → the number does not transfer. **The project currently has NO valid accuracy measurement
of the shipped `txn.*` prompt.** It gets one in LP-345 (re-run against the converged prompt, with Priya's
judgment rows, so the whole picture is measured once). The 98% is NOT quietly inherited.

**Consequences.** The drift CLASS (two producers for one tag, silently divergent, unnoticed for months) is
closed by the two standing guards. A duplicate-producer survey found **txn Stage-A is the ONLY dual case**
(Stage-B sourcing produces its tags but they are not declared as a generic group — one producer, a
different gap: LP-343 F1). No live rule moved; `ACTIVE_RULE_IDS` unchanged; the frozen LF-6T3N trace and
AS-1's suite unchanged; the standalone's batching is untouched (no call-count regression). LP-326's
deferred migration has come due — and the code shows full migration is still blocked by the two-stage flow,
so the guard, not a migration, is the fix. Cross-refs: LP-326 (the deferred migration + the producer
equivalence proof this leans on), LP-343 (the drift finding), LP-337 (the measurement it voids), LP-313/314/
314a (the txn producers), LP-345 (where the number is re-earned).

## ADR-284: Wire the snapshot/rules orchestrator into the real run — two tasks, one run row, fail-closed (LP-365)

**Context.** The LP-316/321 fact-tag architecture — the orchestrator (`verification_run.run_verification`),
the reconciler (`reconcile_evaluation_findings`, LP-322), the snapshot table (`snapshot_records`, LP-209) —
was built, tested, and migrated over ~20 tickets and **never executed on a real loan file.** The Run button
enqueued exactly one task: the AI cross-source sweep (LP-78). Neither rule engine was wired (LP-364-B's
diagnosis confirmed it). The tests asserted every part; none asserted the path. This ADR records the first
wiring and the decisions it forced.

**Decision — a second Celery task (`run_rule_engine_pass`) runs the governed pass ALONGSIDE the sweep on the
same run row.**
- **Run status is FAIL-CLOSED.** Two tasks now write one `Verification` row. The rule task marks the run
  FAILED on exhaustion; the sweep's `COMPLETED` set is guarded to **never overwrite a FAILED**
  (`cross_source.py`). So a run reads COMPLETED **only if BOTH passes completed**; if either failed, it
  reads FAILED. *A run marked COMPLETED while the governed engine silently failed is a run-level
  false-green — the exact class this architecture exists to prevent.* The normal path is behaviour-identical.
- **Counts are NEVER summed.** The sweep keeps sole ownership of `red_count`/`yellow_count` — an ungoverned
  75%-confidence AI observation and a governed, gated, provenance-carrying rule finding are **not the same
  kind of thing**; summing them makes the §8 honesty contract meaningless. The rule findings carry their
  own `evaluation_outcome` axis and are counted separately at read time (LP-369).
- **The LP-78.1 input-fingerprint cache is inherited, and REPORTED as mis-keyed.** It is computed from the
  cross-source inputs; the rule engine reads a SUPERSET (all documents), so a cache-hit could skip a rule
  run a rule-relevant-only change should have triggered. The rule task rides the same cache-miss trigger as
  the sweep for now; a rule-aware fingerprint is its own follow-up. Not silently inherited — flagged.
- **A real run uses the REAL model** (the task passes no reasoners → `reasoners=None`), never a stub.

**Consequences — the engine's first contact with a real file (DB LF-6T3N, 30 documents, 282s, sonnet-4-5):**
- **38 governed findings persisted** (origin `DETERMINISTIC_RULE`, `evaluation_outcome` set, provenance):
  `couldnt_check` 30, `needs_review` 4, `satisfied` 2, **`open` 2** — the first real rule VIOLATIONS ever
  produced (ID-6, IN-2). Separation held: the sweep's `ai_cross_source` findings kept `evaluation_outcome`
  null; nothing merged.
- **The fixture numbers SURVIVED** (they were expected to break): AS-1 = 15 `couldnt_check` + 2
  `needs_review`, identical to the stripped-fixture claim — because the insurance-orphan bug (LP-367) gates
  the DTI on the real file too (`housing.insurance_monthly` unknown; `gross_monthly_income` resolves to
  $28,168.80 but is trapped behind the gate). AS-1's DTI dependency (LP-366) is real on the real file.
- **Run #2 exercised the reconciler for the first time ever**: 38 carried_forward, 0 minted, 0 retired, 0
  resolved — LP-322 reconciles correctly (no duplicate mint on the uniqueness index, no false retirement).
- **95 `tag_production` degradations** on the real run — reported for its own ticket, not fixed here.
- **9 stale `xsrc.*` `deterministic_rule` findings** (2026-07-08) with `evaluation_outcome` null — pre-wiring
  artifacts of the older LP-74 engine; the five-tab read (LP-370) must place null-outcome deterministic
  findings deliberately.

**REPORT, don't fix.** Every surprise is its own ticket (LP-366 AS-1's DTI dep, LP-367 the insurance orphan,
the 95 degradations, the stale xsrc findings). No engine/rule/tag/spec change; `ACTIVE_RULE_IDS` unchanged;
the AI sweep behaviour-identical; the frozen fixture trace unchanged. Cross-refs: LP-316/321 (the
architecture), LP-322 (the reconciler), LP-209 (snapshot_records), LP-364-B (the diagnosis that found it
unplugged), LP-78 (the sweep it coexists with).

## ADR-285: The `loan_tag` operand — a rule reads a LOAN-level tag from any subject, without a calculator (LP-366-A)

**Context.** LP-366 set out to fix AS-1's false DTI dependency as a **pure DATA change**: swap AS-1's income
operand from `{calc: [dti, gross_monthly_income]}` (which fail-closes on `housing.insurance_monthly`, an
input AS-1 never uses — LP-367) to a direct income read. Phase 0 proved the pure-data fix is **impossible**:
`_resolve_operand` reads a `tag` operand from `subject_tags`, and the `per_deposit` enumerator hands each
transaction ONLY its own tag map (`by_subject[txn.content_id]`) — never the loan's. A per-deposit rule
therefore **cannot** read a loan-level fact through a `tag` operand; the ONLY operand that reaches loan-level
is `calc`, which is exactly what drags in the calculator's gate. The blocker is a **missing operand kind**,
not a data typo — so it splits out as its own ticket (LP-366-A, engine), leaving LP-366 as the trivial
data swap that consumes it.

**Decision — add a declared `loan_tag` operand: a LOAN-subject tag read from ANY rule, whatever its subject.**
- **Mechanism.** `_resolve_operand` gains one branch: a `loan_tag` operand reads
  `snapshot.tags.by_subject[LOAN_SUBJECT]` directly (the same access the loan enumerator uses), bypassing
  `subject_tags`. It is coerced through the SAME `_COERCERS[type]` registry as `tag` (so `date`/`decimal`
  work identically), and is a first-class member of the Operand's exactly-one-source set.
- **Fail-closed, never 0.** Absent loan subject / absent tag / unparseable value → `None` → `couldnt_check`.
  Never a fabricated `0` (a `0` income would size AS-1's threshold to `0` and fire on every deposit — the
  precise false-positive the fact-tag discipline exists to prevent).
- **Why it BEATS a `calc` — independent of AS-1.** A `calc` operand ignores the calculator's confidence
  (LP-318 Caveat A: `_calc_operand` never reads `entry.confidence`); a `loan_tag` flows the tag's confidence
  through the ordinary tag gate, like every other governed fact. Reading a loan-level fact as a *governed
  tag* rather than an *opaque calculator number* is strictly more honest — a general property, not an AS-1
  special case.
- **Generic — no rule-id branch.** A new rule opts in with a SPEC line (`{loan_tag: <tag>}`); zero engine
  code per rule. This is the eleventh application of the declared-key-registry pattern.
- **Equivalence.** Every live rule is byte-identical: AS-1 still reads `{calc: [dti, ...]}` (its swap to
  `loan_tag` is LP-366, a separate data change), and the `calc` operand is UNTOUCHED — AS-4 keeps it, because
  its reserves→PITI→insurance dependency is legitimate (a reserves rule genuinely needs the housing expense).
  `ACTIVE_RULE_IDS` unchanged.

**The income tag it reads — `dti.qualifying_income_monthly` (D1, argued not assumed).** The tag already
exists in `fact_tags.csv` (mode `derived`, subject `loan`, consumers `DT-1, AS-1, AS-3`) but was **never
declared in `tag_production.yaml` and had no recipe**, so it never materialized. LP-366-A declares it and adds
the recipe: it sums the borrowers' **MISMO STATED income lines** (`borrower.<n>.income.<m>.monthly_amount`),
the SAME income the DTI qualifies on (its income lines are `source='stated'`). This is the right tag — not a
newly-minted second income figure (which LP-323-IN-A warns against) — because AS-1's threshold is
definitionally "50% of total monthly qualifying income," and the stated 1003 total IS what the DTI qualifies.
On the real file it materializes to **$28,168.80**, matching LP-365's reported `gross_monthly_income` exactly.

**F2 (recorded prominently).** AS-1's income is the **MISMO stated 1003 total** (`source='parsed'`), NOT the
AI `income.qualifying_monthly` tag — which did **not** materialize on the real run (one of the 95
degradations) and whose continuity/averaging convention is underspecified (LP-343 F2). Reading the stated
total keeps F2 entirely OFF AS-1's path: AS-1 never depends on the AI qualifying-income judgment.

**Consequences / reported, not fixed.**
- The **95 `tag_production` degradations** (LP-365) remain their own ticket — NOT investigated here; whether
  `income.qualifying_monthly` *should* materialize is orthogonal to AS-1 reading the stated total.
- **Pre-existing flaky test discovered (its own ticket):** `test_no_raw_pii_in_stored_json` trips the
  `_LONG_DIGITS` at-rest guard (`\b\d{9,}\b`) ~0.6%/persisted-PiiField because a salted `match_hash` hex
  occasionally contains a quote-bounded 12-digit run. Independent of LP-366-A (that test hand-builds its
  snapshot; no recipe runs). Flagged, not fixed.
- LP-366 now becomes the one-line data swap; LP-367 (the insurance orphan) is still needed for the DTI/AS-4,
  but no longer blocks AS-1. Cross-refs: LP-366 (the data swap), LP-367 (insurance orphan), LP-318 (the calc
  gate + Caveat A), LP-328 (typed operands / the coercer registry), LP-343 (F2), LP-365 (the real run).

## ADR-286: The declared-key-with-no-member class — validate what declarations POINT AT, not just that they exist (LP-369)

**Context.** A recurring, high-severity bug has now been found FOUR times, each at a different seam but with one
shape: **a declaration names a key that resolves against a registry/field-set with no such member, and the
system resolves the miss to ABSENT rather than ERROR. Absent is indistinguishable from "the input genuinely
doesn't have this," so the consuming rule couldnt_checks — silently, on every file, forever, with every test
green.**
- **AS-1** (LP-366): read income through a DTI calc gated on `housing.insurance_monthly` — an input AS-1 never
  uses. The calc gated → the threshold never resolved → AS-1 never evaluated a deposit.
- **IN-8 / IN-9** (LP-333): applicability named document types the classifier doesn't emit
  (`verification_of_employment` vs `voe`) → `not_applicable` on every file.
- **The orphaned tags** (LP-366-A / LP-367): `housing.insurance_monthly` / `dti.qualifying_income_monthly`
  declared with a `producer` in the vocabulary but NO producer anywhere in `app/`.
- **Parsed field-name mismatches** (LP-368 / this ticket): parsed declarations named extraction fields that
  don't exist — `id.dob` read `dob` (it is `date_of_birth`), `id.ssn_hash` read `ssn` (it is `employee_ssn`),
  `id.marital_status` read a document field that lives on the borrower in MISMO. **Two LIVE rules (ID-3 DOB,
  ID-2 SSN) had never evaluated anything.**

**The root, named:** *the loader validates declarations that EXIST; it does not validate that what they POINT
AT exists.* A declared key with no member → absent → silent. The four instances are one class at four seams
(calc input, classifier document type, tag producer, extraction field).

**Decision — fix the parsed field mismatches (DATA) and add a GUARD that closes the parsed seam.**
- **The fixes (tag_production.yaml, declaration edits only — no engine Python):** `id.dob` → `date_of_birth`;
  `id.ssn_hash` → `employee_ssn:hash`; `id.id_expiration` → `expiration_date`; `income.employment_start` →
  `start_date`; `income.employment_end` → `end_date` (all real extraction field names). `id.marital_status`
  was wrong on BOTH axes (a document field named `marital_status` that no document has, and it lives on the
  BORROWER in MISMO) → re-keyed to `{subject: borrower, data: marital_status}`.
- **The SUBJECT decision, driven by the rule's read pattern (not the field's logical owner).** `id.dob` feeds
  ID-3, a CONSISTENCY rule that GATHERS a document-keyed fact across the borrower's sources
  (`source_scope: borrower_documents`) and compares. A borrower-keyed tag would give ONE value → nothing to
  compare → uniformly couldnt_check (a lateral move). So `id.dob` stays `subject: document` — only the field
  name was wrong. Same for `id.ssn_hash` → ID-2. Conversely `id.marital_status` is NOT gathered by any live
  rule (ID-7 reads only `id.title_vesting_consistent`, into which the marital/vesting judgment is baked), so
  its correct home is the borrower subject. **The subject must match how the rule READS the tag.**
- **The GUARD (the durable deliverable — worth more than the fixes):** a test asserting every `mode: parsed`
  declaration names a field that EXISTS in its subject's resolution universe — `subject: document` → an
  extraction model's field name (the `DocumentEntry.fields` key space, introspected from `app.ai.extraction.*`
  + the `asserted_name` alias); `subject: transaction` → a `_TXN_FIELDS` key. It **fails loud** on the exact
  pre-fix shape (proven by a self-test: `data: "dob"` → flagged; `data: "date_of_birth"` → passes), splitting
  the `:hash` suffix as the producer does.

**What the guard COVERS and does NOT.**
- COVERS: `subject: document` and `subject: transaction` parsed declarations — a static, complete field
  universe from the models. This is where all four parsed mismatches lived.
- DOES NOT: `subject: borrower` / `loan` declarations read MISMO facts, whose keys are DATA-DEPENDENT
  (`borrower.{n}.<field>` / a full key) and cannot be enumerated from the models — the guard SKIPS them and
  says so. Nor does it cover the OTHER three seams of the class (calc inputs, classifier types, tag producers)
  — each needs its own analogous guard (the classifier seam already has LP-333's).
- **Two declarations are EXEMPTED, loudly:** `income.stated_monthly` (stated income is MISMO-indexed, not a
  document field — needs a derived source) and `stmt.page_count_declared` (no extractor emits a page count).
  Both feed DORMANT rules; the exemption lists them with a reason and a test asserts each is STILL a genuine
  mismatch, so the allow-list cannot rot into hiding a now-resolvable declaration.

**Why a TEST, not a load-time check.** The authoritative field universe lives in `app.ai.extraction.*`. A
load-time validation would force the deterministic tag-vocabulary loader (`declarations.py`) to import the AI
extraction layer — a layering inversion. The test fails CI just as loudly without that coupling; promoting it
to a loader validation is a small follow-up if the layering is ever resolved.

**Consequences (deterministic replay on the persisted LF-6T3N snapshot).**
- **ID-2 (SSN) resurrected:** before, both borrowers couldnt_check ("0 sources carry id.ssn_hash" — the tag
  was absent); after, borrower A → **satisfied** ("SSN matches across all 2 sources", two W2s), borrower B →
  couldnt_check ("only 1 source" — one W2's SSN was non-matchable). A real verdict where there was silent death.
- **ID-3 (DOB): the tag is fixed and materializes (2 driver's licences), but ID-3 still couldnt_checks** —
  because each borrower has exactly ONE document stating DOB (the DL; no 1003/URLA document is in the file), so
  there is nothing to compare. The reason improved from "0 sources (tag broken)" to "1 source (genuinely one)".
  This is CORRECT (a file limitation, not the bug) and, crucially, NOT the lateral move — document-keying means
  a file WITH a second DOB source would now compare; borrower-keying never could.
- **ID-7 unchanged:** not_applicable on non-title documents, couldnt_check on the untyped ones — blocked by the
  absent title document (correct). `id.marital_status` now materializes but no live rule reads it as a tag.
- Every other live rule identical; the full suite passes (2338). No rule spec, vocabulary meaning, or allowed
  value changed — the declarations were wrong; the tags were not.

**Still open (reported, not done here):** the live-rule materialization audit (each of the 11 live rules'
load-bearing tags checked on a real file — this ticket did ID-2/ID-3/ID-7); the dormant tag-layer smoke test
(income/asset AI groups have never run); `income.stated_monthly` re-architecture as a derived tag; the page-
count extraction gap (AS-9). Cross-refs: LP-368 (the diagnosis that found the parsed class), LP-333 (the
classifier-mismatch analogue + `_required_ai_groups`), LP-326 (the declaration/producer model), LP-366 (AS-1,
the first instance of the class), LP-367 (the orphaned insurance producer).

## ADR-287: Wire OC-2's occupancy tags — the third orphan; the first loan-subject AI group; defining "the signals" (LP-371)

**Context.** OC-2 (occupancy reasonableness) is LIVE (`ACTIVE_RULE_IDS`) but had **never assessed a single
file.** Its two load-bearing judgment tags — `occupancy.stated` and `occupancy.consistent_with_signals` —
were in `fact_tags.csv` WITH producers named, but **neither was declared in `tag_production.yaml` and nothing
wrote them** (`grep` → 0; 0 instances in the persisted snapshot). A judgment rule gates its load-bearing tags
fail-closed BEFORE any AI call (`gate.py:56`), so OC-2 couldnt_checked on **every file, structurally** — an
occupancy-fraud signal silently unchecked since the beginning. This is **the third orphan** of a class:
*a tag declared in the vocabulary with a producer, but with no declaration and nothing writing it, resolves to
ABSENT; absent is indistinguishable from "the document genuinely doesn't have this", so the rule couldnt_checks
silently, forever, with every test green.* Prior instances: `housing.insurance_monthly` (LP-367, still open),
`dti.qualifying_income_monthly` (LP-366-A, fixed). **LP-373 will GUARD the class** (a vocabulary tag with a
producer must HAVE a declaration) — not built here.

**Decision — wire both tags as data/declaration/recipe/prompt; no engine change.** The AI materialization path
is already subject-generic (`ai.py` uses `subject_type(group.subject).enumerate/.build_context`) and
`_MATERIALIZED_SUBJECTS` includes `loan`, so a loan-subject AI group runs without new Python.

**D1 — `occupancy.stated` is DERIVED, not parsed.** MISMO's `property.occupancy` = `"primary_residence"`; the
tag's declared `allowed_values` are the shorthand `[primary, second, investment]`. A parsed tag is never
re-typed, so a raw passthrough (LP-370's suggestion) would emit the out-of-enum `"primary_residence"`. Wired
as a **derived recipe** mapping MISMO→enum (`primary_residence→primary`, `second_home→second`,
`investment[_property]→investment`), abstaining to `unknown` on absent/unmapped — never a guessed occupancy.
This is a reported change of production mode, NOT a change to the tag's meaning or allowed_values. (Contrast:
`program.type`'s MISMO `loan.program` is already `"conventional"`, matching its enum — occupancy is the
exception that needs a mapping.)

**D2/D3 — "the signals," and whether the AI can SEE them (the durable part).** `occupancy.consistent_with_signals`
is the FIRST loan-subject AI group. A loan-subject AI's context (`_loan_context`) is the loan's **MISMO facts
ONLY** — NOT the tag layer, NOT the documents. MISMO carries **no borrower residence address** (only
`property.address` = the subject). So the *address*-consistency signals the vocabulary's one-line description
hints at ("address/other signals") are **invisible** to this tag — an AI told to check them would be judging on
nothing (the LP-368/370 "wrong subject's context" trap, avoided). What MISMO DOES carry, and what the tag is
therefore DEFINED to use, are the 1003 **declaration** signals: `property.occupancy` (the claim),
`borrower.<n>.declaration.intenttooccupytype`, `borrower.<n>.declaration.fhasecondaryresidenceindicator`, and
`property.financed_unit_count`. **The tag reports whether the borrower's OTHER declarations AGREE with the
stated occupancy — a structural FACT, not OC-2's reasonableness judgment.** Defining "the signals" concretely
is the antidote to LP-340's root cause (an undefined term the model and the labeler read differently). **LIMIT
(reported, not fixed):** the address-consistency dimension needs a borrower-residence-address MISMO fact
(absent) or surfacing per-document address tags into the loan context (an engine/context change) — a follow-up.

**The prompt (LP-335/340 class avoided).** Copies `STAGE_A_TRANSACTION_SYSTEM_PROMPT`'s §3D framing verbatim in
spirit: STATES that the model structures a fact and does NOT judge rules/approvability/fraud ("Downstream
deterministic code and a human reviewer do all judgement; they can only be correct if your fact is accurate");
NAMES the exact MISMO signals; DEFINES every value (yes/no/unknown) with examples of what the DECLARATIONS
STATE (not what a rule should conclude); makes `unknown` first-class and reachable; and says **nothing** about
OC-2, rules, purpose, or reliability. No exemplar encodes a downstream assumption; no purpose hedge ("so the
rule can…", "where it aids matching" — LP-340/F5); no reliability speculation ("often stale" — LP-335). **The
honest limit: this prompt is UNMEASURED** — LP-335/340 were found by MEASUREMENT, not reading (LP-343's own
stated limit). It must join the calibration worksheet (LP-379).

**D4 — cost.** One added AI call per run (the loan-subject `occupancy` group, 1 subject), plus OC-2's existing
judgment call. Small; runs on every file.

**Consequences (real run on DB LF-6T3N — reported, not predicted).** `occupancy.stated` materializes to
`primary`; the `occupancy` AI group produced `occupancy.consistent_with_signals = yes` (conf 1.0), reasoning
precisely over the named signals ("both borrowers intent-to-occupy 'Yes', secondary-residence 'false',
financed_unit_count 1 — all support primary_residence"); OC-2 then produced a real judgment: **needs_review,
ratification_pending=True** ("occupancy is reasonable … 'yes' is an AI judgment and must be ratified by a
human"). **OC-2 went from couldnt_check-forever to producing a ratification-pending judgment.** `needs_review`
is the correct terminal state for a judgment rule — it never auto-ships; a human ratifies. Fail-closed
preserved: absent occupancy → `occupancy.stated` unknown / `occupancy.consistent_with_signals` absent → the
gate couldnt_checks with a reason (no fabricated verdict). Every other live rule identical; full suite green.

**No fourth orphan surfaced** in this ticket. Cross-refs: LP-370 (the audit that found OC-2 dead), LP-366-A/367
(the orphan class), LP-373 (the orphan guard, deferred), LP-326 (declarations/producers), LP-335/340/343 (the
prompt-bug class this prompt must not join), LP-379 (calibration — this prompt is unmeasured).

## ADR-288: An AI `unknown` gather-filter type is absent-for-comparison — exclude + surface, not veto (LP-372)

**Context — the NEW shape.** ID-4 (current-address consistency, an identity-fraud signal, LIVE + auto-shipping)
gathers `id.address_normalized` filtered by `id.current_address_type == residence`. When ≥2 address candidates
exist, the consistency engine gated the filter tags' confidence/known-ness (`consistency.py`, LP-325 review):
**if ANY candidate's `current_address_type` was `unknown`, the whole per-borrower comparison was VETOED →
couldnt_check.** LP-370 flagged this UNCERTAIN and refused to call it correct ("exactly the call that let
AS-1/ID-2/ID-3 survive"). The shape is genuinely new: not an absent tag, not a wrong field — **a present,
materialized filter tag whose `unknown` value on ONE candidate vetoes an entire per-subject comparison.**

**Evidence (real run 01039e93, LF-6T3N — reasoning strings read, not trusted).** The address-bearing sources
typed `unknown` are the **subject-property documents** — the purchase agreement (`"This is the subject property
being purchased, not the buyer's residence address"`), mortgage statements, property-tax bills. Their `unknown`
is **honest and CORRECT**: a property address is genuinely not the holder's residence. `absent ≠ unknown` holds;
the **producer is innocent** (D1/D2 — not a producer bug; the bank statements typed `address_normalized=unknown`
and dropped out one step earlier, never reaching the gate — LP-370's "bank statements poison it" premise is not
what happens). Each borrower has exactly ONE residence-typed source (their DL) and no 1003, so ID-4 couldnt_checks
on this file for **thin data** — and would do so under EITHER policy (excluding the unknown leaves 1 residence).
**LF-6T3N cannot by itself exercise the veto-vs-exclude choice** (that needs ≥2 confidently-typed residences +
an `unknown` candidate) — the honest limit. But the choice is decidable **on principle**, and that is D3.

**Decision — treat an AI `unknown` filter-type as ABSENT-FOR-COMPARISON: exclude the source, keep it out of the
veto gate, and SURFACE the exclusion count in the finding's reason.** This restores the codebase's own invariant,
which the veto violated: a gather-tag `unknown` is *already* "absent-for-comparison → exclude" (`consistency.py`,
the `_UNKNOWN` skip), and an **absent** filter tag is *already* silently excluded with no veto. Only a *present*
filter tag valued `unknown` vetoed — so **"honest unknown" was punished more harshly than "absent"**, an inversion
of `absent ≠ unknown`. The veto's rationale ("the classifier is untrustworthy here, so distrust its `residence`
labels too") is refuted by the reasoning strings: the classifier is *confidently, correctly* declining to call a
property address a residence — that is it WORKING. And because the purchase agreement is in **every purchase file**
and correctly typed `unknown`, the veto made ID-4 **uniformly couldnt_check** on realistic files (LP-333: a rule
that uniformly couldnt_checks is a FAILURE). **KEPT:** the confidence gate for a present, CONCRETE-but-shaky type
(a `residence`/`mailing` label below the floor) — that IS a genuine shaky inclusion decision.

**Why not (a) keep the veto, or (b) plain-exclude.** (a) VETO → uniform couldnt_check → Tab 1 noise → the tab that
matters gets ignored, and ID-4 never protects anything. (b) PLAIN-EXCLUDE → a disagreeing residence hiding behind
an `unknown` type is silently dropped → an auto-shipped false-green on identity fraud. **(c) EXCLUDE + SURFACE**
takes exclude's usability and closes plain-exclude's gap: the finding's reason names the count of address-bearing
sources that could not be typed and were excluded, so a human can look. **ACCEPTED TRADE-OFF (named in a test so a
reversal is findable — the LP-340 precedent):** if the ONLY disagreeing residence were hidden behind `unknown`,
the discrepancy surfaces only as an exclusion count, not as a `fired`. We accept that over couldnt_checking every
file. Reversible by restoring the veto.

**Generic, no rule-id branch.** The change lives in the generic `_borrower_documents` gather + the evaluator's
reason assembly; it is DECLARED-behavior over any rule's `gather_filter`. **ID-4 is the only spec with a
`gather_filter`**, so no other live rule's behavior changes (ID-1/2/3, IN-5 have `gather_filter=None` and skip the
branch — their reasons are byte-identical). The pattern of keeping engine code rule-generic holds.

**Consequences (real run, reported not predicted).** ID-4 on LF-6T3N: **before** = 2 couldnt_check with the
misleading veto reason (`"… classification … is not trustworthy: … is unknown"`, blaming `doc067c2` = the purchase
agreement); **after** = still 2 couldnt_check, now with the HONEST root (`"only 1 source … of type 'residence' …
nothing to compare (1 other address-bearing source could not be typed as 'residence' and were excluded)"`). Same
verdict, truthful reason. On a richer file (DL + 1003 both residence + an `unknown` candidate) ID-4 now COMPARES
and satisfies/fires — which the veto previously blocked (pinned by new both-direction tests). The `id_address`
prompt remains UNMEASURED and should join LP-379's worksheet. **Priya item:** is a bank statement's stated address
a `residence`? (Here they typed `address_normalized=unknown`; not decided.) Cross-refs: LP-370 (the audit that
refused to call ID-4 correct), LP-325 (the gather contract — ABSENT≠DISAGREEING, `<2`→couldnt_check), LP-335
(FINDING-1, the same tag's last bug), LP-333 (uniform couldnt_check is a failure), LP-343/334 (the prompt is
unmeasured), LP-379 (calibration).

## ADR-289: The vocabulary orphan guard — fail loud when a live consumer reads a tag nobody produces (LP-373)

**The class.** *A tag declared in the vocabulary (`fact_tags.csv`) with a producer named, but with no
declaration in `tag_production.yaml` and nothing in `app/` writing it, resolves to ABSENT; absent is
indistinguishable from "the document genuinely doesn't have this", so the rule reading it couldnt_checks
silently, forever, with every test green.* Found THREE times, each by accident after a LIVE rule was already
dead: `dti.qualifying_income_monthly` (LP-366-A — AS-1 never evaluated a deposit); `housing.insurance_monthly`
(LP-367, open — the DTI calc can never compute on any file, UI shows a fabricated $0.00);
`occupancy.stated`/`occupancy.consistent_with_signals` (LP-371 — OC-2 dead since the beginning). **The root:**
the loader validates declarations that EXIST; it never checks that a vocabulary tag with a producer HAS one.

**Decision — a guard (a TEST) that fails when a LIVE consumer HARD-reads an unproduced vocabulary tag.**
Sibling to LP-369's declaration→field guard, one seam earlier (vocabulary→producer).

**D1 — "produced" has THREE sources, not one.** A definition checking only `tag_production.yaml` is wrong:
(1) a declaration there (54 tags); (2) the **hardcoded transaction path** — `services/tag_production.py`
(Stage A) + `tag_correlation.py` (Stage B, `txn.has_identified_source`), which the live orchestrator leaves
alone (`producer.py`); (3) a live judgment rule's `output_tag`. Missing (2) would false-positive on
`txn.has_identified_source` (read by LIVE AS-1) — D1's trap.

**D2 — the severity model (the census decided it, not the framing).** A guard that fires on every
authored-ahead tag is noise and gets muted within a week (LP-333's dynamic); one that misses a live rule's
orphan is worthless. So an unproduced tag FAILS the build only when a LIVE consumer **hard-reads** it — a live
rule reads it as a gated input (load-bearing / operand / gather / applicability / when-tag → absence =
couldnt_check), OR it is a required input to the always-computed DTI calculator (`_REQUIRED_DTI_TAGS`, the only
tag-gated calc, on the live path, rendered in the UI — LP-367's shape). All three instances were this. Read
only by INERT rules, by NO rule, or **softly** (a judgment rule's `reasoned_over` — not gated, so absence only
thins the AI's context) → reported, not failed. Real census (156 tags): 58 fine, 73 inert-orphan, 22
no-rule-orphan, **2 live DTI-calc orphans**, 1 live-soft orphan. **Zero live-rule HARD orphans remain** (the
three fixes closed them); every `id.*` tag is produced.

**D3 — where it lives: a TEST, not load-time.** The guard needs `ACTIVE_RULE_IDS`, the rule specs, and the
calc layer. Running it at load would force the tag-vocabulary loader to import the rule engine — inverting the
dependency (the vocabulary is read BY the rule engine). Same argument, same conclusion as LP-369; a CI test
fails just as loudly.

**D4 — what it does NOT cover (the seam map).** A declared producer that never RUNS (`_required_ai_groups`,
LP-333/368 — unguarded); a declaration naming a nonexistent field (LP-369, document/transaction only); a tag
that materializes but is WRONG (calibration, LP-379); a live-rule SOFT `reasoned_over` orphan (reported); a
produced+consumed tag ABSENT from the vocabulary (`txn.source_strength` — read by live AS-1, produced by Stage
B, not in `fact_tags.csv` — invisible to a vocabulary scan). This is ONE seam of several — the class is not
"closed", it is now GUARDED at this seam.

**`housing.insurance_monthly` (LP-367 open) is handled, not fixed.** The guard would fail on it today (correct
— it IS a live orphan). It is a LOUD exemption in `_KNOWN_LIVE_ORPHANS` naming LP-367, with a test asserting it
is STILL a genuine orphan (unproduced AND live-consumed), so the exemption cannot rot — LP-369's discipline.

**Fourth orphans found (reported, not fixed — the first complete scan).** `housing.taxes_monthly` — a SECOND
DTI-calc orphan (LP-367 named only insurance; the calc needs both); `property.address_normalized_match` — a
live SOFT orphan (OC-2 `reasoned_over`, ADR-287's documented address follow-up); `txn.source_strength` — a
produced+consumed tag missing from the vocabulary.

**Consequences.** No engine/rule/vocabulary change; `ACTIVE_RULE_IDS` unchanged; full suite green (2357).
`test_guard_fires_on_a_synthetic_live_rule_orphan` proves it can fail; `test_guard_catches_the_dti_calc_orphans_when_not_exempted`
proves it fires on the real open orphans. Cross-refs: LP-366-A/367/370/371 (the instances), LP-369 (the sibling
guard), LP-326 (declarations), LP-333 (the `_required_ai_groups` seam), LP-379 (calibration).

## ADR-290: Wire homeowners insurance as a derived tag — the last orphan, and the DTI-read-path finding (LP-374)

**The third orphan, closed.** `housing.insurance_monthly` was declared in `fact_tags.csv` (`produced_by=AI`)
but nothing produced it — the last instance of the ADR-289 class. Wired as a **derived** recipe reading the
`homeowners_insurance` binder's extracted `annual_premium ÷ 12`. LP-373's guard now PASSES on it (removed from
`_KNOWN_LIVE_ORPHANS`); `housing.taxes_monthly` remains the one exempted DTI-required orphan (a follow-up).

**D1 — the finding that overturned the ticket's premise (the code is the gate of record).** The ticket held
that the DTI "can never compute on any file" because this tag never materializes. **False.** The DTI reads
insurance DIRECTLY from the extraction — `services/dti.py` `_extracted_monthly(homeowners_insurance,
annual_premium) ÷ 12` — and the `_REQUIRED_DTI_TAGS` gate checks the calc LINE (grouped by `from_tag`
*lineage*), never the tag layer. So **the DTI already computes on any file with a binder, independent of this
tag.** `housing.insurance_monthly` (vocab `subject=loan`) is consumed only by INERT rules (DT-1/DT-5/IH-1) — it
is really an inert orphan; ADR-289's "live-orphan(dti-calc)" label rested on reading `_REQUIRED_DTI_TAGS`
membership as a tag read, but it is lineage. **Wiring the tag does NOT unblock the DTI** (nothing was blocked);
it closes the orphan, materializes the tag on a binder file, ALIGNS it with the same `annual_premium ÷ 12` the
DTI computes, and serves the tag's own consumers. Recorded here so the record is honest rather than echoing the
premise.

**D1 subject.** `subject: loan, mode: derived` — matching the vocabulary + the loan-level consumers (a
document-keyed tag would be a lateral move: orphan → present-but-unreadable). A derived recipe reads the whole
snapshot, and `annual_premium` IS in the snapshot's document fields (`build_document_fields`), so — unlike
LP-371's loan-subject AI *context* (MISMO-only) — the recipe can see the binder. Mirrors `occupancy_stated` /
`qualifying_income_monthly`.

**D2 — multiple binders → `unknown` with a reason, never a guessed premium.** The recipe takes the DISTINCT
`annual_premium`; conflicting binders → abstain naming the conflict (the LP-332/LP-336 fail-closed-on-ambiguity
precedent); identical duplicates → the one value. The DTI's `_extracted_monthly` takes the single current binder
without this check, so the tag is STRICTER on ambiguity — deliberate and reported (the DTI is out of scope).

**Absent ≠ 0, and why.** No binder / no premium / non-positive / unparseable → `unknown` with a reason, NEVER
0. A 0 premium makes the DTI confidently too-low — the exact false-green the DTI's gate exists to prevent.

**What this does NOT fix.** LF-6T3N has no binder, so the tag is `unknown` and the DTI stays gated there — the
correct, honest outcome, UNCHANGED by this ticket (the gate is extraction-driven). The UI DTI card's fabricated
"$0.00 Extracted" (the display `DtiCalculation` collapses the unknown insurance input to 0 while the snapshot
calc correctly gates) is LP-375's — reported precisely, not fixed here, and independent of the tag wiring.

**Consequences.** No engine change (a declaration + a recipe-registry entry; `produce_derived_tags` untouched).
Real run (`01039e93`): tag = `unknown` ("no homeowners insurance binder in the file"); DTI `gated=True`
("housing.insurance_monthly is unknown"). Full suite green (2367). Cross-refs: LP-318 (the calc gate), LP-326
(derived recipes + abstention), LP-366-A/370/371/373 (the orphan class + its guard), LP-364 (the UI that exposed
the $0.00), LP-375 (the display fix).

## ADR-291: The read path — surface `satisfied`, separate the two systems' counts structurally, stop the DTI card fabricating 0 (LP-375)

**Why GREEN/`satisfied` must be returned.** `_build_status` filtered findings to `status IN (RED, YELLOW)`,
dropping GREEN — where `satisfied` (and `no_longer_applies`) land. §8 makes `satisfied` FIRST-CLASS: it is how
a human knows a rule RAN and PASSED rather than silently not running. This project found FOUR live rules that
were silently not running (AS-1, ID-2, ID-3, OC-2), each with every test green — a visible `satisfied` is what
makes that difference legible. On LF-6T3N there are 2 `satisfied` rule findings that were unreachable; now they
surface (Tab 2). Fix: `rule_findings` is returned with NO status filter (all outcomes).

**Why the two systems' counts are STRUCTURALLY separate.** An ungoverned 75%-confidence AI sweep observation
(no gated tags, no provenance, no outcome state) and a governed rule finding (gated load-bearing tags, inline
provenance, a spec-cited guideline, a §8 outcome) are not the same kind of thing; summing them makes the §8
honesty contract meaningless. The response returns TWO DIFFERENT TYPES — `findings: list[FindingPublic]`
(legacy) and `rule_findings: list[RuleFindingPublic]` (governed). Different types cannot be concatenated or
their counts summed — structural, not merely conventional. **The discriminator is `evaluation_outcome IS NOT
NULL`, not `origin`:** confirmed on real data, `origin=deterministic_rule` spans BOTH the governed engine AND
retired `xsrc.*` findings (outcome null, stale). So "Tab 5 — Old Findings" is TWO legacy systems (the
`ai_cross_source` sweep + the `xsrc` deterministic rows) = 16 on LF-6T3N; `rule_findings` = 38 (30 couldnt_check
· 4 needs_review · 2 open · 2 satisfied). The guideline citation is read from the SPEC
(`load_rule_spec(rule_id).guideline_reference`), never AI-recalled.

**The $0.00 fix — display layer, and the coupling that shaped it.** The display path collapsed an absent input
to 0 (`_to_items`: `auto.auto or Decimal(0)`) and computed a confident ratio on it, while the snapshot path
(`calculations_section.map_dti`) GATED on the same `auto_amount=None` — two paths contradicting each other on
one page. **Absent ≠ 0: a 0 premium makes the DTI confidently too-low, the exact false-green the gate exists to
prevent.** A subtlety: `build_calculations_section` calls the SAME `build_dti_calculation`, and `map_dti`
returns `None` (absent DTI) when `back_end_dti is None` — so nulling the ratio inside `build_dti_calculation`
would have flipped the snapshot's honest *gated* entry to *absent*, changing the path I was told not to touch.
The fix therefore keeps the ratio computed in `build_dti_calculation` (adding `gated`/`gate_reason` + an
`unknown` line flag) and nulls the ratio at the API boundary (`gate_display_ratios`), so the DISPLAY agrees
with the engine WITHOUT altering the snapshot path or any gate / `_REQUIRED_DTI_TAGS`.

**What this does NOT change.** The sweep's `findings`, counts, and banner are identical (its filter is
unchanged; GREEN is not un-dropped for it). The submission gate (`blocked`/`in_scope_open_count`, LP-75) still
spans both systems — the display lists are separated, but a per-system BLOCKING split is a policy question
(LP-377). `calculations_section.py`, `_REQUIRED_DTI_TAGS`, every gate, and every rule/tag/spec are untouched;
`ACTIVE_RULE_IDS` unchanged; full suite green (2371). Reported for LP-376: `subject_key` is not human-legible
(a compact subject label needs per-family logic — a finding, not faked); Tab 5 is two legacy systems; Tab 4
(`not_applicable`) has no persisted rows. Cross-refs: §8, LP-316 (the Finding model), LP-364-B (the
discriminator), LP-374 (the traced $0.00 + DTI-reads-the-extraction), LP-318 (the gate), LP-376 (the UI),
LP-377 (§10 actions / blocking policy).

## ADR-292: The five §8 tabs + the provenance card — the subject-label + Tab-4 decisions (LP-376)

The §8 mapping (five outcomes → four governed tabs + the legacy quarantine) is the architecture, implemented,
not a decision. Two real decisions were forced in rendering it, recorded here.

**The subject label — the message is the identity; the raw content-id is never shown.** `subject_key` is an
opaque content-id (`txn54c6…`, a borrower UUID, or `"loan"`). A row nobody can identify is a row nobody can
action (LP-376), and a hash is not an identity. Decision: render the **message** as the row's identity (it is
ALWAYS present — the backend refuses to persist a reasonless verdict — and it differs per subject, so rows are
distinguishable), plus a compact **subject chip** derived from the load-bearing tags where a recognisable
value exists (`ruleSubjectChip`: AS-1's txn.amount+txn.date → "$20,000 · date"; a name/address tag; `"loan"` →
"Loan-level"), and NEVER the raw content-id. **Surfaced gap:** the rule NAME (`spec.name`) is not in the
payload — rows show `rule_id` ("ID-4"), not "Current address consistency". Reported for LP-377 (a small
`RuleFindingPublic` addition), not worked around by reaching into the backend.

**Tab 4 (Not applicable) is structurally empty — kept, explained, never fabricated.** `not_applicable`
subjects are not persisted (LP-375), so Tab 4 renders empty on every file. Decision: keep the tab (count 0)
with an honest empty state explaining WHY — because dropping it would let "not applicable" quietly absorb a
"couldn't check", which is the exact honesty violation §8's five-outcome split exists to prevent. Not
fabricated rows, not a hidden tab. This surfaced a model choice: because n/a isn't persisted, the UI cannot
show what a rule found irrelevant; if that ever matters, the backend must persist n/a — a decision, not a bug.

**Everything else is enforcement, not decision.** couldnt_check → Tab 1 only; Tab 3 ≠ Tab 4 (distinct empty
states); needs_review ≠ open (own group + a ratification marker); the two systems are two typed lists into two
tab sets, counts per-list and never summed; Tab 1 groups `open` first so 2 violations don't drown in 30
couldnt_check; the DTI card renders its gate ("Gated", the reason, "Unknown" lines) so the display agrees with
the engine; NO §10 actions on tabs 1-4 (LP-377). Frontend only — zero backend change; `ACTIVE_RULE_IDS` and
the legacy sweep untouched. Cross-refs: §8, LP-316, LP-375 (the two lists + the DTI gate), LP-329/330 (the
honesty contract), LP-333 (uniform couldnt_check), LP-377 (§10 actions).

## ADR-293: Governed rule findings carry their OWN category taxonomy, not the legacy sweep's (LP-376-B)

**Context.** The first human view of the LP-376 tabs showed ID-8 (a citizenship/eligibility rule) as
"Assets" and IN-2 (a pay-stub recency rule) as "Assets". Root cause: a governed rule finding's `category`
was the persisted legacy `FindingCategory` enum — `income/assets/credit/property/documentation/cross_source/
regulatory` — the AI cross-source SWEEP's taxonomy (it drives the legacy filter chips). That enum has **no
Identity and no Occupancy**, so a rule whose real family is Identity/Occupancy (from `rule_kinds.csv`) was
coerced into it, defaulting to `ASSETS`.

**Decision.** `RuleFindingPublic.category` is the rule's OWN category from its SPEC / `rule_kinds.csv` (the
gate of record) — Identity / Income / Occupancy / Assets / … — read at load time, NOT the coerced legacy
`FindingCategory`. The persisted column and the legacy sweep's use of it are unchanged.

**Why — the two systems are different things down to their vocabularies.** LP-375 quarantined the governed
rule engine from the legacy sweep as two distinct TYPES so their lists and counts can never merge. Their
CATEGORY taxonomies are just as distinct: the sweep classifies AI observations into a fixed handful of areas;
the rule engine has its own rule families (Identity, Income, Assets, Occupancy, Credit, Property, …). Forcing
the sweep's enum onto rule findings is the same merge LP-375 forbade, one field down — and it is exactly how
ID-8 became "Assets". So the governed findings carry their own family; the legacy findings keep theirs. A
shared `FindingCategory` enum with Identity/Occupancy added would be the alternative, but that couples the two
taxonomies again and touches the sweep — rejected in favour of reading the rule's own category from the gate
of record. Frontend renders whichever the API sends (no UI change).

Cross-refs: LP-375 (the two-type quarantine), LP-376/376-B (the tabs + the bug), `rule_kinds.csv` (the gate of
record for a rule's category + kind).

## ADR-294: couldnt_check reasons speak mortgage — a declared tag-label registry; the action's home; the untyped-doc collapse (LP-376-C)

**Context.** The first human view of the tabs (LP-376) surfaced right verdicts in unreadable words: every
`couldnt_check` reason was hardcoded in an evaluator interpolating an ENGINE id — a tag (`id.dob`), an
operand, a content-id hash — plus "source"/"subject"/"load-bearing tag". A loan processor reads these and
cannot act on them. The engine was honest; its vocabulary was not.

**Where human text lives (D1).** The evaluator (generic, one place per failure SHAPE) knows a fact is
missing; the DOMAIN (that the fix is "request the 1003") it does not know. Decision: a **declared
`tag_id → mortgage-noun-phrase` registry** (`rule_engine/reasons.py`, keyed by tag — the sanctioned
declared-key-resolved-by-registry pattern, never a per-rule-id branch) lets the evaluator name WHAT is
missing generically ("the borrower's date of birth could not be found in the file"); an unmapped tag
degrades to a humanized stem, so a raw dotted id or hash can never reach a processor. The ACTION stays
SHAPE-derived and honest — "classify it" (untyped document), "a consistency check needs at least two"
(<2 sources), "review it" (low confidence) — and is NOT invented where unknown (the <2-sources reason does
not guess which document to fetch). **An evaluator cannot name an action it has no domain knowledge of;**
per-rule domain actions belong in a spec's `how_to_fix` (precedent exists), authored as a scoped follow-up
for ~130 rules, not here. The tag id remains only in the provenance card (the engineer's view, LP-376).

**The engine was already right, and already knew the good sentence.** `absent_document_couldnt_check` already
composes "no title commitment is in the file — the rule requires one," and is SUPPRESSED, correctly, when ≥1
document is unclassified (LP-330: an untyped doc might BE the title commitment; claiming it is absent would be
a false-negative). The engine was being honest in a sentence nobody could act on, four times. This ticket
humanized that sentence; it did not touch the suppression.

**The untyped-document collapse: UI, not engine (D3).** Four unclassified documents each spawn a distinct
`(rule_id, subject_key)` couldnt_check for ID-7 and ID-9 (8 rows), and LP-322's reconciler keys on exactly
`(rule_id, subject_key)`. Collapsing in the engine would change those keys and break carry-forward/retire.
So the collapse is DISPLAY-ONLY: the UI groups findings sharing `(rule_id, message)` into one summary row
(expandable to the members). The model, the reconciler, and every verdict are untouched — this ticket changes
WORDS, not VERDICTS (audited; the failing tests were all string assertions).

**Cost / what's still open.** The subject a summary expands to is still a content-id, not a document a
processor recognises (LP-375's subject-label finding — mitigated, not solved). The 4 unclassified documents
are ONE root with THREE symptoms (ID-7/ID-9 noise, the suppressed good sentence, ID-4's poisoned filter,
LP-372) — the classifier gap is its own ticket; fixing it collapses all three at the source. Cross-refs:
LP-330 (absent-document contract), LP-375 (subject label + the two-type quarantine), LP-376/376-B (the surface
+ message-states-the-verdict), LP-372 (ID-4's gate), LP-322 (the reconciler key).

## ADR-295: The run wrapper's honesty — atomic status, visible enqueue failure, and an engine-aware cache key (LP-377)

**Context — the class.** The architecture spent ~20 tickets making every FINDING honest: gates, confidence
floors, `couldnt_check`, fail-closed calculators, `absent ≠ 0`. Then the RUN WRAPPER — the layer that reports
a verification COMPLETED — did not carry the contract up. LP-365 wired the governed rule pass alongside the AI
sweep on one run row, and its own review found three run-level fail-opens: (1) a "never overwrite FAILED"
guard that read a stale in-memory ORM `run.status` across sessions (a no-op); (2) a swallowed rule-pass
enqueue failure (a run reads COMPLETED with the governed pass never enqueued); (3) a cache keyed only on the
cross-source inputs, so a rule/spec/tag change with unchanged documents served a prior run's findings from a
version of the engine that no longer existed. **All three are run-level false-greens — the honesty contract
does not survive one layer up.** #3 already cost real time: LP-366/369/371/372/374 all landed after run
`01039e93`, documents unchanged → fingerprint matched → cache hit → neither pass re-ran → ~20 of 30
`couldnt_check` rows were already-fixed bugs, and a human concluded the engine was broken.

**#1 and #2 were already fixed (gate of record).** The LP-365 REVIEW commit (`0000088`, after the original
`a697cbb`) already made the status atomic and the enqueue failure visible. This ADR records the decisions;
LP-377's implementation is #3.

**Atomic status + the partial-failure status (#1).** An ORM in-memory `run.status` check cannot work: the
sweep and the rule pass write the row in SEPARATE task sessions, and SQLAlchemy does not auto-refresh across
sessions, so the sweep's in-memory status is stale (still RUNNING) even after the rule pass committed FAILED.
Decision: the sweep re-reads status under a ROW LOCK (`SELECT status ... FOR UPDATE`) immediately before its
write and sets COMPLETED only if the fresh DB value is not FAILED; the lock is held to commit, so the rule
pass's unconditional `UPDATE status=FAILED` serializes AFTER and stays sticky. **FAILED wins regardless of
commit order.** The run's status on partial failure IS **FAILED** — a run reads COMPLETED only if BOTH passes
completed. A COMPLETED run atop a dead governed engine is the false-green; the sweep's valid findings do not
rescue the wrapper's contract ("COMPLETED = the engine ran"). No new PARTIAL status is introduced (it would
touch the UI, the watchdog, `_build_status`, the version selector for no gain today) and **no UI change is
forced** — the existing FAILED surface + the force-run link handle it.

**Visible enqueue failure (#2).** The task's own fail-closed FAILED only fires if the task RUNS; an
un-enqueued rule pass (broker/worker down) never marks FAILED, so the sweep would complete the run with no
governed verification. Decision: `_enqueue_rule_engine` returns a bool and the handler marks the run FAILED on
an enqueue failure — mirroring `_enqueue_cross_source`. The two paths must fail in the SAME direction (toward
visible), never the direction that hides the problem.

**The engine-aware cache key (#3 — this ticket's build).** The fingerprint must bind the ENGINE's version,
not just the file inputs. Decision: fold an `engine_fingerprint()` into `compute_input_fingerprint` —
`sha256(engine_fingerprint ⊕ canonicalized cross-source context)`, where `engine_fingerprint()` hashes
`sorted(ACTIVE_RULE_IDS)` + the content bytes of every declarative artifact under `app/verification/rules/`
(the rule specs, `tag_production.yaml`, the fact/rule/tag/dependency CSVs, `vocabulary_extra.yaml`), cached
per process. A cache HIT now means "inputs AND engine unchanged → the prior run's findings are genuinely
current"; ANY declarative engine change misses and re-runs the governed pass.

**Why not the alternatives.** *Always-enqueue the rule pass:* rejected — LP-365 measured the rule pass at
~282s and ~$0.15–0.30 of AI per run (Stage A/B + materialization), and the task builds a fresh `TagCaches()`
every invocation (the tag cache does not persist across task runs), so re-running is full cost. Always-enqueue
would DOUBLE AI spend on every no-op Run — exactly what the cache exists to prevent. The rule pass cost is not
small; the ticket's "if it's cheap, always-enqueue" premise is falsified by the code. *A manual ENGINE_VERSION
constant / `app_version`:* rejected — `app_version` is a static `"0.1.0"`, never bumped; a manual constant
relies on a human remembering to bump it, the discipline that already failed five times. A key that can be
forgotten re-introduces the exact silent miss. **A cache MISS is cheap; a cache HIT that serves stale governed
findings is a false-green. The cache was built to avoid re-paying for the AI sweep; the rule engine has a
different cost profile. Caching two systems on one key was always going to break. Fail toward re-running.**

**The reported residual (not worked around).** The engine's Python-resident logic and the AI-group / judgment
prompts that live as Python constants (`tag_materialization/ai.py`, `subjects.py`, `ai/rule_judgment.py`) are
NOT hashed — a change to those with zero declarative edit would not invalidate. Mitigations: such changes
nearly always co-ship a spec/tag/registry edit (which does invalidate); the force-run link (LP-376-A) is the
manual escape hatch; and it is closable later by wiring `app_version` to the build/git-SHA or moving the
Python-resident prompts to files. This residual is strictly SMALLER than the prior behaviour, which ignored
the engine version entirely. Old runs' engine-unaware fingerprints will not match the new key → the next Run
re-runs, which is correct (they were computed under an old engine).

**The test that could not fail.** `test_sweep_completion_never_overwrites_a_failed_run` pinned #1 with a single
in-memory `SimpleNamespace(status=FAILED)` — a state that cannot occur cross-session — so it asserted a
scenario that can't happen and missed the one that can (the bug shipped WITH a green test). The review commit
replaced it with a test that models the guard as a function of the LOCKED DB value. LP-377 adds, for #3, a unit
test asserting the same inputs under a different engine hash to a DIFFERENT fingerprint and an endpoint test
that a rule-relevant change re-runs BOTH passes — both verified to FAIL on the pre-fix code (the endpoint
returns `completed`, the stale hit, instead of `running`).

**Cross-refs.** LP-365 (where all three shipped; the two-task wiring, the cost measurement), the LP-365 review
`0000088` (#1/#2 fixed + the masking test replaced), LP-376/376-C (the stale render that exposed #3), LP-78.1
(the original cross-source cache), LP-376-A (the force-run escape hatch), LP-322 (the reconciler keyed on
`(rule_id, subject_key)`).

## ADR-296: A finding names its subject — the label resolves in the read path, declared per subject type (LP-377-B)

**Context.** A governed finding's row identity was its ``subject_key`` — a stable content-id (LP-312): a
document ``doc067c…``, a transaction ``txn…``, a borrower UUID, or ``"loan"``. LP-376's provenance card
rendered ``Subject id: 59e173ce-…`` verbatim. A processor reads *"a document in the file could not be
classified"* — over 30 documents, WHICH one? The finding model knows exactly which; it just never said. Both
LP-375 (*"a legible subject label needs per-family logic, not uniformly derivable from the stored data"*) and
LP-376-C (*"the FILENAME is not reachable — subject_key is a content-id; no doc index at the reason site"*)
reported this wall and stopped at it. This ticket goes through it.

**Where the label resolves (D1) — the READ PATH, not the evaluator.** The deciding fact: the filename is NOT
in the snapshot. ``DocumentEntry`` carries ``content_id`` / ``document_type`` / ``belongs_to`` (borrower refs
with names) / extraction ``fields`` — but not ``original_filename`` (which lives only in DB
``Document.original_filename``). The evaluator holds only the snapshot and is DB-free, so option (a) — naming
the document in the evaluator's reason string — is impossible without plumbing a filename through the whole
tag/rule pipeline. The read path (``_build_status``) has DB access and the finding's ``subject_key``, so the
label resolves there: ``RuleFindingPublic`` gains a ``subject_label``, resolved once per finding with the
file's borrower + document maps. This fixes the row AND the card in one place, for ALL findings (old and new),
with nothing persisted.

**Declared per SUBJECT TYPE, dispatched on the key's SHAPE (D2) — no rule-id branch.** The subject TYPE is
the key, not the rule id, and the content-id prefixes are designed for exactly this dispatch:
``"loan"`` → "Loan-level"; ``txn…`` → "Deposit of $20,000 on 3/27" (from the inline ``txn.amount`` /
``txn.date`` tags — generalising LP-376's amount chip into ONE mechanism, retiring the frontend
``ruleSubjectChip``); ``doc…`` → the filename; a UUID → the borrower's name; ``account:…`` → "a bank account".
This is ``declared-key-resolved-by-registry`` again — a per-rule-id branch would be the anti-pattern.

**The document bridge — a shared derivation, never duplicated.** A document's content-id is a content hash
(irreversible), so the read path recovers ``{content_id → filename}`` by REBUILDING it from the current
documents via the SAME reshape+assign the snapshot uses (``documents_section._reshape_and_assign_ids`` —
extracted so ``build_documents_section`` and the map share it; duplicating it would let the ids drift and
silently resolve to nothing). Built only when a governed finding actually has a ``doc…`` subject.

**The honest fallback (D3) — never a hash.** A content-id rebuilt from the CURRENT documents will not contain
a removed or re-extracted document's id (a Tab-3 ``no_longer_applies`` finding's subject is gone BY
DEFINITION) → the label reads *"a document no longer in this file"*; a borrower who left → *"a borrower no
longer on this file"*. Never a fabricated name, never the id. This falls out of the rebuild naturally.

**PII posture (D4) — read-time, not persisted.** A filename can carry a borrower's name
(``Bansari_Patel_W2.pdf``). Resolving the label at read time means it is NEVER written into the finding row —
consistent with the existing posture (borrower names already appear in read-time finding messages;
``BorrowerRef.name`` is in the snapshot). This is the argument FOR the read-path option and against persisting
the label.

**The label is cosmetic; the key is identity.** ``subject_key`` stays the reconciler's key (LP-322 matches on
``(rule_id, subject_key)``) and is unchanged — the LABEL must never become the KEY. No verdict, outcome, tab,
or count changed; this ticket changes LABELS.

**Reported cost.** Resolving document labels rebuilds the documents section at read time (the only honest way
to recover a content-id → filename — the id is a content hash). Gated on a ``doc…`` subject being present.

**Cross-refs.** LP-312 (``subject_key`` / content-ids), LP-375 + LP-376-C (both reported this wall and
stopped), LP-376 (the provenance card + the amount chip generalised here), LP-322 (the reconciler key — the
label must not touch it), LP-330 (the absent-document contract behind the honest fallback).

## ADR-297: The LF-6T3N "classifier gap" was not one — 4 untyped documents, three unrelated roots (LP-377-A)

**Context.** LP-368 flagged (recommendation 5) that 4 documents on LF-6T3N were typed `unknown` and starved the
per-document `id.*` tags, and asked *"what those 4 are and why the classifier abstained."* LP-377-A framed them
as the single root behind ID-7/ID-9's 8 `couldnt_check` rows, the suppressed *"no title commitment is in the
file"* sentence, and ID-4's poisoned filter — *"fix the classification and all three collapse."*

**Decision: no classifier / catalog / prompt change — the premise was falsified by the data.** Reading the 4
documents from the live DB (with the classifier's confidence and the generic-analyzer's own words): (1) **"Akash
W2 Wells 2024.pdf"** produced **0 characters** of text → short-circuited to `unknown` at conf 0.0 without an API
call — an **extraction/OCR failure**, not a classifier one. (2) **"EMD wire receipt.pdf"** is a Wells Fargo wire
*request* for a *due-diligence fee* — `earnest_money_receipt` exists in the catalog but the match is
domain-ambiguous, and it is irrelevant to the three symptoms. (3)+(4) the two **"Home Value estimate"** files are
UWM **lender-dashboard screenshots** the model itself flagged as *"NOT a loan document or financial record for a
borrower"* — genuinely not borrower documents, for which `unknown` is correct and no catalog type should exist.
**None of the four is a title commitment, deed, or POA** — the documents ID-7/ID-9 need — and LF-6T3N genuinely
has none (verified: `title_commitment`/`power_of_attorney` absent). So typing the four resolves none of the three
symptoms, and for two of them it would require fabricating a type that should not exist.

**The asymmetric risk (the reason not to guess).** `unknown` is honest and BLOCKS — a `couldnt_check` a human
sees. A WRONG type is SILENT — it routes a rule at the wrong document and produces a confident verdict from the
wrong source, with nothing to catch it (LP-333's IN-8/IN-9 class). Eliminating `unknown` by guessing trades an
honest blocker for a false-green — strictly worse. **A classifier that never abstains fabricates.** `unknown`
stays first-class and reachable (already guarded by five tests).

**The suppression was NOT touched.** *"No title commitment is in the file"* is suppressed while any document is
untyped because an untyped document might BE the title commitment (LP-330). Two of the four are lender
screenshots that cannot be legitimately typed, so the suppression correctly persists. The engine's honesty was
never the bug.

**One root, three symptoms — disproven.** The three symptoms have three different, unrelated roots: (1) ID-7/ID-9
`couldnt_check` because the file genuinely lacks title/POA documents (not because of the untyped four); (2) the
suppressed sentence is correctly suppressed (LP-330); (3) ID-4's filter was settled by LP-372 —
`id.current_address_type = unknown` on **correctly-typed** property documents, not the untyped four.

**New gaps reported (each its own ticket, none fixed here):** the extraction/OCR failure on the text-less W2; the
real design question of a *"confidently not a borrower document"* state distinct from `unknown` (so a screenshot
does not masquerade as *"might be the title commitment"* and block a rule forever); and the domain (sister)
question of whether a due-diligence-fee wire request is an `earnest_money_receipt`.

**Cross-refs.** LP-368 (the census / recommendation 5), LP-372 (ID-4's gate — symptom #3, unrelated), LP-330 (the
absent-document contract), LP-333 (the wrong-type silent-failure class), LP-335/340/343 (the prompt-bug class — why
an unmeasured indicator change was not made), LP-376-C (the reason text that made the rows legible).

## ADR-298: The fourth fail-open — the governed pass has never been allowed to finish (LP-377-C)

**Context — the number was always there.** LP-365 measured the governed rule pass at **~282s** on a 30-document
file; `celery_app.py` set `task_soft_time_limit=120`. **Nobody put 282 next to 120.** Every normal run: the AI
sweep succeeds in ~65s and marked the run COMPLETED; the rule pass was killed at the 120s soft limit, retried
(each retry also timing out), exhausted, and its FAILED marker never landed. The result was a **COMPLETED run
with no governed output**, displaying stale findings from a prior FAILED run as current — and **every governed
count from LP-376 onward (the per-tab numbers, "AS-1's 15 couldnt_check cleared", LP-376-C's before/after,
LP-377-B's labels) was read off run `96f55e9d`, killed mid-flight.** Nobody has ever seen a complete run.

**Why every guard was individually correct and collectively blind.** LP-377 fixed three run-level fail-opens;
none models a timeout mid-execution. BUG 1 (the sweep's atomic status re-read won't overwrite FAILED) is
**moot** — nothing ever set FAILED, because the pass was killed before `_mark_failed` could commit. BUG 2 (a
failed enqueue marks FAILED) is **moot** — `.delay()` **succeeded**; the task was received and ran. The
`retry_or_terminal` → `_mark_failed` exhaustion path runs in **borrowed time after the soft limit already
fired**, so the hard limit kills the worker child before its commit lands. The stuck-RUNNING watchdog only
fired on a **RUNNING** run — which the sweep had already flipped to **COMPLETED**. And the read path showed
governed findings with **no run filter, no status filter**, under the latest run's status. Five correct
pieces, one invisible failure.

**Fix 1 — the runtime/limit mismatch (D1).** The ~282s is dominated by **sequential AI calls**: `materialize_tags`
awaits each of 6 AI groups in a `for` loop, each batching its subjects sequentially, run across every document
(the per-document id.* groups), plus Stage A/B. Reducing it (parallelize / gate groups to relevant doc-types,
LP-368 rec 4) is an ENGINE change — out of scope. So the lever is TIME: `run_rule_engine_pass` gets its OWN
`soft_time_limit=900` / `time_limit=1200` (the 65s sweep keeps the short global 120/180). Threading `TagCaches`
across task runs (LP-377's aside) was rejected — it dedupes only within a run, so the FIRST run pays full cost
regardless; not the lever. A file large enough to exceed even 1200s needs the engine-level fix (reported).

**Fix 2 — the run's status must depend on the governed pass (D2).** The **rule pass is now the completion
authority**: the sweep records its findings/counts/fingerprint and **leaves the run RUNNING** (it cannot know
the other half finished — marking COMPLETED alone was the fail-open); the rule pass marks COMPLETED **on its
success path**, under the LP-377 row lock (only if not already FAILED). A pass killed by the time limit never
reaches that line → the run stays RUNNING → the **watchdog** (timeout raised to **1500s**, above the rule
pass's hard limit) fails it. **Detection does not depend on the dying task committing anything** — the watchdog
owns it. A new `PARTIAL` status (the sweep's findings are valid) was **rejected** for blast radius (an enum
value rippling through the UI, the watchdog, `_build_status`, the version selector); instead the run reads
FAILED, the sweep's findings remain readable (LP-322 immortality), and Fix 3 makes the surface honest. No
schema migration.

**Fix 3 — the read path couples findings to run success (D3).** `_build_status` still shows ALL governed
findings (a `verification_id` filter would **gut LP-322's carry-forward** — a finding minted in run 1 and
carried into run 5 legitimately belongs to run 5). One honest signal is added: `rule_findings_stale` = the
latest run is not COMPLETED AND governed findings exist. The surface then says *"these rule-engine findings are
from an earlier run; the latest run's rule engine did not complete."* This forces a minimal frontend notice
(the D3 honesty; reported and built).

**What this invalidates.** Every governed count from LP-376 onward was partial-run output. The first complete
run's real numbers are recorded in `docs/tickets/LP-377-C.md` (reported, not predicted); LP-377-A survives
(it read the documents + classifier directly, not the findings).

**Cross-refs.** LP-365 (the ~282s measurement nobody compared to 120), LP-377 (the three blind guards + the
row-lock pattern moved here), LP-322 (the reconciler carry-forward Fix 3 preserves), LP-368 (the per-document
AI cost — rec 4, the engine-level capacity fix), LP-89 (the watchdog), LP-376/376-C/377-B (counts read off the
failed run).

## ADR-299: The dormant income/asset producers mostly work — except income_stability, which reorders Epic 1 (LP-378)

**Context.** The ~15 dormant income/asset rules (LP-333 bucket D) were believed "gated on calibration." But
calibration measures a tag's ACCURACY, presupposing it MATERIALIZES — and the income/asset AI groups had never
once run on real data (`_required_ai_groups()` requests only the groups a LIVE rule reads, and none of these is
live). LP-368 warned: *"calibration is necessary but may not be sufficient — the producers are unproven on real
data."* LP-378 forced the 6 dormant groups to run once on LF-6T3N (real sonnet-4-5, off-path, persisting
nothing) to find out.

**Finding — the pipe carries water on 5 of 6.** `income_amounts`, `income_employer`, `income_docs`,
`stmt_facts`, and `asset_facts` all materialize real, structured values on the doc-types they apply to (W-2 →
`$18,697.06` monthly; W-2 → `Wells Fargo Bank, N.A.`; bank statement → owner-match + reserve-eligible;
investment account → `$211,688.19` usable). Their dormant rules are **genuinely calibration-ready** — LP-379 is
well-aimed at them.

**Decision — `income_stability` is blocked on a PRODUCER GAP, not calibration, so it precedes LP-379.** It
produced **0 real values on 120 observations** — a 100% abstention. The cause is architectural, not a bug: it
is asked **per-document** a **cross-document** question (2-year history / decline / same-line-of-work / 3-year
continuance need the borrower's income documents across years, seen together), and a single W-2 or paystub
cannot evidence it (*"a single year does not evidence 2-year history"*). Calibrating a uniformly-`unknown` tag
measures nothing. **The 5 rules that read it (IN-7, IN-10, IN-11, IN-13, IN-14) need a per-borrower,
multi-document income-stability producer BEFORE Priya's time — this reorders Epic 1.** A second, smaller
finding: `income_amounts` **over-produces** a `documented_monthly` on non-income documents (mortgage statement,
property-tax bill, bank statement) — materializing ≠ correct; LP-379 must catch it or LP-377-D must gate the
group to income doc-types.

**Honesty preserved.** This proved the producers RUN and emit values on real data; it did NOT prove those
values are RIGHT (that is LP-379). A uniform-`unknown` group is reported as a finding, not a pass. The probe is
off the normal path (never imported by `verification_run`), used the real model, and persisted nothing — a
diagnostic, not an activation.

**Cross-refs.** LP-368 (the census / the warning this confirms), LP-333 (the dormant bucket), LP-377-C (the
first complete run — the baseline), LP-379 (Priya's calibration — well-aimed for 5 of 6, premature for
income_stability), LP-377-D (the per-document-group gate — fed this probe's doc-type data), LP-377-A (the
brokerage_statement extraction gap that starves asset_facts on that one doc).

## ADR-300: Per-document AI groups declare their doc-types and the dispatcher gates on them — fail-open (LP-377-D)

**Context.** A per-document AI structuring group runs on EVERY document and abstains where it doesn't apply
(LP-368: 95 abstention instances — each a paid call returning "no"). LP-378 upgraded this from a cost problem
to a CORRECTNESS one: `income_amounts` OVER-PRODUCED a confident `documented_monthly` on mortgage statements,
property-tax bills, and bank statements — documents with no income emitting income figures. If such a value
reaches IN-1 (stated-vs-documented income), it fabricates a discrepancy.

**Decision — declare `applies_to` per group; gate the dispatcher on it; FAIL OPEN.** Each per-document group
declares `applies_to: [doc_types]` (or `all`) in `tag_production.yaml` — the applicability that was always
IMPLICIT in the prompt's runtime "not my document" abstention, now DECLARED (the 13th
declared-key-resolved-by-registry). The materializer (`produce_ai_group_tags`) skips a document a group's
`applies_to` excludes — a redundant call, and for income_amounts a fabricated value. Generic: keyed only on
`group.applies_to` + the document's type, with **no group-id or doc-type branch** (a test asserts the gate's
source is free of both).

**The gate FAILS OPEN, layered — the only failure mode is a silently-dead tag, so every uncertainty runs the
group:** the reversibility flag is off (`GATE_AI_GROUPS=0`), the group is not document-subject, `applies_to`
is `all`, the document is typed `unknown`/`None` (LP-377-A's untyped documents — the classifier abstained),
or the type IS in `applies_to`. It ONLY removes a document whose KNOWN, confident type the group's list does
not contain. **The asymmetry is total: a redundant call costs a fraction of a cent; a skipped one costs a
silent-dead rule — the AS-1 / ID-2 / OC-2 class, four times this session. When unsure, wider.** The prompt's
own abstention remains the backstop on every kept document — the gate is an optimization ON TOP of the
existing safety, never a replacement (a test pins that a fail-open document the group shouldn't read still
gets an abstention, not a wrong value).

**`applies_to` derived from each prompt, verified against LP-378's real-value map.** `income_amounts` →
`[pay_stub, w2, uniform_residential_loan_application]`; `income_employer` → +`voe`; `stmt_facts` →
`[bank_statement, money_market_statement]`; `asset_facts` → `[investment_account, brokerage_statement,
retirement_account]`; `id_title`/`id_poa` → their narrow title/POA types. Deliberately kept `all`:
`id_name`/`id_address` (broad — any document with a name/address; feed LIVE auto-shipping ID-1/ID-4;
narrowing them is the silent-death risk), `income_docs` (presence signals), `txn_stage_a`/`occupancy`
(not document-subject), and **`income_stability`** (LP-378: it produces NOTHING per-document — gating masks
its real problem; LP-385 fixes the producer first).

**The confident-mistype residual (reported, not hidden).** The snapshot carries no per-document
classification CONFIDENCE (it lives on the DB `Document`, not `DocumentEntry` — plumbing it is a v5 snapshot
bump that breaks persisted v4, out of scope), so a document CONFIDENTLY mis-typed (a title document typed
`w2`) is gated by its wrong type and its group is skipped. Mitigated by the unknown fail-open + deliberately
wide lists; named in a test as the accepted residual, not silently absorbed.

**Cost & correctness.** The gate removes redundant CALLS and, for income_amounts, the OVER-PRODUCED GARBAGE —
never a legitimate verdict, tag, or confidence (equivalence-except-garbage, proven on LF-6T3N: every
legitimate tag identical, income_amounts' non-income `documented_monthly` gone). Single-file guarantee
(LF-6T3N is the only seeded real file) with the `GATE_AI_GROUPS=0` reversibility net for uncovered shapes.

**Cross-refs.** LP-368 (the 95 abstentions), LP-378 (the gate spec + the over-production), LP-377-A (the
classifier's failure modes + the no-confidence-in-snapshot gap), LP-377-C (the baseline), LP-334 (the
harness), LP-326 (declared production), LP-385 (the income_stability producer fix — why it is NOT gated).

## ADR-301: income_stability is a per-BORROWER group, not per-document — the subject was the bug (LP-385)

**Context.** LP-378 measured `income_stability` producing **0 / 120** on real LF-6T3N — a 100% abstention,
alone among the six dormant income/asset groups. ADR-299 diagnosed the cause as architectural, not a bug, and
reordered it ahead of LP-379's calibration: its four tags (`has_2yr_history`, `is_declining`,
`same_line_of_work`, `continuance_3yr`) each ask a **cross-document** question — an income TREND across years —
but the group was declared `subject: document`, so the producer saw **one document at a time**. A single W-2
cannot evidence a two-year trend. 0/120 was the honest producer being correct about a structurally impossible
question.

**Decision — move the group and its four tags to the `borrower` subject, and teach the borrower context to
gather the borrower's documents.** The LP-332 `borrower` subject already enumerates one subject per MISMO
borrower (keyed by the evidence-based `borrower.{n}.borrower_id` link) and already carries the whole snapshot.
The fix was one context-builder: `_borrower_context` now returns `{borrower_mismo, documents}` — this
borrower's MISMO facts PLUS every document **attributed to them by `belongs_to`** (the LP-202 evidence link).
The group sees ONE borrower's income documents **together**, which is exactly what a trend/decline/continuance
question needs. This is a generic **per-borrower-over-documents** primitive: any future borrower group asking a
cross-document question inherits it, with no new plumbing.

**Attribution is by evidence, never a guess (the LP-332/LP-336 invariant, preserved).** A document is gathered
for a borrower only if its `belongs_to` names that borrower_id. A document with no `belongs_to` is gathered for
**nobody** — the context is honestly incomplete and the tag abstains with a reason, rather than a trend
fabricated from a mis-attributed document. Each borrower's AI call carries ONLY that borrower's documents (a
test and the real probe both confirm no cross-feed — the masking class). PiiField values contribute masked
displays only; no raw PII enters the prompt.

**This is a PRODUCTION fix, not a CORRECTNESS one — the boundary held.** The rewritten prompt DEFINES the four
terms (`has_2yr_history` = ≥2 consecutive years evidenced; `is_declining` = a year-over-year decrease;
`same_line_of_work` = same field after a job change, single-employer → "yes"; `continuance_3yr` = likely to
continue 3+ years) with `unknown` first-class. **These definitions are defensible defaults flagged for Priya
(LP-379), NOT validated.** The Phase-3 probe (off-path, real sonnet-4-5, persisting nothing, on LF-6T3N) proved
production: `income_stability` went from 0/120 to **6 real / 8** — both borrowers got `has_2yr_history=yes`,
`is_declining=no`, `same_line_of_work=yes` from their own two W-2s, and `continuance_3yr=unknown` (correct —
W-2 employment states no horizon). Whether those judgments match a human golden is LP-379's job, unmeasured
here. A group that materialises is reported as materialising, not as passing.

**Reconciles with LP-377-D, does not contradict it.** ADR-300 deliberately left `income_stability` OUT of the
per-document `applies_to` gate ("gating masks its real problem; LP-385 fixes the producer first"). Now that the
group is `subject: borrower`, `applies_to` is dropped entirely — it is a per-document concept and the validator
rejects it on a non-document group. The document-type filtering `income_stability` needs happens inside
`_borrower_context` (it only reasons over the income doc-types among a borrower's attributed docs, per the
prompt), not via the dispatcher gate.

**The IN-10/IN-11 consumption gap (reported, not fixed).** Five dormant rules read these tags. IN-7/IN-13/IN-14
read them **per_borrower** — satisfied directly by the borrower-keyed tags. IN-10/IN-11 read `is_declining` /
`has_2yr_history` **per_document** — they now read a subject that no longer carries the tag, so they need a
per_borrower spec change to consume it. Out of scope (all five rules dormant); named for the rule owner, not
silently absorbed.

**Cross-refs.** LP-378 / ADR-299 (the 0/120 finding + the reorder this executes), LP-332 (the borrower subject
+ the evidence-attribution invariant), LP-202 (the `belongs_to` document→borrower link), LP-336 (never a
guessed attribution), LP-377-D / ADR-300 (why income_stability was left un-gated), LP-379 (the calibration that
validates the term definitions this ticket only defaults), LP-368 (the census that first flagged the borrower
context reading MISMO only).

## ADR-302: A tag that cannot express a risk makes the risk uncatchable — widen txn.apparent_category (LP-379-E)

**Context.** Calibrating LF-6T3N (LP-379), Priya labeled `txn.apparent_category` and reached for values the
enum (`payroll | transfer_own | gift | loan_proceeds | refund | interest | fee | vendor | unknown`) could not
hold: **third-party transfers** (*"Ravi transferred money to Akash"*, *"Akash transferred money to Anand
Patel"* — the enum has only `transfer_own`, the borrower's OWN accounts) and **payments to a creditor**
(*"Must be American Express CC payment"*, *"Some kind of mortgage payment — make sure this is not a monthly
obligation, if so should flag?"* — lumped into `fee`/`vendor`). Her *"should flag?"* is an underwriter
spotting a risk the system is STRUCTURALLY BLIND TO. **Where a tag cannot express a risk, no downstream rule
can ever catch it — the information dies at the tag layer.** This is a hole in what the system can PERCEIVE,
not how accurately it perceives.

**Decision — widen the enum with three Priya-PENDING defaults, defined once in the converged prompt.**
`transfer_third_party_in` (money in from a named third party), `transfer_third_party_out` (money out to a
named person/entity that is not a merchant or creditor), and `debt_payment` (a payment to an apparent
creditor). **These are DEFAULTS to confirm, not decisions taken** — an undefined category is LP-340's exact
bug (the model picks one meaning, the labeler another), so each is DEFINED in the prompt and every one is
flagged as a Priya item. The vocabulary lives in three places kept in sync: `fact_tags.csv` `allowed_values`
(generic-producer coercion), `APPARENT_CATEGORY_VALUES` (standalone-producer coercion), and the prompt; the
two prompt copies stay byte-identical under the LP-344 convergence guard (a test would go red on drift).

**D1 — the tag reports the OBSERVABLE; recurrence is a RULE's job.** *"Recurring obligation"* needs MULTIPLE
statements — a single-statement AI cannot see recurrence, and Priya's ground-truth descriptions were generic
(*"CARD PURCHASE / PAYMENT"* $14,316 → she inferred "American Express" from the AMOUNT + judgment, not the
text). So the honest tag is **`debt_payment`** — "a payment to an apparent creditor," observable when the
description names a lender/card/servicer — NOT the ticket's proposed `recurring_obligation`. A **future DTI
rule** detects recurrence across statements and sizes the undisclosed monthly obligation (noted here, NOT
built). The tag reports the payee-is-a-creditor fact; the rule judges recurrence (LP-335).

**D2 — gift/loan_proceeds are RULE conclusions, but they are load-bearing for dormant rules → kept, with the
simplification flagged.** A bank statement rarely SAYS "gift"/"loan_proceeds" — those are conclusions after
sourcing (AS-5 needs a signed gift letter; AS-2 an undisclosed-loan finding). By LP-335 the honest tag for an
inbound is `transfer_third_party_in`, and a rule decides gift-vs-loan. **But dormant AS-2 (`==loan_proceeds`),
AS-5 (`==gift`), and AS-12 read these values;** removing them would break those specs (out of scope). So they
are KEPT, the prompt reserves them for when the description ITSELF states a gift/loan (rare), and the full
simplification (gift/loan → rule conclusions, rewire AS-2/AS-5) is recorded as a Priya-item + future ticket —
a smaller, honest enum, once its dormant consumers are re-architected.

**D3 — no LIVE rule reads apparent_category, so widening shifts NOTHING live (structural, not just tested).**
The ticket's premise that `apparent_category` "feeds AS-1" is refuted by the gate of record: AS-1's
deterministic body reads `[is_money_in, amount, has_identified_source, source_strength]` and **never
`apparent_category`** (fact_tags.csv's optimistic "used_by_rules: AS-1,…" notwithstanding). Only DORMANT
AS-2/AS-5/AS-12 consume it. A test asserts no `ACTIVE_RULE_IDS` spec references the tag. The committed frozen
fixture tags are unchanged (the AI is NOT re-run here); a real off-path probe confirmed the AI now emits
`transfer_third_party_in` / `transfer_third_party_out` / `debt_payment` on named-payee descriptions (perception
gap closed) while `payroll` etc. are unaffected.

**Honesty preserved.** New categories are DEFAULTS flagged for Priya (not decided); recurrence detection is a
future rule (not built); gift/loan kept because their dormant consumers still need them (the simplification is
recommended, not forced); `unknown` stays first-class; the worksheet is NOT regenerated (it would destroy
Priya's in-progress notes — LP-379-D re-scores). This changes what the system can PERCEIVE, nothing it decides.

**Cross-refs.** LP-379 (Priya's calibration session — the source of the finding), LP-340 (undefined-term =
the model-vs-labeler bug these definitions avoid), LP-343 (the prompt-bug class + the exemplary Stage-A
prompt), LP-344 (the convergence guard the two prompt copies stay under), LP-314a (AS-1's source-strength
ladder — what AS-1 actually reads), LP-335 (the tag reports what the document SHOWS; the rule judges).

## ADR-303: A DB-sourced calibration worksheet for the human, alongside the fixture for CI (LP-379-D)

**Context.** The ticket's premise was that Priya labeled the REAL DB file (Akash Patel, real BofA statements)
while the harness scores the de-identified FIXTURE (Jordan/Taylor), so her labels share no `subject_id`s and
are unscorable. **The gate of record REFUTED this:** all 122 of her filled goldens join to the FIXTURE
worksheet 100% — she labeled the COMMITTED fixture CSVs, so her `subject_id`s ARE the fixture's. Two facts make
them scorable against the fixture: her TRANSACTION labels sit on VERBATIM transactions (the fixture reuses the
DB's real transactions unchanged — same content-ids, date/amount/description; only statement-level fields were
de-identified), and her DOCUMENT labels use the fixture CONTEXT (`id.name_normalized="Jordan A Rivera"`,
`documented_monthly=6500` = Jordan's data). Her notes name real people because she recognized them, not because
the row keys are the DB's.

**Decision — score her labels against the fixture NOW, and ADD a DB-sourced path for FUTURE real-document
rounds (never replacing the fixture path).** Scoring the stable-vocabulary tags against the fixture (real
reasoner): `txn.is_money_in` **98%** (49/50 — one real `in`-vs-`out` review case); `id.name_normalized`,
`id.current_address_type`, `income.documented_monthly`, `income.employer_normalized` **100%**;
`id.address_normalized` 0% — **not a model miss** but Priya's data-entry error (names typed into the address
column, already flagged in LP-379-A; the model output the correct addresses). This is the first REAL
calibration signal off a domain expert's labels.

**Held, explicitly.** `txn.apparent_category` (50 labels) and `txn.has_identified_source` (0) are HELD from
scoring via a named set (`HELD_FOR_RELABELING`), reported — never a silent skip. Her apparent_category labels
are FREE TEXT ("transfer to some one", "Credit card payment"); LP-379-E widened the enum (already committed),
so they can now be re-labeled to enum values — a mapping pass — before scoring. (The ticket's "hold until
LP-379-E lands" is moot — it landed; the hold is now for the re-label.)

**Two paths, clearly separated.** The FIXTURE path (`worksheet.py` + `build_lf6t3n_snapshot`) is the
deterministic, keyless CI path — UNTOUCHED (a new module carries the DB path, importing the same generator).
The DB path (`db_worksheet.write_db_worksheets`) reuses `build_snapshot` + the governed
`document_filenames_by_content_id` + `write_worksheets` — same generator, different snapshot source — for a
future round that labels the real DOCUMENTS (income/id), where the fixture is synthetic and her fixture-context
labels don't transfer. It is DELIBERATE: never called by CI or a normal run.

**PII containment (the serious constraint) — fail-closed, following LP-210.** A DB worksheet carries real
borrower NPI (names, addresses; accounts/SSNs are PiiField-masked). It MUST NEVER be committed. A guard
(`guard_pii_safe_out_dir`) refuses any output path inside the repo tree unless it is under a gitignored
`calibration-local/` segment — outside-repo or gitignored only, raising rather than writing PII to a
committable path; `.gitignore` covers `calibration-local/`. The generator only WRITES to that `out_dir`;
`build_snapshot`'s own logging is the app's existing behaviour (masked fields). A test proves the guard
rejects `docs/calibration/` and the write lands only under the given PII-safe dir.

**Honesty preserved.** The premise refutation is reported, not hidden (a test pins the 122/122 fixture join);
the held tags are held by a named set, not silently; `id.address_normalized` 0% is attributed to the labeler's
data-entry error, not the model; the DB worksheet is never committed and never the CI path.

**Cross-refs.** LP-345 (the live-reasoner path — scores real AI against fixtures/cases, does NOT build a DB
snapshot, so this reuses `build_snapshot` directly), LP-379-A/B/C (the fixture chain + the real-filename
`source_document` column she labeled against), LP-379-E (the widened enum the held apparent_category labels
await a re-map onto), LP-210 (the real-PII generated-locally posture this follows), LP-334 (the calibration
harness whose `summarize`/`failing_cases` produced these numbers).

## ADR-304: apparent_category is measurable only where the memo carries a payee — not a prompt bug (LP-379-F)

**Context.** LP-379-F mapped Priya's 50 free-text `apparent_category` labels onto the LP-379-E enum and scored
them — the tag's FIRST measurement against a domain expert's labels. The gate of record surfaced a decisive
constraint: **30 of the 50 labels sit on the SAME transaction memo — "CARD PURCHASE / PAYMENT"** — which
carries no payee. Priya gave those 30 eight different categories (credit-card payment, mortgage, a transfer to
a friend, an At&t bill, a fee…) from the AMOUNTS + the un-redacted file she opened via LP-379-C's real
filenames. LP-379-E's prompt CORRECTLY tells the AI to categorize from the payee in the description, NOT the
amount — so the AI cannot (and must not) reproduce her call. The memos are the AS-1 "PII-redacted transaction
memo": the redaction that protects PII also removes the payee signal apparent_category needs.

**Decision — score only where the DESCRIPTION supports the category; hold the rest, never guess.** The
mapping (`apparent_category_relabel.relabel`) is CONFIRMED only for description-supported labels and HELD
otherwise: 17 confirmed (payroll ×8 on "PAYROLL DIRECT DEPOSIT", interest ×4 on "INTEREST EARNED",
transfer_own ×4 on "ONLINE TRANSFER … OWN ACCOUNT", one inbound), 33 held (30 generic-memo, 2 uncertain, 1
typo). Scored: **accuracy 100% when concrete (16/16)** — the structuring layer is exactly right on the
categories the memo supports. The 17th (an inbound Priya knew was from "Ravi") the AI **abstained** on —
*"INBOUND PAYMENT RECEIVED is generic, provides no information about the sender"* — an HONEST abstention, not a
miss: the prompt working as designed.

**The finding: NO prompt bug — a DATA limitation.** apparent_category is unmeasurable on this file's redacted
memos for the widened categories (`debt_payment`, `transfer_third_party_*`); the AI correctly abstains rather
than guessing from the amount. Calibrating those categories needs transactions whose memos NAME the payee
(real bank descriptions like "AMEX EPAYMENT", "ZELLE TO ANAND") — which LP-379-E's own probe confirmed the AI
categorizes correctly. That is a calibration-DATA gap (a future ticket: descriptive-memo transactions, weighed
against the PII the redaction removes), not a prompt or model fix.

**Uncertainty preserved; her words preserved.** Where Priya wrote "not sure it's own transfer", the mapping
returns `unknown`, held — a golden never more certain than the labeler. The mapping is a scoring-time
TRANSLATION LAYER (`relabel`), applied to a copy at scoring; her committed free-text golden column is
UNTOUCHED — the strongest form of "preserve her words" (a test pins that "transfer to some one" etc. remain
verbatim in the worksheet). The proposed mapping is Priya's to confirm; the non-obvious 33 stay flagged.

**Cross-refs.** LP-379-E / ADR-302 (the widened enum + the "categorize from the payee, not the amount"
principle this validates), LP-379-D (the held 50 this scores; the fixture-join finding), LP-379-C (the real
`source_document` filenames Priya labeled against — how she saw the un-redacted payees), LP-335/340/343 (the
prompt discipline the 100%/honest-abstention result confirms is intact), AS-1 (the "PII-redacted memo" whose
redaction removes the payee signal).

## ADR-305: Activation bars — a declared, Priya-set decision surface; unmeasured ≠ low bar (LP-380)

**What an activation bar is.** The accuracy a rule's load-bearing AI tags must reach before the rule ships a
TRUSTED (auto, non-ratified) verdict. **It cannot be computed.** `is_money_in` at 98% may be plenty for a
large-deposit FLAG (a false flag → a human glances) and nowhere near enough for a rule that AUTO-APPROVES (a
false approval → a bad loan ships). The height is the COST OF ERROR for THAT rule — the FP-vs-FN asymmetry —
which is DOMAIN judgment. **Priya's.** LP-380 builds the decision surface and PROPOSES a defensible default per
rule (`validated: false`, the LP-379 priya_validated pattern); it sets no bar and activates nothing (LP-389).

**The honest state (reported, not a pass): of 23 inert rules, only 2 are calibratable-now.** `activation_bars.yaml`
classifies every inert rule: **calibratable-now (2)** — IN-1 (documented_monthly 100%), IN-5 (employer_normalized
100%) — a bar can be set + met; **not-calibratable-yet (14)** — a load-bearing AI tag is PRODUCED but UNSCORED
(income_stability, stmt/asset facts) or measured only in a different context (apparent_category is measured for
payroll/interest/transfer_own but UNMEASURED for the gift/loan_proceeds/third-party categories AS-2/AS-5/AS-12
actually read — LP-379-F); **needs-producer (1)** — IN-14's `occupancy.rental_support` has no declared producer;
**no-ai-dependency (6)** — parsed/deterministic rules with no AI gate (activation is a wiring decision, cf. active
IN-2/ID-8). The bar can be SET for 2 rules today; the rest are blocked.

**Unmeasured ≠ low bar — the load-bearing distinction.** A rule with an unmeasured tag is **BLOCKED ON
CALIBRATION**, not "sitting under a high bar it hasn't cleared." Conflating them ships a rule on a tag nobody
measured — the AS-1/ID-2 silent-death class, one level up. So `not-calibratable-yet` carries `threshold: null`
(the loader REJECTS a threshold on a non-calibratable rule) and `activation_mode` returns `blocked`, distinct
from a calibratable rule below its bar (`needs_review`). The two are behaviourally and visibly separate.

**Declared, not branched — the ~15th declared-key-resolved-by-registry.** A bar is a value attached to a rule
in `activation_bars.yaml`, loaded + validated once, resolved by data. `activation_mode(bar, accuracy)` is pure
and depends only on the bar's status/ships/threshold — NO per-rule-id branch in any evaluator (a test pins that
two rules with identical bar data get identical modes).

**One safety with LP-376-B, not a parallel one.** The bar and the ratification armor are the same guard, two
settings. `activation_mode` reconciles them: a judgment rule (`ships: ratify`) NEVER auto-ships (LP-376-B — a
human ratifies even at 100%); a calibratable auto-ship rule BELOW its bar routes to `needs_review`, not an
untrusted auto-ship; an unmeasured rule is `blocked`. LP-389 wires this into activation; LP-380 only declares it.

**Every default is Priya's to confirm** — the FP-vs-FN cost calls, the thresholds (0.98 for the fraud-adjacent
IN-1, 0.95 for IN-5), and the ratify-vs-auto question (IN-1 may warrant ratify-only despite 100% — one file,
one label set). `validated: false` on all; this ticket flips none. **A real finding for LP-389: only 2 rules
have a settable bar; the activation surface is mostly blocked on calibration, not on Priya's bars.**

**Cross-refs.** LP-379-D/F (the measured numbers + the apparent_category-unmeasured-for-gift finding this
consumes), LP-376-B (the ratification armor this reconciles with), LP-385/LP-378 (why income_stability /
stmt / asset tags are produced-but-unscored), LP-333 (the dormant-rule buckets), LP-389 (the activation pass
this feeds), the priya_validated threshold discipline (rule_kinds.csv) the `validated:false` pattern follows.

## ADR-306: The first activation pass is a DECLARED gate, not a list edit; ID-5 held on a subject mismatch (LP-389)

**What activated.** Two inert rules went live: **IN-1** (documented-vs-stated income shortfall; bar 0.98 auto,
Priya-validated; `income.documented_monthly` measured 100% at LP-379-D) and **IN-5** (employer consistency; bar
0.95 auto, validated; `income.employer_normalized` measured 100%). `ACTIVE_RULE_IDS` goes 11 → 13. This
SUPERSEDES the LP-333 IN-1 deferral (documented_monthly is now calibrated and the derived per-borrower producer
is fixed).

**Activation is a gate, not a hand-list — the load-bearing decision.** A rule goes live ONLY by passing
`activation_bars.is_eligible(bar)`, fail-closed: an AI rule needs a Priya-VALIDATED bar its MEASURED accuracy
clears (`measured_accuracy >= threshold`); a no-AI rule needs its parsed input VERIFIED to resolve to real
values **at the subject the rule reads**. Everything else — an unmeasured tag, an unvalidated bar, a missing
accuracy, an unresolved input, `needs-producer` — is HELD. `ACTIVE_RULE_IDS` stays an explicit list (the
foundational registry must not import the bar loader — a circular edge), but a test pins `set(ACTIVE_RULE_IDS) -
_BASE_ACTIVE == eligible_rule_ids()`, so a rule CANNOT enter the live set without meeting the gate, and the list
can never silently drift from the declared evidence. The bars carry two new fields — `measured_accuracy` (the
LP-379 number) and `input_resolves` (the verified-on-a-real-file bit) — both fail-closed defaults (None/False).

**ID-5 was PROPOSED and HELD — the gate caught a producer/consumer subject mismatch.** LP-381 reported ID-5's
parsed inputs (`id.id_expiration`, `contract.closing_date`) "resolve on LF-6T3N" — but at the **document**
subject: both are declared `subject: document` and materialize on the ID/contract documents (`dl1`/`dl2`/`pa1`).
ID-5 READS them at `tags.by_subject["loan"]`, so they never reach it and ID-5 couldnt_checks on **every** file,
not just LF-6T3N (its existing tests only pass because they hand-place the tags at `loan`). So `input_resolves`
is honestly **false**, the gate holds ID-5, and its subject model is a flagged follow-up — with two borrowers,
"which ID is the loan-level expiration" is a Priya call, out of scope for a deliberately small pass. This is the
declared gate earning its keep: a blind list edit would have shipped a rule that never checks anything.

**A derived load-bearing tag pulls its upstream AI group (the second wiring fix).** IN-1's load-bearing tag is
the DERIVED `income.documented_income_shortfall_pct`, which rests on the AI `income.documented_monthly`
(group `income_amounts`). `_required_ai_groups` previously pulled a group only when the DIRECT load-bearing tag
was AI — so IN-1 would have couldnt_checked forever (its AI input group never ran). Fix: an active rule's
activation-bar `load_bearing_ai_tags` (which declare exactly the upstream AI a derived tag rests on — IN-1's bar
names `income.documented_monthly`) are folded into the required set. `income_amounts` + `income_employer` move
from dormant to live; the dormant probe's set shrinks 6 → 4 accordingly.

**Phase 2 — the real run on LF-6T3N (reported, not predicted).** IN-5 → **SATISFIED** on both borrowers (resolves
end-to-end). IN-1 → **couldnt_check**, root: that fixture's MISMO carries no borrower STATED income; the AI
documented side is calibrated and the chain is correct, so it resolves on a file that states income — a DATA
gap (the LP-381/382 derived-input-absent class), not a defect, and not a bar to activating an AI-accuracy-gated
rule. ID-5 → couldnt_check, root: the subject mismatch above (held).

**Cross-refs.** LP-380/ADR-305 (the bars this reads through `is_eligible`), LP-379-D (the 100% measurements that
clear IN-1/IN-5's bars), LP-381 (the ID-5 "input resolves" claim this refines to the subject level; the no-AI
input-resolves pattern), LP-382 (the derived-input-absent-on-LF-6T3N class IN-1's couldnt_check belongs to),
LP-333 (the IN-1 deferral this supersedes), LP-376-B (the ratification armor `activation_mode` reconciles with).

## ADR-307: ID-5's structural-dead subject mismatch — fixed per-borrower; the fifth instance (LP-389-A)

**The bug (a fifth structural-dead instance — the AS-1/ID-2/OC-2/LP-321a class).** ID-5 ("the government photo
ID must be unexpired at closing") read `id.id_expiration` + `contract.closing_date` at
`tags.by_subject["loan"]`, but both are declared `subject: document` and materialize on the ID/contract
DOCUMENTS (`dl1`/`dl2`/`pa1`). They never reach `"loan"`, so ID-5 couldnt_checked on **every** file — LP-389
found this and held it. Its tests were green only because they **hand-placed the tags at `"loan"`** (a fixture
asserting a fiction, LP-321a): the rule "passed tests" and was structurally dead.

**Priya's decision: ID-5 checks EVERY borrower's ID — per-borrower, one verdict each** (a file with 2 borrowers
→ 2 ID-5 findings, one per driver's licence). Not "the earliest expiration," not loan-level — per-borrower,
mirroring LP-385's income move (document→borrower).

**The shape: reuse LP-385's per-borrower-over-documents attribution — the tag stays a document fact, the
CONSUMPTION becomes per-borrower.** `id.id_expiration` STAYS `subject: document` (a DL's expiration *is* a
document fact). A new derived **borrower**-subject tag `id.borrower_id_expiration` promotes it: the recipe reads
`id.id_expiration` from the driver's-licence `belongs_to`-ATTRIBUTED to that borrower (LP-202/332), reusing the
extracted `_borrower_attributed_documents` primitive shared with `_borrower_documented_monthly` — one
attribution mechanism, not two. ID-5 re-scopes to `subject_enumeration: per_borrower` and reads that
borrower-subject tag against the loan's closing date.

**The closing date — a gate-of-record correction.** The ticket assumed `contract.closing_date` was loan-level;
it is `subject: document` (materializes on the purchase agreement). To honor both the intent (one loan-level
closing date each borrower is checked against) and "do not change `contract.closing_date`," a new derived
**loan**-subject tag `contract.loan_closing_date` promotes it (mirroring `housing.insurance_monthly`'s
document→loan promotion); ID-5 reads it via a `loan_tag` operand. `contract.closing_date` itself is untouched.

**Fail-closed, per-borrower isolation, doc-type scoping.** A borrower with no attributable driver's licence →
`unknown` ("no driver's licence found for this borrower") → couldnt_check, never a guessed pass; ID documents
that disagree on the expiration → `unknown` (ambiguous), never a silently-picked date. One borrower's ID never
satisfies another's check (the LP-332 masking class). The promotion is scoped to `drivers_license` — because
`id.id_expiration` is not doc-type-scoped (`homeowners_insurance` also emits an `expiration_date` field), an
unscoped read would leak a policy's expiry into an ID check.

**The fiction-asserting tests rewritten to the true path (LP-321a).** `test_typed_operands` and
`test_identity_family_eval` placed ID-5's tags at `"loan"`; both now place the derived tags at the TRUE subjects
(borrower + loan) with a `belongs_to` document so the per-borrower enumerator yields the borrower. A new
`test_id5_per_borrower_lp389a` pins the full documents→`materialize_tags`→per-borrower-ID-5 path, the isolation,
the fail-closed reasons, and the doc-type scoping. A test that places a tag where the rule wrongly reads it hid
this bug for five rule-generations — it is worse than no test.

**Activation (earned this time): 13 → 14.** ID-5's input now resolves at the subject it reads, so its bar's
`input_resolves` flips true and the SAME LP-389 gate (`is_eligible`) admits it — the gate never changed, only
the evidence did. Phase 2 real run on LF-6T3N: **both borrowers SATISFIED** (DLs expire 2029-06-12 / 2028-02-28,
both after the 2026-07-15 closing). NB the ticket predicted a fire from different dates (2026-06-26 / 2027-08-03)
that the fixture does not carry; the fire path is proven with a synthetic expired DL instead.

**A reported limitation.** The per-borrower rule enumerates borrowers from documents' `belongs_to`, so a
borrower with ZERO attributed documents is not enumerated and gets no ID-5 verdict (inherent to LP-385's
document-driven shape). A borrower with *any* document but no DL IS checked (couldnt_check). Closing the
zero-document gap would need a MISMO-borrower-driven rule enumerator — a separate change.

**Cross-refs.** LP-389/ADR-306 (the mismatch this fixes + the gate that admits ID-5), LP-385 (the per-borrower
document→borrower shape reused), LP-321a (fiction-asserting tests), LP-332/LP-202 (borrower attribution /
`belongs_to`), LP-328 (the `date` typed operand + `loan_tag` operand ID-5 uses), LP-374 (`housing.insurance_monthly`,
the document→loan promotion precedent).

## ADR-308: A frozen base fixture + an extended sibling; the second activation pass; IN-3's misclassification (LP-384)

**The problem.** Five no-AI deterministic rules (AS-9, IN-4, AS-3, AS-10, IN-3) resolved `unknown` because
LF-6T3N lacked the documents they read — not because they are broken (LP-381/382/383 established the pattern).
LP-384 adds those documents, proves each rule's verdict, and activates what passes the eligibility gate.

**Decision 1 — a frozen base + an extended sibling, not a mutated base.** `build_lf6t3n_snapshot` is consumed
by many frozen tests (worksheet / eval traces that assert its exact 30-document shape). Mutating it to add
documents would break those consumers for reasons unrelated to what they test. So LP-384 adds a SIBLING
`build_lf6t3n_plus()` = the base snapshot + exactly three appended documents, each carrying a KNOWN, asserted
answer (the fixture has asserted a fiction five times — LP-321a/337/365/379-A/ID-5 — so every addition is
built to a provable catch, never "it resolved"):
* two VOEs with a DELIBERATE 77-day employment gap → **IN-4 FIRES** (beyond the 30-day window); a no-gap
  variant satisfies.
* one bank statement declaring "Page 1 of 5" with only 4 present → **AS-9 FIRES** ("a page is missing"); a
  complete statement satisfies. It joins an EXISTING account + month, so **AS-10 is undisturbed** (this
  document exercises AS-9 only).
The base is byte-identical; the extension only appends (a test pins that no existing document's tags change).

**Decision 2 — activate the three that resolve; the gate admits them.** AS-9, IN-4, and AS-10 pass the
eligibility gate (`input_resolves` flips true, verified on the fixture), so they enter `ACTIVE_RULE_IDS` via the
declared gate (not a hand-list): **14 → 17**. AS-10 needed no fixture change — it ALREADY resolves on the base
(the statements grew account identity + period dates as the fixture matured; LP-381's "input absent" went
stale). AS-3 stays HELD, fail-closed: its `calc.cash_to_close` recipe is a stub with no §3B cash-to-close
calculator (LP-383) — data cannot unblock it.

**Decision 3 (reported, not fixed) — IN-3 is misclassified as no-AI.** IN-3's load-bearing tag is the derived
`income.ytd_annualized_shortfall_pct`, but that recipe reads `income.documented_monthly` (AI, income_amounts)
alongside the parsed ytd_gross/pay_date. So IN-3 has a TRANSITIVE AI dependency — the same shape as IN-1 — and
cannot resolve from fixture documents alone (it abstains on "documented monthly income is absent"). Its
`no-ai-dependency` bar is wrong; it is an income-wave rule. LP-384 holds it (fail-closed) and its bar's
rationale now records the misclassification, to be reclassified (calibratable, via documented_monthly's 100%
measurement) when the income wave activates it. Not corrected here — reclassification is that wave's Priya call.

**Cross-refs.** LP-381/382/383 (the five stuck rules + their inputs), LP-389/ADR-306 (the eligibility gate this
activates through), LP-379-B (the fixture growth that made AS-10 already-resolve), LP-323-AS-B (the §3B
cash-to-close calculator AS-3 waits on), LP-333/369 (the field-name trap the added documents close).

## ADR-309: IN-10/IN-11 re-scoped per-borrower — the sixth structural-dead instance; a direct read, no recipe (LP-390-1)

**The bug (a sixth structural-dead instance — AS-1/ID-2/OC-2/ID-5/IN-12-class).** LP-385 moved the
income_stability tags (`income.is_declining`, `income.has_2yr_history`) to `subject: borrower` — income trend
is a cross-document question the AI answers over a borrower's income documents (LP-378 measured per-document at
0/120). But IN-10 (`is_declining`) and IN-11 (`has_2yr_history`) still read them `per_document` at the W-2
subject, where the borrower-subject tag never lives → **couldnt_check on every file, silently**, every test
green. LP-385 flagged it as its own ticket; this is it.

**The fix — a DIRECT read, simpler than ID-5 (no promotion recipe).** ID-5 (LP-389-A) needed a promotion
recipe because its source tag was `subject: document` and had to be lifted to the borrower. Here the tag is
ALREADY at the borrower subject (LP-385 put it there) — so the fix is a pure SPEC re-scope: IN-10/IN-11 become
`subject_enumeration: per_borrower`, drop the `document.document_type == w2` applicability, and read the
borrower-subject tag directly through the per_borrower enumerator's merged map (exactly how IN-1 reads its
borrower-subject shortfall). No new code, no recipe, no producer change. Fail-closed (a borrower with no
evidenced trend → the tag is absent/unknown → the gate couldnt_checks with a reason), per-borrower isolation
(one borrower's trend never feeds another's — the LP-332 masking class).

**Verified, still inert.** On the wired fixture with income_stability materialized, IN-10/IN-11 now reach REAL
per-borrower verdicts (a declining borrower → FIRED; a stable one → SATISFIED; unknown → couldnt_check-with-a-
reason) — the rule can now DISTINGUISH, where before it always couldnt_checked-because-empty. They stay INERT
(`ACTIVE_RULE_IDS` unchanged): the tags are AI and UNSCORED, so their bars are `not-calibratable-yet` — held
on CALIBRATION now (the income wave), not on the subject mismatch. The bar rationales are updated to record the
mismatch resolved.

**A reported additional instance (deferred, by scope).** IN-12 reads the SAME `income.has_2yr_history`
(borrower subject) `per_document` at the tax-return subject — the identical latent mismatch. It is out of this
ticket's scope (LP-390-2 audits the other income rules); reported here and in the ticket doc, its fiction test
left in place (still hand-placing the tag) until LP-390-2. IN-13 already reads its borrower-subject tag
per_borrower (correct).

**The fiction-asserting tests rewritten (LP-321a).** IN-10/IN-11's tests hand-placed the tag at the W-2/tax-
return DOCUMENT subject and asserted FIRED — green only because they wired the tag where the rule wrongly read
it. Rewritten to the true per-borrower path (the tag at `by_subject[borrower_id]`, a `belongs_to` document so
the enumerator yields the borrower), plus a test that the same tag at the DOCUMENT subject now couldnt_checks
(proving the rule no longer reads there) and per-borrower isolation.

**Cross-refs.** LP-385 (moved the tags to the borrower subject — the producer this consumes), LP-389-A/ADR-307
(the per-borrower fix pattern; ID-5 needed a recipe, this does not), LP-321a (fiction-asserting tests),
LP-332/LP-202 (borrower attribution), LP-378 (the 0/120 that proved per-document can't answer income trend),
LP-390-2 (the audit of the remaining income rules — IN-12 confirmed as the same class here).

## ADR-310: IN-12 + AS-5 are blocked-on-producer, not subject fixes; the income wave calibrates 12, not 14 (LP-390-2a)

**The finding.** LP-390-2's audit classed IN-12 and AS-5 as subject-mismatches (structurally dead). LP-390-2a
tried to fix them and found the gate of record disagrees: **neither is a subject fix — both are blocked on a
PRODUCER that does not exist.** Per the decision on the ticket, neither is fixed; both become producer subtasks.

**IN-12 — not the IN-11 fix.** IN-12 reads `income.has_2yr_history` per_document (tax_return); the producer is
at `subject: borrower`. A naive per_borrower re-scope (the IN-10/IN-11 fix) makes IN-12 fire IDENTICALLY to
IN-11 — both read the borrower's `has_2yr_history`, which is **income-type-agnostic** — collapsing the
self-employment rule into the variable-income rule. The LP-390-1 reviewer pinned exactly this (a `strict`
xfail). Keeping IN-12 self-employment-specific needs a **borrower-level self-employment signal**: `income.type`
has a `self_employment` value but is `subject: document` (not in the per_borrower map), and `income_stability`
produces no income-type tag. No such signal exists → blocked on a producer.

**AS-5 — a redirection with no linking tag.** AS-5 reads `txn.apparent_category` (a **transaction** fact) at a
`gift_letter` **document** subject. Its two sides — the gift letter (document) and the gift deposit
(transaction) — have **no linking tag**: no gift-letter-presence tag exists (only `voe_present` /
`offer_letter_present`, for income docs), and no loan-level gift-deposit-present signal exists. So no subject
choice makes both sides readable → blocked on a producer.

**Neither blocks Priya.** `has_2yr_history` already reaches IN-11 and `apparent_category` already reaches AS-2
(both calibration-ready), so fixing IN-12/AS-5 adds no new calibration target. **The income wave's calibratable
count stays 12 (LP-390-2), not 14.** The premise "two simple subject fixes" was wrong for both; they join
IN-14 / AS-7 as producer-blocked in the LP-390-8 fix list.

**Two producer gaps reported (LP-390-8):** (1) a borrower-level self-employment signal (promote `income.type`
to the borrower, or income-type-specific history) — unblocks IN-12 AND resolves IN-11's pinned over-fire (a
shared fix); (2) a gift-documentation signal (gift-letter-presence and/or loan-level gift-deposit-present) —
unblocks AS-5.

**Cross-refs.** LP-390-2 (the audit that flagged them), LP-390-1 (the reviewer xfail that pinned IN-12's
non-triviality; the IN-10/IN-11 fix this does NOT transfer), LP-385 (the borrower-subject income producer),
LP-379-E/F (the `apparent_category` widening + `gift` unmeasured on LF-6T3N), LP-323-IN-B (IN-11's pinned
set-membership over-fire, the same income-type gap).


## ADR-311: The first income-wave activation — AS-2 (auto) + AS-12 (ratify) go live; the AS-5 stray-flag fail-closed hardening (LP-390-7)

**The decision.** Activate exactly two AI rules through the eligibility gate: **AS-2** (earnest-money sourcing,
ships auto) and **AS-12** (borrowed-funds detection, ships ratify). Both had their load-bearing tags measured
against Priya's labels — `apparent_category` re-scored **100% concrete (n=17, LP-390-5a)** once the free-text
goldens were mapped to the enum, and `has_identified_source` **93.8% (n=16, LP-390-5)** — and Priya signed off
the proposed 0.90 bars. `measured_accuracy 0.938 >= 0.90` → the gate admits both. `ACTIVE_RULE_IDS` 17 → 19.

**Via the gate, not a hand-list.** Activation is `validated: true` in `activation_bars.yaml` PLUS the id in
`registry._LP390_ACTIVATED` — kept in sync by `test_activation_gate_lp389` (`ACTIVE_RULE_IDS − _BASE_ACTIVE ==
eligible_rule_ids()`). A rule cannot enter the live set without passing `is_eligible`.

**The real run (reported, not predicted; a point-in-time live run on LF-6T3N).**
- **AS-2 (auto): 0 FIRED** — it does NOT falsely fire (LF-6T3N has no `loan_proceeds` deposit, AS-2's trigger).
  15 satisfied + 2 needs_review on the 17 money-in deposits; 33 couldnt_check on the money-out transactions
  (Stage-B produces `has_identified_source` only for money-in, so a sourcing rule has nothing to check on an
  outflow — couldnt_check is the safe non-verdict, not a false pass).
- **AS-12 (ratify): 0 auto** — 16 needs_review (surfaced for human ratification, LP-376-B) + 34 couldnt_check.
  Every verdict routes to a human or is a non-verdict; it never auto-ships.

**The loan_proceeds n=0 caveat AS-2 ships with.** AS-2 fires on `apparent_category == loan_proceeds`, a value
that does not occur on LF-6T3N — so its specific trigger is UNTESTED. `apparent_category` is measured broadly
(100% concrete across payroll/interest/transfer_own/third_party), and `measured_accuracy` is recorded as the
weaker MEASURED gate (`has_identified_source` 0.938), not `apparent_category`'s 1.0, so the number does not
over-read the untested trigger. A file with a loan-proceeds deposit would strengthen it; Priya signed off
knowing this.

**The AS-5 stray-flag hardening (fail-closed).** The ticket warned of `AS-5: validated: true` while
`status: not-calibratable-yet, threshold: null` — a contradiction that would sign off a rule with no bar.
Against the gate of record it was already `validated: false` (LP-390-5a), and the loader ALREADY rejects the
scenario: `parse_bar` raises "only a calibratable-now rule may be validated" on any non-calibratable rule
(LP-380). So no data fix and no loader change were needed — the safety already exists. LP-390-7 PROVES it: a
test asserts AS-5 stays held and that `validated: true` on its null-threshold/not-calibratable state is a LOAD
ERROR, not silent eligibility. A mis-set sign-off cannot leak a rule live.

**Still held.** AS-5 (a DESIGN question — is `gift` a tag value or a rule conclusion, ADR-302 — plus gift n=0)
and IN-3 (calibratable-now but Priya has not signed its shortfall bar). Every other candidate fails the gate
(unmeasured tag / needs-producer / input absent).

**A reported observation (polish, not a blocker).** AS-2/AS-12 enumerate per-transaction and couldnt_check the
~33 money-out transactions (their sourcing tags exist only for money-in). An `is_money_in == in` applicability
filter (as AS-1 has) would trim that noise — a follow-up, not dangerous (couldnt_check surfaces nothing false).

**Cross-refs.** LP-390-5a (apparent_category re-score + the calibratable-now flip), LP-390-6 (the proposed
bars), LP-390-5 (has_identified_source measurement), LP-389/389-A (the eligibility gate + the two-step
activation), LP-380 (the bar mechanism + the loader's validated-only-on-calibratable guard), ADR-302 (the AS-5
gift-as-conclusion design question).


## ADR-312: The third rule state — applicable-but-manual: a blocked-but-applicable rule flags manual review instead of silence (LP-391)

**The problem.** A BLOCKED rule (not in `ACTIVE_RULE_IDS` — uncalibrated tag / missing producer) runs NOTHING,
so a file that qualifies for it produces SILENCE. For real-file testing (a processor on staging), silence reads
as "checked, nothing found" when it is really "didn't look" — a real gift / NSF / reserve / income-trend issue
passes unnoticed. But a blocked rule genuinely cannot ship a TRUSTED verdict (that is why it is blocked).

**The decision — a THIRD rule state.** Between **live** (a trusted verdict) and **inert** (silence) sits
**applicable-but-manual**: a blocked rule that is APPLICABLE to a file surfaces to Tab 1 (Needs Attention) as an
explicit `PENDING_AUTOMATION` — "manual review — the automated check is not active yet" — WITHOUT shipping the
uncalibrated verdict. The honest middle between silence and a wrong finding.

**The applicability-vs-verdict line (the crux).** Applicability ("this file HAS an income trend / reserves /
gift letter") is safe to detect; the VERDICT ("this income IS stable / these reserves ARE sufficient") is the
uncalibrated judgment that must NOT ship. LP-391 detects the former and discards the latter.

**The generic, declared mechanism (no per-rule branch).** Evaluate each blocked candidate rule (generic:
activation-bar candidates minus the active set) with the SAME dispatch the live rules use. Where it reaches a
VERDICT (satisfied / fired / needs_review — applicable + data present, but untrusted) its would-be verdict is
DISCARDED and a `PENDING_AUTOMATION` flag ships instead, carrying NO load-bearing tag values (no leak). Where it
`couldnt_check` (data / producer absent — AS-7's NSF, IN-14's rental support) or `not_applicable` (out of
scope) it stays honestly DARK — no fabricated flag it cannot support.

**The can-surface vs cannot-surface-yet split (empirical, on LF-6T3N).** Surfacing NOW: the per-borrower income
rules whose tags are produced — IN-7 (job change), IN-10 (declining), IN-11 (2yr history), and (on the extended
fixture) IN-8. Staying dark until their producer / data exists: AS-4 (reserves calc gated), AS-7 (no NSF
producer), IN-13 (continuance unclear), IN-14 (rental_support has no producer — LP-390-2a), and the document
rules AS-5 / AS-11 / IN-12 (no gift-letter / retirement-account / tax-return document on this file). The line is
NOT the ticket's per-rule guess — it is whether the rule reaches a verdict, which the gate of record decides.

**Materialization cost, isolated.** A blocked rule can only reach a verdict if its tags are materialized, and
production materializes only the LIVE rules' AI groups. So the pending-check pass materializes the blocked
rules' groups too — the deliberate extra AI cost of honest surfacing — but on a THROWAWAY snapshot copy,
BEST-EFFORT: a blocked/uncalibrated group can never flip `run.degraded` or leak its tags into the persisted
snapshot, and a failure yields no flags rather than failing the run. The live pass and the persisted snapshot
are byte-identical to before.

**The house rule holds — this NEVER ships an uncalibrated verdict.** A `PENDING_AUTOMATION` flag is not a
verdict: it carries no satisfied/open, no confidence, no load-bearing tag values. `ACTIVE_RULE_IDS` is
unchanged (a blocked rule is NOT activated as trusted) — the third state is distinct from activation.

**The surface.** A new `EvaluationOutcome.PENDING_AUTOMATION` (Verdict + outcome + a Tab-1/YELLOW mapping) and a
distinct frontend label ("Manual review") — visually unmistakable as "not yet automated", never aliased with a
real `needs_review` (a judgment worth ratifying) or `couldnt_check` (a data gap) or `satisfied` (a pass).

**Cross-refs.** LP-390-2 (the blocked/wiring audit) and LP-390-5/5a (what is measured) — which rules are
blocked and why; LP-390-8 (the producers the cannot-surface-yet rules — AS-7's NSF, IN-14's rental support —
still need); §8 (the outcome model / the tabs). The path to a real verdict replacing a manual-review flag is
calibration (a Priya-signed bar) or a producer, per each rule's LP-390 status.


## ADR-313: Name-match goldens do not carry from the de-identified fixture to the real-DB worksheet — some of Priya's labels need re-doing on real data (LP-392)

**The context.** LP-392 generates Priya's labeling worksheet from the REAL loan file (real identities, masked
here), because the committed worksheet's context showed the DE-IDENTIFIED fixture (Jordan A Rivera / First
Springfield Bank) while she validates against the real PDFs — so the two didn't line up and
`stmt.owner_matches_borrower` ("does this account holder match the borrower?") was unanswerable. The real-DB worksheet is LOCAL + gitignored (real PII, never committed); the committed fixture
worksheet is untouched (CI).

**The finding — a name-match golden cannot safely carry.** Priya's 159 committed goldens join to the real-DB
worksheet by the stable `(tag_id, subject_id)` key: **121 carry** (transaction + bank-statement rows share
content_ids with the DB), **33 drop** (fixture-only subject_ids — the DL / investment / pay-stub / W2 rows,
whose DB content_ids differ), and **5 are FLAGGED for re-label**: `stmt.owner_matches_borrower` on the five
bank statements. Its subject_id MATCHES the DB, so it WOULD silently carry — but its meaning is a name-match,
and a fixture 'yes' (Jordan==Jordan) is NOT evidence the real account self-matches. Carrying it would ship a
now-possibly-wrong golden into a real-context row.

**The decision.** A tag whose golden's MEANING depends on the (now-changed) identity context is NOT carried on
the real-DB path — it is BLANKED and FLAGGED for re-label (`worksheet.write_worksheets`'
`relabel_on_context_change`; `db_worksheet.RELABEL_ON_REAL_CONTEXT = {stmt.owner_matches_borrower}`). Visible,
never a silent carry. The fixture path (empty relabel set) is byte-unchanged.

**What it affects.** `stmt.owner_matches_borrower` was MEASURED in LP-390-5 (5 bank statements, 100% abstain —
the producer can't see the borrower names, LP-390-6's AS-6 finding). Those goldens were labeled on the
de-identified fixture; on real data Priya must RE-JUDGE them. So the AS-6 calibration record rests on
fixture-context goldens that need redoing — reported here so a future AS-6 activation does not lean on a golden
whose real-data answer is unconfirmed. (The 33 dropped rows — DL/investment/income mechanical labels — also
need filling on the real worksheet; those are absence, not a wrong carry.)

**Scope note.** The de-identified NAME/ADDRESS mechanical goldens (`id.name_normalized`,
`id.address_normalized`) would ALSO be wrong in a real row, but they DROP anyway (their DL subject_ids don't
match the DB) — so no carry, no flag needed. Only `owner_matches_borrower` both matches by key AND depends on
the identity, so it is the one that must be actively re-flagged.

**Cross-refs.** LP-379-D (the DB worksheet path + the PII guard), LP-390-3/3a (the worksheet finalization +
the prior 71-label DB copy), LP-390-5/6 (the `owner_matches_borrower` measurement + the AS-6 producer/context
finding this partly rests on), the LP-210 PII posture (real-loan artifacts generated locally, gitignored).


## ADR-314: The scenario-fixture pattern — a standalone, scenario-driven snapshot for thin-n calibration, never merged into the realism anchor (LP-393-1)

**The problem.** Six rules (IN-7, IN-10, IN-11, IN-12, IN-13, AS-11) are blocked purely on SAMPLE SIZE: their
tags are per-borrower and LF-6T3N has only 2 borrowers, so each caps at n=2 (AS-11 at n=3) — a smoke test, not
a measurement (LP-390-5/6, confirmed on real data by LP-392). The wiring is fixed and the tags produce; the
ceiling is the FILE, not the code.

**The pattern.** Build a STANDALONE, scenario-driven snapshot per calibration wave —
`income_scenarios.build_income_calibration_snapshot`: ~11 scenario borrowers (+ D4 continuance probes) and 6
asset accounts, each at the MINIMUM viable structure for the tag it exercises. It is COMPLETELY SEPARATE from
LF-6T3N: own loan / borrower / content ids, never imported by (or importing) the LF-6T3N builders, asserted
both ways; LF-6T3N stays byte-unchanged. The two fixtures answer different questions — LF-6T3N = "do rules work
on realistic data (real transactions, real structure)"; this = "scenario variety for measurement" — and
keeping them apart lets each number be reported separately (more informative than one blended one). Merging
scenario borrowers into the realism anchor would destroy its realism and break its frozen tests.

**Why Level 1 (a synthetic snapshot, not generated PDFs).** What is blocked is the AI's REASONING about income
scenarios (a 2-year trend, a decline, a line-of-work change). Document EXTRACTION is separately calibrated
(documented_monthly / employer_normalized both 100%, LP-379-D), so re-testing it through fake PDFs buys nothing
here. The snapshot varies EXACTLY the fields the group reads (`tax_year` + `wages_tips_other_comp` for
history/decline; `employer_name` + an occupation field for same_line_of_work; a stated income END for
continuance_3yr), verified against the prompt/context builder, not assumed.

**The synthetic-data caveat.** A tag validated on this fixture is validated for REASONING, not for robustness
to real-document messiness (OCR noise, odd layouts, missing fields). LF-6T3N covers realism; this covers
scenario breadth. **A bar set on a number measured here must carry that caveat** — pair it with the LF-6T3N
smoke result, never treat the scenario n as a full production validation.

**Clear-cut vs ambiguous (anti-anchoring, LP-337).** The clear-cut scenarios (B3-B8) have a KNOWN expected
answer, recorded in `CLEARCUT_EXPECTATIONS` for the probe + tests — NEVER written to a worksheet. The ambiguous
scenarios (B9-B13) carry NO encoded answer anywhere a labeling worksheet could surface it: Priya labels them
blind and HER label becomes the definition (is a 2% drop "declining"? is a promotion "same line of work"? does
a partial 2nd year count?).

**The probe (real model, off-path, reported not asserted — the model is non-deterministic).** Per-tag
non-unknown n on the scenario snapshot: `has_2yr_history` 13, `is_declining` 11, `same_line_of_work` 12,
`asset.liquidation_terms` 6 — all >= 6, the thin-n ceiling broken for IN-7/IN-10/IN-11/AS-11. All six clear-cut
checks PASSED (B3 declining=yes, B4 no, B5 history=no, B6 yes, B7 same-line=yes, B8 no). TWO honest gaps remain
(NOT solved by n):
- **continuance_3yr stays thin (n=1).** Standard W-2 employment honestly yields `unknown` (LP-385); only a
  fixed-term VOE with a stated end (B14) produced `no`. So IN-13 is blocked on more than sample size — it needs
  fixed-term/other-income variety AND `income.type` (a different producer, income_amounts), not just borrowers.
- **IN-12 is not exercisable here.** It needs `has_2yr_history` for a SELF-EMPLOYMENT (tax_return) borrower,
  but income_stability reads only w2/pay_stub/voe/1003 — a tax-return-only borrower yields `unknown`. IN-12
  stays blocked on the producer gap (LP-390-2a), not on n.

**Cross-refs.** LP-390-5 (the thin-n finding), LP-392 (the ceiling confirmed on real data), LP-384 (the
scenario-extended-fixture precedent, `build_lf6t3n_plus`), LP-385 (the per-borrower income producer + its
context builder), LP-337 (anti-anchoring), LP-390-2a (the IN-12 producer gap).

## ADR-315: Priya's scenario corrections — two prompt/label fixes, one confirmed-correct prompt, and the stale-golden trap (LP-393-4 / 4a)

**Context.** LP-393-4 scored the AI against Priya's blind scenario labels and drew three "definitional
divergence" findings. On review she CORRECTED them: two were label slips / an inverted reading, one was a
FIXTURE defect. LP-393-4a applied her 5 label corrections, fixed the fixture + one prompt, and re-scored.
**LP-393-4's scores are SUPERSEDED by the re-score below.**

**is_declining — no materiality gap; it was a label slip → 100%.** LP-393-4 read B9 (−2%) as "the AI over-calls
any drop declining." Priya's B9 label was a SLIP (`no` → **`yes`**): she agrees any year-over-year decrease is
declining. Corrected + re-scored, is_declining is **100% (13/13)**, clear-cut passes. No prompt change. →
**IN-10 ready for a bar.**

**asset.liquidation_terms — the finding was INVERTED; the AI UNDER-restricts → 100% after the prompt fix.**
LP-393-4 read "the AI over-discounts, Priya says fully_liquid." **Backwards.** Priya says a retirement account
with early-withdrawal PENALTIES — 401(k), IRA, Roth, INCLUDING a fully-vested one — is `restricted`, not usable
at face for reserves; the AI was calling those `vested_usable` (UNDER-restricting) and she had 3 labels slipped
to `fully_liquid`. **Her precedence rule (the tag's definition):** (1) PARTIAL vesting present → `vested_usable`
(the partial vesting governs); (2) else PENALTIES present (even fully vested) → `restricted`; (3) else →
`fully_liquid` (brokerage/taxable). LP-393-4a encoded this in the `asset_facts` prompt and corrected the 3
labels; re-scored, liquidation_terms is **100% (6/6)** — restricted (2 Roth + the fully-vested 401(k)),
fully_liquid (2 brokerages), vested_usable (the graded 401(k)). → **AS-11 ready for a bar.** (This explains the
LP-390-5 Roth signal: the AI was under-restricting all along.)

**same_line_of_work — a FIXTURE defect, not a definitional divergence; the prompt was RIGHT.** LP-393-4's 38%
was because 7 scenario borrowers had NO `occupation` field — Priya marked those rows `unknown` "No occupation
given." Her rule confirms the prompt: **"no job change → yes"** (one employer AND unchanged occupation = `yes`).
LP-393-4a added a realistic, unchanged occupation to every such borrower — **no prompt change** (the prompt was
correct).

**THE STALE-GOLDEN TRAP (a real finding — reported, not explained away).** After the fixture fix,
same_line_of_work did NOT improve — it went 38% → **31%**. Root cause: Priya's goldens were labeled on the
occupation-LESS worksheet (her `unknown` = "no occupation given"), but the re-score runs the AI on the
occupation-PRESENT fixture. So the fixed AI (now `yes`, "same employer + same occupation, no job change" — which
MATCHES her stated rule) is scored against her STALE `unknown` labels. The number is invalid: fixing the
fixture invalidated the labels made on the old one. **same_line_of_work needs a RE-LABEL round on the
occupation-present worksheet before it can be measured** — its prompt is confirmed correct, and by her rule the
AI's no-change→`yes` answers are likely right, but that is HER call, not a re-derivation here. → **IN-7 stays
blocked on a re-label**, not a prompt fix. (Process lesson: a fixture fix mid-calibration stales the goldens
labeled on the old fixture — re-label before re-scoring.)

**The one OPEN framing question (has_2yr_history / B14) — her call, unchanged here.** B14 (Beacon, contract
ENDED 2026-06-30, two W-2s present): AI=`yes` (two years of history exist), Priya=`no` ("looks like currently
unemployed… need a new offer letter + a paystub"). Strictly the tag asks HISTORY (which exists); she answered
CONTINUATION. Both readings recorded; B14's label left AS SHE WROTE IT (`no`); the has_2yr_history prompt is NOT
changed — it needs her explicit ruling ("does a terminated job's two years still count as history?"). Otherwise
has_2yr_history is **85%**, clear-cut passes (B12 is her pay-stub-only-needs-a-W-2/1099 nuance). → **IN-11 ready
for a bar**, with B14 flagged.

**THE SYNTHETIC-DATA CAVEAT (LP-393-5's bars must carry it).** These validate the AI's REASONING on CLEAN
scenario data, NOT robustness to real-document messiness — pair any bar with the LF-6T3N real-data result (n=2,
indicative).

**Cross-refs.** LP-393-1 (the fixture), LP-393-2 (the blind-labeling instrument), LP-393-4 (the superseded
first scoring), LP-390-5 (the harness + the now-explained Roth signal), LP-337 (anti-anchoring).

## ADR-316: Priya's four rulings settle the scenario tags; validating a bar activates it (no decouple); a judgmental rule ships ratify despite an AUTO sign-off (LP-393-6)

**Context.** LP-393-5 proposed bars for the four scenario-calibrated rules (IN-7, IN-10, IN-11, AS-11) and left
four open items for Priya. She settled all four; applying them forced two structural decisions this ADR records.

**Ruling 1 — B14 framing (a definitional change to what `has_2yr_history` means).** *A TERMINATED job's two
years DOES still count as HISTORY.* `has_2yr_history` asks about HISTORY only; whether an ended job's income
CONTINUES is a different question. **Ruling 2 — the documentation standard is a SEPARATE check.** The
W-2/1099/offer-letter requirement (pay-stub-only needs a W-2/1099; a lapsed VOE needs an offer letter + a
paystub) is NOT part of `has_2yr_history`. These two rulings make IN-11's two recorded "misses" (B12, B14)
OUT-OF-SCOPE for the tag — the AI answered the tag's actual question correctly both times.

**Re-scored, never hand-edited.** At `measured_accuracy 0.85` vs a `0.90` bar, IN-11 failed its own gate. The
principled fix under the ruling: update B12 + B14's `has_2yr_history` goldens to `yes` (history exists in both),
**preserving her originals in the worksheet Note as the record of why they changed**, then RE-SCORE with the
real reasoner. It came out **100% (13/13)** — the number changed BY MEASUREMENT, not by asserting 0.85 → 1.0.
Editing a measurement by assertion is exactly the dishonesty the calibration system exists to prevent; had the
re-score not delivered, the lower number would stand (a finding, not a forced value).

**Ruling 3 — the four heights + the AUTO call, a named trust decision.** Priya confirmed IN-7 0.90 / IN-10 0.95
/ IN-11 0.90 / AS-11 0.90 and chose **AUTO for all four**, KNOWINGLY overriding the ratify-only recommendation
**on a synthetic-only basis** (measured on the clean LP-393-1 fixture; the only real-data check is LF-6T3N,
n=2). Each rationale records this as her deliberate override, with the synthetic caveat she accepted.

**Validating a bar ACTIVATES it — there is no validate-without-activate in this gate.** In this system
`is_eligible` is `validated ∧ measured ≥ threshold`, and `test_activation_gate_lp389` enforces `ACTIVE_RULE_IDS
− _BASE_ACTIVE == eligible_rule_ids()`. So flipping `validated:true` on the four (with measured ≥ bar) makes
them eligible, and the invariant requires eligible == active. Every prior sign-off (LP-390-7, LP-390-9)
validated + activated in one step for this reason. Geet chose to **validate + activate now** (ACTIVE 20 → 24 via
`registry._LP393_ACTIVATED`) rather than defer validation or redesign the gate to decouple approval from
eligibility. Their AI groups (`income_stability`, `asset_facts`) fold into `_required_ai_groups` automatically
(it derives from `ACTIVE_RULE_IDS`), so every run now materializes them.

**The IN-7 judgmental-vs-AUTO conflict — reported, not forced.** `ships` derives from a rule's KIND, and
LP-376-B's armor is enforced at EVALUATION time (`judgment.py` hard-codes `ratification_pending` for a judgment
rule) — a judgment rule NEVER auto-ships. IN-7 is judgmental. Priya asked for AUTO, but a judgment rule cannot
be trusted to auto-ship, so **IN-7 stays `ships: ratify`**: it is active and surfaces every verdict to
needs_review for human ratification, regardless of the AUTO request. Making IN-7 truly auto would require
RECLASSIFYING its kind (`rule_kinds.csv` + the spec + LP-376-B's armor) — a separate ticket, NOT silently
bypassed here. The three calculative rules (IN-10, IN-11, AS-11) ship auto, matching both their kind and her
call.

**Two new candidate rules Priya's ruling spun off** (their own tickets, NOT built here): (1) *pay-stub-only →
require a W-2/1099* before using the income; (2) *lapsed/terminated employment → require an offer letter + a
pay stub* (the continuation check B14 pointed at). These are the "separate check" that Ruling 2 carved out of
`has_2yr_history`.

**Consequences.** `has_2yr_history` re-scored 100%; IN-11 clears its 0.90 bar; the four are validated + live
(ACTIVE 24). IN-7 ships ratify (surfaces, never auto) pending a kind reclassification. The synthetic-data caveat
rides every bar. The B12/B14 golden change is recorded with her originals preserved.

**Cross-refs.** LP-393-5 (the proposals), LP-393-4b (the measurements), LP-376-B (the ratification armor),
LP-390-7 / LP-390-9 (the validate+activate precedent), LP-389 (the eligibility gate + its invariant).

## ADR-317: The calibration wave found 0 of 4 calibratable — AS-7 is an orphan (needs-producer), and IN-8/IN-9/IN-13 need scenarios, not scoring (LP-395)

**Context.** LP-394's census classified IN-8, IN-9, IN-13, AS-7 as `needs-calibration` — "the cheapest remaining
rules-per-ticket win." LP-395's Phase 0 (establish the achievable n BEFORE labeling) found that **none of the
four is calibratable now**, correcting the census. No worksheet was generated; nothing was scored.

**AS-7 is a true ORPHAN → needs-producer (census wrong; LP-390-2 vindicated).** `txn.is_nsf_or_overdraft` is in
the vocabulary (`fact_tags.csv`, mode=AI) and is READ by the derived `stmt.nsf_count` recipe (`derived.py:558`,
which ABSTAINS when the tag is on no transaction) — but it is produced by **no path**: not in
`tag_production.yaml` (the declared layer), and not in Stage-B (`tag_correlation` emits only
`txn.has_identified_source` / `txn.source_strength`). The AS-7 bar's own rationale hedged ("aggregated from
txn.is_nsf_or_overdraft (AI), UNSCORED — verify the derived chain when calibrating"); the chain is broken at the
leaf. **AS-7's real blocker is a MISSING PRODUCER for `txn.is_nsf_or_overdraft`, not calibration.** This confirms
LP-390-2's orphan finding and reclassifies AS-7 `needs-calibration → needs-producer`.

**IN-8 / IN-9 / IN-13 are `needs-more-scenarios`, not `needs-calibration`.** Their tags produce, but no fixture
carries the discriminating scenario at n≥6 (the LP-393 thin-n discipline):
- **IN-8 `income.voe_present`** — labelable only on VOE / offer-letter documents (the worksheet capacity model);
  the scenario fixture has **3** VOE docs (lf6t3n 0, lf6t3n_plus 2), so **n=3 < 6**. Thin. (A secondary finding:
  the producer runs `voe_present` on ALL documents but the worksheet only labels VOE/offer-letter types, so the
  precision direction — does the AI false-tag a W-2 as a VOE — is not even in the labelable set.)
- **IN-9 `income.offer_letter_present`** — **no offer-letter document exists in any fixture**, so its positive
  class is empty (one-sided, like the AS-5 gift n=0 case). Not measurable until a scenario carries one.
- **IN-13 `income.continuance_3yr`** — produces 13 rows (enough by count), but every borrower carries only
  EMPLOYMENT income, where continuance is honestly `unknown` (LP-393-1 reached n=1 meaningful). The tag is about
  OTHER income (pension / child support / alimony — B3-3.1-09); no such borrower exists. Its second input
  `income.type` is also thinly measured (n=2, all `base`, in the LP-334 set) — though `income.type` is context,
  not the binding load-bearing tag.

**The fixture gaps this spins off (their own tickets, the LP-393-1 pattern — NOT built here):** (1) ≥3 more VOE
documents (and non-VOE income docs for precision) to lift IN-8 to n≥6; (2) an `employment_offer_letter` document
to give IN-9 a positive class; (3) other-income borrowers (pension, child support, alimony, award) to give
IN-13 a discriminating continuance signal. And separately, (4) a PRODUCER for `txn.is_nsf_or_overdraft` (a
Stage-B / statement AI classifier) to unblock AS-7.

**Consequences for the plan.** LP-394's roll-up said one calibration wave clears IN-8/IN-9/IN-13/AS-7 — the
cheapest written-rule win. **That win does not exist:** each of the four needs upstream work (a producer or a
scenario fixture) before any scoring. The corrected blocker classes: AS-7 → needs-producer; IN-8/IN-9/IN-13 →
needs-more-scenarios. The genuinely cheap calibration win among written-inert rules is now: **none** — the
next income-family progress needs a small other-income + VOE + offer-letter scenario fixture first, then a score.

**Cross-refs.** LP-394 (the census this corrects), LP-390-2 (the original AS-7 orphan finding), LP-390-3 (the
IN-8/IN-9 zero-rows-on-LF-6T3N finding), LP-393-1 (the continuance n=1 finding + the scenario-fixture pattern),
LP-393's thin-n discipline.

## ADR-318: stmt_facts never saw the borrower roster — owner_matches_borrower abstained on every file; a declared roster fixes it (LP-390-8a)

**The context gap (verified, not assumed).** `stmt.owner_matches_borrower` (AS-6's load-bearing tag) asks *does
this statement's account holder match a borrower on the loan?* — a COMPARISON. But the `stmt_facts` group runs
under the `document` context builder (`_doc_context`), which sends only the statement's OWN fields. It was never
given the loan's borrowers, so it **structurally could not compare** and abstained `unknown` on every file —
LP-390-5 measured it (5/5 abstain) and LP-396 re-verified it live (5/5 `unknown`, the AI's own reason: *"no
borrower names were provided in the loan"*). The abstention was the fail-safe working, not an AI error; the fix
is to supply the comparison data.

**The fix — a DECLARED roster, not a per-group branch.** A document group that must compare a document's stated
party against the borrowers declares `include_borrower_roster: true` (a new `AiGroup` field, guarded to
document-subject groups). The producer then computes the loan's borrower roster ONCE per run (reusing the LP-332
borrower resolution — `_borrower_enumerate` + PII-safe field reads, no second identity path) and merges
`loan_borrowers: [...]` into each subject's context, part of the content fingerprint. Only `stmt_facts` declares
it, so every other group's context is byte-unchanged (no `if group == stmt_facts` anywhere — the LP-326
vocabulary-driven discipline).

**The comparison shape (D2) — tolerant, flagged for Priya.** The prompt compares the holder against
`loan_borrowers` and is TOLERANT of harmless variation: a middle initial vs full/absent middle name ("Jordan A
Rivera" = "Jordan Rivera"), a nickname (Bob/Robert), a maiden vs married surname, and a JOINT account listing two
holders (a match if EITHER is a borrower). It answers `yes` (matches), `no` (a clearly different party — an
unrelated name, or a trust/LLC/estate not on the loan), or `unknown` WITH A REASON (ambiguous, or an empty/absent
roster — nothing to compare). **Over-strict is the DANGEROUS direction** (a false "not the borrower's account" on
a borrower's own joint statement), so the default leans tolerant; the exact strictness is a Priya call, not a
value set here.

**This makes the tag PRODUCE — correctness is the score.** The live re-score on LF-6T3N confirmed it now
produces a real comparison: BEFORE 5/5 `unknown` → AFTER **5/5 `yes` (100% vs the 8 existing goldens on the 5
bank statements)**, reasoning *"Account holder 'Jordan A Rivera' matches borrower 'Jordan Rivera' — the middle
initial…"*. `is_reserve_eligible` (the group's other tag, AS-4's own separate problem) was UNAFFECTED (the
roster is additive context, explicitly irrelevant to it — D4). **AS-6 is NOT activated** — it is now bar-ready;
a bar + Priya's sign-off + the gate activate it, not this ticket.

**The D5 scope mismatch (reported, not fixed).** The worksheet labels `owner_matches_borrower` on
`investment_account` docs (inv1–3), but `stmt_facts` runs only on `bank_statement`/`money_market` — so those 3
goldens are `unmatched` and can never be scored. The right fix is likely to widen `stmt_facts`' applicability to
the investment/brokerage statement types (they have an account holder too), NOT to narrow the worksheet — but
that is its own ticket (a doc-type scope decision), not done here.

**Cross-refs.** LP-390-5 (the original 100%-abstain finding), LP-396 (the live re-verification that this ticket
never landed), LP-385/332 (the borrower resolution reused), LP-335 (report-what's-shown, matched against the
given context). AS-4's `is_reserve_eligible` domain disagreement is separate and untouched.

## ADR-319: Surface name discrepancies + non-borrower co-holders as SEPARATE fact-tags, not a widened enum — the tag describes, the rule judges (LP-400)

**Priya's ruling (the driver).** A name difference on a bank statement (e.g. a middle initial) should NOT reject
the statement — the account IS the borrower's; it should FLAG for human attention while the document still
COUNTS. A joint account should flag that a co-holder is not a borrower. Neither is a rejection. But
`stmt.owner_matches_borrower`'s `yes/no/unknown` enum cannot express *"matches, but with a discrepancy worth a
look"* — it collapsed an exact match and a differing-middle-initial match into the same `yes` (LP-398's N1), and
had no way at all to say *"there is an extra, non-borrower holder"* (N5). Where a tag cannot express a risk, no
rule can catch it — the information dies at the tag layer (the `apparent_category` / LP-379-E enum-gap lesson).

**Separate tags, not a widened enum.** Added two document-subject AI tags to the existing `stmt_facts` group
(same one call — no per-document cost, D5): `stmt.holder_name_variance` (HOW the name differs, when it matches)
and `stmt.non_borrower_co_holder` (is there an additional holder who is not a borrower). Rejected widening
`owner_matches_borrower`'s enum: (1) it would STALE that tag's hard-won goldens (the LP-393-4a stale-golden
trap); (2) the two discrepancies are ORTHOGONAL — a joint account can MATCH and ALSO have a non-borrower
co-holder, which one enum can't say at once. `owner_matches_borrower` keeps answering only the match question,
semantically UNCHANGED (its 5 LF-6T3N goldens verified still `yes` after the prompt extension).

**The describe-vs-judge line.** The tags report the OBSERVABLE — the KIND of difference — not a verdict. The
value set is `none | middle_absent | middle_differs | nickname | surname_differs | other | unknown`, deliberately
**SPLITTING `middle_differs` (a DIFFERENT middle — LP-398 N1, the risky "relative?" case) from `middle_absent` (a
DROPPED middle — LP-398 P1, benign)**. Collapsing them into one `middle_name` value (the ticket's initial
proposal) would re-create the exact problem at a finer grain — the rule could not tell N1 from P1. The
differs-vs-absent distinction is a FACT about the names, so it belongs in the tag; **WHICH kinds warrant
attention is the RULE's decision (Priya's)**, not the tag's. The live probe confirmed the split works: N1 →
`middle_differs`, P1 → `middle_absent`, P2 → `nickname`, N3/N4/N6 → `none`, N5 → co_holder `yes` (naming the
non-borrower). Value-set questions flagged for Priya: which variances flag; the `surname_differs` value has no
scenario yet (n=0 — a fixture gap).

**AS-6's consumption is DEFERRED.** These tags are UNCALIBRATED. Making AS-6 (or any rule) flag on them now is
exactly the thing the three-bucket architecture forbids — consuming an unmeasured AI tag. AS-6's spec is
untouched; a worksheet → Priya's labels → a score come first, THEN a rule change.

**Cross-refs.** LP-398 (N1/N5 — the discrepancies the enum swallowed), LP-399 (the blind worksheet),
LP-390-8a (the borrower roster both new tags reuse), LP-379-E (the `apparent_category` enum-gap precedent),
LP-393-4a (the stale-golden trap the separate-tag design avoids).

## ADR-320: Priya's owner_matches rule — yes=certain / unknown=flag-for-evidence / no=non-person — reversing LP-390-8a's tolerance; and the co-holder wording resolution (LP-402)

**Priya's owner_matches rule (the refinement).** `stmt.owner_matches_borrower` reports the CONFIDENCE of the
identity match, and only that (the specific name difference lives in `stmt.holder_name_variance`):
- **`yes` ONLY when essentially CERTAIN** — an exact name, a DROPPED middle ("Jordan Rivera" = "Jordan A
  Rivera", less detail not a conflict), or a joint account listing a borrower.
- **`unknown` when PLAUSIBLE but the identity needs EVIDENCE** — a nickname (Bob/Robert), a possible
  maiden/married surname change, an uncertain given-name variant. This is "FLAG FOR EVIDENCE": **the document
  still COUNTS** (the difference is recorded in `holder_name_variance`); do not force `yes`, do not reject `no`.
- **`no` for a genuine NON-match** — a non-person entity (trust/LLC/estate), an unrelated name, OR a CONFLICTING
  middle name/initial that points to a DIFFERENT person ("Jordan M" vs "Jordan A" — a likely relative).

**This REVERSES LP-390-8a's tolerance.** LP-390-8a made `owner_matches` tolerant (nickname/middle/maiden →
`yes`). Priya's rule makes it CONSERVATIVE: tolerance now yields `unknown`, not `yes`. The re-score confirmed the
refined prompt produces her exact shape — **owner_matches 11/11** on the LP-401 fixture (yes=P1/N5/N8/N9,
unknown=N2/N7/P2, no=N1/N3/N4/N6). **The 5 REAL LF-6T3N goldens stayed `yes`** (exact matches — the conservative
rule does not disturb genuine matches; the equivalence that mattered), and `is_reserve_eligible` was unchanged.

**N1 (a different middle initial) → `no`.** Her ruling: a conflicting middle (Jordan M vs Jordan A) is a likely
different person (a relative), not a soft flag — distinct from `unknown` cases (nickname/surname) that are
plausibly the same person.

**The non_borrower_co_holder wording resolution.** The AI's reading was correct — the tag asks *"is there a
SECOND, extra holder who is NOT a borrower?"*, so a single-holder account is `no`. Priya's first-pass `yes`/
`unknown` labels on the single-holder cases were the mismatch. Her clarified rule required correcting **6**
single-holder cells to `no` (n1/n3/n4/n6/n7/p2 — the relayed ticket enumerated only 3; the rule + the AI she
agreed with cover all 6). After correction, **non_borrower_co_holder scored 11/11** (single `no`, N5/N8 `yes`,
N9 `no` — the discriminating control).

**⚠️ The coupling finding (a REGRESSION the conservative change surfaced).** `holder_name_variance`'s prompt
GATES on `owner_matches == "yes"` ("WHEN owner_matches is yes, describe how the name differs"). With
owner_matches now `unknown`/`no` for the flag cases, the variance tag reports `none` for N1/N2/N7/P2 — the very
cases whose difference must be surfaced so "the document still counts." Variance re-scored **4/11** (down from
LP-401). This BREAKS the three-tag design's purpose for the flag-for-evidence cases. **The fix — widen the
variance gate from `yes` to `yes OR unknown` — is a follow-up ticket** (LP-402 scoped the variance prompt OUT).
Until then, `owner_matches` + `non_borrower_co_holder` are calibration-passed; `holder_name_variance` is BLOCKED
on the gate widening.

**AS-6's consumption stays deferred** (its rule change is the next step); the synthetic-data caveat still
applies (validated on scenarios, not real-document messiness). **Cross-refs.** LP-390-8a (the tolerance this
reverses), LP-400 (the three-tag design), LP-401 (the labels + the fixture), LP-335 (report-what's-shown).

## ADR-321: AS-6 as the first MULTI-TAG rule — Priya's three-outcome ruling (surface, don't reject; the flagged document COUNTS) (LP-404)

**The finale of the owner-match thread** (LP-390-8a → LP-403). AS-6 was a single-tag rule (`owner_matches=no`
→ fired, else satisfied). LP-404 makes it the FIRST rule to read THREE calibrated tags — `owner_matches_borrower`
(the confidence), `holder_name_variance` (the specific difference), `non_borrower_co_holder` (an extra holder),
all on the document subject, produced together by the `stmt_facts` group — and combine them into Priya's three
outcomes:

| condition (per statement) | verdict | the document |
|---|---|---|
| `owner_matches=yes`, no non-borrower co-holder | **satisfied** | counts silently |
| `owner_matches=unknown` (plausible, unconfirmed) | **needs_review** | **STILL COUNTS**, surfaced |
| a non-borrower co-holder (`co_holder=yes`) on a `yes` match | **needs_review** | **STILL COUNTS**, surfaced |
| `owner_matches=no` (a genuine non-match) | **fired** | an OPEN finding — does NOT count |
| the holder facts absent / unreadable | **couldnt_check** | honest abstention |

**The "counts but surfaces" outcome is `needs_review`, and this is deliberate (D2).** Priya's middle row —
"surface for a human WHILE THE DOCUMENT COUNTS" — is NOT a normal open finding (`fired` is AS-6's exclude
verdict: a third-party account that does not count). It is also NOT `couldnt_check` (a data gap — "we couldn't
read it"). `needs_review` is the verdict that routes a subject to human review WITHOUT excluding it: the
plausible match / the non-borrower co-holder is a real judgment the processor confirms, and the statement
stays in the borrower's assets pending that confirmation. It is NOT `PENDING_AUTOMATION` either — that is for a
BLOCKED (uncalibrated) rule; AS-6's tags are calibrated (LP-403), so AS-6 RUNS and reaches a real verdict.

**Route on the match CONFIDENCE (owner_matches) + the co-holder — NOT on the variance value (D3, and a
correction of the ticket's own table).** The ticket's proposed table listed `holder_name_variance ∈
{middle_absent, …}` as an independent needs_review trigger. That would FALSE-FLAG the benign dropped middle —
which is exactly the 5 REAL LF-6T3N goldens (holder "Jordan A Rivera" vs roster "Jordan Rivera" → owner=yes,
variance=middle_absent). Routing on the variance would surface a genuine borrower's own account for review — the
FP harm AS-6 exists to avoid. So AS-6 routes on `owner_matches` (yes→counts, unknown→surface, no→open) plus
`co_holder=yes`→surface; the variance tag NAMES the reason a flag was raised (it is in the finding's load-bearing
provenance), it does not independently trigger. Consequence: **N1 (a conflicting middle, owner=`no`) → fired**
(an open finding, like the trust/LLC/unrelated cases), NOT needs_review as the ticket's Phase-2 example said —
because Priya's own `owner_matches` label for N1 is `no` (ADR-320: a conflicting middle = a likely different
person). Her label + the FP-harm requirement (the gate of record) beat the ticket text.

**The gate does NOT gate on owner_matches (D3, a DSL constraint).** The generic fail-closed gate (LP-315)
treats ANY `unknown` load-bearing tag as `couldnt_check`. But Priya's `owner_matches=unknown` is a meaningful
FLAG value that must reach `needs_review`, not `couldnt_check`. So AS-6 gates on `holder_name_variance` instead
(the "was the holder name read & compared" presence check — absent/`unknown` → couldnt_check) and routes
`owner_matches` through the ordered outcomes. `gated_tags` cannot be empty (schema `min_length=1`), so a
non-owner gated tag was required; variance is the natural choice (its presence signals the group ran and the
name was compared). The empty-roster `owner=unknown` (a data-gap Priya's table also maps to couldnt_check) is
subsumed into `needs_review` — the tag value cannot distinguish it from the flag, and needs_review (a human
reviews and sees "no borrowers on the loan") is not a false green.

**The reason strings name the cause in plain language (D4, LP-376-C).** Each surfaced verdict carries a
processor-facing reason — "plausibly matches a borrower but the match is not certain … the statement still
counts", "a joint account with an additional holder who is not a borrower … still counts", "does not resolve to
a borrower … a third-party account". The SPECIFIC (the co-holder's name, the variance kind) lives in the
finding's load-bearing tag provenance (the co_holder / variance tag reasoning), not interpolated into the static
reason — a rule-as-data limitation (the reasoning template interpolates only numeric operands), accepted rather
than adding a bespoke reasoning-interpolation combinator.

**The proof (real reasoner, reported).** On the LP-401 scenario fixture (11 statements): **4 fired** (N1/N3/N4/N6
— non-matches), **5 needs_review** (N2/N7/P2 owner=unknown flags + N5/N8 non-borrower co-holders), **2 satisfied**
(N9 both-borrowers, P1 dropped-middle) — EXACTLY Priya's ruling. On the 5 REAL LF-6T3N bank statements: **all 5
satisfied** (no false flag on a genuine match). AS-6 is NOT activated by this change — its bar stays
`validated:false` (Priya's sign-off, LP-397); `ACTIVE_RULE_IDS` = 24. **Cross-refs.** LP-390-8a / LP-397 / LP-400
/ LP-402 / LP-403 (the thread), LP-391 (the manual-review surface), LP-376-C (human reasons), §8 (the outcome
model), ADR-319 / ADR-320.

## ADR-322: The deterministic DSL cannot express cross-document / ordered-pairwise checks — per-account (and per-sequence) continuity is a DERIVED producer, read as a loan tag (LP-406-2)

**Decision.** A verification rule whose logic is an **ordered, cross-document, pairwise** relation — statement N's
ending balance vs statement N+1's beginning balance; a "no missing period" gap between consecutive statements;
any "the next record in the series" comparison — is **NOT expressible in the deterministic rule DSL**, and must
instead be computed in a **derived tag producer** that emits a loan-level result a trivial deterministic rule
reads. This was found writing AS-8 (statement chaining / continuity, LP-406-2) and shapes every future
statement-sequence / continuity rule.

**Why (read from the code, not asserted).** Three mechanisms could conceivably express a pairwise sequence
compare; none does:
- **The deterministic operand resolver** (`rule_engine/deterministic.py`) resolves each operand to ONE typed
  value per subject (`tag`/`loan_tag`/`reference`/`calc`/`product`). There is no "next-in-series" / index / pair
  operand — a comparison is `left <op> right` over two single values, never a fold over an ordered series.
- **The `per_account` enumerator** (`rule_engine/enumerators.py`) merges an account's statements into one tag
  map and, by design, **DROPS any per-statement tag whose value differs across statements** (each statement's
  own ending/beginning balance and period) — so a `per_account` deterministic rule literally cannot see the pair
  it must compare (it couldnt_checks). Its own comment directs: *"a rule that needs the per-statement series uses
  resolve_accounts directly"* — i.e. a derived producer.
- **`ConsistencyEval`** (`rules/specs.py`) checks that gathered values are **all equal** after normalization —
  not an **ordered pairwise** relation between *different* values (`ending[N] == beginning[N+1]`) and not a gap
  check. It cannot express order or the pair.

**The pattern (already established, not new).** `tag_materialization/derived.py` already computes cross-document,
per-group results in Python and exposes them as loan-level tags a deterministic rule reads: `_stmt_min_account_months`
(groups statements per account via `resolve_accounts`, fail-closed) and `_income_max_employment_gap` (consecutive
pairing within a group, never across groups). A continuity producer (proposed `stmt.continuity`) is the same
footprint (~40–60 lines). The rule then reads it: `broken → fired`, `ok → satisfied`, `unknown → couldnt_check`,
`n/a → not_applicable` (the last via an applicability predicate, because `not_applicable` is not a deterministic
outcome verdict — a one-statement account has nothing to chain and must NOT couldnt_check).

**Consequences.** (1) AS-8 is NOT writable-now — it is `needs-producer` (a `stmt.continuity` derived tag), not a
straight rule-write; LP-406-2 stopped and proposed rather than built (the PC-7 / LP-406-1 precedent). (2) Any
future sequence/continuity rule (per-account or otherwise) should assume a derived producer from the start.
(3) This refines LP-405's Bucket 2: "inputs produced" was necessary but not sufficient — the *check* must also
be expressible; AS-8's inputs are all produced, yet it needs a producer for the pairing. **Cross-refs.** LP-406-2
(this ticket), LP-406-1 (PC-7's analogous `today`-operand stop), LP-405 (the census), LP-336 (`resolve_accounts`),
`_stmt_min_account_months` / `_income_max_employment_gap` (the precedents). `ACTIVE_RULE_IDS` = 24 (unchanged; no
rule written).

## ADR-323: Cross-document rule RELATION classes — the DSL expresses only all-equal natively; ordered-pairwise AND set-coverage each need a derived producer (LP-406-3, extends ADR-322)

**Decision.** A cross-document verification rule's **relation** determines whether it is expressible. There are
three classes, and only the first is native:
- **all-equal** ("do all sources agree on fact T?") — expressed natively by **`ConsistencyEval`** (gather T
  across sources, compare after normalization, AI-judge the differing residue). ID-1/2/3/4/7, IN-5.
- **ordered-pairwise** ("does record N relate to record N+1?" — statement chaining, employment gaps) — **NOT
  native**; a derived producer computes it and exposes a loan/borrower tag a rule reads (ADR-322).
- **set-coverage** ("does every element of set A have a match in set B, both ways?" — pay-stub↔W-2 employer
  coverage, tradeline↔liability reconciliation) — **NOT native**; also a derived producer.

**Why set-coverage is not `ConsistencyEval` (read from the code).** `consistency.py`'s entire comparison is
`len({normalize(v) for v in gathered}) == 1` → AGREE. That is **all-equal**. It gathers ONE undifferentiated
multiset and cannot (a) **partition** it into set A (pay stubs) vs set B (W-2s) — its `gather_filter` restricts
to one type, it does not compare two — nor (b) express **coverage** ("every A has a matching B"). A legitimate
two-employer borrower normalizes to `{A, B}`, `len == 2` → the evaluator calls it a **disagreement and fires**,
which is exactly wrong for a coverage rule (both employers ARE covered → satisfied). IN-5's own spec confirms
the split: *"a borrower with two legitimate jobs shows two employers — the set-coverage case is IN-6, deferred."*
The deterministic DSL resolves one value per subject, so it cannot gather a set either.

**The mechanism for the non-native classes.** Compute the relation in a **derived producer** (the established
"compute in Python over the snapshot, expose a tag" pattern) and let a trivial deterministic rule read the
result. For set-coverage: a per-borrower producer that reuses `_index_borrower_documents` (the `belongs_to`
attribution) + the consistency normalizers (`_normalize` / `drop_entity_suffix`), partitions
`income.employer_normalized` by document type, checks bidirectional coverage, and emits
`covered`/`uncovered`/`n/a`/`unknown` (proposed `income.employer_coverage`, LP-406-3). The one-side-empty case
must map to **not_applicable** (an applicability predicate), never couldnt_check — the AS-8 one-statement trap
in another form. The AI-fuzzy residue ("is this DBA the same employer?") that a pure derived producer cannot
resolve is either a follow-up or a new `ConsistencyEval` `compare_mode: coverage` (an evaluator change, the
heavier alternative).

**Consequences.** (1) IN-6 is NOT writable-now — it is `needs-producer` (`income.employer_coverage`); LP-406-3
stopped and proposed rather than built. (2) **Before writing any cross-document rule, classify its relation** —
only all-equal is a straight `ConsistencyEval` write; ordered-pairwise and set-coverage need a producer first.
(3) The Bucket 2 epic reality: of four "zero-dependency" rules, only OC-1 was writable (and it is held on
calibration); PC-7, AS-8, IN-6 each need one small derived producer (`contract.days_until_closing` /
`stmt.continuity` / `income.employer_coverage`) — a single producer wave. **Cross-refs.** LP-406-3 (this ticket),
ADR-322 (ordered-pairwise), LP-406-1 (PC-7's `today` stop), LP-406-4 (OC-1's calibration hold), LP-405 (the
census that measured "inputs produced" but not "check expressible"), `consistency.py` (the all-equal comparison),
IN-5.yaml (the deferral). `ACTIVE_RULE_IDS` = 24 (unchanged; no rule written).

## ADR-324: The derived-producer wave — derive the fact, let a trivial rule branch on it (the resolution to ADR-322/323); tags describe, rules judge (LP-410)

**Decision.** The relations the DSL cannot express natively (ADR-322 ordered-pairwise; ADR-323 set-coverage; and
PC-7's date-vs-`today`) are resolved by a single pattern: **compute the fact in a small derived producer and let
a trivial deterministic rule branch on the result.** LP-410 builds the three producers that unblock PC-7, AS-8,
and IN-6 — `contract.days_until_closing` (loan), `stmt.continuity` (loan, per-account internally), and
`income.employer_coverage` (borrower) — additively (no rule written; `ACTIVE_RULE_IDS` = 24).

**Tags describe, rules judge (LP-400).** Each tag emits an OBSERVED STATE, never a verdict:
`days_until_closing` emits a signed NUMBER (PC-7's realistic-window threshold stays in the rule, Priya-validated,
never the tag); `stmt.continuity` and `income.employer_coverage` emit descriptive enums (chained/broken/…,
covered/uncovered/…). **No threshold or policy lives inside a producer** — so changing Priya's mind later changes
a rule, not a producer.

**The `not_applicable`-enabling design (a distinct, load-bearing decision).** `not_applicable` is NOT a
deterministic OUTCOME verdict (those are fired/satisfied/needs_review/couldnt_check); it comes from the
applicability layer. A "nothing to check" state therefore must be **distinguishable in the tag** from "cannot
check", or the rule can only ever reach `couldnt_check` and looks broken on ordinary files (the AS-8
one-statement trap, LP-406-2). So each producer emits a dedicated value: `stmt.continuity = "nothing_to_chain"`
when no account has ≥2 statements; `income.employer_coverage = "one_sided"` when a borrower lacks one of the two
document types. The rule maps that value to `not_applicable` via an applicability predicate; `"unknown"` remains
the honest couldnt_check.

**Calibration inheritance (per tag).** `days_until_closing` and `stmt.continuity` read only PARSED data — no AI,
nothing to calibrate. `income.employer_coverage` derives from `income.employer_normalized` (AI, measured 100%
via live IN-5) and matches employers **reusing IN-5's exact-bookend normalizers** (casefold / drop_punct /
collapse_ws / strip / drop_entity_suffix). Because it reuses the ALREADY-MEASURED normalization and adds **no**
new judgment (it does NOT invoke IN-5's AI fuzzy-residue judge), **IN-6 inherits IN-5's calibration and is not
held like OC-1.** The cost: a word-level short-form the normalizer cannot reduce ("Acme" vs "Acme Freight")
reports `uncovered` where the AI might forgive it — a DOCUMENTED limitation (the fuzzy-residue is a later
refinement), never a silent false "covered".

**Multi-account representation (the subtle subject decision).** `stmt.continuity` is loan-level but computes
per-account (via `resolve_accounts`, LP-336) and aggregates with precedence **broken > unknown > chained >
nothing_to_chain**: a break in ONE account surfaces (never masked by a clean sibling — fire-if-any), an unread
account never passes as chained (fail-closed). AS-8 then reads one loan-level value. Per-account grouping also
prevents the false global gap (checking-Jan / savings-Feb / checking-Mar is not a "missing month").

**Consequences.** PC-7 / AS-8 / IN-6 each become a trivial deterministic spec over one tag (their own tickets).
PC-7 additionally needs Priya's closing window (ships `validated=false`); AS-8 and IN-6 carry no threshold. The
three producers mirror existing ones (`income.days_since_most_recent_pay`, `_stmt_min_account_months` +
`resolve_accounts`, `_borrower_attributed_documents` + the consistency normalizers) — no new mechanism.
**Cross-refs.** ADR-322 / ADR-323 (the relations), LP-406-1/2/3/4 (the four stops + OC-1), LP-400 (describe vs
judge), LP-336 (`resolve_accounts`). Additive; `ACTIVE_RULE_IDS` = 24.

## ADR-325: A deterministic rule whose input carries a KNOWN false-positive residue routes that branch to needs_review, not fired (LP-406-3b)

**Decision.** When a deterministic rule branches on a derived tag whose value has a **known, structural
false-positive source**, the uncertain branch ships **`needs_review`** (surface for human confirmation), not
**`fired`** (a confident finding). This is a per-branch OUTCOME verdict (`needs_review` is in `VERDICT_BY_NAME`,
authored directly in the spec's `outcomes`), NOT a rule-wide `ships: ratify` mode. First applied to IN-6
(LP-406-3b): its `income.employer_coverage == uncovered` branch → `needs_review`.

**Why (IN-6's case).** `income.employer_coverage` (LP-410) does the DETERMINISTIC half of IN-5's employer
comparison (the exact-normalized bookend) but NOT IN-5's AI fuzzy-residue judge. A pay stub's short form
("Acme") vs a W-2's legal name ("Acme Freight Co") normalizes to "acme" vs "acme freight" → `uncovered` — when
it is very likely the SAME employer. Short-form employer names on pay stubs are COMMON, so `uncovered` has a
KNOWN false-positive source. The FP/FN calculus: `fired` false-fires on common short forms (noise, processor
distrust); `needs_review` surfaces the uncertain case to a human AND still reaches a human for a GENUINE gap —
so it **strictly dominates `fired`** until the fuzzy residue is closed (a later refinement). The error cost
either way is a human confirmation, never a false auto-verdict.

**The mechanism (why per-branch, not ships:ratify).** The deterministic evaluator's outcome verdicts include
`needs_review` (`VERDICT_BY_NAME`), so a spec can declare `uncovered → needs_review` while `covered → satisfied`
— only the uncertain branch goes to a human, and the certain branch still auto-ships. `ships: ratify` is a
rule-WIDE mode (it would ratify the satisfied branch too), and whether the runtime honors `ratify` on a
structural rule is an unresolved question (the IN-7/LP-393-6 kind-reclassification issue, ADR-316). A per-branch
`needs_review` outcome is the precise, already-supported tool.

**Consequences.** (1) A reusable precedent: future rules on derived tags with a documented FP residue route the
uncertain branch to `needs_review` (and close the residue as a separate refinement). (2) IN-6 is written +
producing but **HELD** — a transitive AI dependency (employer_coverage reads AI `income.employer_normalized`,
100% via IN-5), so its bar is `calibratable-now` (the IN-3 shape) with a PROPOSED 0.95 threshold (IN-5's
precedent — same tag, same evidence) and `validated: false`, pending Priya; `ACTIVE_RULE_IDS` stays 25.
**Cross-refs.** LP-406-3b (this ticket), LP-406-3 (the ADR-323 set-coverage stop), LP-410 (the producer +
the documented fuzzy-residue limitation), IN-3 (the transitive-AI bar precedent), ADR-316 (the ratify-mode
question), LP-400 (describe vs judge).

**EXTENSION — PC-3 (LP-407-4), the SECOND instance → this is now a PATTERN, not a one-off.** PC-3 (property
address matches) compares the purchase contract's subject-property address against the loan file's (MISMO)
subject-property address via a derived tag using the **consistency normalizers** (casefold / drop_punct /
collapse_ws). Those normalizers **cannot expand `St`→`Street` / `Apt`↔`#`↔`Unit`**, so an exact-after-normalize
mismatch carries a known FP residue (an abbreviation variant looks like a different property). A confident
"different property" FIRING on that residue would be noisy and alarming, so — exactly as IN-6 — the mismatch
branch (`property.address_normalized_match == "no"`) routes to **`needs_review`**, never fired: a human confirms
same-vs-different, the rule never asserts. UNLIKE IN-6, PC-3 has **no transitive AI dependency** (the compare is
fully deterministic), so it is NOT held on calibration — it ships **no-ai-dependency** and ACTIVATES (29 → 30).
The residue-closing refinement here is the AI-tolerant `property.address_normalized_match` (its `fact_tags.csv`
design: AI-at-rule-time, "tolerant") — a future calibration ticket that would reduce the `needs_review` noise.
**The pattern, stated generally:** a deterministic rule whose comparison uses normalizers that cannot resolve
every legitimate surface variant routes the mismatch to `needs_review` and defers the tolerant matcher to a
calibration follow-up — rather than firing on the residue or inventing a fuzzy matcher inline. (IN-6: employer
short-forms; PC-3: address abbreviations.) **Cross-refs.** LP-407-4 (PC-3), LP-415 (the audit row), LP-416 (the
redundancy lesson applied at D0).

## ADR-326: A two-sided date window is TWO asymmetric outcomes (past-fires vs a future-threshold); and a no-AI rule with a Priya threshold has no clean hold in the activation model (LP-406-1b)

**Decision (the rule shape).** A "date realism" rule over a signed day-count (e.g. `contract.days_until_closing`,
LP-410) is **two asymmetric outcomes, not one symmetric tolerance**:
- **PAST side** (the date is behind the file date) — a finding at (almost) any magnitude; the default is
  `past_grace_days = 0` (any strictly-past date fires). The question is only whether a small *grace* is allowed.
- **FUTURE side** (the date is implausibly far ahead) — a genuine *threshold* (default `far_future_days = 90`).

They are **different problems for a processor** (a passed/expired date vs a premature/placeholder one), so they
get **separate `fired` outcomes with distinct reasons** (ordered, first-match-wins), and — because the operand
is a real number — the reason **interpolates the day count** ("the closing date is {days} days from the file
date"), unlike the enum rules (AS-8/IN-6) whose reasons are static. First applied to PC-7 (LP-406-1b). This
shapes every future date-window rule (appraisal validity PR-6, credit-report validity CR-13, rate-lock CL-1):
specify past and future as separate outcomes, not one ± window.

**Finding (the model gap).** *(The `input_resolves: false` stand-in below is SUPERSEDED by ADR-327 / LP-411,
which added the `no-ai-threshold-pending` status so PC-7 is held honestly on `validated: false` with
`input_resolves: true`. The two-sided-window decision in this ADR still stands.)* The activation-bar model has **no clean hold for a NO-AI rule that carries a Priya
THRESHOLD.** Its statuses assume: `no-ai-dependency` → activation is a wiring decision gated only by
`input_resolves` (no threshold sign-off); `calibratable-now` → an AI-accuracy sign-off. PC-7 is neither — no AI
tag, but a domain **window** Priya must confirm. Its input *does* resolve (`days_until_closing == "1"` on
LF-6T3N → SATISFIED), so `input_resolves: true` would ACTIVATE it auto-shipping fired verdicts on an
**unvalidated** window — exactly what a sign-off gate should prevent; and `validated: false` does nothing on a
no-ai bar (`is_eligible` reads `input_resolves`, not `validated`). So PC-7 is held by leaving
`input_resolves: false` with an explicit rationale that the true reason is "the window is a default", not "the
input doesn't resolve". **Reported as a gap, not fixed here:** a real hold would gate no-ai eligibility on
`threshold_needs_signoff` (or add a `no-ai-threshold-pending` status), so a no-ai rule with a Priya threshold is
held natively rather than via the `input_resolves` stand-in. `ACTIVE_RULE_IDS` stays 25 (PC-7 held). **Cross-refs.**
LP-406-1b (this ticket), LP-410 (the signed-day tag; window deliberately left out — tags describe, rules judge,
LP-400), IN-2 (the number-vs-threshold mirror), ADR-324 (the derive-then-branch pattern).

## ADR-327: The third eligibility case — `no-ai-threshold-pending` (no AI to calibrate, but a Priya threshold to sign off); the gate of record must not hold a value the system's own proof contradicts (LP-411)

**Decision.** The activation model gains a **third eligibility status**, `no-ai-threshold-pending`:
`is_eligible = input_resolves AND validated`. It sits between the two prior paths — `no-ai-dependency`
(eligible on `input_resolves` alone; nothing to sign off) and `calibratable-now` (eligible on an AI
`measured_accuracy >= threshold` + `validated`). It exists for a rule with **no AI tag to calibrate but a
domain THRESHOLD (a window/limit) Priya must sign off** — first, PC-7's two-sided closing window (LP-406-1b).

**Why a status, not the `threshold_needs_signoff` flag (the code decided).** LP-406-1b's D7 proposed gating
no-AI eligibility on `threshold_needs_signoff`. But that flag is **calculative-only** — `kinds.py` rejects it on
a structural rule, and PC-7 is structural — so PC-7 could not declare its sign-off there. And a plain
`no-ai-dependency` bar cannot be held by `validated` at all: `parse_bar` **forbids `validated: true` on any
non-`calibratable-now` status** ("a blocked rule cannot be signed off as live-able"), and `is_eligible` ignores
`validated` on a no-AI bar. So the only lever LP-406-1b had was `input_resolves: false` — **a value that same
ticket's own proof showed is FALSE** (PC-7's input resolves; `days == "1"` → SATISFIED). A new status is the
minimal honest fix: it makes `validated` meaningful and permitted for exactly this case (the loader now allows
`validated` on `calibratable-now` OR `no-ai-threshold-pending`), so PC-7 is held on `validated: false` with
`input_resolves: true` — honest and held.

**The principle (the AS-5 / IN-7 lineage).** *The gate of record must not contain a value the system's own proof
contradicts.* A false value in `activation_bars.yaml` is trusted by whoever reads the file rather than the
rationale (a future census — LP-394 read this file to classify rules — would report PC-7 as "input doesn't
resolve"). This is the class LP-390-7 hardened against (AS-5's stray `validated: true`) and LP-393-6 refused
(IN-7's `ships: auto` — "the bar would be a lie"). LP-411 removes PC-7's false `input_resolves` and, in the same
LP-390-7 fail-loud spirit, adds a loader guard: a `validated` `no-ai-threshold-pending` bar **must** have
`input_resolves: true` (you cannot sign off a threshold to activate a rule whose input does not resolve).

**The predicate change (before → after).** Only the no-AI side gains a case; the AI side is byte-identical:
- `calibratable-now`: `validated AND threshold != None AND measured_accuracy >= threshold` — **unchanged**.
- `no-ai-dependency`: `input_resolves` — **unchanged**.
- `no-ai-threshold-pending` (**new**): `input_resolves AND validated`.

**Blast radius: ZERO.** The change is purely additive (a new status branch); no existing bar's eligibility moves.
`eligible_rule_ids()` is byte-identical (the same 14); PC-7 was held before (`input_resolves: false`) and is held
after (`validated: false`); **AS-8** (the live no-AI rule) has no threshold, so the new case is a no-op for it —
it stays live. `ACTIVE_RULE_IDS` stays **25**; the LP-389 invariant (`ACTIVE − BASE == eligible_rule_ids()`)
holds. No live rule was deactivated. **Supersedes** ADR-326's `input_resolves`-stand-in note (its two-sided
window decision stands). **Cross-refs.** LP-406-1b (D7 — the gap), LP-390-7 (the AS-5 loader hardening), LP-393-6
(the IN-7 "a bar that lies" refusal), LP-394 (the census that reads this file), `kinds.py` (the calc-only
`threshold_needs_signoff`).

## ADR-328: A monthly-conversion tag fails closed to `unknown` on an unstated/unrecognized periodicity — it must not assume the period the way the DTI display does (LP-407-2)

**Decision.** A derived tag that converts a periodic housing amount to a monthly figure (`housing.hoa_monthly`,
the DT-2 input) maps only the **recognized** frequencies (monthly/quarterly/semiannual/annual) and **fails closed
to `unknown` on an unstated or unrecognized `dues_frequency`** — it never assumes a period. `housing.taxes_monthly`
and `housing.insurance_monthly` have no periodicity axis (their fields are annual by definition → ÷12).

**Why.** The DTI calculator's `_extracted_hoa_monthly` (`services/dti.py`) DEFAULTS an unmapped frequency to
monthly (`divisor.get(frequency, 1)`) — acceptable for a *display* line a processor can override, but a
verification **tag** that silently reads a quarterly/annual due as monthly is a **12× / 4× miscalculation** a rule
would then judge as fact. The tag abstains instead. This keeps the tag **stricter-than-or-equal-to the DTI**
(it emits `unknown` where the DTI assumes a value) — the same "agree-or-abstain, never LOOSER than the DTI"
contract `housing.insurance_monthly` (LP-374) established, and the absent≠0 fail-closed discipline (LP-318/375):
a fabricated or assumed figure makes a downstream DTI/compare confidently wrong.

**Scope note (D5, reported not decided).** `housing.hoa_monthly` is a **number** tag, so it cannot carry a
`not_applicable` enum — it collapses "no HOA on this property" and "HOA unreadable" into `unknown`. DT-2's
`not_applicable` on a genuinely no-HOA property therefore needs a **presence** gate (its applicability keyed on
HOA-statement presence), NOT this amount tag. Left for LP-407-3; no presence tag was invented here.

**Cross-refs.** LP-407-2 (D3/D5), LP-374 (`housing.insurance_monthly` agree-or-abstain), ADR-324 (tags describe,
rules judge), `services/dti.py` `_extracted_hoa_monthly` (the assume-monthly default this diverges from —
**now fixed by LP-413/ADR-329**, so the tag and the calculation agree).

## ADR-329: "Fail closed" in a CALCULATION is the gated/degraded state, not a smaller number — the DTI gates on an unconvertible HOA rather than assume monthly or drop to 0 (LP-413)

**Decision.** `services/dti.py` `_extracted_hoa_monthly` no longer defaults an unstated/unrecognized HOA
`dues_frequency` to monthly (`divisor.get(frequency, 1)`). When a dues amount is present but its frequency is
not in the recognized map, the HOA line is marked **unknown**, which routes into the existing LP-375 gate
(`_AutoLine.unknown` → `DtiLineItem.unknown` → `gated_labels` → `DtiCalculation.gated` → `gate_display_ratios`
nulls the headline ratios). A recognized frequency is UNCHANGED; a genuinely **absent** HOA (no dues) stays a
legitimate `$0` line (not a gate). A processor override on the line is trusted and clears the gate.

**Why — the calculation-vs-tag distinction.** ADR-328 established that the `housing.hoa_monthly` **tag** fails
closed to `unknown` on an unconvertible frequency. A tag can answer `unknown`; a **calculation cannot emit an
unknown number**, so "fail closed" here had to be *defined*. The old default was a **live 12× miscalculation**:
a "600" that is actually annual entered the DTI as $600/mo — an overstatement of housing expense in a number
that drives qualification, with no cross-check. The naive fix (return `None`) is **worse**: HOA is not a
`_REQUIRED_HOUSING_KEYS` member, so `_to_items` would fall to `auto or 0` → a silently **smaller** housing
expense → the borrower looks **more** qualified. **Understating is invisible and dangerous; overstating is
visible and conservative; the honest answer is neither — it is the gated/degraded state** (the ratio is
withheld, not fabricated smaller). The chosen behaviour is the third option: mark the DTI gated.

**The direction that must not happen (recorded).** A missing/unrecognized frequency must NEVER silently produce
a *smaller* housing expense. The fix is guarded by a test asserting exactly this (an unconvertible HOA yields no
confident ratio, not a reduced one).

**Never looser than the tag.** The DTI's frequency map is kept **byte-identical** to the tag's
`_HOA_FREQUENCY_MONTHS` (a drift-guard test asserts equality), so the calculation recognizes exactly the set the
tag does and fails closed on the rest — the LP-374 "agree-or-abstain, never looser" discipline, extended from a
tag to a calculation. Widen the two together or not at all.

**Scope / siblings (D4).** The HOA line is the ONLY DTI input that defaulted a periodicity. `_extracted_monthly`
(taxes/insurance) uses `annual=True`, but that is the **field's contract** (`annual_tax_amount` / `annual_premium`
are annual by name — ÷12 is definitional, not a guessed default); P&I is computed, MI comes from the MI
calculator (already monthly), income/debt are monthly columns. No sibling assume-a-periodicity site. **Reported
but out of scope:** `calculators.build_reserves_view` reads `dti.housing_payment` without honoring `.gated`
(a pre-existing pattern that also applies to absent taxes/insurance), and `calculations_section.map_dti` gates
the SNAPSHOT DTI only on `_REQUIRED_DTI_TAGS` (HOA not among them), so the snapshot DTI would not gate on an
unconvertible HOA — but no LIVE rule reads `calculations.dti` (only AS-4 reads `calculations.reserves`), and
this ticket is scoped to the DTI service. Both are recorded gaps, not fixed here.

**Cross-refs.** ADR-328 (the tag's fail-closed rule), LP-407-2 (the finding), LP-374 (`housing.insurance_monthly`
"agree-or-abstain"), LP-375 (the `unknown`→gated machinery this reuses), `services/dti.py` (`_extracted_hoa_monthly`,
`_to_items`).

## ADR-330: The self-source vacuity pattern — a rule whose operands both trace to ONE extracted field can never fire; and a NUMBER tag cannot carry a `not_applicable` for an optional component (LP-407-3)

**The pattern (named).** A verification rule that compares two operands is only a real check when the operands
are INDEPENDENT. When both operands reduce to the **same extracted field**, the rule compares a value to
itself — it is **vacuous**: it can never fire, yet it looks like coverage while checking nothing. This is worse
than a missing rule (a missing rule is visibly absent; a vacuous one is a false sense of coverage). LP-407-3
found this a **second** time (LP-407-2 found it first, in DT-5), so it is worth naming as a class to check for.

**Two rules fell to it, one survived (the Bucket 2.5 close-out):**
- **DT-5** (LP-407-2) — "premium used vs binder": both sides trace to the homeowners binder's `annual_premium`
  (the DTI insurance line and `housing.insurance_monthly` read the same field). Vacuous. Not written.
- **DT-2** (LP-407-3) — "HOA dues in the DTI": `rule_tags.csv` maps it to `housing.hoa_monthly` ALONE. "HOA
  detected" and "the dues in the DTI" both trace to the one `hoa_statement.dues_amount` (the DTI auto-includes
  what it detects). There is no independent stated-HOA operand. Vacuous → **not written.** (It also has no
  HOA-presence signal — see below.)
- **PC-2** (LP-407-3, WRITTEN + LIVE) — "contract price vs 1003 price": `contract.loan_sales_price` (the
  purchase-agreement document) vs `property.purchase_price` (the 1003/MISMO). **Two genuinely independent
  sources** — a processor can enter a 1003 price that differs from the contract, and PC-2 catches it. Not
  vacuous. Exact compare, no threshold → activates via the no-ai-dependency gate.
- **DT-4** (LP-407-3) — NOT vacuous, but its independent operand (a tax ESTIMATE from `assessed_value`) is
  **unwired**: no `property.assessed_value` tag is produced, and the estimate needs a jurisdiction tax/mill
  rate (a Priya value). The DTI reads `annual_tax_amount` directly and computes no estimate. **Stopped:
  needs-producer + needs-definition** — its own ticket.

**The corollary — a NUMBER tag cannot express `not_applicable` for an optional component.** DT-2's second
problem (LP-407-2 D2, restated general here): a property with NO HOA should be `not_applicable`, but
`housing.hoa_monthly` is a **number** tag, and a number has no `not_applicable` enum — "no HOA statement" and
"HOA unreadable" both collapse to `unknown`. So an optional-component rule keyed on a number tag `couldnt_checks`
on every file lacking that component (the "looks broken on ordinary files" failure). The general answer (for a
future producer ticket): an optional-component rule needs a **presence enum** (`present`/`absent`/`unknown`) its
applicability predicate can gate on — the amount tag alone is insufficient. No presence tag exists today, so
DT-2 is doubly blocked. (Insurance/taxes are REQUIRED components, so their `unknown → couldnt_check` is correct
— this gap is specific to OPTIONAL components like HOA.)

**The discipline (the vacuity check, first).** Before writing a compare rule: trace BOTH operands to their
source fields. If they reduce to one field → STOP (vacuous). If an operand is unwired → STOP (needs-producer).
Only then write it. Two censuses (LP-405, LP-407-1) over-counted this bucket by asking "are the inputs
produced?" without asking "are the operands INDEPENDENT?"; this ADR records the question that separates a real
rule from a vacuous one.

**Cross-refs.** LP-407-2 (DT-5, the first instance; the D2 number-tag gap), LP-407-3 (DT-2 vacuous, DT-4
unwired, PC-2 written), `rule_tags.csv` (the one-operand maps for DT-2/DT-4), `services/dti.py` (the DTI's
HOA/tax lines — the self-source trace), ADR-324 (tags describe, rules judge).

## ADR-331: A borrower-level signal an activation bar declares "missing" is often a DETERMINISTIC promotion of an existing document-subject AI tag — not a new AI producer; and the third redundancy-driven producer abandonment (LP-418)

**The context.** LP-418 was a PRODUCER batch: build the small producers that unblock rules written-but-inert
for lack of an input — no rules written. The interesting decision was HOW to build the borrower-level
self-employment signal IN-12's activation bar named as missing, and WHICH candidate producers to refuse.

**The pattern (named) — promote, don't re-perceive.** IN-12 ("a self-employed borrower needs two years'
history") enumerates per **borrower**, but its bar said the self-employment signal "does not exist —
`income.type` is subject:**document**." The naive reading is "add an AI producer that judges self-employment
per borrower." That is wasteful and worse: it re-perceives, from scratch and with a fresh calibration round, a
fact the pipeline ALREADY extracts. `income.type` is measured per income document (via IN-11's AI). The
borrower-level signal is a **deterministic promotion** of it: `income.is_self_employed` (subject:borrower)
reads the borrower's OWN attributed income documents (`_borrower_attributed_documents`, the LP-385 per-borrower
primitive) and reports `yes` if any states `self_employment`, `no` if types are present but none is, `unknown`
if none is readable. **No new AI, no calibration round.** The derived-last order (ADR/LP-333) is what makes
this legal: a derived recipe runs AFTER the AI stage, so it sees the AI-produced `income.type`.

**Why the `no` branch matters (the enum affordance, cf. ADR-330).** The promotion is an ENUM, so it can carry
`no` — "this borrower has readable income types, none self-employment" — which lets IN-12 reach
`not_applicable` (a non-self-employed borrower is out of scope for the two-year rule, the AS-8
not_applicable lesson). A NUMBER tag could not (ADR-330's corollary). The signal fails **closed** to `unknown`,
never a fabricated `no`.

**The third redundancy abandonment (D0 STOP).** The batch also considered an MI producer. **Refused as
redundant:** the loan product already surfaces mortgage insurance — `calculations_section.map_mi` maps
`compute_loan_mi`, and "MI always determines required," so `housing.mi_monthly` / `mi.required` are already
produced. A new MI producer would re-derive what the product surfaces. This is the **third** time a census
candidate has been abandoned for redundancy against an existing surface rather than built — the standing
discipline: before building a producer, check whether the fact is ALREADY produced (by the product, by an AI
tag, by an existing derived recipe) and promotable, not just whether it is "missing" from the consuming rule's
subject.

**The subject-shape rule (a load-bearing constraint the batch re-hit).** A transaction-subject AI group
(`txn_nsf`, producing `txn.is_nsf_or_overdraft`) must NOT set `applies_to` — that key gates/gathers documents
and is meaningful ONLY for a document- or borrower-subject group. A transaction- or loan-subject group uses
`applies_to: all` / omits it. The declaration loader enforces this (a `DeclarationError`); recorded here so the
next transaction/loan-subject producer does not re-trip it.

**What shipped.** Three producers, zero rules: `income.is_self_employed` (#1, deterministic promotion, the ONE
new vocabulary tag), `txn.is_nsf_or_overdraft` (#2, AI/transaction — AS-7's rule HELD on calibration and only
lacked the producer), `occupancy.rental_support` (#3, AI/loan — IN-14 ships ratify and only lacked the
producer); the latter two already existed in `fact_tags.csv`, so they add production wiring but no vocab tag.
Plus two standalone labeling fixtures supplying the positive classes LP-395 measured as too thin: six VOE + six
offer-letter docs (`offer_letter_present` had n=0), and six other-income borrowers (`continuance_3yr` had n=1).
The rules those producers unblock (IN-12 / AS-7 / IN-14) activate in their OWN later tickets — a producer batch
activates nothing.

**Cross-refs.** LP-396 (the IN-12 / IN-14 activation bars), LP-385 (`_borrower_attributed_documents`), LP-333
(derived-last, why a derived recipe sees AI tags), ADR-330 (the enum-vs-number affordance for `not_applicable`),
LP-395 (the calibration-n measurements the fixtures raise).

## ADR-332: The limit of synthetic calibration — four of seven blocking tags are NOT labelable on invented fixtures without labeling our own invention; some tags need REAL files (LP-420)

**The context.** LP-420 set out to generate ONE Priya labeling session unblocking seven rules (IN-8, IN-9,
IN-12, IN-13, IN-14, AS-7, OC-1) by writing blind worksheets for the six/seven AI tags each blocks — the OC-1
economics lesson (never run a calibration wave for a single rule). The D1 labelability census (the ticket's own
gate: "never spend her time on a thin or one-sided tag") found only THREE of the seven pass. The other four are
not a scheduling problem — they are a **structural** one, and naming it is the ADR.

**The finding — a synthetic fixture cannot calibrate a tag whose correct label IS the content we invent.** The
owner-match precedent (LP-398/399) established that inventing a fixture is legitimate when the invention creates
a GENUINE judgment the labeler uniquely settles (does "Jordan M Rivera" match borrower "Jordan A Rivera"?). It is
NOT legitimate when the invented content DETERMINES its own label — then Priya would be "labeling our own
invention," measuring nothing. Four tags fall on the wrong side:

- **`income.type` (IN-12, IN-13).** 25 rows but one-sided (23/25 base wage), with an EMPTY positive class for
  `self_employment` (IN-12's gate) and `rental` (IN-13). Correction (LP-420 review): this is a FIXTURE gap, not
  a structural one — `income_amounts.applies_to` is `[pay_stub, w2, uniform_residential_loan_application]` and
  its `type` value space already includes `self_employment`/`rental`, so a self-employed / rental **1003** (the
  shape LP-419's self-employed fixture uses, `employment_type=self_employed`) WOULD produce those values; the
  producer need not be changed to read tax returns. The reason to exclude it is the ADR's OWN thesis: authoring
  such a 1003 STAMPS the income type, so labeling `income.type` on it reads back our invention (the type IS the
  label) — a labeling-our-own-invention exclusion, not a reachability one. The genuine unblock is a REAL file
  carrying a self-employment / rental income document, or a materially different fixture whose type is not the
  authored field.
- **`txn.is_nsf_or_overdraft` (AS-7).** n=0 anywhere. A line reading "NSF FEE" pre-answers itself; the only
  genuinely-ambiguous cases (an overdraft-protection transfer, an unlabeled $35 fee) turn on how the tag is
  DEFINED — a prompt question, not an accuracy measurement. Needs REAL bank statements with genuine NSF activity.
- **`occupancy.rental_support` (IN-14) + `occupancy.consistent_with_signals` (OC-1).** Both LOAN-subject — ONE
  row per loan. Reaching n>=6 means authoring 6+ whole loan files whose declaration-vs-signal (in)consistency, or
  lease-vs-rental adequacy, is the exact thing being judged. The invention authors the answer.

**The rule (named).** Before generating a calibration worksheet, ask not only "is n>=6?" but "would the labeler
be judging a GENUINE ambiguity, or reading back the content we authored?" A tag whose correct label is
determined by the fixture we invent is **not calibratable on synthetic data** — it needs real files (for
`income.type`, a real self-employment / rental income document, since authoring one stamps the type we would be
"measuring" — NOT a producer change; `income_amounts` already reads the 1003 where those types can appear). This is the counterpart to
LP-395's thin-n / empty-class lesson: n can be sufficient and the tag still un-calibratable, because the
DISTRIBUTION is authored, not observed.

**What shipped.** Worksheets for the three tags that pass (a genuine two/multi-sided distribution on LP-418's
committed fixtures): `income.voe_present`, `income.offer_letter_present` (IN-8, IN-9) and `income.continuance_3yr`
(advances IN-13). The four exclusions are reported with what each actually needs (a real self-employment/rental
income file / real bank statements / real occupancy files), and pinned by census-guard tests so they cannot
silently rot back into "just run a labeling round."

**Cross-refs.** LP-395 (thin-n / empty-class), LP-398/399/401 (the blind-worksheet pattern and legitimate
invented ambiguity), LP-406-4 (OC-1's tag measures declaration consistency; LF-6T3N states no occupancy), LP-418
(the voe/offer/continuance fixtures), LP-419 (`income.type` unscored; IN-12's self-employment gate).

## ADR-333: The extraction→snapshot boundary is lossy for nested typed structures — a signal can be extracted correctly and still be invisible to every producer (LP-421)

**The finding (named).** A document type's extractor can produce a field as fully TYPED CORE and that field can
still never reach a rule — because the extraction→snapshot mapping (`documents_section.build_document_fields`)
flattens each field through `_scalar`, which returns `None` for any nested structure (a list or object) and the
loop `continue`s. So `tax_return`'s `schedule_c` / `schedule_e` (self-employment / rental — typed, coerced,
correct at extraction) were **dropped at the snapshot boundary**; every producer reads the snapshot, so the
signal was gone before any producer ran. Extraction correctness is necessary but NOT sufficient for a signal to
be usable — it must also be SURFACED.

**The third instance of "built but not connected."** This is now a recognizable class:
1. `DtiOverride` — applied in the DTI calculation but not a snapshot fact, so no rule could see the overridden
   line (the LP-416 vacuity-sweep finding).
2. `compute_self_employed_income` — a real, transparent calculator in services, never wired into
   `snapshot.calculations`, so nothing feeds it (LP-323-IN-B).
3. `schedule_c` / `schedule_e` — extracted as typed core, dropped by `_scalar` at the snapshot boundary (this
   ticket).
The pattern: a component is BUILT and CORRECT in its own layer, but the connective tissue to the layer that
consumes it was never laid. The census lesson generalizes — "is it produced?" is the wrong question; "is it
reachable by the consumer?" is the right one.

**The fix pattern (ADR-061, reused not reinvented).** `bank_statement` transactions were the same shape of
problem — a nested list `_scalar` can't flatten — solved by a FIRST-CLASS TYPED PATH: a frozen record model
(`TransactionRecord`), an optional field on `DocumentEntry`, a reshape gated on `document_type`, and the same
per-field coercion the flat core uses. LP-421 extends exactly this: `ScheduleCRecord` (a list, like transactions)
and `ScheduleERecord` (the two-level shape — an object carrying a `properties` tuple), reshaped by
`build_schedule_c` / `build_schedule_e`, surfaced as `DocumentEntry.schedule_c` / `.schedule_e`. No new
nested-data mechanism was introduced (the standing stop condition). Two deliberate differences from transactions:
schedules carry **no `content_id`** (a schedule is document-level, not a rule-enumerated subject), and are **not
folded into the document content-id fingerprint** (`_document_base` untouched) — so every existing document's
`fields` and `content_id` stay byte-identical (the equivalence that mattered most, `build_document_fields` being
shared by every type).

**What was surfaced, for which consumer.** `schedule_c` (business_name / gross_receipts / total_expenses /
**net_profit**) for the self-employment signal (IN-12); `schedule_e` (total_net_rental_income / depreciation +
**properties**[address / **rents_received** / total_expenses / net_income]) for the rental signal (IN-13). `k1s`
was NOT surfaced — no consumer today (surfacing unused structure is cost with no benefit). Absent≠empty: no
schedule → `None`, never a fabricated empty record.

**The STARTER-extractor caveat the downstream rules inherit.** `tax_return`'s prompt is explicitly a
`STARTER PROMPT — REPLACE WITH / MERGE INTO THE POC + PRIYA TAX-RETURN PROMPT`, and a tax return is "the most
varied, multi-schedule … tested only against constructed inputs is especially risky." **This plumbing makes the
schedules REACHABLE; it does NOT make them TRUSTWORTHY.** A rule that gates on Schedule C presence would rest on
an extractor never validated against a real return. The honest ending is *reachable now; trustworthy after golden
files* — the producer (income.type / is_self_employed mapping) and the golden-file validation are their own later
tickets; LP-421 surfaced the structure only.

**Cross-refs.** ADR-061 (the transactions typed path), LP-302a (`DocumentEntry.transactions`), the LP-420
follow-up investigation (income.type's self_employment/rental structurally unreachable — this is its plumbing
half), LP-419 (`build_self_employed_no_history_snapshot`, a flat stub, left alone), ADR-330/LP-416 (`DtiOverride`
not a snapshot fact), LP-323-IN-B (`compute_self_employed_income` unwired).

## ADR-334: A tag has exactly one producer — a schedule signal cannot feed an AI-only tag; and a DETERMINISTIC producer is the escape hatch from ADR-332's synthetic-calibration limit (LP-422)

**Two findings from wiring the LP-421 schedules to a consumable tag.**

**1. A tag has exactly one producer — so a fact cannot join an AI-produced tag.** `tag_production.yaml` is a
`dict[tag_id → one declaration]` with a single `mode`; `load_declarations()` keys one `TagDeclaration` per
tag_id. So a tag is EITHER `ai` OR `derived` OR `parsed` — never mixed, never two producers on different document
types. `income.type` is `ai` (`income_amounts`, reading pay_stub/w2/1003). The natural instinct — "add a
deterministic producer that sets `income.type = self_employment` / `rental` from a tax return's schedules" — is
therefore **structurally impossible**, not merely inadvisable. The consequence for any future mixed-source
signal: a deterministic fact that wants to reinforce or stand in for an AI tag needs its OWN tag (at the subject
the consumer reads), not a second producer on the AI tag. LP-422 did exactly this: it did not touch
`income.type`; it extended the borrower-level derived `income.is_self_employed` (Schedule C presence, reusing the
LP-418 tag IN-12 already gates on) and added a new borrower-level derived `income.has_rental_income` (Schedule E
presence OR `income.type == "rental"` — the same dual-signal shape, for IN-13's rental scope). A new tag is
needed not because `income.type` "can't carry rental" (it can — `income_amounts` reads the 1003 and its value
space includes `rental`) but because `income.type` is AI-only, so the deterministic Schedule-E signal cannot be
a second producer for it.

**2. A DETERMINISTIC producer is the escape hatch from ADR-332.** ADR-332 named the limit of synthetic
calibration: an AI JUDGMENT tag whose correct label is determined by the fixture we invent cannot be calibrated
on synthetic data (income.type's self_employment/rental were excluded from labeling for exactly this). The escape
hatch, named here: **where a FACT can substitute for the judgment, no labeling round is needed at all.** Schedule
C / Schedule E PRESENCE is a fact (a form is attached or not), not a judgment — so a deterministic producer reads
it with no AI, no worksheet, no Priya bar. This is why LP-422 unblocks the self-employment / rental scope that
LP-420 could not calibrate: it replaced the un-calibratable judgment (what income TYPE is this?) with a
calibration-free fact (is a Schedule C/E present?). The reusable rule: before commissioning a calibration round
for a scope signal, ask whether a surfaced structural FACT already answers it deterministically.

**Presence, not value (ADR-324 reaffirmed).** The producer gates on PRESENCE, never a threshold: a Schedule C
showing a LOSS is still self-employment; a Schedule E for a zero-rent year is still rental. "Is $X of net profit
enough to count" is a RULE question, not a tag question. Fail closed: no schedule → `unknown` (or, for a filed
return with no Schedule E, `no`) — NEVER a fabricated `base` (a tax return without a Schedule C does not make the
borrower a wage earner; it says nothing).

**The STARTER-extractor caveat the consuming rules inherit (surfaced, not decided — LP-421/ADR-333).** The
tax-return extractor is a self-declared STARTER, never validated against a real return. This producer faithfully
translates whatever it surfaces, so IN-12 / IN-13 would activate on an UNVALIDATED extraction path. The failure
mode is milder than a misread number — a wrong SCOPE (a rule applies or not) rather than a wrong figure — but no
golden files exist. LP-422 surfaces this as the open question the RULE ticket must answer; it writes no rule and
decides no activation.

**Cross-refs.** ADR-332 (synthetic-calibration limit — this is its escape hatch), ADR-333 / LP-421 (the surfaced
schedules), LP-418 (`income.is_self_employed`, the reused tag), LP-419 (IN-12 gates on it), ADR-324 (tags
describe, rules judge), LP-420 (why income.type couldn't be calibrated).

## ADR-335: A rule's available gate can be narrower than its intent (never narrow the rule to fit the tag); and the standing rule for ACTIVATING on an unvalidated extractor — when the failure mode is a backstopped wrong-scope (LP-423)

**Two decisions from settling IN-12 / IN-13's activation.**

**1. The available gate is narrower than the rule's intent — do NOT narrow the rule to fit the tag.** LP-422
proposed re-scoping IN-13 onto `income.has_rental_income`. But IN-13 is "Other income continuance" — its scope
is EVERY borrower with non-employment income (child support, alimony, pension, an award, Social Security, notes,
AND rental — LP-420's continuance worksheet built six distinct types). Rental is ONE. Gating IN-13 on the rental
tag would SILENTLY NARROW it, dropping five of six income types — a coverage regression disguised as a fix. The
tag we happened to build (rental presence) is narrower than the rule's intent (all other income). The rule:
when the only available gate is a proper subset of a rule's scope, gating on it is a silent under-coverage bug,
not a fix — STOP and report; the real gate (here, a borrower-level "has other income" signal) may not exist and
becomes its own ticket. IN-13 was NOT re-scoped; it stays held (and independently, its verdict tag
`income.continuance_3yr` is uncalibrated — LP-420's worksheet is unlabeled — so it would stay held regardless).

**2. Activating on an UNVALIDATED extractor — the standing precedent.** Both IN-12 and IN-13's scope gates now
rest on the tax-return extractor, a self-declared STARTER (ADR-333) with NO golden files. The activation decision
turns on the FAILURE MODE, and the two rules differ decisively:
- **IN-12 (activated).** A missed Schedule C → `is_self_employed` no/unknown → IN-12 `not_applicable`. That is a
  wrong SCOPE, VISIBLE as absence — and the borrower's 2-year-history gap is STILL surfaced by IN-11 (live,
  income-type-agnostic), so no finding is lost. The verdict tag (`has_2yr_history`) is Priya-validated at 0.9 /
  measured 100% (inherited from IN-11, the IN-6 same-tag-same-evidence pattern), so the VERDICT is never a false
  green. ⚠️ Correction (LP-423 review): the gate is NOT purely a deterministic Schedule-C fact — `is_self_employed`
  still needs the UNSCORED `income.type` for its "no" → not_applicable determination (a W-2 borrower) and as an
  `income.type == self_employment` secondary "yes" (a 1003-declared self-employment with no surfaced Schedule C).
  So the SCOPE has a bounded FP: an `income.type`-misclassified wage earner (no Schedule C) makes IN-12 apply and
  FIRE a spurious self-employment finding when `has_2yr_history == "no"`. Accepted because it is low-probability
  (clean W-2/pay-stub wage income is unambiguous), BOUNDED (it only co-occurs with an IN-11 finding on the same
  borrower — noise IN-11 already makes, not a new false green), and never a false VERDICT. `income.type` is
  therefore kept in `load_bearing_ai_tags`; `measured_accuracy` reflects the VERDICT tag, not the scope gate.
  → **ACTIVATED** (calibratable-now, validated, eligible — the accepted scope risk is bounded).
- **IN-13 (held).** A missed Schedule E (were it gated on rental) → `not_applicable` → the rule SILENTLY decides
  it does not apply and never checks a borrower who does have that income. Silent UNDER-coverage — the kind a
  processor would not notice. Plus its verdict tag is uncalibrated. → **HELD.**

**The standing rule (Credit will face this 13 times).** A rule fed by an unvalidated extractor MAY activate when
its failure mode is a WRONG SCOPE that a live rule BACKSTOPS (visible under-coverage that loses no finding) AND
its verdict is independently validated; it must NOT activate when the failure mode is SILENT under-coverage (a
`not_applicable` nobody notices) or when the verdict itself is uncalibrated. The activation basis — and the
accepted risk (the unvalidated extractor) — is recorded in the bar rationale (the LP-412 discipline), not just
the flag. Geet's call to activate IN-12 on the starter extractor; Priya's view on the real-world Schedule-C
miss-rate is the follow-up refinement, and golden-file validation of the tax-return extractor remains its own
ticket (the honest ending: LIVE now on a coarse deterministic gate, sharper once the extractor is validated).

**Cross-refs.** ADR-333 (the STARTER tax-return extractor), ADR-334 (the deterministic gate / ADR-332 escape
hatch), LP-419 (IN-12 written + held), LP-422 (the schedule-presence producer), LP-420 (the continuance worksheet
+ the six other-income types), IN-11 (the live backstop for a missed IN-12 scope), IN-6/LP-412 (inherit the
verdict tag's validated bar).

## ADR-336: A live BASE rule can ride an UNSCORED tag — the gate cannot protect a rule that predates it without deactivating it; and the bar loader CAN see a rule's kind (LP-424)

**Context.** LP-424 item 2 set out to backfill activation bars for the 11 `_BASE_ACTIVE` rules — the rules that
were activated BEFORE the eligibility gate existed (LP-389) and so carry no bar and no `measured_accuracy`. The
goal: a future tag/prompt regression would then trip the gate. It STOPPED on a structural wall and a real finding.

**The structural wall.** `load_activation_bars()` fail-louds unless the bars file covers EXACTLY the non-base
CANDIDATE rules (`specs − _BASE_ACTIVE`); and the activation invariant is `ACTIVE_RULE_IDS = _BASE_ACTIVE ⊎
eligible_candidates` (base and gated disjoint). A base rule cannot get a bar without either relaxing that
fail-loud contract (and then a base rule's eligible bar would double-count in `ACTIVE − BASE == eligible`,
breaking the invariant) or MOVING it out of `_BASE_ACTIVE` into the gated set. Backfilling is therefore a
re-architecture of the base/gated split, not a bookkeeping fill.

**The finding (named) — a live rule can ride an unscored tag, and the gate cannot retro-protect it.** Moving the
base rules into the gate would DEACTIVATE any whose tag has no measurement — and **OC-2** is exactly that: it is
LIVE via `_BASE_ACTIVE`, reads `occupancy.consistent_with_signals` (AI, UNSCORED — the same tag OC-1 is held on),
and predates the gate, so the gate never checked it. This is safe TODAY only because OC-2 is JUDGMENTAL and so
RATIFIES every verdict (a human signs each — LP-376-B; already documented in OC-1's bar), never an auto-verdict
on an unmeasured tag. But it means a live rule rests on something no bar measures, and the gate cannot be
extended to cover it without deactivating it. **That is Geet's call** (deactivate OC-2 pending calibration, or
formally accept it as ratify-only on an unscored tag), not a silent change — so item 2 STOPPED and reported it.
The general rule: a rule activated before the gate can rest on an unmeasured input the gate would reject; giving
it a bar is a re-activation decision (may deactivate), never a backfill. Pinned by a test so OC-2 can never be
flipped to auto.

**The counterpart confirmation (item 3).** The bar LOADER CAN see a rule's kind — `rule_kinds.csv` via
`kind_for()` (no import cycle; kinds.py depends only on stdlib). So the loader now REJECTS `ships: auto` on a
judgmental rule at load time (a bar that claims auto for a rule the runtime always ratifies is a lie — the
LP-390-7 AS-5 fail-loud pattern). This is NOT the calc-only limit LP-411 hit (`threshold_needs_signoff`): `kind`
is available to the loader, so this guarantee IS enforceable at the bar layer. No current bar violates it (all
four judgmental bars — AS-12, IN-7, IN-13, IN-14 — correctly ratify).

**Also recorded (item 1).** `rule_tags.csv` has drifted, but the drift is STRUCTURAL, not stale-for-a-few-rules:
the CSV is a DATA-LINEAGE map (rule → its raw INPUT tags — PC-7 → `contract.closing_date`) while the live spec's
`load_bearing_tags` is the DIRECT-READ set (PC-7 → the derived `contract.days_until_closing`). They differ for
nearly every rule by design. A spec-driven regeneration would change the artifact's SEMANTICS and fight the
xlsx-driven generator — a CSV-contract decision, deferred. Nothing reads `rule_tags.csv` at evaluation (the
evaluator reads specs), so the drift is planning-only (pinned by a test).

**Cross-refs.** LP-389 (the gate + `_BASE_ACTIVE`), LP-406-4 (OC-1 / the unscored occupancy tag), LP-376-B (a
judgment rule always ratifies), LP-390-7 (the AS-5 fail-loud guard), LP-411 (the calc-only threshold-signoff
limit — the contrast), LP-406-2b (nothing reads rule_tags.csv at runtime).

### Resolution — the OC-2 acceptance (LP-425)

LP-424 recorded the OC-2 finding and framed it as "Geet's call." LP-425 IS that call — recorded here, in the
same ADR (rather than a new one), so a reader finds the finding and its resolution together.

**THE DECISION: OC-2 stays LIVE, ratify-only, on the unscored `occupancy.consistent_with_signals` — ACCEPTED,
deliberately.** Not deactivated.

- **The fact (re-confirmed from the code, LP-425 Phase 0):** OC-2 ∈ `_BASE_ACTIVE`; its kind is JUDGMENTAL, so
  `judgment.py` hard-codes `ratification_pending=True` — every OC-2 verdict goes to a human (LP-376-B); its
  load-bearing AI tag `occupancy.consistent_with_signals` is UNSCORED (0 labels — never calibrated; LP-406-4;
  it measures DECLARATION consistency, not address signals, LP-371-D3). OC-2 predates the LP-389 gate, so it
  never passed one — it is live by HISTORY, not by a decision.
- **Why accept, not deactivate:** ratification is real human review — every OC-2 verdict is signed off, so the
  unmeasured tag CANNOT produce a trusted automated answer (the ships-mode already mitigates the exact risk an
  unscored tag poses). Deactivating would trade REAL coverage (occupancy consistency, surfaced to a human) for a
  risk that is already contained. The problem LP-424 found was the ABSENCE OF A DECISION, not the behaviour.
- **THE EXIT CONDITION:** this acceptance ends when `occupancy.consistent_with_signals` is CALIBRATED (labels →
  measured accuracy → a Priya bar) — which OC-1 requires anyway (LP-406-4). Calibration needs REAL occupancy
  files (the tag can't be scored on synthetic data — ADR-332). Once scored, OC-2 can move OUT of `_BASE_ACTIVE`
  INTO the gate with a real bar, and the whole `_BASE_ACTIVE` set can be reconsidered (the LP-424 item-2
  re-architecture).
- **THE GUARD (what the acceptance rests on):** the acceptance is valid ONLY WHILE OC-2 RATIFIES. `test_lp425_
  oc2_acceptance` pins OC-2 ∈ `_BASE_ACTIVE` + judgmental + ships:ratify, so any future change that made OC-2
  auto-ship fails loud. Provenance is also left at `_BASE_ACTIVE` in registry.py (the AS-5 lesson: a value with
  no recorded reason gets mistaken for an oversight).

**THE SCOPE — exactly which rules this covers (the sibling check, LP-425 Phase 0):** the acceptance covers
**OC-2 ALONE.** OC-2 is the ONLY live rule on a GENUINELY UNSCORED AI tag. The other AI-dependent base rules were
examined and are NOT in scope:
- **AS-1** (calculative → auto) reads `txn.is_money_in` — MEASURED 98% (n=50, LP-337/340). Robustly scored; fine.
- **ID-9** (judgmental → ratify) reads `id.poa_present_and_acceptable` — MEASURED n=2, 100% (LP-334). A close
  cousin (thinly measured, ratifies) but NOT unscored — not in scope.
- **ID-7** (structural → AUTO) reads `id.title_vesting_consistent` — MEASURED n=2, 100% (LP-334). NOT unscored,
  but it auto-ships on a THIN (n=2) measurement — a distinct, milder concern (the LP-395/AS-6 thin-n lesson),
  NOT the unscored-tag acceptance. Flagged here so it is not silently swept under this decision; its own review
  (widen n before trusting the auto-ship) is a separate item.

No rule auto-ships on a genuinely unscored tag; the acceptance names its one covered rule and covers no other.

**Cross-refs (acceptance).** LP-424 (the finding), LP-406-4 (OC-1's held state + what the tag measures), ADR-332
(why the tag can't be calibrated on synthetic data → the exit condition needs real files), LP-376-B (the
ratification armor the acceptance rests on), LP-334 (the id.* / is_money_in measurements the sibling check reads).

## ADR-337: An AI continuance judgment that honestly hedges to `unknown` is the SIGNAL to spin off a DETERMINISTIC producer — the child-support case is arithmetic (child age vs a termination age), not a prompt bug (LP-427)

**Context.** LP-427 scored `income.continuance_3yr` against Priya's six blind labels (`docs/calibration/
income-continuance-3yr-labels.csv`, LP-420's worksheet). The live sonnet-4-5 reasoner scored **5/6** on a thin,
skewed n (5 `yes` / 1 `no` — the single negative is `note_receivable`, matures 2027). The one miss is
**`child_support`**: Priya labeled `yes`, the AI produced **`unknown`** (confidence 0.7). Its reasoning was not
wrong — it was HONEST: *"the youngest child is age 9. Child support typically continues until age 18, ~9 years
remaining, but without court orders or other documentation… the exact continuation horizon cannot be determined
from income documents alone."* Priya's `yes` came with a note: *"Still child reach 16, this is counted yes"* — she
KNOWS her jurisdiction's termination age and computed 9 → 16 = 7 years > 3.

**The decision — the disagreement is a DEFINITIONAL DIVERGENCE, not a prompt bug; the fix is a deterministic
child-support producer, NOT a higher AI bar.** Three things follow, all recorded, none built (LP-427 measures and
records; it changes no tag/prompt/rule):

1. **Why not a prompt fix.** The AI hedged CORRECTLY given its inputs — a continuance *judgment* over free income
   text cannot fix a termination date it has no court order for, and forcing it to guess `yes` would make it
   WORSE (it would guess `yes` on a 17-year-old too). Raising IN-13's future bar or "sharpening the prompt" would
   paper over a computation the model should not be doing by judgment at all. 5/6 here is the model being right
   about the limit of its own evidence, the same shape as ADR-330's `continuance_3yr=unknown` on a W-2.

2. **Why it IS deterministic (the ADR-334 escape hatch).** Child-support continuance is ARITHMETIC given two
   facts: the child's age (a 1003 field) and a termination age (a domain constant). `termination_age −
   child_age >= 3` → continues. Where a FACT substitutes for a judgment, ADR-334 says no labeling round is needed
   — a deterministic producer sidesteps ADR-332's synthetic-calibration limit. So `child_support` continuance is
   a candidate deterministic producer, FLAGGED (not built): what it needs is (a) the youngest child's age as an
   extracted field (today it lives only in the free-text `other_income_description`, an ADR-333 lossy-boundary
   gap), and (b) the **termination age pinned with Priya** — her note says 16, common defaults are 18, and it is
   plausibly **state-dependent** (a jurisdiction table, not a scalar). Until (b) is a confirmed domain constant
   the rule cannot be built; that is a domain question for the sister, not a coding decision.

3. **The second candidate rule is NOT deterministic — it stays a documentation judgment.** Priya's pension and
   Social Security notes both say *"Need award letter, could be social security award letter, school award
   letter."* That is the LP-393-6 pattern again: the continuance TAG judges the substance (`yes`, both scored
   correctly), and a SEPARATE rule enforces the documentation standard — "pension / SS income present ⇒ an award
   letter must be in the file." Unlike child support, "is an award letter present (in any of its variants)?" is a
   PERCEPTION over documents (like `voe_present` / `offer_letter_present`), so it needs a producer AND a labeling
   round — it is not arithmetic. Both candidate rules are recorded in `docs/tickets/LP-427.md`; neither is built.

**What LP-427 did NOT do.** No bar is proposed for `income.continuance_3yr` / IN-13. 5/6 clears no reasonable
threshold, the miss is a definitional case a bar would not fix, the n is thin and skewed, and — decisively — a
bar would activate nothing anyway: IN-13 stays **not-calibratable-yet** on its OTHER blockers (the missing "has
other income" scope gate, ADR-335; and `income.type`, its second load-bearing tag, still unscored). LP-427
removes exactly ONE of IN-13's blockers (the uncalibrated verdict) and says so — it does not activate IN-13.

**The normalization discipline (LP-393-4a).** Three of Priya's labels came back as `"yes - Read note columnd for
condition"` (her typo + trailing space preserved). Geet confirmed these are `yes` and the note is a separate
documentation requirement. The CSV normalizes `golden_label` to `yes` for scoring but PRESERVES her original
wording verbatim in `labeler_note` and keeps her added `Note` column intact — the label was not silently
rewritten to a bare `yes`; the record of why it changed travels with it.

**Cross-refs.** ADR-334 (one producer per tag; the deterministic escape hatch this invokes), ADR-332 (the
synthetic-calibration limit the escape hatch sidesteps), ADR-333 (the lossy extraction→snapshot boundary — why
the child's age is not yet an extracted field), ADR-335 (IN-13's missing scope gate — a second, independent
blocker), ADR-330 (`continuance_3yr=unknown` on a W-2 — the model being right about its own evidence limit),
LP-393-6 (the documentation-standard-is-a-separate-rule ruling both candidates follow), LP-393-4a (originals
preserved when a label is normalized), LP-420 (the blind worksheet), LP-423 (IN-13 held on two reasons).

## ADR-338: A multi-tag rule's activation bar measures its VERDICT-DRIVING (routing) tags, not every tag it reads — but excluding a non-routing tag that still gates couldnt_check needs a bounded-failure argument, not a "reason-only" claim (AS-6, the first multi-tag rule; LP-429, corrected)

**Context.** LP-404 turned AS-6 (account ownership) into the FIRST multi-tag rule: it reads THREE `stmt_facts`
tags and combines them into Priya's surface-don't-reject ruling — `owner_matches_borrower=no` → fired (a
third-party account, excluded), `owner_matches_borrower=unknown` → needs_review, `non_borrower_co_holder=yes` →
needs_review, `owner_matches_borrower=yes` → satisfied (the middle rows COUNT — the statement is used while a
human confirms). LP-429 activates it on Priya's 0.95 sign-off. The activation surfaced a genuinely new question,
because the three tags scored DIFFERENTLY against her labels (LP-402/403):

- `owner_matches_borrower` — **11/11** (drives fired vs satisfied)
- `non_borrower_co_holder` — **11/11** (drives the joint-account needs_review row)
- `holder_name_variance` — **5/11** vs her exact labels (drives the REASON string shown on a needs_review row)

**The decision — the bar's `measured_accuracy` is the min over the tags that DRIVE THE VERDICT (the ROUTING),
not the min over every tag the spec reads.** AS-6's routing (which of fired / needs_review / satisfied a
statement lands in) rests entirely on `owner_matches_borrower` + `non_borrower_co_holder`, both 11/11 → the bar
measures 1.0 ≥ 0.95 and AS-6 activates. `holder_name_variance` at 5/11 does NOT gate the bar.

**Why `holder_name_variance` is excluded from `measured_accuracy`.** The activation bar exists to answer "can the
automated VERDICT be trusted?" The routing among PROCEEDING statements (fired / needs_review / satisfied) rests
entirely on `owner_matches_borrower` + `non_borrower_co_holder` (both 11/11); `holder_name_variance`'s 5/11 is
accuracy vs Priya's exact variance CATEGORY (nickname / surname / other), which appears only in the reason string
on a `needs_review` row a human already inspects. Folding its 5/11 in would conflate "is the verdict trustworthy"
(yes, 11/11) with "is the explanation always perfectly worded" (no, 5/11) and would BLOCK a rule whose routing is
provably correct.

**⚠️ CORRECTION (LP-429 review): `holder_name_variance` is NOT purely reason-only — it is AS-6's couldnt_check
GATE.** AS-6's spec has `gated_tags: [stmt.holder_name_variance]`: at runtime `holder_name_variance == unknown` →
AS-6 `couldnt_check` (the name could not be compared), and only a non-unknown value lets AS-6 proceed to the
routing. So it IS verdict-affecting — via the couldnt_check gate, not the fired/satisfied routing. The 5/11 is
its CATEGORY accuracy (the reason dimension); the GATE dimension is only unknown-vs-not, whose reliability is not
separately measured. The exclusion from `measured_accuracy` is still defended, but on the correct basis: a wrong
gate value is BOUNDED and safe-direction — a false-unknown produces a VISIBLE `couldnt_check` (a missed check
surfaced as a gap), never a false AUTO verdict (a genuinely unreadable holder name would also leave
`owner_matches_borrower` unknown → needs_review, and the routing verdict is `owner_matches`-driven at 11/11). So
`holder_name_variance`'s accuracy cannot manufacture a wrong satisfied/fired. Measuring the gate's unknown-vs-not
accuracy separately from the 45% category accuracy is a follow-up refinement.

**This REFINES the LP-390-5a weakest-tag rule, does not contradict it.** LP-390-5a — "the bar takes the weakest
load-bearing tag" — was written for single-verdict-driving tags and remains correct for them: among the tags
that DRIVE the verdict, the bar still takes the weakest (here min(11/11, 11/11) = 1.0). ADR-338 only clarifies
the SET that rule ranges over for a multi-tag rule: the verdict-driving (routing) tags, not the reason-decoration
tags. The bar's `load_bearing_ai_tags` is set to exactly the two routing tags; `holder_name_variance` is
deliberately excluded, with the reason recorded in the bar so the exclusion is auditable, never silent.

**The test that keeps this honest (corrected, LP-429 review).** A tag may be excluded from a multi-tag rule's
`measured_accuracy` only when it is not a ROUTING driver — its value must NOT appear in a `when_tags` /
`when_compare` predicate that selects an AUTO (satisfied/fired) verdict. But excluded ≠ harmless: a tag in
`gated_tags` (like `holder_name_variance`) DOES affect the verdict via the couldnt_check gate, so the exclusion
requires the extra safety argument above — the gate failure must be bounded to a VISIBLE couldnt_check, never a
false AUTO verdict. (The original wording of this test checked only `when_tags`/`when_compare` and OMITTED
`gated_tags` — the gap that let `holder_name_variance` be miscalled purely reason-only.) If a future edit made
`holder_name_variance` route a verdict (a `when_tags`/`when_compare` predicate), it would become a routing driver
and MUST re-enter `measured_accuracy` and be re-measured. AS-6's spec routes only on `owner_matches_borrower` +
`non_borrower_co_holder` (with `holder_name_variance` in `gated_tags`), so the exclusion holds under the
bounded-couldnt_check argument; a spec change is the trigger to revisit it.

**What LP-429 did NOT do.** It did not resolve the N2/P2 variance taxonomy residual (she labeled N2 (Roberta) =
`nickname`, P2 (Bob) = `other`; the AI says the reverse, and the conventional reading favours the AI) — a Priya
taxonomy round, its own ticket; AS-6 ships with it recorded. It did not widen `stmt_facts`' applicability (the D5
gap: investment/brokerage statements are not ownership-checked at all) — its own ticket. And the negative FN
direction is proven only on the LP-401 SYNTHETIC cases (the 5 real LF-6T3N statements are all `yes`) — the
synthetic-data caveat AS-6 ships with.

**Cross-refs.** LP-404 (the multi-tag rule + its 4-fired/5-needs_review/2-satisfied proof), LP-397 (the proposed
bar + its now-met ratify caveat), LP-402/403 (the re-scores: routing tags 11/11, variance 5/11 + the residual),
LP-390-5a (the weakest-tag rule this refines), LP-412 / LP-428 (the sign-off-is-the-activation pattern), LP-424
(the ships-mode-matches-kind cross-check — structural → auto is legal), ADR-335 (a rule's gate narrower than its
intent — the D5 stmt_facts applicability gap is the mirror: the tag's coverage narrower than the rule's reach).

## ADR-339: A documentation-standard check spun off a judgment tag is a DETERMINISTIC per-borrower producer (date/presence facts, no calibration); and the documentation-SUFFICIENCY qualifiers (any-employer, dated-after) are a recurring Priya decision (IN-15, LP-430)

**Context.** Priya's B14 ruling (LP-393-6) split a documentation standard OUT of the `has_2yr_history`
judgment: a terminated job's two years still COUNT as history (IN-11's concern), but whether the employment is
documented as CURRENT is a SEPARATE check. LP-430 builds that check as **IN-15** (terminated-employment
documentation) on her exact refinement: "terminated" = ANY employment end date in the past (no grace period);
ONE subsequent pay stub clears it.

**Decision 1 — the check is DETERMINISTIC, not a judgment (ADR-334 applied).** The question reduces to two
FACTS the file already carries as typed-core dates: the VOE's end date (`income.employment_end`, parsed) and the
pay stubs' pay dates (`income.pay_date`, parsed). "Is there a past end date, and if so a pay stub dated after
it?" is date arithmetic — no perception, no judgment. So IN-15 rides a **derived per-borrower producer**
(`income.terminated_employment`, an enum `cleared | needs_pay_stub | not_terminated | unknown`, computed over
the borrower's `_borrower_attributed_documents`), NOT an AI tag. Per ADR-334 a fact substituting for a judgment
needs **no calibration round** — IN-15 is `no-ai-dependency`, eligible on `input_resolves` alone (the IH-3/AS-8
path), and activates immediately (ACTIVE 34 → 35). This is the general shape for every "documentation standard"
Priya spins off a judgment tag: if it reduces to presence/date facts, it is a deterministic producer + a
no-ai-dependency rule, not a new calibration.

**Decision 2 — the reason ASKS FOR THE DOCUMENT, never asserts a fact about the borrower.** A missing pay stub
is a FILE GAP, not evidence the borrower is unemployed. IN-15's fired reason is *"employment shown as ended
{end_date}; a pay stub dated after that is needed to confirm current employment"* — it names the end date
(interpolated, the IH-3 pattern) and requests the document. It never says "unemployed" / "no longer employed".
This is a standing discipline for any missing-documentation rule: the finding is about the FILE, not the person.

**Decision 3 — the documentation-SUFFICIENCY qualifiers are Priya's, and they recur (flagged, not silently
chosen).** "One pay stub" is exact on the COUNT but silent on three qualifiers, each a documentation-sufficiency
judgment that will recur across future documentation checks:
- **Dated AFTER the end date?** YES — a pre-termination stub proves nothing. Decided (arithmetic:
  `pay_date > end_date`).
- **Same employer or ANY employer?** IN-15 takes the **permissive (any-employer)** reading: a new-employer pay
  stub clears it MORE convincingly (the borrower is employed again), and a same-employer-only test would wrongly
  fail a borrower who changed jobs (the wrong direction — a false FIRE on a genuinely-employed borrower). This is
  a **defensible default flagged for Priya**, not a silent narrowing — recorded in the bar so her sign-off (or
  revision) is a one-line change.
- **Does a VOE / offer letter also clear it?** She said "pay stub" specifically. IN-15 does NOT broaden her
  ruling — pay-stub-only — and the VOE/offer-letter question is flagged for her, not implemented.

**The scope boundaries (recorded, not resolved).** A FUTURE end date is a CONTINUATION concern (IN-13's
territory), not a termination → IN-15 is not_applicable (never a finding). An UNREADABLE end date on a present
VOE is an ABSENT `income.employment_end` tag (parsed dates are date-or-absent; there is no `employment_status`
tag), **indistinguishable from no-VOE without the AI `voe_present` tag** — so the deterministic rule treats it as
not_applicable (the never-accuse choice). A future AI-gated variant could distinguish it, but that would forfeit
the no-calibration property; the limitation is documented (LP-430 D4), not silently hidden.

**The IN-11 boundary (D2).** IN-11 (`has_2yr_history=no` → fired) and IN-15 (`needs_pay_stub` → fired) read
DISJOINT tags and produce provably distinct reasons (history vs the pay-stub documentation), so a terminated job
never surfaces two overlapping findings — the AS-8/AS-10, IN-11/IN-12 complementary-not-duplicate discipline.
IN-11/IN-12 are unchanged.

**Cross-refs.** LP-393-6 / ADR-316 (the B14 ruling that carved out the separate check), ADR-334 (the
deterministic escape hatch this applies), LP-421/422 (the derived-producer precedent — a fact promoted to a
borrower tag), LP-385 (`_borrower_attributed_documents`, the per-borrower promotion), LP-417 (the IH-3
no-ai-dependency date-compare + operand interpolation IN-15 mirrors), IN-11 (the history boundary). The three
OTHER rules Priya's answers implied — IH-1 (a spec rewrite), PE-1 (an FHFA table), the pay-stub-only rule (a
boundary check) — are their own tickets; only the terminated-employment check is built here.

## ADR-340: IH-1 is a loss-settlement-BASIS check, not the retired coverage-vs-loan arithmetic (Priya's ruling, effective 2026-03-18) — but its field is not extracted, so LP-431 STOPs at an extractor-extension boundary (LP-431)

**Context.** LP-431 set out to write IH-1 (insurance adequacy). The catalog (`rule_kinds.csv`) had it planned as
a CALCULATIVE rule — *"dwelling coverage vs loan amount/replacement — numeric compare"* (the classic 80%-of-
replacement-cost / coverage-vs-loan-balance test). **Priya's answer REPLACED that rule.** Her ruling, recorded
here with its stated basis so a future reader can re-check it:

**The regulatory premise (Priya's domain ruling — UNVERIFIED from the codebase; its stated effective date is on
record).** Fannie Mae / Freddie Mac **retired the coverage-vs-loan-balance and 80%-of-replacement-cost
comparison, effective 2026-03-18.** So IH-1 is no longer an arithmetic test. Her replacement is a **loss-
settlement-BASIS check**: `replacement_cost_basis = true → adequate`; `false → inadequate`; `missing → manual
review`. No percentage, no coverage/loan comparison. **This ADR does not verify the agency change — it records
that IH-1's entire shape rests on it, so the basis is auditable.**

**The decision — IH-1 is a three-outcome boolean check (satisfied / fired / couldnt_check), NOT calculative.**
That reclassifies it from the catalog's `calculative` to `structural` (a presence/basis read, no ratio, no Priya
threshold — so it would be `no-ai-dependency` and activate without a sign-off, the IH-3 shape). The catalog
description is now stale; it is updated when the rule is actually built.

**THE STOP (D1) — the field is not extracted, so the rule cannot be built yet.** The `homeowners_insurance`
extractor's TYPED CORE is `named_insured / carrier_name / policy_number / property_address / coverage_amount /
annual_premium / effective_date / expiration_date` — **no loss-settlement-basis field.** The extraction PROMPT
does not even solicit it (zero mention of replacement / settlement / ACV), so it will not reliably appear in the
grouped `additional_sections` catch-all either. Per **LP-405** (no rule may depend on the free-form,
per-document, uncoerced catch-all), IH-1 **cannot be built on the current extractor**. This is the PC-4/6/8/9 /
IH-2/IH-8 class: an **extractor-extension ticket** (add a typed-core `loss_settlement_basis` field, with
golden-file evidence), NOT a rule ticket. LP-431 therefore writes **no spec, no producer, no fixture, no
activation** — the honest outcome the ticket flagged as likely. A guard test pins the gap so the exclusion cannot
silently rot (the LP-420 census-guard discipline).

**The ACV-roof nuance cannot be honored yet.** Priya noted *"roof coverage may be settled on an actual-cash-value
basis"* — so an ACV roof must NOT fail a replacement-cost dwelling policy. That requires PER-ITEM settlement
granularity, which the extractor also lacks (there is only one policy-level basis, and it is not extracted at
all). The extractor extension must carry both the dwelling basis AND the per-item (roof) exception, or IH-1 would
false-fire on an ACV roof.

**What the extractor extension needs (the follow-up ticket).** A typed-core `loss_settlement_basis` on
`HomeownersInsuranceExtraction` (enum: `replacement_cost / actual_cash_value / unknown`), the prompt taught to
read the loss-settlement/valuation clause, per-item overrides for the roof (an ACV-roof exception), and golden
files evidencing it. Then IH-1 is a trivial `no-ai-dependency` structural rule (basis == replacement_cost →
satisfied; actual_cash_value → fired; missing → couldnt_check), the IH-3 shape.

**The scope boundaries (recorded, not built).**
- **The LEGACY investor overlay** — some investors still apply `min(100% RC, max(100% loan, 80% RC))` (UWM /
  Sun-West may differ). Recorded as a possible future investor-overlay variant, NOT built (Priya's ruling
  retires the comparison for the agencies; overlays are a separate question for her).
- **The condo / PUD master policy** — Priya's *"a condo/co-op/PUD master policy must cover ≥ 100% of the
  project improvements' replacement cost"* is an ARITHMETIC test on a DIFFERENT document (a master policy), and
  the catalog already reserves it as **IH-7** ("Condo master policy"). NOT IH-1's job; a separate candidate
  (likely similarly extractor-gated — LP-415 found the condo questionnaire has no extractor). IH-1 would need a
  `property.type` / condo indicator to EXCLUDE condos so it does not apply the dwelling-basis test to a master
  policy — and **no confirmed condo indicator tag exists** (the `loan.purpose` situation, LP-424 item 4) — a
  scoping gap the extension must also address.
- **The other two adequacy conditions Priya named** — "required hazards covered" and "the deductible within
  agency limits" — are NOT IH-1's (D2, the AS-8/AS-10 two-rules-one-inadequacy noise lesson). Hazards map to
  IH-6 (flood) / IH-8 (wind-hail) / IH-2 (mortgagee clause); the DEDUCTIBLE is an unwritten candidate that would
  need Priya's agency limits (a threshold — another reason it is not IH-1, which by her ruling has none).

**Cross-refs.** LP-405 (the typed-core-vs-catch-all rule — the STOP basis), LP-417 (IH-3, the live insurance
sibling on the same binder — IH-1's intended shape + the boundary), LP-415 (the Insurance audit — IH-2/IH-8
extractor-gated, the condo questionnaire gap), LP-424 item 4 (the missing property-type indicator precedent),
ADR-333 (the extraction→snapshot boundary — a field must be typed-core to be rule-visible). The three sibling
rules from Priya's B14-adjacent answers (IH-1 here; PE-1 an FHFA table; the pay-stub-only rule) each have their
own ticket; LP-430 built the terminated-employment one.

## ADR-341: The extractor generator emits validated flat schemas and REFUSES the rest — the structure is scriptable, the prose is not (LP-434)

**Context.** `docs/schema-specs/` holds 108 JSON specs describing each document type's extraction schema;
`_GENERATION_GUIDE.md` defines how a spec becomes code. LP-434 built the generator. Because every future extractor
will be produced this way, a template error would propagate silently across ~98 types — so the contract, and the
one place the guide is optimistic, are recorded here.

**The decision — validate first, refuse loudly, generate only the flat/clean part.** The generator
(`app/ai/extraction/generator/`) runs the guide's five §0 stop conditions BEFORE any emitter and refuses a spec
outright — with reasons — rather than emitting partial or guessed code:
(1) a blocking `open_questions` entry; (2) a field `type` with no coercer (`str`/`Decimal`/`date`/`int` only);
(3) a `pii.kind` not in the live `PiiKind` enum (**DOB and ADDRESS do not exist today**); (4) **any** nested list
(~5 bespoke files each, no generic mechanism); (5) a field with no `reason_class`. The valid PII kinds are read
from the live enum, not hard-coded, so adding a kind (with its mask strategy) unblocks its specs with no edit to
the validator. A passing spec emits the module, the prompt scaffold, the `EXTRACTORS` registration snippet, and
the test skeleton. Review metadata (`why` / `reason_class` / `rejected` / `open_questions` / `rule_floor` /
`plumbing_sites`) is NEVER emitted into code. A spec with a shipping `existing_extractor` produces a **diff-mode
report** of the `exists_today: false` additions, never a module and never a patch (a bad patch to a shipping
extractor is worse than a manual edit).

**What it refuses is the point.** All ten of the top specs refuse — the CORRECT outcome, since they are
nested-heavy by design. Notably **008-w2 refuses** (its `employee_address` carries `pii.kind: "ADDRESS"`,
absent from `PiiKind`), correcting the LP-434 ticket's prediction that w2 would pass. `condo_questionnaire` is one
resolved blocking question from generating; `w2`'s four non-address additions generate fine.

**The round-trip is the proof.** A spec describing `property_tax_bill` as it ships (`existing_extractor: null`)
generates a module whose `_CORE_SPEC` is **byte-identical** to the shipping one (same fields, same coercers,
same imports, same function bodies); the ONLY differences are docstrings/comments. Pinned by two tests comparing
the generated `_CORE_SPEC` and model field names/annotations against the live shipping module.

**D2 — mechanism.** f-string templates normalized through ruff itself (`ruff check --fix --select I` +
`ruff format`, via `--stdin-filename` so first-party `app` detection is correct). This is the simplest way to
GUARANTEE byte-clean, import-sorted, ruff- and mypy-passing output for any field set, rather than hand-guessing
where ruff wraps a long call for a long class prefix. ruff is a dev dependency, always present in-repo.

**The D1 finding — the guide's §12 is slightly optimistic about uniformity.** Diffing two shipping flat modules,
the *code* is near-identical (imports modulo the coercer line, the Result class, `.failed()`, the parse/extract
bodies, the logging — all byte-identical modulo substituted names), BUT the module docstring, class docstrings,
and inline field comments are **bespoke prose per module**. The generator therefore emits *neutral, honest*
docstrings/comments — a "GENERATED STARTER — accuracy UNVALIDATED" banner — rather than imitating hand-written
prose it cannot reconstruct from the spec. **The structure is scriptable; the prose (and accuracy) are not.** A
generated extractor ships structurally correct and mechanically tested, tuned by a human prompt pass and Priya's
review of real extractions — never presented as already tuned.

**Consequences.** Sizing the 108 is guide §12: scripted generation for the flat/clean thin majority · ~15–20 real
tickets for the nested / PII-heavy / new-coercer documents · a Priya validation pass over all. Adding a `PiiKind`
(DOB/ADDRESS) with a genuine mask strategy unblocks six of the top ten at condition 3. Nested lists stay bespoke.

**Cross-refs.** `docs/schema-specs/_GENERATION_GUIDE.md` (the authoritative contract), `_FORMAT.md` (the spec
shape), ADR-333 (the extraction→snapshot boundary — a field must be typed-core to be rule-visible), ADR-340
(the extractor-extension boundary that stopped IH-1), LP-62 (the flat-extractor fan-out this scales).

## ADR-342: The schema-spec pass set is the thin Tier-2/3 tail, not the flat valuable middle — the generator's leverage is smaller and differently shaped than guide §12 predicted (LP-435)

**Context.** LP-435 applied Geet's four spec decisions (addresses unmasked; credit-report/appraisal/condo open
questions answered), validated all 108 schema specs, and generated every passing spec. The ADR note asked to
record if the pass rate is far from what `_GENERATION_GUIDE.md` §12 predicts ("scripted generation for the flat
majority · a bounded set of bespoke tickets for the nested/PII-heavy tail"), since that resizes the remaining work.

**The finding — it is far off, in shape more than count.** 14 of 108 pass. But the passing set is the **thin
tail**: by their own declared tier, the 13 generated new-type modules are **1 Tier-1** (condo_questionnaire, 7
rules), **3 Tier-2**, and **9 Tier-3 documents with 0–1 rules each**. They pass precisely *because* they are
simple — no nested lists, no blocking questions, no DOB/ADDRESS. **Every high-value document refuses:** the 1003,
credit report, appraisal, bank statement, title commitment, AUS findings, and the tax-return family all carry a
nested list (61 specs), a DOB/ADDRESS PII kind (27 specs), or an unresolved blocking question (85 specs) — usually
several. There are **66 nested lists across the specs**, each a bespoke ~5-file ticket (guide §4).

**The decision — the generator's leverage is real but bounded, and it is in the tail.** Guide §12's "scripted
generation for the flat majority" is only half right: the flat, all-coercible, no-blocking-question majority that
the generator *can* emit today is the low-rule-count Tier-2/3 tail, not the flat-but-valuable middle. Sizing the
remaining work accordingly: (a) the **66-nested-list backlog** is the critical path — every valuable document is
gated on hand-built lists; (b) a **DOB `PiiKind`** decision (11 fields / 9 specs) plus the accepted address
unmasking are prerequisites for the identity-heavy docs; (c) the ~85 **blocking open questions** are the cheapest
lever — 20 specs are one answer from passing (the near-miss list). The generator remains the right tool for the
thin tail and for the flat additions to shipping extractors (the 18 diff reports), but it does not, by itself,
unlock the documents the rules actually need.

**What LP-435 did with the finding.** Generated + placed the 13 passing modules (unwired, per Geet — the pipeline
extracts only Tier-1, a hard `== 18` invariant forbids silent promotion, and 9 of 13 are near-ruleless Tier-3);
produced a wiring backlog + 18 diff reports (`docs/schema-specs/_WIRING_BACKLOG.md`); left DOB masked and flagged
it. No rule moved; the 18 shipping extractors are byte-unchanged.

**Cross-refs.** ADR-341 (the generator contract), `_GENERATION_GUIDE.md` §4/§12, `docs/tickets/LP-435.md` (the
full validate table + roll-up), `docs/schema-specs/_WIRING_BACKLOG.md` (wiring + diff reports).
