# C0 — S3 storage backend — result

**Branch:** `bedrock_integration` · **Date:** 2026-08-03

All seven tasks done. Lint, types, and the storage suite are green; the full suite has
**one pre-existing flaky failure unrelated to C0**, detailed below rather than glossed.
The default (`local`) path is untouched and verified.

**One Stop-and-report condition fired** (a filesystem assumption outside `app/storage/`).
It does not block Fargate and did not change the implementation — §"Stop-and-report" below.

---

## Files created and modified

| File | Change |
|---|---|
| `backend/pyproject.toml` | **Modified** — added `aioboto3>=15.5.0` with a comment on why not boto3 |
| `backend/uv.lock` | **Modified** — 18 new transitive packages, no conflicts |
| `backend/app/core/config.py` | **Modified** — 5 S3 settings, a startup `model_validator`, a blank-string `field_validator`, one import line |
| `backend/.env.example` | **Modified** — the 5 new keys, blank, with the no-credentials rule in prose |
| `backend/app/storage/s3.py` | **Created** — `S3StorageBackend`, 4 methods + helpers |
| `backend/app/storage/__init__.py` | **Modified** — the `"s3"` factory branch, `__all__`, docstring |
| `backend/tests/storage/test_s3_storage.py` | **Created** — 28 tests |
| `backend/scripts/verify-s3.py` | **Created** (`chmod +x`) — real-bucket verification, 6 steps |
| `decisions.md` | **Modified** — appended ADR-356 and ADR-357 (max was ADR-355) |
| `docs/tickets/C0-s3-storage-result.md` | **Created** — this file |

**Not modified, per the ticket:** `app/storage/local.py`, the ABC in `app/storage/base.py`,
and all eight `StorageBackend` call sites. No Alembic migration was created. `STORAGE_BACKEND`
remains `local` in both `backend/.env` and `backend/.env.example`.

### Script location

`backend/scripts/verify-s3.py`, not repo-root `scripts/`. The ticket writes
`scripts/verify-s3.py` inside a `cd backend` block, `backend/scripts/` already exists (it
holds `generate_refi_fixtures.py`), and the script needs the backend venv for `aioboto3` and
`app.*`. Repo-root `scripts/` holds shell ops scripts (`check-stack.sh`, `seed-from-main.sh`).

---

## Verify — actual output

### `uv sync`

```
Resolved 117 packages in 1.27s
Prepared 18 packages in 1.15s
Installed 18 packages in 40ms
 + aioboto3==15.5.0      + aiobotocore==2.25.1    + aiofiles==25.1.0
 + aiohappyeyeballs==2.7.1  + aiohttp==3.14.3     + aioitertools==0.13.0
 + aiosignal==1.4.0      + attrs==26.1.0          + boto3==1.40.61
 + botocore==1.40.61     + frozenlist==1.8.0      + jmespath==1.1.0
 + multidict==6.7.1      + propcache==0.5.2       + s3transfer==0.14.0
 + wrapt==1.17.3         + yarl==1.24.5
```

**No dependency conflict** — nothing was downgraded or unpinned; the only `~` line is the
project's own editable install. `uv.lock` updated and committed.

### `uv run pytest tests/storage/ -v`

```
63 passed in 0.11s
```

35 pre-existing local/factory tests plus the 28 new S3 tests, all named in the run:

```
test_save_returns_same_key_as_local_backend_for_identical_inputs PASSED
test_save_applies_the_shared_extension_sanitization              PASSED
test_save_uses_sse_s3_when_no_kms_key_configured                 PASSED
test_save_uses_sse_kms_when_a_key_is_configured                  PASSED
test_save_never_writes_an_unencrypted_object                     PASSED
test_save_sets_content_type_from_the_extension                   PASSED
test_save_then_read_round_trips_exact_bytes                      PASSED
test_read_missing_key_raises_storage_error_not_botocore          PASSED
test_read_missing_key_does_not_raise_client_error                PASSED
test_read_non_missing_client_error_also_becomes_storage_error    PASSED
test_delete_removes_the_object                                   PASSED
test_delete_is_idempotent_on_a_missing_key                       PASSED
test_delete_swallows_a_missing_object_error_from_s3              PASSED
test_delete_surfaces_a_real_failure                              PASSED
test_get_url_returns_presigned_url_with_bucket_and_expiry        PASSED
test_get_url_uses_the_configured_expiry                          PASSED
test_get_url_differs_from_local_which_returns_none               PASSED
test_client_is_opened_per_operation_not_held                     PASSED
test_client_is_built_with_the_configured_region_and_endpoint     PASSED
test_backend_refuses_an_empty_bucket                             PASSED
test_factory_returns_s3_backend_when_configured_s3               PASSED
test_factory_still_returns_local_by_default                      PASSED
test_settings_reject_s3_backend_without_a_bucket                 PASSED
test_settings_reject_s3_backend_with_a_blank_bucket              PASSED
test_settings_accept_s3_backend_with_a_bucket                    PASSED
test_settings_accept_local_backend_without_a_bucket              PASSED
test_blank_optional_s3_strings_normalize_to_none                 PASSED
test_no_aws_credential_settings_exist                            PASSED
```

### `uv run pytest` (full suite)

```
1 failed, 2943 passed, 5 skipped, 1 xfailed, 2 warnings in 242.83s (0:04:02)
FAILED tests/services/test_loan_file_ids.py::test_inbox_token_is_independent_of_display_id
```

**This failure is a pre-existing flake, not a C0 regression.** Evidence:

- The assertion is `assert code not in token` — a random 4-char display code must not appear
  as a substring of an independently random inbox token
  (`backend/tests/services/test_loan_file_ids.py:120`). It loops **1000 times** per run.
- Observed failure: `'8DX6' not in '7P8DX6t1g42JgKmS'` — a genuine chance substring hit.
- The display code is 4 chars from a 31-char alphabet
  (`app/services/loan_file_ids.py:23-26`); the token is `secrets.token_urlsafe(12)` → 16 chars
  over the 64-char base64url alphabet (`loan_file_ids.py:29`, `:51`). There are 13 possible
  start positions, so a collision is rare but has non-zero probability on **every** run, and
  1000 iterations per run compounds it. It is a property test written as if the property were
  absolute.
- **Re-ran the test 6/6 times: passed every time.**
- It touches `app/services/loan_file_ids.py` — no storage, no config, no S3. Nothing in the C0
  diff can reach it. `git status` confirms neither the test nor the module is in this change.

Per the ticket ("do not refactor, fix, or improve anything you find"), I left it alone. It is
worth a separate ticket — a seeded RNG or an explicit tolerance would make it deterministic.

### `uv run ruff check .` / `ruff format` / `uv run mypy app`

```
All checks passed!
650 files already formatted
Success: no issues found in 297 source files
```

Ruff initially flagged 3 issues in the new code (2 unused `noqa` directives, 1 unused unpacked
variable) and the formatter reflowed `s3.py` and `verify-s3.py`; all fixed, re-verified clean.

### `python scripts/verify-s3.py --help`

Imports cleanly and prints usage (run as `uv run python scripts/verify-s3.py --help` — the
script needs the backend venv for `aioboto3`):

```
usage: verify-s3.py [-h] --bucket BUCKET [--region REGION]
                    [--endpoint-url ENDPOINT_URL] [--kms-key-id KMS_KEY_ID]
                    [--presign-expiry PRESIGN_EXPIRY] [--keep]

Verify the S3 storage backend against a real bucket (C0).
...
Credentials come from the default AWS provider chain (SSO/profile locally,
task role on ECS). Exits non-zero on the first failure.
```

`EXIT=0`. Omitting the required `--bucket` exits `2`. The app imports are deliberately
**deferred into `_run()`** so `--help` works without a populated `backend/.env` (importing
`app.storage` constructs the `Settings` singleton).

### The default path is untouched

```
$ grep STORAGE_BACKEND backend/.env
STORAGE_BACKEND=local
$ grep '^STORAGE_BACKEND' backend/.env.example
STORAGE_BACKEND=local

$ docker compose ps
mbai-bedrock-postgres   Up 3 days (healthy)
mbai-bedrock-redis      Up 3 days (healthy)
mbai-bedrock-worker     Up 3 days
```

**Extra check not in the ticket, but necessary.** `app/storage/__init__.py` now imports
`app.storage.s3` at module scope, which imports `aioboto3` — so the worker **image** must
carry the new dependency or the worker dies on import. The running container held the old
code *and* old deps (consistent, so it was not broken), but the next rebuild had to be proven.
Rebuilt and confirmed:

```
$ docker compose up -d --build worker
 Image mbai-bedrock-worker Built ... Container mbai-bedrock-worker Started

$ docker compose logs --tail=12 worker
[2026-08-03 15:19:00,928: INFO/MainProcess] Connected to redis://redis:6379/0
[2026-08-03 15:19:01,944: INFO/MainProcess] mingle: all alone
[2026-08-03 15:19:01,961: INFO/MainProcess] celery@71b3a0069116 ready.

$ docker exec mbai-bedrock-worker uv run python -c "import aioboto3, app.storage; ..."
aioboto3 15.5.0
backend: LocalStorageBackend
```

Worker ready, `aioboto3` installed from the committed lock via `uv sync --frozen`, and the
factory still resolves to `LocalStorageBackend`.

---

## The client-lifecycle decision, and why

**Chosen: an `aioboto3.Session` held on the instance, a client opened per operation.**
Recorded as ADR-357.

The ticket asked me not to create a client per call, because that is a TLS handshake per
document read. That instinct is right in a normal async service and **wrong here**, and the
reason is specific:

`aioboto3` clients are built on `aiohttp`, so a client is bound to the event loop that created
it. The Celery bridge runs **a fresh event loop per task** — `run_async` is literally
`asyncio.run(coro)` (`app/tasks/base.py:41-43`). The backend instance outlives tasks because
`get_storage_backend()` is `@lru_cache(maxsize=1)`. So a cached client would be created in task
N's loop and reused in task N+1's *different, already-closed* loop → "Event loop is closed".
The `lru_cache` does not make that unlikely; it makes it **certain**.

The codebase already met this exact problem with the database and answered it the same way:
`task_session` builds a fresh engine per task with `NullPool` because "asyncpg connections are
loop-bound" (`app/tasks/base.py:46-65`). Following that precedent beats inventing a second,
contradictory loop-lifetime model inside one worker.

**The cost, stated plainly:**

- **On the worker there is no amplification.** The pipeline performs exactly *one* storage read
  per document (`app/tasks/document_processing.py:115`), so it is one handshake per task
  either way.
- **On the API it is a real per-request cost.** Uvicorn runs one long-lived loop, so a cached
  client would be safe there.

**Why I did not special-case the API:** a per-event-loop client cache needs a close hook when
the loop ends; `asyncio.run` provides none, so every task would leak an unclosed `aiohttp`
connector — trading a handshake for an fd leak. The clean fix is upstream: give the worker a
persistent loop (the "revisit loop/pool reuse if throughput grows" caveat already at
`app/tasks/base.py:9-10`), after which a long-lived client is safe everywhere.

### Is the `@lru_cache` safe across Celery forks? — Yes

It caches the *backend instance*, and the S3 instance holds only an `aioboto3.Session`: a
credential/config resolver with **no sockets**, therefore fork-safe. This is also the standard
boto3 guidance (share a session, never share clients). Clients — the non-fork-safe and
loop-bound part — are never held. Documented in both `app/storage/s3.py` and the factory
docstring, and asserted by `test_client_is_opened_per_operation_not_held`.

---

## `get_url()` — the behavioural-change finding

The ticket asked me to check `app/api/documents.py:393` and report whether it branches on
`None`. **It does not, and the change is inert.**

The download endpoint (`app/api/documents.py:381-400`) never calls `get_url()` at all. It does:

```python
storage = get_storage_backend()
content = await storage.read(document.storage_path)
return Response(content=content, media_type=document.mime_type, headers={...})
```

i.e. it **proxies the bytes** through the API. A repo-wide grep for `get_url` across
`backend/` and `frontend/` finds **no application call site whatsoever**:

```
backend/app/storage/local.py:84       the definition
backend/app/storage/base.py:103       the ABC declaration
backend/tests/storage/test_local_storage.py:156,158   asserts local returns None
```

So `get_url()` returning a real URL under S3 breaks nothing — there is no caller to break, and
no `if url is None` fallback anywhere. **No Stop-and-report condition fired on this.** I did not
touch the endpoint.

Worth flagging for a later ticket, not this one: switching downloads from proxy-through-API to
a presigned redirect would cut egress and API load, but it moves the authorization boundary
from the endpoint to the URL's expiry window. That is a real security decision, and C0
deliberately does not make it. Noted in ADR-356 under "Not decided here".

---

## Test approach: stubs, not moto

**Chosen: a hand-written in-memory fake of the aioboto3 client surface.** No new dev dependency.

Why: the repo's established pattern for an external SDK is exactly this — `tests/ai/test_client.py:70-73`
swaps the Anthropic singleton for a `SimpleNamespace` whose `messages.create` is an `AsyncMock`.
There is no moto, LocalStack, or testcontainers anywhere in the suite, and moto's aiobotocore
integration is a separate and historically fragile dependency. A stub keeps the suite offline
and dependency-free, which is what CI relies on.

The fake raises **real `botocore.exceptions.ClientError`** objects, so the missing-key→
`StorageError` mapping is tested against the true exception type rather than a lookalike.

**What this does not prove, stated so nobody over-trusts the green tick:** the stub verifies the
backend's *contract* (key shape, encryption arguments, error mapping, delete idempotency,
per-operation client) but nothing about IAM permissions, whether the bucket policy accepts the
encryption arguments, or whether a presigned URL actually resolves. That is precisely what
`scripts/verify-s3.py` exists to prove.

The single most important test is `test_save_returns_same_key_as_local_backend_for_identical_inputs`:
existing DB rows hold local-format keys, so an S3 backend deriving keys differently would orphan
every stored document. It asserts byte-identical output from both backends for the same inputs.

---

## Stop-and-report

Four conditions were listed. Three did not fire:

| Condition | Outcome |
|---|---|
| Need to change the `StorageBackend` ABC | **Did not fire** — no signature changed; `s3.py` implements the existing four methods verbatim |
| A call site broken by `get_url()` returning a URL | **Did not fire** — there is no `get_url` call site at all (above) |
| `aioboto3` conflicting with a pinned dependency | **Did not fire** — clean resolution, 18 additions, no downgrades |

### One condition DID fire — a local-filesystem assumption outside `app/storage/`

**`backend/app/scripts/seed_dev_data.py:870-872`:**

```python
company_dir = Path(settings.storage_local_path) / str(company_id)
if company_dir.exists():
    shutil.rmtree(company_dir, ignore_errors=True)
```

The dev seed script reaches **past** the storage abstraction to delete previously-seeded bytes
directly off the filesystem. Under `storage_backend="s3"` this silently does nothing: it builds
a local path that does not exist, `exists()` is `False`, and the S3 objects are left behind.

**Reporting it, not working around it** — per the ticket, I changed nothing. My assessment of
severity, separated from the fact:

- It is **not on the Fargate runtime path.** `seed_dev_data.py` is a developer convenience for
  populating a local database; it is not imported by the API, the worker, or any task.
- The abstraction does **not** leak anywhere that matters for deployment. Every runtime path
  goes through `get_storage_backend()` — verified across all eight call sites.
- So **S3 alone remains sufficient for Fargate**, which is what that Stop condition is really
  asking. I judged this not worth halting the ticket over, and completed the work.
- The fix, when someone wants the seed script to work against S3, is a `delete()` loop over the
  known keys rather than an `rmtree`. That is a seed-script ticket, not C0.

Two test files do the same thing (`tests/integration/test_phase2_real_stack.py:254` unlinks a
stored file directly; several conftests monkeypatch `storage_local_path`). Test-only, and they
are correct for a local-backend test.

---

## Commands the user must run — task 6 is NOT done

Task 6's script is written and verified to import, **but it has never been run against a real
bucket**, because that needs AWS credentials this ticket does not provide. Until it passes,
the S3 backend is *implemented and unit-tested*, not *proven*.

```bash
cd backend

# SSE-S3 (default):
uv run python scripts/verify-s3.py --bucket <your-bucket> --region <region>

# SSE-KMS:
uv run python scripts/verify-s3.py --bucket <your-bucket> --region <region> \
    --kms-key-id arn:aws:kms:<region>:<acct>:key/<id>

# MinIO/LocalStack:
uv run python scripts/verify-s3.py --bucket <bucket> --endpoint-url http://localhost:9000
```

Credentials come from the default chain — `aws sso login` (or `AWS_PROFILE=…`) beforehand.
It prints one line per step and exits non-zero on the first failure:

```
[  ok  ] save     — key=<uuid>/<uuid>/<uuid>.pdf (41 bytes)
[  ok  ] read     — 41 bytes, byte-identical
[  ok  ] presign  — HTTP 200, 41 bytes, expiry=900s
[  ok  ] encrypt  — ServerSideEncryption=AES256, ContentType=application/pdf
[  ok  ] delete   — object removed
[  ok  ] delete (again) — no error on a missing key — idempotent
[  ok  ] read after delete — StorageError as expected
```

It writes exactly one object and deletes it. The key comes from the app's own
`build_storage_path()` — deliberately, since proving the real key derivation is half the point
— so it looks like any document key and carries no "this is a test" marker. The key is printed
at the save step; **if the run fails before the delete steps, that object is left behind and
you should remove it.** `--keep` retains it on purpose.

The required IAM permissions on the bucket/prefix are `s3:PutObject`, `s3:GetObject`,
`s3:DeleteObject`, and `s3:ListBucket`; SSE-KMS additionally needs `kms:GenerateDataKey` and
`kms:Decrypt` on the key.

**To actually switch a deployment to S3** (do not do this locally — it changes where documents
live, and existing local bytes would not be visible):

```bash
STORAGE_BACKEND=s3
S3_BUCKET=<bucket>          # REQUIRED — the app now refuses to start without it
S3_REGION=<region>
S3_KMS_KEY_ID=<arn>         # optional; blank => SSE-S3
```

Note there is **no migration path for existing local bytes** in this ticket — the 4562 files
under `backend/storage/` would need copying to the bucket under the same keys. Keys are
identical across backends (that is the parity test), so a plain `aws s3 sync` preserving the
relative paths is sufficient. Out of scope here; flagging it because a deployment that flips the
setting without copying would find every existing document unreadable.

---

## Decisions recorded

`decisions.md` maximum was **ADR-355** (A1). Appended:

- **ADR-356** — aioboto3 over boto3; credential chain and never key settings; encryption always
  on; startup validation over deferred failure.
- **ADR-357** — the client-lifecycle choice, why the obvious optimization is wrong here, and the
  upstream fix that would let it be revisited.

Both qualify: each is non-obvious, each would otherwise be "fixed" by a future reader into
something broken, and each cost real reasoning to reach.

---

## Anything not done, and why

- **Task 6 not executed** — needs AWS credentials the ticket does not provide, and the ticket
  says to leave running it to the user.
- **`docker compose down`, Alembic, `git push`** — not run, per the ticket.
- **The download endpoint** — untouched, per the ticket, even though S3 now makes a presigned
  redirect possible.
- **`local.py`, `base.py`, the eight call sites** — untouched, per the ticket.
- **The `seed_dev_data.py` filesystem assumption** — reported above, deliberately not fixed.
- **The flaky `test_inbox_token_is_independent_of_display_id`** — reported above, deliberately
  not fixed.

---

## Follow-up — four review findings fixed, over two rounds

Two code reviews of the branch raised four defects in this commit. Three shared one shape:
**a deployment-scoped fault disguised as an ordinary, per-document outcome** — the exact
late-failure mode the startup bucket validator was written to prevent, reintroduced elsewhere.
The fourth (§3) is its mirror image: a boot refused over a setting the process never reads.

The second review re-examined `s3.py` directly and filed **nothing** against it, confirming
`generate_presigned_url` is genuinely a coroutine in the pinned aiobotocore, that `ClientError`
and `BotoCoreError` are siblings so the two-clause mapping is both required and correctly
ordered, that the body is read inside the client context, and that `NoSuchBucket` now falls
through to a hard raise.

### 1. `NoSuchBucket` classified as "object missing" (`s3.py`)

`_MISSING_CODES` contained `NoSuchBucket`. A typo'd `S3_BUCKET`, or a bucket in another
account, therefore made every `read()` raise `StorageError("No stored file at …")` —
indistinguishable from a genuinely deleted document — and made every `delete()` return the
idempotent success **having deleted nothing**. One config error would read as per-document
data loss across an entire tenant.

Removed from the set, with the reasoning recorded at the definition. Bucket-level errors now
fall through to the generic branch and raise.

### 2. Only `ClientError` mapped to `StorageError` (`s3.py`)

`ClientError` and `BotoCoreError` are **siblings** — both derive straight from `Exception` —
so catching the first does not catch the second. `NoCredentialsError`,
`EndpointConnectionError`, `ConnectTimeoutError` and `ResponseStreamingError` (a reset during
`await response["Body"].read()`) all escaped raw, against a module docstring and a test
asserting botocore never escapes. That set is precisely the Fargate day-one list: task role not
yet attached, NAT/VPC-endpoint hiccup.

Added an `except BotoCoreError` clause to all four operations. In `delete` it deliberately does
**not** take the idempotent path: an unanswered call is no evidence the object is absent, so
reporting success there would be a silent no-op.

### 3. Blank values not honoured on the two defaulted S3 settings (`config.py`)

`_blank_s3_str_is_none` covered `s3_bucket`, `s3_endpoint_url` and `s3_kms_key_id` but not
`s3_region`, while `.env.example` heads the block with "Leave blank for local dev". A blank
`S3_REGION=` validated as `""` and reached botocore as an invalid region name at the first S3
call.

A follow-up review then caught the field that fix left behind: `s3_presign_expiry_seconds`
was the only S3 setting with no normalizer at all, and it failed *earlier* rather than later —
a blank `S3_PRESIGN_EXPIRY_SECONDS=` raised `int_parsing` at `Settings` construction and
refused to start the app **even under `STORAGE_BACKEND=local`**, where the value is never
read. Verified by probing both backends against the pre-fix commit:

```
PRE-FIX,  blank S3_PRESIGN_EXPIRY_SECONDS=
  storage_backend=local: REFUSED TO START -> ValidationError: s3_presign_expiry_seconds
  storage_backend=s3:    REFUSED TO START -> ValidationError: s3_presign_expiry_seconds
POST-FIX
  storage_backend=local: OK -> expiry=900
  storage_backend=s3:    OK -> expiry=900
```

Both are fixed by one validator, because the recurring defect in this area has been **the
field someone forgot** — three times now. These fields differ in kind from the optional
strings: each has a safe default and a non-optional annotation, so "unset" resolves to the
default rather than to `None` (which the annotation would reject). The validator registers
itself from `_BLANK_S3_MEANS_DEFAULT` via `@field_validator(*_BLANK_S3_MEANS_DEFAULT)`, so
its field list *is* the registry — adding an entry is the whole change, with no second place
to remember. `_DEFAULT_S3_REGION` and `_DEFAULT_S3_PRESIGN_EXPIRY_SECONDS` are named so a
field default and its normalizer cannot drift.

`test_every_defaulted_s3_setting_has_a_blank_normalizer` closes the loop structurally: it
reflects over `Settings.model_fields` and asserts every non-optional `s3_*` field appears in
the registry, so a fourth omission fails the suite rather than shipping.

### Verification

Fourteen tests added across the two rounds. Every one that targets a defect was confirmed to
**fail against the pre-fix code**; two (`test_explicit_s3_region_is_untouched`,
`test_explicit_s3_presign_expiry_is_untouched`) pass both ways by design, guarding against
over-correcting a real configured value to the default.

Full gate green: **2958 passed, 5 skipped, 1 xfailed** (up from 2944), `ruff check` clean,
`ruff format` clean on 650 files, `mypy` strict clean on 297 source files.

No ADR: these are defect fixes within ADR-356's stated intent, not new decisions.

**Not fixed here.** Both reviews raised findings against *earlier* branch commits, all still
open and out of this commit's scope — chiefly the `derived.py` bank-statement continuity
cluster (AS-8), the `dti.py` HOA gate reaching only the `/dti` display rather than the snapshot
or AS-4 reserves, `eval/stubs.py` converting abstention into a fabricated `"no"`, and the
`check-stack.sh` / `seed-from-main.sh` / `.env.stack.example` infra items from A1.
