# Why the staging migration failed twice with `%3B` in a secret that has no `%`

**Date:** 2026-08-12 · **Scope:** read-only on AWS. The migrate stage was not run
and no secret was written.

---

## Diagnosis

**Neither is stale. The log is current, the secret is current, and the secret has
always been correct.**

The `%3B` was never in Secrets Manager. It was **manufactured inside the container**
on every run: `settings.database_url` is a Pydantic `PostgresDsn`, and `str()` on it
percent-encodes the userinfo, turning the password's literal `;` into `%3B`. That
string was then handed to `config.set_main_option`, which stores it in a ConfigParser
using `BasicInterpolation` — and `%` is an interpolation escape.

So the traceback named configparser, the value in the traceback pointed at the
secret, and the actual bug was in `backend/alembic/env.py:25`. Re-running
`secrets --force` could never have fixed it, and did not change the stored value in
any meaningful way: **both** secret versions hold the identical, correct password.

**The only change needed is `env.py`.** Re-run migrate after deploying a rebuilt
image.

---

## DATA

### 1. Both log streams exist and belong to their own task

```
$ aws logs describe-log-streams --log-group-name /ecs/mbai-staging/api \
    --log-stream-name-prefix migrate/migrate/
[
  { "name": "migrate/migrate/065b8112507243f5a82e7b0b210238e4", "first": 1786571597185 },
  { "name": "migrate/migrate/27ef531afd76497e9748508d79ede931", "first": 1786572382576 }
]
```

Exactly two streams: exactly two migrate tasks have ever run. Converted, and merged
with the secret versions:

```
2026-08-12 17:43:43 -04  SECRET AWSPREVIOUS 6a799490   version created
2026-08-12 17:53:17 -04  TASK  065b81125072            first log event
2026-08-12 18:05:04 -04  SECRET AWSCURRENT  55d83461   version created
2026-08-12 18:06:22 -04  TASK  27ef531afd76            first log event
```

The second task's own stream is what you saw. **The log is not stale.**

Exact task timings put this beyond doubt — the second task was *created* 50 seconds
after the new secret version existed:

```
$ aws ecs describe-tasks --cluster mbai-staging --tasks 065b8112... 27ef531a...
065b8112...  created 17:52:45.629  pullStart 17:53:04.048  started 17:53:11.853  exit 1
27ef531a...  created 18:05:54.019  pullStart 18:06:08.491  started 18:06:17.145  exit 1
```

⚠️ `createdAt 18:05:54` is **after** `AWSCURRENT` was created at `18:05:04.866`. ECS
resolved the secret during provisioning, i.e. against the *new* version. So the
second task read the corrected secret and still produced the same traceback — which
is the fact that rules out both "stale log" and "stale secret".

**Both logged URLs are byte-identical, and both contain the `%`:**

```
stream 065b811250724   logged URL length: 154   contains % : True   char[46]: '%'   chars 44-50: 'l(%3BSS'
stream 27ef531afd764   logged URL length: 154   contains % : True   char[46]: '%'   chars 44-50: 'l(%3BSS'
```

### How the migrate stage picks a stream — no reporting bug

`scripts/deploy`:

```bash
stream="migrate/migrate/${task_id}"
awsx logs get-log-events --log-group-name "$group" --log-stream-name "$stream" … \
  || warn "No log stream for this task. …"
```

`task_id` is the id of the task **this invocation just started**
(`${arn##*/}`). There is no prefix search, no "most recent stream" fallback, and no
default. It either fetches that exact stream or fails and says so. **It cannot show a
different task's output.** Your suspicion was reasonable and the answer is no.

*(One cosmetic defect found and fixed while checking: the failure message was
truncated mid-sentence — "…the container died before it logged anything -- with ECS".
It now names the three causes that look identical at that moment.)*

### 2. What is stored, and in which version

```
$ aws secretsmanager list-secret-version-ids --secret-id mbai/staging/database-url
[
  { "v": "55d83461-…", "stages": ["AWSCURRENT"],  "created": "2026-08-12T18:05:04.866-04:00" },
  { "v": "6a799490-…", "stages": ["AWSPREVIOUS"], "created": "2026-08-12T17:43:43.830-04:00" }
]

$ … --version-stage AWSCURRENT  … | cut -c30-70
in:SbAjimmzz2YLl(;SScSKUWgW61Phia(Z@mbai-

$ … --version-stage AWSPREVIOUS … | cut -c30-70
in:SbAjimmzz2YLl(;SScSKUWgW61Phia(Z@mbai-
```

⚠️ **Both versions hold the literal `;`.** Not just the current one — the previous one
too. Fingerprinted (values never printed):

```
AWSCURRENT   urlLen=152 pwLen=32 pwHas%=False pwSha12=77892c47d94f
AWSPREVIOUS  urlLen=152 pwLen=32 pwHas%=False pwSha12=77892c47d94f
```

152 characters, no `%`, `;` at index 46. The logged URL is **154** characters with `%`
at index 46 — two characters longer, exactly the difference between `;` and `%3B`.

### 3. The task definition does not pin a version

```
$ aws ecs describe-task-definition --task-definition mbai-staging-migrate \
    --query 'taskDefinition.containerDefinitions[].secrets'
[[
  { "name": "DATABASE_URL",   "valueFrom": "arn:…:secret:mbai/staging/database-url-wLBNUH" },
  { "name": "ENCRYPTION_KEY", "valueFrom": "arn:…:secret:mbai/staging/encryption-key-wLBNUH" },
  { "name": "JWT_SECRET_KEY", "valueFrom": "arn:…:secret:mbai/staging/jwt-secret-key-IJw0rG" },
  { "name": "REDIS_URL",      "valueFrom": "arn:…:secret:mbai/staging/redis-url-pNYqBI" }
]]
```

Plain ARNs — no `:json-key:version-stage:version-id` suffix — so ECS injects
**AWSCURRENT**. Nothing is pinned. (Revision 1, registered 2026-08-11 20:09.)

### 5. The Terraform state password

```
terraform state password
  length            : 32
  contains %        : False
  non-alnum chars   : ( ;
  sha256 first 12   : 77892c47d94f
```

**No `%`.** And its fingerprint is identical to the password inside *both* secret
versions — `77892c47d94f` in all three places.

⚠️ **Timeline correction.** The `%3B` did **not** come from an earlier manual paste.
Whatever was pasted produced a value byte-identical to Terraform state, and both
stored versions still match it. No version of this secret has ever contained a `%`.

### The reproduction

Against the installed Pydantic and the exact production password:

```
pydantic 2.13.4
input  len: 152  has %: False  char[46]: ';'
str()  len: 154  has %: True   char[46]: '%'      chars 44-50: 'l(%3BSS'
INPUT == OUTPUT ? False

configparser.set with raw (literal ;)   : OK
configparser.set with str(PostgresDsn)  : ValueError: invalid interpolation syntax in
  'postgresql+asyncpg://mbai_admin:SbAjimmzz2YLl(%3BSScSKUWgW61Phia(Z@…' at position 46
```

Position 46, byte-identical to the production traceback.

---

## INFERENCE

- The `%` is produced by `str()` on a Pydantic URL type, not by any operator action,
  any AWS component, or any transport. **DATA** for the mechanism (reproduced above);
  **INFERENCE** only in attributing the container's failure to it — the container's
  logged string matches the reproduction exactly, and no other source of a `%` exists
  in the path.
- Both runs failed identically because the input was identical. `secrets --force`
  rewrote the same bytes, so nothing changed. **INFERENCE**, supported by the three
  matching fingerprints.
- The `;` in the password comes from `override_special = "!$&*()-_=+,.;~"` in
  `modules/data/main.tf`. That set deliberately excludes `%` — which prevented a
  *worse* version of this bug, and did not prevent this one, because `;` only becomes
  a `%` after Pydantic touches it. **DATA** (the charset) + **INFERENCE** (intent,
  though the file's comment states it).

---

## The fix

`backend/alembic/env.py` no longer routes the URL through Alembic's ConfigParser.

**Option (b), not (a).** Escaping (`"%" → "%%"`) would have worked and is a smaller
diff, but it leaves the trap armed: the next person to call `set_main_option` with a
URL reintroduces it, and the failure reappears in a container against a password
nobody can predict. Removing the ini hop removes the class of bug.

```python
DATABASE_URL = str(settings.database_url)          # no set_main_option
…
context.configure(url=DATABASE_URL, …)             # offline
connectable = create_async_engine(DATABASE_URL, poolclass=pool.NullPool)   # online
```

**The offline path was checked, as asked.** `run_migrations_offline` did read the ini
(`config.get_main_option("sqlalchemy.url")`); it now uses `DATABASE_URL` directly.
`run_async_migrations` used `async_engine_from_config(config.get_section(…))`, which
reads the same key back out — replaced with `create_async_engine`.

**Nothing is lost.** `alembic.ini` leaves `sqlalchemy.url` commented out and defines
no other `sqlalchemy.*` option, so the ini section contributed only the value
`env.py` had just injected.

⚠️ Interpolation stays **on** for the rest of the ini, which needs it — `script_location
= %(here)s/alembic` and `file_template = %%(year)d…`. Disabling it globally would have
broken those; that is a second reason (b) beats "turn interpolation off".

**Proved end to end** — a real offline migration with the production password shape and
no database:

```
$ DATABASE_URL='postgresql+asyncpg://mbai_admin:SbAjimmzz2YLl(;SScSKUWgW61Phia(Z@…' \
  alembic upgrade head --sql
INFO  [alembic.runtime.migration] Generating static SQL
BEGIN;
CREATE TABLE alembic_version (…);
…
```

Before the change this raised `ValueError` at import, before emitting anything.

### The test

`backend/tests/test_alembic_env.py` — 14 cases, all passing, ruff and mypy clean:

| test | covers |
|---|---|
| `test_url_reaches_the_engine_with_the_password_intact` | 5 passwords with `%`/`;`/parens survive into `create_async_engine` with the password unchanged |
| `test_pydantic_manufactures_the_percent` | pins the mechanism: `;` in → `%3B` out |
| `test_the_old_ini_route_would_still_break` | demonstrates the regression rather than describing it — each URL raises through a ConfigParser |
| `test_percent_followed_by_hex_is_still_lossy` | the known limit, below |
| `test_env_py_does_not_route_the_url_through_alembic_config` | source guard: no `set_main_option`, no `async_engine_from_config` |

### ⚠️ A known limit the tests pin, rather than paper over

The fix removes the *crash*. It does not make every `%` safe, because the corruption
for one shape happens below Alembic:

| password | Pydantic renders | SQLAlchemy parses back | |
|---|---|---|---|
| `pa%ss` | `pa%ss` | `pa%ss` | ok |
| `100%pure` | `100%pure` | `100%pure` | ok |
| `trailing%` | `trailing%` | `trailing%` | ok |
| `Sb(x;y)Z` | `Sb(x%3By)Z` | `Sb(x;y)Z` | ok |
| **`pa%3Bss`** | `pa%3Bss` | **`pa;ss`** | **LOSSY** |
| **`a%25b`** | `a%25b` | **`a%b`** | **LOSSY** |

Pydantic passes `%` through unchanged; SQLAlchemy percent-*decodes* the userinfo. A
password containing `%` followed by two hex digits therefore reaches the driver
altered, and the symptom is an authentication failure with no hint the password was
rewritten. **This is exactly why `override_special` excludes `%`** — so it is latent
for generated passwords and live only for a hand-set one.

---

## What you run next

The fix is in the image, so the image has to be rebuilt.

```bash
# 1. Rebuild and push. ECR tags are immutable, so bump the tag first:
#    edit infra/envs/staging/terraform.tfvars ->  image_tag = "staging-2"
./scripts/deploy staging images

# 2. Re-register the task definitions against the new tag.
./scripts/deploy staging phase1

# 3. Re-run the migration.
./scripts/deploy staging migrate
```

**Do not touch the secret.** It is correct, and has been correct since 17:43 today.
`secrets` will skip all four as already populated.

If you would rather not bump the tag, deleting the `staging` tag from both ECR
repositories and re-pushing works too — but the bump keeps the failed image
identifiable, which is worth more than the tidiness.

---

## Files changed

| | |
|---|---|
| `backend/alembic/env.py` | the fix, with the reasoning inline |
| `backend/tests/test_alembic_env.py` | new — 14 regression cases |
| `scripts/deploy` | comment stating the log stream cannot be another task's; truncated failure message completed |
