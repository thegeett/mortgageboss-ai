# C3 — ECS Fargate services, ALB, and per-task IAM

**Branch:** `bedrock_integration`
**Depends on:** C0 (S3), C1 (images), C2 (foundation)
**Blocks:** C4 (DNS/TLS), C5 (deploy)
**Target:** account `591554480818`, `us-east-1`, environment `dev`

---

## What this does and why

C2 built the foundation — VPC, RDS, ElastiCache, ECR, KMS, secrets. C3 puts the application on
it: an ECS cluster, three Fargate services, an Application Load Balancer, and a database
migration task.

**The load-bearing part is per-task IAM.** A single EC2 host would give every container the same
instance profile, making the api/worker separation a diagram rather than a control. Fargate task
roles are what deliver it — and delivering it is most of why Fargate was chosen.

After C3 the stack is reachable over the ALB's own DNS name on HTTP. C4 adds the custom domain
and TLS.

## Acceptance criteria

1. Three ECS services run on Fargate: `api`, `worker`, `frontend`.
2. `api` and `frontend` are reachable through the ALB; `worker` has **no** inbound path.
3. Per-task IAM roles match the matrix below exactly — no broader, no narrower.
4. Every task reaches steady state and passes its health check.
5. Alembic runs as a one-off task, not at container start.
6. No secret value appears in any `.tf` file, task definition, or plan output.
7. `terraform fmt -check` and `validate` pass; the §6b grep over `infra/modules/` stays empty.
8. Nothing is applied. The user applies.

---

## Established facts — use these, do not re-derive

### IAM matrix (from `docs/bedrock-call-sites.md`, verified by call-chain tracing)

| Permission | `api` | `worker` | `frontend` |
|---|---|---|---|
| `bedrock:InvokeModel` / `…WithResponseStream` | **no** | **yes** | no |
| `s3:PutObject` | **yes** | **no** | no |
| `s3:GetObject` | yes | yes | no |
| `s3:DeleteObject` | **no** | **no** | no |
| `kms:GenerateDataKey` (bucket CMK) | yes | no | no |
| `kms:Decrypt` (bucket CMK) | yes | yes | no |

Evidence: all 13 `complete()` call sites are worker-only — zero are reachable from a FastAPI
route. API-side S3 writes are `app/api/documents.py:153` (upload), `:318` (replace), and
`app/mismo/import_service.py:241`. API-side read is the download proxy at `:393`. The worker
reads at `app/tasks/document_processing.py:115` and `:408` and never writes.
`StorageBackend.delete()` has **no call site anywhere**, consistent with soft-delete throughout.

**Scope Bedrock to the two inference-profile ARNs**, not `*`:
```
arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0
arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0
arn:aws:bedrock:us-east-1:591554480818:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0
arn:aws:bedrock:us-east-1:591554480818:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0
```
A cross-region inference profile requires **both** the profile ARN and the underlying
foundation-model ARNs in the policy. Verify the exact form and report it. Take the account id
and model ids as variables (§6b).

`frontend` still gets a task role — with no permissions — so the task definition has one.

### The execution role is separate and shared

Used by the ECS **agent** before your container starts: ECR pull, `secretsmanager:GetSecretValue`
on the three secret ARNs, `kms:Decrypt` on the secrets CMK, and CloudWatch Logs write. All three
services share it. **No task role needs `GetSecretValue`** — injection happens before the process
exists.

### ⚠️ Health checks — three separate traps

**1. Use `/health/live`.** There are three endpoints and two of them return **503** when Postgres
or Redis is unreachable. An ALB target group pointed at either would deregister every `api` task
on a database blip, and replacement tasks would fail their checks too — turning a recoverable
wobble into a total outage. `/health/live` is liveness only.

**2. The image has a baked HEALTHCHECK that api and frontend must override.** C1 added a Celery
`inspect ping` HEALTHCHECK to the backend image, and api shares that image. A container that does
not override `healthCheck` in its container definition will sit **unhealthy forever** while
serving traffic fine. Set an explicit `healthCheck` on the api container (curl `/health/live` on
localhost) and confirm the frontend image has no inherited healthcheck problem.

**3. The worker needs a container health check, not an ALB one.** It has no HTTP endpoint, so ECS
cannot distinguish "alive" from "alive but not consuming" — a worker that lost its broker
connection looks healthy and silently stops processing. Keep C1's `celery inspect ping`. Set
`startPeriod` generously; a cold start plus DB connection takes time.

### ⚠️ Configuration that fails silently if wrong

| Variable | Value | If wrong |
|---|---|---|
| `STORAGE_BACKEND` | `s3` | **Defaults to `local`** — documents write to ephemeral container disk that vanishes on task replacement, with **no error**. Sharpest silent failure here. |
| `DATABASE_URL` | `…?ssl=require` | `?sslmode=require` raises `TypeError: connect() got an unexpected keyword argument 'sslmode'` — asyncpg has no such parameter. RDS docs use the wrong spelling. |
| `REDIS_URL` | `rediss://…?ssl_cert_reqs=required` | Without the query param, redis-py verifies the cert and kombu resolves to `CERT_NONE`. Same URL, opposite posture. |
| `CORS_ALLOWED_ORIGINS` | the ALB origin | Defaults to `["http://localhost:3000"]` — frontend blocked |
| `ENVIRONMENT` | `dev` | Defaults to `development` |
| `LOG_FORMAT` | `json` | Defaults to `console` |
| `AI_PROVIDER` | `bedrock` | Defaults to `anthropic` — would need an API key |
| `BEDROCK_MODEL_{CLASSIFICATION,EXTRACTION,REASONING}` | the `us.` profile ids | Boot-required under bedrock; app refuses to start |
| `S3_BUCKET` | `mbai-dev-documents-591554480818` | Boot-required when `storage_backend=s3` |

**`PGSSLROOTCERT`** must point at an RDS CA bundle in the image to reach `verify-full`.
`?ssl=require` encrypts but does **not** verify the certificate or hostname. Report whether the
C1 image contains a CA bundle; if not, say what C5 must add. `?sslrootcert=` in the URL would
crash exactly like `sslmode`.

**`AI_REQUESTS_PER_MINUTE_BEDROCK`**: the limiter is **per-process**. The account is at 10 RPM,
so with `desired_count = 1` set it to `8`. State in the result doc that scaling the worker
requires dividing this value by the task count.

### ⚠️ CPU architecture — the most likely first failure

C1's images were built on a **Mac**. If that is Apple Silicon, `docker build` produces
**arm64** images by default. Fargate task definitions default to `X86_64`.

An arm64 image on an X86_64 task definition fails with `exec format error` — the task starts,
dies immediately, and the message appears only in the CloudWatch log stream, not in the ECS
console's service events. It is a confusing failure for something with a one-line fix.

Two options, and this must be a deliberate decision:

- Set `runtime_platform { cpu_architecture = "ARM64" }` on all task definitions. Fargate
  supports Graviton, it is ~20% cheaper, and it matches the local build with no cross-compile.
- Or keep X86_64 and require `docker buildx build --platform linux/amd64` in C5's push step.

**Determine the architecture of the images C1 actually built** (`docker image inspect
<image> --format '{{.Architecture}}'`) and make `cpu_architecture` a variable set to match.
Report which you found. Do not guess.

If ARM64 is chosen, verify nothing in the image is x86-only — check whether any wheel in
`uv.lock` ships platform-specific binaries.

### ⚠️ You will need to debug a task you cannot SSH into

Fargate has no SSH. Without **ECS Exec** the only diagnostic surface is CloudWatch logs, and
several of the failure modes enumerated above (empty secret, wrong `STORAGE_BACKEND`, TLS
parameter mismatch) produce either no log line or a misleading one.

Set `enable_execute_command = true` on all three services and add
`ssmmessages:CreateControlChannel`, `CreateDataChannel`, `OpenControlChannel`, and
`OpenDataChannel` to each **task** role. Give the `aws ecs execute-command` invocation for each
service in the result doc.

Note in the result doc that ECS Exec is a **production access path** — for staging it should be
gated or disabled, since it grants a shell in a task holding borrower data. Dev is fine.

### Graceful shutdown

A Celery worker SIGKILLed mid-extraction loses the task. Set `stopTimeout` on the worker
container to the maximum Fargate allows (120s) so Celery finishes its current task after
SIGTERM. Confirm the container's entrypoint actually forwards signals — a shell-form `CMD`
wrapping `uv run` can swallow SIGTERM, in which case the timeout does nothing. Report what you
find.

api and frontend can keep the default; their requests are short.

### Networking

- `api` listens on 8000, `frontend` on 3000. Both need `--host 0.0.0.0` / `HOSTNAME=0.0.0.0` —
  binding to 127.0.0.1 inside a container makes the health check fail with no useful error.
- All three run in **private** subnets with `assign_public_ip = false`. Dev egresses via the NAT
  gateway C2 created.
- `NEXT_PUBLIC_API_URL` is **baked at build time** (C1) and cannot be a task environment
  variable. The image must be built with the eventual public origin. Since C4 sets the domain,
  document that the frontend image needs rebuilding after C4 — or that C3 uses the ALB DNS name
  and C4 triggers a rebuild. State which you chose.

---

## Tasks

### 1. `modules/compute` — cluster and services

New module. Environment-agnostic per §6b — no `dev`, no account id, no region, no `mbai-*`
literal.

- ECS cluster with Container Insights (make it a variable; it costs money)
- One task definition per service. **`api` and `worker` share the same image URI** with different
  `command` values — C1 established one image for both.
- `awslogs` driver pointing at the log groups C2 created. Do **not** let ECS auto-create them.
- `desired_count = 1` for all three, variable. **No autoscaling** — one tester, and worker
  autoscaling needs a queue-depth metric that does not exist yet. Say so in the result doc.
- Deployment circuit breaker **enabled with rollback**, so a bad task definition does not loop.
- Task CPU/memory as variables. Starting points: api 512/1024, worker 1024/2048, frontend
  256/512. The worker gets more because extraction holds whole PDFs in memory while base64
  encoding, against a 50 MB upload cap.
- **Use the `FARGATE` capacity provider, not `FARGATE_SPOT`.** Spot would halve the cost, but a
  two-minute interruption notice during an extraction that is already rate-limited to minutes
  means lost work and a confusing partial state. Record this as a considered-and-rejected
  decision rather than leaving it unexplained — it is the first cost saving anyone will propose.
- Leave `platform_version` at `LATEST`.

### 2. `modules/compute` — IAM

One execution role, three task roles, per the matrix above. Every policy scoped by ARN — no
`Resource: "*"` except where AWS requires it (say where, and why).

Add a **negative test** in the result doc: confirm by reading the rendered policy that the `api`
role has no `bedrock:*` and the `worker` role has no `s3:PutObject`.

### 3. `modules/compute` — ALB

- Internet-facing, public subnets, the `alb` security group C2 created
- HTTP :80 listener for now; C4 adds HTTPS
- Two target groups, `ip` type (required for Fargate/awsvpc)
- Path routing:
  - `/api/*` → api
  - `/health/*` → api ⚠️ **the health endpoints are at the app root, not under `/api/`** — verify
    against `backend/app/main.py` and report the actual paths. Without this rule the ALB health
    check has no route.
  - default → frontend
- Target group health check on `/health/live` for api; the frontend's own root path for frontend
- Deregistration delay 30s (default 300s makes every deploy slow)
- Access logs to S3: make it a variable, default off for dev

### 4. Migration task

Alembic must **not** run at container start — three tasks starting concurrently would race, and a
failed migration would crash-loop the service.

Create a separate task definition, same image, command `uv run alembic upgrade head`, with the
api task role and the shared execution role. It is invoked manually via `aws ecs run-task`; give
the exact command in the result doc.

⚠️ `alembic/env.py:25` reuses the **asyncpg** `DATABASE_URL`, so the same `?ssl=require` applies.
Note that C2's `scripts/check-stack.sh` guard is local-only and does not protect this path —
flag it if that matters.

### 5. `envs/dev` wiring

Consume outputs from `envs/dev` (network, data, secrets) and from `infra/shared` (ECR image
URIs). ⚠️ `shared` is a **third state file** — use `terraform_remote_state` or a data source, and
say which and why.

New outputs: ALB DNS name, cluster name, service names, task definition ARNs, the migration task
command.

### 6. Documentation

**`docs/tickets/C3-ecs-services-result.md`** — what this ticket is, acceptance criteria with
evidence, what was implemented, and **every assumption and decision with reasoning**. Include:

- The rendered IAM policy for each task role, and the negative test from task 2
- Which health check path each target group uses, and the actual paths found in `main.tf`
- The `NEXT_PUBLIC_API_URL` / C4 rebuild decision
- Whether the C1 image contains an RDS CA bundle
- **The architecture of the C1 images**, and the `cpu_architecture` chosen to match
- The `aws ecs execute-command` invocation for each service, and a note that ECS Exec must be
  reconsidered for staging
- Whether the worker's entrypoint forwards SIGTERM
- The `terraform_remote_state` vs data-source decision for `shared`
- The exact command sequence the user runs, in order
- Revised monthly cost including Fargate and the ALB

**`infra/README.md`** — add C3 to the apply order, the migration-task command, and a
**pre-deploy checklist**:
1. All three secrets populated (`aws secretsmanager get-secret-value` returns a value, not an
   empty string) — a task whose secret is empty fails to start
2. Images pushed to ECR with the tag the task definition references
3. **The 4,562 existing documents synced to S3** — keys are byte-identical across backends
   (C0 parity test), so `aws s3 sync` preserving relative paths works. Without this every
   existing document 404s after cutover.
4. Migration task run and succeeded
5. Then, and only then, scale the services up

**`decisions.md`** — append ADRs for real decisions. Read for the current maximum (C2 reached
ADR-365) and continue.

---

## Verify

```bash
cd infra
terraform fmt -recursive -check
cd envs/dev && terraform init -backend=false && terraform validate
grep -rniE '591554480818|us-east-1|\bdev\b|mbai-dev' infra/modules/
```

All must pass; the grep must be empty or comments only.

**Do not run `plan` or `apply`.** A plan needs the state backend and the C2 apply; both are the
user's.

Also confirm nothing local was disturbed:
```bash
docker compose ps        # mbai-bedrock-* healthy, uptime intact
git status               # no .tfstate, no .terraform/, no tfvars with secrets
```

---

## Stop and report — do not work around

- The health endpoint paths in `backend/app/main.py` differing from `/health/live`.
- Any task role needing a permission outside the matrix. The matrix came from call-chain
  tracing; a gap means the tracing was wrong and that is worth knowing, not patching.
- Any Bedrock ARN form that does not work with cross-region inference profiles.
- `frontend` needing an AWS permission for any reason.
- The `shared` state file being unreadable from `envs/dev`.
- Any secret that would have to be an `environment` variable rather than a `secrets` entry.
- An image architecture that cannot be determined, or a mismatch you cannot resolve by setting
  `cpu_architecture` — report it rather than picking one.
- A container entrypoint that swallows SIGTERM, making `stopTimeout` ineffective.

## Do not

- `git push`. Commit locally with a clear message.
- Run `terraform apply`, `destroy`, or `plan`.
- Create any Alembic migration.
- Put an account id, region, or environment name in `modules/`.
- Grant `api` any Bedrock permission, or `worker` any `s3:PutObject`.
- Add autoscaling. One tester, and the worker's scaling signal does not exist yet.
- Modify `app/`, any Dockerfile, or C2's modules beyond adding outputs they need to expose.
- Touch the running local Docker stacks.
