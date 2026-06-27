# Development Workflow

This document describes how automated quality checks work in mortgageboss-ai:
GitHub Actions CI (runs on the server) and pre-commit hooks (run locally before
each commit). Together they catch lint, formatting, type, test, and build
breakage early.

## Overview

| Layer            | Runs                  | When                        | Speed         |
| ---------------- | --------------------- | --------------------------- | ------------- |
| Pre-commit hooks | On your machine       | On every `git commit`       | Seconds       |
| GitHub Actions   | On GitHub's runners   | On push to `main` / PRs     | 1–3 minutes   |

Pre-commit gives instant feedback and auto-fixes most issues. CI is the
authoritative gate that runs on a clean checkout.

## Pre-commit hooks

The hooks are defined in [`.pre-commit-config.yaml`](../.pre-commit-config.yaml).

### What they check

- **General hygiene** — trailing whitespace, end-of-file newline, YAML/JSON/TOML
  syntax, large files (>1 MB blocked), merge-conflict markers, case conflicts,
  and line endings normalized to LF.
- **Secret detection** — [detect-secrets](https://github.com/Yelp/detect-secrets)
  scans staged files against `.secrets.baseline` and blocks new secrets. (We use
  detect-secrets rather than gitleaks because it is pure-Python and needs no Go
  toolchain to install.)
- **Python** — `ruff` lint (with `--fix`) and `ruff-format`, scoped to `backend/`.
  The ruff version is pinned to match `backend/uv.lock`, so local and CI
  formatting never disagree.
- **TypeScript/JS/JSON** — `biome check --write`, scoped to `frontend/`. The hook
  is pointed at `frontend/biome.json` via `--config-path frontend` so it uses the
  project's 2-space style (not biome's tab default).

### Install

`pre-commit` is a developer tool, not a project dependency. Install it once,
globally, with any of:

```bash
pipx install pre-commit     # recommended
# or
pip install --user pre-commit
# or, if you use uv:
uv tool install pre-commit
```

Then enable the git hook in this repo:

```bash
pre-commit install
```

### Run manually

```bash
# Run all hooks against every file (good first-time sanity check)
pre-commit run --all-files

# Run a single hook
pre-commit run ruff --all-files
```

The **first run is slow** (1–3 min) while hook environments are downloaded and
built; subsequent runs take seconds.

### When a hook "fails"

Fixer hooks (ruff-format, biome-check, end-of-file-fixer, …) modify your files
and report a failure when they do. That is expected — just re-stage and commit
again:

```bash
git add -u
git commit
```

### Skipping hooks (rarely)

```bash
git commit --no-verify   # bypasses ALL pre-commit hooks
```

Only do this for genuine emergencies (e.g. a hook is broken). Don't make it a
habit: CI runs the same checks and will fail the push anyway, so skipping just
moves the failure later.

## GitHub Actions

Two workflows live in [`.github/workflows/`](../.github/workflows/):

- **`backend-ci.yml`** — runs on changes under `backend/` (or the workflow file).
- **`frontend-ci.yml`** — runs on changes under `frontend/` (or the workflow file).

### When they run

- On **push to `main`**.
- On **pull requests targeting `main`**.

Path filters mean a backend-only change won't spend CI minutes on the frontend
pipeline, and vice versa.

### What each job checks

**Backend** (`uv`, Python 3.12):

1. `uv sync --frozen` — install locked dependencies.
2. `uv lock --check` — verify `uv.lock` matches `pyproject.toml`.
3. `ruff check .` — lint.
4. `ruff format --check .` — formatting.
5. `mypy app/` — strict type checking.
6. `pytest -v` — unit tests (with dummy env vars; see note below).

**Frontend** (`pnpm`, Node 20):

1. `pnpm install --frozen-lockfile` — install locked dependencies.
2. `pnpm lint` — Biome lint + format check.
3. `pnpm typecheck` — `tsc --noEmit`.
4. `pnpm build` — production `next build`.

> **Service-backed tests:** CI runs a **Postgres** service container, so the
> DB-backed suites (models, services, and the API integration suite) run against
> a real test database. Redis/Celery are **not** started — the health-check tests
> tolerate an absent broker (assert `200` *or* `503`), and the integration suite
> mocks Celery `.delay` rather than running a worker. Full broker-backed
> end-to-end testing (a live worker) remains a later concern (see ADR-028).

## Integration tests (LP-45)

`backend/tests/integration/` exercises the API through the **real stack** — real
HTTP (httpx `AsyncClient` via `ASGITransport`), real DB, real auth/JWTs, real
routing/DI/services/tenant-scoping, and real local storage (a temp dir). **Only**
the AI (`classify_document` / `extract_*`) and Celery dispatch (`.delay`) are
mocked, because they are slow/costly/non-deterministic/external (ADR-152). They
**complement** the unit suites (`tests/ai`, `tests/tasks`, `tests/services`),
testing the seams those suites mock.

What they cover: the auth, loan-file, document, borrower/property, and override
flows end-to-end; a **systematic tenant-isolation pass** (every company-scoped
route → `404` cross-company, lists don't leak — the security-critical goal); and
contract/leak checks (no `storage_path` / `inbox_token` / raw SSN / unmasked
account number in any response).

Run with coverage:

```bash
cd backend
uv run pytest tests/integration -v                 # just the integration suite
uv run pytest --cov=app --cov-report=term-missing  # whole suite + coverage
```

Coverage is configured (`[tool.coverage.run]`) with
`concurrency = ["greenlet", "thread"]` — **required** so coverage traces code
running inside SQLAlchemy's greenlet async context; without it the async handler
and service lines are silently dropped (ADR-153). Current overall coverage of
`app/` is **~93%**, with the API layer near-complete and complete tenant-isolation
coverage.

### Viewing results

Open the repo's **Actions** tab on GitHub, or look at the checks on a PR. The CI
status badges in the README link straight to the latest runs.

## Common CI failures and fixes

| Failure                         | Fix locally                                            |
| ------------------------------- | ------------------------------------------------------ |
| `ruff format --check` fails     | `cd backend && uv run ruff format .`                   |
| `ruff check` fails              | `cd backend && uv run ruff check --fix .`              |
| `mypy` errors                   | `cd backend && uv run mypy app/` and fix the types     |
| `pytest` fails                  | `cd backend && uv run pytest -v` and fix the test/code |
| `uv.lock` out of sync           | `cd backend && uv lock`                                |
| Biome lint/format fails         | `cd frontend && pnpm lint:fix`                          |
| `tsc` errors                    | `cd frontend && pnpm typecheck` and fix the types      |
| `next build` fails              | `cd frontend && pnpm build` and fix the error          |
| pnpm lockfile mismatch          | `cd frontend && pnpm install` then commit the lockfile |

## Branch strategy

- This is a solo build; work happens on a working branch (currently `phase1`) and
  lands on `main` via PR.
- Feature branches are optional for larger chunks of work.
- The PR template ([`.github/pull_request_template.md`](../.github/pull_request_template.md))
  prompts for summary, testing, and a checklist.

## Local development cycle

1. Make your change.
2. `git commit` — pre-commit hooks run automatically; re-stage if a fixer
   modified files.
3. Push — GitHub Actions runs the relevant pipeline.
4. Fix any CI failures before merging to `main`.

## Running the full local stack (the consistent dev model — LP-73)

Document processing and the AI needs reasoning run in a **Celery worker**, a separate
process from the API. The settled local-dev model is **all-in-Docker with a shared
storage volume** — chosen to remove the host-API / Docker-worker asymmetry that caused a
real bug (the worker couldn't read host-written files):

```bash
docker compose up -d            # postgres, redis, mailhog — AND the worker (default)
```

- The **worker starts by default** (LP-73 — it's no longer behind a profile), so the
  async/AI features can't silently do nothing because no worker is consuming. After a
  backend code change, rebuild it: `docker compose up -d --build worker`. Watch it with
  `docker logs -f mortgageboss-worker`.
- **Shared storage:** the API (run on the host with `uvicorn`) writes uploads to
  `backend/storage`; the worker container mounts that same directory at `/app/storage`
  (the `worker.volumes` entry), so both read/write one storage root. The relative
  `STORAGE_LOCAL_PATH=./storage` resolves to different real dirs on host vs. container —
  the volume is what makes them one. (Object storage, S3/MinIO, is the production answer;
  the **S3 backend is not yet implemented** — Phase 7.)
- Alternative: run the worker **on the host** (`cd backend && uv run celery -A
  app.tasks.celery_app worker --loglevel=info`) so it shares the host filesystem directly
  (no volume needed). Pick one model; don't mix host-API + Docker-worker without the
  shared volume.

If documents upload but never leave "processing" (or the AI needs never appear), the
worker is almost certainly not running, not rebuilt after a change, or can't see storage —
check `docker logs mortgageboss-worker` first.

## Seeding dev data

There is no public signup (accounts are provisioned — see
[`onboarding-and-tenancy.md`](onboarding-and-tenancy.md)). To get working accounts to
log in with locally, run the minimal seed script (Postgres must be up — `docker compose
up -d`):

```bash
cd backend
uv run python -m app.scripts.seed_dev
```

It creates one company and two users with **real bcrypt-hashed** passwords, and prints
the credentials. It is **idempotent** — safe to re-run (it reports "already existed"
rather than duplicating). Defaults (override via `SEED_*` env vars):

| | Email | Password | Role |
| --- | --- | --- | --- |
| Company | — (slug `demo`) | — | — |
| Admin | `admin@demo.com` | `adminpass123` | ADMIN |
| Processor | `processor@demo.com` | `processorpass123` | PROCESSOR |

Log in with these via the frontend (`/login`) or `POST /api/v1/auth/login`. These are
**DEV-ONLY** default passwords, not secrets — production users are provisioned
differently (see the onboarding doc). The comprehensive seed (lenders, sample loan
files, multiple companies) is a later ticket (LP-48).
