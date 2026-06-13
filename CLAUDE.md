# CLAUDE.md

Conventions and context for Claude Code working in this repo. Keep this current;
it is read on every interaction.

## Project

**mortgageboss-ai** is a standalone loan processing assistant for mortgage loan
processors at processing companies. It helps a processor assemble complete,
accurate loan files — documents, extracted data, verification findings, and
conditions — before submission to underwriting. V1 is a monorepo with a Python
backend and a Next.js frontend.

Mortgage processing is jargon-heavy — see [`docs/glossary.md`](docs/glossary.md)
for domain terms. The resident **domain expert** ("sister") verifies domain
questions; when unsure about a mortgage term, flag it rather than guess.

## Current status

**Phase 1 — Foundation.** Epic 1 (Repo & Infrastructure Setup, LP-1…LP-8) is
**complete**: skeleton, Docker services, backend + frontend scaffolding,
environment config, health checks, and CI/CD. **Epic 2 (Database & Models, LP-9+)
is next.** The full plan is in [`docs/phases/phase-1.md`](docs/phases/phase-1.md).

## Tech stack

- **Backend:** Python 3.12, FastAPI (async), SQLAlchemy 2.x (async), Alembic,
  Celery, PostgreSQL 16, Redis 7, Anthropic Claude, structlog. Managed with **uv**.
- **Frontend:** Next.js 15 (App Router), TypeScript (strict), Tailwind CSS,
  shadcn/ui, TanStack Query (server state), Zustand (client state),
  react-hook-form + Zod, axios. Managed with **pnpm**.
- **Tooling:** Ruff + mypy (Python), Biome (TS/JS), pytest, pre-commit, GitHub
  Actions. Local services via Docker Compose (Postgres, Redis, MailHog).

## Repository structure

Monorepo: `backend/`, `frontend/`, `docs/`, `scripts/`, `.github/`. Backend code
lives under `backend/app/` (`core`, `models`, `schemas`, `api`, `ai`, `services`,
`verification`, `tasks`, `storage`). See
[`docs/project-structure.md`](docs/project-structure.md) for the full layout and
"where does X go?" conventions.

## Conventions

**Backend (Python)**

- **Async-first** — no synchronous DB calls; async SQLAlchemy sessions and async
  route handlers. Long work runs on Celery, not in the request.
- **SQLAlchemy 2.x** — modern `Mapped[...]` / `mapped_column()` style.
- **Pydantic v2** — request/response schemas and settings.
- **Fully typed** — all functions/methods typed; mypy runs in strict mode.
- **Configuration** via Pydantic Settings from env/`.env`; access the cached
  `settings` singleton (`from app.core.config import settings`). Required vars
  missing → app refuses to start.
- **Structured logging** with structlog (console in dev, JSON in prod).
- **Health checks** are three-tier: `/health` (detail), `/health/live`,
  `/health/ready`.
- **Ruff** for lint + format (config in `pyproject.toml`).

**Frontend (TypeScript)**

- **TypeScript strict** (plus `noUncheckedIndexedAccess`, `noImplicitOverride`).
- **Server Components by default**; add `"use client"` only when interactivity is
  needed.
- **Biome** for lint + format (2-space, double quotes; config in
  `frontend/biome.json`).
- **Design tokens** from LP-5: primary blue (`#2563EB`), cool-gray neutrals,
  semantic success/warning/danger/info, system font stack. Defined as CSS
  variables in `app/globals.css` and `tailwind.config.ts` — use the tokens, never
  ad-hoc colors.

**Data model principles** (apply as Epic 2+ lands)

- The **database is the source of truth**; AI never accesses it directly (typed
  tools only).
- **Stated vs verified data** tracked separately. Deterministic rules; AI only
  for perception (classify/extract).
- **Soft delete**, **versioning** of derived data, an **audit/activity log**, and
  **multi-tenancy** (`company_id` scoping) everywhere.

## Working on tickets

Every ticket gets a `docs/tickets/LP-XXX.md` recording what was done, assumptions,
and decisions. Architectural decisions go in [`decisions.md`](decisions.md) as a
new ADR. CI (ruff/mypy/pytest, biome/tsc/build) must stay green; install
pre-commit hooks for local feedback (see
[`docs/development-workflow.md`](docs/development-workflow.md)).

## Key docs

- [`docs/README.md`](docs/README.md) — documentation index
- [`docs/architecture.md`](docs/architecture.md) — system architecture
- [`docs/glossary.md`](docs/glossary.md) — domain + technical terms
- [`docs/project-structure.md`](docs/project-structure.md) — repo layout
- [`decisions.md`](decisions.md) — ADR log
