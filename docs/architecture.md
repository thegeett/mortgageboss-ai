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
- **AI** — Anthropic Claude, used only for *perception*: classifying document
  types and extracting structured fields from document text. Reached through an
  async client wrapper with retries, metadata logging, and cost estimation
  (✅ LP-37; see [AI client](#ai-client-lp-37)). The classifier (LP-38) and
  extractor (LP-39) that use it arrive next in Epic 5.
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

## AI client (LP-37)

Every Claude API call flows through one wrapper (`app/ai/client.py`) so the AI
features — document classification (LP-38) and extraction (LP-39) — call
`complete(...)` and stay focused on their own logic. The wrapper owns the
cross-cutting concerns:

- **Singleton client** — a lazy, cached `AsyncAnthropic` (`get_anthropic_client`,
  mirroring the LP-35 storage factory). The missing-key error fires at **call
  time**, not import, so the app and tests load without a key. The wrapper owns
  retries, so the SDK's own retries are disabled (`max_retries=0`).
- **Transient-only retries** — rate limits (429), server errors (5xx), and
  connection/timeout errors are retried with **exponential backoff + jitter**, up
  to `ai_max_retries` attempts. Deterministic 4xx (400/401/403/404/422) **fail
  fast** — retrying them only wastes time and money. `_is_transient` classifies
  via the SDK's exception hierarchy.
- **Metadata-only logging (privacy)** — each attempt/outcome logs **metadata**
  (model, token counts, latency, attempt, outcome, error type) and **never** the
  prompt or response **content**, which carries borrower PII (pay-stub /
  bank-statement data). Any content logging would be a redacted, debug-only
  option — not the default.
- **Usage surfaced for cost** — `complete` returns an `AICompletion` (text +
  input/output tokens). `app/ai/cost.py::estimate_cost` turns usage into a USD
  **estimate** via a per-model pricing table; that estimate feeds
  `Extraction.cost_estimate` (LP-16) and `Verification.total_cost_estimate`
  (LP-18).
- **Document / image input (LP-37 revision)** — the AI features send the **full
  document** (PDF / image bytes) for **native reading** — no OCR, no
  pre-extracted text. `build_document_block(content, media_type)` /
  `build_document_message(...)` build base64 `document` (PDF) and `image`
  (JPEG/PNG) content blocks (shape verified against the installed SDK);
  `complete` forwards `messages` to the SDK **unchanged**, so document-bearing
  messages use the **same** retry/logging/timing path as text. The metadata-only
  logging covers this — document bytes, base64, message content, and response
  text are never logged. **Known concern:** multi-page / large documents are
  token-heavy (higher cost + latency) and there are per-request page/size limits
  — *verify against current Anthropic docs*; page-splitting / size-guarding is
  **deferred** (Option A — send the whole document for now). This repositions
  deterministic PDF text extraction (LP-40) as a **dev-only comparison tool**,
  not a pipeline step. See ADR-126.

**Configuration to verify.** Model identifiers (`anthropic_model_classification`
/ `_extraction`) and the pricing table are **configuration that changes over
time** — both are marked with `TODO` to verify against current Anthropic docs.
The cost output is an estimate for tracking, not a billing figure. See ADR-117 /
ADR-118 / ADR-119.

## Classification (LP-38)

The first act of the system "understanding" a document. `classify_document(content:
bytes, media_type: str) -> ClassificationResult` sends the **full document**
(PDF/image bytes) to the Haiku-class model for **native reading** (no OCR, no
pre-extracted text) via the LP-37 document/image content block, and returns
`{ document_type: str, confidence: float, reasoning: str }`. It routes extraction
— LP-39 extracts type-specifically, so the type must be known first.
(Originally took pre-extracted text; changed to full-document input in the LP-38
modification — ADR-127, following the LP-37 revision / ADR-126.)

- **Full-document input** — supported media types are `application/pdf`,
  `image/jpeg`, `image/png` (`image/jpg` normalized). An empty or unsupported
  document short-circuits to `unknown` **without an API call**. The loaded prompt
  is the `system` instruction; the document is the `user` message
  (`build_document_message`).

- **Type as a flexible string** — `document_type` is a lowercase slug
  (`pay_stub`, `bank_statement`, `w2`, …, or `unknown`), not an enum (LP-15); the
  taxonomy is large and evolving (Phase 2). `confidence` drives downstream
  review.
- **Prompt as a file** — the prompt is loaded at runtime from
  `app/ai/prompts/classification/document_classifier.txt` via
  `app/ai/prompt_loader.py::load_prompt` (path-checked, cached), never hardcoded
  in Python. A **starter** prompt ships; the tuned **POC prompt** is pasted into
  that file (no code change). Extraction (LP-39) reuses the loader.
- **Graceful failure** — `classify_document` **never raises**: empty/short text
  short-circuits to `unknown` *without* an API call, and any AI error or
  unparseable output returns `ClassificationResult.unknown(...)`. The pipeline
  (LP-42) treats unknown / low-confidence as `NEEDS_REVIEW`. The JSON parser is
  defensive — it tolerates ```` ```json ```` fences / prose, clamps confidence to
  `[0, 1]`, and falls back to `unknown` on garbage.
- **Privacy** — the document bytes (and their base64) and the model's raw
  response carry borrower PII and are **never** logged; only metadata (the
  classified type + confidence) is. Uses `settings.anthropic_model_classification`
  (a cheaper Haiku-class model; a `TODO`-marked value to verify). This module
  returns a result — persisting it onto the `Document` is the pipeline's job
  (LP-42). See ADR-120 / ADR-121 / ADR-122 / ADR-127.

## Extraction (pay stub — LP-39)

Where classification answered "what kind of document is this?", extraction
answers "what does it say?". `extract_pay_stub(text: str) ->
PayStubExtractionResult` reads the structured values out of a pay stub's text.
**Phase 1 is pay stub only** — one document type end-to-end to establish the
per-type pattern (typed schema + prompt + module) that Phase 2 replicates for the
other ~100 types.

- **Typed, not a field bag** — `PayStubExtraction` is a Pydantic schema with
  named, typed, mostly-nullable fields (`gross_pay: Decimal | None`,
  `pay_period_end: date | None`, …). This is the deliberate departure from the
  POC's generic `ExtractedField` approach (LP-16, ADR-057): typed values are what
  make extracted data **verifiable** downstream (Phase 3 checks them as `Decimal`
  / `date`). The result serializes to JSON for `Extraction.extracted_data`,
  persisted/versioned by the pipeline (LP-42), not here.
- **Honest nulls, no hallucination** — a value not present/legible is `None`,
  **never fabricated**; the prompt forbids guessing. A made-up income figure is
  worse than a missing one (it could falsely pass verification). Extraction
  **reads** faithfully; it does not verify/compute/judge (that's Phase 3).
- **Tolerant coercion** — currency strings (`"$4,200.00"` → `Decimal`) and common
  date formats are parsed; a single uncoercible field drops to `None` and marks
  the run `PARTIAL` rather than failing the whole extraction. `status` reuses
  LP-16's `ExtractionStatus` (`SUCCEEDED` / `PARTIAL` / `FAILED`).
- **Graceful failure & privacy** — `extract_pay_stub` never raises (empty text /
  AI error / unparseable → `PayStubExtractionResult.failed(...)`); the document
  text, raw response, and extracted **values** are never logged (only status,
  confidence, and a non-null field count). Reuses the LP-38 patterns —
  `load_prompt`, the shared defensive parser (`app/ai/parsing.py`), graceful
  failure — and uses `settings.anthropic_model_extraction` (a more capable
  Sonnet-class model). The prompt and field set are **starters** (POC prompt /
  Priya refinement). See ADR-123 / ADR-124 / ADR-125.

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
