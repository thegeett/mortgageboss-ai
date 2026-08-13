# C5 — bootstrap the first admin, and add users afterwards

**Date:** 2026-08-12
**Outcome:** two one-off provisioning tools plus a local hashing helper, wired into
`scripts/deploy`. **Nothing was run. Nothing was created in AWS.**

---

## The command sequence

```bash
# 1. The FIRST company and admin. Refuses if any user already exists.
./scripts/deploy staging bootstrap-admin

# 2. Every user after that.
./scripts/deploy staging add-user
```

`bootstrap-admin` prompts for:

```
  Admin email:
  Admin first name:
  Admin last name:
  Company name:
  Company slug (lowercase, url-safe):
  Password:            <- read -s, hashed HERE, never sent
  Confirm:
```

then shows a summary, asks one `[y/N]`, and runs the task. `add-user` is the same
with a `Role (ADMIN or PROCESSOR)` prompt and a `Company slug (must already exist)`.

⚠️ **Then create the matching Cognito user**, or the account cannot be reached at
all — the database row gets you past the *application's* login, not past the ALB:

```bash
POOL_ID=$(terraform -chdir=infra/envs/staging output -raw cognito_user_pool_id)
aws --profile mbai-staging-admin cognito-idp admin-create-user \
  --user-pool-id "$POOL_ID" --username you@example.com \
  --user-attributes Name=email,Value=you@example.com Name=email_verified,Value=true \
  --desired-delivery-mediums EMAIL
```

The `bootstrap-admin` stage prints this command with the pool id filled in when it
finishes.

---

## Why a hash

The values reach the container through `aws ecs run-task --overrides`. That is
visible in `describe-tasks` for about an hour and recorded permanently in the
CloudTrail `RunTask` event. A **bcrypt hash at cost 12 with a random salt** is not
meaningfully sensitive in either place. A plaintext password would be.

So the password is hashed on your machine and only the hash travels. This buys the
security property of wiring a Secrets Manager secret into the task definition, at
the cost of a script instead of a Terraform change and an apply.

---

## What was built

| File | |
|---|---|
| `backend/app/scripts/_provisioning.py` | shared guards: required-env, email normalization, bcrypt validation, environment allowlist |
| `backend/app/scripts/bootstrap_admin.py` | the first company + admin; refuses against a populated database |
| `backend/app/scripts/add_user.py` | every user after that; refuses unknown/deleted company, duplicate email, bad role |
| `scripts/hash-password` | local bcrypt hashing via the app's own `hash_password` |
| `scripts/deploy` | `bootstrap-admin` and `add-user` stages |
| `backend/tests/test_bootstrap_admin.py` | 28 tests |
| `backend/tests/test_add_user.py` | 33 tests |

**Email normalization is a guard, not a nicety.** Both scripts put the address
through `email_validator` — the same library `LoginRequest.email: EmailStr` uses —
and store the `.normalized` form (domain lowercased, local part untouched). The
login lookup is an exact string match against a value pydantic has already
normalized, so storing whatever the operator typed means an admin created as
`Admin@Example.COM` is a row that the *same string*, typed at the login form,
never finds. With no signup route, no password reset, and `bootstrap_admin`
refusing to run twice, that mistake is close to unrecoverable. Normalizing at the
write is what makes the two agree by construction; it also rejects a malformed
address before anything is written.

### `bootstrap_admin.py`

Reads six required variables, no defaults:
`BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD_HASH`,
`BOOTSTRAP_ADMIN_FIRST_NAME`, `BOOTSTRAP_ADMIN_LAST_NAME`,
`BOOTSTRAP_COMPANY_NAME`, `BOOTSTRAP_COMPANY_SLUG`
plus `BOOTSTRAP_ALLOWED_ENVIRONMENTS` (default `staging`).

Creates one `companies` row (`is_active=true`) and one `users` row
(`role=ADMIN`, `is_active=true`, `hashed_password` = the supplied hash, stored
verbatim — the script never re-hashes).

**Guard (a) — refuses against a populated database.**

```python
existing_users = await db.scalar(select(func.count()).select_from(User))
if existing_users:
    raise ProvisioningError("Refusing to bootstrap: this database already contains …")
```

It counts **every** user including soft-deleted ones. A soft-deleted row still means
this database has been used, and "bootstrap" stops being an accurate description of
what the tool would do.

**Guard (b) — an explicit environment allowlist.**

⚠️ **Deliberately not `settings.is_production`.** That predicate is
`environment == "production"` and nothing else, so **every "not in production" guard
in this codebase is OFF in staging** — including `seed_dev_data.py`'s. That is the
reason this guard exists, so reusing the predicate would have reproduced the bug it
is defending against. The allowlist names what it permits and refuses everything
else, including an environment name nobody anticipated. An empty allowlist permits
nothing (fails closed).

Both guards live inside `bootstrap()`, not in `main()`, so no caller — test, future
script, REPL — can reach the writes without passing them.

### `add_user.py`

Same shape, minus guard (a). Required: `ADD_USER_EMAIL`, `ADD_USER_PASSWORD_HASH`,
`ADD_USER_FIRST_NAME`, `ADD_USER_LAST_NAME`, `ADD_USER_ROLE`,
`ADD_USER_COMPANY_SLUG`, plus `ADD_USER_ALLOWED_ENVIRONMENTS` (default `staging`).

Three refusals of its own:

- **Unknown or soft-deleted company slug** — it will not create one. A typo'd slug
  silently making a second company is the failure to prevent, and it bites harder
  than it looks: `authenticate_user` does not check the company at all, so a user
  attached to a stray one logs in perfectly well and sees an empty, wrong tenant.
  The lookup filters `deleted_at IS NULL`: companies carry `SoftDeleteMixin` and are
  soft-deleted rather than removed, so a decommissioned tenant's slug still resolves
  and would produce exactly that outcome.
- **Duplicate email** — email is **globally unique, not per tenant**, so a collision
  with a user in a *different* company is possible. Reported as a refusal naming that
  fact, rather than surfacing as an `IntegrityError` traceback from the driver. The
  comparison is **case-insensitive**, unlike the unique index on `users.email`:
  email is case-insensitive in practice, so an exact-match guard would wave through
  `Admin@example.com` alongside `admin@example.com` — and so would Postgres —
  leaving two rows for one human, possibly in two different companies.
- **Bad role** — `ADMIN` or `PROCESSOR`, either case, no default. Defaulting would
  mean a typo silently producing either the less privileged role (confusing) or the
  more privileged one (dangerous).

### `scripts/hash-password`

Prompts twice with `read -s`, confirms they match, and calls the application's **own**
`hash_password` and `validate_password_strength` from `backend/.venv` — not a
reimplementation, so the hash is by construction one `authenticate_user` will verify
and the policy is the one the app enforces (≥ 8 characters, ≤ 72 bytes).

Prompts go to **stderr**, the 60-character hash to **stdout** with no trailing
newline, so `HASH=$(./scripts/hash-password)` captures exactly the hash.

---

## Security properties, verified rather than asserted

**No provisioning value reaches argv.** `ps` shows a process's full command line to
every user on the machine; it does not show its environment. So the run-task request
is built by `jq` reading **`env.NAME`**, never `--arg`, into a `0600` file, and passed
as `--cli-input-json file://…`.

Proved with recording wrappers on `jq` and `aws`:

```
jq ARGV: -n {overrides:{containerOverrides:[{name:env.ONEOFF_CONTAINER,environment:[
     {name:"BOOTSTRAP_ADMIN_PASSWORD_HASH",value:env.BOOTSTRAP_ADMIN_PASSWORD_HASH}, …
aws ARGV: ecs run-task --cli-input-json file:///…/req.json

clean: [$2b$12$SENTINELhash…] never in argv
clean: [sentinel@example.com] never in argv
clean: [Sentinel Company]     never in argv
clean: [correct horse battery staple] never in argv
```

Only the jq *program* (which contains variable **names**, not values) and a file path.

**The password never leaves the machine.** In `scripts/hash-password`, `$password`
appears only in shell builtins — `read`, `[`, and one `printf … |` into the
interpreter's **stdin**. It is never an argument to an external command, never
written to disk, never echoed.

**Nothing sensitive is printed.** These logs sit in CloudWatch for 30 days. Success is
one line:

```
created company example, user admin@example.com
created user processor@example.com as processor in example
```

Tested: the hash, the password, and even the substring `$2` are absent from the
success line and from every refusal message.

> ⚠️ **One judgement call to flag.** The brief said both "not the email's domain"
> and 'report only "created company <slug>, user <email>"'. Those conflict; I
> followed the explicit format line and the email **is** printed, because it is the
> identifier you need to correlate the run. If you would rather it were not, the
> output is isolated in `success_line()` in both scripts — a one-line change with a
> test already asserting the exact string.

**Malformed hashes fail before any write.** Two checks, because neither alone
suffices: structural (prefix `$2a$`/`$2b$`, exactly 60 characters) *and* a
`bcrypt.checkpw` probe. `checkpw` alone accepts a **truncated** hash and returns
`False`, which would create an account nobody can ever log into with no clue why; the
length check alone would accept a right-shaped but unparseable string. Tests assert
that after a rejection, **zero companies and zero users exist** — no orphaned company
left behind.

---

## Verification

```
ruff check      All checks passed!      (5 new files)
ruff format     clean
mypy            Success: no issues found in 5 source files
bash -n         scripts/deploy, scripts/hash-password
./scripts/deploy --help   lists both new stages
pytest          53 new tests pass (25 bootstrap + 28 add-user)
```

The new tests cover every item asked for, against a real Postgres with
transaction-rollback isolation:

| | |
|---|---|
| guard (a) | refuses when a user exists; refuses when the only user is **soft-deleted**; nothing left behind |
| guard (b) | refuses `development` / `production` / `prod` / `test` / empty; refuses **before** touching the database; accepts a multi-entry list; an empty allowlist permits nothing; the message names the variable |
| malformed hash | plaintext password, wrong algorithm, truncated, too long, right-shape-unparseable, empty — each rejected with zero rows written |
| authentication | the created user is authenticated by the app's own `authenticate_user`, not by `verify_password` in isolation |
| output hygiene | success line and refusal messages contain no hash, no password, no `$2` |
| add-user | unknown slug refuses and creates nothing; a **soft-deleted** company's slug refuses; duplicate email refuses; cross-company duplicate refuses; a duplicate **differing only in case** refuses; bad role refuses; both roles settable; adds to a populated database |
| email normalization | the stored address is exactly what `LoginRequest.email` yields for the same input; a mixed-case address created by either script **logs in** through the app's own `authenticate_user`; a malformed address refuses with zero rows written |

Also verified: `$2a$` hashes are accepted (a legitimate bcrypt variant), and the
supplied hash is stored **verbatim** rather than re-hashed.

### ⚠️ 21 pre-existing failures in the full suite, unrelated to this change

`pytest` over the whole backend reports `21 failed, 4053 passed`. All 21 are in
`tests/ai/` and `tests/tasks/test_document_processing.py`, and all are caused by this
worktree's `backend/.env` setting `AI_PROVIDER=bedrock` while those tests assert the
`anthropic` default:

```
E  AssertionError: assert 'bedrock' == 'anthropic'
```

Forcing the provider makes them all pass:

```
$ AI_PROVIDER=anthropic pytest tests/ai/ tests/tasks/test_document_processing.py -q
118 passed in 9.90s
```

Nothing in `tests/ai` or `tests/tasks` references the new modules. Pre-existing and
environmental, not caused here — but worth its own fix, since it makes the suite red
by default in this worktree.

---

## Assumptions

1. **The migrate task definition is the right vehicle.** It already has
   `DATABASE_URL` injected via `secrets[]`, runs the same image, and lands in the
   subnets that have the interface endpoints. Only its `command` is overridden. If a
   future change removes `DATABASE_URL` from it, both stages break loudly at task
   start rather than silently.
2. **The log stream shape is `migrate/<container>/<task-id>`** — the awslogs stream
   prefix is a property of the task definition, not of the command, so overriding the
   command does not change it.
3. **An applied Cognito user pool is required.** Both stages refuse otherwise.
   Creating an admin account that can log in to an environment with no
   authentication wall in front of it is a state worth refusing to produce. This
   was specified for `bootstrap-admin`; I applied it to `add-user` on the same
   reasoning. The check reads the **`cognito_user_pool_id` output**, not
   `enable_cognito` in `terraform.tfvars`: tfvars is what the operator intends to
   apply, and editing it to `true` before running `phase2` would satisfy a tfvars
   check while the load balancer still has no `authenticate-cognito` action. The
   output is `var.enable_cognito ? ...[0].id : null`, so a non-empty value means
   the pool — and the listener rule gated on the same variable — really exists.
   The refusal still quotes the tfvars value, because that is usually the clue to
   what the operator expected.
4. **The container runs as root and `uv run` works** — the same invocation the migrate
   task uses today, with `UV_NO_SYNC=1` already set on the task definition.
5. **The allowlist is a fixed list in `scripts/deploy`** (`PROVISIONING_ENVIRONMENTS`,
   currently `staging`), **not `$ENV_NAME`.** Passing the target back as its own
   allowlist would make the guard tautological — `./scripts/deploy production
   bootstrap-admin` would set the allowlist to `production` and then pass it. The
   deploy script also refuses a non-permitted target up front, before prompting
   for a password, so the container-side check stays as defence in depth against a
   mismatch between the target directory and the container's `ENVIRONMENT`.
   Widening it means editing `scripts/deploy` in a reviewed commit.

---

## What is still manual

- **The Cognito user** — a separate identity, printed as a ready-to-run command at the
  end of `bootstrap-admin`.
- **MFA** — turn `cognito_mfa_configuration` to `ON` once users are enrolled; it starts
  `OPTIONAL` because enforcing it before any user exists locks out the first account.
- **Password changes** — there is no password-reset or change endpoint in the
  application. The password set here is the password until one is built. `add-user`
  will not overwrite an existing user, by design.
