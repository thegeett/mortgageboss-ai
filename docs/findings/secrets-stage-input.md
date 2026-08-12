# Why `./scripts/deploy staging secrets` rejects a valid DATABASE_URL

**Date:** 2026-08-12 · **Scope:** read-only diagnosis. No secret was written, the
secrets stage was not run, and no script was modified.

---

## Verdict

**The hypothesis is refuted.** The stage does *not* read `DATABASE_URL` from the
environment, and your paste *did* reach the `read`. The stage is interactive.

**The stage has a genuine bug.** `prompt_with_suggestion` writes its prompt to
**stdout**, and it is called inside a command substitution:

```bash
url=$(prompt_with_suggestion "DATABASE_URL" "$suggestion")
```

Command substitution captures stdout. So every line of the prompt is swallowed into
`$url` instead of reaching your terminal, and your pasted value is **appended to the
prompt text**. The validator then sees `"\n  DATABASE_URL\n  suggested…\n…" + your URL`,
which does not start with `postgresql+asyncpg://`, and rejects it.

Both prompted secrets are affected — `database-url` and `redis-url`. There is no
input you can type that makes the current code accept anything. `jwt-secret-key`
and `encryption-key` are generated, not prompted, and are unaffected.

---

## 1. What the code actually does

### How the values are obtained

`scripts/deploy:604-616` — an interactive `read -r`, no prompt string, no `-s`, no
environment variable, no flag, no file:

```bash
prompt_with_suggestion() {
  local label="$1" suggestion="$2" value
  info ""
  info "  ${C_BOLD}${label}${C_RESET}"
  info "  suggested (from terraform output):"
  info "    ${suggestion}"
  info "  Press Enter to accept, or paste the corrected value."
  printf '  %s> ' "$label"
  read -r value
  [ -z "$value" ] && value="$suggestion"
  printf '%s' "$value"
}
```

`info()` is `printf '%s\n' "$*"` — **stdout** (`deploy-lib.sh:25`). So is the
`printf '  %s> '`. The only thing that should be on stdout is the last line.

Called at `scripts/deploy:639` and `:659` as `url=$(prompt_with_suggestion …)`.

### The rejection conditions

`validate_database_url` (`scripts/deploy:526-566`), in order — all `case` matches:

| # | Rejects when the URL | Reason given |
|---|---|---|
| 1 | contains `sslmode=` | asyncpg has no `sslmode` kwarg; `TypeError` at connect |
| 2 | contains `sslrootcert=` | same failure; the CA path comes from `PGSSLROOTCERT` |
| 3 | does not start `postgresql+asyncpg://` | a bare `postgresql://` selects psycopg2 |
| 4 | has no `?ssl=` or `&ssl=` | asyncpg defaults to `prefer` — encrypts, verifies nothing |
| 5 | contains `<`…`>` | an unfilled `<PASSWORD>` placeholder |
| — | is not `ssl=verify-full` | **warning only, accepted** |

**Condition 3 is the one that fired.** Not because your URL was wrong.

### The `...` in the error is not a truncation

It is a literal in the error template (`scripts/deploy:551`):

```bash
die "DATABASE_URL must start with postgresql+asyncpg:// -- got: ${url%%://*}://..."
```

`${url%%://*}` strips from the **first** `://` in the captured blob — which is the
one inside the swallowed *suggested* line. So the message renders as
`…    postgresql+asyncpg://...`. The `...` is the template's own ellipsis. **Not a
bug in the suggestion; a symptom of the capture bug.**

### `got:` looking empty

Also a symptom. `${url%%://*}` still contains the embedded newlines from the
swallowed prompt, so everything after `got: ` is pushed onto the following lines.

---

## 2. Reproduced exactly

Offline, with a piped paste, sourcing the real functions:

```
### WHAT ENDED UP IN $url (od, first 200 bytes):
0000000   \n           D   A   T   A   B   A   S   E   _   U   R   L  \n
0000020            s   u   g   g   e   s   t   e   d       (   f   r   o
0000040    m       t   e   r   r   a   f   o   r   m       o   u   t   p
0000060    u   t   )   :  \n                   p   o   s   t   g   r   e
0000100    s   q   l   +   a   s   y   n   c   p   g   :   /   /   m   b
…
### length of $url = 392        <- your 132-char URL plus 260 bytes of prompt
```

producing, byte for byte, what you saw:

```
STOPPED DATABASE_URL must start with postgresql+asyncpg:// -- got:
  DATABASE_URL
  suggested (from terraform output):
    postgresql+asyncpg://...
```

Why it *looked* like it was waiting without a prompt: the preamble and the
"RDS master password" hazard are printed by `stage_secrets` itself, outside the
command substitution, so they display normally. Everything from
`prompt_with_suggestion` onward is captured. Your typing echoed because the terminal
driver echoes it, not because the script printed anything.

---

## 3. The fix (NOT APPLIED — your call)

One change, `scripts/deploy:604-616`: send every prompt byte to stderr, leave only
the value on stdout.

```bash
 prompt_with_suggestion() {
   local label="$1" suggestion="$2" value
-  info ""
-  info "  ${C_BOLD}${label}${C_RESET}"
-  info "  suggested (from terraform output):"
-  info "    ${suggestion}"
-  info "  Press Enter to accept, or paste the corrected value."
-  printf '  %s> ' "$label"
+  # The caller captures this function's STDOUT, so the prompt must go to STDERR
+  # or it is swallowed into the variable AND prepended to the typed value.
+  {
+    info ""
+    info "  ${C_BOLD}${label}${C_RESET}"
+    info "  suggested (from terraform output):"
+    info "    ${suggestion}"
+    info "  Press Enter to accept, or paste the corrected value."
+    printf '  %s> ' "$label"
+  } >&2
   read -r value
   [ -z "$value" ] && value="$suggestion"
   printf '%s' "$value"
 }
```

Verified in a scratch harness: prompt visible, `$url` is exactly the 132-byte pasted
value, validator accepts.

Two things worth fixing in the same pass, both found while tracing this:

- **`redis_url_scheme` is `rediss`, not `rediss://`.** See §5 — the suggested Redis
  URL is malformed as a result.
- **`read` without `-e`.** With readline off, a long pasted URL cannot be edited with
  arrow keys. Cosmetic, but this is a 130-character paste.

---

## 4. What to run instead, right now

Since the stage cannot accept input until it is fixed, populate the two prompted
secrets directly. This is exactly what the stage would do — same secret ids, same
`file://` technique so the value never appears in `ps` output or shell history.

### 4a. DATABASE_URL

Real values, confirmed from `terraform output` today:

| | |
|---|---|
| host | `mbai-staging.c45amqau4ov5.us-east-1.rds.amazonaws.com` |
| database | `mortgageboss` |
| user | `mbai_admin` |
| secret id | `mbai/staging/database-url` |

```bash
export AWS_PROFILE=mbai-staging-admin AWS_REGION=us-east-1

umask 077

# -s: no echo. The password never appears on screen, in argv, or in history.
read -r -s -p 'RDS master password: ' PW; echo

# printf is a shell builtin, so the assembled URL never becomes a process
# argument either. No trailing newline -- asyncpg would carry one into the DSN.
printf '%s' \
  "postgresql+asyncpg://mbai_admin:${PW}@mbai-staging.c45amqau4ov5.us-east-1.rds.amazonaws.com:5432/mortgageboss?ssl=verify-full" \
  > /tmp/dburl

aws secretsmanager put-secret-value \
  --secret-id mbai/staging/database-url \
  --secret-string "file:///tmp/dburl"

rm -f /tmp/dburl; unset PW
```

⚠️ **Do not build this with a heredoc.** A heredoc appends `\n`, and asyncpg carries
it into the DSN. `printf '%s'` is what the stage's own `put_secret` uses, for exactly
this reason.

Verify without printing the value:

```bash
aws secretsmanager get-secret-value --secret-id mbai/staging/database-url \
  --query 'SecretString' --output text | wc -c
```

### 4b. Confirm your password copy first

From `terraform state pull`, `module.data.random_password.db` — derived values only:

| | |
|---|---|
| length | **32** |
| first two | `Sb` |
| last two | `(Z` |
| sha256, first 12 hex | `77892c47d94f` |
| non-alphanumeric characters present | `(` and `;` |

Check your copy without either of us echoing it:

```bash
printf '%s' 'YOUR_COPY' | shasum -a 256 | cut -c1-12     # must print 77892c47d94f
```

⚠️ **Your copy is probably wrong in a specific way.** You said the password contains
`(`, `;` **and `)`**. It does **not** contain `)`. It contains only `(` and `;`. If
you added a `)`, or percent-encoded one that is not there, the password will not
match — and the failure appears as an authentication error from Postgres at task
start, not here.

---

## 5. Redis

### The AUTH token has NOT been applied

```json
{ "auth": false, "tls": true, "status": "available" }
```

`AuthTokenEnabled: false`, `TransitEncryptionEnabled: true`. Meanwhile
`terraform output redis_requires_auth_token` is **`true`** — so Terraform created the
`redis-url` **secret** on the assumption that a token exists, and the task definition
injects `REDIS_URL` from it.

**Your instinct was right:** a `REDIS_URL` carrying a token would be accepted by the
validator, written to Secrets Manager, and then fail at connection time — in the
**worker**, as a `NOAUTH`/authentication error, with nothing in the secrets stage to
explain it.

### The stage does not apply the token

`grep -n "modify-replication-group\|auth-token" scripts/deploy scripts/deploy-lib.sh`
→ **no matches**. It only prints:

> "Apply the AUTH token to the replication group out of band first."

It assumes you have already done it. It does not check, and `AuthTokenEnabled` is
false, so nothing today would catch the mismatch.

### Applying the token

Constraints, quoted from `aws elasticache modify-replication-group help`:

- printable ASCII only
- **16–128 characters**
- **cannot contain `/`, `"`, `@`, or `%`**
- `--auth-token` must be given together with `--auth-token-update-strategy`
- strategies: `ROTATE` (default), `SET` ("allowed only after ROTATE"), `DELETE`

Because this group currently has **no** token, the initial application is `ROTATE`;
`SET` is rejected until a rotation has happened.

```bash
export AWS_PROFILE=mbai-staging-admin AWS_REGION=us-east-1

# 32 chars, no / " @ % — and no shell metacharacters to fight with
TOKEN=$(LC_ALL=C tr -dc 'A-Za-z0-9!*()-_=+.,;~' </dev/urandom | head -c 32)

aws elasticache modify-replication-group \
  --replication-group-id mbai-staging \
  --auth-token "$TOKEN" \
  --auth-token-update-strategy ROTATE \
  --apply-immediately
```

Then wait for `available` and confirm the flag actually flipped:

```bash
aws elasticache describe-replication-groups --replication-group-id mbai-staging \
  --query 'ReplicationGroups[0].{auth:AuthTokenEnabled,status:Status}'
```

⚠️ Do not proceed while `auth` is still `false`. ⚠️ `$TOKEN` is in your shell history
and environment — populate the secret in the same session, then `unset TOKEN`.

### ⚠️ The suggested Redis URL the stage builds is malformed

`terraform output -raw redis_url_scheme` returns **`rediss`** — the bare scheme. The
output's own description says "Always rediss://", but the value
(`modules/data/outputs.tf:42`) is `value = "rediss"`. The stage concatenates as if
the `://` were included (`scripts/deploy:651,656`):

| branch | builds | result |
|---|---|---|
| auth on | `"${scheme}:<AUTH_TOKEN>@…"` | `rediss:<AUTH_TOKEN>@master…` — **missing `//`** |
| auth off | `"${scheme}${endpoint}…"` | `redissmaster.mbai-staging…` — **scheme fused to host** |

Both are rejected by `validate_redis_url`, which requires `rediss://*`. So it fails
safe rather than writing garbage — but pressing Enter to accept the suggestion can
never work. Second bug, same stage.

### The URL shape the validator accepts

Endpoint confirmed today: `master.mbai-staging.ltiayc.use1.cache.amazonaws.com`

```
rediss://:TOKEN@master.mbai-staging.ltiayc.use1.cache.amazonaws.com:6379/0?ssl_cert_reqs=required
```

Note the **empty username** — `rediss://:token@host`, colon immediately after `//`.
Redis AUTH with a single token has no username.

```bash
umask 077
printf '%s' "rediss://:${TOKEN}@master.mbai-staging.ltiayc.use1.cache.amazonaws.com:6379/0?ssl_cert_reqs=required" > /tmp/redisurl
aws secretsmanager put-secret-value --secret-id mbai/staging/redis-url --secret-string "file:///tmp/redisurl"
rm -f /tmp/redisurl; unset TOKEN
```

`?ssl_cert_reqs=required` is mandatory: redis-py (cache) defaults to verifying,
kombu (Celery broker) resolves to `CERT_NONE`. Same URL, opposite posture.

---

## 6. Percent-encoding — you do not need it

Tested against the SQLAlchemy actually installed (`backend/.venv`, **2.0.50**):

| form | `make_url(...).password == original` |
|---|---|
| `aB3%28xY%3Bz%299Qw` (encoded) | **True** |
| `aB3(xY;z)9Qw` (literal) | **True** |

Both work. SQLAlchemy percent-*decodes* the userinfo when parsing a URL string, so an
encoded value round-trips and a literal one passes through untouched. `(`, `)` and
`;` are RFC 3986 sub-delims and are legal unencoded in a userinfo component.

Both forms also pass the deploy validator (checked: literal, encoded, `ssl=require`,
`sslmode=`, unfilled placeholder).

**Use the literal password.** The generator was designed for it —
`modules/data/main.tf:106`:

```hcl
override_special = "!$&*()-_=+,.;~"
```

with the comment: *"the set below is narrowed further so the value is genuinely safe
to paste into a URL without percent-encoding"*. `/ @ " space : # ? %` are all
excluded deliberately.

⚠️ **`%` is the trap that makes encoding risky, and it is why the charset excludes
it.** SQLAlchemy decodes on parse, so a literal `%` in a password is silently
mangled — verified: `has%20space` parses as `has space`. Since the generated password
can never contain `%`, encoding buys nothing and adds a way to get it subtly wrong
(a half-encode, or a double-encode, produces a wrong password whose only symptom is
an auth failure at task start).

**Secrets Manager round-trip:** the value is stored and returned verbatim — no
encoding transformation. Writing via `file://` (as above and as the stage does) also
keeps it off the command line, so no shell mangling either.

---

## 7. Order to run

1. `printf '%s' 'YOUR_COPY' | shasum -a 256 | cut -c1-12` → expect `77892c47d94f`.
   Fix your copy first; remember there is **no `)`** in it.
2. Populate `database-url` (§4a), literal password, no encoding.
3. Apply the Redis AUTH token (§5), confirm `AuthTokenEnabled: true`.
4. Populate `redis-url` (§5) with the token URL.
5. `./scripts/deploy staging status` — all four secrets should read *populated*.
   `jwt-secret-key` and `encryption-key` are generated by the stage and are still
   empty; they are unaffected by this bug, so once the fix in §3 is applied you can
   run `./scripts/deploy staging secrets` and it will skip the two you populated by
   hand and generate the other two.

⚠️ Step 5 is the reason to fix the stage rather than do all four by hand: the
`encryption-key` path validates the generated Fernet key by construction and prints
it once with the "store this outside AWS" warning. Generating it by hand skips both.

---

## Files referenced

| | |
|---|---|
| `scripts/deploy:604-616` | `prompt_with_suggestion` — the bug |
| `scripts/deploy:639,659` | the two capturing call sites |
| `scripts/deploy:526-566` | `validate_database_url` |
| `scripts/deploy:568-586` | `validate_redis_url` |
| `scripts/deploy:651,656` | the malformed Redis suggestion |
| `scripts/deploy-lib.sh:25` | `info()` writes to stdout |
| `infra/modules/data/outputs.tf:42` | `redis_url_scheme = "rediss"` |
| `infra/modules/data/main.tf:106` | `override_special` — why no encoding is needed |
