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

## Documentation

- **Implementation history:** see [`docs/tickets/`](docs/tickets/) for a record
  of what each ticket delivered.
- **Architectural decisions:** see [`decisions.md`](decisions.md) for the
  lightweight ADR log.
