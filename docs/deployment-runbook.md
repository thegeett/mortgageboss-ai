# Deployment runbook

How to deploy an environment with `scripts/deploy`, what each stage does, what to
do when one fails, and how to roll back.

The authority on *why* each step exists is
[`docs/tickets/C5-deploy-staging.md`](tickets/C5-deploy-staging.md). This document
is the operating manual for the script that implements it.

---

## The command

```
./scripts/deploy <env> <stage> [--yes] [--profile NAME] [--force]
```

`<env>` is a directory under `infra/envs/`. Nothing in the script names an
environment: the account id, region, domain, and phase flags come from that
environment's `terraform.tfvars`, and every identifier — subnets, security groups,
cluster, ECR URLs, bucket, user pool — comes from `terraform output`.

**Adding production is a new `infra/envs/production/` with its own tfvars, plus an
AWS profile. No edit to the script.**

| Option | Meaning |
|---|---|
| `--yes` | Answer every confirmation yes. Still prints what it does. |
| `--profile NAME` | AWS profile. Default: `$AWS_PROFILE`, else `mbai-<env>-admin`. |
| `--force` | `secrets` only: overwrite a secret that already holds a value. |

Exit codes: `0` success · `1` failure, refusal, or an operator "no" · `2` (smoke
only) every automated check passed but manual checks are unverified.

---

## Before you start

Both of these have bitten this project before.

**1. Log in.** SSO sessions are separate; one login does not cover the others.

```bash
aws sso login --sso-session mbai
AWS_PROFILE=mbai-staging-admin aws sts get-caller-identity   # must be 058190633983
```

Every stage re-checks that the profile's account matches the environment's
`aws_account_id` and refuses otherwise, so a wrong profile fails immediately
rather than three steps in.

**2. Check the clock.** The SSO session is about 4h20m. `phase1` alone takes 10–15
minutes, mostly RDS. A token that expires **mid-apply** fails partway and leaves
half-created resources.

**3. Know where you are.** `status` is read-only and safe at any moment:

```bash
./scripts/deploy staging status
```

---

## The sequence

```bash
./scripts/deploy staging bootstrap   # state bucket
./scripts/deploy staging phase1      # ~60 resources, TLS and Cognito OFF
./scripts/deploy staging dns         # prints nameservers, waits — applies nothing
#   ... add four NS records at Namecheap ...
./scripts/deploy staging images      # buildx arm64, push, verify architecture
./scripts/deploy staging secrets     # generate + populate, validated before writing
./scripts/deploy staging migrate     # alembic upgrade head as a one-off ECS task
./scripts/deploy staging phase2      # ACM + HTTPS listener + Cognito
./scripts/deploy staging smoke       # the seven checks
```

Or `./scripts/deploy staging all`, which runs the same order and **stops at `dns`**
for the manual registrar step, telling you to re-run `all` afterwards. Every stage
is individually idempotent, so re-running `all` resumes rather than repeats.

Two steps the script deliberately does **not** do, both from the ticket:

- **Cognito users** (step 8) — `admin-create-user`, then turn MFA **on** once users
  are enrolled. It is `OPTIONAL` initially because enforcing it before any user
  exists locks out the first account.
- **The pre-handover security checklist** (step 10) — work it *before* the first
  real loan file, not after.

---

## What each stage does

### `bootstrap`

`terraform init` + `plan` in `infra/bootstrap`, shows the plan, asks, applies.
Creates the S3 state bucket every other directory stores its state in — which is
why this one directory uses **local state**.

Idempotent: a plan with no changes reports "already exists and matches" and exits
0 without prompting.

> **If `init` rejects `use_lockfile`** the script **stops** and prints the C4b
> fallback (swap to `dynamodb_table` and restore the lock table in bootstrap). It
> does not work around it: the only available workaround is setting both lock
> mechanisms, which Terraform treats as a conflict. `use_lockfile` had never been
> verified against Terraform v1.15.8 when this was written.

### `phase1`

Same pattern in `infra/envs/<env>`, with `enable_tls = false` and
`enable_cognito = false`. Refuses to run if either flag is true.

**Before offering to apply, it inspects the plan JSON and refuses if any
`aws_acm_certificate` change appears.** ACM validates over DNS; created before the
registrar delegation is live it sits in `PENDING_VALIDATION` until the apply times
out 45 minutes later.

Expect the ECS services to start and their tasks to **fail** afterwards — no images
have been pushed yet. That is the expected state, not a fault.

### `dns`

**Applies nothing.** Prints the four nameservers from `terraform output` with the
Namecheap path (Domain List → `mortgageboss.ai` → Manage → Advanced DNS → Add New
Record → NS Record, four times, host `staging`), then polls
`dig +short NS <domain>` every 30s until four `awsdns` nameservers answer.

The apex stays at the registrar and is never delegated. Ctrl-C is always safe here.
Timeout defaults to 30 minutes (`DEPLOY_DNS_TIMEOUT_SECONDS`).

### `images`

ECR login, then `docker buildx build --platform linux/arm64 … --push` for both
images, using exactly the URIs in the `container_image_uris` output — the same
strings the task definitions reference.

- The frontend gets `--build-arg NEXT_PUBLIC_API_URL=https://<domain>`, derived
  from `domain_name` in the environment's tfvars. **It is inlined into the
  JavaScript bundle at build time and is not read at runtime** — build it wrong and
  the browser calls the wrong host with nothing in the server logs.
- **After pushing, each image's architecture is verified.** An x86 image on an
  ARM64 task definition dies with `exec format error`, visible only in the
  CloudWatch log stream — in the ECS console it looks like a task that started and
  stopped for no reason.

ECR tags are **immutable**, so a re-push of the same tag is rejected by the
registry. That makes "already pushed" the only possible idempotent behaviour: the
stage verifies what is already there (digest, push time, architecture) and moves
on. To ship new bytes, bump `image_tag` in the tfvars and re-run `phase1` then
`images`.

Requires `docker buildx`. If the plugin is missing the stage stops with install
instructions rather than falling back to a plain `docker build`, which would not
reliably produce — or let it verify — an arm64 manifest.

### `secrets`

Terraform creates the four secrets as **empty containers**, and a task whose secret
is empty fails to start.

- `jwt-secret-key` — generated, 48 random bytes urlsafe.
- `encryption-key` — a generated Fernet key, **validated by construction** using the
  same `cryptography` library the app uses (it looks for `backend/.venv/bin/python`
  first). A length check would accept values Fernet rejects at the first SSN write,
  inside a request handler. Printed **once**, with the warning to store it outside
  AWS: single-key Fernet, no rotation path until B2, so losing it means losing every
  stored SSN.
- `database-url` — prompted, pre-filled from `rds_address` / `rds_username` /
  `rds_database_name` with `?ssl=verify-full`. The master password is deliberately
  not a Terraform output, so you paste it in.
- `redis-url` — prompted, pre-filled as
  `rediss://…:6379/0?ssl_cert_reqs=required`. With AUTH enabled the token is applied
  out of band and the URL carries it.

**Validated before writing.** Refusals: `sslmode` or `sslrootcert` anywhere in
`DATABASE_URL` (both crash asyncpg with an unexpected-kwarg `TypeError`), a
non-`postgresql+asyncpg` scheme, no `ssl=` parameter at all (asyncpg's default
`prefer` encrypts with `CERT_NONE` and no hostname check), a `REDIS_URL` that is not
`rediss://` or has no `ssl_cert_reqs`, and any leftover `<PLACEHOLDER>`. `ssl=require`
is accepted with a warning — it verifies the chain but not the hostname.

**Refuses to overwrite** a secret that already has a value unless `--force`, which
additionally requires a per-secret confirmation and, for `encryption-key`, spells
out that overwriting makes existing SSNs permanently undecryptable.

Values never appear on a command line: each is written through a `0600` temp file
that the exit trap deletes, because `ps` shows the full argv of a running process.
All four are verified non-empty (by byte count, never by value) at the end.

### `migrate`

Runs the `migrate` task definition with `aws ecs run-task`, polls until it stops,
prints its CloudWatch log stream, and exits non-zero on a non-zero container exit
code.

The network configuration is read off the **running API service**, not from the raw
subnet list: tasks are pinned to the AZs that have interface endpoints, and
`private_subnet_ids` includes AZs that do not. `alembic upgrade head` is idempotent,
so re-running the stage is safe.

### `phase2`

**Refuses to run unless `dig` already shows four `awsdns` nameservers.** Then flips
`enable_tls` **and** `enable_cognito` to `true` in the tfvars (shown and confirmed
first; it is a tracked file, so the change appears in `git status`), plans, shows,
confirms, applies.

The two flags move together, always. An ALB cannot attach `authenticate-cognito` to
an HTTP listener, so `modules/compute/alb.tf` fails the plan on the pair
(cognito = true, tls = false) rather than letting the environment come up with no
authentication while appearing configured.

### `smoke`

The seven checks from step 9, in order, exiting non-zero on any failure.

| # | Check | Automated |
|---|---|---|
| 1 | `https://<domain>` → **302** to Cognito | yes |
| 2 | `https://<domain>/api/v1/health` → **302** | yes |
| 3 | `http://<domain>` → **301** to HTTPS | yes |
| 4 | Log in through Cognito, then the app | manual |
| 5 | Upload one document | manual |
| 6 | `extractions` shows a `us.anthropic.*` model with **non-zero** cost | manual |
| 7 | The document is in **S3**, not on container disk | yes |

> **Check 2 is a security check, not a health check.** A **200** there means the
> `/api/*` listener rule is missing its `authenticate-cognito` action and **the API
> is open to the internet** — every route reachable by anyone, without credentials.
> The script says exactly that, in those words, and fails. Do not hand the
> environment to anyone and do not upload a real loan file until it is fixed.

Check 6 needs database access the operator's laptop does not have (private subnet,
no public access), so the script prints the SQL and asks. Checks 4–6 are confirmed
interactively; under `--yes` they are recorded as **unverified** and the stage exits
**2** rather than silently passing.

Check 7 failing right after a skipped check 5 just means nothing has been uploaded
yet. Failing after a real upload means `STORAGE_BACKEND` is not `s3`, and documents
are on ephemeral container disk that vanishes on task replacement — with no error at
any point.

### `status`

Read-only, runnable at any time, never changes anything. Reports: state bucket,
phase-1 applied, phase flags, certificate present, DNS delegation, both images
(pushed + tag), every secret (populated, byte count), the last migration task's exit
code, each service's running/desired count, and the RDS instance's status.

`unknown` appears where a check genuinely cannot be made — an expired SSO session,
or a stopped migration task that has aged out of the ECS API after about an hour.
`unknown` never means "fine".

A service reported as `SHUT DOWN -- desired 0` and a `database  STOPPED` line mean
the environment was taken down with `down`, not that something failed.

### `down` and `up`

`down` takes the environment offline; `up` brings it back. Neither is part of a
deployment — they exist so staging does not bill for the hours nobody is using it.
About **$0.10 an hour**, which over a night and a weekend is most of what the
environment costs.

```
./scripts/deploy staging down     # end of the day
./scripts/deploy staging up       # next morning
```

`down` scales the three ECS services to desired 0, waits for the tasks to actually
stop (the worker gets its SIGTERM window to finish or re-queue what it is holding),
and only then stops RDS. If the tasks have not drained inside
`DEPLOY_DOWN_DRAIN_TIMEOUT_SECONDS` it leaves the database running rather than cut
their connections mid-task; re-running `down` picks up where it left off.

`up` reverses it, database first — a task that starts before Postgres answers fails
its readiness check, and the deployment circuit breaker can roll it back. It waits
for RDS to reach `available`, then scales each service to the count in that
environment's `terraform.tfvars`.

**Nothing durable is lost.** RDS keeps its storage and its backups (they keep
billing, which is why they are not part of the saving), and Redis holds nothing
durable.

**ElastiCache and the ALB stay up in both directions**, deliberately. A replication
group has no stop operation, only delete, and its AUTH token is applied out of band —
a recreated one would come up with no token while Secrets Manager still held the old
URL, and every API and worker container would fail on connect. The ALB is not worth
churning its ACM, Cognito and Route 53 associations for. So while the environment is
down the site answers with **503**, with no targets behind it.

Two things to know:

- **`deploy` and `migrate` refuse to run while the environment is down**, and say so.
  Both would otherwise fail confusingly: Terraform can fail mid-apply against a
  stopped instance, and a service left at desired 0 reaches steady state instantly,
  so `deploy` would report success for an image no task is running.
- **AWS force-starts an instance left stopped for seven days**, so it does not miss a
  maintenance window. A nightly shutdown never reaches that; a long holiday one does,
  and the instance then stays up until someone stops it again.

This depends on `lifecycle { ignore_changes = [desired_count] }` on all three
services in `infra/modules/compute/main.tf`. Without it the next `terraform apply`
would silently scale everything back up. See
[`docs/tickets/LP-630.md`](tickets/LP-630.md).

| Variable | Default | Meaning |
|---|---|---|
| `DEPLOY_DOWN_DRAIN_TIMEOUT_SECONDS` | 300 | `down`: how long to wait for tasks to stop |
| `DEPLOY_RDS_START_TIMEOUT_SECONDS` | 900 | `up`: how long to wait for RDS |

---

## When a stage fails

The script never continues past an error, and every refusal names the reason.

| Symptom | Where to look |
|---|---|
| **Task starts and dies immediately** | The **CloudWatch log stream**, not ECS service events. An architecture mismatch, an empty secret, and the `uv run` PyPI hang look identical from the console. |
| **Task stuck in `PENDING`** | Almost always the image pull: check the ECR endpoint and that the tag really exists (`./scripts/deploy <env> status`). |
| **Nothing in the logs at all** | The container died before logging. With ECS Exec off, the fastest diagnosis is running the same image locally with the same environment. |
| **ACM stuck in `PENDING_VALIDATION`** | Delegation. `dig +short NS <domain>` — you need four `awsdns` answers. |
| **`terraform init` rejects `use_lockfile`** | Apply the C4b fallback by hand; the script prints it. Never set both lock mechanisms. |
| **Apply fails partway** | Re-run the same stage. Terraform plans only the difference, so a partial apply is recoverable. |
| **SSO token expired mid-apply** | `aws sso login --sso-session mbai`, then re-run the stage. Check the remaining session time before starting another. |
| **`smoke` check 2 returns 200** | Stop. Fix the listener rule, re-apply `phase2`, re-run `smoke`. This is a security failure. |

Debris an aborted run can leave: a `*.tfplan` file in the terraform directory
(gitignored; safe to delete — the script deletes it on success), and, if `phase2`
was aborted after the confirmation, `enable_tls`/`enable_cognito` already flipped to
`true` in the tfvars. Either apply, or set both back to `false`.

---

## Rolling back

- **A failed ECS deployment rolls itself back.** The circuit breaker with rollback is
  enabled on all three services.
- **A bad image** — update the service to the previous task definition revision, or
  bump `image_tag` back and re-run `phase1`. Immutable tags mean the previous image
  is still exactly where it was.
- **A bad apply** — `terraform apply` the previous plan, or revert the tfvars change
  and re-run the stage.
- **Phase 2 specifically** — setting `enable_tls` and `enable_cognito` back to `false`
  and applying removes the HTTPS listener and the Cognito action. That leaves the
  environment reachable over **plain HTTP with no authentication**, so treat it as a
  break-glass step, not a routine one.

⚠️ **`terraform destroy` is not a rollback here.** Staging is not a
destroy-and-rebuild environment: `rds_deletion_protection = true`,
`rds_skip_final_snapshot = false`, `secret_recovery_window_days = 30`,
`ecr_force_delete = false`, and the documents bucket carries `prevent_destroy`. A
destroy will refuse on the database, and that is intended.

---

## Related

- [`docs/tickets/C5-deploy-staging.md`](tickets/C5-deploy-staging.md) — the ticket:
  full resource inventory, every hazard, and the pre-handover security checklist
- [`infra/README.md`](../infra/README.md) — layout, apply order, secret spellings
- [`docs/secrets-audit.md`](secrets-audit.md) — why each URL is spelled the way it is
- [`decisions.md`](../decisions.md) — ADR-370 (`UV_NO_SYNC`) and the C-series ADRs
