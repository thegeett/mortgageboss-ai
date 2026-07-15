# Phase 3 Staging Deployment — Recon & Plan

**Scope:** stand up an internal **staging URL** so a tester + Priya can exercise the app **through
Phase 3 only**. Recon-and-planning only — no app code was written or changed in this pass.
**Branch reconned:** `phase3_new_AI_arch_finding_stage2` (the current working branch; the prompt named
`phase3_new_AI_arch_finding` — this branch is that line of work plus the LP-3xx fact-tag engine).

> **Doc availability caveat.** Only `docs/verification-architecture-v2.docx` is in the repo (read +
> extracted). **`V1_Build_Plan_v2.docx` was not on disk** (it was to be a session attachment). So
> build-plan (infrastructure) claims below are verified **against the code**, using the prompt's
> build-plan summary as the reference; where I could not cross-check a build-plan claim against the doc
> itself, it is marked *(build-plan per prompt)*. The architecture doc governs verification; the code is
> the tie-breaker where they conflict.

---

## 0. The headline finding — read this first

**A tester can upload documents, import MISMO, run verification, and click through findings today — but
those findings come from the OLD deterministic engine, NOT the fact-tag architecture the v2 doc
describes.** The fact-tag engine (the whole point of `verification-architecture-v2.docx`) is **fully
built and tested but not wired to any request or worker** — it is invoked **only by tests**.

- `app/services/verification_run.py::run_verification` (the LP-321 fact-tag orchestrator) and the whole
  `app/verification/rule_engine/` + `app/verification/tag_materialization/` stack have **zero non-test
  importers** (verified: `grep -rn "services.verification_run" app --include=*.py | grep -v test` →
  nothing).
- The LIVE verification path is the LP-78 deterministic engine: `app/api/verification.py` →
  `_enqueue_cross_source` → `app/tasks/cross_source.py::run_cross_source_pass` → `Finding` rows →
  `app/api/findings.py` → the Wireframe-5 UI (`frontend/components/file/verification/*`).

**Consequence for the decision to deploy:** the deployment IS worth doing — the deterministic
upload→classify→extract→verify→findings loop is real and demoable. **But Priya will be testing the
engine the v2 architecture supersedes.** She will not see the four-tab honesty-contract surface
(needs-attention / satisfied / no-longer-applies / not-applicable), the couldnt_check false-green guard,
ratification-pending judgments, or any of the LP-312→330 identity/occupancy work. If the goal of her
testing is to validate the *new* architecture, this deployment does not do that yet, and no amount of
infra changes it — it needs the engine wired to the surface first (see §5, LP-331).

---

## 1. What exists today (verified per file)

### 1.1 Backend
| Item | Code | Notes |
|---|---|---|
| Entrypoint | `app/main.py` (FastAPI `app`) | uvicorn target `app.main:app`. |
| Python | `pyproject.toml` `requires-python = ">=3.12"` | managed with `uv`. |
| Config | `app/core/config.py` (`Settings`, pydantic-settings, `.env`) | env-var driven; required vars have no default → app refuses to boot without them. |
| API | `/api/v1` prefix; routers: auth, loan-files, borrowers, property, lenders, needs, activity, documents (nested+flat), findings, stated-financials, dti, ltv, calculators, overlay-admin, validation-aid, verification, preferences (`app/main.py:105-122`) | **`dev_router` is mounted when `not settings.is_production` (`app/main.py:126`) — so it IS reachable in staging** (`environment=staging` is not production). The routes stay auth'd + tenant-scoped, but they are exposed → the perimeter (§6) must cover them, or gate them on `is_development` / drop the `/api/v1/dev` prefix at the proxy. Flagged in LP-334. |
| Health | `/health`, `/health/live`, `/health/ready` (`app/main.py:143-175`) | three-tier, matches build-plan. |

### 1.2 Frontend
| Item | Code | Notes |
|---|---|---|
| App | `frontend/` — Next.js 15 App Router, TS, Tailwind, Biome | routes under `app/(protected)/` + `app/(auth)/login`. |
| Build | `next build` / `next start` (`package.json`) | no `engines` pin (Node version unspecified — flag: pin Node 20/22 for staging). |
| Backend URL | `frontend/lib/api/client.ts:5` — `NEXT_PUBLIC_API_URL ?? "http://localhost:8000"` | **baked at BUILD time** (Next `NEXT_PUBLIC_*`). Staging needs it set before `next build`, not at runtime. |
| Talks only to backend | `apiClient` (axios) → `/api/v1/*` only | no direct AI/storage calls from the browser (verified in `lib/api/*`). |
| Real vs stubbed tabs | Verification tab **real** (see §2); later-phase file tabs empty by design | — |

### 1.3 Database
| Item | Code | Notes |
|---|---|---|
| Driver | `postgresql+asyncpg://` (SQLAlchemy async) | `alembic/env.py:25` injects `settings.database_url`. |
| Migrations | Alembic, 48 versions under `alembic/versions/` | entrypoint `alembic upgrade head`. |
| Multi-tenant / soft-delete / UUID+`LF-` / column encryption | present (per `app/models/*`, LP-14 encryption at `encryption_key`) | encryption is **application-level Fernet**, env-injected (`config.py:90`) — good for per-env key isolation. |

### 1.4 Async workers
| Item | Code | Notes |
|---|---|---|
| Celery app | `app/tasks/celery_app.py` — Redis broker+backend from settings; JSON-only serialization | **no beat schedule / no periodic tasks** → **beat is NOT needed**. |
| Registered task modules | `_TASK_MODULES = [health, document_processing, needs, cross_source]` | one worker, default queue. |
| Worker-seam guards | `tests/tasks/test_task_registration.py` asserts every `@celery_app.task` module is in `_TASK_MODULES`; enqueue-failure → run marked FAILED (`app/api/verification.py:116-128`), and a watchdog reconciles a stuck RUNNING → FAILED on read (`verification.py:74-104`). | Both build-plan lessons are guarded in-repo. |

### 1.5 File storage — **local disk only; S3 is NOT implemented**
- `app/storage/` = `base.py`, `local.py`, `__init__.py`. **There is no `s3.py`.** `base.py:72-74`
  states "an S3 backend lands in production (Phase 7)". `config.py:99` offers
  `storage_backend: Literal["local","s3"]` but **only `local` resolves to an implementation**.
- **This is the single most consequential infra fact.** Files live at `storage_local_path` (default
  `./storage`), and the **API process (upload/download) and the worker process (classify/extract read
  the bytes) must share the same filesystem.** With separate api/worker containers on most PaaS, they
  do **not** share disk — the worker would not find the uploaded bytes and the whole pipeline breaks.
  This drives the topology choice (§4) and is the #1 predicted staging break (§8).

### 1.6 AI layer
| Item | Code | Notes |
|---|---|---|
| Calls | `app/ai/*` (classification, extraction, the fact-tag `rule_judgment`/`tag_production` — the latter unwired) | |
| Models | `config.py:58-59`: classification `claude-haiku-4-5` (matches "Haiku"), extraction **`claude-opus-4-8`** | **DRIFT:** build-plan says Sonnet for extraction; code uses **Opus 4.8**. Configurable via env, so staging can pin a cheaper model, but note the cost delta. |
| Key / provider | `anthropic_api_key` env-injected; model IDs env-overridable; **no base-URL/provider override** | staging can use a distinct key (cost attribution) with no code change. |

### 1.7 Phase 3's "missing 20%"
The incomplete work is the **fact-tag rewrite**, not the deterministic product loop:
- Arch doc STATUS: **§3D fact-tag architecture = IN PROGRESS**; **UI four-tab surface = NOT STARTED
  ("biggest remaining gap between engine and product")**; §7 discovery, §9 reconciliation, §10 action
  buttons = TO BUILD.
- In code, the engine itself is far past 80% *as an engine* (2079 tests green, LP-312→330), but it is
  **not connected** to any endpoint/worker/UI. So the "missing 20%" that matters for a product is the
  **wiring + the four-tab surface**, and it is **~0% for the new engine**.
- **Does the missing 20% block the tester?** **No — for the OLD engine.** The deterministic loop is
  complete and testable. **Yes — for the new architecture**, which is unreachable from the UI.

### 1.8 What one full (live) verification run touches
`upload → process_document (Haiku classify → tier route → Opus extract → record findings) →` then
`POST verification → run_cross_source_pass (Celery, AI cross-source pass) → Finding rows → findings API`.
**Services that must be live for a run:** Postgres, Redis (broker+backend), the Celery **worker**, the
Anthropic API, and the **shared storage volume** (worker reads the uploaded bytes). The API process
alone is not enough — a run that never reaches the worker strands (guarded to FAILED, not stuck).

### 1.9 Docs-vs-code discrepancy table
| Claim | Doc | Code | Agree? |
|---|---|---|---|
| Findings UI exists (full Verification tab) | build-plan §3.7 (per prompt): yes, Phase 3 wk4 | Wireframe-5 tab exists (`components/file/verification/*`) **against the deterministic model** | **Both true** — see §2 |
| Four-tab fact-tag surface exists | arch doc: **NOT STARTED** | absent (no four-tab UI; findings UI is the old model) | **Agree (with build-plan) — it does not exist** |
| Fact-tag engine is the live engine | arch doc: §3D IN PROGRESS | built, **unwired** (test-only) | Code confirms arch doc |
| Extraction model | build-plan: Sonnet | `claude-opus-4-8` | **Drift** |
| S3 storage | build-plan: S3 in prod | not implemented (Phase 7) | Consistent (local-only today) |
| Email infra | build-plan: Phase 4 | no send path (SMTP config unused) | Consistent (none) |
| Node version | build-plan: Next.js | no `engines` pin | Gap (pin for staging) |

**What a human can actually see and click today:** log in → create a loan file → upload documents →
import a MISMO 3.4 file → view classified documents + extracted data + DTI/LTV calculators → trigger a
verification run → view **deterministic** findings in the Wireframe-5 Verification tab (stats, filter
pills, expandable finding cards with why-it-matters / suggested-fix / source evidence, per-finding
actions). **They cannot** see the fact-tag four-tab surface or any LP-312→330 behavior.

---

## 2. Resolution of the findings-UI tension

**Both documents are right about different things.** The Wireframe-5 Verification tab exists and is
wired to the **deterministic** engine; the fact-tag architecture's four-tab surface does **not** exist.

- **Real + wired (deterministic):** `frontend/app/(protected)/loan-files/[id]/verification/` +
  `frontend/components/file/verification/{verification-panel,verification-stats,findings-list,finding-card,finding-filters}.tsx`
  + `frontend/lib/api/verification.ts` → `app/api/verification.py` / `app/api/findings.py` →
  `app/tasks/cross_source.py::run_cross_source_pass` → `Finding` rows.
- **Built + NOT wired (fact-tag):** `app/services/verification_run.py`, `app/verification/rule_engine/*`,
  `app/verification/tag_materialization/*` — invoked only by `tests/`.

So the arch-doc STATUS ("processor surface NOT STARTED, the biggest remaining gap") is accurate **for the
new architecture**, and the build-plan Verification tab is accurate **for the deterministic model**. The
UI a tester sees is the old one.

---

## 3. Deployment requirements

### 3.1 Processes
| Process | Command (from code) | Notes |
|---|---|---|
| API | `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT` | 1 instance is plenty for 2 users. |
| Worker | `uv run celery -A app.tasks.celery_app worker --loglevel=INFO` | **required** — classify/extract/verify run here. |
| Beat | — | **NOT needed** (no periodic tasks). |
| Migrate (one-shot, pre-deploy) | `uv run alembic upgrade head` | **exactly once**, in a release/pre-deploy step — **never** in the worker or on every API boot. |
| Frontend | `pnpm build` then `pnpm start` (or static) | `NEXT_PUBLIC_API_URL` set at **build** time. |

### 3.2 Backing services
- **PostgreSQL 16** (asyncpg). Dedicated to staging.
- **Redis 7** (Celery broker + result backend, and app cache). Dedicated to staging.
- **Object storage:** **none** — local disk only (no S3 in code). Requires a **persistent volume shared
  by API + worker** (see §4).

### 3.3 Env var manifest (from `app/core/config.py` — not guessed)
**Required to boot (no default — app refuses to start):**
- `DATABASE_URL` — `postgresql+asyncpg://…` *(staging-distinct)*
- `REDIS_URL` — `redis://…` *(staging-distinct)*
- `ANTHROPIC_API_KEY` *(staging-distinct — cost attribution)*
- `JWT_SECRET_KEY` *(staging-distinct)*
- `ENCRYPTION_KEY` — Fernet 44-char urlsafe-b64 *(staging-distinct — a prod-encrypted column must not
  decrypt in staging)*

**Required for full function / correct behavior:**
- `ENVIRONMENT=staging` (drives log format + gates the dev router off)
- `CORS_ALLOWED_ORIGINS=["https://<staging-frontend>"]` (default is `http://localhost:3000` — must change)
- `NEXT_PUBLIC_API_URL=https://<staging-api>` (frontend build-time)
- `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` — optional; default to `REDIS_URL` (leave unset to share
  the one staging Redis)
- `STORAGE_BACKEND=local`, `STORAGE_LOCAL_PATH=/data/storage` (a path on the shared persistent volume)

**Optional / has a safe default:** `DEBUG` (leave false), `LOG_LEVEL`, `LOG_FORMAT` (set `json` in
staging), `ANTHROPIC_MODEL_CLASSIFICATION` / `ANTHROPIC_MODEL_EXTRACTION` (can pin a cheaper model),
`AI_*` retry/timeout, `DATABASE_POOL_*`, `SMTP_*` (**unused — do not set / no email**), needs-flagging
flag.

**Flag:** no env var is read anywhere I could find that is absent from `Settings` (spot-checked
`DATABASE_URL`, `REDIS_URL`, `ANTHROPIC_API_KEY`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`, storage, celery).

### 3.4 URL surface (publicly reachable)
Only **two**: the **frontend** and the **API**. **No public webhook** (no inbound email — Phase 4 absent).
Redis/Postgres/worker must **not** be publicly reachable.

---

## 4. Recommended staging topology

**Recommendation: a single small VM running `docker-compose` (e.g. Fly.io single-machine app, an AWS
Lightsail instance, or a $10–20/mo VPS), all five processes on one host, with API + worker bind-mounting
the same `./storage` directory.**

**Why (the deciding factor is §1.5):** storage is **local-disk only** and the API and worker **must share
the filesystem**. A single host with a shared bind mount satisfies that with **zero code changes** — the
explicit "prefer whichever the code already supports without modification" instruction. It is also the
cheapest and simplest thing that runs the *real* stack (Postgres + Redis + api + worker + frontend)
honestly for two users, with the worker seam exercised through the real broker. Basic-auth / IP-allowlist
(§5) goes on a one-line reverse proxy (Caddy/nginx) in the same compose file; Caddy gives automatic HTTPS.

**Runner-up: Render** (managed Postgres + Redis, HTTPS free, trivial basic-auth). What it costs today:
because a Render **Disk attaches to a single service** and is **not shared across services**, API + worker
must be collapsed into **one** Render service running both `uvicorn` and `celery` under a process manager
(honcho/supervisord) with one attached Disk, and the frontend as a separate service. That works but is
awkward and pins that service to a single instance.

**What flips the call:** implementing the **S3 storage backend** (Phase 7 work, out of scope here).
Once bytes live in object storage, API and worker no longer need a shared filesystem, and **Render or
Railway with clean separate api/worker services becomes the obvious pick** — at which point the single-VM
recommendation should be revisited. Until then, shared local disk is the constraint that decides it.

*(Kubernetes/microservices/autoscaling/CDN/monitoring stacks are deliberately excluded per the build-plan
"simple PaaS, no orchestration" posture and the two-user scope.)*

---

## 5. Blocking gaps (sized `LP-3xx` — next free is LP-331)

**Ordered: does the tester's core loop work?**

- **LP-331 — (NOT a deploy blocker; the reason to question the deployment) Wire the fact-tag engine to a
  surface, or accept testing the deterministic engine.** *(L — weeks; explicitly out of scope for a
  staging stand-up.)* If Priya's testing must validate the v2 architecture, the deployment does not
  achieve that; decide with Geet whether to (a) ship staging on the deterministic engine now and label it
  clearly, or (b) wait for the four-tab surface. **This is a product decision, not an infra task** —
  surfaced because it reshapes what the deployment is *for*.
- **LP-332 — Shared-storage topology (BLOCKING for a working pipeline).** *(S)* Ensure API + worker share
  the persistent volume at `STORAGE_LOCAL_PATH`. If deployed with separate non-shared disks, uploads
  succeed but classification/extraction/verification silently fail to find bytes. Encoded in the §4
  single-VM recommendation; must be validated by the §8 acceptance check.
- **LP-333 — Staging seed of *uploadable* synthetic documents (BLOCKING for "do anything useful").** *(M)*
  `app/scripts/seed_dev.py` creates only a company + admin + processor **users** — **no loan files, no
  documents**. `LF-6T3N` in-repo is `tests/verification/eval/fixtures/lf6t3n_tagged_snapshot.json` — a
  **fact-tag snapshot artifact**, not uploadable PDFs and not consumed by the live pipeline. A tester
  cannot exercise upload→classify→extract without synthetic **document files**, which come from the
  **separate `mortgageboss-synthetic` companion tool**. Either (a) add a staging seed that ingests
  companion-tool output, or (b) document the manual companion-tool → upload workflow for the tester.
- **LP-334 — Perimeter auth + HTTPS + isolation wiring (BLOCKING per §6).** *(S)* Basic-auth/IP-allowlist
  proxy in front of both URLs (this also covers the **dev router** `/api/v1/dev/*`, which is live in
  staging since env ≠ production); distinct staging Postgres/Redis/keys; confirm HTTPS-only; keep
  `STORAGE_BACKEND=local` (setting `s3` raises `ValueError` at `get_storage_backend` — the S3 branch is
  unimplemented). Non-negotiable given no Phase 7 hardening.
- **LP-335 — Pin Node + a `Dockerfile`/compose for the stack (BLOCKING to deploy).** *(S)* No `engines`
  pin in `frontend/package.json`; no container/PaaS config in-repo. Propose (do not build) the artifacts
  in §9.

**Nice-to-have (not blocking):** pin a cheaper `ANTHROPIC_MODEL_EXTRACTION` for staging cost; set
`LOG_FORMAT=json`.

---

## 6. Environment isolation (hard requirements) — status

- **Perimeter auth:** **MUST ADD** (LP-334). No MFA / no auth rate-limiting / no upload malware scan
  exist (Phase 7 absent) — the perimeter does that job. Basic-auth or IP-allowlist over both URLs. **Note
  the dev router:** `/api/v1/dev/*` is mounted whenever the env is not `production` (so it is live in
  staging) — the perimeter must sit in front of it, or block `/api/v1/dev` at the proxy.
- **No real PII in staging:** **enforce.** Seed only from the `mortgageboss-synthetic` companion +
  `LF-6T3N`. **Code paths that could leak real PII to staging:** none automatic (staging is empty until
  someone uploads) — **the risk is entirely human: a tester/Priya uploading a real client file.** There
  is **no upload-time guard** that would reject real PII. See the Open Question — this is the highest-
  consequence item.
- **Distinct encryption key:** **confirmed env-injected** (`config.py:90`, `ENCRYPTION_KEY`) — a staging
  key can't decrypt prod columns and vice-versa, as long as a distinct value is set.
- **Distinct Anthropic key + separate Postgres/Redis:** supported by config; **must be set staging-
  distinct** (no shared state).
- **No outbound email:** **confirmed by construction** — no send path in code (`grep` for
  `smtplib/aiosmtplib/send_email/sendmail` → nothing; SMTP settings exist but are unused). True until
  Phase 4.
- **HTTPS:** the recommended proxy (Caddy) or PaaS provides it; confirm no plain-HTTP fallback and that
  `NEXT_PUBLIC_API_URL` is `https://`.

---

## 7. Known-incomplete surfaces (tell the tester up front — not bugs)

- **The Verification tab shows deterministic-engine findings, not the v2 fact-tag four-tab surface.** No
  needs-attention/satisfied/no-longer-applies/not-applicable tabs; no couldnt_check/ratification-pending
  semantics; none of the LP-312→330 identity/occupancy behavior. *(This is the big one.)*
- **File-detail tabs for later phases are empty** (communication/inbox/timeline = Phase 4; conditions =
  Phase 4.5; AI chat = Phase 5; synthesis/lender package = Phase 6). Empty = correct.
- **No email anywhere** (drafts, per-file inbox, request-docs-by-email) — Phase 4.
- **No malware scanning on upload, no MFA, no auth rate-limiting** — Phase 7; the perimeter compensates.
- **DTI/LTV and rule thresholds are largely `validated=false`** (see §10) — over-flagging is expected and
  is *not* the tool being wrong.

---

## 8. Worker-seam acceptance check (the real acceptance criterion)

The acceptance check is **not** "API returns 200." It is: upload a synthetic loan file → confirm
**classification + extraction run in the worker** → confirm a **verification run completes through the
real broker** → confirm a deliberately-broken enqueue surfaces as **FAILED**, not stuck RUNNING.

**In-repo readiness (verified):** `tests/tasks/test_task_registration.py` (every task module registered);
enqueue-failure → run FAILED (`app/api/verification.py:116-128`); stuck-RUNNING watchdog → FAILED
(`verification.py:74-104`). Run the registration guard against the **staging** settings as part of the
release step.

**Prediction — where the pipeline will break under a real deployment (the most useful output):**
1. **#1: shared storage (LP-332).** If API and worker do **not** share the `STORAGE_LOCAL_PATH` volume,
   the upload persists to the API's disk, the worker can't read the bytes → `process_document`
   classification fails → no extraction → verification has nothing → the tester sees a stuck/empty file
   with no obvious cause. This is the single most likely break and follows directly from "S3 not
   implemented" (§1.5). **The acceptance check must assert the worker read the uploaded bytes**, not just
   that a task ran.
2. **#2: seed (LP-333).** With no uploadable synthetic docs in-repo, the acceptance check can't even start
   until the companion-tool documents are available.
3. **#3: env completeness.** Any of the five no-default vars missing → the process refuses to boot
   (fail-loud, easy to spot); `CORS_ALLOWED_ORIGINS` still at localhost → the browser is blocked from the
   API (silent-ish, check the network tab).

Report the end-to-end result **after** the first deploy; expect break #1 or #2 first.

---

## 9. Proposed artifacts (to write later, not now)

- **`backend/Dockerfile`** — `python:3.12-slim`, `uv sync`, non-root, `CMD uvicorn app.main:app`; a
  `worker` variant/override running the celery command. (Same image, different command.)
- **`frontend/Dockerfile`** — `node:22-alpine`, `pnpm install --frozen-lockfile`, `NEXT_PUBLIC_API_URL`
  as a build ARG, `pnpm build` → `pnpm start`.
- **`docker-compose.staging.yml`** — postgres:16, redis:7, api, worker (both mounting a named volume at
  `/data/storage`), frontend, and a Caddy reverse proxy doing basic-auth + HTTPS in front of api +
  frontend. One-shot `migrate` service running `alembic upgrade head` before api starts.
- **Staging seed command** — `uv run python -m app.scripts.seed_staging` that (a) creates the staging
  company + a tester + Priya users, and (b) ingests `mortgageboss-synthetic` output as uploaded documents
  for one or two synthetic loan files (or, minimally, documents the manual companion-tool → upload steps).

---

## 10. Threshold discipline (matters more here than in prod)

- **The live engine is the deterministic one**; its rules + gates live as version-controlled files
  (`app/verification/rules/` — `rule_kinds.csv`, `specs/*.yaml`, `samples.py`), read via
  `load_rule_spec()` from `_SPECS_DIR` (repo path). **Confirmed: no env/DB threshold-override mechanism
  and no staging-only override path** — staging reads the same committed specs; git history is the audit
  trail. Do not introduce one.
- **Most thresholds are `validated=false`** (agency Fannie/Freddie defaults encoded in the specs; Priya
  confirms lender **overlays/deviations**, not all ~130 rules). **Staging must tell Priya which thresholds
  are unvalidated**, so she reads over-flagging as "numbers not yet confirmed," not "the tool is wrong."
  Surface the `priya_validated` / `threshold_needs_signoff` flags in her test brief.
- Caveat tying back to §0: because the **fact-tag** spec engine (the one behind `load_rule_spec`) is not
  the live path, Priya's threshold feedback will actually land on the **deterministic** engine's
  thresholds. Note that in her brief so feedback is attributed to the right engine.

---

## 11. Open questions (for Geet — resolve before deploying)

1. **[HIGHEST CONSEQUENCE] Will Priya test with real client files?** If yes, the "no real PII in staging"
   / GLBA constraint is violated — there is **no upload guard** to stop it. This may change the hosting
   decision (real PII would demand prod-grade isolation, encryption-at-rest posture, and access controls
   this staging plan deliberately omits). **Do not assume either way — confirm with Geet.**
2. **Is this deployment meant to validate the NEW (fact-tag) architecture or just the Phase-3 product
   loop?** Per §0/§2 it can only do the latter today. If the former, sequence LP-331 (wiring + four-tab
   surface) first.
3. **Companion `mortgageboss-synthetic` availability** — is it runnable to produce staging documents, and
   is its fake-PII mapping the one to seed from? (Blocks LP-333.)
4. **Extraction on Opus 4.8 vs Sonnet** — accept the cost, or pin a cheaper model for staging via
   `ANTHROPIC_MODEL_EXTRACTION`? (Config supports it; behavior/quality delta unmeasured here.)
5. **Hosting owner + budget** — single-VM/compose (recommended) vs Render (runner-up). Confirms §4.

---

*Recon only. No application code changed. Committed locally on `phase3_new_AI_arch_finding_stage2`; not
pushed.*
