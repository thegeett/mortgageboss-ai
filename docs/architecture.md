# Architecture

A system architecture overview for mortgageboss-ai. This describes the intended
V1 shape and marks what exists **today** versus what arrives in later phases, so
the document stays honest about the current build.

> **Status legend:** ✅ built · 🚧 in progress · 📋 planned (later phase)
>
> As of the end of **Epic 1 (Foundation)**: the skeleton, local infrastructure,
> configuration, health checks, and CI are built. Feature subsystems
> (models, auth, file CRUD, document AI pipeline) are planned for Epics 2–6.

For the full ticket-by-ticket plan see [`phases/phase-1.md`](phases/phase-1.md);
the canonical product plan is the external **V1 Build Plan v2**.

---

## Overview

mortgageboss-ai is a standalone assistant for mortgage **loan processors**. It
helps a processor assemble a complete, accurate loan file — documents, extracted
data, verification findings, conditions, and the lender package — before the file
goes to underwriting, reducing avoidable underwriting conditions.

It is a **monorepo** with a conventional three-tier shape plus a few subsystems:

```
        ┌─────────────┐      HTTPS/JSON      ┌──────────────────┐
        │  Frontend   │ ───────────────────▶ │     Backend      │
        │ Next.js 15  │ ◀─────────────────── │     FastAPI      │
        └─────────────┘                      └──────┬───────────┘
                                                    │
              ┌─────────────────────┬───────────────┼───────────────┐
              ▼                     ▼               ▼               ▼
       ┌────────────┐       ┌──────────────┐  ┌───────────┐  ┌────────────┐
       │ PostgreSQL │       │ Async workers│  │   Redis   │  │File storage│
       │  (source   │       │   (Celery)   │  │  broker / │  │ local → S3 │
       │ of truth)  │       │              │  │   cache   │  │            │
       └────────────┘       └──────┬───────┘  └───────────┘  └────────────┘
                                   │
                                   ▼
                          ┌──────────────────┐     ┌──────────────┐
                          │  Anthropic API   │     │ Email (SMTP) │
                          │ (classify/extract)│    │  MailHog dev │
                          └──────────────────┘     └──────────────┘
```

## Components

- **Frontend** — ✅ Next.js 15 (App Router, TypeScript strict), Tailwind +
  shadcn/ui, TanStack Query for server state, Zustand for client state. Renders
  the processor's UI: dashboard, file detail, document upload, etc. (the home
  page and design system exist today; feature screens arrive in Epics 4–6).
- **Backend** — ✅ FastAPI (async), serving a JSON API. Today: configuration,
  CORS, structured logging, and health endpoints. 📋 Auth, loan-file CRUD,
  document, and verification routes arrive in later epics.
- **Async workers** — 📋 Celery workers (Redis broker) that run the document
  classification → extraction pipeline outside the request cycle (Epic 5).
- **Database** — ✅ PostgreSQL 16 (reachable; schema/models arrive in Epic 2).
  The **single source of truth** for all application state.
- **File storage** — ✅ a storage abstraction (local filesystem in dev, S3 in
  production) for uploaded document bytes (LP-35; see [Storage](#storage-document-bytes--lp-35)).
  The upload endpoint and pipeline that use it arrive next in Epic 5.
- **AI** — 📋 Anthropic Claude, used only for *perception*: classifying document
  types and extracting structured fields from document text. Reached through an
  async client wrapper with retries, logging, and cost tracking (Epic 5).
- **Email** — 📋 SMTP, captured by MailHog locally (✅ infra running), used for
  borrower/loan-officer communication (Phase 4).

## Storage (document bytes — LP-35)

Uploaded document **bytes** live in a storage backend, never in the database.
The `Document` row holds only a `storage_path` pointing at them (LP-15,
ADR-057). All byte I/O goes through a single abstraction so calling code never
knows or cares where the bytes physically live.

- **`StorageBackend` interface** (`app/storage/base.py`) — async
  `save` / `read` / `delete` / `get_url`. `save` takes the server-controlled
  ids + filename + bytes and returns the `storage_path` to persist;
  `get_url` returns a direct URL or `None`.
- **`LocalStorageBackend`** (`app/storage/local.py`) — dev backend writing under
  a configured root (`storage_local_path`, default `./storage`). Blocking file
  I/O is wrapped in `asyncio.to_thread` so the interface is genuinely async.
  `get_url` returns `None` — local files are served only through the auth'd
  download endpoint (LP-36), never a direct URL.
- **Factory** (`app/storage/get_storage_backend`) — settings-driven
  (`storage_backend`); returns the local backend today. An **S3 backend** lands
  in production (Phase 7) as a new implementation + an `"s3"` branch — **no
  calling-code changes** (`get_url` returns a presigned URL there).

**Path pattern** — tenant-prefixed, UUID-named:
`{company_id}/{file_id}/{document_id}.{ext}`. Every component is a
**server-controlled UUID**; only the extension derives from the (sanitized,
allowlisted) filename. This prevents collisions and removes user input from the
path entirely.

**Security.** File/path handling is a classic vulnerability source, so:
the path is built from server ids, never user input; the local backend
**resolves every path and rejects anything that escapes the root** (`../`,
absolute paths, symlinks) with a `StorageError` *before* touching the
filesystem; the storage root sits **outside any web-served/static directory**,
so files are reachable only through auth'd endpoints; and stored files are
**data, never executed**. See ADR-112 / ADR-113.

## Data flow (intended V1)

How a loan file moves through the system once feature work lands:

1. **Intake** — a loan file is created (borrower, property, loan, lender). 📋
2. **MISMO import** — the 1003/MISMO 3.4 file seeds **stated** data. 📋
3. **Documents** — the processor uploads PDFs/images; each is stored, then
   **classified** (Haiku) and **extracted** (Sonnet) into typed, **verified**
   data by async workers. 📋
4. **Verification** — deterministic rules compare stated vs verified data and
   check guidelines/overlays, producing **findings** (red/yellow/green). 📋
5. **Conditions & needs** — findings and a generated **needs list** tell the
   processor what is missing or wrong. 📋
6. **Lender package** — once clean, the file is assembled for submission. 📋

## Key architectural principles

These shape every later design decision:

- **The database is the source of truth.** All state lives in PostgreSQL; nothing
  authoritative lives in memory or in the AI layer.
- **Stated vs verified data are tracked separately.** Borrower-claimed data
  (MISMO/1003) and evidence-backed data (documents) are distinct, so the system
  can compare them — that comparison is the product's core value.
- **Deterministic rules; AI for perception.** Business rules (DTI/LTV, guideline
  checks) are deterministic code. AI is used only to *perceive* documents
  (classify, extract). Decisions are never left to a model.
- **AI never touches the database directly.** Models receive text and return
  structured data via typed tools/schemas; persistence is done by application
  code, never by the model.
- **Async everywhere.** Async route handlers, async DB sessions, async AI calls
  (ADR-022); long work runs on Celery workers, not in the request.
- **Soft delete everywhere.** Records are marked deleted, not physically removed,
  preserving history.
- **Versioning on derived data.** Extractions and verification runs are versioned
  (only one "current"), so re-runs are auditable and reversible.
- **Audit log captures everything.** An activity log records who/what/when across
  user, system, and AI actions.
- **Multi-tenancy from day one.** Every row is scoped to a `company_id`; queries
  are filtered by the current user's company so tenants are isolated.

## Technology choices

| Area              | Choice                                  | ADR        |
| ----------------- | --------------------------------------- | ---------- |
| Monorepo          | Single repo, backend + frontend         | ADR-001    |
| Local services    | Docker Compose (Postgres/Redis/MailHog) | ADR-002, 004, 006 |
| Database          | PostgreSQL 16                           | ADR-003    |
| Backend language  | Python 3.12                             | ADR-007    |
| Python packaging  | uv                                      | ADR-008    |
| Web framework     | FastAPI                                 | ADR-009    |
| ORM               | SQLAlchemy 2.x async                     | ADR-010, 022 |
| Python lint/format| Ruff                                    | ADR-011    |
| Python types      | mypy (strict)                           | ADR-012    |
| Frontend framework| Next.js 15 (App Router)                 | ADR-013    |
| Frontend types    | TypeScript strict                       | ADR-014    |
| Component library | shadcn/ui                               | ADR-015    |
| JS lint/format    | Biome                                   | ADR-016    |
| Node packaging    | pnpm                                    | ADR-017    |
| State management  | TanStack Query + Zustand                | ADR-018    |
| Typography        | System font stack                       | ADR-019    |
| Configuration     | Pydantic Settings                       | ADR-020    |
| Logging           | structlog                               | ADR-021    |
| Health checks     | Three-tier (live/ready/detail)          | ADR-023    |
| CI                | GitHub Actions                          | ADR-025    |
| Local hooks       | pre-commit                              | ADR-026    |

See [`../decisions.md`](../decisions.md) for the full rationale behind each.

## What is intentionally NOT in the V1 architecture

- No direct lender-portal/LOS integrations (processors still submit manually).
- No microservices — a single backend service is sufficient for V1.
- No Kubernetes / container orchestration in V1 (Docker Compose locally).
- No real-time WebSockets — the UI polls for async processing status.
- No jumbo loan program (Conventional and FHA only).
- No OCR for scanned PDFs in V1 (text-based PDFs only; flag if no text).

## Phase roadmap

The build is organized into epics (see [`phases/phase-1.md`](phases/phase-1.md)):

1. **Epic 1 — Repo & Infrastructure Setup** ✅ *(this epic; LP-1…LP-8)*
2. **Epic 2 — Database & Models** 📋 *(next; LP-9 onward)*
3. **Epic 3 — Authentication & Authorization** 📋
4. **Epic 4 — Loan File CRUD** 📋
5. **Epic 5 — Document Upload & Processing** 📋
6. **Epic 6 — Testing, Polish & Phase 1 Completion** 📋

We are at the **end of Epic 1**: foundation built and documented; Epic 2 begins
the database schema and models.
