# LP-3 — Backend Project Initialization

- **Ticket:** LP-3 — Backend project initialization
- **Epic:** Epic 1 — Repo & Infrastructure Setup
- **Status:** Completed
- **Date:** 2026-06-09

## Summary

This ticket initialized the Python backend for MortgageBoss AI: a Python 3.12 +
FastAPI project managed with `uv`, with strict tooling (Ruff for lint/format,
mypy in strict mode, pytest for tests). It establishes the full `backend/app/`
package tree that later tickets will populate, a minimal FastAPI application
exposing `/` and `/health`, a placeholder `core/config.py` (filled in LP-6), and
a sample async test suite. All runtime and dev dependencies were resolved and
locked (`uv.lock`), and every verification step — server boot, endpoint
responses, tests, lint, format, and type check — passed.

## Acceptance Criteria

| #  | Criterion                                                             | Status |
| -- | --------------------------------------------------------------------- | ------ |
| 1  | `backend/pyproject.toml` with metadata + runtime + dev deps           | ✅ Done |
| 2  | `backend/.python-version` pins 3.12                                    | ✅ Done |
| 3  | `backend/uv.lock` generated and committed                             | ✅ Done |
| 4  | `backend/` Ruff config (lint + format)                                | ✅ Done (in `pyproject.toml`) |
| 5  | Strict mypy config                                                    | ✅ Done (`[tool.mypy]` in `pyproject.toml`) |
| 6  | Backend `.gitignore` only if needed                                   | ✅ N/A — root `.gitignore` already covers Python artifacts |
| 7  | `backend/app/` structure with `__init__.py` in every package          | ✅ Done |
| 8  | `app/main.py` with `/` and `/health`                                  | ✅ Done |
| 9  | `app/core/config.py` skeleton                                         | ✅ Done (placeholder) |
| 10 | `tests/` with `conftest.py` + sample passing test                    | ✅ Done |
| 11 | `uv sync` installs all dependencies                                   | ✅ Done |
| 12 | `uv run uvicorn app.main:app --reload` serves on :8000               | ✅ Done |
| 13 | `GET /health` → `{"status": "healthy"}`                              | ✅ Done |
| 14 | `GET /` → welcome message                                            | ✅ Done |
| 15 | `uv run pytest` passes                                               | ✅ Done (2 passed) |
| 16 | `uv run ruff check .` clean                                          | ✅ Done |
| 17 | `uv run ruff format --check .` clean                                 | ✅ Done |
| 18 | `uv run mypy app/` no errors                                         | ✅ Done (24 files, no issues) |
| 19 | README.md "Backend Setup" section                                   | ✅ Done |
| 20 | ADRs added to decisions.md                                           | ✅ Done (ADR-007…012) |
| 21 | `docs/tickets/LP-3.md` created                                       | ✅ Done (this file) |

## What Was Built

### Files created

- **`backend/pyproject.toml`** — PEP 621 project metadata, runtime deps,
  `[dependency-groups].dev`, plus `[tool.ruff]`, `[tool.ruff.lint]`,
  `[tool.ruff.format]`, `[tool.mypy]`, `[tool.pytest.ini_options]`, and a
  Hatchling `[build-system]`.
- **`backend/.python-version`** — pins `3.12`.
- **`backend/uv.lock`** — fully resolved lock file (committed for reproducible
  installs).
- **`backend/app/main.py`** — minimal FastAPI app: `lifespan` context manager
  (startup/shutdown stubs), CORS middleware (allowing `http://localhost:3000`),
  and the `/` and `/health` routes, all fully type-hinted.
- **`backend/app/core/config.py`** — placeholder with a `TODO(LP-6)` for the
  Pydantic `Settings` class.
- **`backend/tests/conftest.py`** — async `client` fixture using
  `httpx.AsyncClient` + `ASGITransport` against the app.
- **`backend/tests/test_main.py`** — two async tests covering `/` and `/health`.

### Directory structure under `backend/app/`

The full package tree from the V1 plan was created, with an empty `__init__.py`
in every package and `.gitkeep` files in directories that are otherwise empty
(to be populated by later tickets):

```
backend/app/
├── __init__.py
├── main.py
├── core/                 (config.py placeholder)
├── models/               (.gitkeep — LP-10+)
├── schemas/
│   └── ai/
├── api/
│   └── routes/           (.gitkeep — LP-23+)
├── ai/
│   └── prompts/{classification,extraction,communication}/
├── services/
├── verification/
│   ├── rules/{regulatory,conventional,fha,cross_source}/
│   └── overlays/
├── tasks/
└── storage/
```

### Dependencies

Runtime and dev dependencies were resolved by `uv sync` (Python 3.12.13). Notable
resolved versions: FastAPI/Starlette, Uvicorn 0.49, SQLAlchemy 2.0.50,
asyncpg, Pydantic v2, Celery + redis 6.4, Anthropic SDK, Ruff 0.15.16,
mypy, pytest 9.0.3. See `uv.lock` for the exact pinned set.

## Dependencies Installed

| Category   | Package                      | Purpose                  |
| ---------- | ---------------------------- | ------------------------ |
| Web        | fastapi                      | API framework            |
| Web        | uvicorn                      | ASGI server              |
| Database   | sqlalchemy[asyncio]          | ORM                      |
| Database   | asyncpg                      | Postgres async driver    |
| Database   | alembic                      | Migrations               |
| Validation | pydantic                     | Data validation          |
| Validation | pydantic-settings            | Config management        |
| Tasks      | celery[redis]                | Background tasks         |
| Tasks      | redis                        | Redis client             |
| AI         | anthropic                    | Claude API SDK           |
| HTTP       | httpx                        | HTTP client              |
| Security   | python-jose[cryptography]    | JWT                      |
| Security   | passlib[bcrypt]              | Password hashing         |
| Files      | python-multipart             | File uploads             |
| Files      | pypdf                        | PDF processing           |
| Misc       | email-validator              | Email validation         |
| Logging    | structlog                    | Structured logging       |
| Dev        | pytest                       | Test runner              |
| Dev        | pytest-asyncio               | Async tests              |
| Dev        | pytest-cov                   | Coverage                 |
| Dev        | ruff                         | Linting and formatting   |
| Dev        | mypy                         | Type checking            |
| Dev        | types-passlib, types-python-jose | Type stubs           |

## Decisions Made

ADR-007 through ADR-012 were recorded in [`decisions.md`](../../decisions.md):

- **ADR-007 — Python 3.12.** Current stable; big perf gains over 3.11; mature
  async; 3.13 too new for full ecosystem support.
- **ADR-008 — uv.** Much faster than Poetry/pip-tools/pdm/pipenv;
  `pyproject.toml`-centric; built-in `uv.lock`; same vendor as Ruff.
- **ADR-009 — FastAPI.** Native async (crucial for concurrent LLM calls),
  automatic OpenAPI docs, Pydantic integration, type-first.
- **ADR-010 — SQLAlchemy 2.x async.** Most mature ORM; clean async API; Alembic
  integration; use `Mapped` style consistently.
- **ADR-011 — Ruff.** One fast tool replaces black/isort/flake8/etc., configured
  in `pyproject.toml`.
- **ADR-012 — mypy strict.** Catches bugs early and documents intent;
  `ignore_missing_imports` during V1 for libraries lacking stubs.

## Assumptions

- The developer has Python 3.12 available (pyenv/asdf/system), or lets `uv`
  fetch it (it did so here — CPython 3.12.13).
- The developer can install `uv` (script at <https://astral.sh/uv/install.sh>).
- The environment is macOS, Linux, or Windows + WSL2.
- PyPI is reachable from the developer's network.

## Verification Performed

All executed on this machine (uv 0.11.19, CPython 3.12.13):

- ✅ `uv sync` — resolved and installed all deps; generated `uv.lock`.
- ✅ `uv run uvicorn app.main:app` — server started on port 8000.
- ✅ `curl http://localhost:8000/` →
  `{"service":"mortgageboss-ai","version":"0.1.0","status":"running"}`.
- ✅ `curl http://localhost:8000/health` → `{"status":"healthy"}`.
- ✅ `http://localhost:8000/docs` → HTTP 200; OpenAPI exposes `/` and `/health`.
- ✅ `uv run pytest -v` → **2 passed**.
- ✅ `uv run ruff check .` → All checks passed (one import-order fix auto-applied
  to `conftest.py`).
- ✅ `uv run ruff format --check .` → all 25 files already formatted.
- ✅ `uv run mypy app/` → Success: no issues found in 24 source files.

## Notes

- Several directories under `app/` contain only `__init__.py` and `.gitkeep`;
  they are placeholders for later tickets.
- `core/config.py` is a placeholder; LP-6 will add the `Settings` class.
- Database/Redis connections are deferred to LP-6 (they need `config.py` first).
- All `__init__.py` files are intentionally empty (no premature exports).
- No `backend/.gitignore` was created — the root `.gitignore` already ignores
  `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, and
  `*.egg-info/`.
- **Fixed an unrelated `.gitignore` conflict:** the root `storage/` rule (added
  in LP-1 for local uploads) also matched the new `backend/app/storage/` source
  package, which would have left it untracked. Re-anchored the rule to
  `/storage/` and `/backend/storage/` (the actual runtime upload locations) so
  the package is committed while runtime upload dirs stay ignored.

## What's Next

LP-4 (backend directory scaffolding) is effectively satisfied here, since the
full `app/` tree was created. Next is **LP-5 — Frontend project initialization**.

## References

- [`docs/tickets/LP-2.md`](LP-2.md) — previous ticket (Docker Compose).
- [uv documentation](https://docs.astral.sh/uv/)
- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.x documentation](https://docs.sqlalchemy.org/en/20/)
