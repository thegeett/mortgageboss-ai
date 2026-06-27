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
