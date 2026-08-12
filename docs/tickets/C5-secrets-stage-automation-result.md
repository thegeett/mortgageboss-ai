# C5 — secrets stage: one command, no manual value preparation

**Date:** 2026-08-12
**Goal:** `./scripts/deploy staging secrets` populates all four secrets with no
value extracted, transcribed, or pasted by hand.
**Constraint honoured:** the stage was **not** run, **no secret was written**, and
the ElastiCache cluster was **not modified**. Only read-only AWS calls were made.

---

## The single command you run

```bash
./scripts/deploy staging secrets
```

Answer two confirmations:

| prompt | default | what it does |
|---|---|---|
| `Use this DATABASE_URL?` | **Y** | accepts the URL derived from Terraform state |
| `Apply an AUTH token to mbai-staging now?` | **N** | modifies the live cluster |

Everything else is automatic. Total interaction: two keystrokes, neither of them a
value.

⚠️ The second prompt defaults to **no** because it changes live infrastructure. The
first defaults to **yes** because declining it just means typing the URL yourself.

---

## 1 — DATABASE_URL is derived, not prompted

### What changed

`db_password_from_state` reads `module.data.random_password.db.result` out of
`terraform state pull`, and the branch assembles:

```
postgresql+asyncpg://<rds_username>:<password>@<rds_address>:5432/<rds_database_name>?ssl=verify-full
```

from the three existing outputs plus the state-read password. The operator sees only:

```
  Derived from Terraform state -- nothing to paste:

    postgresql+asyncpg://mbai_admin:****@mbai-staging.c45amqau4ov5.us-east-1.rds.amazonaws.com:5432/mortgageboss?ssl=verify-full

  Password read from module.data.random_password.db (32 characters).
  It is never displayed, never placed on a command line, and is written
  through a 0600 file that this run deletes.

  Use this DATABASE_URL? [Y/n]
```

**Why this was needed:** pasting the password was the actual failure mode — three
attempts lost to terminal wrapping and clipboard handling, and the only symptom was a
validator rejection that could not say which character was wrong.

### `terraform output` is not used for the password

Deliberately. It is not an output, and making it one would expose it to
`terraform output`, to CI logs, and to anything that reads the output map.
`terraform state pull` reads the value that is *already* in state — which is why the
state bucket is encrypted, versioned and access-blocked.

### Fallbacks preserved

| situation | behaviour |
|---|---|
| state read fails (not initialised, no such resource, bad JSON) | warns, falls back to the paste prompt |
| operator answers `n` | falls back to the paste prompt |
| either way | **every existing validator still runs** on the final value |

`db_password_from_state` is silent on every failure path and returns 1, so a failure
degrades to the old behaviour rather than stopping the stage.

### ⚠️ A bug the harness caught, worth recording

The first implementation piped state into `python3 - <<'PY' … PY`. That is wrong and
it **can never work**: the heredoc *becomes python's stdin*, so `json.load(sys.stdin)`
reads the program text's EOF and the piped state never arrives. It failed silently —
the function returned empty and the stage would have fallen back to prompting forever,
looking like "state has no password" rather than "the code is broken".

Fixed by passing the extractor with `-c`. The program is a fixed string with no secret
in it, so argv is the right place for it; the *state* is what must stay on stdin. The
comment in the source says so, to stop it being "tidied" back.

---

## 2 — The Redis AUTH token is applied, then the URL is derived

### The five states, and what each does

| terraform wants | cluster has | behaviour |
|---|---|---|
| token | **no token** | offer to apply one, then derive the URL — **today's case** |
| token | **has token** | ⚠️ **never rotates**; falls back to prompting |
| no token | no token | derive a credential-less URL, `[Y/n]` |
| no token | has token | warn, prompt |
| any | unreadable | warn, prompt — a failed describe must not block the stage |

### Applying it

1. **Token generation** — 32 characters from RFC 3986 **unreserved** characters only
   (`A–Z a–z 0–9 - . _ ~`), via `secrets.choice`. That single choice satisfies three
   constraints at once:
   - ElastiCache forbids `/`, `"`, `@`, `%` — none are in the alphabet.
   - None is special to a shell, so quoting cannot mangle it.
   - Unreserved characters need **no percent-encoding** in a URL userinfo, so the
     token drops into `rediss://:TOKEN@host` verbatim. Same reasoning as the RDS
     password's `override_special`, and it removes encoding as a category of error.

   ~193 bits of entropy.

2. **Explicit confirmation**, showing the replication group id, the endpoint, and the
   `False -> true` transition. Defaults to **no**.

3. **The modify call**:

   ```
   aws elasticache modify-replication-group --cli-input-json file://<0600 file>
   ```

   with `{"ReplicationGroupId", "AuthToken", "AuthTokenUpdateStrategy":"ROTATE",
   "ApplyImmediately":true}`. Key names taken from `--generate-cli-skeleton`.

   ⚠️ **`--cli-input-json`, not `--auth-token` on the command line.** A token passed
   as an argument is visible in `ps` to every user on the machine for the life of the
   call. This is the whole reason for the JSON file.

   **ROTATE, not SET** — the AWS CLI documents `SET` as *"allowed only after ROTATE"*,
   and this group has never had a token.

4. **Polling** until `Status == available` **and** `AuthTokenEnabled == true`, every
   15s, with progress lines and a 900s timeout
   (`DEPLOY_REDIS_AUTH_TIMEOUT_SECONDS`). This takes minutes.

5. **The URL is built from the token in the same run** and written. The token is never
   printed, never written to disk outside the 0600 request file, and exists only in
   the process and in Secrets Manager.

### ⚠️ If the poll times out

The token **was** submitted but this run cannot confirm it took effect, so it writes
nothing and says so. The generated token is then discarded. If the rotation did
complete, the cluster holds a token nobody knows — and the recovery is another
rotation, which the next run will *decline* to do automatically (see below) and will
ask you to supply the URL for. The message says all of this rather than leaving it to
be discovered.

### ⚠️ Never rotates an existing token

If `AuthTokenEnabled` is already true, the stage does **not** rotate. The existing
token is not knowable — ElastiCache never returns it — and rotating to a
script-generated one would silently break every consumer still using the old one. It
explains that and asks for the URL instead. **Verified by test A below.**

---

## 3 — Idempotency

Unchanged. The pre-existing skip is untouched:

```bash
if [ -n "$existing" ]; then
  if [ "$FORCE" != "1" ]; then
    note "skip  $key ($id) -- already has a value, $existing bytes"
    continue
  fi
  …confirm per secret, with the extra encryption-key warning…
fi
```

A re-run writes nothing for any secret that already holds a value. With `--force` it
still confirms per secret. Because the skip happens *before* the branch, a re-run also
does **not** re-read state and does **not** touch the cluster.

---

## Argv, log and terminal safety

| value | how it moves | argv exposure |
|---|---|---|
| RDS password | `state pull` → pipe → `python -c` (static program) → shell variable | none |
| DATABASE_URL | shell variable → `put_secret` → 0600 file → `--secret-string file://…` | none |
| Redis token | `python` stdout → shell variable → 0600 JSON → `--cli-input-json file://…` | none |
| Fernet key | python stdout → variable → **stdin** of the validator → `put_secret` | none |
| JWT secret | python stdout → variable → `put_secret` | none |

**Also fixed here:** the Fernet validation used
`python -c '…Fernet(sys.argv[1])' "$fkey"`, which put the encryption key in the
process command line. It now arrives on stdin via the `printf` builtin.

**Proved, not asserted.** A recording wrapper on `aws` and `python3` captured the full
argv of every external process while a sentinel secret flowed through each path:

```
--profile p --region r secretsmanager put-secret-value --secret-id mbai/staging/database-url --secret-string file:///…/payload.49285
--profile p --region r elasticache modify-replication-group --cli-input-json file:///…/redis-auth.json
-c import sys; sys.stdin.read()
-

RESULT: CLEAN - sentinel never appeared in any argv
RESULT: CLEAN - generated token never in argv
```

Only paths and static program text. Additionally: shell variables are not visible in
`ps` and none of these are exported, so they are not in `/proc/<pid>/environ` either;
`db_password_from_state` runs `set +x` defensively so it cannot be expanded under
xtrace; and the redacted display is built **from parts** with a literal `****`, so the
password is never in the displayed string at any point — a redaction that can fail
open is not a redaction.

Temp files live in the run's own `mktemp -d`, are written under `umask 077`, are
removed immediately after use, and the exit trap removes the directory on Ctrl-C.

---

## Verification

No stage was run. Everything below is a scratch harness outside the repo, or a
read-only AWS call.

```
bash -n scripts/deploy                     OK
bash -n scripts/deploy-lib.sh              OK
./scripts/deploy --help                    OK
terraform fmt -recursive -check            clean
validate: bootstrap / envs/staging / envs/dev   Success (all three)
```

**Harness 1 — derivation, redaction, token generator (13 assertions, all pass).**
Against a *mock* state file containing a decoy `random_password`:

```
  ok  picks module.data.random_password.db
  ok  did NOT pick the decoy
  ok  redacted contains no part of the password
  ok  redacted has the **** marker
  ok  real URL passes the validator
  ok  failed state read -> rc=1, empty output
  ok  10 tokens all exactly 32 chars
  ok  no char outside A-Za-z0-9._~- (and none of / " @ %)
  ok  successive tokens differ
  ok  token needs no percent-encoding (unreserved only)
  ok  derived redis URL passes validator
  ok  token survives SQLAlchemy-style parse unchanged
```

**Harness 2 — the real branch, all five states (16 assertions, all pass).** The
`redis-url` branch body is extracted from `scripts/deploy` and executed with stubs, so
this exercises the shipped code, not a copy:

```
A. cluster ALREADY has a token   ok did NOT rotate · ok prompted · ok wrote the typed URL
B. no token, confirmed           ok rotated · ok did NOT prompt · ok wrote token-bearing URL
C. no token, declined            ok did NOT rotate · ok died · ok wrote nothing
D. no token wanted or present    ok did NOT rotate · ok did NOT prompt · ok wrote credential-less URL
E. cluster unreadable            ok did NOT rotate · ok prompted
F. derived URL declined          ok did NOT rotate · ok prompted instead
```

**Harness 3 — argv leakage.** Output above.

**Against real state (read-only), password never printed:**

```
length            : 32
sha256 first 12   : 77892c47d94f      <- matches the fingerprint from the diagnosis
MATCH: extractor returns the real master password
derived URL: VALIDATOR ACCEPTED
SQLAlchemy parses it : postgresql+asyncpg mbai-staging.… mortgageboss {'ssl': 'verify-full'}
password round-trips : yes
```

That last line is the end-to-end proof: the password the extractor pulls, embedded in
the derived URL, parses back out of it byte-identically under the SQLAlchemy the
application actually uses.

---

## Assumptions

1. **The state read is authoritative.** `module.data.random_password.db.result` is the
   password RDS currently has. It would not be if someone rotated it in the console
   without applying Terraform — in that case Terraform would show a drift on the next
   plan, and the derived URL would be wrong. Not detectable from here.
2. **`terraform state pull` requires an initialised backend.** The stage already calls
   `require_outputs`, which runs `terraform output`, so this holds by the time the
   branch runs. If it does not, the read fails and the stage prompts.
3. **The resource is addressed by type and name, not by module path** — any
   `random_password` named `db`. Correct for every environment in this repo; it would
   pick the wrong one if a second `random_password.db` were ever added elsewhere in the
   same state.
4. **`ROTATE` is the right strategy for a first application.** Taken from the AWS CLI's
   own help text (*"SET — allowed only after ROTATE"*), not from memory. Not executed,
   so not empirically confirmed.
5. **Adding a token does not break current consumers**, because nothing is deployed in
   this environment yet — no images, services at 0/1. Stated in the confirmation
   prompt so it is re-evaluated if that changes.
6. **`AuthTokenEnabled` is a sufficient success signal.** Combined with
   `Status == available`, that is what the API exposes; there is no way to test the
   token itself without connecting from inside the VPC.

---

## What is still manual, and why

- **The Fernet key must be stored outside AWS.** The stage prints it once and waits for
  Enter. That cannot be automated away: there is no rotation path until B2, so a human
  has to put it somewhere.
- **Cognito users** and the **pre-handover checklist** — unchanged, out of scope.
