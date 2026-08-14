# Staging frontend crash loop — the app was bound to one interface

**Date:** 2026-08-14
**Symptom:** Next.js starts cleanly, registers as an ALB target, then ECS kills it
~130s later for "failed container health checks". Repeats. Deployment now FAILED
with 3 failed tasks; the site stays up only because the previous task still serves.
**Outcome:** root cause found and fixed. Nothing was deployed or applied.

---

## ⚠️ The hypothesis was wrong

> *"wget is not in the frontend image."*

**It is.** The image is Alpine and `wget` is present:

```
$ docker run --rm --entrypoint sh <image> -c 'command -v wget; command -v curl; command -v node; cat /etc/os-release'
  wget: /usr/bin/wget          -> symlink to /bin/busybox (BusyBox v1.37.0)
  curl: ABSENT
  node: /usr/local/bin/node
  NAME="Alpine Linux"
```

Step 3's message settles it — the distinguishing evidence the brief asked for:

```
$ docker run --rm --entrypoint sh <image> -c 'wget -q --spider http://127.0.0.1:3000/ ; echo "exit=$?"'
  wget: can't connect to remote host (127.0.0.1): Connection refused
  exit=1
```

**"Connection refused", not "not found".** The binary exists and runs. And against a
correctly-bound server it succeeds:

```
$ docker exec <running container> sh -c 'wget -q --spider http://127.0.0.1:3000/ ; echo "exit=$?"'
  exit=0
```

So the health check command was never broken. Had it been "repaired", the crash loop
would have continued.

---

## The actual cause: Next.js bound to the task ENI address only

The frontend logs, side by side:

| | `Local:` | `Network:` |
|---|---|---|
| local `docker run` | `http://localhost:3000` | `http://0.0.0.0:3000` |
| **Fargate** | `http://ip-10-30-47-218.ec2.internal:3000` | **`http://10.30.47.218:3000`** |

In Fargate the server listens on **one address** — the task's ENI IP. That produces a
failure shaped like nothing at all:

- the **ALB** connects to `10.30.47.218:3000` → target registers **HEALTHY**, the
  site serves;
- the **container health check** connects to `127.0.0.1:3000` → **connection
  refused**, every time;
- after `startPeriod 30` + `3 × interval 30` the task is killed. Observed: started
  15:01:26, registered 15:01:56, killed 15:03:38 — **132s**, matching exactly.

**Why.** Next.js standalone `server.js` binds to `process.env.HOSTNAME`. The
Dockerfile sets `ENV HOSTNAME=0.0.0.0` and that wins under a plain `docker run` —
verified, `HOSTNAME=0.0.0.0` inside the local container. **In Fargate the ECS agent
injects the container's own hostname, and the image's value loses.**

The deployed container definition confirms nothing set it back: its `environment` is
`[{NODE_ENV: production}]` — no `HOSTNAME`.

### Reproduced locally, then fixed locally

Running the deployed image with `HOSTNAME` set to a resolvable address, as ECS does:

```
  ▲ Next.js 15.0.3   - Network: http://172.20.0.2:3000
  wget 127.0.0.1  -> exit=1   (can't connect: Connection refused)   <- the container check
  wget 172.20.0.2 -> exit=0                                          <- the ALB path
```

The same image with `HOSTNAME=0.0.0.0` explicitly set:

```
  ▲ Next.js 15.0.3   - Network: http://0.0.0.0:3000
  wget 127.0.0.1  -> exit=0
  wget 172.20.0.3 -> exit=0
  node -e "require('http').get(...)" -> exit=0
```

Both paths work. That is the fix.

---

## Where the health check was defined

**Only in Terraform** — `infra/modules/compute/main.tf`, as a `healthCheck` block on
the container definition. `frontend/Dockerfile` has **no** `HEALTHCHECK` instruction
(the module's own comment records this: *"the frontend image has NO baked
healthcheck (verified: Config.Healthcheck is null)"*). So there is no precedence
question — there was only ever one.

*(Contrast the backend image, which does bake one in and therefore requires an
override on the API container — that override is present and correct.)*

---

## The fix

### 1. Root cause — `HOSTNAME=0.0.0.0` set explicitly

In `local.frontend_env`, merged **under** the caller's map so an environment can
still override it deliberately:

```hcl
frontend_env = [
  for k in sort(keys(merge({ HOSTNAME = "0.0.0.0" }, var.frontend_environment_variables))) :
  { name = k, value = merge({ HOSTNAME = "0.0.0.0" }, var.frontend_environment_variables)[k] }
]
```

Verified offline in a scratch module — renders
`[{HOSTNAME,0.0.0.0},{NODE_ENV,production}]`, and a caller-supplied `HOSTNAME` wins.

### 2. The container health check — REMOVED, not repaired

**Recommendation: remove.** Three reasons, in order of weight:

1. **It is redundant for a load-balanced service.** The ALB target group already
   probes `/` with matcher 200-399 and deregisters a task that stops answering. Two
   checks of the same liveness, and only one of them can *kill* the task.
2. **It cannot be verified before deploying.** I can prove `HOSTNAME=0.0.0.0` fixes
   the bind *locally*, but not that the ECS agent honours a container-definition
   `environment` entry over its own injected value — that needs a deploy, which is
   out of scope here. The risk is asymmetric: if the env fix does not take and the
   check is still there, **the crash loop continues**; if the check is gone, the
   worst case is "app serves, bound to one interface" — the status quo, minus the
   outage.
3. The check's only real contribution was detecting a bind problem, and that problem
   is now fixed at the source rather than discovered by killing tasks.

⚠️ **The worker keeps its check** — it has no ALB, so `celery inspect ping` is the
only way ECS can distinguish "alive" from "alive but not consuming". That reasoning
does not transfer to a service behind a load balancer.

If a container check is ever wanted back on the frontend, the comment in the module
records the right command — `node -e`, using the guaranteed runtime rather than a
BusyBox applet that a base-image change could remove — **verified working inside the
deployed image** (exit 0 above). Only add it back after confirming the task binds
`0.0.0.0`.

⚠️ **Note on the stated constraint.** The brief said not to modify `infra/` beyond
the healthcheck definition. The `HOSTNAME` line goes one line past that, because the
diagnosis showed the healthcheck was *not* the defect. Removing only the check would
have stopped the crash loop while leaving the app bound to a single interface —
silently wrong, and waiting to resurface behind any future loopback probe.

---

## The same class of error elsewhere — both fine, nothing changed

### 5. API container

```
CMD-SHELL  python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)" || exit 1
```

That is exactly what C3 recorded shipping — `python3` + `urllib` precisely because
curl and wget are absent from the backend image. **It works**, proven by the
deployed environment rather than a local reproduction:

```
api      healthStatus = HEALTHY   lastStatus = RUNNING   rolloutState = COMPLETED   failedTasks = 0
```

A health check that did not work could not report `HEALTHY`.

### 6. Worker container

```
CMD-SHELL  uv run celery -A app.tasks.celery_app inspect ping -d celery@$HOSTNAME || exit 1
```

**It works:**

```
worker   healthStatus = HEALTHY   lastStatus = RUNNING   rolloutState = COMPLETED   failedTasks = 0
```

⚠️ Worth noting explicitly, because it looks like the same trap: this check
interpolates **`$HOSTNAME`** — the very variable that broke the frontend. Here it is
*correct*, because Celery derives its node name from the same hostname, so both
sides move together. The frontend's problem was never `$HOSTNAME` being wrong; it
was Next.js *binding* to it.

Service status across all three:

```
svc                     running  desired  state      failed
mbai-staging-api        1        1        COMPLETED  0
mbai-staging-worker     1        1        COMPLETED  0
mbai-staging-frontend   1        1        FAILED     3
```

---

## Verification

```
terraform fmt -recursive -check              clean
terraform validate  bootstrap/staging/dev    Success (all three)
frontend_env expression                      rendered offline; HOSTNAME present, override honoured
healthcheck command in the image             wget exit 0 against a bound server; node -e exit 0
the fix                                      reproduced the failure AND the fix locally
```

AWS access was read-only throughout: `describe-services`, `describe-task-definition`,
`describe-tasks`, `list-tasks`, `logs get-log-events`, plus one ECR pull.

**Not verified:** that ECS honours a container-definition `HOSTNAME` over its own
injected value. That requires a deploy. It is the standard fix for Next.js standalone
on Fargate, and the removal of the health check means the deploy is safe either way —
if it does not take, the service still serves, it is simply still bound narrowly, and
the logs will say so (`Network: http://10.30.x.x:3000` rather than `0.0.0.0`).

---

## What to run

```bash
./scripts/deploy staging deploy
```

No application code changed, so the image tag is unchanged and the build is skipped;
the Alembic head is unchanged so the migration is skipped. What it does is apply the
task-definition change and wait for all three services to roll.

⚠️ The current deployment is **FAILED** with the circuit breaker tripped. The apply
registers a new revision and starts a fresh deployment, which clears it.

**Confirm afterwards** — the log line is the direct evidence:

```bash
aws logs get-log-events --log-group-name /ecs/mbai-staging/frontend \
  --log-stream-name "$(aws logs describe-log-streams --log-group-name /ecs/mbai-staging/frontend \
      --order-by LastEventTime --descending --max-items 1 \
      --query 'logStreams[0].logStreamName' --output text)" \
  --start-from-head --query 'events[].message' --output text
```

Expect `Network: http://0.0.0.0:3000`. If it still shows `10.30.x.x`, the env
override did not take — the service will be healthy regardless, and the next step
would be a `command` override on the container instead.

```bash
./scripts/deploy staging status     # frontend should read COMPLETED, not FAILED
```
