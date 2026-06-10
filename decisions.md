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
