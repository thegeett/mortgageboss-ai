# Secrets audit — ECS Fargate staging (C2 input)

**Scope.** Every field of `backend/app/core/config.py`, classified for a staging
deployment on ECS Fargate. Read-only audit; no file outside this document was
modified.

**Method.** Each claim below is either **DATA** (observed in the repo, or produced by
running the installed libraries) or **INFERENCE** (my judgement, marked as such).
Anything non-obvious carries a `file:line`. Several claims that are usually asserted
from memory — asyncpg's SSL default, whether structlog leaks frame locals, whether
pydantic echoes a rejected secret — were **executed against the installed versions**
rather than recalled, and the transcripts are summarised in the notes.

**Classification key**

| Class | Meaning |
|---|---|
| **SECRET** | Must live in Secrets Manager; injected by the ECS *execution* role via `secrets[]` |
| **CONFIG** | Plain `environment[]` entry in the task definition; not sensitive |
| **LOCAL** | Dev-only; has no place in a deployed task definition at all |
| **DERIVED** | Supplied by the platform (task role, container runtime); must NOT be config |

---

## Verdict on the drafted four-secret list

You drafted `database-url`, `jwt-secret-key`, `encryption-key`, `anthropic-api-key`.

| Drafted secret | Verdict | Why |
|---|---|---|
| `database-url` | **KEEP** | Correct. But the *value* has a trap — see Note 3; `?sslmode=` crashes the app. |
| `jwt-secret-key` | **KEEP** | Correct. Per-environment; rotation is cheap (Note 2). |
| `encryption-key` | **KEEP — with a hard constraint** | Correct, and the most consequential of the four. It is effectively **unrotatable** and must be **identical for any environment that reads the same database**. Terraform generating a fresh one per environment is a data-loss bug. See Note 1. |
| `anthropic-api-key` | **REMOVE for a Bedrock staging** | Conditional since B1. When `AI_PROVIDER=bedrock` the app requires it *not at all*, and `AsyncAnthropicBedrock` never sends it. Injecting it adds a credential to the task with no consumer. See Note 6. |

**Missing from the list:** only `REDIS_URL`, and only conditionally — it is a secret
exactly when ElastiCache AUTH is enabled, because the token is embedded in the URL.
See Note 7.

**Does not belong:** nothing else in `config.py` is a credential. `S3_KMS_KEY_ID`
(`config.py:206`) is an ARN, not a key — CONFIG. `SMTP_PASSWORD` (`config.py:212`) is
dead config today (Note 8).

So the corrected staging set is **three or four secret containers**, not four:
`database-url`, `jwt-secret-key`, `encryption-key`, plus `redis-url` *iff* AUTH is on.

---

## Full classification

### Application

| Setting | file:line | Class | Notes |
|---|---|---|---|
| `app_name` | `config.py:51` | CONFIG | Default fine. |
| `app_version` | `config.py:52` | CONFIG | |
| `environment` | `config.py:53` | **CONFIG — must be set** | Defaults to `"development"`. Drives `is_development`/`is_production` (`config.py:222,230`). |
| `debug` | `config.py:54` | **CONFIG — must stay false** | Safe default, but see Note 5: `debug=True` turns on SQLAlchemy `echo`, which logs **statement parameters** — i.e. borrower PII into CloudWatch. |

### Database

| Setting | file:line | Class | Notes |
|---|---|---|---|
| `database_url` | `config.py:57` | **SECRET** | Carries the RDS master password. Whole-URL, not parts — see Note 3. |
| `database_pool_size` | `config.py:58` | CONFIG | |
| `database_max_overflow` | `config.py:59` | CONFIG | |
| `database_pool_timeout` | `config.py:60` | CONFIG | |

### Redis / Celery

| Setting | file:line | Class | Notes |
|---|---|---|---|
| `redis_url` | `config.py:63` | **SECRET if AUTH enabled, else CONFIG** | Note 7. |
| `celery_broker_url_override` | `config.py:71` | CONFIG (unset) | Same rule as `redis_url` if you do set it. |
| `celery_result_backend_override` | `config.py:72` | CONFIG (unset) | |

### AI provider

| Setting | file:line | Class | Notes |
|---|---|---|---|
| `anthropic_api_key` | `config.py:79` | **SECRET — only when `ai_provider="anthropic"`** | Note 6. |
| `anthropic_model_classification` | `config.py:102` | CONFIG | Tier identity; also the *lookup key* under Bedrock (`config.py:428-434`). |
| `anthropic_model_extraction` | `config.py:103` | CONFIG | |
| `anthropic_model_reasoning` | `config.py:104` | CONFIG | Do not re-point — the 37 rules are calibrated on it. |
| `anthropic_model_analysis` | `config.py:107` | CONFIG | ⚠️ Re-pointing it raises `ModelResolutionError` under Bedrock (known gap, commit `a0034bc`). |
| `ai_provider` | `config.py:116` | CONFIG | `bedrock` for staging. |
| `bedrock_region` | `config.py:117` | CONFIG | |
| `bedrock_model_classification` | `config.py:129` | CONFIG | Required when provider is bedrock (`config.py:335-349`). |
| `bedrock_model_extraction` | `config.py:130` | CONFIG | |
| `bedrock_model_reasoning` | `config.py:131` | CONFIG | |
| `ai_requests_per_minute_anthropic` | `config.py:137` | CONFIG | |
| `ai_requests_per_minute_bedrock` | `config.py:138` | **CONFIG — size it per task** | Limiter is process-local (`config.py:135-136`); N tasks pace at N× the value. |
| `ai_max_retries` | `config.py:141` | CONFIG | |
| `ai_base_retry_delay_seconds` | `config.py:142` | CONFIG | |
| `ai_request_timeout_seconds` | `config.py:149` | CONFIG | |
| `needs_duplicate_flagging_enabled` | `config.py:153` | CONFIG | |
| `gate_ai_groups` | `config.py:159` | CONFIG | |
| `pending_checks_enabled` | `config.py:165` | CONFIG | |

### Auth / crypto

| Setting | file:line | Class | Notes |
|---|---|---|---|
| `jwt_secret_key` | `config.py:168` | **SECRET** | Note 2. |
| `jwt_algorithm` | `config.py:172` | CONFIG | HS256 — symmetric, so the signing key is also the verifying key. |
| `jwt_access_token_expire_minutes` | `config.py:173` | CONFIG | 24h. |
| `jwt_refresh_token_expire_days` | `config.py:174` | CONFIG | 30d — the blast radius of a leaked `jwt_secret_key`. |
| `encryption_key` | `config.py:184` | **SECRET — shared, unrotatable** | Note 1. |

### CORS / storage

| Setting | file:line | Class | Notes |
|---|---|---|---|
| `cors_allowed_origins` | `config.py:190` | **CONFIG — must be set** | Defaults to `["http://localhost:3000"]`. Not permissive, so the failure is a broken frontend, not an open origin. Applied with `allow_credentials=True` (`main.py:111`) — never combine that with `["*"]`. |
| `storage_backend` | `config.py:193` | CONFIG | `s3` in staging. |
| `storage_local_path` | `config.py:194` | **LOCAL** | Unread when backend is `s3`. |
| `s3_bucket` | `config.py:200` | CONFIG | Boot-required when `s3` (`config.py:385-386`). |
| `s3_region` | `config.py:201` | CONFIG | |
| `s3_endpoint_url` | `config.py:203` | **LOCAL** | MinIO/LocalStack only; must be unset in AWS. |
| `s3_presign_expiry_seconds` | `config.py:204` | CONFIG | |
| `s3_kms_key_id` | `config.py:206` | CONFIG | An ARN, not a credential. |
| *(no AWS key settings)* | `config.py:197-199` | **DERIVED** | Deliberate: credentials come from the provider chain / task role. Adding key settings would defeat the design. |

### Email — all dead config today (Note 8)

| Setting | file:line | Class |
|---|---|---|
| `smtp_host` | `config.py:209` | **LOCAL** (MailHog default) |
| `smtp_port` | `config.py:210` | **LOCAL** (1025) |
| `smtp_username` | `config.py:211` | CONFIG (unused) |
| `smtp_password` | `config.py:212` | SECRET *when wired*; **omit now** |
| `smtp_from_email` | `config.py:213` | CONFIG |
| `smtp_from_name` | `config.py:214` | CONFIG |

### Logging

| Setting | file:line | Class | Notes |
|---|---|---|---|
| `log_level` | `config.py:217` | CONFIG | |
| `log_format` | `config.py:218` | **CONFIG — set `json`** | Defaults to `console`. |

### Computed — never task-definition entries

`is_development` (`:222`), `is_production` (`:230`), `celery_broker_url` (`:234`),
`celery_result_backend` (`:240`) are `@computed_field` properties. **DERIVED.**

### Platform-supplied

| Value | Class | Notes |
|---|---|---|
| AWS credentials (S3 + Bedrock) | **DERIVED** | Task role via the container credential endpoint. |
| `PGSSLROOTCERT` | CONFIG | The *only* way to give asyncpg a CA bundle through this code path — Note 3. |
| `NEXT_PUBLIC_API_URL` | **CONFIG, build-time only** | Note 4. |

---

## Notes

### Note 1 — ENCRYPTION_KEY: two independent uses, and it cannot be rotated

**DATA.** `encryption_key` is read in exactly one module, `app/core/encryption.py`
(`config.py:184`; reads at `encryption.py:47` and `:58`). It has **two** consumers:

1. **Fernet encryption at rest.** `get_cipher()` (`encryption.py:58`) →
   `EncryptedString` (`app/models/encrypted_types.py:52,56`) → the single column
   `Borrower.ssn` (`app/models/borrower.py:88`). This is the only encrypted column.
2. **A derived HMAC key for PII match-hashing.** `derive_key()` (`encryption.py:47`)
   → `pii._match_key()` (`app/verification/snapshot/pii.py:134`) →
   `match_hash()` (`pii.py:137-150`), which is
   `HMAC-SHA256(K, "{kind}:{loan_file_id}:{normalized}")` prefixed `v1:`.

**Rotation consequence — asymmetric between the two uses, and this is the key finding:**

*Fernet (use 1): permanent, unrecoverable data loss.* Fernet here is constructed with
a **single key**, not a `MultiFernet` rotation chain (`encryption.py:58`). Rotating
`encryption_key` makes every existing `borrowers.ssn` ciphertext undecryptable —
`decrypt_value` raises `ValueError` (`encryption.py:91-93`). The module says so
outright: *"Key rotation and secret-manager integration are out of scope for V1"*
(`encryption.py:23-24`), echoed at `config.py:182-183`. **There is no re-encryption
path in the repo.** Recovery requires the old key; if the old key is gone, every
stored SSN is gone.

*Match-hash (use 2): survivable, and less damaging than it first looks.* The hashes
are persisted — `PiiField.match_hash` is serialized into the snapshot blob
`snapshot_records.snapshot_json` (`app/models/snapshot_record.py:57`), written by
`persist_snapshot` (`app/services/verification_run.py:563`), and materialized as the
**value** of the `id.ssn_hash` fact tag (`tag_materialization/parsed.py:33-37`;
vocabulary at `rules/fact_tags.csv:48`) which rule **ID-2** gathers
(`rules/specs/ID-2.yaml:30`, `rule_tags.csv:110`).

But rotation does **not** break live rule evaluation, because every run rebuilds the
snapshot from source data and recomputes all hashes under the current key — so hashes
are internally consistent *within* a run, which is all ID-2 compares.

**DATA:** nothing in the application compares hashes across runs. `.matches()` and
`is_matchable` (`pii.py:254-277`) have **zero callers** in `app/`.
`load_snapshots_for_loan_file` (`persistence.py:109`) has **zero callers**.
`load_snapshot` (`persistence.py:101`) is called only by
`app/scripts/snapshot_persist_smoke.py:43`.

**INFERENCE.** So today the match-hash damage from rotation is latent: historical
`snapshot_records` rows keep hashes that no longer correspond to anything recomputed,
and any *future* feature that diffs two runs' PII (a "what changed between runs" view)
would silently see every PII field as changed across the rotation boundary. The `v1:`
version prefix (`pii.py:62`) exists precisely so a construction change is detectable —
but it does **not** encode the *key*, so a key rotation is invisible to it. That is a
gap worth knowing about, not a blocker today.

**⚠️ Constraint for Terraform — the one you flagged, confirmed.** `ENCRYPTION_KEY`
must be **IDENTICAL for every task that reads the same database**. That means API and
worker tasks share one value (they do if both read one secret), and it means a
`random_password`/`random_id` resource generating a *fresh* key per environment is
correct *only* because staging has its own RDS instance. **It becomes a data-loss bug
the moment two environments share a database, or the moment the secret is regenerated
by a `terraform destroy`/`apply` cycle against a surviving RDS instance.** Whatever
resource generates it must have `lifecycle { prevent_destroy }`-grade protection, or
be generated once out-of-band and imported. This is the single most dangerous value in
the audit.

**Attacker capability with `ENCRYPTION_KEY`:** decrypt every stored borrower SSN from
a database dump (the whole point of ADR-051 is that a DB-only compromise yields
ciphertext — this key removes that protection), **and** brute-force the match-hashes:
`pii.py:28-36` states the threat model explicitly — an SSN has ~10⁹ possibilities, so
a holder of *both* a snapshot and this key can enumerate SSNs offline.

### Note 2 — JWT_SECRET_KEY: nothing durable breaks

**DATA.** Used only in `app/core/jwt.py:84` (sign) and `:123` (verify). Tokens are
stateless and carry only `sub`/`type`/`iat`/`exp` (`jwt.py:76-81`) — deliberately no
role, email, or PII (`jwt.py:3-10`). No token is stored in the database; there is no
denylist or revocation table.

**Rotation consequence:** every outstanding access token (24h) and refresh token (30d)
fails verification with `InvalidTokenError` (`jwt.py:128-129`); users re-login.
Nothing durable is lost. **Per-environment; rotate freely.**

**INFERENCE.** Because there is no revocation mechanism anywhere, rotating this secret
*is* the only way to mass-revoke sessions. That is an argument for it being
independently rotatable in Terraform — i.e. its own secret container, which your draft
already has right.

**Attacker capability:** mint a valid token for **any** `user_id` — full impersonation
of any user including admins, for up to 30 days, with no server-side way to revoke it
short of rotating the key. Authorization is looked up live from the DB (`jwt.py:7-10`),
so the token grants identity, not roles — but identity is sufficient.

### Note 3 — DATABASE_URL: whole URL, and `sslmode` is a hard crash

**Whole URL, not parts — DATA.** `str(settings.database_url)` is passed directly to
`create_async_engine` in both places that build an engine: `app/core/database.py:19`
and `app/tasks/base.py:59`. Alembic also injects it
(`alembic/env.py:25`). Nothing anywhere reads a host/user/password component
separately. **A single whole-URL secret is correct.**

**The SSL trap — DATA, executed against the installed versions** (asyncpg 0.31.0,
SQLAlchemy 2.0.50):

- **There is no SSL configuration anywhere in the repo.** No `connect_args`, no
  `ssl=`, no `sslmode` — `database.py:18-25` and `tasks/base.py:59` pass the URL and
  nothing else. A repo-wide grep for `sslmode|ssl=|ssl_context` returns nothing.
- **SQLAlchemy's asyncpg dialect has zero SSL handling.** Grepping the installed
  `sqlalchemy/dialects/postgresql/asyncpg.py` source for `sslmode`, `ssl_`, `"ssl"`,
  `SSL` returns **0 hits each**. It does not translate libpq names.
- **Unknown query params become raw kwargs to `asyncpg.connect()`.** Running
  `PGDialect_asyncpg().create_connect_args(...)`:

  ```
  ...?sslmode=require  ->  {..., 'sslmode': 'require'}
  ...?ssl=require      ->  {..., 'ssl': 'require'}
  ```

  and `AsyncAdapt_asyncpg_dbapi.connect` forwards `**kw` to `asyncpg.connect`
  unfiltered (it pops only `async_fallback`, `async_creator_fn`, and the two
  prepared-statement options).
- **`asyncpg.connect()` has no `sslmode` parameter and no `**kwargs`** —
  `inspect.signature` confirms `sslmode in parameters == False`,
  `ssl in parameters == True` (default `None`), `has **kwargs == False`.

**⇒ `DATABASE_URL=...?sslmode=require` does not get ignored — it raises `TypeError:
connect() got an unexpected keyword argument 'sslmode'` and the app cannot connect at
all.** The libqp-conventional spelling, which is what almost everyone writes and what
RDS documentation uses, is a hard startup failure here. This is the trap you suspected,
and it is sharper than "easy to miss".

**The correct spelling is `?ssl=require`.**

**Does `rds.force_ssl=1` *require* an explicit argument? — DATA: no, but the default is
weak.** `asyncpg/connect_utils.py:652-656`:

```python
if ssl is None:
    ssl = os.getenv('PGSSLMODE')
if ssl is None and have_tcp_addrs:
    ssl = 'prefer'
```

So over TCP with nothing specified, asyncpg uses **`prefer`** — it attempts TLS and
falls back to plaintext. Against `rds.force_ssl=1` the TLS attempt succeeds, so **the
connection works and is encrypted**. But `prefer` is explicitly advisory: the same
module sets `ssl.verify_mode = CERT_NONE` and
`ssl.check_hostname = sslmode >= SSLMode.verify_full` — so under `prefer` there is
**no certificate validation and no hostname check**, i.e. no protection against an
in-path attacker.

**INFERENCE.** For GLBA-covered data in transit you want `verify-full`, not `prefer`.
Getting there has a second trap: `sslrootcert` is parsed by asyncpg only from *its own*
DSN (`connect_utils`), and SQLAlchemy never hands asyncpg a DSN — so
`?sslrootcert=/path` would become another unexpected kwarg and crash exactly like
`sslmode`. The only paths that work through this code are (a) the `PGSSLROOTCERT`
**environment variable** (`connect_utils` reads it), which is a plain CONFIG env var
pointing at the RDS CA bundle baked into the image, or (b) an `ssl.SSLContext` passed
via `connect_args`, which is an app-code change. **Not a Terraform change — flagging it
as the constraint on the secret's value and on the image.**

**Attacker capability with `DATABASE_URL`:** full read/write to the entire database —
every loan file, borrower, document, and snapshot across all tenants (`company_id`
scoping is enforced in application queries, not by database roles). Borrower SSNs come
back as ciphertext only; everything else is plaintext. Combined with `ENCRYPTION_KEY`
it is a total compromise of borrower NPI.

### Note 4 — Build-time vs runtime

**DATA.** `NEXT_PUBLIC_API_URL` is the only build-time value, and the C1 Dockerfile
already documents it (`frontend/Dockerfile:14-15,24,29-31`, `ARG`/`ENV` at `:60-61`):
*"NEXT_PUBLIC_* variables are INLINED INTO THE JAVASCRIPT AT BUILD TIME… setting
NEXT_PUBLIC_API_URL in an ECS task definition does [nothing]"*, and *"a build arg is
visible in `docker history`, so a secret passed this way is a leak"*.

**Independently verified:** a grep for `process.env.` across `frontend/src` and
`frontend/next.config.ts` returns **no hits at all** — the Dockerfile's claim that it
is "the only non-NODE_ENV environment variable the frontend reads"
(`frontend/Dockerfile:31`) holds.

**Are there others? DATA: no.** On the backend, every setting is read through the
`settings` singleton at runtime. The one deploy-time (not build-time) reader is Alembic
(`alembic/env.py:25`), which needs `DATABASE_URL` — so the migration task needs the
same secret as the app.

**⇒ No backend setting is baked into an image. `NEXT_PUBLIC_API_URL` is the sole
build-time value and it must never be a secret.**

### Note 5 — Unsafe-in-deployment defaults

**DATA.** Every default that is wrong for staging:

| Setting | Default | Failure if left |
|---|---|---|
| `environment` | `"development"` | `is_production` false; staging reports itself as dev. |
| `debug` | `False` ✅ | Safe — but if ever enabled, `create_async_engine(echo=settings.debug)` (`database.py:20`) logs **every statement with its parameters**, putting borrower PII into CloudWatch. Treat as a compliance switch, not a dev convenience. |
| `log_format` | `"console"` | Human-formatted logs; no structured aggregation. |
| `cors_allowed_origins` | `["http://localhost:3000"]` | Frontend blocked. Restrictive, so it fails closed — an availability bug, not a hole. |
| `smtp_host`/`smtp_port` | `localhost:1025` | MailHog. Harmless only because nothing sends mail (Note 8). |
| `storage_local_path` | `"./storage"` | Ignored under `s3`; would silently write to container-local disk if `storage_backend` were left `local`. |

**INFERENCE.** No default is *permissive* — there is no wildcard CORS, no debug-true,
no auth bypass. The risk profile is "silently behaves like dev", not "open to the
world". The `storage_backend` one is the sharpest: leaving it `local` in staging writes
documents to ephemeral container storage that vanishes on task replacement, with no
error at any point.

### Note 6 — Can the app start with a secret absent?

**DATA.** Two boot-time `model_validator(mode="after")` guards, both of which run at
**import** (`settings = get_settings()`, `config.py:397`) and therefore crash the
container rather than failing at first use:

- `_require_provider_credentials` (`config.py:322-370`) — requires `ANTHROPIC_API_KEY`
  **only when** `ai_provider == "anthropic"` (`:332-333`); requires all three
  `BEDROCK_MODEL_*` when provider is bedrock (`:335-349`); and rejects an ambiguous
  tier→Bedrock mapping (`:356-369`).
- `_require_s3_bucket_when_s3` (`config.py:372-387`) — requires `S3_BUCKET` when
  `storage_backend == "s3"`.

Plus field-level constraints: `jwt_secret_key` `min_length=32` (`:168-171`),
`encryption_key` `min_length=44` (`:184-187`), `database_url` as `PostgresDsn`
(`:57`), `redis_url` as `RedisDsn` (`:63`). All are boot-time.

**⚠️ One real gap — DATA, executed.** `encryption_key` is validated for **length only,
not format**. A 44-character non-base64 string constructs `Settings()` successfully;
`Fernet()` rejects it only at first use:

```
Settings() constructed OK with a 44-char non-base64 key
Fernet() rejects it only at FIRST USE -> ValueError: Fernet key must be 32 url-safe base64-encoded bytes.
```

And `get_cipher()` is `@lru_cache`d and called lazily (`encryption.py:50-58`), so the
first failure happens on the first SSN write — inside a request handler or a Celery
task, as a generic 500 or a task failure. **This is exactly the "healthy container that
fails every document" shape that `_require_s3_bucket_when_s3` and
`_require_provider_credentials` were written to prevent** (`config.py:376-380`,
`:326-330`), so it is an inconsistency with the codebase's own stated convention rather
than a subjective preference. A truncated or mis-encoded value in Secrets Manager is a
very plausible way to hit it.

**INFERENCE.** Not a Terraform fix — noting it because it changes what "the deployment
came up green" proves. A healthy task does **not** prove `ENCRYPTION_KEY` is valid.

### Note 7 — REDIS_URL

**DATA.** Used for cache and as the Celery broker/result backend
(`config.py:63`, computed at `:234,240`). All Celery task payloads observed are UUID
strings only — `process_document(document_id)` (`tasks/document_processing.py:440`),
`run_rule_engine_pass(loan_file_id, run_id)` (`tasks/verification_rules.py:67`),
`update_needs_for_document(loan_file_id, document_id)` (`tasks/needs.py:92`),
`run_cross_source_pass` (`tasks/cross_source.py:32`). **No PII transits the broker.**

**INFERENCE.** Therefore Redis contents are low-sensitivity and the URL is not a
secret *by virtue of what it protects*. It becomes **SECRET** purely if the URL embeds
an ElastiCache AUTH token (`rediss://:TOKEN@host`), which is a Terraform decision. If
you enable AUTH — and you should, since it is also what gets you TLS — the URL is a
credential and needs a secret container. If you rely on security-group isolation
alone, it is CONFIG.

### Note 8 — SMTP is entirely unwired

**DATA.** A grep for `smtp_host`, `smtp_username`, `smtp_password` across `app/`
returns hits **only in `config.py`** — there is no mailer, no consumer, nothing
imports them.

**⇒ Do not provision an SMTP secret for staging.** All six settings are dead config.
When email lands, `smtp_password` becomes a SECRET and `smtp_username` CONFIG.

---

## Beyond config.py — what a security questionnaire would ask

**Password hashing — DATA.** bcrypt directly, auto-salted (`app/core/security.py:19,55`),
with a documented 72-byte input guard (`security.py:22,33-38`). Passlib deliberately
avoided (ADR referenced at `security.py:3-4`). No pepper, so no additional secret.

**Hardcoded credentials — DATA.** Two dev seed scripts contain literal passwords:

- `app/scripts/seed_dev_data.py:85` — a `_SEED_PASSWORD` literal (values redacted
  here; carries `# pragma: allowlist secret`, documented DEV-ONLY at `:80`), used
  at `:282`.
- `app/scripts/seed_dev.py:36,38-39` — `ADMIN_PASSWORD` / `PROCESSOR_PASSWORD`
  literals, **overridable via `SEED_ADMIN_PASSWORD` / `SEED_PROCESSOR_PASSWORD`**.

(The literal values are deliberately not reproduced in this document — that would
put them in a second file. Read the cited lines.)

**INFERENCE.** These are correctly scoped and clearly labelled, but they are a
questionnaire item and a real risk of a specific kind: if a seed script is ever run
against staging — plausible, since staging will want demo data — it creates accounts
with **publicly known passwords in a git repository**. `seed_dev.py` at least honours
env overrides; `seed_dev_data.py` does not (the literal is unconditional). Worth an
explicit "never run against a deployed environment" guard, or an `environment` check.

**Secrets in logs — DATA, executed both directions.** The structlog config
(`app/core/logging.py:22-41`) puts `format_exc_info` in the shared processors and
`dict_tracebacks` in the JSON branch. `structlog.tracebacks.ExceptionDictTransformer`
defaults to **`show_locals=True`** (verified on the installed structlog 26.1.0).

That combination *looks* dangerous, but the **ordering saves it**: `format_exc_info`
runs first, pops `exc_info`, and renders a plain string traceback — leaving
`dict_tracebacks` with nothing to do. Running the exact production processor list with
a secret in a frame local produced:

```json
{"event": "something_failed", "level": "error", ...,
 "exception": "Traceback (most recent call last):\n ... ValueError: decrypt failed"}
```

**No locals. The current configuration is safe.**

**⚠️ But it is safe by accident, not by intent.** Removing `format_exc_info` — the
natural edit for someone who wants structured tracebacks in JSON — flips it. Same
exception, same secrets, `format_exc_info` removed:

```json
"frames": [..., {"name": "boom", "locals": {
   "the_ssn_plaintext": "'123-45-6789'",
   "api_key_local": "'sk-ant-SUPERSECRET-abcdef123456'"}}]
```

**INFERENCE.** With `show_locals=True` and `locals_max_string=80`, any future traceback
through `encrypt_value` would serialize the `plaintext` local — a raw SSN — into
CloudWatch. The protection is one line-order away from failing, and nothing in the
repo pins it. Worth an explicit `ExceptionDictTransformer(show_locals=False)` and a
test, independent of C2.

**⚠️ Secrets leaked by *boot-time validation failure* — DATA, executed.** Pydantic
echoes the rejected input. Because `settings = get_settings()` runs at import
(`config.py:397`), a bad secret crashes with a traceback on stdout → CloudWatch:

```
jwt_secret_key
  String should have at least 32 characters [type=string_too_short, input_value='TOO-SHORT-SECRET', input_type=str]
encryption_key
  String should have at least 44 characters [type=string_too_short, input_value='SHORT-FERNET-KEY', input_type=str]
```

and a malformed DSN leaks the password through pydantic's middle-truncation:

```
database_url
  URL scheme should be ... [input_value='postgres-BAD-SCHEME://db...rSecretDbPw123@h:5432/d', ...]
```

**INFERENCE.** The exposure is bounded to values that *fail* validation — a correct
secret is never printed. But the failure cases are precisely the plausible ones (a
truncated key, a mis-pasted DSN, a Secrets Manager value with a trailing newline), and
the resulting CloudWatch entry contains real credential material with normal
log-group permissions. Treat a boot-validation crash as a **credential-rotation
event**, not just a config typo.

**Runtime error handling — DATA, clean.** `unhandled_exception_handler`
(`app/core/errors.py:58-74`) logs **metadata only** — `error_type`, `path`, `method`,
no `exc_info`, no body, no values — and returns a generic 500 envelope.
`http_exception_handler` (`:77-91`) passes through only the codebase's own safe
`detail` strings. The AI client logs at `app/ai/client.py:371,394` only; no prompt
content or key. `decrypt_value` never echoes the token (`encryption.py:91-93`).
`persist_snapshot` scans for raw PII before writing and refuses
(`persistence.py:13-19`).

**Health endpoints — DATA.** Defined in `app/main.py`; no settings values are exposed.

---

## Per-environment vs shared

| Secret | Per-env or shared? | Rotatable? |
|---|---|---|
| `ENCRYPTION_KEY` | **Must be IDENTICAL for every task reading a given database.** Per-environment *only* because staging has its own RDS. | **Effectively NO.** Single-key Fernet, no `MultiFernet`, no re-encryption path. Rotation = permanent loss of every stored SSN. |
| `JWT_SECRET_KEY` | Per-environment. | Yes, freely. Cost: all sessions invalidated (≤30d of refresh tokens). |
| `DATABASE_URL` | Per-environment. | Yes (RDS password rotation), if the secret and the DB rotate together. |
| `REDIS_URL` (if AUTH) | Per-environment. | Yes. |
| `ANTHROPIC_API_KEY` (if provider=anthropic) | Per-environment preferred. | Yes. |

**⚠️ The constraint you flagged, restated as the one thing Terraform must not do:**
generate `ENCRYPTION_KEY` with a resource that can be replaced while the RDS instance
survives. A `terraform destroy`/`apply` of the secret alone, a provider upgrade that
forces replacement of a `random_*` resource, or a second environment pointed at the
same database all produce the same outcome — **every borrower SSN already in that
database becomes permanently unreadable.** The key must outlive the Terraform state
that created it.

---

## Summary of what to change in C2

Findings only; no Terraform proposed, per your instruction.

1. **Drop `anthropic-api-key`** from the staging secret set if `AI_PROVIDER=bedrock` —
   the app requires it not to be set.
2. **Add `redis-url`** as a secret *only if* ElastiCache AUTH is enabled.
3. **`DATABASE_URL` must use `?ssl=require`, never `?sslmode=require`** — the latter is
   a `TypeError` at connect, not a no-op.
4. **Protect `ENCRYPTION_KEY` from regeneration** at the Terraform-resource level.
5. **Set the non-default CONFIG values** that otherwise silently behave like dev:
   `ENVIRONMENT`, `LOG_FORMAT=json`, `CORS_ALLOWED_ORIGINS`, `STORAGE_BACKEND=s3`,
   `AI_PROVIDER`, the three `BEDROCK_MODEL_*`, `S3_BUCKET`.
6. **`NEXT_PUBLIC_API_URL` is a `--build-arg`**, not a task-definition entry.
7. **The migration task needs `DATABASE_URL`** (`alembic/env.py:25`) — same secret.

Out-of-band, not C2: pin `show_locals=False`; boot-validate the Fernet key format;
guard the seed scripts against deployed environments; treat a boot-validation crash as
a credential-rotation event.
