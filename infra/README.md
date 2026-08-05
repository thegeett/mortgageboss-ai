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
  shared/             ECR registry + its KMS key — SHARED across environments
  envs/
    dev/              the only environment C2 builds
    staging/          tfvars example only — proves the modules are portable
```

**`shared/` is a separate state on purpose.** The registry is shared across
environments — one repository set, distinguished by image *tag*, so the exact bytes
tested in dev are what get promoted. A shared resource therefore cannot be owned by
an environment's state: `envs/dev` is destroy-and-rebuild and ran with
`ecr_force_delete = true`, so it would have deleted every environment's images and
scheduled deletion of the CMK protecting them. See `shared/main.tf`.

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

# 2. The shared registry — once per ACCOUNT, not per environment.
cd ../shared
terraform init
terraform plan -out=shared.tfplan
terraform apply shared.tfplan

# 3. The environment. Now that the bucket exists, the S3 backend resolves.
cd ../envs/dev
terraform init
terraform plan -out=dev.tfplan     # ← read this before applying
terraform apply dev.tfplan
```

### Migrating an already-applied environment

**If `envs/dev` has never been applied, skip this entire section** — the greenfield
path above is all you need.

If it has, four changes here are replacement-forcing. Read all four before touching
anything; three of them break a running environment silently.

#### 1. The RDS master password ROTATES

`override_special` narrowed (to keep `#`, `?`, `%` and `:` out of `DATABASE_URL`),
and that attribute is `ForceNew` on `random_password`:

```
~ override_special = "!#$%&*()-_=+[]{}<>:?" -> "!$&*()-_=+,.;~" # forces replacement
Plan: 1 to add, 0 to change, 1 to destroy.
```

`aws_db_instance.password` reads it, and RDS applies a `MasterUserPassword` change
**immediately** regardless of `apply_immediately`. The `mbai/dev/database-url`
secret is populated out of band, so it keeps the old password and every task starts
failing authentication. **Re-populate the secret in the same maintenance step:**

```bash
cd infra/envs/dev
terraform apply                      # rotates the password
terraform state show random_password.db   # not an output by design; read it here
# then rebuild the URL and push it:
aws secretsmanager put-secret-value --secret-id mbai/dev/database-url \
  --secret-string 'postgresql+asyncpg://mbai_admin:NEW_PASSWORD@HOST:5432/mortgageboss?ssl=require'  # pragma: allowlist secret
```

#### 2. The RDS log group must be imported first

RDS already auto-created `/aws/rds/instance/mbai-dev/postgresql`, and Terraform
does **not** adopt existing resources — the apply fails with
`ResourceAlreadyExistsException`. Import before applying:

```bash
terraform import 'module.data.aws_cloudwatch_log_group.rds_postgresql' \
  /aws/rds/instance/mbai-dev/postgresql
```

#### 3. The ElastiCache parameter group is replaced

Its name changes from `mbai-dev` to `mbai-dev-redis7` (the family is now in the
name, because `aws_elasticache_parameter_group` has no `name_prefix` and a static
name plus `create_before_destroy` makes replacement impossible). The next apply
replaces the group and re-associates the replication group. That is one-time churn
with no data loss, but do it in a maintenance window: with
`apply_immediately = false` the association update is deferred, and a deferred
association plus a same-apply delete of the old group can surface
`InvalidCacheParameterGroupState`.

#### 4. Moving ECR into `infra/shared`

Move the state — **do not** just apply, which would destroy dev's repositories and
recreate them in shared's, discarding every image.

```bash
# Drop them from dev's state WITHOUT touching AWS.
cd infra/envs/dev
terraform state rm 'module.registry.aws_ecr_repository.this["mbai/api"]'
terraform state rm 'module.registry.aws_ecr_repository.this["mbai/frontend"]'
terraform state rm 'module.registry.aws_ecr_lifecycle_policy.this["mbai/api"]'
terraform state rm 'module.registry.aws_ecr_lifecycle_policy.this["mbai/frontend"]'

# Adopt them into shared's state.
cd ../../shared
terraform init
terraform import 'module.registry.aws_ecr_repository.this["mbai/api"]' mbai/api
terraform import 'module.registry.aws_ecr_repository.this["mbai/frontend"]' mbai/frontend
```

⚠️ **Before you plan, set `registry_kms_key_arn` in `shared/terraform.tfvars` to
dev's existing CMK.** ECR has no API to re-encrypt a repository, so the provider
marks `encryption_configuration` `ForceNew`: imported repositories carry dev's key
in state while the module would otherwise demand a newly created one, and the plan
becomes **`# must be replaced` on every repository**. Since `ecr_force_delete =
false` here, that destroy then *fails* on repositories holding images and leaves
the apply half-done. Setting the variable adopts them in place with no replacement:

```hcl
# shared/terraform.tfvars — migration only
registry_kms_key_arn = "arn:aws:kms:us-east-1:591554480818:key/THE-DEV-KEY-ID"
```

```bash
terraform plan   # expect: lifecycle policies only. NO repository replacement.
```

**While `registry_kms_key_arn` is set, the images are still protected by dev's CMK,
so `terraform destroy` in `envs/dev` schedules that key's deletion and makes every
image unpullable seven days later.** `terraform -chdir=infra/shared output
registry_key_is_owned_here` reports `false` for exactly as long as this is true.

To end that coupling, push fresh images to new repository names under the shared
key, repoint the ECS task definitions, and delete the old repositories. There is no
in-place path — that is an ECR limitation, not a Terraform one.

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
`secret_recovery_window_days = 0`.

⚠️ `terraform destroy` here **no longer deletes ECR repositories** — the registry
moved to `infra/shared`, which is exactly the point: a dev rebuild must not be able
to delete another environment's images.

⚠️ **That is not yet true of the image BYTES if you migrated an existing
environment.** While `shared/terraform.tfvars` sets `registry_kms_key_arn` to dev's
CMK (see migration step 4), the images are encrypted with a key that lives in
**this** state — so this destroy schedules that key's deletion and every image
becomes permanently unpullable when the window expires. Check before destroying:

```bash
terraform -chdir=../../shared output registry_key_is_owned_here   # must be true
```

If it reports `false`, either finish the migration off dev's key first, or accept
that the destroy costs every pre-migration image.

```bash
cd infra/envs/dev
terraform destroy
```

### Survives a destroy

- The **state bucket** and **lock table** (`bootstrap/`, both `prevent_destroy`).
- **The registry** — repositories and images live in `infra/shared`, outside this
  environment's state. Their KMS key does too **on a greenfield apply**; after a
  migration it is still this environment's CMK until the images are re-pushed (see
  the warning above and `registry_key_is_owned_here`).
- The **documents bucket `mbai-dev-documents-591554480818`** — hand-created in C0,
  **never managed by this Terraform**. It holds uploaded files. It is referenced
  by `data.aws_s3_bucket`, never created or imported, so `destroy` cannot touch it.

### Lost

- **All RDS data.** Re-seeding is manual.
- All CloudWatch logs.
- The KMS key enters a 7-day pending-deletion window. It is unusable but not yet
  gone, and it still bills — see the table below.

### Resources with destroy-time friction — and how each is handled

| Resource | Default behaviour | Handling |
|---|---|---|
| Secrets Manager secret | Deleted name stays **reserved** 7–30 days → re-apply fails on a name conflict | `recovery_window_days = 0` |
| ECR repository | Destroy **fails** if it still contains images | Not applicable — the registry is in `infra/shared`, and `ecr_force_delete = false` there so this friction is deliberate |
| RDS instance | Destroy **fails** when `deletion_protection` is on | `rds_deletion_protection = false` |
| RDS instance | Destroy **fails** demanding a snapshot name when `skip_final_snapshot = false` | `rds_skip_final_snapshot = true` |
| KMS **alias** | `destroy` leaves it **orphaned**, so the next apply fails `AlreadyExistsException` | `kms_create_alias = false` — no alias, no orphan |
| KMS key | Cannot be deleted immediately; 7–30 day window is mandatory | `kms_deletion_window_days = 7` (the AWS minimum). **Orphaned keys pending deletion for 7 days, ~$1/month each — no rebuild friction.** |
| State bucket / lock table | `prevent_destroy` | Intentional — not part of the environment destroy |

**Every one of these is configured so `terraform destroy` succeeds and the next
`apply` works with no console intervention.**

The KMS row deserves a note, because the obvious diagnosis is wrong. The deletion
window is **not** what blocks a rebuild — a fresh apply creates a *new* key without
complaint, whatever state the old one is in. The blocker was the **alias**:
`terraform destroy` schedules the key but leaves the alias behind
([hashicorp/terraform-provider-aws#35161](https://github.com/hashicorp/terraform-provider-aws/issues/35161)),
and `alias/mbai-dev` is then still taken, so the next apply dies with
`AlreadyExistsException` and needs a manual `aws kms delete-alias`.

So the fix targets the alias, not the key: `kms_create_alias = false` here. The
alias is console readability only — every consumer references the key by ARN
through the module outputs — so nothing functional is lost.

**The residue is cost, not friction.** Each destroy leaves one orphaned key
pending deletion for 7 days at roughly **$1/month prorated (~$0.23 per key)**,
and they accumulate if you rebuild repeatedly within a week. That is the accepted
trade. To reclaim one early:

```bash
aws kms cancel-key-deletion --key-id <id>   # then re-schedule, or reuse it
```

⚠️ **Staging sets `kms_create_alias = true`** — it is long-lived, so console
readability is worth more than a rebuild friction that will rarely be exercised.
When staging *is* rebuilt, the orphaned alias must be removed by hand:

```bash
aws kms delete-alias --alias-name alias/mbai-staging
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
- `kms_create_alias = true` — dev disables it only because it is rebuilt often
- `enable_vpc_endpoints = true`, `enable_nat_gateway = false`
- a **different** `vpc_cidr` — identical ranges cannot be peered
