# LP-2 — Docker Compose for Local Services

- **Ticket:** LP-2 — Docker Compose for local services
- **Epic:** Epic 1 — Repo & Infrastructure Setup
- **Status:** Completed
- **Date:** 2026-06-09

## Summary

This ticket defines the local development infrastructure for MortgageBoss AI as a
single `docker-compose.yml` at the repo root, orchestrating three services:
PostgreSQL 16 (the application database), Redis 7 (the Celery broker and cache),
and MailHog (a local SMTP catcher for testing email-sending code). All services
run on a dedicated bridge network, use `mortgageboss-`-prefixed container names,
declare health checks, and restart `unless-stopped`. Postgres and Redis persist
data in named volumes. With this in place, backend development (LP-3 onward) has
the data, queue, and mail dependencies it needs available via a single
`docker compose up -d`.

## Acceptance Criteria

| #  | Criterion                                                                 | Status |
| -- | ------------------------------------------------------------------------- | ------ |
| 1  | `docker-compose.yml` at repo root with postgres, redis, mailhog           | ✅ Done |
| 2  | PostgreSQL `16-alpine`, host port 5432                                     | ✅ Done |
| 3  | Redis `7-alpine`, host port 6379                                          | ✅ Done |
| 4  | MailHog, SMTP 1025 + Web UI 8025                                          | ✅ Done |
| 5  | Health checks on all services                                            | ✅ Done |
| 6  | Named volume for Postgres data persistence                               | ✅ Done |
| 7  | All services on `mortgageboss-network` bridge network                    | ✅ Done |
| 8  | Service/container names follow `mortgageboss-{service}`                   | ✅ Done |
| 9  | `docker compose up -d` brings services online without errors             | ✅ Done |
| 10 | `docker compose ps` shows all three healthy                              | ✅ Done |
| 11 | Connect to Postgres from host (port 5432, working credentials)           | ✅ Done |
| 12 | `redis-cli ping` returns PONG                                            | ✅ Done |
| 13 | MailHog Web UI reachable at http://localhost:8025                        | ✅ Done (HTTP 200) |
| 14 | README.md updated with "Local Development Setup" section                 | ✅ Done |
| 15 | New ADRs added to decisions.md                                          | ✅ Done (ADR-002…006) |
| 16 | `docs/tickets/LP-2.md` created                                          | ✅ Done (this file) |

> All criteria verified on a Colima-backed Docker runtime (see ADR-006). The
> runtime was installed during this ticket because no Docker engine was present
> initially. See **Verification Performed** below for the captured output.

## What Was Built

### Files created / modified

- **`docker-compose.yml`** (new) — three-service local stack (see table below).
- **`README.md`** (modified) — added a "Local Development Setup" section with
  prerequisites, quick-start commands, a service/ports table, and troubleshooting.
- **`decisions.md`** (modified) — added ADR-002 through ADR-006.
- **`docs/tickets/LP-2.md`** (new) — this completion document.

### Network and volume topology

- **Network:** a single user-defined bridge network, `mortgageboss-network`. All
  three services attach to it, so they can reach each other by service name
  (`postgres`, `redis`, `mailhog`) on the internal network while host ports are
  published for local tooling.
- **Volumes:** two named volumes — `mortgageboss-postgres-data`
  (→ `/var/lib/postgresql/data`) and `mortgageboss-redis-data` (→ `/data`,
  with Redis AOF persistence enabled via `--appendonly yes`). MailHog uses no
  volume (in-memory is fine for development).

### Service configuration notes

- **postgres** — `postgres:16-alpine`; env sets user/password/db; health check
  via `pg_isready -U mortgageboss -d mortgageboss_dev` (interval 5s, timeout 5s,
  retries 5, start period 10s).
- **redis** — `redis:7-alpine`; `command: redis-server --appendonly yes` for
  durability; health check via `redis-cli ping` (interval 5s, timeout 3s,
  retries 5).
- **mailhog** — `mailhog/mailhog:latest`; publishes 1025 (SMTP) and 8025 (UI);
  health check via `wget --spider http://localhost:8025` (interval 10s, timeout
  5s, retries 3).
- All services use `restart: unless-stopped`.

## Services Configured

| Service | Image                  | Host Port  | Container Port | Purpose                       |
| ------- | ---------------------- | ---------- | -------------- | ----------------------------- |
| postgres| postgres:16-alpine     | 5432       | 5432           | Application database          |
| redis   | redis:7-alpine         | 6379       | 6379           | Celery broker and cache       |
| mailhog | mailhog/mailhog        | 1025, 8025 | 1025, 8025     | Email capture for development |

## Decisions Made

The following ADRs were recorded in [`decisions.md`](../../decisions.md):

- **ADR-002 — Docker Compose for local services.** Orchestrating Postgres, Redis,
  and MailHog through one compose file gives a one-command, machine-consistent
  local stack with no native installs (only Docker is required).
- **ADR-003 — PostgreSQL 16 over 17.** 16 is more mature/battle-tested, broadly
  supported by managed hosts (Render/Railway/Supabase), has strong `asyncpg`
  support, and good JSON performance; 17 can be revisited in V2.
- **ADR-004 — MailHog over alternatives.** Chosen over Mailpit and Mailtrap
  because it is established, fully local, account-free, and has a simple UI.
- **ADR-005 — Hardcoded development credentials.** Acceptable because the file is
  development-only, the DB is local-only, and it streamlines onboarding;
  production credentials will be environment-injected by the host in Phase 7.
- **ADR-006 — Colima as the Docker runtime.** We chose **Colima over Docker
  Desktop** for this project because Colima is:
  - **Free for commercial use** — Docker Desktop requires a paid license for
    commercial/larger-org use, whereas Colima (Apache-2.0) does not.
  - **Lighter on resources** — a smaller, leaner VM footprint than Docker
    Desktop.
  - **No GUI overhead** — runs headless from the CLI; nothing extra to keep open.
  - **Identical CLI compatibility** — `docker` and `docker compose` work exactly
    as they would under Docker Desktop, so no workflow changes.

  The trade-off is one extra startup step (`colima start` before
  `docker compose up -d`), documented in the README's "First-time Colima setup".

## Assumptions

- The developer has a Docker runtime + Compose v2 running. This project uses
  Colima (ADR-006), installed via Homebrew; Docker Desktop or a native Linux
  Docker Engine would work equally well.
- Host ports 5432, 6379, 1025, and 8025 are available (verified free on this
  machine at authoring time).
- At least ~4GB of RAM is available to Docker.
- The environment is macOS, Linux, or Windows + WSL2.

## Verification Performed

Docker was not present on the machine initially, so a Colima-based runtime was
installed first (`brew install colima docker docker-compose`; plugin dir
registered in `~/.docker/config.json`; `colima start --cpu 4 --memory 8`). With
the engine running, the full verification was executed successfully:

- ✅ **Pre-flight:** host ports 5432, 6379, 1025, 8025 confirmed free (`lsof`)
  before bring-up — no conflicts.
- ✅ **`docker compose pull`** then **`docker compose up -d`** — network
  `mortgageboss-network`, volumes `mortgageboss-postgres-data` /
  `mortgageboss-redis-data`, and all three containers created and started with no
  errors.
- ✅ **`docker compose ps`** — all three services report **healthy**:

  ```
  NAME                    IMAGE                    SERVICE    STATUS
  mortgageboss-postgres   postgres:16-alpine       postgres   Up (healthy)
  mortgageboss-redis      redis:7-alpine           redis      Up (healthy)
  mortgageboss-mailhog    mailhog/mailhog:latest   mailhog    Up (healthy)
  ```

- ✅ **Postgres:** `pg_isready` → `accepting connections`; `SELECT version();` →
  `PostgreSQL 16.14 on aarch64-unknown-linux-musl`.
- ✅ **Redis:** `redis-cli ping` → `PONG`.
- ✅ **MailHog:** `curl http://localhost:8025` → HTTP `200`; the
  `/api/v2/messages` API returns valid JSON (`{"total":0,...}`).
- ✅ **Host reachability:** TCP connect from the host to `localhost:{5432, 6379,
  1025, 8025}` all succeed (published ports confirmed).
- ✅ **Data persistence:** created `_test` table → `docker compose stop` →
  `docker compose start` → `_test` **still present** after restart → dropped it.
  Confirms the named Postgres volume persists across the container lifecycle.

### Notes / caveats

- The `mailhog/mailhog:latest` image is `linux/amd64` only; on Apple Silicon
  (arm64) it runs under emulation. Compose prints a platform-mismatch notice,
  but the container runs and passes its health check normally.
- Host-side `psql` / `redis-cli` binaries are not installed on this machine, so
  AC-11/12 were validated via (a) the published-port TCP reachability check from
  the host and (b) the in-container clients against the same published services.
  GUI clients (DBeaver/TablePlus/IntelliJ) can connect to `localhost:5432` with
  the documented credentials.

## What's Next

**LP-3 — Backend project initialization.** Set up the Python project (uv) with
FastAPI, SQLAlchemy 2.x (async), and Celery dependencies in `backend/`.

## References

- [`docs/tickets/LP-1.md`](LP-1.md) — previous ticket (repo skeleton).
- [Docker Compose documentation](https://docs.docker.com/compose/)
- [PostgreSQL 16 release notes](https://www.postgresql.org/docs/16/release-16.html)
