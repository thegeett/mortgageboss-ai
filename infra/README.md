# `infra/` — Terraform for the AWS environments

Foundation only: network, registry, database, cache, keys, secret containers,
log groups, and a budget alarm. ECS services are ticket C3; DNS and TLS are C4.

```
infra/
  bootstrap/          state bucket + lock table — LOCAL state, applied once
  modules/
    network/          VPC, subnets, egress, security groups
    data/             RDS + ElastiCache + log groups
    registry/         ECR
    secrets/          KMS + Secrets Manager containers
  envs/
    dev/              the only environment C2 builds
    staging/          tfvars example only — proves the modules are portable
```

Modules are **environment-agnostic**. No module contains an account id, a region,
an environment name, or a `mbai-*` literal — `envs/<env>/terraform.tfvars` supplies
every one. The acceptance test:

```bash
grep -rniE '591554480818|us-east-1|\bdev\b|mbai-dev' infra/modules/    # must be empty
```

---

## Apply order

Every `apply` is run **by a human**, never by an agent.

```bash
# 1. Bootstrap — once, ever. Creates the state bucket and lock table.
cd infra/bootstrap
terraform init
terraform apply

# 2. The environment. Now that the bucket exists, the S3 backend resolves.
cd ../envs/dev
terraform init
terraform plan -out=dev.tfplan     # ← read this before step 3
terraform apply dev.tfplan
```

**`terraform plan` is the first point at which cost becomes real, and applying it
is the first point at which anything is billable.** Read the plan.

Both directories carry an account guard: a `precondition` on
`terraform_data.account_guard` fails the plan if the resolved credentials do not
match `var.aws_account_id`. It is a precondition rather than a `check` block
because a `check` only warns.

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

This environment is meant to be torn down between uses. That is why
`secret_recovery_window_days = 0` and `ecr_force_delete = true`.

```bash
cd infra/envs/dev
terraform destroy
```

### Survives a destroy

- The **state bucket** and **lock table** (`bootstrap/`, both `prevent_destroy`).
- **ECR images** — the repositories are destroyed, but see the note below.
- The **documents bucket `mbai-dev-documents-591554480818`** — hand-created in C0,
  **never managed by this Terraform**. It holds uploaded files. It is referenced
  by `data.aws_s3_bucket`, never created or imported, so `destroy` cannot touch it.

### Lost

- **All RDS data.** Re-seeding is manual.
- The KMS key enters a 7-day pending-deletion window (it is not immediately gone,
  but it is unusable).
- All CloudWatch logs.

### Resources with destroy-time friction — and how each is handled

| Resource | Default behaviour | Handling |
|---|---|---|
| Secrets Manager secret | Deleted name stays **reserved** 7–30 days → re-apply fails on a name conflict | `recovery_window_days = 0` |
| ECR repository | Destroy **fails** if it still contains images | `ecr_force_delete = true` |
| RDS instance | Destroy **fails** when `deletion_protection` is on | `rds_deletion_protection = false` |
| RDS instance | Destroy **fails** demanding a snapshot name when `skip_final_snapshot = false` | `rds_skip_final_snapshot = true` |
| KMS key | Cannot be deleted immediately; 7–30 day window is mandatory | `kms_deletion_window_days = 7` — the AWS minimum. **This is unavoidable.** |
| State bucket / lock table | `prevent_destroy` | Intentional — not part of the environment destroy |

**Every one of these is configured so `terraform destroy` succeeds with no console
intervention, with a single unavoidable exception:** the KMS key cannot be deleted
outright — AWS mandates a 7-to-30-day waiting period. `destroy` still *succeeds*
(the key is scheduled, not blocking), but the key and its alias linger. A re-apply
within that window fails on the **alias**, which is still taken. If you need to
rebuild inside 7 days, cancel the deletion first:

```bash
aws kms cancel-key-deletion --key-id <id>
```

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
- `ecr_force_delete = false`
- `enable_vpc_endpoints = true`, `enable_nat_gateway = false`
- a **different** `vpc_cidr` — identical ranges cannot be peered
