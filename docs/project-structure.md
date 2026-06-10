# Project Structure

A "where does X go?" guide to the mortgageboss-ai repository. It reflects the
**current** layout (end of Epic 1) and notes where things will live as later
epics add them.

---

## Repository root

```
mortgageboss-ai/
├── .github/             # CI workflows and GitHub templates
├── backend/             # FastAPI backend (Python, uv)
├── frontend/            # Next.js frontend (TypeScript, pnpm)
├── docs/                # Project documentation (you are here)
├── scripts/             # Dev/ops scripts (e.g. seed data — arrives LP-48)
├── .editorconfig        # Editor defaults (indentation, line endings)
├── .gitignore           # Root ignore rules
├── .pre-commit-config.yaml  # Local git hooks (lint/format/secrets)
├── .secrets.baseline    # detect-secrets allowlist of known non-secrets
├── docker-compose.yml   # Local Postgres + Redis + MailHog
├── README.md            # Setup & navigation hub
├── CLAUDE.md            # Conventions for Claude Code (read every session)
└── decisions.md         # Architecture Decision Records (ADR log)
```

## backend/

```
backend/
├── app/
│   ├── core/         # Cross-cutting infra: config, database, redis, logging
│   ├── models/       # SQLAlchemy ORM models (Epic 2)
│   ├── schemas/      # Pydantic request/response schemas
│   ├── api/          # FastAPI routers & dependencies (Epic 3+)
│   ├── ai/           # Anthropic client, classification, extraction, prompts (Epic 5)
│   ├── services/     # Business logic (e.g. loan-file service, PDF utils)
│   ├── verification/ # Deterministic rule engine & rules (Phase 3)
│   ├── tasks/        # Celery app & async pipeline tasks (Epic 5)
│   ├── storage/      # File storage abstraction: local → S3 (Epic 5)
│   └── main.py       # FastAPI app factory, lifespan, health endpoints
├── tests/            # Pytest suite (conftest.py + test_*.py)
├── pyproject.toml    # Dependencies + tool config (ruff, mypy, pytest)
└── uv.lock           # Locked dependency versions
```

Every directory under `app/` is a Python package (`__init__.py`). Most are
scaffolding today and fill in over Epics 2–6. **Alembic migrations**
(`backend/alembic/`) arrive in LP-9.

Built so far: `app/core/` (config, database, redis, logging), `app/main.py`
(health endpoints), and the test suite.

## frontend/

```
frontend/
├── app/                  # Next.js App Router
│   ├── (auth)/           # Route group: unauthenticated pages (login/register — Epic 3)
│   ├── (app)/            # Route group: authenticated app (dashboard/files — Epic 4+)
│   ├── api/              # Next.js route handlers (proxy to backend when needed)
│   ├── layout.tsx        # Root layout (metadata, fonts, providers)
│   ├── page.tsx          # Home page
│   └── globals.css       # Tailwind layers + design-token CSS variables
├── components/
│   ├── ui/               # shadcn/ui components (owned, in-repo)
│   └── providers.tsx     # Client providers (TanStack Query, Toaster)
├── lib/
│   ├── api/client.ts     # Axios instance + typed API helpers
│   ├── config.ts         # Frontend constants
│   ├── query-client.ts   # TanStack Query client factory
│   └── utils.ts          # cn() class-merge helper
├── hooks/                # Custom React hooks (grows over time)
├── biome.json            # Biome lint/format config
├── components.json       # shadcn/ui config
├── tailwind.config.ts    # Theme (design tokens) + shadcn variables
└── tsconfig.json         # TypeScript (strict) config
```

## docs/

```
docs/
├── README.md                 # Documentation index
├── architecture.md           # System architecture overview
├── glossary.md               # Domain + technical terms
├── poc-learnings.md          # Lessons from the prototype
├── project-structure.md      # This file
├── development-workflow.md    # CI/CD + pre-commit workflow
├── phases/phase-1.md          # Ticket-by-ticket phase plan
└── tickets/LP-XXX.md          # Per-ticket implementation records
```

`docs/database.md` (migration guide) arrives with Alembic in **LP-9**.

## .github/

```
.github/
├── workflows/
│   ├── backend-ci.yml    # ruff, mypy, pytest, uv.lock check
│   └── frontend-ci.yml   # biome, tsc, next build
├── CODEOWNERS
├── pull_request_template.md
└── ISSUE_TEMPLATE/{bug_report,feature_request}.md
```

---

## Conventions: where does X go?

| To add…                     | Put it in…                                                        |
| --------------------------- | ----------------------------------------------------------------- |
| A new **API endpoint**      | a router in `backend/app/api/` (with Pydantic schemas in `app/schemas/`) |
| A new **database model**    | `backend/app/models/`, then an Alembic migration in `backend/alembic/` |
| A new **verification rule** | `backend/app/verification/`                                       |
| A new **AI prompt**         | `backend/app/ai/prompts/<classification|extraction>/...`          |
| A new **business service**  | `backend/app/services/`                                           |
| A new **Celery task**       | `backend/app/tasks/`                                              |
| A new **frontend page**     | `frontend/app/(app)/...` (authenticated) or `frontend/app/(auth)/...` |
| A new **shared UI component**| `frontend/components/` (shadcn primitives in `components/ui/`)    |
| A new **API client call**   | `frontend/lib/api/`                                               |
| **Ticket documentation**    | `docs/tickets/LP-XXX.md` (required for every ticket)              |
| An **architecture decision**| a new ADR in `decisions.md`                                       |
| A **dev/ops script**        | `scripts/`                                                        |
