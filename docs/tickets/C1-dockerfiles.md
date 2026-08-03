# C1 — Dockerfiles for API and frontend

**Branch:** `bedrock_integration`
**Depends on:** C0
**Blocks:** C2 (Terraform), C3 (ECS services)

---

## Why this exists

Fargate deploys images, not source. Three services need one:

| Service | Image | Status today |
|---|---|---|
| worker | `backend/Dockerfile` | **exists** — `build: ./backend` in compose |
| api | same image, different command | needs verification, likely no change |
| frontend | none | **must be written** |

The API and worker should share **one image** with different `command` values — the pattern
compose already uses. Two images from one codebase means two build paths that can drift.

---

## Tasks

### 1. Audit the existing backend Dockerfile

Read `backend/Dockerfile` and report in the result doc:

- Base image and Python version — must satisfy `requires-python = ">=3.12"`
- Whether it uses `uv sync --frozen` (it must, so `uv.lock` governs — C0 added `aioboto3` there)
- Whether it runs as a **non-root user**
- Whether it is multi-stage
- Final image size: `docker images mbai-bedrock-worker --format '{{.Size}}'`
- Whether `CMD`/`ENTRYPOINT` is overridable (compose overrides it today, so probably yes)

Change it only if something below requires it. It has been working for weeks; do not
opportunistically refactor.

### 2. Make the same image serve the API

Verify the existing image can run uvicorn — the dependency is already there
(`README.md:172` documents `uv run uvicorn app.main:app --reload`).

Test without modifying anything:

```bash
docker run --rm --env-file backend/.env \
  -e DATABASE_URL=... -e REDIS_URL=... \
  -p 8101:8000 mbai-bedrock-worker \
  uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then `curl` the health endpoint. **Find the real health path** by reading
`backend/app/main.py` — do not assume `/health`. Report what it is; C3 needs it for the ALB
target group.

If it works, no Dockerfile change is needed and the API is a command override in C3. If it does
not, report why before changing anything.

**`--host 0.0.0.0` is required** — the default `127.0.0.1` binds inside the container only and
the ALB health check fails with no useful error.

### 3. Add a container healthcheck for the worker

A Celery worker has no HTTP endpoint, so ECS cannot tell "alive" from "alive but not consuming"
— a worker that lost its broker connection looks healthy and silently stops processing.

Add to `backend/Dockerfile`:

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD uv run celery -A app.tasks.celery_app inspect ping -d celery@$HOSTNAME || exit 1
```

Verify the exact app path against `backend/app/tasks/celery_app.py` and the compose `command`.
Confirm it reports healthy on the running worker and unhealthy when Redis is stopped — but
**do not stop the main worktree's Redis**; use this worktree's `mbai-bedrock-redis`, and restart
it after.

### 4. Write `frontend/Dockerfile`

Multi-stage, Next.js, pnpm (`frontend/pnpm-lock.yaml`), Node 20
(`.github/workflows/frontend-ci.yml:38` — the only place Node is pinned).

Requirements:

- **`output: 'standalone'`** in `next.config.*`. Check whether it is already set; if not, add it
  and say so. Without it the runtime stage carries the full `node_modules` — hundreds of MB
  versus tens.
- Three stages: deps (`pnpm install --frozen-lockfile`) → builder (`pnpm build`) → runner
  (standalone output plus `public/` and `.next/static/` only)
- Enable pnpm via `corepack`, do not `npm i -g pnpm`
- Non-root user in the runner stage
- `EXPOSE 3000`, `CMD ["node", "server.js"]`
- `HOSTNAME=0.0.0.0` — same binding trap as uvicorn

**The build-time environment problem.** `NEXT_PUBLIC_*` variables are inlined at build time, not
read at runtime. `frontend/lib/config.ts:2` and `frontend/lib/api/client.ts:5` both fall back to
`http://localhost:8000` when `NEXT_PUBLIC_API_URL` is unset — so an image built without it ships
a frontend pointing at localhost, which fails silently in the browser with no server-side error.

Take it as a build arg:

```dockerfile
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
RUN pnpm build
```

Document prominently in the result doc that **the staging image must be built with
`--build-arg NEXT_PUBLIC_API_URL=https://staging.mortgageboss.ai`**, and that changing the API
URL requires a rebuild, not a task-definition edit. This is the single most likely deployment
mistake in the whole C series.

### 5. Add `.dockerignore` files

`backend/.dockerignore` must exclude at minimum: `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`,
`.ruff_cache/`, `.mypy_cache/`, `storage/`, `.env`, `tests/`.

**`storage/` is the important one** — 227 MB / 4,562 files of dev documents would otherwise land
in the build context and, worse, in the image. Check whether it is already excluded; report the
before/after build-context size.

`frontend/.dockerignore`: `node_modules/`, `.next/`, `.env*.local`.

**Never bake `.env` into an image.** Runtime config comes from the task definition and Secrets
Manager.

### 6. Verify both images run together

Add `docker-compose.images.yml` — a compose file that runs api, worker, and frontend all from
built images against this worktree's existing postgres and redis. This is the local rehearsal of
the Fargate topology: no bind mounts, no host processes, everything containerised.

It must not interfere with the existing stack. Use ports **8102** and **3102** to avoid the
running 8100/3100 host processes.

Prove: frontend loads, it reaches the API, the API reaches Postgres, the worker consumes a task.

### 7. Document

**`docs/tickets/C1-dockerfiles-result.md`** — files created and modified; the health endpoint
path found in task 2; image sizes for all three; the build-context size change from
`.dockerignore`; the exact `docker build` commands including the frontend build arg; and any
`next.config` change.

**`decisions.md`** — append an ADR only if a real decision was made. Read for the current maximum
(C0 recorded ADR-343) and use the next in sequence. Candidates: one shared image for api+worker;
standalone output mode; build-arg API URL. If nothing qualifies, say so.

---

## Verify

```bash
# backend
docker build -t mbai-api:test ./backend
docker images mbai-api:test --format '{{.Size}}'

# frontend
docker build -t mbai-frontend:test \
  --build-arg NEXT_PUBLIC_API_URL=http://localhost:8102 ./frontend
docker images mbai-frontend:test --format '{{.Size}}'

# all three together
docker compose -f docker-compose.images.yml up -d
curl -f http://localhost:8102<health-path>
curl -f http://localhost:3102
docker compose -f docker-compose.images.yml logs worker | tail -20
```

Then confirm nothing was disturbed:

```bash
docker compose ps                        # mbai-bedrock-* still healthy, uptime intact
cd ../mortgageboss-ai && docker compose ps   # mortgageboss-* untouched
```

Both stacks must still be running with their original uptime.

---

## Stop and report — do not work around

- The existing backend image cannot run uvicorn without a Dockerfile change.
- `output: 'standalone'` breaks the build or an existing route.
- Any secret that would have to be a build arg to make the frontend build — build args are
  visible in image history, so a secret there is a leak, not an inconvenience.
- The frontend needing `NEXT_PUBLIC_*` values that are not known until deploy time.

## Do not

- `git push`.
- Create any Alembic migration.
- Modify the existing `docker-compose.yml` — add the new file alongside it.
- Run `docker compose down` in either worktree.
- Bake `.env`, credentials, or `backend/storage/` into any image.
- Push images to ECR — that is C2.
- Change `STORAGE_BACKEND` from `local`.
