# C0 — S3 storage backend

**Branch:** `bedrock_integration`
**Depends on:** A1, A2
**Blocks:** all ECS/Fargate work (C1–C5)

---

## Why this exists

Today the host-run API and the containerised Celery worker share document bytes through a
Docker bind mount (`./backend/storage:/app/storage`). On Fargate they are **separate tasks on
separate hosts with no shared filesystem**. The worker reads bytes at
`app/tasks/document_processing.py:115`; without object storage that read fails for every
document. This is the hard blocker for deployment.

Secondary benefit: it removes the relative-path footgun documented in `docker-compose.yml`
(the SHARED STORAGE comment), which already names object storage as *"the robust long-term
answer."*

## Current state (from A2 recon — verify, do not assume)

- `StorageBackend(ABC)` at `backend/app/storage/base.py:69-109` — four abstract methods:
  `save`, `read`, `delete`, `get_url`
- `LocalStorageBackend` at `backend/app/storage/local.py:22-87` — the only implementation
- `get_storage_backend()` at `backend/app/storage/__init__.py:26-39` — `@lru_cache(maxsize=1)`,
  the `"s3"` branch is **commented out** at `:36-38` and any non-local value raises `ValueError`
- `storage_backend: Literal["local", "s3"]` at `backend/app/core/config.py:113` — the type
  already permits `"s3"`, so Pydantic accepts it at startup and the app fails only at first use
- **No boto3/aioboto3** in `backend/pyproject.toml`
- **No bucket, region, or credential settings** anywhere in `config.py`
- `build_storage_path()` at `base.py:52-66` → `{company_id}/{file_id}/{document_id}.{ext}`
- `get_url()` returns `None` in the local backend (`local.py:84-87`) — the interface already
  reserves this slot for presigned URLs

**Do not change the `StorageBackend` interface.** Eight call sites depend on it (A2 §8). This
ticket adds an implementation, nothing more.

---

## Tasks

### 1. Add the dependency

Add **`aioboto3`** to `backend/pyproject.toml`. Not plain boto3 — the interface is `async` and
the app runs on asyncpg/async SQLAlchemy. Wrapping sync boto3 in `asyncio.to_thread` would work
but adds a thread per call under Celery concurrency.

Run `uv sync` and confirm `uv.lock` updates. Commit the lock file.

### 2. Add settings to `backend/app/core/config.py`

Alongside the existing `storage_backend` / `storage_local_path`:

| Setting | Type | Default | Notes |
|---|---|---|---|
| `s3_bucket` | `str \| None` | `None` | Required when backend is `s3` |
| `s3_region` | `str` | `"us-east-1"` | |
| `s3_endpoint_url` | `str \| None` | `None` | For MinIO/LocalStack in tests |
| `s3_presign_expiry_seconds` | `int` | `900` | 15 minutes |
| `s3_kms_key_id` | `str \| None` | `None` | When set, use SSE-KMS; else SSE-S3 |

**Add a Pydantic model validator** that fails at startup if `storage_backend == "s3"` and
`s3_bucket` is unset. This closes the gap A2 §10 item 14 flagged — today `"s3"` is accepted at
boot and only fails at first use, which defeats the "required vars missing → refuse to start"
convention in `CLAUDE.md`.

**No AWS credential settings.** Credentials come from the default provider chain: SSO locally,
task role on ECS. Never add access-key settings — that is the anti-pattern the whole
task-role design exists to avoid.

Update `backend/.env.example` with the new keys (keys only, no real values).

### 3. Implement `backend/app/storage/s3.py`

`S3StorageBackend(StorageBackend)` implementing all four methods. Mirror `local.py`'s structure
and docstring style.

**`save`** — reuse `build_storage_path()` from `base.py`. Do not reimplement path construction;
the sanitization and allowlist there are security-relevant (`base.py:37-49`). Put the object,
return the same key string the local backend would.

Set `ServerSideEncryption`:
- `aws:kms` with `SSEKMSKeyId` when `s3_kms_key_id` is set
- `AES256` otherwise

Also set `ContentType` from the extension, so `get_url()` downloads render correctly in-browser
rather than forcing a save.

**`read`** — get the object, return bytes. A missing key must raise `StorageError`
(`base.py:33-34`), matching `local.py:65-73`. Map botocore's `NoSuchKey` / 404 to `StorageError`
— **never let a botocore exception escape**, or callers that catch `StorageError` will miss it
and the pipeline's failure handling breaks.

**`delete`** — must be **idempotent**, matching `local.py:75-82` (`unlink(missing_ok=True)`).
S3's `delete_object` already succeeds on a missing key; just don't add a pre-check that raises.

**`get_url`** — return a presigned GET URL with `s3_presign_expiry_seconds` expiry. This is the
one method that gains real capability over local (which returns `None`). Note for the result
doc: callers currently treat `None` as "no URL available", so returning a real URL is a
behavioural change — check `app/api/documents.py:393` (the download endpoint) to see whether it
branches on `None`, and report what you find. **Do not change that endpoint in this ticket.**

**Client lifecycle.** `aioboto3` sessions create clients via an async context manager. Do not
create a client per call — that is a TLS handshake per document read. Create a session once at
`__init__` and open the client per operation, or hold a long-lived client with explicit cleanup.
Choose one, document the reasoning in the module docstring, and make sure it works under Celery
prefork (each worker process needs its own client — clients are not fork-safe).

### 4. Enable the factory

`backend/app/storage/__init__.py` — uncomment and implement the `"s3"` branch:

```python
if settings.storage_backend == "s3":
    return S3StorageBackend(
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        endpoint_url=settings.s3_endpoint_url,
        kms_key_id=settings.s3_kms_key_id,
        presign_expiry=settings.s3_presign_expiry_seconds,
    )
```

Keep the `ValueError` fallthrough for unknown values. Keep `@lru_cache(maxsize=1)` — but note in
the result doc whether that cache is safe across Celery forks given the client-lifecycle choice
in task 3.

### 5. Tests — `backend/tests/storage/test_s3_storage.py`

Follow the existing patterns in `tests/storage/test_local_storage.py` and `test_factory.py`.
**No network calls.** Use `moto` (add to dev dependencies) or stub the aioboto3 client — pick
whichever fits the existing test style better and say which you chose and why.

Cover:

- `save` returns the same key shape as local for identical inputs — this is the parity that
  matters, since existing DB rows hold local-format keys
- `save` sets `ServerSideEncryption` correctly for both the KMS and non-KMS cases
- `read` round-trips bytes exactly
- `read` on a missing key raises `StorageError`, **not** a botocore exception
- `delete` is idempotent — deleting a nonexistent key does not raise
- `get_url` returns a URL containing the bucket and an expiry parameter
- Factory returns `S3StorageBackend` when `storage_backend="s3"`
- **Startup validation fails** when `storage_backend="s3"` and `s3_bucket` is `None`

### 6. Manual verification against real S3

Local unit tests do not prove IAM, encryption, or presigning work. Write
`scripts/verify-s3.py` — a standalone script that, given a bucket name:

1. Saves a small test payload
2. Reads it back and asserts byte equality
3. Fetches a presigned URL and confirms it resolves (HTTP 200)
4. Deletes, then deletes again to prove idempotency
5. Confirms the object had the expected encryption header before deletion

It must print each step's outcome and exit non-zero on any failure. This is what proves the
backend actually works before Fargate depends on it.

**You cannot run this** — it needs AWS credentials the ticket does not provide. Write it,
verify it imports and its `--help` works, and leave running it to the user.

### 7. Document

**`docs/tickets/C0-s3-storage-result.md`** — files created and modified, actual test output
(not "passed"), the client-lifecycle decision and why, the `get_url()` behavioural-change
finding from task 3, and the exact commands the user must run for task 6.

**`decisions.md`** — append an ADR only if a real decision was made. Read the file for the
current maximum number (A1 recorded ADR-341) and use the next in sequence; match the existing
format. Likely candidates: aioboto3 over boto3; the client-lifecycle choice; startup validation
over deferred failure. If nothing qualifies, say so in the result doc rather than padding.

---

## Verify

```bash
cd backend
uv sync
uv run pytest tests/storage/ -v          # all green, including new S3 tests
uv run pytest                            # full suite — no regressions
uv run ruff check . && uv run mypy app   # or whatever the repo's linters are
python scripts/verify-s3.py --help       # imports cleanly
```

Then confirm the default path is untouched:

```bash
grep STORAGE_BACKEND backend/.env        # must still be "local"
docker compose ps                        # worker still healthy
```

**The existing local flow must be completely unaffected.** `storage_backend` defaults to
`"local"` and this ticket does not change that default.

---

## Stop and report — do not work around

- Any need to change the `StorageBackend` ABC signature. Eight call sites depend on it; a
  signature change is a different ticket.
- Any call site that would break because `get_url()` now returns a URL instead of `None`.
- `aioboto3` conflicting with an existing pinned dependency.
- Any place the code assumes a local filesystem path outside `app/storage/` — that would mean
  the abstraction leaks and S3 alone is not sufficient for Fargate.

## Do not

- `git push` — commit locally only.
- Create any Alembic migration. This ticket has no schema changes, and both worktrees must stay
  at the same revision.
- Change `STORAGE_BACKEND` from `local` in any committed `.env` or example.
- Add AWS access-key or secret-key settings. Credential chain only.
- Modify `local.py`, the ABC in `base.py`, or any of the eight call sites.
- Create an S3 bucket, or run anything that requires AWS credentials.
