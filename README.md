# MortgageBoss AI

A standalone loan processing assistant for mortgage loan processors at processing companies.

**Status:** Phase 1 — Foundation (in progress)

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

> Coming after LP-2 through LP-5 are complete.

## Repository Structure

| Path                  | Description                                                   |
| --------------------- | ------------------------------------------------------------ |
| `backend/`            | Python + FastAPI backend (filled in LP-3).                   |
| `frontend/`           | Next.js + TypeScript frontend (filled in LP-5).              |
| `docs/`               | Project documentation.                                       |
| `docs/tickets/`       | Ticket-by-ticket implementation history (LP-XXX.md).         |
| `docs/architecture/`  | Architecture documentation.                                  |
| `scripts/`            | Development and operations scripts.                          |
| `.github/workflows/`  | CI/CD workflow definitions.                                  |

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

## Documentation

- **Implementation history:** see [`docs/tickets/`](docs/tickets/) for a record
  of what each ticket delivered.
- **Architectural decisions:** see [`decisions.md`](decisions.md) for the
  lightweight ADR log.
