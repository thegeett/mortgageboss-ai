# C1 — Dockerfiles for API and frontend — result

**Branch:** `bedrock_integration` · **Date:** 2026-08-03

All seven tasks done. All three images build and run together against this worktree's
Postgres and Redis. **No Stop-and-report condition fired.** Both existing stacks kept
their uptime throughout.

One deviation from the Verify block, for safety: the images stack must be run with
`-p mbai-images`. Reason and evidence in "Deviation" below.

---

## Files created and modified

| File | Change |
|---|---|
| `backend/Dockerfile` | **Modified** — added a Celery `HEALTHCHECK` (+ comments). Nothing else touched. |
| `backend/.dockerignore` | **Modified** — added `tests/` and `.env.*`; annotated why `storage/` matters |
| `frontend/Dockerfile` | **Created** — 3-stage, Node 20, pnpm via corepack, non-root |
| `frontend/.dockerignore` | **Created** |
| `frontend/next.config.ts` | **Modified** — added `output: "standalone"` |
| `docker-compose.images.yml` | **Created** — the local Fargate rehearsal |
| `decisions.md` | **Modified** — appended ADR-344 and ADR-345 (max was ADR-343) |
| `docs/tickets/C1-dockerfiles-result.md` | **Created** — this file |

`docker-compose.yml` was **not** modified. No Alembic migration. `STORAGE_BACKEND` still
`local`. No images pushed.

---

## Task 1 — Backend Dockerfile audit

Audited as-is, before any change:

| Question | Finding |
|---|---|
| Base image / Python | `python:3.12-slim` (`backend/Dockerfile:5`) — satisfies `requires-python = ">=3.12"` |
| `uv sync --frozen`? | **Yes**, twice: `--frozen --no-dev --no-install-project` (`:14`) then `--frozen --no-dev` (`:18`). So `uv.lock` governs and C0's `aioboto3` is picked up — confirmed in C0 by `aioboto3 15.5.0` inside the rebuilt worker. |
| Non-root user? | **No — runs as root.** No `USER` directive. Celery says so on every boot: `You're running the worker with superuser privileges … uid=0 euid=0`. |
| Multi-stage? | **No** — single stage. |
| Final image size | **605 MB** (`mbai-bedrock-worker:latest`), **589 MB** after this ticket's `.dockerignore` change |
| `CMD`/`ENTRYPOINT` overridable? | **Yes** — `CMD` (not `ENTRYPOINT`) at `:21`, exec form. Compose overrides it today, and task 2 overrode it to run uvicorn. |

**I did not change the base image, add a build stage, or add a non-root user.** The ticket
says to change it only if something below requires it, and nothing did. Recording the two
gaps for a later decision rather than acting on them:

- **Running as root** is a real hardening gap for Fargate. Adding a `USER` is not a one-line
  change here: `/app/.venv` is created by root during build, and the worker writes to
  `/app/storage` via the compose mount. Worth its own ticket, with the S3 backend (C0) in
  place so the storage-ownership half disappears.
- **Single-stage** keeps `uv` and build artifacts in the final image. The win is smaller than
  it looks (the venv dominates), so it is not obviously worth the churn.

## Task 2 — The same image serves the API

**It works with no Dockerfile change.** Run verbatim from the existing image:

```bash
docker run -d --rm --name c1-api-test --env-file backend/.env \
  --network mbai-bedrock_mortgageboss-network \
  -e DATABASE_URL='postgresql+asyncpg://…@postgres:5432/mortgageboss_dev' \
  -e REDIS_URL='redis://redis:6379/0' \
  -p 8101:8000 mbai-bedrock-worker \
  uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Ready in ~1 s:

```
[info] starting_application  app=mortgageboss-ai environment=development version=0.1.0
[info] database_connected
[info] redis_connected
[info] application_ready
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### The health endpoint path — `/health/live`

There are **three**, all on the app root (not under `/api/v1`), found by reading
`backend/app/main.py`:

| Path | Line | Behaviour | Observed |
|---|---|---|---|
| `/health` | `main.py:156` | Checks Postgres + Redis; **503** if either fails | `{"status":"healthy",…,"checks":{"database":"ok","redis":"ok"}}` → 200 |
| `/health/live` | `main.py:178` | Liveness. No dependency checks. | `{"status":"alive"}` → 200 |
| `/health/ready` | `main.py:189` | Readiness. Checks Postgres + Redis; **503** if either fails | `{"ready":true,…}` → 200 |

**C3 should point the ALB target group at `/health/live`.** `/health` and `/health/ready`
return 503 when a dependency is down, so an ALB wired to either would deregister *every* API
task on a database blip — turning a recoverable wobble into a total outage, with replacement
tasks failing their checks too. `/health/live` answers the question an ALB actually asks
("should this task be replaced?"). Keep `/health/ready` for deployment gating, where refusing
traffic until dependencies are up is the point.

`--host 0.0.0.0` is required; the default `127.0.0.1` binds inside the container only and the
ALB check fails with nothing useful in the application log.

## Task 3 — Worker healthcheck

Added to `backend/Dockerfile`, app path verified against
`backend/app/tasks/celery_app.py:32` and the compose `command` (`docker-compose.yml:81`) —
both `app.tasks.celery_app`:

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD uv run celery -A app.tasks.celery_app inspect ping -d celery@$HOSTNAME || exit 1
```

Shell form deliberately, so `$HOSTNAME` expands at runtime. Confirmed Docker sets it to the
container id and Celery names its node to match:

```
$ docker exec mbai-bedrock-worker sh -c 'echo $HOSTNAME'      → 71b3a0069116
$ docker exec … 'uv run celery … inspect ping -d celery@$HOSTNAME'
->  celery@71b3a0069116: OK
        pong
1 node online.                                                EXIT=0
```

`-d celery@$HOSTNAME` pins the probe to this container's own node, so a second healthy worker
on the same broker cannot mask this one being dead — which matters, because the rehearsal
stack does exactly that (two nodes, one broker).

### Both directions verified

```
baseline                                    mbai-images-worker=healthy
$ docker stop mbai-bedrock-redis
t+5s … t+95s: healthy
t+100s:       unhealthy          ← 30s interval × 3 retries, as configured
$ docker start mbai-bedrock-redis
t+5s … t+20s: unhealthy
t+25s:        healthy
```

I stopped **`mbai-bedrock-redis`** (this worktree's), never the main worktree's, and restarted
it immediately. After restart: `mbai-bedrock-worker` reconnected on its own
(`Connected to redis://redis:6379/0`), both stacks healthy, API and frontend still serving 200.

**Note:** `mbai-bedrock-worker` itself has **no** healthcheck — its image predates this change
(built during C0). `docker inspect` reports `<none>`. It picks one up on the next
`docker compose up -d --build worker`.

## Task 4 — Frontend Dockerfile

Three stages: `deps` (pnpm install) → `builder` (pnpm build) → `runner` (standalone output +
`public/` + `.next/static/`). Node 20 (matching `.github/workflows/frontend-ci.yml:38`, the only
pin in the repo), pnpm 10.33.0 via `corepack`, `--frozen-lockfile`, non-root, `EXPOSE 3000`,
`CMD ["node", "server.js"]`, `HOSTNAME=0.0.0.0`.

**`output: 'standalone'` was NOT already set** — `frontend/next.config.ts` was an empty config
object (`/* config options here */`). I added it. The build succeeded and no route broke, so
that Stop-and-report condition did not fire.

Two details that are easy to get wrong and are commented in the Dockerfile: `public/` and
`.next/static/` are **not** part of the standalone output and must be copied alongside it
(omit them and the server boots fine while serving no CSS, images, or client chunks); and the
entrypoint is plain `node server.js`, because the bundle ships no Next CLI and no pnpm.

Non-root confirmed: `docker run --rm --entrypoint sh mbai-frontend:test -c id` →
`uid=1000(node) gid=1000(node)`.

---

## ⚠️ The build-time API URL — the most likely deployment mistake in the C series

**`NEXT_PUBLIC_*` variables are inlined into the JavaScript at build time. They are not read at
runtime.** Setting `NEXT_PUBLIC_API_URL` in an ECS task definition does **nothing** — the value
is already compiled into the shipped bundle.

`frontend/lib/config.ts:2` and `frontend/lib/api/client.ts:5` both fall back to
`http://localhost:8000` when it is unset. An image built without the build arg therefore ships
a frontend that asks **the user's own machine** for the API. It fails only in the browser, with
no server-side error and a green ECS health check.

**The staging image must be built with:**

```bash
docker build -t mbai-frontend:staging \
  --build-arg NEXT_PUBLIC_API_URL=https://staging.mortgageboss.ai ./frontend
```

**Changing the API URL requires a rebuild and redeploy — not a task-definition edit.**

Verified that the arg is genuinely baked, not merely accepted:

```
$ docker exec mbai-images-frontend grep -rl 'localhost:8102' .next/static
.next/static/chunks/551-8d46163e3f42a05b.js
.next/static/chunks/323-bb221f6e0c112e87.js
.next/static/chunks/app/layout-e01089a8f84da9a9.js

$ docker exec mbai-images-frontend grep -rl 'localhost:8000' .next/static
(no output — the fallback did not ship)
```

**Only `NEXT_PUBLIC_*` values may be build args** — a build arg is visible in `docker history`,
so a secret there is a leak, not a shortcut. Audited before writing the Dockerfile:
`NEXT_PUBLIC_API_URL` is the **only** non-`NODE_ENV` environment variable the frontend reads
(the other `process.env` hits are `NODE_ENV` in `providers.tsx`, `document-drawer.tsx`,
`client.ts`, `error-boundary.tsx`). Nothing secret is needed at build time, so that
Stop-and-report condition did not fire.

---

## Task 5 — `.dockerignore` and build-context size

**`backend/.dockerignore` already existed** and already excluded `storage/`, `.venv/`, `.env`,
and the caches. It was missing **`tests/`** from the ticket's minimum list; I added that plus
`.env.*` (so `.env.local` / `.env.production` variants cannot be baked either).

**Build context, measured** (this Docker uses the legacy builder, which prints
`Sending build context to Docker daemon`; BuildKit produced no output here):

| | Context |
|---|---|
| Before (existing `.dockerignore`) | **18.07 MB** |
| After (added `tests/`) | **6.547 MB** |

A **64% reduction**, and the image dropped 605 MB → **589 MB**.

`storage/` was **already excluded**, so it contributed nothing to either number — but that is
the exclusion that matters most, and it is now annotated in the file rather than left implicit:

```
$ du -sh backend/storage backend/.venv backend/tests
228M  backend/storage      ← 4,562 dev documents, real borrower NPI
331M  backend/.venv
 12M  backend/tests
```

Had `storage/` not been excluded, the context would have been ~246 MB and those documents
would have landed **in the image** — an image is a far wider distribution boundary than a dev
machine.

`frontend/.dockerignore` created: `node_modules/`, `.next/`, `.turbo/`, `out/`, `*.tsbuildinfo`,
`.pnpm-store/`, `.env*.local`, `.env`, plus editor/OS noise. The `.env*.local` entry is
load-bearing beyond hygiene — a stray `frontend/.env.local` in the context would silently
override the build arg.

No `.env` is baked into either image.

---

## Task 6 — All three images running together

`docker-compose.images.yml` runs api + worker + frontend **from built images**, no bind mounts,
no host processes, against this worktree's existing Postgres and Redis (joined as an external
network). Ports 8102 / 3102, avoiding the 8100 / 3100 host dev servers.

```
$ docker ps
mbai-images-api        Up (healthy)   0.0.0.0:8102->8000/tcp
mbai-images-frontend   Up (healthy)   0.0.0.0:3102->3000/tcp
mbai-images-worker     Up (healthy)
mbai-bedrock-postgres  Up 3 days (healthy)      0.0.0.0:5433->5432/tcp
mbai-bedrock-redis     Up (healthy)             0.0.0.0:6380->6379/tcp
mbai-bedrock-worker    Up About an hour
mortgageboss-*         Up 2 weeks / 25 hours    (untouched)
```

All four required properties proven, not assumed:

| Claim | Evidence |
|---|---|
| **Frontend loads** | `curl http://localhost:3102` → **HTTP 200**; container healthy |
| **Frontend reaches the API** | `localhost:8102` baked into 3 static chunks; `localhost:8000` fallback absent (above) |
| **API reaches Postgres** | `curl http://localhost:8102/health` → `{"status":"healthy","checks":{"database":"ok","redis":"ok"}}` |
| **Worker consumes a task** | 8 `health.db_ping` tasks dispatched **from the api container**; the images-worker log shows them succeed: `Task health.db_ping[5f9f3cce…] succeeded in 0.083s: 'db-ok'` — which also proves worker → Postgres |

Two things the rehearsal deliberately exposes rather than hides:

- **No storage bind mount.** With `STORAGE_BACKEND=local` the API and worker have separate empty
  filesystems, so document *processing* would fail at the storage read
  (`app/tasks/document_processing.py:115`). That is precisely the gap C0's S3 backend closes,
  and the compose file says so in a comment. The tasks exercised here (`health.db_ping`) do not
  touch storage.
- **Two Celery workers share one broker.** `mbai-images-worker` and `mbai-bedrock-worker` are
  both on `mbai-bedrock-redis`, so `inspect ping` reports `2 nodes online` and dispatched tasks
  are load-balanced between them. This is why the healthcheck pins itself to
  `celery@$HOSTNAME`, and why I dispatched 8 tasks rather than 1.

### Deviation: `-p mbai-images` is required

The Verify block gives `docker compose -f docker-compose.images.yml up -d` with no project
flag. **I did not run it that way**, because it is unsafe here:

```
$ docker compose -f docker-compose.images.yml config → name: mbai-bedrock
$ docker compose -p mbai-images -f … config          → name: mbai-images
```

The repo-root `.env` sets `COMPOSE_PROJECT_NAME=mbai-bedrock` (A1), which takes precedence over
the file's own `name:` key. Without `-p`, this file runs **inside the mbai-bedrock project**,
where its `worker` service collides with the existing `worker` service in `docker-compose.yml`
— compose would recreate the long-running worker container, and would report
postgres/redis/mailhog as orphans (which `--remove-orphans` would then delete). A `down`
without `-p` would tear down the real stack.

Task 6 requires that this file "must not interfere with the existing stack", so the explicit
project name is what satisfies the ticket. It is documented at the top of the compose file.

**Correct usage:**

```bash
docker compose -p mbai-images -f docker-compose.images.yml up -d
docker compose -p mbai-images -f docker-compose.images.yml logs -f worker
docker compose -p mbai-images -f docker-compose.images.yml down   # safe: network is external
```

The stack is **still running** at hand-off. Stop it with the `down` above when you no longer
need it; the external network and the postgres/redis it borrows are untouched by that.

---

## Image sizes

| Image | Size | Base | App content |
|---|---|---|---|
| `mbai-api:test` (api + worker) | **589 MB** | `python:3.12-slim` 205 MB | ~384 MB (dominated by `.venv`) |
| `mbai-frontend:test` | **265 MB** | `node:20-alpine` 194 MB | ~71 MB (standalone output) |
| `mbai-bedrock-worker:latest` (pre-C1, for comparison) | 605 MB | — | — |

---

## Exact build commands

```bash
# Backend — one image, serves both api and worker (command decides which)
docker build -t mbai-api:test ./backend

# Frontend — the build arg is MANDATORY; see the warning above
docker build -t mbai-frontend:test \
  --build-arg NEXT_PUBLIC_API_URL=http://localhost:8102 ./frontend

# Staging
docker build -t mbai-frontend:staging \
  --build-arg NEXT_PUBLIC_API_URL=https://staging.mortgageboss.ai ./frontend
```

Backend command overrides:

```bash
# API
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
# Worker (the image default)
uv run celery -A app.tasks.celery_app worker --loglevel=info
```

---

## Verify — nothing disturbed

```
$ docker compose ps                          # this worktree
mbai-bedrock-postgres   Up 3 days (healthy)
mbai-bedrock-redis      Up (healthy)          ← restarted BY DESIGN for the task-3 test
mbai-bedrock-worker     Up About an hour

$ cd ../mortgageboss-ai && docker compose ps  # main worktree
mortgageboss-mailhog    Up 2 weeks (healthy)
mortgageboss-postgres   Up 2 weeks (healthy)
mortgageboss-redis      Up 2 weeks (healthy)
mortgageboss-worker     Up 25 hours
```

The main worktree's four containers kept their full uptime and were never touched. The only
restart anywhere was `mbai-bedrock-redis`, which task 3 explicitly calls for; it was restarted
immediately and everything reconnected.

---

## For C2 and C3

- **ALB target group health path: `/health/live`** — not `/health` or `/health/ready` (reasoning
  above and in ADR-344).
- **Every API task definition must override the healthcheck.** The image's baked Celery
  `HEALTHCHECK` applies regardless of command, so an API container that does not override it
  sits unhealthy forever.
- **The frontend task definition must NOT try to set `NEXT_PUBLIC_API_URL`.** It has no effect;
  the value is compiled in. Each environment needs its own image build.
- **The API needs `--host 0.0.0.0`; the frontend needs `HOSTNAME=0.0.0.0`.** Both default to
  localhost-only and fail the ALB check with no useful log line.
- **`STORAGE_BACKEND=s3` is required on Fargate** (C0) — there is no shared filesystem, as this
  rehearsal's missing bind mount demonstrates.

---

## Decisions recorded

`decisions.md` maximum was **ADR-343** (C0). Appended:

- **ADR-344** — one image for api + worker; the `/health/live` choice; and the baked-HEALTHCHECK
  consequence with its required override.
- **ADR-345** — `output: 'standalone'` and the build-time `NEXT_PUBLIC_API_URL` boundary.

Both qualify: each would otherwise have to be reverse-engineered from a production failure.

## Not done, and why

- **Non-root backend image / multi-stage backend** — audited and reported (task 1); the ticket
  says not to opportunistically refactor a Dockerfile that has worked for weeks.
- **No images pushed to ECR** — that is C2.
- **`docker-compose.yml` unmodified**, no Alembic migration, no `docker compose down` in either
  worktree, no `git push`, `STORAGE_BACKEND` unchanged.
