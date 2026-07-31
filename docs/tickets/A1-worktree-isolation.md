# A1 — Worktree isolation for the Bedrock branch

**Branch:** `bedrock_integration`
**Worktree:** `../mbai-bedrock`
**Depends on:** nothing
**Blocks:** every subsequent Bedrock ticket

---

## Context

A second worktree runs the Bedrock integration branch alongside the existing rule-engine
branch on the same machine. `git worktree` isolates **files only** — Docker containers,
Postgres, Redis, and host ports are runtime and will collide unless separated explicitly.

The existing stack has been up for weeks with live dev data in Docker volumes. **Nothing in
this ticket may disturb it.** Every change is backward-compatible via shell-variable defaults:
with no root `.env` present, the existing stack resolves to exactly its current names and ports.

### Hazard 1 — container names override project prefixing

`container_name` **overrides** Compose's project-name prefixing. The current file hardcodes
`mortgageboss-postgres`, `mortgageboss-redis`, `mortgageboss-mailhog`, `mortgageboss-worker`.
A second project fails on duplicate container names — `-p` cannot help while those are hardcoded.

Volumes and the network are already safe (no explicit `name:`, so Compose prefixes them per
project). The worker's `DATABASE_URL` is also already safe — it targets the service name
`postgres:5432` on the project-internal network. Only **container names** and **host ports**
need parameterizing.

### Hazard 2 — Alembic against the wrong database

Both worktrees run Alembic. If this worktree ever points at port 5432, a migration corrupts the
live rule-engine schema. That is the one failure here that destroys real work.

### Hazard 3 — database rows reference files on disk

Extraction rows reference uploaded files under `backend/storage`. Copying the database without
copying that directory produces rows pointing at files that do not exist. Both must be copied.

---

## Tasks

### 1. Parameterize `docker-compose.yml`

Edit in place. **Preserve all comments** — the worker's storage-mount comment documents a real
footgun and must survive.

Container names — defaults must reproduce current behavior exactly:

```yaml
postgres:  container_name: ${STACK:-mortgageboss}-postgres
redis:     container_name: ${STACK:-mortgageboss}-redis
mailhog:   container_name: ${STACK:-mortgageboss}-mailhog
worker:    container_name: ${STACK:-mortgageboss}-worker
```

Host ports — container-side ports stay fixed:

```yaml
postgres:  - "${PG_PORT:-5432}:5432"
redis:     - "${REDIS_PORT:-6379}:6379"
mailhog:   - "${SMTP_PORT:-1025}:1025"
           - "${MAILHOG_UI_PORT:-8025}:8025"
```

Change nothing else. Do not touch volumes, networks, healthchecks, `depends_on`, the worker
`environment` block, or the storage mount.

### 2. Add `.env.stack.example` at the repo root

Compose's **variable interpolation** reads `.env` next to `docker-compose.yml`. This is a
**different file** from `backend/.env`, which the worker loads via `env_file`. Both exist and
do different jobs — document that in the example file.

```
# Root .env — consumed by Docker Compose variable interpolation ONLY.
# Distinct from backend/.env, which the worker loads via env_file.
# Leave absent in the main worktree to keep current names and ports.

COMPOSE_PROJECT_NAME=mbai-bedrock
STACK=mbai-bedrock
PG_PORT=5433
REDIS_PORT=6380
```

`COMPOSE_PROJECT_NAME` here means plain `docker compose up -d` selects the right project with
no `-p` flag to remember.

### 3. Prevent cross-worktree cross-talk (CRITICAL — recon finding)

Two hardcoded defaults will silently wire this worktree to the **other** worktree's stack:

- `frontend/lib/config.ts:2` and `frontend/lib/api/client.ts:5` both fall back to
  `http://localhost:8000` when `NEXT_PUBLIC_API_URL` is unset. Without an override, the
  Bedrock frontend on 3100 talks to the **rule-engine backend on 8000**.
- `backend/app/core/config.py:110` defaults `cors_allowed_origins` to
  `["http://localhost:3000"]`. Without an override, the Bedrock API on 8100 **rejects** the
  Bedrock frontend on 3100.

The first is silent and dangerous; the second is loud and blocking. Both are fixed by env
files, not code — do not change the defaults, other worktrees depend on them.

There are **three** `.env` files in play. Document this distinction clearly:

| File | Read by | Purpose |
|---|---|---|
| `.env` (repo root) | Docker Compose interpolation | `STACK`, ports, project name |
| `backend/.env` | FastAPI settings + worker `env_file` | DB, Redis, CORS, keys |
| `frontend/.env.local` | Next.js | `NEXT_PUBLIC_API_URL` |

Verify `.gitignore` already covers the root `.env` — recon confirms `.gitignore:28` does, with
`!.env.example` at `:31-32`. This is a check, not an edit. Confirm `frontend/.env.local` is
also ignored; add it if not.

Create `frontend/.env.local` in this worktree:

```
NEXT_PUBLIC_API_URL=http://localhost:8100
```

And confirm `backend/.env` in this worktree contains:

```
CORS_ALLOWED_ORIGINS=["http://localhost:3100"]
```

Also check `.claude/settings.local.json:46-61` — it allowlists curl/lsof strings for ports
8000/3000. Add 8100/6380/5433/3100 equivalents if the existing entries would block tool use in
this worktree. Report what you changed.

### 4. Add `scripts/check-stack.sh`

Guard run before any Alembic command in this worktree. Must exit non-zero on mismatch.

```bash
#!/usr/bin/env bash
# Fails unless the DB reached is on the port this worktree expects.
# Prevents running a migration against the other worktree's live database.
set -euo pipefail

EXPECTED_PORT="${EXPECTED_PG_PORT:-5433}"
ACTUAL_PORT=$(docker exec "${STACK:-mbai-bedrock}-postgres" \
  psql -U mortgageboss -d mortgageboss_dev -tAc 'select inet_server_port();' | tr -d '[:space:]')

if [ "$ACTUAL_PORT" != "5432" ]; then
  echo "REFUSING: unexpected in-container port $ACTUAL_PORT." >&2
  exit 1
fi

HOST_PORT=$(docker port "${STACK:-mbai-bedrock}-postgres" 5432 | head -1 | sed 's/.*://')
if [ "$HOST_PORT" != "$EXPECTED_PORT" ]; then
  echo "REFUSING: container publishes $HOST_PORT, expected $EXPECTED_PORT." >&2
  echo "You are probably pointed at the other worktree's database. Check .env." >&2
  exit 1
fi
echo "OK: ${STACK:-mbai-bedrock}-postgres published on $HOST_PORT."
```

`chmod +x`. Using `docker exec` avoids depending on a host `psql` and guarantees a version
match with the server.

### 5. Add `scripts/seed-from-main.sh`

Copies schema **and** data from the main worktree's database into this one, plus the storage
files those rows reference.

Requirements:

- **Read-only on the source.** `pg_dump` only. Never write to `mortgageboss-postgres`.
- Run `pg_dump` and `pg_restore` **inside the containers** (`docker exec`) so client and server
  versions match — both are `postgres:16-alpine`.
- Refuse to run if the target container is not `${STACK}-postgres`, or if `STACK` is unset or
  equals `mortgageboss`.
- Use `--clean --if-exists --no-owner` on restore so it is re-runnable.
- Copy `../mortgageboss-ai/backend/storage/` into `backend/storage/` after the restore.
- Print a row count for the loan-file table and the `alembic_version` revision when done.

Shape:

```bash
docker exec mortgageboss-postgres pg_dump -U mortgageboss -d mortgageboss_dev -Fc \
  > /tmp/main_dev.dump

docker exec -i "${STACK}-postgres" pg_restore -U mortgageboss -d mortgageboss_dev \
  --clean --if-exists --no-owner < /tmp/main_dev.dump

cp -R ../mortgageboss-ai/backend/storage/. backend/storage/
```

Read the repo to determine the correct loan-file table name for the row-count check. Do not
guess it.

### 6. Write `docs/worktree-setup.md`

Recon has confirmed the commands below. Use them; verify each against the repo before writing.

**Backend** — `app.main:app` at `backend/app/main.py:94`, Python 3.12, uv with `uv.lock`:

```bash
cd backend && uv run uvicorn app.main:app --reload --port 8100
```

**Frontend** — `frontend/`, manager is **pnpm** (`frontend/pnpm-lock.yaml`), dev script is
`next dev`:

```bash
cd frontend && pnpm dev -- --port 3100
```

Node is not pinned in the repo; CI uses 20 (`.github/workflows/frontend-ci.yml:38`).

Sections required:

**Setup** — worktree creation, all three `.env` files, `mkdir -p backend/storage`,
`uv sync` and `pnpm install`.

**Port map**

| | Main worktree | Bedrock worktree |
|---|---|---|
| Postgres | 5432 | 5433 |
| Redis | 6379 | 6380 |
| FastAPI (host) | 8000 | 8100 |
| Next.js (host) | 3000 | 3100 |
| Mailhog | 1025 / 8025 | not run |

**Docker commands** — at minimum:

```bash
docker compose up -d --build postgres redis worker   # start (no mailhog on this branch)
docker compose ps                                    # health
docker compose logs -f worker                        # follow worker
docker compose up -d --build worker                  # rebuild worker after code change
docker compose stop                                  # free memory, keep volumes
docker compose start                                 # resume
docker ps --format '{{.Names}}\t{{.Ports}}' | sort    # confirm both stacks
docker volume ls | grep postgres-data                # confirm separate volumes
```

Bold warning that `docker compose down -v` destroys the volume, and that neither `down` nor
`down -v` may be run in the main worktree.

**Backend and frontend start commands** — the user runs these manually. Note the API runs on
the **host**, not in Docker, and shares `backend/storage` with the containerised worker via the
compose mount.

**Database commands** — psql shell via `docker exec`, table list, seed-from-main, guard script,
and the Alembic sequence with the guard in front:

```bash
./scripts/check-stack.sh && uv run alembic upgrade head
```

Note that `DATABASE_URL` is **asyncpg-only** (`backend/app/core/config.py:31`); there is no
sync `postgresql://` variant anywhere in the repo, and Alembic reuses the asyncpg URL
(`backend/alembic/env.py:25`). All psql access therefore goes through `docker exec`.

**Troubleshooting** — container name conflict, port in use, worker restart-looping on missing
`backend/.env`, `backend/storage` created root-owned, and **frontend showing the wrong data
because `NEXT_PUBLIC_API_URL` is unset and defaulting to 8000**.

Include this warning prominently:

> `git worktree` does not copy gitignored files. The new worktree has no `.env`,
> no `backend/.env`, no `frontend/.env.local`, no `.venv`, no `node_modules`, and no
> `backend/storage`. Create `backend/storage` **before** `docker compose up`, or Docker
> creates the mount target root-owned.

### 7. Write `docs/tickets/A1-worktree-isolation-result.md`

Completion record. Must contain:

- Files created and modified, one line each
- Every verify step with its actual observed output — not "passed"
- Row counts and `alembic_version` revision on both databases, side by side
- Anything encountered that the ticket did not anticipate
- Anything deliberately not done, with the reason
- Exact commands the user must run manually (backend, frontend)

### 8. Update `decisions.md` if any decision was made

Only if a real choice was made that a future reader would otherwise have to reverse-engineer.
Append a new ADR using the **next number in sequence** — read the file to find the current
maximum, do not assume. Match the existing ADR format exactly.

Likely candidates from this ticket: parameterizing rather than removing `container_name`;
seeding from the main database rather than migrating from empty; excluding mailhog from this
branch's stack. If nothing genuinely qualifies, do not pad the file — say so in the result doc.

---

## Verify

Run in order. Every step must pass. Steps C and D run **before** seeding.

**A. Existing stack is untouched.** From the **main** worktree, with no root `.env`:

```bash
docker compose config | grep -E 'container_name|published'
```

Must resolve to `mortgageboss-*` and ports 5432 / 6379 / 1025 / 8025 — identical to today.
This proves the defaults are backward-compatible. **Do not run `up` or `down` in the main
worktree.** The running stack stays up throughout.

**B. Bedrock stack resolves separately.** From `../mbai-bedrock` with the root `.env` present:

```bash
docker compose config | grep -E 'container_name|published'
```

Must show `mbai-bedrock-*` and ports 5433 / 6380.

**C. Both stacks run concurrently:**

```bash
docker compose up -d --build postgres redis      # worker starts after the seed
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}' | sort
```

Both sets must appear. The four `mortgageboss-*` containers must still show their **original
uptime** — a reset means something was disturbed.

**D. Target database is empty before seeding:**

```bash
docker exec mbai-bedrock-postgres psql -U mortgageboss -d mortgageboss_dev \
  -c "select count(*) from information_schema.tables where table_schema='public';"
```

Must return `0`. **Any non-zero value means you reached the wrong database — stop and report.**

**E. Seed, then confirm parity:**

```bash
./scripts/seed-from-main.sh
```

Then compare both databases side by side — table count, `alembic_version` revision, and the
loan-file row count. Revisions must be **identical**. Record actual numbers in the result doc.

**F. Storage files copied:**

```bash
diff -rq ../mortgageboss-ai/backend/storage backend/storage | head
```

Empty output, or explain any difference.

**G. Volumes are distinct:**

```bash
docker volume ls | grep postgres-data
```

Two volumes, different project prefixes.

**H. Worker starts clean against the seeded database:**

```bash
docker compose up -d --build worker
docker compose logs --tail=50 worker
```

Must reach ready state with no connection or migration errors.

**I. Guard script works both ways:**

```bash
./scripts/check-stack.sh                          # expect OK on 5433
EXPECTED_PG_PORT=9999 ./scripts/check-stack.sh    # expect non-zero exit
```

**J. No cross-talk to the other worktree:**

```bash
grep -r "localhost:8000\|localhost:3000" frontend/.env.local backend/.env 2>/dev/null
```

Must return nothing. Then confirm the resolved values:

```bash
grep NEXT_PUBLIC_API_URL frontend/.env.local      # must be :8100
grep CORS_ALLOWED_ORIGINS backend/.env            # must include :3100
grep -E '^(DATABASE_URL|REDIS_URL)' backend/.env  # must be :5433 and :6380
```

---

## Stop and report — do not work around

- Any container name collision after the edits.
- Verify D returning a non-zero table count.
- Any need to stop, restart, or recreate a `mortgageboss-*` container.
- Any existing root `.env` in the main worktree that the defaults would override.
- `pg_restore` errors beyond benign "does not exist, skipping" from `--if-exists`.
- Backend or frontend start command that cannot be determined from the repo — report rather
  than guessing.

---

## Do not

- `git push` — commit locally only.
- Run any Alembic command. Schema arrives via the seed, carrying its own `alembic_version`.
- Run `docker compose down` or `down -v` in **either** worktree.
- Write to the main worktree's database. `pg_dump` reads; nothing writes.
- Modify `backend/.env` in the main worktree.
- Change the worker's `environment` block — those service-name URLs are already correct.
- Start the backend or frontend dev servers. The user runs those; the ticket documents them.
