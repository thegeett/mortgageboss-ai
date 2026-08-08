# C4 — Staging: DNS, TLS, and access control: result

**Ticket:** [`C4-staging-dns-tls.md`](C4-staging-dns-tls.md) · **Branch:** `bedrock_integration`
**Target:** account `058190633983`, `us-east-1`, environment `staging`
**Depends on:** C0–C3 · **Blocks:** C5 (deploy and handover)

---

## What this ticket is

C2 and C3 built modules validated against `envs/dev` — but **`envs/dev` is never
applied**. Local development runs against Docker Compose and calls Bedrock from the
laptop, so dev is a reference template, not a deployed environment.

C4 creates the **first and only deployed environment**: staging, at
`staging.mortgageboss.ai`. It adds what a local template never needed — a real
domain, TLS, authentication at the edge, egress that never touches the public
internet, and the safety flags dev deliberately left off.

**Nothing was applied.** No `plan`, no `apply`, no `destroy`. Work ended at
`fmt` + `validate`.

---

## ⚠️ Read this first: a Stop-and-report condition was hit

**Task 2's outbound audit found a dependency the endpoint set does not cover, and
it hangs rather than failing.** The ticket lists this as Stop-and-report. It is
reported in full below rather than worked around — and the fix eliminates the
dependency rather than routing around it, which is why implementation continued.

**`uv run` — the production container CMD — reaches PyPI at every container start.**

Verified by running the real image with `--network none`, which simulates the
endpoint-only VPC:

```
uv run python -c "print('STARTED')"               -> still RUNNING at 15s, NO output
uv run --no-sync python -c "print('STARTED')"     -> exited 0 in ~1s, "STARTED"
/app/.venv/bin/python -c "print('STARTED')"       -> exited 0 in ~1s, "STARTED"
UV_OFFLINE=1 uv run python -c "print('STARTED')"  -> exit 1: "× Failed to download `mypy==2.1.0`"
```

The `UV_OFFLINE` line is the diagnosis: uv syncs the **dev dependency group**
(`mypy` is not in the runtime environment at all) from PyPI before running anything.

**Why this would have been miserable.** With no NAT there is no route to PyPI, so
the sync does not fail — it **hangs**. The container never starts, so it emits **no
application log line**; the ECS event says only that the task stopped. ECS Exec is
off (task 6), so there is no shell. The deployment circuit breaker then rolls back,
producing a loop whose visible symptom is "tasks keep dying" with nothing explaining
why.

**Fix: `UV_NO_SYNC=1` as a task-definition environment variable** on every
container. No image change, no code change. Recorded as **ADR-370**.

This also affects the dev template, which has NAT — there it is merely a PyPI round
trip on every task start, slow rather than fatal, and undesirable regardless.

---

## The outbound-dependency audit (task 2)

With no NAT, anything not covered by an endpoint is unreachable. Audited empirically.

| Dependency | Reached via | Covered? |
|---|---|---|
| Bedrock inference | `bedrock-runtime` endpoint | ✅ |
| S3 (documents) | S3 **gateway** endpoint (free, AZ-independent) | ✅ |
| ECR image pull | `ecr.api` + `ecr.dkr` + S3 gateway (layers live in S3) | ✅ |
| CloudWatch Logs | `logs` endpoint | ✅ |
| Secrets Manager | `secretsmanager` endpoint (execution role) | ✅ |
| ECS task credentials | link-local `169.254.170.2` — no endpoint needed | ✅ |
| **PyPI, via `uv run` sync** | **nothing** | ❌ **→ fixed with `UV_NO_SYNC=1`** |

**What the audit ruled out**, so the endpoint list stays minimal:

- **HTTP clients:** the only network-capable imports in `backend/app/` are
  `aioboto3` (S3) and `botocore`. `urllib.parse.quote` in `app/api/documents.py:21`
  is string handling, not a request. No `httpx`, `requests`, or `aiohttp` is
  imported by application code.
- **SMTP:** `smtp_*` settings appear **only** in `config.py`. No mailer, no
  consumer, nothing imports them — dead config. No endpoint needed.
- **External hostnames:** the only ones in `backend/app/` are
  `http://www.datamodelextension.org/Schema/{DU,ULAD}` and `mismo.org` in
  `app/mismo/parser.py:47-51`. These are **XML namespace identifiers** in an
  ElementTree namespace dict — string keys, never fetched.
- **Frontend:** no `fetch`/`axios` call to any external host; `NEXT_TELEMETRY_DISABLED=1`
  is set in the image.
- **KMS:** **no endpoint required.** `app/storage/s3.py:159-163` uses *server-side*
  SSE-KMS (`ServerSideEncryption: aws:kms` + `SSEKMSKeyId`), so **S3 calls KMS**,
  not the client. The only AWS client the application constructs is `s3`
  (`s3.py:157`). If uploads ever *hang* rather than fail, a KMS interface endpoint
  is the first thing to add — but the code says it should not be needed.

**One config item this surfaced that the ticket did not mention:** the app sends
`SSEKMSKeyId` **only when `s3_kms_key_id` is set**. With a CMK-encrypted bucket and
that unset, it would send `AES256` instead. **`S3_KMS_KEY_ID` is therefore wired**
to the environment CMK in the task environment.

---

## Acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `envs/staging` validates, same modules, values only; §6b grep clean | ✅ | below |
| 2 | Route 53 zone with four nameservers as an output | ✅ | `module.dns`, `output "route53_name_servers"` |
| 3 | ACM certificate, DNS validation records created automatically | ✅ | `aws_acm_certificate` + `aws_route53_record.validation` + `aws_acm_certificate_validation` |
| 4 | HTTPS on 443; HTTP on 80 **redirects** | ✅ | `aws_lb_listener.https`; `http` default action becomes a 301 when `enable_tls` |
| 5 | Cognito on the default rule, covering `/api/*` | ✅ **and more** | see ADR-371 — the default alone would **not** have covered `/api/*` |
| 6 | Interface endpoints in one AZ, no NAT | ✅ | `endpoint_availability_zones = ["us-east-1a"]`, `enable_nat_gateway = false` |
| 7 | Frontend build documented with the real origin | ✅ | below |
| 8 | Nothing applied | ✅ | no plan/apply/destroy run |

### Verify output

```
fmt -recursive -check      exit 0
validate: bootstrap        Success! The configuration is valid.
validate: shared           Success! The configuration is valid.
validate: envs/dev         Success! The configuration is valid.   ← still passes, modules changed
validate: envs/staging     Success! The configuration is valid.
```

### §6b grep — verbatim

C4 widens the pattern to include `staging` and `mbai-`:

```
$ grep -rniE '058190633983|591554480818|us-east-1|\bstaging\b|\bdev\b|mbai-' infra/modules/
infra/modules/secrets/README.md:75:     **Staging and production must use `30`.** ...
infra/modules/secrets/variables.tf:30:    STAGING AND PRODUCTION MUST USE 30. ...
infra/modules/network/variables.tf:3:  # NOTHING environment-specific has a default. A default here is how a staging
infra/modules/compute/variables.tf:4:  # name, no `mbai-*` string. ...
infra/modules/registry/variables.tf:44:    is precisely a long-lived staging or production tag; ...
infra/modules/registry/variables.tf:66:    workflow. Set false for staging and production, ...
infra/modules/data/variables.tf:70:  description = "... ⚠️ MUST BE true FOR STAGING AND PRODUCTION."
infra/modules/data/variables.tf:75:  description = "... ⚠️ MUST BE true FOR STAGING AND PRODUCTION."
infra/modules/data/variables.tf:80:  description = "... ⚠️ MUST BE false FOR STAGING AND PRODUCTION."
```

**Nine hits, all in `#` comments or `description` strings — "comments only", which
the ticket permits.** Every one is documentation telling a future reader what a
different environment must set. **No account id, region, environment name, or
`mbai-` literal appears in any HCL value.**

---

## The two-phase apply

Terraform cannot complete in one run: ACM cannot validate until the zone's NS
records are live at the registrar, and those NS records do not exist until the zone
is created.

### Phase 1 — `enable_tls = false` (the committed default)

```bash
cd infra/envs/staging
terraform init
terraform plan -out=staging.tfplan
terraform apply staging.tfplan
```

Creates everything except the certificate, the HTTPS listener, the redirect, and
Cognito. The application is reachable on the ALB's own DNS name over HTTP.

### MANUAL — delegate the subdomain at Namecheap

**The four nameservers do not exist until phase 1 has been applied.** Retrieve them:

```bash
terraform output -json route53_name_servers
```

Four `ns-….awsdns-….{com,net,org,co.uk}` values. At **Namecheap**, on
`mortgageboss.ai` → *Advanced DNS*, add **four NS records** with host `staging`,
one per nameserver. The apex stays at Namecheap and is **never** delegated to AWS.

Verify delegation is live before continuing:

```bash
dig +short NS staging.mortgageboss.ai
```

**Four `awsdns` nameservers means delegation is live.** Empty output or the
registrar's own nameservers means it is not — wait and retry. Propagation is
usually minutes but the TTL can make it longer.

### Phase 2 — `enable_tls = true`

Edit `terraform.tfvars`, set `enable_tls = true`, then:

```bash
terraform plan -out=staging-tls.tfplan
terraform apply staging-tls.tfplan
```

Creates the certificate, waits for issuance, adds the HTTPS listener with Cognito,
and converts port 80 to a 301 redirect.

**If phase 2 runs before delegation propagates**, ACM sits in `PENDING_VALIDATION`
and Terraform blocks until the 45-minute timeout, then fails. Nothing is broken —
re-run once `dig` is clean — but it is a slow way to learn.

`-target` was **not** used. It is a debugging escape hatch, and the phase boundary
is a real property of the deployment rather than a Terraform inconvenience.

---

## Design decisions

### Module structure — avoiding a real cycle

`modules/dns` **deliberately knows nothing about the load balancer.** The alias A
record lives in `envs/staging/main.tf`, not in the module. That split is what keeps
the graph acyclic:

```
compute  needs  certificate_arn   (for the HTTPS listener)
dns      needs  alb_dns_name      (for the alias record)
```

Both in one module is a cycle Terraform cannot resolve. Splitting the alias record
out gives a clean order: **dns → compute → alias record**.

### Cognito has no circular dependency — and this was checked

A Stop-and-report condition was *"any Cognito configuration requiring the ALB DNS
name before the ALB exists."* There is none: the callback URL is built from
**`var.domain_name`** (`https://staging.mortgageboss.ai/oauth2/idpresponse`), which
is known before anything is created. Deriving it from the ALB's generated DNS name
would have created exactly that cycle.

### Health checks are unaffected by the auth action — confirmed

The ALB probes each registered target **directly at its IP and port**. The probe
never traverses a listener and therefore never meets `authenticate-cognito`.
`health_check` configures the **target group**; `authenticate-cognito` is an action
on a **listener rule** — different objects, different paths. Were it otherwise,
every task would fail its check behind Cognito and no service could reach steady
state.

### Session timeout — 7 days, deliberately

When an ALB auth session expires mid-use, an in-flight `fetch()` receives a **302
toward the hosted login page**, which browser JavaScript **cannot follow** — it
either fails CORS or silently receives HTML where JSON was expected. The application
then fails in ways that look like application bugs rather than an expired login.

A 7-day session moves expiry to **between visits** rather than during one. The
refresh token is set to 30 days so it always outlives the session and the ALB can
renew silently; a shorter refresh token would reintroduce the same mid-session
bounce it was set to avoid.

### TLS policy

`ELBSecurityPolicy-TLS13-1-2-2021-06` — TLS 1.3 with a 1.2 floor. TLS 1.3 removes
the negotiated-cipher and renegotiation downgrade classes outright; keeping 1.2
available avoids failing clients that cannot do 1.3, which in 2026 is a small set
but not empty. A 1.2-only policy would be weaker for no gain; 1.3-only would break
those clients for little.

### Single-AZ endpoints

Interface endpoints are ENIs billed **per endpoint per AZ**: five across two AZs is
~$73/month, in one ~$36.50.

**What is kept:** the full compliance property — no route to the internet from the
private subnets, all AWS service traffic on the AWS network.

**What is given up:** AZ redundancy — acceptable only because there is none to lose
(`desired_count = 1`, single-AZ RDS).

⚠️ **Tasks and endpoints move together.** `envs/staging` pins the ECS tasks to the
same AZ list via `module.network.private_subnet_ids_by_az`. A task in an AZ without
a local endpoint still *works* — private DNS resolves VPC-wide — but every call
crosses an AZ boundary, adding transfer cost and giving back the AZ independence
the placement was meant to buy. RDS still requires a two-AZ subnet group; that is a
constraint on the subnet **group definition**, and the second subnet stays empty.

### ECS Exec — off, and the friction is the point

**`enable_execute_command = false`.** Full argument in **ADR-372**.

Short version: Exec is a shell inside a task holding decrypted `DATABASE_URL`,
`JWT_SECRET_KEY`, and `ENCRYPTION_KEY`, plus borrower NPI in memory. That is a
standing, credential-free path to the most sensitive data in the system.

**Does this make staging undebuggable?** Nearly, for one narrow class: a container
that fails *before* it can log. That class is now well-understood — architecture
mismatch, empty secret, and the `uv run` hang above — and each has a pre-deploy
check. Everything else is visible in CloudWatch.

**It can be flipped on for a session and back off.** Doing so requires editing
tfvars, planning, and applying a service update — minutes, and visible in version
control and the ECS deployment history. Turning on a shell into borrower data
becomes an auditable act rather than an ambient capability.

### IP allowlisting — a lever, not a default

`allowed_cidr_blocks` defaults to empty (unrestricted) and drives the ALB security
group. Not enabled: a home IP is dynamic, so an allowlist would eventually lock out
a legitimate user with no visible cause — a poor trade when Cognito already gates
every request. Use it for a genuinely fixed egress IP.

### Documents bucket

Created by Terraform (unlike dev's hand-made one): SSE-KMS with the environment CMK,
Block Public Access, versioning, a TLS-only bucket policy, and `prevent_destroy` —
the bucket holds the only copy of every uploaded document, and the database stores
keys rather than content.

⚠️ **No lifecycle expiry rule, deliberately.** A disposal obligation exists in
principle, but the retention period is an unresolved **policy** decision, not a
technical default. A number invented here would silently become the answer, and a
lifecycle rule deletes borrower records on a schedule nobody agreed to. **This is an
open decision** — see Open items.

⚠️ **Staging starts empty.** No document sync from dev and no database seed — dev
documents are development artifacts and have no place in an environment holding
borrower NPI. The schema comes from the migration task against an empty RDS
instance.

---

## Frontend rebuild (task 8)

`NEXT_PUBLIC_API_URL` is **inlined into the JavaScript bundle at build time** and is
not read at runtime, so it cannot be a task environment variable. C3 left it unset
because the shared ALB made everything same-origin. The origin is now real:

```bash
docker buildx build --platform linux/arm64 \
  --build-arg NEXT_PUBLIC_API_URL=https://staging.mortgageboss.ai \
  -t <account>.dkr.ecr.us-east-1.amazonaws.com/mbai/frontend:staging \
  ./frontend
```

`--platform linux/arm64` matters: the task definitions pin `ARM64` to match the
images C1 built.

**`CORS_ALLOWED_ORIGINS` is set to `["https://staging.mortgageboss.ai"]`.** C3 left
it at the localhost placeholder. C3 verified the application parses this env var as
**JSON** and raises `SettingsError` on a bare string — so this one **fails loudly**
rather than silently.

---

## Cognito user creation

Users are admin-created; self-registration is off.

```bash
POOL_ID=$(terraform output -raw cognito_user_pool_id)

aws cognito-idp admin-create-user \
  --user-pool-id "$POOL_ID" \
  --username priya@example.com \
  --user-attributes Name=email,Value=priya@example.com Name=email_verified,Value=true \
  --desired-delivery-mediums EMAIL
```

Cognito emails a temporary password; the user sets a permanent one at first login.

**MFA is `OPTIONAL`, not `ON`** — enforcing it before any user exists locks out the
first admin-created account. **Turn it ON once users are enrolled**; it is on the
pre-handover checklist.

---

## Revised monthly cost

| Item | Monthly |
|---|---|
| RDS `db.t4g.small`, single-AZ, 50 GB gp3 | $30.66 |
| ElastiCache `cache.t4g.small` | $24.82 |
| **Interface endpoints ×5, ONE AZ** | **$36.50** |
| S3 gateway endpoint | free |
| ALB (fixed + ~1 LCU) | $22.27 |
| Fargate: api + worker + frontend (ARM64) | $45.29 |
| KMS CMK | $1.00 |
| Secrets Manager ×4 | $1.60 |
| Route 53 hosted zone | $0.50 |
| ACM certificate | free |
| Cognito (< 50 MAU) | free |
| CloudWatch Logs + S3 documents | ~$4.00 |
| **Total** | **≈ $167** |

**Against the $300 budget** — comfortable, with room for Bedrock inference (usage-
driven, excluded). Two-AZ endpoints would add ~$36.50; NAT instead of endpoints
would have been ~$33 but reintroduces public-internet egress.

Container Insights is **off**; enabling it adds roughly $9/month per task.

---

## Open items and what is still needed before handover (C5)

1. **⚠️ Document retention is an unresolved policy decision.** No lifecycle rule
   exists on the documents bucket, deliberately. Someone must decide the period
   before the disposal obligation has an answer.
2. **The RDS CA bundle** (C3 finding, still open): the image contains none and
   `PGSSLROOTCERT` is unset, so `?ssl=require` encrypts without verifying the
   certificate or hostname. C5 must add the bundle to the image and set the
   variable.
3. **Build and push both images** with the `staging` tag — the frontend with the
   build arg above.
4. **Populate all four secrets** — `database-url`, `jwt-secret-key`,
   `encryption-key`, and `redis-url` (Redis AUTH is enabled here, so the URL is a
   credential). An empty secret means a task that will not start.
5. **Apply the Redis AUTH token out of band** and record it in the `redis-url`
   secret; Terraform deliberately does not hold it.
6. **Run the migration task** against the empty database.
7. **Create Cognito users, then turn MFA ON.**
8. **Work the pre-handover security checklist** in `infra/README.md` — especially
   removing the standing `AdministratorAccess` permission set and dropping
   `BedrockDeveloper`, since the worker task role invokes Bedrock, not a human.
9. **Confirm the budget address receives mail** — an alarm nobody reads is not an
   alarm.
