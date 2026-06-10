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

> **Integration tests:** CI does not start Postgres/Redis. The health-check
> tests tolerate absent services (they assert `200` *or* `503`), so they pass in
> CI. Full service-backed integration testing is a Phase 7 concern (see ADR-028).

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
