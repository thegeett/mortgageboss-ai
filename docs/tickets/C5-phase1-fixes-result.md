# C5 — phase-1 apply fixes

**Target:** account `058190633983` · `us-east-1` · `staging.mortgageboss.ai`
**Situation:** phase 1 created ~85 of 89 resources; four failed.
**Outcome:** fix-and-re-run. Nothing was rolled back, nothing was applied, nothing
was destroyed. Work ends at `fmt` + `validate`.

---

## Summary

| # | What failed | Root cause | Class |
|---|---|---|---|
| 1 | `aws_db_parameter_group.this` | em dash in `description` | non-ASCII → AWS API |
| 2 | `aws_elasticache_parameter_group.this` | em dash in `description` | non-ASCII → AWS API |
| 3 | `aws_lb_listener_rule.api_root_paths` | six path patterns, limit is five | AWS limit |
| 4 | `aws_ce_cost_allocation_tag.environment` | member account, not management | management-only |

Four more problems of the same three classes were found and fixed or ruled out —
**one of them would have failed the very next apply.** See *Also found*.

---

## 1 & 2 — em dash in AWS resource descriptions

```
InvalidParameterValue: The parameter Description must not contain
non-printable control characters.
```

`modules/data/main.tf:46` and `:187`. Both descriptions contained **U+2014 EM
DASH**:

```
"mbai-staging — forces TLS on every connection."
"mbai-staging — cache parameters."
```

The em dash is not a control character. The RDS and ElastiCache parameter-group
APIs simply validate their description fields against a narrower charset than the
error message admits — the message is misleading, which is part of why this was not
caught by reading.

**Fixed:** replaced with a plain ASCII hyphen.

### The full sweep

Every `.tf` under `infra/` was scanned — plus `.tfvars`, which the brief did not ask
for but which feeds values straight into resources. A plain grep is the wrong tool
here: **353** lines contain non-ASCII, and the distinction that matters is not the
line but the enclosing block. So the scan tracked the enclosing HCL block type.

| Where | Lines | Reaches an AWS API? |
|---|---|---|
| `#` comments | 201 | **No** — stripped before Terraform parses a value |
| `variable "…" { description }` | 112 | **No** — Terraform-side, for `terraform console` and humans |
| `output "…" { description }` | 40 | **No** — same |
| `resource "aws_…" { … }` | **6** | **YES** |
| `data` / `locals` / `module` / `provider` / `terraform` | 0 | — |
| `.tfvars` values | 0 | — |

**All six that reach an AWS API, all now ASCII:**

| File:line | Attribute | Sent as | Applied in phase 1? |
|---|---|---|---|
| `modules/data/main.tf:49` | `aws_db_parameter_group.description` | `CreateDBParameterGroup` | ❌ **failed** |
| `modules/data/main.tf:190` | `aws_elasticache_parameter_group.description` | `CreateCacheParameterGroup` | ❌ **failed** |
| `modules/data/main.tf:202` | `aws_elasticache_replication_group.description` | `CreateReplicationGroup` | ⚠️ **never attempted** |
| `modules/secrets/main.tf:45` | `aws_kms_key.description` | `CreateKey` | ✅ accepted |
| `modules/secrets/main.tf:112` | `aws_secretsmanager_secret.description` | `CreateSecret` | ✅ accepted |
| `modules/dns/main.tf:31` | `aws_route53_zone.comment` | `CreateHostedZone` | ✅ accepted |

**Two hits needed a second look and are NOT in the list:**

- `bootstrap/main.tf:125` — reads `description = "S3 bucket holding Terraform state
  — …"`, which looks exactly like a resource description. It is an **`output`**
  block. Terraform-side. Left alone.
- `modules/data/variables.tf:149` — matched a "non-ASCII on a `default` line" grep.
  The line begins *"defaults to NEVER EXPIRE…"* inside a `description` heredoc.
  A false positive. Left alone.

### Why the four that worked were changed anyway

Three of the six reached APIs that **accepted** U+2014 — the environment has a KMS
key, four secrets, and a hosted zone whose descriptions contain an em dash right
now. Per-API charset tolerance is undocumented and is discovered only by an apply
failing, so the four surviving coin flips were removed too. This is ADR-377.

⚠️ **Consequence for your re-run:** those three already exist, so normalising their
descriptions produces **three in-place updates** in the plan that are not related to
the four failures. All three are non-destructive metadata updates —
`UpdateKeyDescription`, `UpdateSecret`, `UpdateHostedZoneComment`. No replacement,
no downtime, no new ARNs. Expect them; they are not a surprise regression.

The two parameter-group descriptions are `ForceNew` in the provider (neither API can
modify a description after creation), but both resources failed to create, so they
are plain creates.

---

## 3 — listener rule exceeds the condition-value limit

```
ValidationError: A rule can only have '5' condition values and regex values
```

`modules/compute/alb.tf:263` listed six: `/health`, `/health/*`, `/docs`, `/docs/*`,
`/redoc`, `/openapi.json`.

⚠️ **The limit is per RULE, not per condition block** — counted across every block in
it. Splitting six values across three `path_pattern` blocks is the same violation.

**Fixed** in three parts.

**(a) Only `/health` and `/health/*` remain.** The four FastAPI paths are gone, not
moved to a second rule.

`/docs`, `/docs/*`, `/redoc` and `/openapi.json` are FastAPI's interactive
documentation and its OpenAPI schema: a complete, machine-readable map of every
endpoint, its parameters and its response shapes. Staging holds real borrower files.
They **would** be behind Cognito from phase 2 — this is not an open door — but
*"an authenticated user can enumerate the entire API surface"* is a weaker position
than *"the load balancer has no route to it"*, and holding the stronger one costs
nothing. Removing them also fixes the limit **without a second rule**, so the outage
fix and the better posture are the same edit.

Unrouted, those paths hit the frontend's default action and 404. The application
still serves them internally, so `curl` from inside the VPC is unaffected.

**(b) The list is now a variable.**

```hcl
variable "api_root_path_patterns" {
  type    = list(string)
  default = ["/health", "/health/*"]
}
```

A future environment that wants the docs — a public demo — adds them at the
environment level without editing the module.

**(c) A `validation` block, which is the part that actually matters.**

```hcl
validation {
  condition     = length(var.api_root_path_patterns) <= 5
  error_message = "…an ALB listener rule permits only 5 condition values and regex
                   values in total, counted across every condition block in the rule…"
}
```

Without it, the next person to add a sixth path learns about the limit the way this
ticket did — from a `ValidationError` **partway through an apply**, with the
environment half-created and a 10–15 minute RDS create already spent. The error
message names the limit *and its per-rule scope*, so the reader does not have to find
the ADR to understand what to do.

A second validation rejects an empty list, which would otherwise fail at apply time
on a `path_pattern` condition that requires at least one value.

⚠️ **`terraform validate` does NOT evaluate variable validations.** Verified: a
scratch module carrying the original six paths as its default passes
`terraform validate` cleanly, both with and without a reference to the variable. The
guarantee is **plan** time, which is what the brief asked for — but it is worth
knowing that the repo's `validate` step will not catch a future regression here.

What *was* verified without running a plan, via `terraform console`:

```
length(["/health","/health/*","/docs","/docs/*","/redoc","/openapi.json"]) <= 5  →  false
length(["/health","/health/*"])                                            <= 5  →  true
```

---

## 4 — cost allocation tag cannot be set from a member account

```
AccessDeniedException: Failed to update Cost Allocation Tag: Linked account
doesn't have access to cost allocation tags.
```

Cost Explorer tag activation is **management-account only**. `058190633983` is a
member account in the organization, so this can never succeed there. It is an
**organizational boundary, not an IAM gap** — no policy change inside the account
makes it work.

**Fixed without deleting the resource**, because deleting it would hide a silent
failure. ADR-373 established what it is load-bearing for: the `$300` budget filters
on `user:Environment$staging`, and **AWS Budgets matches nothing until that tag is
active**. An inactive tag produces no error, no warning, and no empty state — the
budget reports **$0 forever and never fires, while looking correctly configured in
the console.** It is a silent failure of a control whose whole job is making a
different failure loud.

| Change | File |
|---|---|
| `activate_environment_cost_allocation_tag = false`, with a comment saying **member account, not preference**, and what must happen instead | `envs/staging/terraform.tfvars` |
| The resource kept, `count`-gated as before; comment block records the error verbatim and why it stays | `envs/staging/main.tf` |
| Variable description gains the management-account-only constraint | `envs/staging/variables.tf` |
| New **MANUAL** step in the apply order: activate from the management account, 24h to report, budget inert until then | `infra/README.md` |
| Item 7 on the pre-handover security checklist | `infra/README.md` |
| Same on the C5 checklist (step 10) | `docs/tickets/C5-deploy-staging.md` |

A commented-out resource is a note that decays. A `count = 0` resource is a note that
`terraform plan` keeps putting in front of whoever runs it — and one a future
management-account root module adopts by flipping a variable **there**.

---

## Also found

The brief asked for anything else that would fail for the same three reasons.

### ⚠️ Would have failed the NEXT apply — `aws_elasticache_replication_group`

`modules/data/main.tf:202`:

```
description = "mbai-staging — cache and Celery broker."
```

It does not appear in the four reported errors **because it was never attempted**:
its `parameter_group_name` references `aws_elasticache_parameter_group.this.name`
(`:213`), which failed, so Terraform skipped every dependent. Fixing only the two
reported parameter groups would have unblocked it and sent an em dash to
`CreateReplicationGroup` on the re-run.

Whether that API rejects U+2014 is **unproven** — the parameter-group API does, and
the KMS/Secrets/Route 53 APIs do not. Fixed rather than gambled on. The same
dependency chain applies to `aws_db_instance` (`parameter_group_name` at `:131`), so
the database and the cache are both among the resources still to be created.

### Ruled out — other AWS limits

Every resource whose name has a documented length ceiling was rendered with
`name_prefix = "mbai-staging"` and measured. All well inside:

| | rendered | len | max |
|---|---|---|---|
| ALB name | `mbai-staging` | 12 | 32 |
| target group | `mbai-staging-frontend` | 21 | 32 |
| IAM role | `mbai-staging-frontend-task` | 26 | 64 |
| replication group id | `mbai-staging` | 12 | 40 |
| db identifier | `mbai-staging` | 12 | 63 |
| documents bucket | `mbai-staging-documents-058190633983` | 35 | 63 |
| cognito domain prefix | `mbai-staging-auth` | 17 | 63 |

The only other ALB condition list in the module is `["/api/*"]` — one value. IAM
inline policies are far short of the 10,240-character limit; the largest is the
worker's Bedrock statement at 8 ARNs.

### Ruled out — other management-account-only actions

```
grep -rn 'resource "aws_\(ce_\|organizations\|account\|servicequotas\|guardduty\|securityhub\|ram_\|cur_\)'
```

One hit: `aws_ce_cost_allocation_tag`, which is error 4. `aws_budgets_budget` is
per-account and works from a member account.

---

## Verification

```
terraform fmt -recursive -check                exit 0
validate: bootstrap                            Success! The configuration is valid.
validate: envs/staging                         Success! The configuration is valid.
validate: envs/dev                             Success! The configuration is valid.
```

**Non-ASCII rescan, by enclosing block type:**

```
resource   0        <- was 6
data       0
locals     0
module     0
provider   0
terraform  0
variable   112      exempt - Terraform-side only
output     40       exempt - Terraform-side only
.tfvars    0
```

**§6b grep over `infra/modules/`** — 12 hits under a deliberately broad pattern
(`mbai|0581906|5915544|us-east|us-west|staging|production|\bdev\b`), **all in `#`
comments or `description` strings**: "MUST BE true FOR STAGING AND PRODUCTION",
"a DEV dependency", `e.g. ["mbai/api", "mbai/frontend"]`. **No account id, region,
environment name, or `mbai-` literal in any HCL value.** Unchanged in character from
C4b.

**Not run, per the brief:** `terraform plan`, `apply`, `destroy`. The scratch module
used to probe `validate` behaviour was created outside the repo, had no provider, no
backend and no state, and was deleted.

---

## Decisions recorded

- **ADR-375** — FastAPI's documentation paths are not routed at the load balancer,
  and the root-path list is a variable with a 5-value ceiling
- **ADR-376** — the cost allocation tag resource stays, gated to zero, because the
  manual step it stands for is otherwise invisible
- **ADR-377** — strings that reach an AWS API are ASCII-only

ADR-377 was not among the two the brief nominated. It is here because the em dash is
house style across 353 lines of this repo and will be reached for again; a
convention that lives only in a ticket doc is one nobody finds.

---

## What the re-run should show

- **4 creates** that previously failed — two parameter groups, one listener rule,
  and nothing for the cost tag (now `count = 0`, so it simply disappears from the
  plan).
- **Everything downstream of the two parameter groups**, which was skipped rather
  than failed: the **RDS instance** (10–15 minutes) and the **ElastiCache
  replication group** among them.
- **3 in-place updates** from the ASCII normalisation of already-created resources —
  KMS key, four secrets, hosted zone. Expected, non-destructive.
- The listener rule now carries **2** path patterns, not 6.

⚠️ **Then, by hand, from the MANAGEMENT account:** activate the `Environment` cost
allocation tag. Nothing in any future apply will remind you, and until it is done —
plus up to 24 hours — the budget is inert.
