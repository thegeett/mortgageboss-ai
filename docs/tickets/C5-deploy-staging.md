# C5 — Deploy staging

**Target:** account `058190633983` · `us-east-1` · `staging.mortgageboss.ai`
**Prerequisite:** C0–C4b complete, validated, committed
**Outcome:** a working URL Priya can log into

---

## Before you start

Two things, both of which have bitten this project before.

**1. Log in to every SSO session.** They are separate; one login does not cover the others. A
`terraform apply` takes 10–15 minutes for RDS, and a token expiring mid-run fails **partway**,
leaving half-created resources.

```bash
aws sso login --sso-session mbai
AWS_PROFILE=mbai-staging-admin aws sts get-caller-identity
```

Must return `058190633983`. If it returns anything else, stop.

**2. Check the SSO clock.** The session is ~4h20m, and the apply plus smoke tests will take
longer than one sitting.

```bash
./scripts/sso-status --profile=mbai-staging-admin
```

---

## What gets built — full inventory

**≈ 60 resources.** Phase 1 creates everything except the last block.

### Bootstrap — applied once, local state

| Resource | Notes |
|---|---|
| S3 bucket `mbai-tfstate-058190633983` | versioned, SSE-KMS (`aws/s3`), public access blocked |

No DynamoDB table — `use_lockfile` uses S3 conditional writes.

### Network

| Resource | Count | Notes |
|---|---|---|
| VPC | 1 | |
| Public subnets | 2 | ALB requires two AZs |
| Private subnets | 2 | RDS subnet group requires two; **only one is used** |
| Internet gateway + public route table | 1 | ALB egress only |
| Private route tables | 2 | **no default route** — this is the no-internet property |
| Security groups | 4 | `alb`, `ecs_tasks`, `rds`, `redis` — referenced by group id, not CIDR |
| VPC interface endpoints | 5 | `bedrock-runtime`, `ecr.api`, `ecr.dkr`, `logs`, `secretsmanager` — **single AZ** |
| S3 gateway endpoint | 1 | free, a route table entry rather than an ENI |

**No NAT gateway.** Anything not covered by an endpoint is unreachable — and *hangs* rather
than failing.

### Security & secrets

| Resource | Notes |
|---|---|
| KMS CMK + alias | rotation enabled; encrypts RDS, S3, secrets, logs, ECR |
| Secrets Manager × 4 | `database-url`, `jwt-secret-key`, `encryption-key`, `redis-url` — **containers only, empty** |
| Cognito user pool | admin-created users only, no self-signup |
| Cognito hosted UI domain | the login page |
| Cognito app client | callback from `var.domain_name`, not the ALB DNS name |

⚠️ `encryption-key` has **no generating resource** by design. Rotating it destroys every stored
SSN (single-key Fernet, no re-encryption path until B2 lands).

### Data

| Resource | Spec |
|---|---|
| RDS Postgres 16 | `db.t4g.small`, 50 GB gp3, single-AZ, private, CMK, **deletion protection ON**, final snapshot ON |
| RDS parameter group | `rds.force_ssl = 1` |
| ElastiCache Redis 7.1 | `cache.t4g.small`, single node, TLS + AUTH |
| ElastiCache parameter group | name varies with family (CBD requirement) |
| S3 documents bucket | SSE-KMS, versioned, TLS-only policy, **`prevent_destroy`**, no lifecycle rule |

### Registry & compute

| Resource | Count |
|---|---|
| ECR repositories | 2 — `mbai/api`, `mbai/frontend`, immutable tags, scan on push |
| ECS cluster | 1 |
| Task definitions | 4 — api, worker, frontend, **migration** |
| ECS services | 3 — desired_count 1, circuit breaker with rollback |
| IAM execution role | 1, shared |
| IAM task roles | 3 — see the matrix below |
| CloudWatch log groups | 3, 30-day retention, CMK |

**Task role matrix — the load-bearing part:**

| | Bedrock | S3 put | S3 get | S3 delete |
|---|---|---|---|---|
| `api` | **no** | yes | yes | no |
| `worker` | yes (8 scoped ARNs) | **no** | yes | no |
| `frontend` | no | no | no | no |

### Load balancer & DNS

| Resource | Notes |
|---|---|
| ALB | internet-facing, public subnets |
| Target groups × 2 | `ip` type, required for Fargate awsvpc |
| Listener :80 | phase 1 forwards; **phase 2 becomes a 301 redirect** |
| Listener rules | `/api/*` and `/health/*` → api; default → frontend |
| Route 53 hosted zone | `staging.mortgageboss.ai` |
| Route 53 alias A record | apex → ALB |

### Phase 2 only

| Resource | Notes |
|---|---|
| ACM certificate + validation records | DNS validation |
| Listener :443 | TLS 1.3 policy |
| `authenticate-cognito` action | **on every rule**, not just the default |

### Cost-cutting

| Resource | Notes |
|---|---|
| Budget `$300` | 80% actual, 100% forecast |
| Cost allocation tag `Environment` | ⚠️ account-level; without it the budget matches nothing and reports $0 forever |

---

## The sequence

### Step 1 — Bootstrap

```bash
cd infra/bootstrap
AWS_PROFILE=mbai-staging-admin terraform init
```

⚠️ **First real test of `use_lockfile`.** It was never verified against Terraform v1.15.8. If
init rejects it, apply the fallback in `C4b-consolidate-staging-result.md`: restore the DynamoDB
table to bootstrap and swap `use_lockfile` for `dynamodb_table` in `envs/staging/backend.tf`.
Never set both.

```bash
AWS_PROFILE=mbai-staging-admin terraform plan -out=bootstrap.tfplan
AWS_PROFILE=mbai-staging-admin terraform apply bootstrap.tfplan
```

The account guard is a `precondition` — a wrong-account apply is a hard plan failure, not a
warning.

### Step 2 — Phase 1 apply

```bash
cd ../envs/staging
AWS_PROFILE=mbai-staging-admin terraform init      # first init, not a migration
AWS_PROFILE=mbai-staging-admin terraform plan -out=staging.tfplan
```

**Read this plan.** It is the first point at which anything becomes billable. Confirm
`enable_tls = false` and that no ACM certificate appears.

```bash
AWS_PROFILE=mbai-staging-admin terraform apply staging.tfplan
```

**10–15 minutes**, mostly RDS. Services will start and their tasks will fail — no images exist
yet. That is expected.

### Step 3 — Delegate the subdomain at Namecheap

```bash
terraform output -json route53_name_servers
```

Four `ns-….awsdns-….{com,net,org,co.uk}` values.

At **Namecheap** → `mortgageboss.ai` → **Advanced DNS**, add **four NS records** with host
`staging`, one per nameserver. The apex stays at Namecheap and is never delegated.

```bash
dig +short NS staging.mortgageboss.ai
```

**Four `awsdns` nameservers means delegation is live.** Anything else means wait. Do not
proceed until this is clean — running phase 2 early makes ACM sit in `PENDING_VALIDATION` until
its 45-minute timeout.

### Step 4 — Build and push images

```bash
ACCOUNT=058190633983
REGISTRY=$ACCOUNT.dkr.ecr.us-east-1.amazonaws.com
AWS_PROFILE=mbai-staging-admin aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin $REGISTRY
```

⚠️ **`--platform linux/arm64` on both.** C3 verified the C1 images are arm64 and pinned
`cpu_architecture = "ARM64"`. An x86 image on an ARM64 task definition dies with
`exec format error`, visible only in the log stream — not in ECS service events.

```bash
docker buildx build --platform linux/arm64 \
  -t $REGISTRY/mbai/api:staging ./backend
docker push $REGISTRY/mbai/api:staging

docker buildx build --platform linux/arm64 \
  --build-arg NEXT_PUBLIC_API_URL=https://staging.mortgageboss.ai \
  -t $REGISTRY/mbai/frontend:staging ./frontend
docker push $REGISTRY/mbai/frontend:staging
```

⚠️ **The frontend build arg is baked into the JavaScript bundle and is not read at runtime.**
Build it wrong and the browser calls the wrong host, with **nothing in your server logs**.

⚠️ **Two open items must be in the image before this step:**
- **The RDS CA bundle**, with `PGSSLROOTCERT` pointing at it. Without it `?ssl=require`
  encrypts but verifies neither certificate nor hostname. Open since C3.
- Confirm **`UV_NO_SYNC=1`** is in the task definitions. Without it `uv run` reaches PyPI at
  container start, and with no NAT it **hangs** — no log line, no shell, circuit-breaker
  rollback loop.

### Step 5 — Populate the four secrets

Terraform creates empty containers. **A task whose secret is empty fails to start.**

```bash
gen() { python3 -c "import secrets;print(secrets.token_urlsafe(48))"; }

AWS_PROFILE=mbai-staging-admin aws secretsmanager put-secret-value \
  --secret-id mbai/staging/jwt-secret-key --secret-string "$(gen)"

python3 -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
# → put-secret-value into mbai/staging/encryption-key
```

⚠️ **`encryption-key` must be a valid Fernet key** (44-char urlsafe base64). It is validated for
length but not format at boot, so a malformed value starts cleanly and fails at the first SSN
write, inside a request handler.

⚠️ **Save it somewhere safe outside AWS.** Until B2 lands there is no rotation path — losing it
means losing every stored SSN.

**`database-url`** — from the Terraform output, and:

⚠️ **`?ssl=require`, never `?sslmode=require`.** The latter raises
`TypeError: connect() got an unexpected keyword argument 'sslmode'`. RDS documentation uses the
wrong spelling for asyncpg.

**`redis-url`** — apply the AUTH token out of band, then:

⚠️ **`rediss://…?ssl_cert_reqs=required`.** Without the query parameter, redis-py verifies the
certificate and kombu resolves to `CERT_NONE` — same URL, opposite posture.

Verify all four are non-empty:

```bash
for s in database-url jwt-secret-key encryption-key redis-url; do
  printf '%-18s ' "$s"
  AWS_PROFILE=mbai-staging-admin aws secretsmanager get-secret-value \
    --secret-id mbai/staging/$s --query 'SecretString' --output text | wc -c
done
```

### Step 6 — Run the migration

Against an **empty** database. No seed, no dump — dev documents and dev data have no place here.

```bash
AWS_PROFILE=mbai-staging-admin aws ecs run-task \
  --cluster mbai-staging \
  --task-definition mbai-staging-migrate \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<private-subnet-id>],securityGroups=[<ecs-sg-id>],assignPublicIp=DISABLED}"
```

Watch it in CloudWatch Logs. Confirm `alembic_version` is at head before continuing.

### Step 7 — Phase 2 apply (TLS + Cognito)

Set `enable_tls = true` in `terraform.tfvars`.

```bash
AWS_PROFILE=mbai-staging-admin terraform plan -out=staging-tls.tfplan
AWS_PROFILE=mbai-staging-admin terraform apply staging-tls.tfplan
```

Creates the certificate, waits for issuance, adds the HTTPS listener with Cognito, converts
port 80 to a redirect.

### Step 8 — Create Cognito users

```bash
POOL_ID=$(terraform output -raw cognito_user_pool_id)
AWS_PROFILE=mbai-staging-admin aws cognito-idp admin-create-user \
  --user-pool-id "$POOL_ID" --username priya@example.com \
  --user-attributes Name=email,Value=priya@example.com Name=email_verified,Value=true \
  --desired-delivery-mediums EMAIL
```

Cognito emails a temporary password. **Then turn MFA ON** — it is `OPTIONAL` initially because
enforcing it before any user exists locks out the first account.

The app also needs a first company and user. `seed_dev_data.py` hardcodes `DevPassword123!`
and is **not** suitable here — create the first account through the app's own registration
path, or by a one-off task with a supplied password.

### Step 9 — Smoke test

In order. Each isolates a different layer.

1. `curl -I https://staging.mortgageboss.ai` → **302 to Cognito**. Not 200 — that would mean
   auth is not applied.
2. `curl -I https://staging.mortgageboss.ai/api/v1/health` → **also 302.** A 200 here means the
   `/api/*` rule is missing its auth action and **the API is open to the internet.**
3. `curl -I http://staging.mortgageboss.ai` → **301** to HTTPS.
4. Log in through Cognito, then through the app.
5. Upload one document.
6. Confirm it reached Bedrock:
   ```sql
   select model_used, cost_estimate, extraction_status
   from extractions order by created_at desc limit 3;
   ```
   A `us.anthropic.*` model with **non-zero cost**. A zero cost means the pricing table is
   missing the model — telemetry is broken even though extraction worked.
7. Confirm the document is in **S3**, not on container disk:
   ```bash
   AWS_PROFILE=mbai-staging-admin aws s3 ls s3://<bucket>/ --recursive | tail
   ```
   Empty means `STORAGE_BACKEND` is not `s3` — documents are on ephemeral disk and vanish on
   task replacement, **with no error**.

### Step 10 — Pre-handover security checklist

Work this **before** Priya's first real file, not after. This is the moment the account changes
character, and nothing about it feels like a milestone.

- [ ] Remove or narrow the standing `AdministratorAccess` permission set → break-glass only
- [ ] Drop `BedrockDeveloper` — the worker task role invokes Bedrock, not a human
- [ ] Confirm `enable_execute_command = false`
- [ ] MFA **ON** for every Cognito user
- [ ] Budget notification address receives mail
- [ ] `Environment` cost allocation tag activated — up to 24h before it reports
- [ ] Bedrock invocation logging **off** (it would write raw borrower documents to S3)
- [ ] Error tracking scrubbed — an exception payload carrying `extracted_data` is the likeliest
      real leak

---

## If something fails

**Task starts and dies immediately** → CloudWatch log stream, not ECS service events.
Architecture mismatch, empty secret, and the `uv run` hang all look identical from the console.

**Task stuck in PENDING** → almost always image pull. Check the ECR endpoint and that the tag
exists.

**Nothing in logs at all** → the container died before logging. With ECS Exec off, the fastest
diagnosis is running the same image locally with the same environment.

**ACM stuck in PENDING_VALIDATION** → delegation. Re-check `dig`.

**Rollback:** `terraform apply` the previous plan, or update the service to the previous task
definition revision. The circuit breaker rolls back a failed deployment automatically.

---

## Open decisions this surfaces

1. **Document retention** — no lifecycle rule on the bucket, deliberately. A policy decision
   nobody has made.
2. **B2 (key rotation)** — until it lands, `ENCRYPTION_KEY` cannot be rotated. If it is ever
   exposed, the choice is between leaving it in place and destroying every stored SSN.
3. **RPM 10** — the quota request is pending. Extraction will pace at ~8 requests/minute, so a
   full loan file takes minutes. Priya should be told this is a quota limit, not a bug.
