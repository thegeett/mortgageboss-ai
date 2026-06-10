# MortgageBoss AI

[![Backend CI](https://github.com/thegeett/mortgageboss-ai/actions/workflows/backend-ci.yml/badge.svg)](https://github.com/thegeett/mortgageboss-ai/actions/workflows/backend-ci.yml)
[![Frontend CI](https://github.com/thegeett/mortgageboss-ai/actions/workflows/frontend-ci.yml/badge.svg)](https://github.com/thegeett/mortgageboss-ai/actions/workflows/frontend-ci.yml)

A standalone loan processing assistant for mortgage loan processors at processing
companies. It helps a processor assemble complete, accurate loan files —
documents, data, verification findings, and conditions — before submission to
underwriting.

**Project status:** Phase 1 (Foundation) — **Epic 1 complete**, building Epic 2
(Database & Models).

## Architecture Overview

MortgageBoss AI is a monorepo containing a Python/FastAPI backend and a Next.js
frontend. The backend exposes an async REST API backed by PostgreSQL and uses
Celery for background processing of loan documents and tasks. The frontend is a
TypeScript + Next.js application styled with Tailwind and shadcn/ui. Local
development is orchestrated with Docker Compose (Postgres, Redis, MailHog).

## Tech Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.x (async), Celery, PostgreSQL 16
- **Frontend:** Next.js 15, TypeScript, Tailwind CSS, shadcn/ui
- **Infrastructure (local):** Docker Compose — Postgres, Redis, MailHog
- **Package managers:** uv (Python), pnpm (Node)

## Quick Start

Prerequisites: a Docker runtime (Colima), Python 3.12 + [uv](https://docs.astral.sh/uv/),
and Node 20+ + [pnpm](https://pnpm.io/). Then, in three terminals:

```bash
# 1. Local services (Postgres, Redis, MailHog)
docker compose up -d

# 2. Backend → http://localhost:8000  (docs at /docs)
cd backend && uv sync && cp .env.example .env && uv run uvicorn app.main:app --reload

# 3. Frontend → http://localhost:3000
cd frontend && pnpm install && cp .env.example .env.local && pnpm dev
```

Visiting <http://localhost:3000> shows the home page with a live backend
"System status" card. Full details are in the setup sections below. For backend
work alone, Docker isn't strictly required until the database lands in Epic 2.

## Repository Structure

| Path                  | Description                                                   |
| --------------------- | ------------------------------------------------------------ |
| `backend/`            | Python + FastAPI backend.                                    |
| `frontend/`           | Next.js + TypeScript frontend.                               |
| `docs/`               | Project documentation (start at [`docs/README.md`](docs/README.md)). |
| `docs/tickets/`       | Ticket-by-ticket implementation history (LP-XXX.md).         |
| `scripts/`            | Development and operations scripts.                          |
| `.github/workflows/`  | CI/CD workflow definitions.                                  |

See [`docs/project-structure.md`](docs/project-structure.md) for a full,
annotated layout and "where does X go?" conventions.

## Local Development Setup

Local infrastructure (PostgreSQL, Redis, MailHog) runs via Docker Compose.

### Prerequisites

- A Docker runtime + Compose v2. This project uses **Colima** (no Docker
  Desktop) — see ADR-006 in [`decisions.md`](decisions.md). On Linux, a native
  Docker Engine + Compose v2 works equally well.

### First-time Colima setup (macOS)

```bash
# Install Colima, the docker CLI, and the compose plugin
brew install colima docker docker-compose

# Start the Colima VM (4 CPUs, 8 GB RAM)
colima start --cpu 4 --memory 8

# Verify the docker CLI can reach the engine
docker ps

# Stop Colima when you're done for the day
colima stop
```

> If `docker compose` reports the plugin is missing, add the Homebrew plugin
> directory to `~/.docker/config.json`:
> `"cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]`.

Colima only needs to be running for the service commands below to work
(`colima start` once per session, before `docker compose up -d`).

### Quick start

```bash
# Start all local services
docker compose up -d

# Check that all services are healthy
docker compose ps

# View logs for a specific service
docker compose logs -f postgres

# Stop services (data persists)
docker compose stop

# Stop and remove services (data persists in volumes)
docker compose down

# Stop and remove everything including data (DESTRUCTIVE)
docker compose down -v
```

### Service ports

| Service         | Address                                  | Credentials                                                                 |
| --------------- | ---------------------------------------- | --------------------------------------------------------------------------- |
| PostgreSQL      | `localhost:5432`                         | user `mortgageboss` / password `mortgageboss_dev_password` / db `mortgageboss_dev` |
| Redis           | `localhost:6379`                         | —                                                                           |
| MailHog (SMTP)  | `localhost:1025`                         | —                                                                           |
| MailHog (Web UI)| <http://localhost:8025>                  | —                                                                           |

> Development credentials are intentionally committed in `docker-compose.yml`.
> They are for local use only — never reuse them in any shared or production
> environment. See [`decisions.md`](decisions.md) ADR-005.

### Troubleshooting

- **Port conflict (e.g. `5432` already in use):** another Postgres (or service)
  is bound to that port. Find the offender with `lsof -nP -iTCP:5432 -sTCP:LISTEN`
  (macOS/Linux), then stop it — or remap the host side of the port in
  `docker-compose.yml` (e.g. `"5433:5432"`) and connect on the new host port.
- **Resetting data:** `docker compose down -v` removes the named volumes and
  wipes all local Postgres/Redis data. The next `docker compose up -d` starts
  from a clean slate.
- **Checking service health:** `docker compose ps` shows each service's health
  status; wait until all three report `healthy`.
- **Viewing logs:** `docker compose logs -f <service>` (e.g. `postgres`,
  `redis`, `mailhog`) tails a service's logs to diagnose startup issues.

## Backend Setup

The backend is a Python 3.12 + FastAPI application managed with
[uv](https://docs.astral.sh/uv/). All commands below run from the `backend/`
directory.

### Prerequisites

- **Python 3.12** — managing it via [pyenv](https://github.com/pyenv/pyenv) or
  [asdf](https://asdf-vm.com/) is recommended. `uv` can also fetch a matching
  interpreter automatically (the version is pinned in `backend/.python-version`).
- **uv** — install with:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

### First-time setup

```bash
cd backend
uv sync          # creates .venv and installs all dependencies from uv.lock
```

### Run the development server

```bash
cd backend
uv run uvicorn app.main:app --reload
```

Then visit:

- <http://localhost:8000> — service welcome JSON
- <http://localhost:8000/health> — health check
- <http://localhost:8000/docs> — auto-generated OpenAPI (Swagger) docs

### Tests

```bash
cd backend
uv run pytest
```

### Linting and formatting

```bash
cd backend
uv run ruff check .     # lint
uv run ruff format .    # format
```

### Type checking

```bash
cd backend
uv run mypy app/
```

## Frontend Setup

The frontend is a [Next.js 15](https://nextjs.org/) (App Router) application
written in TypeScript, styled with Tailwind CSS and [shadcn/ui](https://ui.shadcn.com),
and managed with [pnpm](https://pnpm.io/). All commands below run from the
`frontend/` directory.

### Prerequisites

- **Node.js 20+** — managing it via [nvm](https://github.com/nvm-sh/nvm) or
  [fnm](https://github.com/Schniz/fnm) is recommended.
- **pnpm** — install with:
  ```bash
  npm install -g pnpm
  ```

### First-time setup

```bash
cd frontend
pnpm install
cp .env.example .env.local
```

### Run the development server

```bash
cd frontend
pnpm dev
```

Then visit <http://localhost:3000>.

### Linting and formatting

The frontend uses [Biome](https://biomejs.dev/) (replaces ESLint + Prettier).

```bash
cd frontend
pnpm lint      # check lint + formatting
pnpm lint:fix  # apply safe lint fixes + organize imports
pnpm format    # apply formatting
```

### Type checking

```bash
cd frontend
pnpm typecheck
```

### Building for production

```bash
cd frontend
pnpm build
```

## Environment Configuration

Both the backend and the frontend load configuration from environment variables.
The pattern is: **commit `.env.example`** (documents every variable) and
**gitignore the real `.env` / `.env.local`** (holds local secrets).

### Backend (`backend/.env`)

The backend uses [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/);
`Settings` is validated on startup and the app **refuses to boot** if a required
variable is missing or invalid (e.g. a JWT secret shorter than 32 characters).

```bash
cd backend
cp .env.example .env
# generate a real JWT secret and paste it into .env:
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Variable groups:

| Group       | Variables                                                            | Notes                                                       |
| ----------- | -------------------------------------------------------------------- | ----------------------------------------------------------- |
| Application | `APP_NAME`, `APP_VERSION`, `ENVIRONMENT`, `DEBUG`                     | `ENVIRONMENT` ∈ development \| staging \| production        |
| Database    | `DATABASE_URL`, `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`, `DATABASE_POOL_TIMEOUT` | URL **must** use the `postgresql+asyncpg://` scheme |
| Redis       | `REDIS_URL`                                                          | Celery broker + cache                                       |
| Anthropic   | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL_*`                             | Get a key at <https://console.anthropic.com/> (a placeholder is fine in Phase 1) |
| JWT / Auth  | `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_*_EXPIRE_*`                   | Secret must be ≥ 32 chars                                   |
| CORS        | `CORS_ALLOWED_ORIGINS`                                               | JSON array, e.g. `["http://localhost:3000"]`                |
| Storage     | `STORAGE_BACKEND`, `STORAGE_LOCAL_PATH`                              | `local` for development                                     |
| Email/SMTP  | `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM_*`                              | Points at **MailHog** (`localhost:1025`) in development     |
| Logging     | `LOG_LEVEL`, `LOG_FORMAT`                                            | `LOG_FORMAT=console` for dev, `json` for production         |

> The default `DATABASE_URL` and `REDIS_URL` in `.env.example` already match the
> credentials in `docker-compose.yml`, so they work out of the box against the
> local Docker services.

### Frontend (`frontend/.env.local`)

```bash
cd frontend
cp .env.example .env.local
```

The only variable is `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`),
which the axios client uses as its base URL.

### Verifying end-to-end connectivity

```bash
# Terminal 1: start local services
docker compose up -d

# Terminal 2: start the backend
cd backend
uv run uvicorn app.main:app --reload

# Terminal 3: start the frontend
cd frontend
pnpm dev

# Visit http://localhost:3000 — the "System status" card should show the
# API server, PostgreSQL, and Redis as connected.
```

The backend exposes three health endpoints:

| Endpoint        | Purpose                          | Behaviour                                          |
| --------------- | -------------------------------- | -------------------------------------------------- |
| `/health`       | Human-readable overall status    | `200` healthy / `503` degraded, with per-dep checks |
| `/health/live`  | Liveness probe (process alive)   | Always `200` if the process is up (no dep checks)  |
| `/health/ready` | Readiness probe (can serve)      | `200` when all deps up, `503` if any dep is down   |

## Continuous Integration

Every push to `main` and every pull request targeting `main` runs automated
checks via GitHub Actions:

- **Backend** (`.github/workflows/backend-ci.yml`) — `ruff` lint, `ruff format`
  check, `mypy` strict type checking, `pytest`, and `uv.lock` verification.
- **Frontend** (`.github/workflows/frontend-ci.yml`) — Biome lint/format,
  `tsc` type checking, and a production `next build`.

Path filters mean each pipeline only runs when its area changes. CI status is
shown by the badges at the top of this file.

For fast local feedback, install the **pre-commit hooks** (lint, format, secret
detection, and hygiene checks that run on every commit):

```bash
pipx install pre-commit   # or: pip install --user pre-commit / uv tool install pre-commit
pre-commit install
pre-commit run --all-files   # optional: run against the whole repo once
```

See [`docs/development-workflow.md`](docs/development-workflow.md) for the full
workflow: what each check does, what to do when CI fails, and when (not) to skip
hooks.

## Documentation

Full documentation lives in [`docs/`](docs/README.md). Highlights:

- **[docs/README.md](docs/README.md)** — the documentation index (start here).
- **[Architecture](docs/architecture.md)** — system overview, components, data
  flow, and the principles that guide design.
- **[Glossary](docs/glossary.md)** — mortgage domain terms and technical terms.
- **[Project structure](docs/project-structure.md)** — repository layout and
  "where does X go?" conventions.
- **[Development workflow](docs/development-workflow.md)** — CI and pre-commit.
- **[POC learnings](docs/poc-learnings.md)** — lessons carried from the prototype.
- **Implementation history:** [`docs/tickets/`](docs/tickets/) — what each ticket
  delivered.
- **Architectural decisions:** [`decisions.md`](decisions.md) — the ADR log.
- **AI assistant conventions:** [`CLAUDE.md`](CLAUDE.md).
