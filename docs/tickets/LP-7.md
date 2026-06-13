# LP-7 — CI/CD Setup

- **Ticket:** LP-7 — CI/CD Setup
- **Epic:** Epic 1 — Repo & Infrastructure Setup
- **Status:** Completed
- **Date:** 2026-06-10

## Summary

This ticket added automated quality gates. Two GitHub Actions workflows run on
pushes to `main` and PRs targeting `main`: the backend pipeline runs ruff lint,
ruff format check, mypy (strict), pytest, and a `uv.lock` verification; the
frontend pipeline runs Biome lint/format, `tsc` type checking, and a production
`next build`. Path filters keep each pipeline scoped to its area. A
`pre-commit` configuration provides fast local feedback — hygiene checks, secret
detection (detect-secrets), ruff for Python, and Biome for the frontend — all
verified green via `pre-commit run --all-files`. GitHub `CODEOWNERS`, a PR
template, and issue templates were added, along with a development-workflow
guide, CI badges in the README, and ADRs 025–029.

## Acceptance Criteria

| #  | Criterion                                                                | Status |
| -- | ------------------------------------------------------------------------ | ------ |
| 1  | `backend-ci.yml` with lint, format, types, tests, lock-check jobs        | ✅ Done |
| 2  | `frontend-ci.yml` with lint/format, types, build jobs                    | ✅ Done |
| 3  | Both workflows trigger on push to `main` and PRs to `main`               | ✅ Done |
| 4  | Caching for uv and pnpm, invalidated on lockfile change                  | ✅ Done |
| 5  | Workflows designed to complete in < 3 min on cache hit                   | ✅ Done |
| 6  | Workflow status badges in README                                         | ✅ Done |
| 7  | `.pre-commit-config.yaml` with all required hook categories              | ✅ Done |
| 8  | Hooks installable via `pre-commit install`                               | ✅ Done |
| 9  | Documentation explains installing and using pre-commit                   | ✅ Done |
| 10 | `.github/CODEOWNERS` with ownership                                      | ✅ Done |
| 11 | `.github/pull_request_template.md`                                       | ✅ Done |
| 12 | `bug_report.md` and `feature_request.md` issue templates                 | ✅ Done |
| 13 | README updated with CI/CD section and badges                             | ✅ Done |
| 14 | `docs/development-workflow.md` created                                    | ✅ Done |
| 15 | New ADRs (025–029) added to decisions.md                                 | ✅ Done |
| 16 | `docs/tickets/LP-7.md` created                                           | ✅ Done |
| 17 | Workflows verified to run on GitHub                                      | ⏳ On push/PR (see Verification) |
| 18 | Pre-commit hooks installable and runnable locally                        | ✅ Done |
| 19 | A deliberately broken file fails the appropriate check                   | ✅ Done |
| 20 | Workflows pass on the current clean codebase                             | ✅ Done (locally mirrored) |

## What Was Built

### GitHub Actions
- **`.github/workflows/backend-ci.yml`** — single `lint-and-test` job on
  `ubuntu-latest`: installs uv (with cache keyed on `backend/uv.lock`), Python
  3.12, `uv sync --frozen`, `uv lock --check`, `ruff check`, `ruff format
  --check`, `mypy app/`, `pytest` (dummy env vars supplied).
- **`.github/workflows/frontend-ci.yml`** — single `lint-and-build` job: sets up
  pnpm + Node 20 (with pnpm cache keyed on `frontend/pnpm-lock.yaml`), `pnpm
  install --frozen-lockfile`, `pnpm lint`, `pnpm typecheck`, `pnpm build`.
- Both trigger on push to `main` and PRs to `main`, with path filters so only the
  relevant pipeline runs.

### Pre-commit
- **`.pre-commit-config.yaml`** — hygiene hooks (trailing whitespace, EOF fixer,
  YAML/JSON/TOML checks, large-file block at 1 MB, merge-conflict/case checks, LF
  line endings), detect-secrets, ruff + ruff-format (scoped to `backend/`),
  biome-check (scoped to `frontend/`, pointed at `frontend/biome.json`).
- **`.secrets.baseline`** — detect-secrets baseline recording known, intentional
  non-secrets (env-example placeholders, test values, local dev credentials);
  lock files excluded to avoid false positives on integrity hashes.

### GitHub templates
- **`.github/CODEOWNERS`** — `* @thegeett` plus commented placeholders for future
  team ownership.
- **`.github/pull_request_template.md`** — summary, ticket link, change type,
  testing, and a checklist.
- **`.github/ISSUE_TEMPLATE/bug_report.md`** and **`feature_request.md`**.

### Documentation
- **`docs/development-workflow.md`** — CI overview, pre-commit install/use, common
  failures + fixes, branch strategy, local dev cycle.
- **README** — CI badges under the title and a "Continuous Integration" section.
- **decisions.md** — ADR-025…029.

## CI Jobs

| Workflow         | Check                  | Command                  | Est. time |
| ---------------- | ---------------------- | ------------------------ | --------- |
| backend-ci.yml   | Lock verification      | `uv lock --check`        | ~10s      |
| backend-ci.yml   | Lint                   | `ruff check .`           | ~30s      |
| backend-ci.yml   | Format                 | `ruff format --check .`  | ~10s      |
| backend-ci.yml   | Types                  | `mypy app/`              | 1–2 min   |
| backend-ci.yml   | Tests                  | `pytest -v`              | ~30s      |
| frontend-ci.yml  | Lint + format          | `pnpm lint` (biome)      | ~20s      |
| frontend-ci.yml  | Types                  | `pnpm typecheck` (tsc)   | ~30s      |
| frontend-ci.yml  | Build                  | `pnpm build` (next)      | 1–2 min   |

## Pre-commit Hooks

| Hook                     | Catches                                                  |
| ------------------------ | -------------------------------------------------------- |
| trailing-whitespace      | Stray trailing spaces (markdown excluded)                |
| end-of-file-fixer        | Missing final newline                                    |
| check-yaml/json/toml     | Malformed config files                                   |
| check-added-large-files  | Files larger than 1 MB                                   |
| check-merge-conflict     | Leftover `<<<<<<<` conflict markers                      |
| check-case-conflict      | Names that collide on case-insensitive filesystems       |
| mixed-line-ending        | Normalizes line endings to LF                            |
| detect-secrets           | New secrets not in `.secrets.baseline`                   |
| ruff / ruff-format       | Python lint + formatting (`backend/`)                    |
| biome-check              | TS/JS/JSON lint + formatting (`frontend/`)               |

## Decisions Made

See ADR-025 (GitHub Actions), ADR-026 (pre-commit; includes the detect-secrets vs
gitleaks rationale), ADR-027 (path-based triggering), ADR-028 (skip integration
tests in CI for V1), ADR-029 (coverage as a metric, not a gate) in `decisions.md`.

## Assumptions

- The repo is hosted on GitHub (`github.com/thegeett/mortgageboss-ai`).
- The developer can install pre-commit (`pipx`/`pip`/`uv tool`).
- Standing up Postgres/Redis in CI is a Phase 7 concern.
- Branch-protection rules are configured separately in the GitHub UI.

## Deviations From the Spec

- **Secret detection uses detect-secrets, not gitleaks.** The gitleaks pre-commit
  hook builds via a Go toolchain that isn't installed; detect-secrets (the
  ticket's allowed alternative) is pure-Python and installs cleanly. A baseline
  file is included.
- **`ruff-pre-commit` pinned to `v0.15.16`** (not `v0.8.4`) to match the ruff
  version locked in `backend/uv.lock`, so the pre-commit formatter and CI's
  `ruff format --check` never disagree.
- **Frontend CI uses pnpm `version: 10`** (not `9`) to match the pnpm major
  version that generated `pnpm-lock.yaml`, so `--frozen-lockfile` validates.
- **biome-check hook gets `--config-path frontend`** so it uses the project's
  2-space `frontend/biome.json` instead of biome's tab default when invoked from
  the repo root.
- **Reformatted three LP-6 backend files** (`config.py`, `main.py`,
  `test_config.py`) that predated the `ruff format --check` gate.

## Verification Performed

- `pre-commit install` succeeded; `pre-commit run --all-files` passes all hooks.
- Backend checks mirrored locally with the same commands CI runs: `uv lock
  --check`, `ruff check .`, `ruff format --check .`, `mypy app/`, `pytest` — all
  pass (8 tests).
- Frontend checks mirrored locally: `pnpm lint`, `pnpm typecheck`, `pnpm build` —
  all pass.
- Deliberately broke a staged Python file and a staged TS file: `ruff-format` and
  `biome-check` both **failed** the commit and auto-fixed the files (re-stage
  required); `ruff` lint failed on an unused import. Temp files removed.
- Workflow YAML validated by parsing.
- GitHub-side run (criteria 17/20): triggers on push to `main` / PR to `main`.
  Pending the push/PR to `main`; all checks the workflows run are already green
  locally.

## Known Limitations

- CI doesn't run service-backed integration tests (no Postgres/Redis in CI).
- No deployment automation yet (no target).
- No coverage gating (intentional — ADR-029).
- Secret scanning is baseline detect-secrets only; deeper scanning is Phase 7.
- No PR-title linting.

## Future Improvements

- Phase 7: Postgres/Redis services in CI for full test runs.
- Phase 7: Docker image building.
- Phase 7: staging then production deployment automation.
- Optional: Codecov integration; Dependabot/Snyk security scanning.

## What's Next

LP-8 (initial documentation refinement), followed by Epic 2 starting with LP-9
(Alembic migrations).

## References

- GitHub Actions: https://docs.github.com/actions
- pre-commit: https://pre-commit.com
- astral-sh/setup-uv: https://github.com/astral-sh/setup-uv
- pnpm/action-setup: https://github.com/pnpm/action-setup
- detect-secrets: https://github.com/Yelp/detect-secrets
