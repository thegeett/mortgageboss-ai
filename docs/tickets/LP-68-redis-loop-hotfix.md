# LP-68 hotfix — Per-loop async Redis client for Celery tasks

- **Ticket:** LP-68 serialization-infra hotfix (surfaced during LP-71.5 verification)
- **Epic:** Phase 2 — Document Handling → the needs list
- **Status:** Completed
- **Date:** 2026-06-24

## Summary

A real infrastructure bug in **LP-68's per-file needs serialization**, found while
verifying that LP-69's AI reasoning actually produces needs end-to-end. The worker
ran but **every needs task crashed** with `RuntimeError: Event loop is closed`, so no
AI needs were ever created (and `ai_needs_status` stayed `pending`). See **ADR-181**.

## The bug

- `loan_file_needs_lock` (LP-68) acquires a Redis lock via `get_redis_client()`.
- `get_redis_client()` returned a **process-global** `redis.asyncio` client; its
  connections bind to the event loop that created them.
- Celery runs each task on a **fresh** event loop (`run_async` = `asyncio.run` per
  task). The first needs task created the client on loop A; once loop A closed, the
  next task (a new loop) reused the same client → `RuntimeError: Event loop is closed`
  the moment it touched the lock, **before** any need was created or status updated.
- The DB path already handled this (`task_session` builds a fresh engine per task
  loop); the Redis client did not. Unit tests masked it with a `_loop_bound_redis`
  fixture that hands out a per-loop client, so the bug only showed in the real worker.

## The fix

`get_redis_client()` is now **loop-aware**: it caches the client keyed on the running
event loop and rebuilds when the loop changes.

- API (one long-lived loop): the same client is reused — no behaviour change.
- Worker (a fresh loop per task): each task gets a loop-local client — no reuse of a
  client bound to a closed loop.

This mirrors `task_session`'s per-loop engine.

## Verification

- `tests/core/test_redis_loop.py` (3 tests): two `asyncio.run` loops both ping (the
  cross-loop case that **fails with "Event loop is closed" without the fix** —
  confirmed by stashing the fix and watching the two cross-loop tests fail); the
  client is rebuilt for a new loop; the same loop reuses one client.
- Full backend suite: **1013 passed**; mypy + ruff clean. No call sites changed.

## Operational note

The running worker image must be **rebuilt** to pick this up (and the LP-71.5 code):

```
docker compose --profile worker up -d --build worker
```

After that, a fresh MISMO import runs LP-69 to completion: the AI-reasoned needs are
created and `ai_needs_status` flips `pending` → `completed`. A file whose task already
crashed (pre-fix) stays `pending` until re-imported — there's no auto-retry.

## References

- ADR-181 (decisions.md); LP-68 (the per-file serialization); LP-69 (the AI
  reasoning the lock gates); LP-71.5 (the verification that surfaced this).
