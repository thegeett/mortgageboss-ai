# C3 — ECS Fargate services, ALB, and per-task IAM: result

**Ticket:** [`C3-ecs-services.md`](C3-ecs-services.md) · **Branch:** `bedrock_integration`
**Target:** account `591554480818`, `us-east-1`, environment `dev`
**Depends on:** C0, C1, C2 · **Blocks:** C4 (DNS/TLS), C5 (deploy)

---

## What this ticket is

C2 built the foundation — VPC, RDS, ElastiCache, ECR, KMS, secret containers. C3
puts the application on it: an ECS cluster, three Fargate services, an Application
Load Balancer, and a one-off database migration task.

The load-bearing part is **per-task IAM**. A single EC2 host would give every
container the same instance profile, making the api/worker separation a diagram
rather than a control. Fargate task roles are what deliver it.

After C3 the stack is reachable over the ALB's own DNS name on HTTP. C4 adds the
custom domain and TLS.

**Nothing was applied.** No `plan`, no `apply`, no `destroy`. Work ended at
`fmt` + `validate`, as instructed.

---

## Empirical vs assumed — read this first

The ticket asked for three things to be checked against reality rather than
assumed. All three were checked, and **two of them changed the design**.

| # | Question | Status | Finding |
|---|---|---|---|
| 1 | Architecture of the C1 images | ✅ **EMPIRICAL** | `arm64` — both images. `cpu_architecture = "ARM64"`. |
| 2 | Health endpoint paths | ✅ **EMPIRICAL** | `/health`, `/health/live`, `/health/ready` at app **root**, not under `/api`. |
| 3 | Does the worker entrypoint forward SIGTERM? | ✅ **EMPIRICAL** | **Yes** — `uv run` forwards it, so `stopTimeout` is effective. |
| 4 | Bedrock ARN form for cross-region profiles | ✅ **EMPIRICAL** | **Ticket was incomplete** — profiles route to 3 regions, not 1. |
| 5 | `curl` available for the API health check | ✅ **EMPIRICAL** | **Absent** — used `python3` instead. |
| 6 | RDS CA bundle in the C1 image | ✅ **EMPIRICAL** | **Not present.** C5 must add it. |
| 7 | Documents bucket encryption (SSE-S3 vs CMK) | ⚠️ **PENDING** | No permission. Command below. |

Everything else in this document that is not marked EMPIRICAL is a design decision
or an assumption, and is labelled as such.

### 1. Image architecture — EMPIRICAL

```
$ docker image inspect mbai-api:test      --format '{{.Architecture}}/{{.Os}}'  -> arm64/linux
$ docker image inspect mbai-frontend:test --format '{{.Architecture}}/{{.Os}}'  -> arm64/linux
$ docker exec mbai-bedrock-worker uname -m                                      -> aarch64
```

The images are **arm64**, built on Apple Silicon. Fargate defaults to `X86_64`, and
the mismatch fails with `exec format error` — the task starts, dies immediately, and
the message appears **only in the CloudWatch log stream**, never in the ECS console's
service events.

`cpu_architecture = "ARM64"` is set to match. The third line is the strongest
evidence: the arm64 image is not merely buildable, it is running the local stack
right now. Recorded as **ADR-366**.

### 2. Health endpoints — EMPIRICAL

From `backend/app/main.py`:

| Path | Line | Behaviour |
|---|---|---|
| `/health` | `:156` | **503** when Postgres or Redis is down |
| `/health/live` | `:178` | 200 unconditionally — **no dependency calls** |
| `/health/ready` | `:188` | **503** when Postgres or Redis is down |

Two things follow, and both are implemented:

- **The API target group uses `/health/live`.** Pointing it at either sibling would
  turn a database blip into a total outage — every task deregisters, and every
  replacement fails its check for the same reason.
- **The paths are at the application ROOT, not under `/api/v1`.** Every feature
  router is mounted under `/api/v1`, but these three are not. Without a dedicated
  listener rule they fall through to the default action and reach the *frontend*,
  which does not serve them — so the ALB health check would have no route at all.
  `aws_lb_listener_rule.api_root_paths` (priority 90) handles `/health`,
  `/health/*`, and also `/docs`, `/redoc`, `/openapi.json`, which FastAPI likewise
  mounts at the root.

This matched the ticket's expectation, so it is **not** a Stop-and-report.

### 3. SIGTERM forwarding — EMPIRICAL

The container's PID 1 is `uv`, not Celery (image CMD is
`["uv","run","celery",...]`), so `stopTimeout` is only meaningful if `uv` forwards
the signal. Tested with a SIGTERM-handling probe under both a direct interpreter and
`uv run`:

```
CONTROL  /app/.venv/bin/python -c <probe>   started=1 handler_fired=1 exit=0
TEST     uv run --no-sync python -c <probe> started=1 handler_fired=1 exit=0
```

**`uv run` (0.5.11) forwards SIGTERM.** Identical to the control. So
`stopTimeout = 120` is effective rather than decorative — Celery does get its grace
period to finish the task in flight instead of losing it.

### 4. Bedrock ARNs — EMPIRICAL, and this corrects the ticket

The ticket listed four ARNs, with the foundation models scoped to `us-east-1` only.
Verified:

```
$ aws bedrock get-inference-profile --inference-profile-identifier us.anthropic.claude-haiku-4-5-20251001-v1:0
   arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0
   arn:aws:bedrock:us-east-2::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0
   arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0
```

Both `us.` profiles route to **three** regions. A cross-region invocation authorises
against the profile ARN **and** the foundation-model ARN in whichever region Bedrock
routes to — so a `us-east-1`-only list under-grants.

**The failure mode is why this matters:** it is **intermittent**, not a clean break.
It would pass a smoke test and then fail a fraction of production extractions with
an `AccessDeniedException` that reads like an application bug. Routing across regions
is the entire *point* of a cross-region profile, so the mis-scoped policy fails
precisely when the feature is working as designed.

The policy therefore grants **8 ARNs** — 2 models × 3 regions, plus 2 profiles. The
region list is the variable `bedrock_profile_regions`. Recorded as **ADR-368**.

*Also observed:* `global.anthropic.*` profiles exist in this account alongside the
`us.*` ones. Nothing uses them; they would route wider still and need the same
treatment.

The profile ARN form in the ticket was otherwise **correct**, verified exactly:
`arn:aws:bedrock:us-east-1:591554480818:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0`

### 5. Health-check tooling — EMPIRICAL

The ticket says to curl `/health/live`. **`curl` is not in the backend image**, and
neither is `wget`:

| Image | curl | wget | python3 | node |
|---|---|---|---|---|
| `mbai-api` | ✗ | ✗ | ✓ | ✗ |
| `mbai-frontend` | ✗ | ✓ | ✗ | ✓ |

So the API container health check uses `python3` + `urllib` (which raises on a
non-2xx status, so failure is a non-zero exit without an explicit comparison), and
the frontend's uses `wget --spider`.

Also verified, and this is the trap the ticket flagged:

```
mbai-api      Config.Healthcheck -> {"Test":["CMD-SHELL","uv run celery ... inspect ping ..."], ...}
mbai-frontend Config.Healthcheck -> null
```

The backend image **does** bake a Celery healthcheck, so the API — which runs the
same image with no Celery node — **must** override it or sit unhealthy forever while
serving traffic fine. It does. The frontend has none, so there is nothing to
override there; the ticket's "confirm the frontend image has no inherited
healthcheck problem" is **confirmed clean**.

### 6. RDS CA bundle — EMPIRICAL

```
$ docker run --rm mbai-api:test sh -c 'ls /etc/ssl/certs/*rds* /opt/rds* 2>/dev/null; echo $PGSSLROOTCERT'
   no rds-named bundle found
   system CA bundle: 224449 bytes
   PGSSLROOTCERT: <unset>
```

**The C1 image contains no RDS CA bundle**, and `PGSSLROOTCERT` is unset.

Consequence: `?ssl=require` encrypts the connection but asyncpg does **not** verify
the certificate or hostname. **C5 must** (a) add the RDS CA bundle to the image and
(b) set `PGSSLROOTCERT` to its path in the task definition. It cannot be expressed
in the URL — `?sslrootcert=` would crash exactly like `?sslmode=` does, because
SQLAlchemy forwards unknown query parameters as raw kwargs to `asyncpg.connect()`,
which accepts neither.

*Assumption, not verified:* that the system bundle (224 KB) does not already chain
to the RDS roots. AWS publishes RDS certificates under its own regional CAs, which
are not part of the standard `ca-certificates` package.

### 7. Documents bucket encryption — ⚠️ PENDING

```
$ aws s3api get-bucket-encryption --bucket mbai-dev-documents-591554480818
An error occurred (AccessDenied) ... not authorized to perform:
s3:GetEncryptionConfiguration
```

The only working credentials assume `AWSReservedSSO_BedrockDeveloper`, which is
Bedrock-scoped. `documents_bucket_kms_key_arn` is therefore **`null`**, which
assumes **SSE-S3** and attaches **no** KMS statement to the task roles.

**If the bucket is actually CMK-encrypted, uploads fail with an opaque `AccessDenied`
from S3** (not from KMS, which is what makes it hard to diagnose). Run before
applying:

```bash
aws s3api get-bucket-encryption --bucket mbai-dev-documents-591554480818
```

If it reports `aws:kms`, set `documents_bucket_kms_key_arn` to that key's ARN. The
module already renders the correct statements for both cases — `api` gets
`GenerateDataKey` + `Decrypt`, `worker` gets `Decrypt` only.

---

## Acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Three Fargate services: api, worker, frontend | ✅ | `aws_ecs_service.{api,worker,frontend}`, `launch_type = "FARGATE"` |
| 2 | api + frontend behind the ALB; worker has **no** inbound path | ✅ | worker has no `load_balancer` block, no target group, no `portMappings` |
| 3 | Per-task IAM matches the matrix exactly | ✅ | negative test below |
| 4 | Every task reaches steady state and passes its health check | ⚠️ **UNVERIFIABLE** | requires an apply, which is the user's |
| 5 | Alembic runs as a one-off task, not at container start | ✅ | `aws_ecs_task_definition.migrate`, no service references it |
| 6 | No secret value in any `.tf`, task definition, or plan output | ✅ | only `valueFrom` ARNs; no `secret_string` anywhere |
| 7 | `fmt -check` + `validate` pass; §6b grep empty | ✅ | below |
| 8 | Nothing applied | ✅ | no plan/apply/destroy run |

Criterion 4 is the only one not met, and it **cannot** be met from this side — it
requires the stack to exist. Everything checkable without an apply is verified.

### Verify output

```
fmt -recursive -check            exit 0
validate: bootstrap              Success! The configuration is valid.
validate: shared                 Success! The configuration is valid.
validate: envs/dev               Success! The configuration is valid.
grep §6b over infra/modules/     (no output) exit 1
docker compose ps                mbai-bedrock-{postgres,redis,worker} all healthy
git status                       no .tfstate, no .terraform/, no secret tfvars
```

### Negative test — task 2

Static extraction from `modules/compute/iam.tf`. **This is a static check, not a
rendered plan** — a plan needs the state backend and C2's apply, both of which are
the user's.

```
PASS  api role has NO bedrock:*
PASS  api role has NO s3:DeleteObject
PASS  api role has NO secretsmanager:*
PASS  worker role has NO s3:PutObject
PASS  worker role has NO s3:DeleteObject
PASS  worker role has NO kms:GenerateDataKey
PASS  worker role has NO secretsmanager:*
PASS  ONLY the execution role has secretsmanager:GetSecretValue
PASS  execution role has NO bedrock:*
PASS  execution role has NO s3:*
```

Rendered action sets:

| Role | Actions |
|---|---|
| `api_task` | `s3:PutObject`, `s3:GetObject`, `kms:GenerateDataKey`*, `kms:Decrypt`* |
| `worker_task` | `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream`, `s3:GetObject`, `kms:Decrypt`* |
| `execution` | `ecr:GetAuthorizationToken`, `ecr:BatchCheckLayerAvailability`, `ecr:GetDownloadUrlForLayer`, `ecr:BatchGetImage`, `secretsmanager:GetSecretValue`, `kms:Decrypt`, `logs:CreateLogStream`, `logs:PutLogEvents` |
| `frontend_task` | `ssmmessages:*` only (and **nothing at all** when Exec is off) |

\* KMS statements render only when `documents_bucket_kms_key_arn` is set. At `null`
(the current value, pending check 7) they are absent.

**Exactly two `Resource: "*"` statements, both AWS-mandated:**

- `ecr:GetAuthorizationToken` — returns a **registry-wide** token; AWS rejects any
  other `Resource`. The pull actions beside it *are* ARN-scoped, so this grants only
  the ability to obtain a token, not to read a repository.
- `ssmmessages:*` — a channel-establishment API with no resource model.

---

## What was implemented

```
infra/modules/compute/          NEW
  main.tf        cluster, 4 task definitions, 3 services
  iam.tf         1 execution role + 3 task roles
  alb.tf         ALB, 2 target groups, listener, 2 rules
  variables.tf   no defaults except genuinely universal values
  outputs.tf
  README.md
infra/modules/data/outputs.tf   + log_group_arns / *_by_key (additive only)
infra/envs/dev/{main,variables,outputs}.tf, terraform.tfvars   compute wiring
```

**Four task definitions, three services.** The fourth is `migrate`, which no service
references.

---

## Decisions and assumptions

### `api` and `worker` share one image

C1 established one image for both; only the command differs. The API overrides the
image's Celery CMD with
`uv run uvicorn app.main:app --host 0.0.0.0 --port 8000`. Binding to `0.0.0.0` is
required — binding to localhost inside a container makes the health check fail with
no useful error. The frontend image already sets `HOSTNAME=0.0.0.0` and `PORT=3000`,
so it needs no command override.

### Migration task

Separate task definition, same image, `uv run alembic upgrade head`, **API task role**
+ shared execution role. Alembic must not run at container start: three tasks
starting concurrently would race on the same migration, and a failure would
crash-loop the service rather than failing one visible job.

It reuses the API task role rather than inventing a fourth — it needs no S3 or
Bedrock access, and an unused role is a thing to keep in sync for no benefit.

`alembic/env.py:25` reads the same asyncpg `DATABASE_URL`, so the same `?ssl=require`
spelling applies. **Flagged as the ticket asked:** C2's `scripts/check-stack.sh`
guard is local-only and does **not** protect this path — nothing prevents running
the migration task against the wrong environment except the operator reading the
cluster name in the command.

### No autoscaling

One tester, and worker autoscaling needs a **queue-depth metric that does not
exist**. Scaling on CPU would be actively wrong: the worker is rate-limited to a few
requests per minute against Bedrock and spends most of its time on I/O, so CPU stays
*low* precisely when the backlog is deepest — CPU-based scaling would scale down
under load.

⚠️ **`AI_REQUESTS_PER_MINUTE_BEDROCK = 8` assumes `desired_count = 1`.** The limiter
is process-local: N worker tasks pace at N × the value, against an account quota of
10 RPM. Raising the worker count **requires** dividing this value by the new count.

### `FARGATE`, not `FARGATE_SPOT`

Spot halves compute cost and is the first saving anyone will propose. Rejected: a
two-minute interruption notice during an extraction that is *already* rate-limited to
minutes means work lost partway, in a confusing partial state. Saving ≈ $9/month
against unreproducible failures.

### `NEXT_PUBLIC_API_URL` and the C4 rebuild — decision

**C3 does not set it at all, and the frontend image will need rebuilding after C4.**

It is inlined into the JavaScript bundle at **build** time (C1), so it cannot be a
task environment variable — setting one would do nothing while appearing to work.
The frontend container therefore has no `NEXT_PUBLIC_API_URL` entry, deliberately.

This is survivable in C3 because **the frontend and API sit behind the same ALB**:
the browser loads the page from `http://<alb>/` and calls `http://<alb>/api/...`,
which is **same-origin**. A relative API base works without the variable being set
correctly at all.

**C4 must trigger a frontend rebuild** with the real origin baked in, because the
custom domain changes the origin. Chosen over building against the ALB DNS name now
and rebuilding again later — that would mean two rebuilds instead of one, and an
image tagged with a hostname nobody should be using once the domain exists.

### CORS — chicken and egg, and it fails loudly

`CORS_ALLOWED_ORIGINS` should be the ALB origin, but the ALB DNS name does not exist
until after the first apply, and it cannot be self-referenced (`module.compute`
cannot depend on its own output). It is left at `["http://localhost:3000"]` as a
placeholder.

Not on the critical path, for the same same-origin reason as above. It becomes
essential at C4.

**Verified:** the application parses this env var as **JSON**. A bare
`http://host` string raises `SettingsError` and the app **refuses to start** — so
this one fails loudly rather than silently, unlike most config traps here. Terraform
`jsonencode`s a list to match.

### `terraform_remote_state` vs data source — decision

**`data.aws_ecr_repository`, keyed by repository name.** Not `terraform_remote_state`.

Reasoning in **ADR-367**: remote state reads the *entire* shared state (needing
`s3:GetObject` on it, and pulling in every attribute of every resource to obtain two
strings), and couples to shared's *output names*, so a rename there breaks every
environment at once. The repository **name** is the real contract and is already a
variable.

Trade-off accepted: no plan-time ordering. If `shared` has not been applied, this
fails with a clear "repository not found" — an explicit, diagnosable failure rather
than an implicit dependency.

### ECS Exec

Enabled on all three services, with the four `ssmmessages` actions gated on the same
variable. **ADR-369** records the part that matters: this is a **production access
path**, not a debugging convenience — it grants an interactive shell inside a task
holding decrypted secrets and borrower NPI. Fine for a throwaway environment;
**for staging it should be gated behind break-glass or disabled.**

Gating IAM on the same flag resolves a tension in the ticket, which asked both that
the frontend have "no permissions" and that every task role carry `ssmmessages`: the
frontend has no *application* permissions either way, and **zero** statements when
Exec is off.

**Invocations** (each needs `--task <id>`, which changes every deployment; list with
`aws ecs list-tasks --cluster mbai-dev --service-name <service>`):

```bash
aws ecs execute-command --cluster mbai-dev --task <task-id> --container api      --interactive --command /bin/sh
aws ecs execute-command --cluster mbai-dev --task <task-id> --container worker   --interactive --command /bin/sh
aws ecs execute-command --cluster mbai-dev --task <task-id> --container frontend --interactive --command /bin/sh
```

Requires the Session Manager plugin locally.

### Other choices

- **Deployment circuit breaker with rollback** on all three services — without it a
  bad task definition loops, launching failing tasks until someone notices.
- **`deregistration_delay = 30s`** — the AWS default of 300s makes every deploy crawl
  for no benefit on short HTTP requests.
- **`drop_invalid_header_fields = true`** on the ALB.
- **Log groups are passed in, never auto-created** — an ECS-created group defaults to
  never expire.
- **Task definitions sort their `environment` arrays** so plans are stable; an
  unsorted map reorders and shows a spurious diff every time.
- **`worker` startPeriod = 120s** — a cold start plus first DB connection takes time,
  and a check firing too early kills a task that was merely starting.

---

## Revised monthly cost

Fargate ARM64 (Graviton) rates, `us-east-1`, `desired_count = 1`, 730 h:

| Item | vCPU/GB | Monthly |
|---|---|---|
| api task (0.5 vCPU, 1 GB) | | $12.94 |
| worker task (1 vCPU, 2 GB) | | $25.88 |
| frontend task (0.25 vCPU, 0.5 GB) | | $6.47 |
| ALB (fixed) | | $16.43 |
| ALB LCU (low traffic, ~1 LCU) | | $5.84 |
| **C3 subtotal** | | **≈ $68** |
| C2 foundation (RDS, cache, NAT, KMS, secrets, ECR, logs) | | ≈ $66 |
| **Total** | | **≈ $134** |

**Assumptions:** ARM64 Fargate at $0.03238/vCPU-h and $0.00356/GB-h; ~1 LCU for a
single tester. Container Insights is **off** — enabling it adds roughly $9/month per
task at this scale. Bedrock inference is usage-driven and excluded.

⚠️ **This lands close to the $150 budget alarm** C2 set: ≈ $134 of ≈ $150, with
Bedrock inference and any C4 costs still to come. The alarm will fire at 80%
(≈ $120) almost immediately. **Raise the budget or plan to destroy between uses** —
which is what this environment is designed for.

---

## Commands the user runs, in order

```bash
# 0. PRE-DEPLOY CHECKLIST — see infra/README.md. Especially: secrets populated,
#    images pushed with the referenced tag, and the 4,562 documents synced to S3.

# 1. Verify the pending bucket-encryption question (check 7 above).
aws s3api get-bucket-encryption --bucket mbai-dev-documents-591554480818

# 2. Plan and apply.
cd infra/envs/dev
terraform init
terraform plan -out=dev.tfplan      # ← read this; it is where cost becomes real
terraform apply dev.tfplan

# 3. Run the migration ONCE, before scaling up.
terraform output -raw migration_run_task_command   # prints the full invocation
# then run it, and confirm it exited 0:
aws ecs describe-tasks --cluster mbai-dev --tasks <task-arn> \
  --query 'tasks[0].containers[0].exitCode'

# 4. Reach the stack.
terraform output -raw alb_dns_name
curl http://$(terraform output -raw alb_dns_name)/health/live
```

---

## Follow-ups

1. **Verify the documents bucket's encryption** (check 7) — the one PENDING item.
2. **C5 must add the RDS CA bundle** to the image and set `PGSSLROOTCERT`, or the
   database connection stays unverified.
3. **C4 must rebuild the frontend image** with the real origin baked in.
4. **Set `CORS_ALLOWED_ORIGINS`** to the real origin at C4.
5. **Reconsider ECS Exec for staging** — it is a shell into borrower data.
6. **Raise the budget alarm or destroy between uses** — C2 + C3 ≈ $134 against $150.
7. **Re-verify `bedrock_profile_regions`** when adding a model tier; AWS extending a
   profile to a fourth region silently re-introduces the intermittent failure.
