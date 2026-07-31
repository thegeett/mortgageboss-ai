# Running a second worktree alongside the main stack

Two checkouts of this repo run on one machine: the **main worktree**
(`../mortgageboss-ai`, the rule-engine branch) and the **Bedrock worktree**
(`../mbai-bedrock`, branch `bedrock_integration`).

`git worktree` isolates **files only**. Docker containers, Postgres, Redis, and host
ports are *runtime* — they collide unless separated explicitly. This document is how
they are separated, and how to drive both stacks without disturbing either.

> **`git worktree` does not copy gitignored files.** A new worktree has no `.env`,
> no `backend/.env`, no `frontend/.env.local`, no `.venv`, no `node_modules`, and no
> `backend/storage`. Create `backend/storage` **before** `docker compose up`, or Docker
> creates the mount target root-owned.

---

## How the isolation works

`docker-compose.yml` is parameterized with shell-variable defaults:

```yaml
container_name: ${STACK:-mortgageboss}-postgres
ports: ["${PG_PORT:-5432}:5432"]
```

`container_name` **overrides** Compose's project-name prefixing, so `-p` alone cannot
separate two stacks while those names are hardcoded — parameterizing them is what makes
a second stack possible at all. Volumes and the network carry no explicit `name:`, so
Compose already prefixes them per project; they needed no change.

**With no root `.env`, every default resolves to exactly the original value** —
`mortgageboss-postgres` / `-redis` / `-mailhog` / `-worker` on 5432 / 6379 / 1025 / 8025.
The main worktree is unaffected by this change and must be left with no root `.env`.

## The three `.env` files

Do not confuse these. They are read by three different programs.

| File | Read by | Purpose |
|---|---|---|
| `.env` (repo root) | Docker Compose interpolation | `STACK`, host ports, `COMPOSE_PROJECT_NAME` |
| `backend/.env` | FastAPI settings + worker `env_file` | `DATABASE_URL`, `REDIS_URL`, CORS, keys |
| `frontend/.env.local` | Next.js | `NEXT_PUBLIC_API_URL` |

All three are gitignored. `.env.stack.example` at the repo root is the tracked template
for the first one.

---

## Setup

```bash
# 1. Create the worktree (from the main worktree)
git worktree add ../mbai-bedrock -b bedrock_integration

cd ../mbai-bedrock

# 2. Root .env — Compose interpolation
cp .env.stack.example .env          # COMPOSE_PROJECT_NAME/STACK=mbai-bedrock, 5433, 6380

# 3. backend/.env — copy from the main worktree, then REPOINT the ports
cp ../mortgageboss-ai/backend/.env backend/.env
#    DATABASE_URL   -> ...@localhost:5433/mortgageboss_dev
#    REDIS_URL      -> redis://localhost:6380/0
#    CORS_ALLOWED_ORIGINS -> ["http://localhost:3100"]

# 4. frontend/.env.local — must exist, see "Cross-talk" below
echo 'NEXT_PUBLIC_API_URL=http://localhost:8100' > frontend/.env.local

# 5. Storage mount target — BEFORE docker compose up, or Docker creates it root-owned
mkdir -p backend/storage

# 6. Dependencies (not copied by git worktree)
cd backend && uv sync && cd ..
cd frontend && pnpm install && cd ..
```

`COMPOSE_PROJECT_NAME` in the root `.env` means a plain `docker compose up -d` selects
the right project — there is no `-p` flag to remember.

Node is not pinned in the repo; CI uses 20 (`.github/workflows/frontend-ci.yml:38`).

### Cross-talk — the two defaults that will silently wire you to the other worktree

Both are fixed by env files, **not** by code. Do not change the defaults; the main
worktree depends on them.

- `frontend/lib/config.ts:2` and `frontend/lib/api/client.ts:5` both fall back to
  `http://localhost:8000` when `NEXT_PUBLIC_API_URL` is unset. Without
  `frontend/.env.local`, the Bedrock frontend on 3100 talks to the **rule-engine backend
  on 8000** and shows the wrong data. This failure is **silent**.
- `backend/app/core/config.py:110` defaults `cors_allowed_origins` to
  `["http://localhost:3000"]`. Without the override, the Bedrock API on 8100 **rejects**
  the Bedrock frontend on 3100. This failure is loud.

---

## Port map

| | Main worktree | Bedrock worktree |
|---|---|---|
| Postgres | 5432 | 5433 |
| Redis | 6379 | 6380 |
| FastAPI (host) | 8000 | 8100 |
| Next.js (host) | 3000 | 3100 |
| Mailhog | 1025 / 8025 | not run |

Mailhog is **not started** on this branch. Its compose entry still resolves to 1025/8025
(the ports are parameterizable via `SMTP_PORT` / `MAILHOG_UI_PORT` but are not set in
`.env.stack.example`), so starting it here would collide with the main worktree's
Mailhog. Start only `postgres redis worker`.

Because Mailhog is not run here, `SMTP_HOST=localhost` / `SMTP_PORT=1025` in this
worktree's `backend/.env` reaches the **main worktree's** Mailhog. Harmless for a dev
mail catcher, but it is genuine cross-talk — expect Bedrock dev mail to land in the
main worktree's inbox at <http://localhost:8025>.

---

## Docker commands

Run these from `../mbai-bedrock`.

```bash
docker compose up -d --build postgres redis worker   # start (no mailhog on this branch)
docker compose ps                                    # health
docker compose logs -f worker                        # follow worker
docker compose up -d --build worker                  # rebuild worker after a code change
docker compose stop                                  # free memory, keep volumes
docker compose start                                 # resume
docker ps --format '{{.Names}}\t{{.Ports}}' | sort    # confirm both stacks
docker volume ls | grep postgres-data                # confirm separate volumes
```

> ⚠️ **`docker compose down -v` DESTROYS the volume and every row in it.**
>
> ⚠️ **Never run `docker compose down` or `down -v` in the main worktree.** That stack has
> been up for weeks with live dev data. Use `stop` / `start` if you need to free memory —
> `down` removes containers, and `down -v` removes the data.

---

## Backend and frontend

Both run on the **host**, not in Docker. You start them manually.

```bash
# Backend — FastAPI (app.main:app is defined at backend/app/main.py:94)
cd backend && uv run uvicorn app.main:app --reload --port 8100

# Frontend — Next.js, pnpm (frontend/pnpm-lock.yaml)
cd frontend && pnpm dev --port 3100
```

**No `--` separator.** pnpm 10 (10.33.0 here) passes `--` through to the script
literally rather than stripping it, so `pnpm dev -- --port 3100` runs
`next dev -- --port 3100`. Verified against this repo with
`pnpm typecheck -- --version` → `tsc --noEmit -- --version` →
`error TS5023: Unknown compiler option '--'`.

The API runs on the host and writes uploads to `backend/storage`
(`STORAGE_LOCAL_PATH=./storage`). The containerised worker reads them through the
compose mount `./backend/storage:/app/storage`, so both share one storage root. If that
mount is missing or empty, every document fails to process with a `StorageError` at read
time.

---

## Database commands

`DATABASE_URL` is **asyncpg-only** (`backend/app/core/config.py:31` types it as a
`PostgresDsn` with the asyncpg driver). There is no sync `postgresql://` variant anywhere
in the repo, and Alembic reuses the asyncpg URL (`backend/alembic/env.py:25`). All psql
access therefore goes through `docker exec` — there is no host `psql` in the loop.

```bash
# psql shell
docker exec -it mbai-bedrock-postgres psql -U mortgageboss -d mortgageboss_dev

# list tables
docker exec mbai-bedrock-postgres psql -U mortgageboss -d mortgageboss_dev -c '\dt'

# current migration revision
docker exec mbai-bedrock-postgres psql -U mortgageboss -d mortgageboss_dev \
  -tAc 'select version_num from alembic_version;'
```

### Seeding from the main database

```bash
./scripts/seed-from-main.sh
```

Copies schema **and** data from the main worktree's database into this one, plus the
storage files those rows reference. It is **read-only on the source** — `pg_dump` only,
nothing writes to `mortgageboss-postgres`. `pg_dump` and `pg_restore` both run inside
their containers (both `postgres:16-alpine`) so client and server versions match.

Re-runnable: `--clean --if-exists --no-owner` drops and recreates rather than duplicating.

It refuses to run if `STACK` is unset, if `STACK=mortgageboss`, if either container is
not running, or if the port guard below fails.

Database rows reference files on disk, so the database and `backend/storage` must be
copied **together** — the script does both. A database-only copy leaves extraction rows
pointing at files that do not exist.

### The Alembic guard

```bash
./scripts/check-stack.sh && uv run alembic upgrade head
```

`check-stack.sh` fails non-zero unless the reached database is published on the port this
worktree expects (`EXPECTED_PG_PORT`, default 5433). **Run it in front of every Alembic
command.** Both worktrees run Alembic against the same schema; a migration accidentally
aimed at 5432 corrupts the main worktree's live database. That is the one failure here
that destroys real work.

The guard reads the server port with `current_setting('port')`, not `inet_server_port()`
— `docker exec` connects over the container's Unix domain socket, and `inet_server_port()`
is NULL for any non-TCP connection.

---

## Troubleshooting

**Container name conflict** — `Conflict. The container name "/mortgageboss-postgres" is
already in use`. The root `.env` is missing or `STACK` is unset, so `container_name`
resolved to the default. Check `cp .env.stack.example .env`, then
`docker compose config | grep container_name`.

**Port already in use** — `bind: address already in use` on 5433/6380 means a stale
container from this project. `docker compose ps -a`. On **5432/6379** it means you are
about to collide with the main stack: your `PG_PORT` / `REDIS_PORT` did not take effect.

**Worker restart-loops** — almost always a missing `backend/.env`. The worker loads it via
`env_file` and the app refuses to start without required settings (e.g.
`ANTHROPIC_API_KEY`). `docker compose logs worker` shows the failing setting.
A `env file ... not found` error from Compose itself means the file is absent entirely.

**`backend/storage` is root-owned** — Docker created the bind-mount target because the
directory did not exist at `up` time. Fix with
`sudo chown -R "$(id -u):$(id -g)" backend/storage`, and `mkdir -p backend/storage` before
`up` next time.

**Frontend shows the wrong data** — the single most likely cause is
`frontend/.env.local` missing or not picked up, so `NEXT_PUBLIC_API_URL` is unset and
both `lib/config.ts` and `lib/api/client.ts` fall back to `http://localhost:8000` — the
**other worktree's** backend. Nothing errors; the data is simply from the wrong branch.
Confirm with `grep NEXT_PUBLIC_API_URL frontend/.env.local` (must be `:8100`) and restart
`pnpm dev` — `NEXT_PUBLIC_*` values are inlined at build time, so an already-running dev
server will not pick up a new value.

**Frontend gets CORS errors** — `CORS_ALLOWED_ORIGINS` in `backend/.env` does not include
`http://localhost:3100`. Restart uvicorn after changing it.

**Which stack am I talking to?**

```bash
docker ps --format '{{.Names}}\t{{.Ports}}' | sort
grep -E '^(DATABASE_URL|REDIS_URL)' backend/.env    # must be :5433 and :6380
grep NEXT_PUBLIC_API_URL frontend/.env.local        # must be :8100
```
