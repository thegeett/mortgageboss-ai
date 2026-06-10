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
