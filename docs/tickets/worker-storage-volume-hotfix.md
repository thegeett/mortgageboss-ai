# Hotfix — Share the storage directory with the Dockerized Celery worker

- **Type:** Infra/config hotfix (surfaced during LP-71.x verification)
- **Epic:** Phase 2 — Document Handling
- **Status:** Completed
- **Date:** 2026-06-25

## Summary

Every document uploaded at the Documents tab failed (`status=failed`). A read-only
diagnostic found the cause: the API (on the **host**) writes uploads to
`backend/storage`, but the Celery **worker** runs in Docker and read from an **empty**
`/app/storage` (no shared volume) → `StorageError` at the file-read step, before
classification. **Not a code regression** — a storage-sharing gap that appeared when the
worker moved into Docker. See **ADR-184**.

## The fix

Added a volume to the `worker` service in `docker-compose.yml` so the host's
`backend/storage` is mounted at the path the worker resolves `./storage` to (WORKDIR is
`/app`, so `./storage` → `/app/storage`):

```yaml
  worker:
    volumes:
      - ./backend/storage:/app/storage
```

Only the worker needs the mount (the API is on the host and sees `backend/storage`
directly). The pipeline / extractors / LP-71 code are unchanged.

## The trap + the long-term direction

The **relative** `STORAGE_LOCAL_PATH=./storage` is the trap — it resolves to different
real directories on the host (`backend/storage`) vs. in the container (`/app/storage`).
The minimal local-dev fix is the shared mount. The production-correct answer is **object
storage (S3/MinIO — already supported via `storage_backend`)** so the host API and the
worker share a *network* store; an absolute `STORAGE_LOCAL_PATH` + the mount is the
interim hardening. (Object storage is **Phase 7**, not done here.)

## Verification

- `docker compose --profile worker up -d worker` → the worker's `/app/storage` now lists
  the host's tenant subdirectories (no longer empty); a previously-failed document's
  `storage_path` resolves to a real file inside the container.
- Reprocessed a previously-failed pay stub end-to-end: **no StorageError** → classified
  (`pay_stub`, 0.95) → extracted (10 core fields, succeeded) → `document_completed`
  (`status` flipped `failed` → `completed`) → the needs update ran.

## Notes

- Already-failed documents do **not** auto-retry — re-upload (or reprocess) after the fix
  to clear them. (The stale `processing_error` text on a reprocessed-successful row is
  cosmetic; `status=completed` is authoritative.)
- Operational/infra fix — a one-stanza `docker-compose.yml` change + worker restart.

## References

- ADR-184 (decisions.md); the diagnostic (the StorageError root cause);
  `backend/app/storage/local.py` (the read path); `backend/app/core/config.py`
  (`storage_local_path`, `storage_backend`).
