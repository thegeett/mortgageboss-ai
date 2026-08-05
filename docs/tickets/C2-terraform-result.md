# C2 — Terraform foundation: result

**Ticket:** [`C2-terraform.md`](C2-terraform.md) · **Branch:** `bedrock_integration`
**Target:** account `591554480818`, `us-east-1` · **Depends on:** C0, C1 · **Blocks:** C3, C4, C5

---

## What this ticket is

C1 produced container images. They needed somewhere to live and something to run
against. C2 builds that foundation **as code** — VPC, ECR, RDS, ElastiCache, KMS,
Secrets Manager, log groups, a budget alarm — so staging later is a second set of
variable values rather than a second afternoon of clicking.

Dev first, deliberately: getting the rough edges wrong in an account with no client
data is much cheaper.

**Nothing was applied.** Per the ticket, this work ends at `validate`. No
`terraform plan`, no `apply`, no `destroy` was run. No AWS resource was created and
nothing is billable yet.

---

## Acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `infra/bootstrap` init + fmt + validate | ✅ | `Success! The configuration is valid.` |
| 2 | `infra/envs/dev` init `-backend=false` + validate | ✅ | `Success! The configuration is valid.` |
| 3 | `terraform fmt -recursive -check` clean | ✅ | exit 0 (one file needed formatting; fixed) |
| 4 | §6b grep over `infra/modules/` empty | ✅ | exit 1, **no output** — see below |
| 5 | No `apply`/`destroy` run | ✅ | no state file exists anywhere |
| 6 | No `.tfstate`, `.terraform/`, or secret tfvars committable | ✅ | `git add -An` lists neither; `git check-ignore` confirms both rules fire |
| 7 | Account guard present | ✅ | `terraform_data.account_guard` precondition in bootstrap **and** envs/dev |
| 8 | Provider pinned `~> 5.x`, `required_version >= 1.9` | ✅ | every `.tf` with a `terraform` block |
| 9 | All resources tagged | ✅ | `default_tags` on the provider + per-resource `Name` |
| 10 | No 0.0.0.0/0 on 5432 or 6379 | ✅ | only ingress from `referenced_security_group_id` |
| 11 | RDS/ElastiCache not publicly accessible | ✅ | stated below |
| 12 | No secret value in any `.tf` or `.tfvars` | ✅ | no `secret_version`, no `random_password` for app secrets |
| 13 | Local Docker stack undisturbed | ✅ | `mbai-bedrock-{postgres,redis,worker}` all healthy |
| 14 | NAT-vs-endpoints arithmetic + recommendation | ✅ | below |
| 15 | Redis TLS/AUTH finding | ✅ | below |
| 16 | `bedrock-runtime` / `bedrock-mantle` endpoint findings | ⚠️ **BLOCKED** | below — insufficient IAM permission |
| 17 | RDS engine 16.x verified available | ⚠️ **BLOCKED, mitigated** | below |
| 19 | Redis engine version correct | ✅ **CONFIRMED** | 7.1 GA all regions since Nov 2023; highest Redis OSS ElastiCache supports |
| 18 | `terraform plan` resource count | ⚠️ **N/A by design** | ticket forbids `plan`; static count below |

**Two criteria could not be met** (16, 17) and both are IAM-permission blockers, not
design problems. Details and exact commands in *Blocked verifications*.

### §6b verification — verbatim

```
$ grep -rniE '591554480818|us-east-1|\bdev\b|mbai-dev' infra/modules/
$ echo $?
1
```

**Empty.** Not "comments only" — genuinely zero hits. Three `description` strings
originally carried illustrative values (`"mbai/dev"`, `"/ecs/mbai-dev/api"`, and a
mention of dev-and-staging); all three were rewritten to be environment-neutral so
the result is unambiguous rather than requiring a judgement call about whether a
heredoc counts as HCL.

### RDS and ElastiCache are not publicly accessible

Stated explicitly, as the ticket requires:

- **RDS** sits in private subnets via `aws_db_subnet_group` over
  `module.network.private_subnet_ids`, and sets `publicly_accessible = false`
  (`modules/data/main.tf`).
- **ElastiCache** sits in private subnets via `aws_elasticache_subnet_group`. It has
  no public-access attribute; subnet placement is the control.
- The `rds` security group admits 5432 **only** from the `ecs_tasks` group, by
  `referenced_security_group_id`. The `redis` group admits 6379 the same way.
- The only `0.0.0.0/0` ingress anywhere in this configuration is 80/443 on the ALB
  security group, which is what a load balancer is for.

---

## What was implemented

25 files under `infra/`.

```
infra/
  .gitignore                             state, plans, .terraform/, secret tfvars
  README.md                              apply order, secret population, destroy workflow
  bootstrap/  main.tf  terraform.tfvars  README.md
  modules/
    network/   main.tf variables.tf outputs.tf
    data/      main.tf variables.tf outputs.tf README.md
    registry/  main.tf variables.tf outputs.tf
    secrets/   main.tf variables.tf outputs.tf README.md
  envs/
    dev/       main.tf variables.tf terraform.tfvars backend.tf outputs.tf
    staging/   terraform.tfvars.example  README.md
```

### Static resource count

The ticket forbids `plan`, and a plan needs the state bucket that only the user can
create. So this is a **static enumeration of resource blocks with `count`/`for_each`
expanded** — not a plan output. Expect the real plan to match; treat any difference
as worth understanding before applying.

| Component | Resources |
|---|---|
| `modules/network` | 30 |
| `modules/data` | 10 |
| `modules/secrets` | 6 |
| `modules/registry` | 4 |
| `envs/dev` (guard + budget) | 2 |
| **`envs/dev` total** | **52** |
| `bootstrap` (separate state) | 6 |

The 30 in `network` is dominated by per-AZ fan-out: 4 subnets, 3 route tables, 4
route-table associations, 2 routes, plus 4 security groups and their 8 rules.

---

## NAT versus interface endpoints

**This corrects a premise in the ticket.** The draft costed interface endpoints at
"~$7/month each". That is the **single-AZ** price. Endpoints bill **per endpoint per
AZ** at $0.01/hour, so across the two AZs an RDS subnet group mandates, each is
$14.60/month.

Five endpoints are needed — `ecr.api`, `ecr.dkr`, `logs`, `secretsmanager`,
`bedrock-runtime` — plus the S3 gateway endpoint, which is free but **mandatory**:
ECR stores image layers in S3, so an ECR interface endpoint without it cannot pull.

| Option | Fixed monthly | Per GB |
|---|---|---|
| NAT gateway (one, shared across AZs) | **$32.85** | $0.045 |
| 5 interface endpoints, 2 AZ | **$73.00** | $0.010 |
| 5 interface endpoints, 1 AZ | **$36.50** | $0.010 |

At realistic transfer volumes the per-GB advantage never closes the gap:

| Egress/mo | NAT | Endpoints (2 AZ) | Endpoints (1 AZ) |
|---|---|---|---|
| 10 GB | $33.30 | $73.10 | $36.60 |
| 30 GB | $34.20 | $73.30 | $36.80 |
| 100 GB | $37.35 | $74.00 | $37.50 |

**Crossover: endpoints only become cheaper above ~1,147 GB/month of egress.** This
environment's dominant transfer is image pulls — tens of GB.

### Recommendation

**Dev: NAT.** Cheapest by 2.2x, one moving part instead of six, and easier to debug
when something cannot reach the internet. Dev holds no borrower data, so cost and
debuggability are the only axes that matter. Set in `envs/dev/terraform.tfvars`.

**Staging: interface endpoints.** Not a cost decision. Staging holds real
GLBA-covered NPI, and the property being bought is that task egress **never touches
the public internet** — the same argument that moved inference to Bedrock in the
first place. Paying ~$40/month more is the point; choosing NAT there to save it
would undo the compliance story the whole Bedrock effort exists to make. Set in
`envs/staging/terraform.tfvars.example`.

**Consequence worth stating:** dev is therefore *not* a faithful rehearsal of
staging's network path. A staging apply exercises endpoint routing for the first
time. If that matters more than $4/month, the 1-AZ endpoint option ($36.50) makes
dev rehearse the routing at near-NAT cost.

Recorded as **ADR-362**.

---

## Redis TLS and AUTH — finding

`transit_encryption_enabled = true` is set unconditionally. Two consequences, and
the second is the one that bites.

### 1. The scheme must become `rediss://`

A `redis://` client cannot connect to a TLS-required cache. `REDIS_URL` must use
`rediss://`. Verified that this does not break the config layer: pydantic's
`RedisDsn` accepts `rediss://` and `rediss://:token@host` without complaint.

### 2. ⚠️ The two Redis clients disagree on certificate verification

The application uses **two different Redis libraries**, both reading the same
`REDIS_URL` (`celery_broker_url` falls back to `redis_url`,
`backend/app/core/config.py:236`). Executed against the installed versions:

| Client | Used by | `rediss://host:6379/0` with no query param |
|---|---|---|
| **redis-py 6.4.0** | cache (`backend/app/core/redis.py:39`) | `ssl_cert_reqs` absent from kwargs → `SSLConnection` default `'required'` → `cert_reqs = 2` — **verifies** |
| **kombu 5.6.2** | Celery broker + result backend | resolves to `{'ssl_cert_reqs': CERT_NONE}` → `cert_reqs = 0` — **does not verify** |

So with the obvious URL, the API's cache client validates the certificate and the
worker's broker client does not. Same URL, same setting, opposite posture.

**Both accept `?ssl_cert_reqs=required`, and both then verify.** So the URL must be:

```
rediss://HOST:6379/0?ssl_cert_reqs=required
```

This is the direct analogue of the `sslmode`/`ssl` trap on the database side: a
default that silently gives you encryption without authentication.

ElastiCache's in-transit certificates chain to a **public** CA, so no custom bundle
is needed — unlike RDS, where `verify-full` needs `PGSSLROOTCERT`.

### 3. Does transit encryption require an AUTH token?

**No.** Transit encryption and AUTH are independent on Redis 6.0+; a token is
optional, and Redis 7.x additionally offers RBAC. Terraform sets transit encryption
unconditionally and leaves the token to `redis_auth_enabled`.

*This one is documented behaviour, not executed* — `elasticache:DescribeCacheEngineVersions`
was denied (see *Blocked verifications*). The configuration does not depend on it
being right: transit encryption is on either way, and the token is applied out of
band.

**Dev sets `redis_auth_enabled = false`**, so `REDIS_URL` carries no credential and
is **CONFIG**, in `environment[]`. **Staging sets it `true`**, which makes the URL a
**SECRET** and auto-creates the `redis-url` container. One variable drives both the
data module and the secrets module, so the two cannot drift apart.

The token itself is never in Terraform — it would land in state.
`ignore_changes = [auth_token]` keeps Terraform from reverting an out-of-band token.

---

## Bedrock endpoint findings — ⚠️ BLOCKED

**Neither could be verified.** The only working credentials are the SSO profile
`mbai-dev`, which assumes `AWSReservedSSO_BedrockDeveloper`. That role is scoped to
Bedrock and denies the EC2 describe call this needs:

```
$ aws ec2 describe-vpc-endpoint-services --query "ServiceNames[?contains(@,'bedrock')]"
An error occurred (UnauthorizedOperation) ... not authorized to perform:
ec2:DescribeVpcEndpointServices because no identity-based policy allows the action
```

The `mbai-dev-admin` profile, which would have the permission, has an **expired SSO
token** (`Token has expired and refresh failed`).

So both findings the ticket asks for are **PENDING**, not answered:

1. **`com.amazonaws.us-east-1.bedrock-runtime`** — expected to exist (B1 confirmed
   Bedrock itself works in this account via `bedrock-runtime` with `us.` inference
   profiles on 2026-08-04), but **the endpoint's existence is a separate fact from
   the API's existence** and has not been checked.
2. **`bedrock-mantle`** — not verified. I have no positive knowledge of an AWS
   interface endpoint by that name, but I am not treating that as evidence of
   absence, because asserting a negative from my own recall is exactly the kind of
   claim this ticket asks to be established empirically.

**The ticket lists a missing `bedrock-mantle` endpoint as a Stop-and-report
condition.** It is recorded here as unverified rather than worked around — nothing
in this ticket depends on it, since nothing uses that endpoint today.

**This does not block dev.** Dev uses NAT, so no Bedrock endpoint is created. It
**does** block staging, which turns endpoints on and NAT off — a missing
`bedrock-runtime` endpoint there means tasks cannot reach Bedrock at all. Flagged in
`infra/envs/staging/README.md`.

To resolve, after `aws sso login --profile mbai-dev-admin`:

```bash
AWS_PROFILE=mbai-dev-admin aws ec2 describe-vpc-endpoint-services \
  --region us-east-1 --query "ServiceNames[?contains(@,'bedrock')]" --output text
```

---

## Other blocked verifications, and how each was mitigated

### RDS PostgreSQL 16.x availability

`rds:DescribeDBEngineVersions` and `rds:DescribeOrderableDBInstanceOptions` were
both denied by the same Bedrock-scoped role.

**Mitigated by design rather than left pending.** `postgres_version = "16"` is
**major-only**. AWS then selects the current minor itself, so there is no pinned
minor that can be retired between writing this and applying it, and
`auto_minor_version_upgrade = true` keeps it current afterwards. A guessed minor
like `16.4` is exactly the value that fails at apply months later.

This satisfies the ticket's engine-match requirement (local is `postgres:16-alpine`)
without depending on the blocked call. To confirm anyway:

```bash
AWS_PROFILE=mbai-dev-admin aws rds describe-db-engine-versions --engine postgres \
  --query "DBEngineVersions[?starts_with(EngineVersion,'16.')].EngineVersion" --output text
```

`redis_version = "7.1"` matches local `redis:7-alpine`. Same mitigation is not
available (ElastiCache wants a concrete version), but it no longer needs one:
**CONFIRMED correct** — ElastiCache for Redis 7.1 has been GA in all regions since
November 2023 and remains the highest Redis OSS version ElastiCache supports. No
pre-apply check is required.

### `terraform plan`

Not run — the ticket forbids it, and it requires the state bucket that only the user
can create. The static count above stands in for it.

---

## Monthly cost estimate

Dev, left running a full month, on-demand `us-east-1` pricing:

| Item | Monthly |
|---|---|
| RDS `db.t4g.micro`, single-AZ | $11.68 |
| RDS gp3 storage, 20 GB | $2.30 |
| ElastiCache `cache.t4g.micro`, 1 node | $11.68 |
| NAT gateway | $32.85 |
| NAT data processing (~30 GB) | $1.35 |
| KMS customer-managed key | $1.00 |
| KMS keys orphaned by a destroy (7-day window, ~$0.23 each) | $0.00–1.15 |
| Secrets Manager, 3 secrets @ $0.40 | $1.20 |
| ECR storage (~20 GB) | $2.00 |
| CloudWatch Logs (ingest + storage, low volume) | $2.00 |
| S3 state bucket + DynamoDB locks | <$0.10 |
| Budget alarm | free |
| **Total** | **≈ $66** |

Against the ticket's $75–95 estimate. The difference is mostly that one shared NAT
gateway was used rather than one per AZ.

**Not included:** ECS Fargate tasks (C3), the ALB (C4), and Bedrock inference — all
of which are usage-driven and will exceed this foundation's cost. The $150 budget
alarm has meaningful headroom over $66 but is **not** generous once C3 and C4 land;
revisit it then.

**Backups** are free up to 100% of allocated storage, so 7-day retention on 20 GB
costs nothing. **Storage autoscaling to 100 GB** would add up to $9.20/month if ever
triggered.

---

## Commands the user runs, in order

```bash
# 1. Bootstrap — once, ever. Local state; creates the S3 backend + lock table.
cd infra/bootstrap
terraform init
terraform apply

# 2. The environment — now the S3 backend resolves.
cd ../envs/dev
terraform init

# 3. ⚠️ READ THIS PLAN. This is where the resource count and cost become real.
terraform plan -out=dev.tfplan

# 4. First billable moment.
terraform apply dev.tfplan
```

**Step 3 is the review gate**, and step 4 is the first point at which anything
costs money. Expect ~52 resources.

### 5. Populate the secrets

```bash
# encryption-key — ⚠️ GENERATE ONCE. Rotating it permanently destroys every
# stored borrower SSN (single-key Fernet, no re-encryption path). See below.
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
aws secretsmanager put-secret-value \
  --secret-id mbai/dev/encryption-key \
  --secret-string 'PASTE_THE_GENERATED_KEY'

# jwt-secret-key — safe to rotate; only invalidates sessions.
aws secretsmanager put-secret-value \
  --secret-id mbai/dev/jwt-secret-key \
  --secret-string "$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"

# database-url — ⚠️ ?ssl=require, NOT ?sslmode=require.
terraform output rds_address     # host
aws secretsmanager put-secret-value \
  --secret-id mbai/dev/database-url \
  --secret-string 'postgresql+asyncpg://mbai_admin:PASSWORD@HOST:5432/mortgageboss?ssl=require'  # pragma: allowlist secret
```

The RDS master password is generated by Terraform and deliberately **not** an
output — read it from the console or from state, or rotate it and use the new one.

There is **no `redis-url` secret** in dev (`redis_auth_enabled = false`);
`REDIS_URL` goes in `environment[]` as
`rediss://HOST:6379/0?ssl_cert_reqs=required`.

There is **no `anthropic-api-key` secret** by design — see below.

---

## Assumptions and decisions

**One NAT gateway, not one per AZ.** A per-AZ NAT is the availability-correct choice
— an AZ outage takes its NAT with it — but triples the cost. The database is
single-AZ in dev, so it is already the AZ-failure bound; a second NAT would buy
nothing. Private route tables are still per-AZ, so adding one later is a route
change, not a re-architecture.

**No `anthropic-api-key` secret.** The ticket says not to create one and the secrets
audit is why: under `AI_PROVIDER=bedrock` the app's validator does not require it
(`config.py:332-333`) and `AsyncAnthropicBedrock` never sends it. Creating it would
place a live credential in the task with no consumer.

**Secret containers, never values.** No `aws_secretsmanager_secret_version`, no
`random_password` for any application secret. A Terraform-written value sits in
state, appears in every plan diff, and can be replaced by a provider upgrade.
**ADR-364.**

The ticket asks for `lifecycle { ignore_changes = [secret_string] }` "on any version
resource". **There is no version resource, so there is nothing to add.**
`secret_string` is an attribute of `aws_secretsmanager_secret_version`, not of the
container — putting `ignore_changes` on the container would only suppress drift on
its *own* attributes (name, description, KMS key), which are precisely the things
that should stay managed. The value is protected by the absence of a resource, not
by an ignore rule. An earlier draft of this module had exactly that mistake; it was
removed rather than left in as decoration.

**`ENCRYPTION_KEY` gets no generating resource at all** — not even a protected one.
The ticket offered `prevent_destroy` + `ignore_changes` on a `random_password` as an
alternative; that is weaker, because `prevent_destroy` blocks a destroy but a
provider upgrade forcing replacement still reaches the resource. The safest resource
is the one that does not exist. Consequence, stated in three places: the
destroy-and-rebuild workflow is safe **only because RDS is destroyed alongside the
secret**; the two must never be destroyed independently.

**Two ECR repositories, not three.** The worker shares the API image (C1), so a
third repository would hold byte-identical copies and create a drift opportunity.
Repositories are also **not** environment-prefixed — one registry, distinguished by
tag. **ADR-363.**

**Bootstrap state is NOT committed.** It contains no secrets today (a bucket and a
table have none), so committing it would be safe — but it would become a liability
the moment a secret-bearing resource is added, and it is a merge-conflict surface
for a file Terraform rewrites on every apply. Both resources are trivially
re-importable; the commands are in `bootstrap/README.md`. The `.gitignore`
deliberately does **not** whitelist it, so committing it stays an explicit
`git add -f` decision.

**Bootstrap uses the AWS-managed `aws/s3` key, not a CMK.** A CMK for the state
bucket is a second chicken-and-egg (the key protecting state would itself need
state) and costs $1/month for no added control — the threat model is "someone
without S3 access reads it", which the managed key already covers. The application's
CMK is created in `modules/secrets`.

**No KMS alias in dev.** The alias is the single thing that made
destroy-and-rebuild need a console step, and it buys only console readability —
`kms_create_alias = false` here, `true` for staging. **ADR-365.**

**The account guard is a `precondition`, not a `check` block.** A `check` emits only
a **warning**; applying to the wrong account must be a hard error. Present in both
`bootstrap` and `envs/dev`.

**An egress precondition was added beyond the ticket.** With both
`enable_nat_gateway` and `enable_vpc_endpoints` false, private tasks cannot pull
their image, and the failure surfaces as an opaque ECS placement error much later.
`modules/network` refuses the plan instead.

**`apply_immediately` is deliberately unset** on RDS and ElastiCache, so parameter
changes wait for the maintenance window rather than restarting the datastore
mid-use.

**`rds.force_ssl = 1` uses `apply_method = "pending-reboot"`** — it is a static
parameter and AWS rejects a dynamic apply for it.

**KMS key policy includes a CloudWatch Logs grant.** Without it, encrypted log
groups fail at apply with an opaque `InvalidParameterException`. Scoped by
`kms:EncryptionContext:aws:logs:arn` to log groups in this account and region.

**ECR repositories are `IMMUTABLE`.** With one registry shared across environments
and one image shared across two services, a re-pointable tag would make "which bytes
are running?" unanswerable and a rollback a guess.

**The documents bucket is looked up, never managed.** `data.aws_s3_bucket` in
`envs/dev/main.tf`. It holds uploaded files and must survive every destroy. Not
created, not imported, not referenced as a managed resource.

**Terraform was not installed on this machine** and was installed via
`brew install hashicorp/tap/terraform` (v1.15.8) to run the Verify steps. That is a
change to the developer machine, not to the repository.

---

## Destroy readiness

Every resource that would block a clean `terraform destroy` in its default
configuration is configured so it does not:

| Resource | Default friction | Handling |
|---|---|---|
| Secrets Manager secret | Name reserved 7–30 days after delete → re-apply name conflict | `secret_recovery_window_days = 0` |
| ECR repository | Destroy fails if it holds images | **Not applicable** — the registry moved to `infra/shared` (review follow-up), so an environment destroy never touches it. `ecr_force_delete = false` there, and that friction is deliberate |
| RDS | Destroy fails with deletion protection on | `rds_deletion_protection = false` |
| RDS | Destroy demands a snapshot name | `rds_skip_final_snapshot = true` |
| KMS **alias** | `destroy` orphans it → next apply fails `AlreadyExistsException` | `kms_create_alias = false` |
| KMS key | 7–30 day deletion window is mandatory | `kms_deletion_window_days = 7`; orphaned keys clear in 7 days, **no rebuild friction** |
| State bucket / lock table | `prevent_destroy` | Intentional; not part of the env destroy |

**There is now no manual step. The earlier "unavoidable exception" was a
misdiagnosis** — worth recording, because the obvious reading is wrong.

The deletion window is **not** what blocks a rebuild. A fresh apply creates a *new*
key regardless of what state the old one is in. The actual blocker was the
**alias**: `terraform destroy` schedules the key but leaves the alias behind
([hashicorp/terraform-provider-aws#35161](https://github.com/hashicorp/terraform-provider-aws/issues/35161)),
so `alias/mbai-dev` is still taken and the next apply dies with
`AlreadyExistsException`, needing a manual `aws kms delete-alias`.

So the fix targets the alias, not the key: **`kms_create_alias = false`** for dev.
The alias is console readability only — every consumer takes the key by ARN through
the module outputs — so nothing functional is lost. `kms_deletion_window_days`
stays at the AWS minimum of 7 so orphaned keys clear as fast as allowed.

**Revised residue: cost, not friction.** Each destroy leaves one orphaned key
pending deletion for 7 days. **Assumption:** a KMS customer-managed key bills at
$1/month, so a 7-day orphan costs roughly **$0.23**, and orphans accumulate only if
the environment is rebuilt more than once within a week — e.g. five rebuilds in a
week ≈ **$1.15** of overlapping keys, on top of the $1.00 already in the cost table
for the live key. Immaterial at this scale, and reclaimable early with
`aws kms cancel-key-deletion --key-id <id>`.

**Staging sets `kms_create_alias = true`** — long-lived, so console readability
outweighs a rebuild friction it will rarely hit. When staging *is* rebuilt, the
orphaned alias needs `aws kms delete-alias --alias-name alias/mbai-staging`.

**Rejected: moving the KMS key (or the secrets) into `bootstrap`.** It would dodge
the orphan entirely, but it trades a ~$0.23 cost for a cross-state dependency
Terraform cannot track — `envs/dev` would consume a key it does not manage, with no
plan-time link between the two. And the `encryption-key` half of the argument
protects only against a *targeted* destroy of the secrets module alone, which is a
narrow case that B2 addresses properly. Not worth the coupling.

Documented in `infra/README.md`. Rebuild time is ~10–15 minutes (RDS and ElastiCache
create in parallel, 5–10 minutes each), plus secret population and re-seeding.

---

## Follow-ups

1. **Verify the Bedrock endpoints** (`bedrock-runtime`, `bedrock-mantle`) with admin
   credentials — **required before staging**, not before dev.
2. **C3 must set `PGSSLROOTCERT`** in the image and task definition to reach
   `verify-full` on the database. `?ssl=require` alone encrypts without verifying.
3. **Revisit the $150 budget** once C3 (Fargate) and C4 (ALB) land.
4. **B2** makes `ENCRYPTION_KEY` rotatable; until then an accidental regeneration is
   unrecoverable.

*Resolved since first writing:* the `redis_version` check (confirmed — see above)
and the placeholder budget address (now `budget@mortgageboss.ai`).
