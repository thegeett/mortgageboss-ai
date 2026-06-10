# LP-1 — Initialize V1 Monorepo Skeleton

- **Ticket:** LP-1 — Initialize V1 monorepo skeleton
- **Epic:** Epic 1 — Repo & Infrastructure Setup
- **Status:** Completed
- **Date:** 2026-06-09

## Summary

This ticket bootstrapped the MortgageBoss AI V1 repository as a monorepo. It
established the top-level directory structure for the backend, frontend, docs,
scripts, and CI workflows; added comprehensive repository hygiene files
(`.gitignore`, `.editorconfig`); seeded the project documentation (`README.md`,
`CLAUDE.md`, `decisions.md` with the first ADR); and created the initial commit
on the `main` branch. No application code, dependency manifests, or
infrastructure definitions were added — those are intentionally deferred to
later tickets (LP-2 through LP-5).

## Acceptance Criteria

1. ✅ New git repository initialized at the project directory.
2. ✅ All required top-level directories created.
3. ✅ Root `.gitignore` covers Python, Node, IntelliJ, VS Code, OS files, logs,
   storage, databases, and secrets.
4. ✅ Root `README.md` with project overview and quick-start placeholder.
5. ✅ `decisions.md` initialized with purpose header and the first entry
   (ADR-001).
6. ✅ `.editorconfig` present for consistent formatting across editors.
7. ✅ All empty directories preserved via `.gitkeep` files.
8. ✅ Initial commit made on `main` branch with message
   "LP-1: Initial repo skeleton".
9. ✅ Implementation documentation created at `docs/tickets/LP-1.md` (this file).

## What Was Built

### Directory structure

```
mortgageboss-ai/
├── .github/
│   └── workflows/        (.gitkeep)
├── backend/              (.gitkeep — filled in LP-3)
├── frontend/             (.gitkeep — filled in LP-5)
├── docs/
│   ├── tickets/          LP-1.md
│   └── architecture/     (.gitkeep)
├── scripts/              (.gitkeep)
├── .editorconfig
├── .gitignore
├── README.md
├── CLAUDE.md
└── decisions.md
```

### Files created

- **`.gitignore`** — ignore rules for Python (`__pycache__`, `*.pyc`, `.venv`,
  `venv`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, `*.egg-info`, `dist`,
  `build`, coverage), Node (`node_modules`, `.next`, `.turbo`, `*.tsbuildinfo`,
  `.pnpm-store`), environment files (`.env`, `.env.local`, `.env.*.local` while
  keeping `.env.example`), IntelliJ (`.idea/`, keeping `.idea/codeStyles/`),
  VS Code (`.vscode/`, keeping `settings.json`), OS junk (`.DS_Store`,
  `Thumbs.db`, `*.swp`), logs (`*.log`, `logs/`), local `storage/`, and
  databases (`*.db`, `*.sqlite`).
- **`.editorconfig`** — `root = true`, UTF-8, LF line endings, final newline,
  trim trailing whitespace; 4-space indent for Python, 2-space indent for
  TS/JS/JSON/YAML/Markdown/CSS/HTML, tabs for Makefiles.
- **`README.md`** — project title, status, architecture overview, tech stack,
  quick-start placeholder, repository structure table, and links to
  `docs/tickets/` and `decisions.md`.
- **`CLAUDE.md`** — project purpose, current phase, tech stack with versions,
  repository structure, coding conventions, decision-log pointer, and a note to
  document each ticket in `docs/tickets/LP-XXX.md`.
- **`decisions.md`** — ADR log header, format description, and ADR-001
  ("Use a monorepo for V1").
- **`docs/tickets/LP-1.md`** — this implementation document.
- **`.gitkeep`** files in `.github/workflows/`, `backend/`, `frontend/`,
  `docs/architecture/`, and `scripts/` to keep otherwise-empty directories
  tracked by git.

## Decisions Made

- **Monorepo over multi-repo.** A single repo keeps the backend and frontend in
  lockstep, simplifies cross-cutting changes and CI for a solo developer, and
  can still be split later if needed. Recorded as ADR-001 in `decisions.md`.
- **Include `.editorconfig`.** The repo mixes two ecosystems (Python and Node)
  with different indentation conventions. `.editorconfig` enforces consistent
  charset, line endings, and per-language indentation across any editor without
  relying on each developer's local settings.
- **LF line endings over CRLF.** The primary toolchains (Python, Node, Docker,
  shell scripts) and CI run on Unix-like systems. Standardizing on LF avoids
  noisy cross-platform diffs and `\r` issues in shell scripts and Docker builds.
- **`storage/` in `.gitignore`.** Locally uploaded loan documents will live in
  `storage/`. These are runtime artifacts and may contain sensitive borrower
  data, so they must never be committed.
- **`.gitkeep` to preserve empty directories.** Git does not track empty
  directories. `.gitkeep` placeholder files ensure the intended structure (e.g.,
  `backend/`, `frontend/`) is present from the first commit before later tickets
  fill them in.
- **Default branch `main`.** Initialized the repository directly on `main` to
  match the convention referenced throughout the build plan.
- **Whitelist-style ignore exceptions.** Rather than ignoring everything under
  `.idea/` and `.vscode/`, the `.gitignore` keeps `.idea/codeStyles/` and
  `.vscode/settings.json` so shared formatting/editor settings can be committed
  if desired.

## Assumptions

- The repository lives at
  `/Users/geetthaker/Geet/project/loan-processing/mortgageboss-ai` and was
  previously empty apart from a local `.idea/` directory (now ignored).
- Python 3.12, Node/Next.js 15, uv, and pnpm will be introduced by later tickets;
  no dependency manifests are expected in this commit.
- LP-2 will add `docker-compose.yml`, LP-3 will add `backend/pyproject.toml`, and
  LP-5 will add `frontend/package.json`; their target directories are stubbed
  with `.gitkeep` for now.
- A remote (e.g., GitHub) will be configured in a later step; this ticket only
  establishes the local repository.

## What's Next

**LP-2 — Local infrastructure via Docker Compose.** Define `docker-compose.yml`
with Postgres 16, Redis, and MailHog for local development.

## References

- V1 Build Plan — Phase 1 (Foundation), Epic 1 (Repo & Infrastructure Setup).
- [EditorConfig](https://editorconfig.org/)
- [Architecture Decision Records](https://adr.github.io/)
