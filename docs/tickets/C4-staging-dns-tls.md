# C4 — Staging environment: DNS, TLS, and access control

**Branch:** `bedrock_integration`
**Depends on:** C0, C1, C2, C3
**Blocks:** C5 (deploy and handover)
**Target:** account **`058190633983`** (staging), `us-east-1`, environment `staging`

---

## What this does and why

C2 and C3 produced modules validated against `envs/dev`, but **`envs/dev` will never be
applied** — dev is local-only (Bedrock from the laptop, no infrastructure). C4 creates the first
and only deployed environment: **staging**, at `staging.mortgageboss.ai`.

It adds what dev never needed:

- A real domain, delegated from Namecheap to Route 53
- TLS via ACM, with HTTP redirecting to HTTPS
- **Cognito on the ALB** — staging holds real borrower files and must not be openly reachable
- **VPC interface endpoints instead of NAT** — so egress never traverses the public internet
- The safety flags dev deliberately left off: deletion protection, final snapshots, a 30-day
  secret recovery window

## Acceptance criteria

1. `envs/staging` exists and validates, using the **same modules** as `envs/dev` with different
   values only. The §6b grep over `infra/modules/` stays empty.
2. A Route 53 hosted zone for `staging.mortgageboss.ai` with its four nameservers as an output.
3. An ACM certificate with DNS validation records created automatically in that zone.
4. HTTPS on 443; HTTP on 80 **redirects** rather than serving.
5. Cognito authentication on the **default** listener rule, covering `/api/*`.
6. VPC interface endpoints in **one AZ**, no NAT gateway.
7. The frontend image build documented with `NEXT_PUBLIC_API_URL=https://staging.mortgageboss.ai`.
8. Nothing applied. The user applies, in two phases.

---

## ⚠️ This apply is in TWO phases with a manual step between

Terraform cannot complete in one run. The sequence:

```
Phase 1   apply everything EXCEPT the ACM certificate and HTTPS listener
          → outputs four Route 53 nameservers
   ↓
MANUAL    user adds those four NS records at Namecheap for the
          staging.mortgageboss.ai subdomain, then waits for propagation
   ↓
Phase 2   apply the certificate and HTTPS listener
          → ACM validates against the now-delegated zone
```

**If phase 2 runs before delegation propagates, ACM sits in `PENDING_VALIDATION` and Terraform
waits until its timeout, then fails.** Nothing is broken, but it is a slow and confusing first
encounter.

Implement this with a variable — `enable_tls` (default `false`) — gating the ACM certificate,
the HTTPS listener, and the redirect. Phase 1 is `enable_tls = false`; phase 2 flips it to
`true`. Do **not** use `-target`; it is a debugging escape hatch, not a workflow.

Document both phases and the Namecheap step precisely in the result doc, including how to
verify delegation before attempting phase 2:

```bash
dig +short NS staging.mortgageboss.ai
```

Four `awsdns` nameservers means delegation is live.

---

## Established facts — use these, do not re-derive

**Both Bedrock VPC endpoints exist** in `us-east-1`, verified against this account:
`com.amazonaws.us-east-1.bedrock-runtime` and `com.amazonaws.us-east-1.bedrock-mantle`. This
closes the PENDING item from C2. Use `bedrock-runtime` — the app calls it via `us.` inference
profiles (B1, proven). Record that `bedrock-mantle` exists but is unused.

**Bedrock quotas in this account:** TPM 5,000,000, tokens/day 13,500,000, **RPM 10**. Identical
to dev. A request for 100 RPM is pending. `AI_REQUESTS_PER_MINUTE_BEDROCK = 8` with
`desired_count = 1`.

**Images are arm64** (C3, verified). `cpu_architecture = "ARM64"`.

**The documents bucket for staging does not exist yet** — C0's bucket is in the dev account.
Staging needs its own, and unlike dev's it should be **CMK-encrypted**, since it will hold real
borrower files. C3's compute module already renders the KMS statements when
`documents_bucket_kms_key_arn` is set.

⚠️ **Staging starts EMPTY.** No document sync from dev, no database seed. Dev documents are
development artifacts and have no place in an environment holding borrower NPI. The database
gets its schema from the migration task against an empty RDS instance.

---

## Tasks

### 1. `envs/staging`

Same modules as `envs/dev`. Every difference is a **value**, not code.

| Variable | staging | vs dev |
|---|---|---|
| `aws_account_id` | `058190633983` | different account |
| `environment` / `name_prefix` | `staging` / `mbai-staging` | |
| `vpc_cidr` | **must differ from dev's** | if they ever peer |
| `enable_nat_gateway` | `false` | dev used NAT |
| `enable_vpc_endpoints` | `true` | see task 2 |
| `rds_deletion_protection` | **`true`** | dev `false` |
| `rds_skip_final_snapshot` | **`false`** | dev `true` |
| `rds_multi_az` | `false` | revisit for production |
| `secret_recovery_window_days` | **`30`** | dev `0` |
| `log_retention_days` | `30` | |
| `budget_limit_usd` | **`300`** | dev's `150` would fire immediately |
| `enable_execute_command` | see task 6 | |
| `kms_create_alias` | `true` | staging is long-lived |

The account guard from C2 must assert `058190633983`.

### 2. VPC endpoints — single AZ (the cost decision)

Interface endpoints are ENIs billed **per endpoint per AZ**: ~$7.30/month each, so five
endpoints across two AZs is ~$73. In one AZ it is ~$36.50.

Place them in **one AZ**, and place all ECS tasks in that same AZ.

RDS still requires a two-AZ subnet group — but that is a constraint on the *subnet group
definition*, not on where anything runs. The second subnet exists and stays empty.

**What this keeps:** the full compliance property — no route to the internet from private
subnets, all AWS service traffic on the AWS network.

**What it gives up:** AZ redundancy. Acceptable because `desired_count = 1` and single-AZ RDS
mean there is no redundancy to lose.

Implement as a variable — `endpoint_availability_zones` — a list, set to one AZ. Production sets
two. Note in the result doc that **tasks and endpoints must move together**: tasks in an AZ
without a local endpoint work but incur cross-AZ transfer and lose the AZ independence.

Endpoints needed: `bedrock-runtime`, `ecr.api`, `ecr.dkr`, `logs`, `secretsmanager`, plus the
**free** S3 gateway endpoint (a route table entry, not an ENI — AZ-independent).

⚠️ **With no NAT, anything not covered by an endpoint is unreachable.** Audit the application
for outbound calls beyond those services — SMTP, any external HTTP client, any package fetch at
startup — and report what you find. A missed dependency **hangs** rather than failing cleanly,
which is a miserable thing to debug on a task with no shell.

### 3. Route 53

A hosted zone for `staging.mortgageboss.ai` — a **delegated subdomain**. The apex stays at
Namecheap and is never delegated to AWS.

- Output the four nameservers, clearly labelled as the values to enter at Namecheap
- An A-record alias for the zone apex → the ALB
- Do **not** create a zone for `mortgageboss.ai` itself

### 4. ACM and HTTPS

- Certificate for `staging.mortgageboss.ai`, `validation_method = "DNS"`
- Validation records created automatically in the zone from task 3
- `aws_acm_certificate_validation` so Terraform waits for issuance
- HTTPS listener on 443 with `ELBSecurityPolicy-TLS13-1-2-2021-06` or later — state which and
  why
- The **existing** port-80 listener changes from forwarding to a **301 redirect** to HTTPS

All of the above gated on `enable_tls` per the two-phase note.

⚠️ **The ALB target group health check is unaffected by listener rules** — it probes the target
directly. Confirm this and say so; if it were affected, every task would fail its check behind
Cognito and the service would never stabilise.

### 5. Cognito — access control

Staging must not be openly reachable. The app has JWT auth, but staging is where auth bugs live,
and an independent layer at the ALB means **unauthenticated requests never reach a task**.

- `aws_cognito_user_pool` — no self-registration, admin-created users only, MFA optional (make
  it a variable; recommend on)
- `aws_cognito_user_pool_domain` — the hosted UI
- `aws_cognito_user_pool_client` with the ALB callback URL
- `authenticate-cognito` as the **default listener action**

⚠️ **The auth action goes on the DEFAULT rule, so it covers `/api/*` too.** Excluding API paths
to avoid the XHR issue below would leave the upload endpoint open to the internet, defeating the
entire exercise. Do not do it.

⚠️ **Session timeout must be long — 7 days.** When an ALB session expires mid-use, an in-flight
`fetch` receives a 302 to the login page, which browser JavaScript cannot follow. The app then
fails in confusing ways rather than redirecting cleanly. A long session means expiry happens
between visits, not during one. State this in the result doc.

Users are created by hand — two people do not need self-signup. Give the
`aws cognito-idp admin-create-user` command in the result doc.

**IP allowlisting** as an optional extra: an `allowed_cidr_blocks` variable, default empty
(meaning no restriction), applied to the ALB security group. Not enabled — a home IP is dynamic
and Priya would have no idea why the site stopped working. Present as a lever, not a default.

### 6. ECS Exec — reconsider for staging

C3 enabled it and flagged it: this is a **shell inside a task holding decrypted secrets and
borrower NPI**, not a debugging convenience.

Set `enable_execute_command = false` for staging by default. Note in the result doc that it can
be flipped on temporarily for a specific debugging session and flipped back — and that doing so
requires a service update, which is the friction that makes it deliberate.

If you judge this makes staging undebuggable, say so and argue the other way rather than
silently flipping it.

### 7. Documents bucket

Create it in Terraform for staging — unlike dev's, which was hand-made.

- Name from a variable
- **SSE-KMS with the environment CMK**, not SSE-S3
- Block Public Access on, versioning on, TLS-only bucket policy
- `documents_bucket_kms_key_arn` wired into the compute module so the task-role KMS statements
  render

⚠️ **Lifecycle expiry: leave it unset and say so.** The FTU Safeguards Rule disposal provision
suggests an outer bound, but the retention decision was explicitly deferred. Do not invent a
number; flag it as an open decision in the result doc.

### 8. Frontend rebuild

`NEXT_PUBLIC_API_URL` is inlined at **build** time (C1), so it cannot be a task environment
variable. C3 deliberately left it unset because the ALB made everything same-origin.

Now the origin is real. The staging image must be built as:

```bash
docker buildx build --platform linux/arm64 \
  --build-arg NEXT_PUBLIC_API_URL=https://staging.mortgageboss.ai \
  -t <ecr>/mbai/frontend:staging ./frontend
```

Document this prominently. Also state that **CORS_ALLOWED_ORIGINS must be
`["https://staging.mortgageboss.ai"]`** — C3 left it at the localhost placeholder, and C3's
result doc verified the app parses this as JSON and refuses to start on a bare string, so this
one fails loudly.

### 9. Documentation

**`docs/tickets/C4-staging-dns-tls-result.md`** — what this ticket is, acceptance criteria with
evidence, what was implemented, and **every assumption and decision with reasoning**. Include:

- The exact two-phase apply sequence with the Namecheap step
- The four nameservers will not be known until phase 1 — say how the user retrieves them
- The outbound-dependency audit from task 2
- The ECS Exec recommendation and its argument
- The Cognito user-creation command
- Revised monthly cost with single-AZ endpoints
- What is still needed before handover (C5)

**`infra/README.md`** — add staging to the apply order, the two-phase note, and a
**pre-handover security checklist**:
1. Remove or narrow the standing `AdministratorAccess` permission set on this account
2. Drop `BedrockDeveloper` — the worker task role invokes Bedrock, not a human
3. Confirm `enable_execute_command = false`
4. Confirm all secrets populated (an empty secret means a task that will not start)
5. Confirm MFA on every Cognito user
6. Confirm the budget alarm notification address receives mail

**Also record that `infra/envs/dev/` is a reference template, not a deployed environment.**
Otherwise someone will later assume infrastructure is missing there.

**`decisions.md`** — append ADRs. Read for the current maximum (C3 reached ADR-369) and continue.

---

## Verify

```bash
cd infra
terraform fmt -recursive -check
cd envs/staging && terraform init -backend=false && terraform validate
cd ../dev && terraform validate          # must still pass — modules changed
grep -rniE '058190633983|591554480818|us-east-1|\bstaging\b|\bdev\b|mbai-' infra/modules/
```

All must pass; the grep must be empty or comments only.

**Do not run `plan` or `apply`.**

---

## Stop and report — do not work around

- Any outbound dependency the endpoint set does not cover (task 2). With no NAT this is a hang,
  not an error.
- The ALB target group health check being affected by the Cognito listener action.
- Any Cognito configuration requiring the ALB DNS name before the ALB exists — a circular
  dependency Terraform cannot resolve.
- `enable_tls` gating that cannot cleanly separate the two phases.
- Any module change that breaks `envs/dev` validation.

## Do not

- `git push`. Commit locally with a clear message.
- Run `terraform apply`, `destroy`, or `plan`.
- Use `-target` to work around the two-phase problem.
- Create an Alembic migration.
- Put an account id, region, environment name, or domain in `modules/`.
- Seed staging with dev documents or a dev database dump.
- Enable ECS Exec by default.
- Put the Cognito auth action anywhere other than the default listener rule.
- Set a lifecycle expiry on the documents bucket.
