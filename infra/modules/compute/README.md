# `modules/compute`

ECS cluster, three Fargate services (`api`, `worker`, `frontend`), an Application
Load Balancer, per-task IAM, and a run-once Alembic migration task.

## The load-bearing part is per-task IAM

A single EC2 host would give every container the same instance profile, making the
api/worker separation a diagram rather than a control. Fargate task roles make it
enforceable — and that is most of why Fargate was chosen.

| Permission | `api` | `worker` | `frontend` |
|---|---|---|---|
| `bedrock:InvokeModel` / `…WithResponseStream` | **no** | **yes** | no |
| `s3:PutObject` | **yes** | **no** | no |
| `s3:GetObject` | yes | yes | no |
| `s3:DeleteObject` | **no** | **no** | no |
| `kms:GenerateDataKey` (bucket CMK) | yes | no | no |
| `kms:Decrypt` (bucket CMK) | yes | yes | no |
| `ssmmessages:*` (ECS Exec) | only when `enable_execute_command` | ditto | ditto |

The KMS rows render **only** when `documents_bucket_kms_key_arn` is set. Under
SSE-S3 there is no key to grant against and the statements are omitted.

`s3:DeleteObject` appears nowhere because `StorageBackend.delete()` has **no call
site in the application** — consistent with soft-delete throughout. Granting it
would widen the roles past what the code can even use.

### The execution role is separate, shared, and the only holder of secrets access

It belongs to the ECS **agent**, which runs before any container process exists:
pull the image, fetch the secrets, decrypt them, write logs. **No task role has
`secretsmanager:GetSecretValue`** — by the time the application is running, the
values are already environment variables.

### Two `Resource: "*"` statements, both AWS-mandated

- `ecr:GetAuthorizationToken` returns a **registry-wide** token; AWS rejects any
  other `Resource`. The pull actions beside it *are* ARN-scoped, so this grants
  only the ability to obtain a token, not to read a particular repository.
- `ssmmessages:*` is a channel-establishment API with no resource model.

Everything else is scoped by ARN.

## Health checks — three separate traps

**1. The target group uses `/health/live`, and that choice matters.** The
application serves three health endpoints (verified in `backend/app/main.py`):

| Path | Behaviour |
|---|---|
| `/health` | **503** when Postgres or Redis is down |
| `/health/ready` | **503** when Postgres or Redis is down |
| `/health/live` | 200 unconditionally — no dependency calls at all |

Pointing a target group at either of the first two turns a database blip into a
total outage: every task deregisters, and every replacement task fails its check
for the same reason.

**2. The API MUST override the image's baked HEALTHCHECK.** Verified with
`docker image inspect`: the backend image bakes
`uv run celery -A app.tasks.celery_app inspect ping`. That is right for the worker
and wrong for the API, which runs no Celery node — an API container that does not
override it sits **UNHEALTHY FOREVER while serving traffic perfectly**.

**`curl` and `wget` are both absent from the backend image** (verified), so the
override uses `python3`, which is present. `urllib` raises on a non-2xx status, so
failure is a non-zero exit without an explicit comparison.

The frontend image has **no** baked healthcheck (`Config.Healthcheck` is null), so
there is nothing to override there; its check uses `wget`, which that image does
have.

**3. The worker needs a container health check, not an ALB one.** It has no HTTP
surface, so ECS cannot otherwise distinguish "alive" from "alive but not
consuming" — a worker that lost its broker connection looks healthy and silently
stops processing. C1's `celery inspect ping` is kept, with a generous
`startPeriod` (120s) because a cold start plus the first database connection takes
time and a check firing too early kills a task that was merely starting.

## CPU architecture

`cpu_architecture` must match the images. **Verified empirically** for this
repository's images: both are `arm64` (built on Apple Silicon), and the running
worker container reports `aarch64`.

Fargate defaults to `X86_64`. The mismatch fails with `exec format error` — the
task starts, dies immediately, and the message appears **only in the CloudWatch log
stream**, never in the ECS console's service events. It is a confusing failure for
a one-line fix.

## Graceful shutdown is real, not decorative

`stopTimeout = 120` (the Fargate maximum) gives Celery time to finish the task in
flight rather than losing it to SIGKILL.

This only works if the signal actually reaches Celery, and the container's PID 1 is
`uv`, not Celery. **Verified empirically that `uv run` forwards SIGTERM to its
child** — a probe with a SIGTERM handler under `uv run` fired the handler and exited
0, identical to running the interpreter directly. So the timeout does what it says.

## No autoscaling, deliberately

There is one tester, and worker autoscaling would need a **queue-depth metric that
does not exist yet**. Scaling on CPU is actively wrong for this worker: it is
rate-limited to a few requests per minute against Bedrock and spends most of its
time waiting on I/O, so CPU stays low precisely when the backlog is deepest.

⚠️ **Raising the worker's `desired_count` requires dividing
`AI_REQUESTS_PER_MINUTE_BEDROCK` by the new count.** That limiter is process-local:
N tasks pace at N × the value, and the account is at 10 RPM.

## `FARGATE`, not `FARGATE_SPOT`

Spot would roughly halve compute cost and is the first saving anyone will propose.
Rejected: a two-minute interruption notice during an extraction that is *already*
rate-limited to minutes means the work is lost partway, leaving a confusing partial
state. The saving is a few dollars a month; the cost is unreproducible failures.

## Configuration that fails silently

`STORAGE_BACKEND=s3` is the sharpest. Left at its `local` default the application
starts happily and writes uploaded documents to **ephemeral container disk that
vanishes on task replacement, with no error at any point.** Every other wrong
default here fails loudly or visibly.

`CORS_ALLOWED_ORIGINS` is the opposite and is worth knowing: the application parses
it as **JSON**, so a bare `http://host` string raises `SettingsError` and the app
refuses to start (verified). It fails loudly.

See `infra/README.md` for the full list.
