# `infra/` — Terraform for the AWS environments

Everything runs in **one AWS account**: staging, `058190633983`, `us-east-1`.

```
infra/
  bootstrap/          state bucket — LOCAL state, applied once, staging account
  modules/
    network/          VPC, subnets, egress, security groups
    data/             RDS + ElastiCache + log groups
    registry/         ECR
    secrets/          KMS + Secrets Manager containers
    compute/          ECS cluster, services, ALB, per-task IAM, Cognito
    dns/              Route 53 zone + ACM
    documents/        the documents bucket
  envs/
    dev/              ⚠️ REFERENCE TEMPLATE — never applied (see below)
    staging/          the ONLY deployed environment
```

> ### ⚠️ `envs/dev/` is a template, not a deployed environment
>
> Nothing in `envs/dev/` has ever been applied, and nothing is missing as a result.
> Local development runs against Docker Compose and calls Bedrock from the laptop,
> so it needs no AWS infrastructure at all.
>
> It exists to prove the modules take a different set of values without any module
> edit, and as a starting point for a future environment. It has **no `backend.tf`**
> — that described a state file which would never exist — and its `terraform.tfvars`
> carries placeholder account values.
>
> ⚠️ **Do not repoint it at staging's backend.** An accidental `apply` there would
> then write to staging's state.
>
> **`envs/staging/` is the real environment.**

### One account, one registry

ECR lives in `envs/staging`, alongside everything that pulls from it. It was
previously a separate `infra/shared` state in a second account, with a dedicated KMS
key and cross-account grant plumbing — a whole mechanism serving exactly one
consumer, and one carrying a nasty failure mode: a cross-account pull missing the
`kms:Decrypt` grant fails with an authorization error naming **KMS, not ECR**.

Production, when it exists, will be a separate account with its own registry. The
image-promotion trade-off that implies is recorded in
[`../docs/tickets/C4b-consolidate-staging-result.md`](../docs/tickets/C4b-consolidate-staging-result.md),
deliberately not pre-solved.

### State locking

S3 conditional writes (`use_lockfile = true`), **not** a DynamoDB table. There is no
lock table anywhere. Never set both — Terraform treats that as a conflict.

Modules are **environment-agnostic**. No module contains an account id, a region,
an environment name, or a `mbai-*` literal — `envs/<env>/terraform.tfvars` supplies
every one. The acceptance test:

```bash
grep -rniE '058190633983|us-east-1|\bstaging\b|\bdev\b|mbai-' infra/modules/   # comments only
```

---

## Apply order

Every `apply` is run **by a human**, never by an agent.

```bash
# ── 0. Log in. The staging profiles use the `mbai` SSO session.
aws sso login --sso-session mbai

# ── 1. Bootstrap — ONCE, EVER. Local state; creates the S3 state bucket.
cd infra/bootstrap
terraform init
AWS_PROFILE=mbai-staging-admin terraform apply

# ── 2. Staging, PHASE 1 — enable_tls = false, enable_cognito = false.
cd ../envs/staging
AWS_PROFILE=mbai-staging-admin terraform init      # picks up the S3 backend
AWS_PROFILE=mbai-staging-admin terraform plan -out=staging.tfplan
AWS_PROFILE=mbai-staging-admin terraform apply staging.tfplan

# ── MANUAL: delegate staging.mortgageboss.ai at Namecheap.
terraform output -json route53_name_servers        # the four NS values
dig +short NS staging.mortgageboss.ai              # four awsdns = delegation live

# ── 3. Staging, PHASE 2 — flip enable_tls and enable_cognito to true.
AWS_PROFILE=mbai-staging-admin terraform plan -out=staging-tls.tfplan
AWS_PROFILE=mbai-staging-admin terraform apply staging-tls.tfplan

# ── 4. Run the database migration ONCE, before the services are useful.
terraform output -raw migration_run_task_command   # prints the full invocation
# run it, then confirm it exited 0:
aws ecs describe-tasks --cluster <cluster> --tasks <task-arn> \
  --query 'tasks[0].containers[0].exitCode'

# ── 5. Reach the stack.
curl https://staging.mortgageboss.ai/health/live
```

**Three steps, one account.** There is no tooling-account bootstrap and no
`infra/shared` apply — both are gone.

`terraform init` in step 2 is a **first** init, not a migration: nothing was ever
applied under the previous layout, so there is no state to move.

⚠️ **Work through the pre-deploy checklist below BEFORE step 2.** Several of its
items cause failures that produce no useful log line — an empty secret, a missing
image tag, or an architecture mismatch.

⚠️ **On the first `terraform init`, confirm `use_lockfile` is accepted.** It was not
verified against the pinned Terraform (v1.15.8). If init rejects it, see the C4b
result doc for the `dynamodb_table` fallback.

Both `bootstrap` and `envs/staging` carry an account guard: a `precondition` on
`terraform_data.account_guard` fails the plan if the resolved credentials do not
match `var.aws_account_id`. A precondition rather than a `check` block, because a
`check` only warns.

---

## The two-phase staging apply

Terraform cannot complete staging in one run. ACM validates by DNS, and the zone's
nameservers must be live **at the registrar** before validation can succeed — but
those nameservers do not exist until the zone is created.

`enable_tls` in `envs/staging/terraform.tfvars` is the phase gate.

### Phase 1 — `enable_tls = false`

```bash
cd infra/envs/staging
terraform init
terraform plan -out=staging.tfplan
terraform apply staging.tfplan
```

Everything except the certificate, the HTTPS listener, the port-80 redirect, and
Cognito. Reachable on the ALB's own DNS name over HTTP.

### MANUAL — delegate the subdomain at Namecheap

The four nameservers **do not exist until phase 1 has been applied**:

```bash
terraform output -json route53_name_servers
```

At Namecheap, on `mortgageboss.ai` → *Advanced DNS*, add **four NS records** with
host `staging`, one per nameserver. The apex stays at Namecheap and is **never**
delegated to AWS.

Confirm delegation is live before phase 2:

```bash
dig +short NS staging.mortgageboss.ai
```

**Four `awsdns` nameservers means it is live.** Anything else means it is not.

### Phase 2 — `enable_tls = true`

Edit `terraform.tfvars`, then plan and apply again.

**If phase 2 runs before delegation propagates**, ACM sits in `PENDING_VALIDATION`
and Terraform blocks until its 45-minute timeout, then fails. Nothing is broken —
re-run once `dig` is clean.

Do **not** use `-target` to work around the ordering. It is a debugging escape
hatch; the phase boundary is a real property of the deployment.

---

## ⚠️ Pre-handover security checklist

Work through this before handing the environment to anyone. Every item is
something that is safe during build-out and **not** safe once real borrower files
are in it.

1. **Remove or narrow the standing `AdministratorAccess` permission set** on the
   staging account. It was needed to build the environment and is not needed to run
   it.
2. **Drop the `BedrockDeveloper` permission set.** The worker's **task role**
   invokes Bedrock — a human does not need to. A standing human Bedrock permission
   is an unused credential, and unused credentials are the ones nobody notices
   being used.
3. **Confirm `enable_execute_command = false`.** ECS Exec is a shell inside a task
   holding decrypted secrets and borrower NPI (ADR-372). It can be flipped on for a
   specific session and back off; it must not be left on.
4. **Confirm all four secrets are populated** — `database-url`, `jwt-secret-key`,
   `encryption-key`, `redis-url`. Check the LENGTH, not existence: Terraform creates
   the containers empty, and a task whose secret is empty fails to start with an
   unhelpful message.
5. **Confirm MFA is ON for every Cognito user**, and flip
   `cognito_mfa_configuration` from `OPTIONAL` to `ON`. It starts OPTIONAL only
   because enforcing it before any user exists locks out the first account.
6. **Confirm the budget alarm address actually receives mail.** An alarm nobody
   reads is not an alarm.

---

## ⚠️ Pre-deploy checklist

Every item here has caused, or would cause, a failure that is hard to diagnose from
CloudWatch alone. Work through it **before** applying the environment.

### 1. All three secrets populated — with real values, not empty strings

```bash
for s in database-url jwt-secret-key encryption-key; do
  printf '%-16s ' "$s"
  aws secretsmanager get-secret-value --secret-id mbai/dev/$s \
    --query 'length(SecretString)' --output text 2>/dev/null || echo "MISSING"
done
```

A task whose secret is **empty** fails to start, and the ECS event says only that
the essential container exited. Length, not existence, is the check — the container
is created by Terraform with no value at all.

Populate them per the section below. ⚠️ `encryption-key` is generate-once: rotating
it permanently destroys every stored borrower SSN.

### 2. Images pushed, with the tag the task definitions reference

```bash
terraform output -json container_image_uris
aws ecr describe-images --repository-name mbai/api      --image-ids imageTag=<tag>
aws ecr describe-images --repository-name mbai/frontend --image-ids imageTag=<tag>
```

A missing tag fails at launch with `CannotPullContainerError`, visible only in the
service events.

⚠️ **The images must be `arm64`.** The task definitions pin
`cpu_architecture = "ARM64"` to match what C1 actually built. An amd64 image fails
with `exec format error`, which appears **only in the CloudWatch log stream** — not
in the ECS console. Check with:

```bash
docker image inspect <image> --format '{{.Architecture}}'   # expect: arm64
```

### 3. ⚠️ Do NOT sync documents from anywhere

**Staging starts empty, deliberately.** There is no document sync and no database
seed: development documents are development artifacts and have no place in an
environment holding real borrower NPI.

The documents bucket is created empty by `modules/documents`, and the schema comes
from the migration task run against an empty RDS instance.

### 4. Migration run, and confirmed successful

```bash
terraform output -raw migration_run_task_command
```

Run it and check `exitCode` is `0`. Alembic deliberately does **not** run at
container start: three tasks starting at once would race on the same migration, and
a failure would crash-loop the service instead of failing one visible job.

⚠️ C2's `scripts/check-stack.sh` guard is **local-only** and does not protect this
path. Nothing stops the migration task running against the wrong environment except
reading the cluster name in the command.

### 5. Then, and only then, scale the services up

`desired_count` is 1 for all three. Bring them up only after 1–4 are green.

⚠️ **Raising the worker's count requires dividing `AI_REQUESTS_PER_MINUTE_BEDROCK`
by the new count.** That limiter is per-process: N tasks pace at N × the value,
against an account quota of 10 RPM.

---

## Populating the secrets

Terraform creates **empty containers**. It never writes a value — a value written
by Terraform lives in state, appears in plan diffs, and can be replaced by a
provider upgrade.

### 1. `encryption-key` — ⚠️ read this before generating anything

Generate **once**, and never regenerate while a database holding data survives:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

aws secretsmanager put-secret-value \
  --secret-id mbai/dev/encryption-key \
  --secret-string 'PASTE_THE_FERNET_KEY'
```

**Rotating this key permanently destroys every stored borrower SSN.** It encrypts
`borrowers.ssn` with single-key Fernet (`backend/app/core/encryption.py:58`,
`backend/app/models/borrower.py:88`) — there is no `MultiFernet` chain and no
re-encryption path in the repository. It also derives the HMAC key for PII
match-hashing (`backend/app/verification/snapshot/pii.py:134`), so rotation
invalidates every existing `match_hash`.

This is why no `random_password` generates it: the safest resource is the one that
does not exist. See `modules/secrets/README.md` for the full analysis.

**The destroy-and-rebuild workflow below is safe only because RDS is destroyed
alongside the secret.** No surviving database means no data to lose. **Never
destroy the two independently** — destroying the secret while the database
survives is the unrecoverable case.

*Ordering note:* ticket B2 adds `MultiFernet` and a re-encryption path. Until it
lands, an accidental regeneration is unrecoverable; after it, recoverable only if
the old key still exists. B2 lowers the severity, it does not remove the need.

### 2. `jwt-secret-key`

Rotating this only invalidates sessions (24h access, 30d refresh tokens) — nothing
durable is lost. There is no revocation table, so rotating it is in fact the only
way to mass-revoke sessions.

```bash
aws secretsmanager put-secret-value \
  --secret-id mbai/dev/jwt-secret-key \
  --secret-string "$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
```

### 3. `database-url` — mind the `?ssl=require`

Terraform generates the master password but deliberately does **not** output it,
so assemble the URL from the console or from state, then:

```bash
aws secretsmanager put-secret-value \
  --secret-id mbai/dev/database-url \
  --secret-string 'postgresql+asyncpg://mbai_admin:PASSWORD@HOST:5432/mortgageboss?ssl=require'  # pragma: allowlist secret
```

⚠️ **`?ssl=require`, never `?sslmode=require`.** The database enforces TLS
(`rds.force_ssl = 1`), and SQLAlchemy's asyncpg dialect does not translate libpq
parameter names — it forwards unknown query parameters as raw kwargs to
`asyncpg.connect()`, which has no `sslmode` parameter and no `**kwargs`. The
result is `TypeError: connect() got an unexpected keyword argument 'sslmode'` and
the app cannot connect at all. `?sslrootcert=` fails the same way.

Get the host from `terraform output rds_address`.

### 4. `redis-url` — only when `redis_auth_enabled = true`

With `redis_auth_enabled = false` (the dev setting) there is no `redis-url` secret:
the URL carries no credential, so it belongs in the task definition's
`environment[]` as CONFIG. It must still be:

```
rediss://HOST:6379/0?ssl_cert_reqs=required
```

⚠️ **Both parts matter.** Transit encryption is unconditional, so `redis://`
cannot connect. And the two Redis clients this application uses disagree on the
default certificate policy for `rediss://`:

| Client | Used by | default with no query param |
|---|---|---|
| redis-py 6.4.0 | cache (`backend/app/core/redis.py:39`) | **verifies** (`CERT_REQUIRED`) |
| kombu 5.6.2 | Celery broker and result backend | **does not verify** (`CERT_NONE`) |

Both read the same `REDIS_URL` (`backend/app/core/config.py:236`). Setting
`?ssl_cert_reqs=required` explicitly makes both verify.

---

## CONFIG the deployed task must set

Every one of these has a default that silently behaves like development
(`docs/secrets-audit.md`, Note 5). None is a secret; all belong in `environment[]`.

```
ENVIRONMENT=dev              default "development"
LOG_FORMAT=json              default "console"
CORS_ALLOWED_ORIGINS=[...]   default ["http://localhost:3000"] — frontend blocked if unset
STORAGE_BACKEND=s3           default "local"
S3_BUCKET=<documents bucket> boot-required when STORAGE_BACKEND=s3
AI_PROVIDER=bedrock          default "anthropic"
BEDROCK_MODEL_CLASSIFICATION=us.anthropic.claude-...
BEDROCK_MODEL_EXTRACTION=us.anthropic.claude-...
BEDROCK_MODEL_REASONING=us.anthropic.claude-...
REDIS_URL=rediss://...?ssl_cert_reqs=required
```

**`STORAGE_BACKEND` is the sharpest.** Left at `local`, the app starts happily and
writes uploaded documents to ephemeral container disk that vanishes on task
replacement — **with no error at any point**. Every other wrong default fails
loudly or visibly; this one does not.

`AI_PROVIDER=bedrock` requires no `ANTHROPIC_API_KEY` at all — the app's validator
requires it only when the provider is `anthropic`, and `AsyncAnthropicBedrock`
never sends it. There is deliberately no `anthropic-api-key` secret.

Also: **the migration task needs `DATABASE_URL`** — the same secret as the app, not
a separate one. Alembic reads it from the settings singleton
(`backend/alembic/env.py:25`).

⚠️ Certificate verification for the database is **not** a Terraform concern.
Reaching `verify-full` needs the `PGSSLROOTCERT` environment variable pointing at
an RDS CA bundle baked into the image; asyncpg reads that variable directly and it
cannot be expressed in the URL. **That is a C3 image and task-definition
requirement.** Without it, `?ssl=require` still encrypts but does not verify the
certificate or hostname.

---

## The destroy-and-rebuild workflow

⚠️ **Staging is NOT a destroy-and-rebuild environment.** The flags that made the
`envs/dev` template disposable are all inverted here — `rds_deletion_protection =
true`, `rds_skip_final_snapshot = false`, `secret_recovery_window_days = 30`,
`ecr_force_delete = false`. A `terraform destroy` will refuse on the database, and
that is intended.

The notes below describe what *would* happen, so the refusals are understood rather
than worked around.

### Survives a destroy

- The **state bucket** (`bootstrap/`, `prevent_destroy`).
- The **documents bucket** — `prevent_destroy` in `modules/documents`. It holds the
  only copy of every uploaded file, and the database stores keys rather than
  content.
- **ECR repositories**, because `ecr_force_delete = false` makes the destroy fail
  rather than discard image history.

### Lost

- **All RDS data**, if deletion protection is ever turned off to allow it. A final
  snapshot is taken (`rds_skip_final_snapshot = false`).
- All CloudWatch logs.
- The KMS key enters a 30-day pending-deletion window — unusable but not yet gone,
  and still billing.

### Resources with destroy-time friction — and how each is handled

Unlike the dev template, **most of this friction is deliberate here.**

| Resource | Behaviour | Handling |
|---|---|---|
| RDS instance | Destroy **fails** with deletion protection on | ✅ Intended. Turn it off explicitly, in its own change, if you truly mean it. |
| RDS instance | Demands a final snapshot name | ✅ Intended — `rds_skip_final_snapshot = false` leaves a recovery point. |
| ECR repository | Destroy **fails** while it holds images | ✅ Intended — `ecr_force_delete = false`. Emptying a repository is a deliberate console action. |
| Secrets Manager secret | Deleted name stays **reserved** 30 days → re-apply hits a name conflict | ✅ Intended — a mistaken destroy stays recoverable. |
| Documents bucket | `prevent_destroy` | ✅ Intended. |
| State bucket | `prevent_destroy` | ✅ Intended — destroying it orphans every resource. |
| KMS **alias** | `destroy` orphans it, so a re-apply fails `AlreadyExistsException` | `kms_create_alias = true` here (ADR-365), so a rebuild needs `aws kms delete-alias`. Accepted: staging is rebuilt rarely. |
| KMS key | 30-day deletion window is mandatory | Unavoidable. |

### Rebuild time

RDS and ElastiCache each take **5–10 minutes** to create; they run in parallel, so
a full rebuild is roughly **10–15 minutes**, plus secret population and re-seeding.

---

## ⚠️ Before staging

Staging is a copy of `envs/dev/*.tf` with `envs/staging/terraform.tfvars.example`
filled in — no module edit. See `envs/staging/README.md`. The settings that
**must** flip:

- `rds_multi_az = true`
- `rds_deletion_protection = true` — **staging holds real borrower NPI**
- `rds_skip_final_snapshot = false`
- `secret_recovery_window_days = 30` — 0 there makes a mistaken destroy unrecoverable
- `kms_create_alias = true` — dev disables it only because it is rebuilt often
- `enable_vpc_endpoints = true`, `enable_nat_gateway = false`
- a **different** `vpc_cidr` — identical ranges cannot be peered
