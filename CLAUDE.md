# CLAUDE.md

## Project

MortgageBoss AI is a standalone loan processing assistant for mortgage loan
processors at processing companies. It helps processors manage loan files,
documents, and tasks through an async API and a web UI. This is a V1 build
organized as a monorepo containing both the backend and frontend.

## Current Phase

**Phase 1 — Foundation.** Establishing the repository skeleton, local
infrastructure, and project scaffolding before feature work begins.

## Tech Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.x (async), Celery, PostgreSQL 16
- **Frontend:** Next.js 15, TypeScript, Tailwind CSS, shadcn/ui
- **Infrastructure (local):** Docker Compose — Postgres, Redis, MailHog
- **Package managers:** uv (Python), pnpm (Node)

## Repository Structure

```
mortgageboss-ai/
├── .github/workflows/   # CI/CD workflows
├── backend/             # FastAPI backend (LP-3)
├── frontend/            # Next.js frontend (LP-5)
├── docs/
│   ├── tickets/         # Per-ticket implementation docs (LP-XXX.md)
│   └── architecture/    # Architecture docs
├── scripts/             # Dev/ops scripts
├── .editorconfig
├── .gitignore
├── README.md
├── CLAUDE.md
└── decisions.md
```

## Conventions

- **Async-first Python** — no synchronous database calls; use async SQLAlchemy
  sessions and async FastAPI route handlers.
- **SQLAlchemy 2.x** — use the modern `Mapped[...]` / `mapped_column()` style.
- **Pydantic v2** — for request/response schemas and settings.
- **Type hints everywhere** — all functions and methods are fully typed.
- **Pytest** — for all tests.
- **Document each ticket** in `docs/tickets/LP-XXX.md`.

## Decision Log

Architectural decisions are recorded in [`decisions.md`](decisions.md) using a
lightweight ADR format.

## Working on Tickets

When implementing a ticket, always create/update the corresponding
`docs/tickets/LP-XXX.md` file with what was done, assumptions made, and
decisions taken.
