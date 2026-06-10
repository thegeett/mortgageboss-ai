# LP-6 — Environment Configuration

- **Ticket:** LP-6 — Environment configuration
- **Epic:** Epic 1 — Repo & Infrastructure Setup
- **Status:** Completed
- **Date:** 2026-06-10

## Summary

This ticket wired the foundation together. The backend now loads all
configuration from environment variables via a validated pydantic-settings
`Settings` singleton, connects to PostgreSQL (async SQLAlchemy engine) and Redis
(async client) on startup, fails fast if either is unreachable, and emits
structured logs via structlog (colored console in dev, JSON in prod). The
health surface was upgraded to three endpoints — `/health`, `/health/live`,
`/health/ready` — that verify dependencies and follow the Kubernetes probe
pattern. On the frontend, the axios client gained interceptors and a typed
`checkBackendHealth()` helper, and the home page now fetches and displays live
backend connectivity (API server, PostgreSQL, Redis) with loading, healthy,
degraded, and unreachable states. End-to-end connectivity was verified, the
unhealthy path (Postgres down → `503`) was exercised, and all checks (ruff,
mypy, pytest, Biome, tsc, build) pass.

## Acceptance Criteria

| #  | Criterion                                                                  | Status |
| -- | -------------------------------------------------------------------------- | ------ |
| 1  | `app/core/config.py` has a `Settings` class using pydantic-settings        | ✅ Done |
| 2  | Settings loads from env vars and optional `.env`                           | ✅ Done |
| 3  | All required settings are typed and validated                              | ✅ Done |
| 4  | Missing required settings fail startup with a clear error                  | ✅ Done |
| 5  | `app/core/database.py` provides async engine and `get_db`                  | ✅ Done |
| 6  | `app/core/redis.py` provides an async Redis client                         | ✅ Done |
| 7  | `app/core/logging.py` configures structlog                                 | ✅ Done |
| 8  | `app/main.py` configures CORS, logging, startup checks, graceful shutdown  | ✅ Done |
| 9  | `/health` checks DB + Redis and returns detailed status                    | ✅ Done |
| 10 | `/health/ready` added (503 if any dependency down)                         | ✅ Done |
| 11 | `/health/live` added (200 if app running)                                  | ✅ Done |
| 12 | `backend/.env.example` documents all variables                             | ✅ Done |
| 13 | `backend/.env` (gitignored) created for local dev                          | ✅ Done |
| 14 | `frontend/.env.example` verified correct (from LP-5)                       | ✅ Done |
| 15 | `frontend/.env.local` (gitignored) created                                 | ✅ Done |
| 16 | `frontend/lib/api/client.ts` updated with full axios config                | ✅ Done |
| 17 | `frontend/app/page.tsx` fetches and displays backend health                | ✅ Done |
| 18 | Frontend handles unreachable backend (error state, not blank)              | ✅ Done |
| 19 | README.md updated with environment configuration instructions              | ✅ Done |
| 20 | New ADRs (020–024) added to decisions.md                                   | ✅ Done |
| 21 | `docs/tickets/LP-6.md` created                                             | ✅ Done |
| 22 | Backend starts with `uv run uvicorn app.main:app --reload`                 | ✅ Done |
| 23 | Startup logs show successful Postgres + Redis connections                  | ✅ Done |
| 24 | `curl /health` returns detailed status with DB + Redis                     | ✅ Done |
| 25 | `curl /health/live` returns 200                                            | ✅ Done |
| 26 | `/health/ready` returns 200 when up, 503 when down                         | ✅ Done |
| 27 | Frontend `pnpm dev` runs and home page fetches health                      | ✅ Done |
| 28 | Stopping Postgres causes `/health/ready` to return 503 with reason         | ✅ Done |
| 29 | All existing tests still pass (`uv run pytest`)                            | ✅ Done |

## What Was Built

### Backend — configuration
- `app/core/config.py` — `Settings(BaseSettings)` with typed/validated fields for
  application, database, Redis, Anthropic, JWT, CORS, storage, SMTP, and logging;
  `is_development` / `is_production` computed fields; `get_settings()` cached
  singleton (`lru_cache`) exported as `settings`.

### Backend — database
- `app/core/database.py` — async engine (`create_async_engine` with pool sizing
  and `pool_pre_ping`), `async_session_maker`, `get_db` dependency + `DbSession`
  alias, `check_database_connection()` and `close_database_connections()`.

### Backend — redis
- `app/core/redis.py` — lazily created async Redis client (`get_redis_client`),
  `check_redis_connection()`, `close_redis_connections()`.

### Backend — logging
- `app/core/logging.py` — `setup_logging()` configures structlog (console vs JSON
  by `LOG_FORMAT`), bridges stdlib logging, quiets noisy loggers; `get_logger()`.

### Backend — health checks & lifespan
- `app/main.py` — `setup_logging()` at import; lifespan verifies DB + Redis on
  startup (raises `RuntimeError` if unreachable) and disposes connections on
  shutdown; CORS from settings; `/`, `/health`, `/health/live`, `/health/ready`.

### Backend — env & tests
- `backend/.env.example`, `backend/.env` (gitignored, real generated JWT secret).
- `tests/test_config.py` (settings loading, JWT length validation, env property),
  `tests/test_health.py` (liveness, readiness, full health).
- `tests/test_main.py` — health test updated to the new detailed contract.

### Frontend
- `lib/api/client.ts` — axios instance (timeout, request/response interceptors,
  dev error logging) + `HealthResponse` type and `checkBackendHealth()` (accepts
  200 and 503 so degraded state renders; only transport errors reject).
- `app/page.tsx` — client component using TanStack Query to fetch `/health`,
  rendering a "System status" card with loading / healthy / degraded / unreachable
  states and a retry button; keeps the LP-5 styled look.
- `frontend/.env.local` (gitignored) with `NEXT_PUBLIC_API_URL`.

## Configuration Architecture

```
environment variables  ─┐
backend/.env (optional) ─┼─▶  Settings(BaseSettings)  ──▶  settings (lru_cache singleton)
                         │         (validated)                     │
                         │                                         ├─▶ database.py (engine, sessions)
                         │                                         ├─▶ redis.py    (client)
                         │                                         ├─▶ logging.py  (structlog)
                         │                                         └─▶ main.py     (CORS, lifespan, routes)
```

`Settings` validates on instantiation; required fields with no default
(`DATABASE_URL`, `REDIS_URL`, `ANTHROPIC_API_KEY`, `JWT_SECRET_KEY`) cause a
startup failure if missing. Modules import the shared singleton via
`from app.core.config import settings`.

## Health Check Endpoints

| Endpoint        | Purpose                       | Checks deps? | Status codes                       |
| --------------- | ----------------------------- | ------------ | ---------------------------------- |
| `GET /health`   | Overall status with detail    | Yes          | `200` healthy / `503` degraded     |
| `GET /health/live`  | Liveness probe            | No           | always `200` if process alive      |
| `GET /health/ready` | Readiness probe           | Yes          | `200` all up / `503` any down      |

## Environment Variables

- **Application** — `APP_NAME`, `APP_VERSION`, `ENVIRONMENT`, `DEBUG`.
- **Database** — `DATABASE_URL` (`postgresql+asyncpg://`), `DATABASE_POOL_SIZE`,
  `DATABASE_MAX_OVERFLOW`, `DATABASE_POOL_TIMEOUT`.
- **Redis** — `REDIS_URL`.
- **Anthropic** — `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL_CLASSIFICATION`,
  `ANTHROPIC_MODEL_EXTRACTION`.
- **JWT/Auth** — `JWT_SECRET_KEY` (≥32 chars), `JWT_ALGORITHM`,
  `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, `JWT_REFRESH_TOKEN_EXPIRE_DAYS`.
- **CORS** — `CORS_ALLOWED_ORIGINS` (JSON array).
- **Storage** — `STORAGE_BACKEND`, `STORAGE_LOCAL_PATH`.
- **Email/SMTP** — `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`,
  `SMTP_FROM_EMAIL`, `SMTP_FROM_NAME`.
- **Logging** — `LOG_LEVEL`, `LOG_FORMAT`.

## Decisions Made

See ADR-020 (Pydantic Settings), ADR-021 (structlog), ADR-022 (async-only DB),
ADR-023 (three-tier health checks), and ADR-024 (connection pool sizing) in
`decisions.md`.

## Assumptions

- The Docker Compose services from LP-2 are running.
- The developer has created a `.env` file with valid values.
- An Anthropic API key is available (a placeholder is used in Phase 1; no AI
  calls are made yet).
- `JWT_SECRET_KEY` is generated securely (not the placeholder).

## Verification Performed

- Backend starts and connects to Postgres and Redis; startup logs show
  `starting_application`, `database_connected`, `redis_connected`,
  `application_ready` (colored console output).
- `GET /health` → `200` `{"status":"healthy", ... "database":"ok","redis":"ok"}`.
- `GET /health/live` → `200` `{"status":"alive"}`.
- `GET /health/ready` → `200` when services up.
- `docker compose stop postgres` → `/health/ready` returns `503`
  `{"ready":false,"checks":{"database":"fail","redis":"ok"}}`; `/health/live`
  stayed `200`; recovered to `200` after `docker compose start postgres`.
- CORS preflight + request return `access-control-allow-origin: http://localhost:3000`
  with credentials.
- Frontend `pnpm dev` serves the home page (System status card); production
  `pnpm build` succeeds.
- `uv run pytest` → 8 passed. `uv run ruff check .` clean. `uv run mypy app/`
  clean. `pnpm lint` clean. `pnpm typecheck` clean.

## Known Limitations

- The `.env` file is local-only (production will use platform-injected env vars).
- No secrets management yet (Phase 7).
- No rate limiting on endpoints (later).
- No request-ID tracking yet (Phase 7).

## What's Next

LP-7 (CI/CD setup) is next, then LP-8 (documentation refinement). Epic 2 begins
with LP-9 (Alembic migrations) and the database schema work.

## References

- Pydantic Settings: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
- SQLAlchemy 2.x async: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- structlog: https://www.structlog.org/
- The Twelve-Factor App: https://12factor.net/config
