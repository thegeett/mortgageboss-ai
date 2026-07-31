# A1 — Worktree isolation for the Bedrock branch — result

**Branch:** `bedrock_integration` · **Worktree:** `../mbai-bedrock` · **Date:** 2026-07-31

All eight tasks done. All ten verify steps (A–J) pass. No Stop-and-report condition was hit.
The main stack was never stopped, restarted, recreated, or written to — its four containers
still show their original **13-day** uptime and its database is byte-for-byte unchanged.

---

## Files created and modified

| File | Change |
|---|---|
| `docker-compose.yml` | **Modified** — 8 lines: 4 `container_name`, 4 host ports parameterized with defaults. All comments preserved. |
| `.env.stack.example` | **Created** — tracked template for the root `.env`, documenting the three-`.env` split. |
| `scripts/check-stack.sh` | **Created** (`chmod +x`) — Alembic guard; refuses unless the reached DB publishes the expected host port. |
| `scripts/seed-from-main.sh` | **Created** (`chmod +x`) — read-only `pg_dump` from the main DB → `pg_restore` here, plus the storage files. |
| `docs/worktree-setup.md` | **Created** — setup, port map, Docker/DB commands, troubleshooting. |
| `docs/README.md` | **Modified** — one index row for `worktree-setup.md`. |
| `decisions.md` | **Modified** — appended ADR-341 (max was ADR-340). |
| `docs/tickets/A1-worktree-isolation-result.md` | **Created** — this file. |

**Not created, because they already existed in this worktree with correct contents:**
`.env` (root), `backend/.env`, `frontend/.env.local`. All three were verified rather than
written — see Verify J.

### The compose diff, in full

```diff
-    container_name: mortgageboss-postgres          +    container_name: ${STACK:-mortgageboss}-postgres
-      - "5432:5432"                                +      - "${PG_PORT:-5432}:5432"
-    container_name: mortgageboss-redis             +    container_name: ${STACK:-mortgageboss}-redis
-      - "6379:6379"                                +      - "${REDIS_PORT:-6379}:6379"
-    container_name: mortgageboss-mailhog           +    container_name: ${STACK:-mortgageboss}-mailhog
-      - "1025:1025"  # SMTP                        +      - "${SMTP_PORT:-1025}:1025"  # SMTP
-      - "8025:8025"  # Web UI                      +      - "${MAILHOG_UI_PORT:-8025}:8025"  # Web UI
-    container_name: mortgageboss-worker            +    container_name: ${STACK:-mortgageboss}-worker
```

Nothing else changed. Volumes, networks, healthchecks, `depends_on`, the worker
`environment` block, the storage mount, and every comment are untouched.

---

## Verify — actual observed output

### A. Existing stack is untouched

The ticket's command run from the main worktree (`../mortgageboss-ai`, no root `.env`):

```
$ ls .env  →  No such file or directory
    container_name: mortgageboss-mailhog     published: "1025"  published: "8025"
    container_name: mortgageboss-postgres    published: "5432"
    container_name: mortgageboss-redis       published: "6379"
    container_name: mortgageboss-worker
```

**This alone does not prove backward compatibility.** The main worktree is checked out on
`phase3_bucket_2` and therefore holds the *unedited* `docker-compose.yml` — the command
above measures today's baseline, not the effect of my edits. So I additionally resolved the
**edited** file with the root `.env` suppressed:

```
$ docker compose --env-file <empty> config | grep -E 'container_name|published'
    container_name: mortgageboss-mailhog     published: "1025"  published: "8025"
    container_name: mortgageboss-postgres    published: "5432"
    container_name: mortgageboss-redis       published: "6379"
    container_name: mortgageboss-worker
```

Identical to the baseline. `STACK` and `PG_PORT` confirmed unset in the shell first.
No `up` or `down` was run in the main worktree.

### B. Bedrock stack resolves separately

```
    container_name: mbai-bedrock-mailhog     published: "1025"  published: "8025"
    container_name: mbai-bedrock-postgres    published: "5433"
    container_name: mbai-bedrock-redis       published: "6380"
    container_name: mbai-bedrock-worker
project name: mbai-bedrock
```

Mailhog still resolves to 1025/8025 — see "Not anticipated" below.

### C. Both stacks run concurrently

`docker compose up -d --build postgres redis` created a new network, two new volumes, and
two containers. Immediately after:

```
mbai-bedrock-postgres   Up 2 seconds (health: starting)   0.0.0.0:5433->5432/tcp
mbai-bedrock-redis      Up 2 seconds (health: starting)   0.0.0.0:6380->6379/tcp
mortgageboss-mailhog    Up 13 days (healthy)              0.0.0.0:1025->1025, 0.0.0.0:8025->8025
mortgageboss-postgres   Up 13 days (healthy)              0.0.0.0:5432->5432/tcp
mortgageboss-redis      Up 13 days (healthy)              0.0.0.0:6379->6379/tcp
mortgageboss-worker     Up 13 days
```

All four `mortgageboss-*` retained their original uptime. No container name conflict.

### D. Target database empty before seeding

```
$ docker exec mbai-bedrock-postgres pg_isready …   → /var/run/postgresql:5432 - accepting connections
$ … select count(*) from information_schema.tables where table_schema='public';
 count
-------
     0
```

**0 — correct, empty database.** Proceeded.

### E. Seed, then parity

```
$ ./scripts/seed-from-main.sh
OK: mbai-bedrock-postgres published on 5433.

Source: mortgageboss-postgres (read-only)  ->  Target: mbai-bedrock-postgres

[1/4] pg_dump mortgageboss-postgres -> /tmp/main_dev.dump
      553820 bytes
[2/4] pg_restore -> mbai-bedrock-postgres
      restored (benign --if-exists notices: 0)
[3/4] storage: ../mortgageboss-ai/backend/storage -> backend/storage
      4562 file(s) present
[4/4] verifying
```

**Side-by-side, both databases:**

| | `mortgageboss-postgres` (main) | `mbai-bedrock-postgres` (this) |
|---|---|---|
| public tables | **33** | **33** |
| `loan_files` rows | **28** | **28** |
| `alembic_version` | **`9f0a5f88b6f8`** | **`9f0a5f88b6f8`** |

Revisions identical. Pre-seed source baseline was measured independently
(`tables=33 loan_files=28 alembic=9f0a5f88b6f8`) and matched post-seed — the source was
not modified.

The `pg_restore` stderr log was **completely empty** — zero lines, so not even the benign
`does not exist, skipping` notices appeared, and certainly nothing beyond them.

**Re-runnability tested** (not required by the ticket, but the ticket asks for a re-runnable
script, so I checked the claim). Ran the script two more times against the now-populated
target: identical output, still 33 / 28 / `9f0a5f88b6f8` — **28 rows, not 56**, confirming
`--clean --if-exists` drops and recreates rather than duplicating.

**Safety guards tested by deliberately tripping them:**

```
$ STACK=mortgageboss ./scripts/seed-from-main.sh
REFUSING: STACK=mortgageboss is the MAIN worktree's stack.
This script restores INTO ${STACK}-postgres — that would overwrite live data.        exit 1

$ STACK=nonesuch ./scripts/seed-from-main.sh
REFUSING: container nonesuch-postgres is not running.                                exit 1
```

### F. Storage files copied

```
$ diff -rq ../mortgageboss-ai/backend/storage backend/storage | head
(no output, exit 0)
```

227 MB / 4562 files, identical both sides. No differences to explain.

### G. Volumes are distinct

```
local     mbai-bedrock_mortgageboss-postgres-data
local     mortgageboss-ai_mortgageboss-postgres-data
```

Two volumes, different project prefixes — Compose's per-project prefixing working as the
ticket predicted (no `name:` key was needed).

### H. Worker starts clean against the seeded database

`docker compose up -d --build worker` built `mbai-bedrock-worker:latest` and started it.
`docker compose logs --tail=50 worker`:

```
 -------------- celery@082151fe44c5 v5.6.3 (recovery)
 - ** ---------- .> app:         mortgageboss:0xea6cac47e2d0
 - ** ---------- .> transport:   redis://redis:6379/0
 - ** ---------- .> results:     redis://redis:6379/0
 - *** --- * --- .> concurrency: 4 (prefork)
[tasks] documents.process_document, documents.reprocess_document, health.db_ping,
        health.ping, needs.propose_ai_needs, needs.update_for_document,
        verification.run_cross_source, verification.run_rule_engine
[INFO/MainProcess] Connected to redis://redis:6379/0
[INFO/MainProcess] mingle: searching for neighbors
[INFO/MainProcess] mingle: all alone
[INFO/MainProcess] celery@082151fe44c5 ready.
```

Ready, no connection or migration errors. The only warning is Celery's standard
"running with superuser privileges" notice, which the main worker also emits.

**`mingle: all alone` is the isolation proof** — the worker found no neighbours, i.e. it did
*not* join the main worktree's Redis, despite the main worker running. `redis://redis:6379/0`
is the Compose service name on the project-internal network (`mbai-bedrock_mortgageboss-network`),
which is why the worker's `environment` block correctly needed no change.

I also dispatched a task end-to-end to prove the worker actually reaches the **seeded**
database, not just Redis:

```
$ docker exec mbai-bedrock-worker uv run celery -A app.tasks.celery_app call health.db_ping
05eabe59-ff72-49ac-aeb4-6d0e0b29773c
… Task health.db_ping[05eabe59…] succeeded in 0.0593s: 'db-ok'
```

### I. Guard script works both ways

```
$ ./scripts/check-stack.sh
OK: mbai-bedrock-postgres published on 5433.                                          exit 0

$ EXPECTED_PG_PORT=9999 ./scripts/check-stack.sh
REFUSING: container publishes 5433, expected 9999.
You are probably pointed at the other worktree's database. Check .env.               exit 1
```

### J. No cross-talk to the other worktree

```
$ grep -r "localhost:8000\|localhost:3000" frontend/.env.local backend/.env
(no output, exit 1 — pass)

$ grep NEXT_PUBLIC_API_URL frontend/.env.local
NEXT_PUBLIC_API_URL=http://localhost:8100
$ grep CORS_ALLOWED_ORIGINS backend/.env
CORS_ALLOWED_ORIGINS=["http://localhost:3100"]
$ grep -E '^(DATABASE_URL|REDIS_URL)' backend/.env
DATABASE_URL=postgresql+asyncpg://mortgageboss:<redacted>@localhost:5433/mortgageboss_dev
REDIS_URL=redis://localhost:6380/0
```

The password is redacted here only to keep the `detect-secrets` pre-commit hook green; the
observed value is the committed dev credential from `docker-compose.yml` (ADR-005). The part
that matters for this check — **`:5433`** and **`:6380`** — is verbatim.

### Final integrity check on the main stack

```
mortgageboss-mailhog    Up 13 days (healthy)
mortgageboss-postgres   Up 13 days (healthy)
mortgageboss-redis      Up 13 days (healthy)
mortgageboss-worker     Up 13 days
tables=33  loan_files=28  alembic=9f0a5f88b6f8      # unchanged from the pre-seed baseline
$ git -C ../mortgageboss-ai status --short          # clean, no output
```

---

## Not anticipated by the ticket

**1. The guard script's SQL query cannot work as written — fixed.** The ticket specifies
`select inet_server_port()`. `docker exec` reaches the server over the container's **Unix
domain socket**, and `inet_server_port()` is NULL for any non-TCP connection. It returned an
empty string, and the first run of `seed-from-main.sh` died with the confusing
`REFUSING: unexpected in-container port .` — the guard failing for the wrong reason.

Replaced with `select current_setting('port')`, which reports the port the server listens on
regardless of how the client connected and needs no password:

```
$ docker exec mbai-bedrock-postgres psql … -tAc "select current_setting('port');"   → 5432
```

The alternative — forcing TCP inside the container with `psql -h 127.0.0.1` — also returns
5432 but requires `PGPASSWORD` in the script. `current_setting('port')` preserves the guard's
exact meaning with no credential. The reason is commented in the script.

**2. The frontend start command in the ticket is wrong for this pnpm — corrected.** The
ticket gives `pnpm dev -- --port 3100`. pnpm here is **10.33.0**, which passes `--` through
to the script literally instead of stripping it. Verified without starting a dev server, by
using an existing script that exits immediately:

```
$ pnpm typecheck -- --version    → tsc --noEmit -- --version
                                 → error TS5023: Unknown compiler option '--'.
$ pnpm typecheck --version       → tsc --noEmit --version → Version 5.9.3
```

So `pnpm dev -- --port 3100` would run `next dev -- --port 3100`. `docs/worktree-setup.md`
documents **`pnpm dev --port 3100`** with this evidence. This was determinable from the repo,
so I corrected it rather than stopping. The backend command (`uv run uvicorn app.main:app
--reload --port 8100`) is correct as given — `app` is at `backend/app/main.py:94`, confirmed.

**3. `seed-from-main.sh` needed a `.env` reader, and its precedence matters.** `STACK` lives
in the root `.env`, which Docker Compose reads but the **shell does not** — so `STACK` is
unset in any normal terminal and the ticket's "refuse if `STACK` is unset" guard would have
fired every time. The script reads `.env` itself. My first version sourced it with
`set -a; . ./.env`, which let `.env` **override** an exported `STACK` — the opposite of
Compose's own precedence, and it made the `STACK=mortgageboss` guard impossible to test.
Rewritten so the shell environment wins, matching Compose. Both guards were then tested (see E).

**4. Mailhog cross-talk, recorded not fixed.** Mailhog is excluded from this branch's stack,
but its compose entry still resolves to 1025/8025 here, so starting it would collide.
Consequently `SMTP_HOST=localhost` / `SMTP_PORT=1025` in this worktree's `backend/.env`
reaches the **main worktree's** Mailhog — genuine cross-talk, harmless for a dev mail
catcher. Documented in `docs/worktree-setup.md` and ADR-341 rather than fixed with a fourth
port. `SMTP_PORT` / `MAILHOG_UI_PORT` are parameterized and available if that changes.

**5. `.claude/settings.local.json` does not exist in this worktree.** The ticket asked me to
check `.claude/settings.local.json:46-61` for port-8000/3000 curl/lsof allowlist entries that
might block tool use here.

- There is no `.claude/` directory in `../mbai-bedrock` at all.
- The main worktree has one, but it is **not shared** — it is excluded by the user's *global*
  gitignore (`~/.config/git/ignore:1: **/.claude/settings.local.json`), so `git worktree`
  never copied it. It is not a repo file.
- Its first allow entry is `Bash(*)`, which already permits every Bash invocation; the
  port-specific curl/lsof strings below it are redundant and could not block anything.

**I changed nothing here.** Nothing blocked during this ticket, and creating a permissions
file the user did not ask for is out of scope.

---

## Checks performed that were confirmations, not edits

- **`.gitignore` covers the root `.env`** — `git check-ignore -v .env` → `.gitignore:28:.env`. Confirmed.
- **`frontend/.env.local` is ignored** — `frontend/.gitignore:33:.env*`. Already covered; nothing added.
  (The root `.gitignore` also has `.env.local` at :29.)
- **`.env.stack.example` is NOT ignored** — `git check-ignore` reports no match, so it will be
  tracked. The `!.env.example` negation at `.gitignore:31-32` is a literal filename match and
  does not apply to it, but nothing ignores it in the first place.
- **`DATABASE_URL` is asyncpg-only** — grep for a sync `postgresql://` across `backend/` and
  `docker-compose.yml` returns **nothing**. The doc's claim that all psql access goes through
  `docker exec` is correct.
- **Loan-file table name** — read from `backend/app/models/loan_file.py:128`:
  `__tablename__ = "loan_files"`. Not guessed.
- **Next ADR number** — `decisions.md` maximum was **ADR-340** (340 ADRs total, LP-431); appended **ADR-341**.

---

## Deliberately not done

- **No `git push`.** Committed locally only, per the ticket.
- **No Alembic command of any kind.** The schema arrived via the seed carrying its own
  `alembic_version`. This is the point of seeding rather than migrating.
- **No `docker compose down` / `down -v` in either worktree.** The Bedrock stack was only ever
  `up`-ed; the main stack was not touched.
- **No writes to the main database.** `pg_dump` only. Verified after the fact: main-side table
  count, row count, and revision are unchanged from the pre-seed baseline.
- **`backend/.env` in the main worktree not modified.** Not read for anything but the setup
  instructions in the doc.
- **Worker `environment` block unchanged.** Its service-name URLs were already correct, and
  `mingle: all alone` proves it.
- **Backend and frontend dev servers not started.** The user runs those (below). The one
  pnpm behaviour I needed was tested via `pnpm typecheck`, which exits immediately.
- **Mailhog not started here.** Would collide on 1025/8025.

---

## Commands the user must run manually

Both run on the **host**, not in Docker, from `../mbai-bedrock`:

```bash
# Backend — FastAPI on 8100
cd backend && uv run uvicorn app.main:app --reload --port 8100

# Frontend — Next.js on 3100   (NOTE: no `--` separator; see item 2 above)
cd frontend && pnpm dev --port 3100
```

`uv sync` and `pnpm install` have **not** been run in this worktree — `git worktree` does not
copy `.venv` or `node_modules`. Run them once before the commands above.

`NEXT_PUBLIC_*` values are inlined at build time, so if `pnpm dev` is already running from
before `frontend/.env.local` existed, restart it or the frontend will still be pointed at
`:8000`.

Current stack state at hand-off: `mbai-bedrock-postgres`, `-redis`, and `-worker` are up and
healthy on 5433 / 6380, database seeded to parity with the main worktree.

---

## See also

- [`docs/worktree-setup.md`](../worktree-setup.md) — the operational guide
- `decisions.md` ADR-341 — why parameterized defaults, and why seed rather than migrate
- [`A1-worktree-isolation.md`](A1-worktree-isolation.md) — the ticket
