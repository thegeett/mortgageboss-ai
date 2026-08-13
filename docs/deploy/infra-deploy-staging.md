# Deploying an environment — runbook

**Written from the staging deploy of 2026-08-12**, which is the only environment
deployed to date. Everything here was executed; nothing is theoretical.

**Reference environment:** `staging` · account `058190633983` · `us-east-1` ·
`staging.mortgageboss.ai`

**Time:** ~2 hours if nothing surprises you. Budget half a day the first time.
DNS propagation and RDS creation are the only unavoidable waits.

**Cost once running:** ~$166/month infrastructure, plus Bedrock at roughly $0.75
per loan file.

---

## 0 — Before you touch anything

**Log in to every SSO session.** They are separate; one login does not cover the
others.

```bash
aws sso login --sso-session mbai
AWS_PROFILE=mbai-staging-admin aws sts get-caller-identity
```

Must return the target account. If it returns anything else, stop.

⚠️ **The SSO session is ~4h20m.** RDS creation alone takes 10–15 minutes, and a
token that expires mid-apply fails partway, leaving half-created resources. Check
the clock before starting: `./scripts/sso-status --profile=mbai-staging-admin`.

**Know where you are.** `status` is read-only and safe at any moment:

```bash
./scripts/deploy staging status
```

⚠️ **`export AWS_PROFILE` for the session.** Several failures during this deploy
were nothing but a missing profile on a bare `terraform` command. The script sets
it; a manual `terraform apply` does not.

---

## The sequence

```bash
./scripts/deploy staging bootstrap        # state bucket
./scripts/deploy staging phase1           # ~89 resources, TLS and Cognito OFF
./scripts/deploy staging dns              # prints nameservers, then waits
#   ... add four NS records at the registrar ...
./scripts/deploy staging images           # buildx arm64, push, verify manifest
./scripts/deploy staging secrets          # derives both URLs, generates two keys
./scripts/deploy staging migrate          # alembic upgrade head, one-off task
./scripts/deploy staging phase2           # ACM + HTTPS + Cognito
./scripts/deploy staging bootstrap-admin  # first company + admin user
#   ... create the matching Cognito user ...
./scripts/deploy staging smoke
```

⚠️ **Never mix the script and raw `terraform` within one stage.** A `plan` from the
script followed by a hand-run `apply` produced an `Inconsistent dependency lock
file` error, because the script's `init` ran between them.

---

## ⚠️ The rule that cost the most time

**Images must be pushed BEFORE anything references the tag.**

ECR tags are immutable, so shipping new code means bumping `image_tag` in
`terraform.tfvars`. The correct order is always:

```
1. edit image_tag        →  staging-N+1
2. deploy … images       →  build and push that tag
3. deploy … phase2       →  re-register task definitions against it
4. run whatever needed the new code
```

**This was inverted twice**, both times producing:

```
CannotPullContainerError: ... :staging-N: not found
```

The failure is loud and immediate, so it costs minutes not hours — but it is
entirely avoidable.

> **Fix worth making:** have the `images` stage derive the tag from
> `git rev-parse --short HEAD`. Then the tag always exists before anything
> references it, and this whole class of error disappears.

**When you rebuild, remember what is already in the image.** Any script the deploy
runs as a one-off task — `alembic`, `bootstrap_admin`, `add_user` — lives in the
image. Writing it locally is not enough.

---

## 1 — Bootstrap

```bash
./scripts/deploy staging bootstrap
```

Creates the S3 state bucket every other directory stores its state in — which is
why this one directory uses **local state**.

`use_lockfile = true` was accepted by Terraform v1.15.8. If a future version
rejects it, the fallback is `dynamodb_table` plus restoring the lock table; never
set both.

**Bootstrap's `terraform.tfstate` is gitignored and stays that way.** It trips
detect-secrets on the S3 canonical owner id and a base64 provider-timeout blob,
neither of which is a secret. Recovery is one command, documented in
`infra/bootstrap/README.md`:

```bash
terraform import aws_s3_bucket.state mbai-tfstate-<account>
```

---

## 2 — Phase 1

```bash
./scripts/deploy staging phase1
```

89 resources. Read the plan — this is the first point at which anything is
billable. Confirm **no `aws_acm_certificate`** appears; the stage refuses if one
does, because ACM before delegation sits in `PENDING_VALIDATION` for its full
45-minute timeout.

10–15 minutes, mostly RDS.

**Afterwards the ECS services will fail.** No images exist yet. That is the
expected state.

### Four resources failed on the first attempt

| Failure | Cause |
|---|---|
| RDS parameter group | **em dash (U+2014)** in `description` |
| ElastiCache parameter group | same |
| `api_root_paths` listener rule | 6 path values against an ALB limit of **5** |
| Cost allocation tag | **management-account only** |

**The em dash is a repo-wide hazard.** AWS rejects it with a misleading
"non-printable control characters" message. It appears in 353 lines of this repo;
only the ones inside a `resource` block reach an AWS API. Comments and
`variable`/`output` descriptions are fine.

⚠️ A fifth resource carried the same em dash but was **never attempted** — its
dependency failed first. Fixing only the reported errors would have hit it on the
re-run. **When a class of error appears, sweep for it rather than fixing the
instances reported.**

**The ALB limit is 5 condition values per RULE**, counted across every condition
block — splitting them across blocks is the same violation.

⚠️ **The cost allocation tag is a MANUAL step.** From the **management** account:
Billing → Cost allocation tags → activate `Environment`. Until then, plus up to 24
hours, the budget filter matches nothing and **the alarm never fires while looking
correctly configured.**

---

## 3 — DNS delegation

```bash
./scripts/deploy staging dns
```

Applies nothing. Prints four nameservers, then polls until they answer.

At the registrar, add **four NS records**:

| Type | Host | Value |
|---|---|---|
| NS | `staging` | one nameserver each |

⚠️ **Host is `staging`, not `staging.mortgageboss.ai`.** Registrars append the
domain, so the full name creates records for
`staging.mortgageboss.ai.mortgageboss.ai`.

The apex stays at the registrar and is never delegated.

**Went live in 30 seconds** once the records existed. A flat `0/4` for 30 minutes
means the records are absent or wrong, not slow — genuine propagation shows
partial results.

---

## 4 — Images

```bash
./scripts/deploy staging images
```

⚠️ **`docker buildx` is required and may be missing.** This machine runs **Colima**,
which ships BuildKit inside the VM but not the client-side CLI plugin:

```bash
brew install docker-buildx
mkdir -p ~/.docker/cli-plugins
ln -sfn $(brew --prefix)/opt/docker-buildx/bin/docker-buildx ~/.docker/cli-plugins/docker-buildx
```

`linux/arm64` is **native** on Apple Silicon — full speed, no emulation. An x86
image on an ARM64 task definition dies with `exec format error` visible only in the
CloudWatch log stream, not in ECS service events. The stage verifies each pushed
manifest.

⚠️ **`NEXT_PUBLIC_API_URL` is baked at build time**, not read at runtime. Build it
wrong and the browser calls the wrong host with **nothing in the server logs**. The
stage derives it from `domain_name` in tfvars.

---

## 5 — Secrets

```bash
./scripts/deploy staging secrets
```

Two confirmations, neither asking for a value:

| Prompt | Answer |
|---|---|
| Use this DATABASE_URL? | **Y** — derived from state, password shown as `****` |
| Apply an AUTH token to the cluster now? | **Y** — defaults to N; modifies a live cluster |

The second polls for minutes until the replication group is `available` with
`AuthTokenEnabled: true`, then builds the Redis URL from the token in the same run.

⚠️ **The Fernet encryption key prints once. Have a password manager open.** It
encrypts `borrowers.ssn` and derives the PII match-hash key. Single-key Fernet, no
`MultiFernet`, no re-encryption script — **until B2 lands there is no rotation
path**, and losing it means every stored SSN is permanently unreadable. Store it
*outside* the AWS account, because the scenario it guards against is the secret
being gone while the database survives.

### Four bugs surfaced here, all now fixed

1. **`prompt_with_suggestion` wrote to stdout inside `$(...)`.** Command
   substitution swallowed the prompt into the variable and appended the pasted
   value to it. **No input could ever have been accepted.**
2. **`redis_url_scheme` is `rediss`, not `rediss://`** — the suggested URL was
   malformed in both branches.
3. **The ElastiCache AUTH token was never applied.** Terraform set
   `transit_encryption_enabled = true` while `AuthTokenEnabled` was false. A
   token-bearing URL would have been written happily and failed later **in the
   worker** as a `NOAUTH` error.
4. **The Fernet key was passed as `sys.argv[1]`** — visible in `ps`.

### Two spellings that fail silently

| Wrong | Right | Failure |
|---|---|---|
| `?sslmode=require` | `?ssl=verify-full` | `TypeError: connect() got an unexpected keyword argument 'sslmode'` — asyncpg has no such parameter, and RDS docs use the wrong spelling |
| `rediss://…` with no `ssl_cert_reqs` | `?ssl_cert_reqs=required` | redis-py verifies the certificate, kombu resolves to `CERT_NONE`. **Same URL, opposite posture.** |

### Do not percent-encode the RDS password

`override_special` deliberately excludes `/ @ " : # ? %` so the value is
paste-safe. SQLAlchemy percent-*decodes* userinfo on parse, so encoding is at best
a no-op and at worst silently wrong.

⚠️ **Verify any hand-copied password by fingerprint, never by eye.** A 32-character
string wraps in the terminal and a partial selection looks complete:

```bash
printf '%s' 'YOUR_COPY' | shasum -a 256 | cut -c1-12
```

Three copies failed this check before the derivation was automated.

---

## 6 — Migration

```bash
./scripts/deploy staging migrate
```

`alembic upgrade head` as a one-off task against the **empty** database. No seed,
no `pg_dump` — staging starts empty by design.

**This is the first thing that connects to RDS.** Three failure shapes:

| Symptom | Cause |
|---|---|
| Connection refused / auth error | the `database-url` value |
| Certificate verify failed | the CA bundle, or a `verify-full` hostname mismatch |
| **No output, hangs** | `uv run` reaching PyPI — `UV_NO_SYNC=1` missing |

That third one is nasty: with no NAT there is no route out, so it waits rather than
failing, and produces no log line.

### The bug that took two rounds to find

```
ValueError: invalid interpolation syntax in 'postgresql+asyncpg://…%3B…'
```

**The `%3B` was never in Secrets Manager.** `settings.database_url` is a Pydantic
`PostgresDsn`; calling `str()` on it percent-encodes the userinfo, turning the
literal `;` into `%3B` **inside the container**. `alembic/env.py` then handed that
to `configparser`, where `%` is an interpolation escape.

Two hypotheses were wrong before the real cause was found — a stale log and a stale
secret. What settled it: the failing task was created **50 seconds after** the
corrected secret version. It read the right value and failed anyway.

**Fixed** by bypassing the ini layer entirely and passing the URL straight to
`create_async_engine`, rather than escaping `%%` — which would have left the trap
armed for the next caller.

⚠️ **A residual hazard remains below this fix:** Pydantic passes `%` through and
SQLAlchemy percent-decodes userinfo, so a password containing `%` followed by two
hex digits reaches the driver **altered**, with an auth failure as the only symptom.
This is why the generated charset excludes `%`. Never hand-set a password
containing one.

---

## 7 — Phase 2: TLS and Cognito

```bash
./scripts/deploy staging phase2
```

Flips `enable_tls` and `enable_cognito` together — **always together**. An ALB
cannot attach `authenticate-cognito` to an HTTP listener, so the pair
(cognito = true, tls = false) fails at plan time rather than producing an
environment that looks authenticated and is not.

It edits `terraform.tfvars`, a tracked file, so the change appears in `git status`.

ACM validation takes a few minutes; Terraform waits.

### Verify in the plan before applying

- **Both listener rules** get `authenticate-cognito` at `order = 1` with `forward`
  at `order = 2` — not just the default action
- Port 80 becomes a **301 redirect**
- `session_timeout = 604800` (7 days)

⚠️ **The auth action must be on EVERY rule.** ALB rules are evaluated in priority
order and the default action only fires when nothing matches — so a specific
`/api/*` rule without an auth action **bypasses Cognito entirely** while the
default rule looks correctly configured. This was a real error in the C4 ticket,
caught before it shipped.

**After this, phase2 is your apply stage for everything.** `phase1` refuses once
the flags are true. The naming implies a one-time sequence; only the preconditions
differ.

---

## 8 — Users: two identities per person

**Cognito gets you past the load balancer. The app login is separate.** Both are
required, and they are different systems.

```bash
./scripts/deploy staging bootstrap-admin    # first company + admin, refuses if any user exists
./scripts/deploy staging add-user           # everyone after that
```

Both hash the password **locally** and send only the bcrypt hash, so no plaintext
credential enters CloudTrail, a task definition, or a log.

Then the Cognito side, which the script prints for you:

```bash
aws cognito-idp admin-create-user --user-pool-id <printed> \
  --username person@example.com \
  --user-attributes Name=email,Value=person@example.com Name=email_verified,Value=true
```

⚠️ **There is no signup route and no password-change endpoint in the application.**
Whatever password you set is permanent until someone builds a change flow. Tell
whoever you hand credentials to.

**Roles:** `ADMIN` vs `PROCESSOR` matters for exactly two surfaces —
`overlay_admin` and `validation_aid`. Uploading works either way.

⚠️ **`mfa_configuration` starts `OPTIONAL`** because enforcing MFA before any user
exists locks out the first account. **Flip it to `ON` once everyone is enrolled.**

---

## 9 — Smoke test

```bash
./scripts/deploy staging smoke
```

| # | Check | Expect |
|---|---|---|
| 1 | `https://<domain>` | **302** to Cognito |
| 2 | `https://<domain>/api/v1/health` | **302** |
| 3 | `http://<domain>` | **301** to HTTPS |
| 4–6 | login, upload, extraction row | manual |
| 7 | document in S3 | automated |

⚠️ **Check 2 is a security check, not a health check.** A **200** means the
`/api/*` rule is missing its auth action and **the API is open to the internet**.
Do not hand over the environment or upload a real file until it is fixed.

**Check 7 failing after a real upload** means `STORAGE_BACKEND` is not `s3` — so
documents are on ephemeral container disk that vanishes on task replacement, **with
no error at any point.**

Use `curl -i`, not `curl -I`. The health endpoints allow GET only; a HEAD returns
405, which looks like a failure and is not.

Worth doing **before** phase 2, while plain HTTP still works:

```bash
curl -i http://<alb-dns>/health/ready
```

`{"ready":true,"checks":{"database":"ok","redis":"ok"}}` confirms the whole data
path. After Cognito lands, every response is a 302 and this becomes impossible.

---

## Before handing over

- [ ] Remove or narrow the standing `AdministratorAccess` permission set → break-glass only
- [ ] Drop `BedrockDeveloper` — the worker task role invokes Bedrock, not a human
- [ ] Confirm `enable_execute_command = false` (a shell in a task holding borrower NPI)
- [ ] MFA **ON** for every Cognito user
- [ ] Activate the `Environment` cost allocation tag from the **management** account
- [ ] Bedrock invocation logging **off** — it writes raw documents to S3
- [ ] Error tracking scrubbed — an exception payload carrying `extracted_data` is the likeliest real leak
- [ ] Confirm the budget notification address receives mail

---

## When something fails

| Symptom | Where to look |
|---|---|
| **Task starts and dies immediately** | The **CloudWatch log stream**, not ECS service events. An architecture mismatch, an empty secret, and the `uv run` PyPI hang look identical from the console. |
| **`CannotPullContainerError`** | The tag does not exist. Run `images` before anything references it. |
| **Task stuck in `PENDING`** | Image pull. Check the ECR endpoint and that the tag exists. |
| **Nothing in the logs at all** | The container died before logging. With ECS Exec off, run the same image locally with the same environment. |
| **ACM stuck in `PENDING_VALIDATION`** | Delegation. `dig +short NS <domain>` — you need four `awsdns` answers. |
| **`No valid credential sources found`** | `AWS_PROFILE` missing on a bare `terraform` command. |
| **`Inconsistent dependency lock file`** | An `init` ran between plan and apply. Regenerate the plan. |
| **Apply fails partway** | Re-run. Terraform plans only the difference. |

**Rollback:** the ECS circuit breaker rolls back a failed deployment automatically.
For a bad image, bump `image_tag` back and re-apply — immutable tags mean the
previous image is exactly where it was.

⚠️ **`terraform destroy` is not a rollback here.** `rds_deletion_protection = true`,
`rds_skip_final_snapshot = false`, `secret_recovery_window_days = 30`, and the
documents bucket carries `prevent_destroy`. A destroy will refuse on the database,
and that is intended.

---

## What I would do differently next time

**Derive the image tag from the git SHA.** Two failures came from bumping the tag
and forgetting to build. `git rev-parse --short HEAD` removes the class entirely.

**Sweep for a class of error, not the instances reported.** The em dash sweep found
a fifth resource that had never been attempted because its dependency failed first.

**Test the data path before adding the auth wall.** `curl /health/ready` over plain
HTTP proved database and Redis connectivity in one call. After Cognito, that
becomes a 302 and you lose the ability to isolate the app layer.

**Verify hand-copied secrets by fingerprint.** Three password copies were wrong in
ways that looked right.

**Treat `is_production` with suspicion.** In this codebase it means
`environment == "production"` and nothing else, so every "not in production" guard
is **off in staging** — including the one that keeps `secure` off the refresh-token
cookie, which is a real defect in an HTTPS-only environment holding borrower files.
Prefer explicit allowlists.

**Expect the image to lag the code.** Any script run as a one-off task lives in the
image. Writing it locally is not enough.

---

## Known-open items

| | |
|---|---|
| **B2 — key rotation** | Until it lands, `ENCRYPTION_KEY` cannot be rotated. If it leaks, the choice is leaving it in place or destroying every stored SSN. |
| **Refresh-token cookie `Secure`** | `secure=settings.is_production` is False in staging. Real defect, own ticket. |
| **21 failing tests** | `backend/.env` sets `AI_PROVIDER=bedrock` while those tests assert the anthropic default. The suite is red by default in this worktree. |
| **Bedrock RPM 10** | Quota request pending. Extraction paces at ~8/min, so a full loan file takes minutes. Tell users this is a quota, not a bug. |
| **Document retention** | No lifecycle rule on the bucket, deliberately. A policy decision nobody has made. |
| **No password-change flow** | Whatever password you set is permanent. |
