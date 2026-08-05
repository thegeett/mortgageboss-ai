# C2 — Terraform: network, ECR, RDS, ElastiCache, KMS, Secrets

**Branch:** `bedrock_integration`
**Depends on:** C0, C1
**Blocks:** C3 (ECS services), C4 (DNS/TLS), C5 (deploy)
**Target account:** Dev — `591554480818`, `us-east-1`

---

## Why this exists

C1 produced images. They need somewhere to live and something to run against: a VPC, a
registry, a database, a cache, keys, and secret storage. This ticket builds that foundation as
code so staging is a second workspace rather than a second afternoon of clicking.

**Dev first, deliberately.** Same modules will target staging later. Getting the rough edges
wrong in an account with no client data is much cheaper.

## ⚠️ This ticket creates real, billable AWS resources

Roughly **$75–95/month** if left running (itemised at the end). Every `apply` step below must be
run **by the user**, not by you. Write the code, run `validate` and `plan`, show the plan, and
stop.

---

## Ground rules

- **Never run `terraform apply`.** Write, `init`, `validate`, `fmt`, and `plan` only. The user
  applies.
- **Never commit `.tfstate`, `.tfvars` containing secrets, or `.terraform/`.**
- No hardcoded account IDs, ARNs, or passwords in `.tf` files — variables and data sources.
- Tag every resource: `Project=mortgageboss-ai`, `Environment=dev`, `ManagedBy=terraform`.
- Pin the AWS provider to a `~> 5.x` version. Pin `required_version >= 1.9`.
- **Add an account guard.** Use `data.aws_caller_identity.current` with a
  `lifecycle { precondition }` or a `check` block asserting the account is the one in
  `var.aws_account_id`. Quotas were once requested against the wrong account in this project;
  applying Terraform to the wrong account is the same class of error with worse consequences.
  Take the id as a variable — never hardcode it in a `.tf` file.

---

## Tasks

### 1. Layout

```
infra/
  bootstrap/          # state bucket + lock table, local state, applied once
    main.tf
    README.md
  modules/
    network/
    data/             # RDS + ElastiCache + subnet groups
    registry/         # ECR
    secrets/          # KMS + Secrets Manager
  envs/
    dev/
      main.tf
      variables.tf
      terraform.tfvars    # non-secret values only, committed
      backend.tf
      outputs.tf
```

Modules take variables and return outputs; `envs/dev` wires them together. Staging later is a
sibling directory with different variable values — **no module should contain the word `dev`.**

### 2. Bootstrap (the chicken-and-egg)

Terraform's S3 backend needs a bucket that Terraform hasn't created yet. `infra/bootstrap/`
solves it with **local state**, applied once:

- S3 bucket `mbai-tfstate-591554480818` — versioning on, SSE-KMS, public access blocked
- DynamoDB table `mbai-tf-locks`, key `LockID` (string), PAY_PER_REQUEST

Its own `terraform.tfstate` is committed **only if it contains no secrets** — check and say
which you did. The README must explain that this directory is applied once and then left alone.

### 3. `modules/network`

- VPC, `/16`, DNS hostnames and support enabled
- **2 AZs** (`us-east-1a`, `us-east-1b`) — RDS subnet groups require two, even for a
  single-instance database
- Public subnets (ALB) and private subnets (ECS tasks, RDS, ElastiCache)
- Internet Gateway; public route table
- **NAT: make it a variable `enable_nat_gateway`, default `false`.**

  NAT costs ~$32/month plus data. The alternative is **VPC interface endpoints** for the
  services tasks actually need — ECR API, ECR DKR, S3 (gateway, free), CloudWatch Logs,
  Secrets Manager, and Bedrock. Interface endpoints are ~$7/month each; the S3 gateway endpoint
  is free.

  **Do the arithmetic in the result doc** and recommend one. Endpoints also keep traffic off the
  public internet entirely, which matters for the staging security story — so this is not purely
  a cost question.

  ⚠️ **B1 has landed since this ticket was drafted.** Bedrock is confirmed working in this
  account via `bedrock-runtime` with `us.` inference profiles (verified 2026-08-04). The
  endpoint that matters is therefore `com.amazonaws.us-east-1.bedrock-runtime` — confirm it
  exists and include it.

  Separately, report whether an interface endpoint exists for **`bedrock-mantle`**. Nothing
  uses that endpoint today so it does not affect this ticket, but its absence would rule out
  the Messages API surface for a compliance-constrained deployment. Worth knowing before
  anyone proposes switching.

- Security groups, least-privilege, referencing each other by ID rather than CIDR:
  - `alb` — 80/443 from `0.0.0.0/0`
  - `ecs_tasks` — 8000 and 3000 from `alb` **only**
  - `rds` — 5432 from `ecs_tasks` **only**
  - `redis` — 6379 from `ecs_tasks` **only**

  No security group may allow 0.0.0.0/0 on 5432 or 6379. State explicitly in the result doc that
  RDS and ElastiCache are **not** publicly accessible.

### 4. `modules/secrets`

- **Customer-managed KMS key** with rotation enabled, plus an alias `alias/mbai-dev`
- Secrets Manager secrets — **create the containers, not the values**:
  - `mbai/dev/database-url`
  - `mbai/dev/jwt-secret-key`
  - `mbai/dev/encryption-key`
  - `mbai/dev/redis-url` — **only if** ElastiCache AUTH is enabled (the token is embedded in
    the URL, which makes it a credential). If you rely on security-group isolation alone,
    `REDIS_URL` is CONFIG, not a secret. Decide in task 5 and be consistent.

**Do NOT create an `anthropic-api-key` secret.** An earlier draft of this ticket said to. The
secrets audit (`docs/secrets-audit.md`) established that under `AI_PROVIDER=bedrock` the app
does not require it and `AsyncAnthropicBedrock` never sends it — injecting it would add a
live credential to the task with no consumer.

### ⚠️ `ENCRYPTION_KEY` — the most dangerous value in this stack

The audit established (`app/core/encryption.py:58`, `app/models/borrower.py:88`) that this key
has **two** consumers: single-key Fernet encryption of `borrowers.ssn`, and a derived HMAC key
for PII match-hashing. There is **no `MultiFernet` rotation chain and no re-encryption path in
the repo.**

**Rotating it permanently destroys every stored borrower SSN.** Not "requires re-auth" —
unrecoverable, unless the old key still exists.

So the Terraform must guarantee the key **outlives the state that created it**:

- If generated by a `random_*` resource, it needs `lifecycle { prevent_destroy = true }` and
  `ignore_changes`. A provider upgrade that forces replacement, or a `destroy`/`apply` of the
  secret alone against a surviving RDS instance, produces the same permanent loss.
- **Preferred: generate it out of band once and import it**, so no Terraform resource can
  replace it at all.

Whichever you choose, state it explicitly in the result doc and in `infra/README.md`, with the
consequence spelled out. This directly conflicts with the destroy-and-rebuild workflow this
environment is designed for — **if RDS is destroyed alongside it there is no data to lose, but
the two must never be destroyed independently.** Say so.

**Ordering note:** ticket B2 makes `ENCRYPTION_KEY` rotatable (`MultiFernet` plus a
re-encryption path). Until B2 lands, an accidental regeneration is unrecoverable. After B2 it
is recoverable *provided the old key still exists somewhere*. Either way the protection above
is required — B2 lowers the severity, it does not remove the need.

`backend/.env.example` lists `JWT_SECRET_KEY` and `ENCRYPTION_KEY`; the second is the Fernet key
that `app/verification/snapshot/pii.py` derives the PII match-hash key from
(`pii.py:62-63`). **Rotating it invalidates every existing `match_hash`.** Note that in the
module README — it is a real operational hazard, not a footnote.

Use `aws_secretsmanager_secret` without `aws_secretsmanager_secret_version` where the value is
user-supplied, and add `lifecycle { ignore_changes = [secret_string] }` on any version resource
so Terraform never prints or overwrites a secret.

**Set `recovery_window_in_days = 0` for dev** (a variable, defaulting to `30` for staging).
Deleted secrets otherwise sit in a 7–30 day pending-deletion state **with the name reserved**,
so a `destroy` followed by `apply` fails on a name conflict. Since this environment is meant to
be torn down and rebuilt, zero-day recovery is the correct dev setting — and the wrong staging
one.

**No secret values in Terraform, ever.** The user populates them via CLI; give the commands in
the result doc.

### 4b. Budget alarm

Add an `aws_budgets_budget` in `envs/dev`: monthly cost, **$150**, with email notification at
80% actual and 100% forecast. Take the notification address as a variable — do not hardcode it.

This environment is meant to be destroyed between uses. A budget alarm is what catches the case
where it was not.

### 5. `modules/data`

**RDS PostgreSQL**
- Engine version matching local — local is `postgres:16-alpine`, so **16.x**. Verify the exact
  available minor with `aws rds describe-db-engine-versions`.
- `db.t4g.micro`, 20 GB gp3, storage autoscaling to 100 GB
- **Single AZ** (dev), private subnets, `publicly_accessible = false`
- `storage_encrypted = true` with the module's KMS key
- 7-day backups, `deletion_protection = false` for dev (**variable**, must default `true` for
  staging), `skip_final_snapshot = true` for dev (also a variable)
- Master password via `random_password`, written to the `database-url` secret. Never in state
  output, never in a variable default.
- ⚠️ **The URL must use `?ssl=require`, NOT `?sslmode=require`.** The audit executed this
  against the installed asyncpg 0.31.0 / SQLAlchemy 2.0.50: SQLAlchemy's asyncpg dialect does
  not translate libpq parameter names, so unknown query params are forwarded as raw kwargs to
  `asyncpg.connect()`, which has no `sslmode` parameter and no `**kwargs`. The result is
  `TypeError: connect() got an unexpected keyword argument 'sslmode'` — the app cannot connect
  at all. `sslmode` is the spelling RDS documentation uses, so this is very easy to get wrong.
- Note for the result doc: with no SSL argument at all, asyncpg defaults to `prefer` over TCP —
  the connection IS encrypted against `rds.force_ssl=1`, but with `CERT_NONE` and no hostname
  check. Reaching `verify-full` requires the `PGSSLROOTCERT` **environment variable** pointing
  at an RDS CA bundle in the image (asyncpg reads it directly); `?sslrootcert=` in the URL would
  crash exactly like `sslmode`. Record this as a C3 image/task-definition requirement — it is
  not a Terraform change.
- **Custom parameter group with `rds.force_ssl = 1`.** Without it, an unencrypted connection is
  accepted silently — the security architecture assumes TLS to the database, and the default
  parameter group does not enforce it. Note in the result doc whether asyncpg needs an explicit
  `ssl` argument in `DATABASE_URL` for this to work, since a forced-SSL server plus a client
  that does not negotiate it means the app cannot connect at all.
- `enabled_cloudwatch_logs_exports = ["postgresql"]`
- **`performance_insights_enabled = false`** for dev — it is free at 7-day retention but adds
  noise; make it a variable so staging can turn it on.

**ElastiCache Redis**
- `cache.t4g.micro`, single node, engine 7.x to match `redis:7-alpine`
- Private subnets, `transit_encryption_enabled = true`, `at_rest_encryption_enabled = true`

  **Check whether transit encryption requires an AUTH token** for your engine version, and
  whether `redis://` must become `rediss://` in `REDIS_URL`. Celery is sensitive to this — get
  it wrong and the worker fails to connect with an unhelpful error. Report the finding.

**CloudWatch log groups** — create them in Terraform rather than letting ECS auto-create them,
so retention is set from the start:

- `/ecs/mbai-dev/api`, `/ecs/mbai-dev/worker`, `/ecs/mbai-dev/frontend`
- `retention_in_days = 30` (variable)
- Encrypted with the module's KMS key

Auto-created groups default to **never expire**, which accumulates cost and — more importantly
for staging — retains logs indefinitely with no deliberate policy. Setting it now avoids a
retroactive cleanup.

### 5b. NOT managed by this Terraform

State explicitly in `infra/README.md` that the documents bucket
**`mbai-dev-documents-591554480818`** is hand-created (C0) and deliberately **outside**
Terraform's management. It holds uploaded files and must survive every `terraform destroy`.

Do not import it, do not create it, do not reference it as a managed resource. If `envs/dev`
needs its name for an output or an IAM policy, take it as a variable or a
`data.aws_s3_bucket` lookup.

### 6. `modules/registry`

Three ECR repositories: `mbai/api`, `mbai/frontend` — and note in the result doc whether
`worker` needs its own. **It does not** (C1 established one image for api and worker), so create
two and say why.

- `image_tag_mutability = "IMMUTABLE"` — a tag must always mean the same bytes
- `scan_on_push = true`
- Lifecycle policy: keep the last 10 images, expire untagged after 7 days
- Encryption with the KMS key

### 6b. Nothing environment-specific may be hardcoded

⚠️ **This is the requirement that decides whether staging is a copy-paste or a rewrite.**

Every value that differs between dev, staging, and production must be a **variable with no
default in the module**, supplied by `envs/<env>/terraform.tfvars`. A module containing the
literal `dev`, `591554480818`, `us-east-1`, or `mbai-dev-*` is a defect, not a shortcut.

At minimum, these must be variables:

| Variable | dev value | Notes |
|---|---|---|
| `aws_account_id` | `591554480818` | Used by the account guard; **never** in a `.tf` file |
| `aws_region` | `us-east-1` | |
| `environment` | `dev` | Drives naming and the tag |
| `name_prefix` | `mbai-dev` | Every resource name derives from this |
| `vpc_cidr` | e.g. `10.20.0.0/16` | ⚠️ staging **must** differ from dev if the two ever peer |
| `availability_zones` | `["us-east-1a","us-east-1b"]` | Do not hardcode AZ suffixes |
| `rds_instance_class` | `db.t4g.micro` | staging/prod will be larger |
| `rds_allocated_storage` | `20` | |
| `rds_multi_az` | `false` | **must default true for staging** |
| `rds_deletion_protection` | `false` | **must default true for staging** |
| `rds_skip_final_snapshot` | `true` | **must default false for staging** |
| `redis_node_type` | `cache.t4g.micro` | |
| `enable_nat_gateway` | per your task-3 recommendation | |
| `log_retention_days` | `30` | |
| `secret_recovery_window_days` | `0` | **must be 30 for staging** |
| `budget_limit_usd` | `150` | |
| `budget_notification_email` | (user-supplied) | never hardcode an address |
| `documents_bucket_name` | `mbai-dev-documents-591554480818` | looked up, not managed (§5b) |

Rules:

- **No `default` in `modules/*/variables.tf`** for anything environment-specific. A default is
  how a staging value silently inherits a dev setting. Defaults are acceptable only for values
  that are genuinely universal (a port number, an engine family).
- **The five RDS/secret safety variables above default to the UNSAFE value for dev.** Add a
  comment on each stating the required staging value, so the difference is visible in the diff
  rather than remembered.
- Derive every resource name from `var.name_prefix`. No string literal containing `mbai` or
  `dev` anywhere in `modules/`.
- Region comes from the provider block in `envs/`, not from a module.
- AZs come from `var.availability_zones` or a `data.aws_availability_zones` lookup — never
  `"${var.aws_region}a"` string concatenation.

**Verification:** after writing, run

```bash
grep -rniE '591554480818|us-east-1|\bdev\b|mbai-dev' infra/modules/
```

and report the output. It should be **empty**, or every hit should be a comment. Any hit in
actual HCL is a Stop-and-report condition.

Add a `infra/envs/staging/` directory containing **only** a `terraform.tfvars.example` with the
staging values from the table above and a README line saying the `main.tf` is a copy of
`envs/dev/main.tf`. Do not write the staging environment itself — this ticket is dev — but
prove the modules can take those values.

### 7. `envs/dev`

Wire the modules. Outputs C3 will consume: VPC id, subnet ids, security group ids, ECR
repository URLs, RDS endpoint, Redis endpoint, KMS key ARN, secret ARNs.

**Mark any output containing a hostname or ARN as non-sensitive; mark nothing secret as an
output at all.**

`backend.tf` points at the bootstrap bucket with DynamoDB locking and `encrypt = true`.

### 8. Document

**`infra/README.md`** — the apply order (bootstrap → dev), how to populate secrets, how to
destroy, and a prominent note that **RDS deletion protection and final snapshots must be
enabled for staging.**

It must also list the **CONFIG values a deployed task must set**, because every one of them has
a default that silently behaves like development (from `docs/secrets-audit.md` Note 5):

```
ENVIRONMENT           default "development" — staging would report itself as dev
LOG_FORMAT=json       default "console"
CORS_ALLOWED_ORIGINS  default ["http://localhost:3000"] — frontend blocked if unset
STORAGE_BACKEND=s3    default "local" — would write documents to ephemeral container
                      disk that vanishes on task replacement, with NO error
S3_BUCKET             boot-required when storage_backend=s3
AI_PROVIDER=bedrock   default "anthropic"
BEDROCK_MODEL_{CLASSIFICATION,EXTRACTION,REASONING}   boot-required under bedrock
```

`STORAGE_BACKEND` is the sharpest — leaving it `local` fails silently rather than loudly.

Note also that the **migration task needs `DATABASE_URL`** (`alembic/env.py:25`) — the same
secret as the app, not a separate one.

It must also document the **destroy-and-rebuild workflow explicitly**, since that is how this
environment is intended to be used:

- What survives a `destroy`: the state bucket, the lock table, ECR images, and the
  hand-created documents bucket `mbai-dev-documents-591554480818` (which is **not** managed by
  this Terraform).
- What is lost: all RDS data. Re-seeding is a manual step.
- Which resources have destroy-time friction and how each is handled — secret recovery window,
  ECR repositories containing images (`force_delete`), and any resource needing an empty
  precondition.
- Approximate time to rebuild (RDS and ElastiCache each take 5–10 minutes).

Explicitly list any resource that would **block** a clean `destroy` in its default
configuration, and confirm each is configured so `terraform destroy` succeeds without manual
console intervention. If any cannot be, say which and why.

**`docs/tickets/C2-terraform-result.md`** — files created; the `terraform plan` resource count
and a summary of what it creates; the NAT-versus-endpoints arithmetic and your recommendation;
the Redis TLS/AUTH finding; the `bedrock-mantle` endpoint finding; monthly cost estimate; and
the exact commands the user must run, in order.

**`decisions.md`** — append ADRs only for real decisions. Current maximum is **ADR-345** (C1).
Candidates: NAT versus interface endpoints; two ECR repos not three; secret containers in
Terraform with values out of band.

---

## Verify

**Your work ends at `validate`.** A `plan` requires the state bucket to exist, and the state
bucket requires an `apply` of `bootstrap` — which only the user may run. So:

```bash
cd infra/bootstrap
terraform init && terraform fmt -check && terraform validate

cd ../envs/dev
terraform init -backend=false     # backend not reachable until bootstrap is applied
terraform fmt -recursive -check
terraform validate
```

All four must pass. **Do not run `plan` and do not run `apply`.**

Then prove no environment-specific value leaked into a module (§6b):

```bash
grep -rniE '591554480818|us-east-1|\bdev\b|mbai-dev' infra/modules/
```

Report the output verbatim. Empty, or comments only. Any hit in real HCL is a
Stop-and-report condition.

Then write the exact command sequence the user runs, in order, into the result doc:

```
1. cd infra/bootstrap && terraform init && terraform apply
2. cd ../envs/dev && terraform init            # picks up the S3 backend
3. terraform plan -out=dev.tfplan               # review before applying
4. terraform apply dev.tfplan
5. populate the secrets  (give the exact aws secretsmanager put-secret-value commands)
```

Note in the result doc that **step 3 is where the resource count and cost become real** — the
user should read that plan before step 4, and it is the first point at which anything is
billable.

Also confirm nothing local was disturbed:

```bash
docker compose ps                 # mbai-bedrock-* healthy
cd ../../../.. && git status      # no .tfstate, no .terraform/, no .tfvars with secrets
```

---

## Stop and report — do not work around

- Any resource that would require a secret value in a `.tf` file or a variable default.
- Any need for `0.0.0.0/0` ingress on a database or cache security group.
- `terraform plan` showing destruction of anything (nothing exists yet — destruction means a
  state or naming collision worth understanding).
- RDS engine 16.x unavailable in `us-east-1`, or a version mismatch with local Postgres 16.
- An interface endpoint for `bedrock-mantle` not existing — record it, do not work around it.
- Any environment-specific literal that cannot be turned into a variable without breaking
  something. Report the constraint rather than hardcoding it.

## Do not

- Run `terraform apply` or `terraform destroy`. Ever, in this ticket.
- Commit `.tfstate` (except bootstrap's, if verified secret-free), `.terraform/`, or
  `*.tfvars` containing secrets. Add a `.gitignore` for `infra/`.
- Put any account ID, password, or key material in a `.tf` file.
- `git push`.
- Create Alembic migrations.
- Reference `dev`, `591554480818`, `us-east-1`, or any `mbai-dev*` name inside `modules/`.
  Modules must be environment-agnostic — §6b is the acceptance test for this.
- Touch the running Docker stacks.
