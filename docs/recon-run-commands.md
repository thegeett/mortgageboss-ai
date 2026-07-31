# Recon — run commands & config (read-only)

_All answers quote file:line. "NOT FOUND" = not determinable from the repo._

## 1. FRONTEND
- **Next.js app dir:** `frontend/` (relative to repo root)
- **dev script (verbatim):** `"dev": "next dev"` — `frontend/package.json:6`
- **Run on port 3001:** `cd frontend && pnpm dev -- --port 3001` (pnpm is the manager: `frontend/pnpm-lock.yaml`; `next dev` takes `-p/--port`). npm equivalent: `npm run dev -- --port 3001`.
- **Node version pinned:** NOT pinned in `.nvmrc` (none at root or `frontend/`), no `engines` and no `packageManager` in `frontend/package.json`, no frontend Dockerfile. Only CI pins it: `node-version: "20"` — `.github/workflows/frontend-ci.yml:38`.

## 2. BACKEND
- **ASGI import path:** `app.main:app` — object at `backend/app/main.py:94` (`app = FastAPI(`); confirmed `README.md:172,380`.
- **Documented dev command:** `uv run uvicorn app.main:app --reload` — `README.md:172,380`. First-run: `cd backend && uv sync && cp .env.example .env && uv run uvicorn app.main:app --reload` — `README.md:39`. No Makefile (none in repo). No run script.
- **Run on port 8001 with reload:** `cd backend && uv run uvicorn app.main:app --reload --port 8001`
- **Python version:** `requires-python = ">=3.12"` — `backend/pyproject.toml:5`; `backend/.python-version` = `3.12`; mypy `python_version = "3.12"` — `backend/pyproject.toml:64`.
- **Package manager uv:** YES (`README.md:39` uses `uv sync`/`uv run`; no `[tool.uv]` section but that is not required). **`uv.lock` EXISTS** — `backend/uv.lock`.

## 3. CONFIG / ENV
- **`backend/.env.example` keys (keys only):**
  `APP_NAME`, `APP_VERSION`, `ENVIRONMENT`, `DEBUG`, `DATABASE_URL`, `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`, `DATABASE_POOL_TIMEOUT`, `REDIS_URL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL_CLASSIFICATION`, `ANTHROPIC_MODEL_EXTRACTION`, `AI_MAX_RETRIES`, `AI_BASE_RETRY_DELAY_SECONDS`, `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, `JWT_REFRESH_TOKEN_EXPIRE_DAYS`, `ENCRYPTION_KEY`, `CORS_ALLOWED_ORIGINS`, `STORAGE_BACKEND`, `STORAGE_LOCAL_PATH`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_FROM_NAME`, `LOG_LEVEL`, `LOG_FORMAT`.
  (Commented-out extras present: `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` — `backend/.env.example:20-21`.)
- **Sync (psql-compatible) DB URL:** NOT FOUND. `DATABASE_URL` is asyncpg-only — `database_url: PostgresDsn = Field(description="PostgreSQL connection URL with asyncpg driver")` (`backend/app/core/config.py:31`); `.env.example:9` = `postgresql+asyncpg://…`. Alembic reuses the same asyncpg URL (`config.set_main_option("sqlalchemy.url", str(settings.database_url))` — `backend/alembic/env.py:25`; note `alembic/env.py:23`). No `postgresql://`-without-`+asyncpg` variant is defined anywhere.
- **Storage path variable:** `STORAGE_LOCAL_PATH` → `storage_local_path: str = "./storage"` — `backend/app/core/config.py:114`. **Default: `./storage`.**
- **S3 support:** DECLARED but NOT IMPLEMENTED. Type allows it — `storage_backend: Literal["local", "s3"] = "local"` (`config.py:113`) — but the factory `get_storage_backend()` implements only `"local"` (returns `LocalStorageBackend(settings.storage_local_path)`); the `"s3"` branch is **commented out** and any non-local value **raises `ValueError`** — `backend/app/storage/__init__.py:34-39`. Only `app/storage/local.py` exists (no `s3.py`). **No S3 variables configure it** (no bucket/region/AWS keys in `config.py` or `.env.example`).
- **Anthropic client:** constructed in `backend/app/ai/client.py:153` — `return AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=0)`. Key read from `settings.anthropic_api_key` (`config.py:49`, from env `ANTHROPIC_API_KEY`); missing-key guard raises `AIClientError` at `client.py:151`.

## 4. WORKTREE SAFETY
- **Root `.env` (next to `docker-compose.yml`):** NO — does not exist. (A `backend/.env` exists, but not at repo root.)
- **`.gitignore` covers root `.env`:** YES — `.gitignore:28` (`.env`), `:29-30` (`.env.local`, `.env.*.local`), with `:31-32` `!.env.example` keeping examples tracked.
- **Hardcoded 5432 / 6379 / 8000 / 3000 outside `docker-compose.yml`:**
  Application/config code:
  - `frontend/lib/config.ts:2` — `apiUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"` (8000 fallback)
  - `frontend/lib/api/client.ts:5` — `API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"` (8000 fallback)
  - `backend/app/core/config.py:110` — `cors_allowed_origins: list[str] = ["http://localhost:3000"]` (3000 default)
  - `frontend/.env.example:2` — `NEXT_PUBLIC_API_URL=http://localhost:8000` (8000)
  - `backend/.env.example:9` — `DATABASE_URL=…@localhost:5432/…` (5432)
  - `backend/.env.example:15` — `REDIS_URL=redis://localhost:6379/0` (6379); `:20-21` commented CELERY (6379)
  - `backend/.env.example:55` — `CORS_ALLOWED_ORIGINS=["http://localhost:3000"]` (3000)
  Tests:
  - `backend/tests/test_config.py:9` — `postgresql+asyncpg://…@localhost:5432/test` (5432; creds redacted here)
  Docs/tooling (non-code, for completeness): `README.md:38,41,45,122,123,133-134,177-179,298,353,369,386`; `frontend/README.md:17`; `decisions.md:2060`; `.claude/settings.local.json:46-61` (curl/lsof allowlist strings for 8000/3000).
