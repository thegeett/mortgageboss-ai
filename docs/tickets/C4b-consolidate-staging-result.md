# C4b — Consolidate into the staging account: result

**Ticket:** [`C4b-consolidate-staging.md`](C4b-consolidate-staging.md) · **Branch:** `bedrock_integration`
**Target:** account `058190633983` (staging), `us-east-1`
**Depends on:** C4 · **Blocks:** C5 (deploy)

---

## What this ticket is

C2–C4 built a two-account layout: a **tooling** account (`591554480818`) holding ECR
and Terraform state, and a **workload** account holding everything else. Both halves
of that assumption turned out to be wrong.

`envs/dev` is never applied — local development is Docker Compose plus Bedrock calls
from a laptop, creating no AWS infrastructure. And production, when it exists, will
be a separate account with its own registry. So `infra/shared` — a separate state, a
dedicated KMS key, repository policies, and cross-account grant plumbing — served
**exactly one consumer**: staging.

C4b collapses everything into the staging account and adopts S3-native state
locking. **Nothing was ever applied**, so this is a clean edit, not a migration.

**Nothing was applied here either.** No `plan`, no `apply`, no `destroy`. Work ended
at `fmt` + `validate`. `~/.aws/config` was not touched.

---

## Acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `infra/shared` gone; ECR created by `envs/staging` | ✅ | directory deleted; `module "registry"` in `envs/staging/main.tf` |
| 2 | `infra/bootstrap` targets staging only, single state | ✅ | `aws_account_id = "058190633983"`, one directory, local state |
| 3 | All locking uses `use_lockfile`; no DynamoDB table | ✅ | grep below |
| 4 | `envs/staging/backend.tf` points at a bucket in `058190633983` | ✅ | `bucket = "mbai-tfstate-058190633983"` |
| 5 | No cross-account ECR plumbing active | ✅ | `pull_account_ids` unset → empty default → policy not created |
| 6 | `envs/dev` still validates; §6b grep clean | ✅ | below |
| 7 | Nothing applied | ✅ | no plan/apply/destroy run |

### Verify output

```
terraform fmt -recursive -check          exit 0
validate: bootstrap                      Success! The configuration is valid.
validate: envs/dev                       Success! The configuration is valid.
validate: envs/staging                   Success! The configuration is valid.
```

**`dynamodb_table` / `mbai-tf-locks`:**

```
$ grep -rn "dynamodb_table\|mbai-tf-locks" infra/
infra/bootstrap/main.tf:117:# deprecated `dynamodb_table` in 1.11. One fewer resource, one fewer thing to
infra/bootstrap/README.md:…          (the documented fallback, if init rejects use_lockfile)
```

**Zero in any HCL value** — the only hits explain why there is no table.

**`591554480818`:**

```
$ grep -rn "591554480818" infra/
(no matches)
```

**Gone entirely**, including from `envs/dev/terraform.tfvars` — see *Decisions*.

**§6b grep over `infra/modules/`** — ten hits, all in `#` comments or `description`
strings ("MUST BE true FOR STAGING AND PRODUCTION", "a DEV dependency", etc.). No
account id, region, environment name, or `mbai-` literal in any HCL value. Unchanged
in character from C4.

---

## What was implemented

```
DELETED   infra/shared/                     (7 files — never applied, no state)
DELETED   infra/envs/dev/backend.tf         (described a state file that never existed)

infra/bootstrap/main.tf                     DynamoDB table + variable + output removed
infra/bootstrap/terraform.tfvars            → staging account, no lock table
infra/bootstrap/README.md                   rewritten
infra/envs/staging/backend.tf               → same-account bucket + use_lockfile
infra/envs/staging/main.tf                  registry module, cost-allocation tag, cross-account block removed
infra/envs/staging/variables.tf             ecr_registry_account_id removed; registry vars added
infra/envs/staging/terraform.tfvars         ditto
infra/envs/dev/main.tf                      "never applied" banner
infra/envs/dev/terraform.tfvars             tooling account → placeholder
infra/README.md                             header + apply order + destroy section rewritten
```

`modules/registry` needed **no change** — its cross-account policy was already
`for_each`-gated on `length(var.pull_account_ids) > 0`, with the variable defaulting
to `[]`. Leaving `pull_account_ids` unset in `envs/staging` makes the resource inert
without deleting code that production may want.

---

## Decisions and assumptions

### The production-registry trade-off — stated, not solved

With one registry per account, promoting a staging-validated image to production
later means one of:

- **A cross-account pull** — re-introducing the plumbing just deleted, at a point
  where it would finally serve two accounts rather than one and therefore earn its
  complexity; or
- **Rebuilding in production** — simpler, but produces a **different digest from the
  artifact that was validated**, which weakens the meaning of "we tested this build".

**This is deliberately not pre-solved.** The decision needs production to exist and
real information about how releases will work. It is recorded here and in **ADR-373**
so it is visible rather than forgotten — the resource to un-gate is
`aws_ecr_repository_policy.cross_account_pull` in `modules/registry`, plus a
`kms:Decrypt` grant on the environment CMK for the pulling account.

### Which KMS key the bootstrap bucket uses

**The AWS-managed `aws/s3` key** — `sse_algorithm = "aws:kms"` with no
`kms_master_key_id`.

Deliberate, and stated rather than left implicit: bootstrap runs **before any
environment exists**, so the environment CMK (created by `modules/secrets`) is not
available to it. A CMK created inside bootstrap would be a second chicken-and-egg —
the key protecting state would itself need state — and costs $1/month for no added
control. The threat model for a state bucket is "someone without S3 access reads
it", which the managed key already covers.

### ⚠️ `use_lockfile` is NOT verified at v1.15.8

Confirming it requires `terraform init`, which was out of scope.

**Check this first on the initial init.** If Terraform rejects `use_lockfile`, the
fallback is mechanical:

1. In `infra/envs/staging/backend.tf`, replace `use_lockfile = true` with
   `dynamodb_table = "mbai-tf-locks"`.
2. Restore the lock table in `infra/bootstrap/main.tf`:

```hcl
resource "aws_dynamodb_table" "locks" {
  name         = "mbai-tf-locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
  lifecycle { prevent_destroy = true }
}
```

3. Apply bootstrap **before** initialising staging.

⚠️ **Never set both** — Terraform treats that as a conflict.

**Version note worth carrying forward:** the S3 backend is a **Terraform core**
feature, initialised before providers load. The `~> 5.0` AWS provider pin has no
bearing on it — the version that matters is Terraform's (v1.15.8). An earlier
investigation reached for the provider version when reasoning about this.

### Why the `data.aws_ecr_repository` constraint no longer applies

C4's result doc records that `envs/staging` deliberately **assembled** repository
URLs from `ecr_registry_account_id` rather than looking them up, because
`data.aws_ecr_repository` resolves through the environment's **own provider** —
it searched the workload account, found nothing, and failed the plan with
`RepositoryNotFoundException`.

**That constraint is gone.** The registry is now in the same account *and the same
state*, so a **module output** is the correct source — better than either the old
data source or the string assembly, because it creates a real dependency edge rather
than a coincidence of matching strings.

This is noted in `envs/staging/main.tf` itself, next to the module call, specifically
so the old reasoning is not re-applied by someone who finds the C4 doc later.

### ⚠️ The cost-allocation tag had to move, and this was nearly a silent breakage

`infra/shared` also held `aws_ce_cost_allocation_tag.environment`, which is
**account-level**, not environment-level.

The staging budget filters on `user:Environment$staging`, and **AWS Budgets matches
nothing until that tag is activated as a cost allocation tag.** Deleting `shared`
without moving it would have left the budget reporting **$0 forever and never
firing** — while looking correctly configured in the console.

It now lives in `envs/staging/main.tf`, with `activate_environment_cost_allocation_tag`
as its variable and a warning that **only one root module per account may set it
true** — a second environment in the same account would have two states fighting
over one account-wide setting.

This was not called out in the ticket; it was found by reading what `shared` actually
contained before deleting it.

### `envs/dev` — deleted backend, added banner, neutralised account

`envs/dev/backend.tf` is **deleted**: it described a state file that would never
exist. `terraform validate` there already runs with `-backend=false`, so nothing
breaks. It was **not** repointed at staging — an accidental `apply` in `envs/dev`
would then write to staging's state.

A banner at the top of `envs/dev/main.tf` and a callout in `infra/README.md` say the
directory is a reference template.

**Going slightly beyond the ticket:** `envs/dev/terraform.tfvars` still carried
`aws_account_id = "591554480818"` and `mbai-dev-documents-591554480818`. Both are now
placeholders (`000000000000`), because the ticket's own verify step requires no
`591554480818` outside comments, and a real-but-unused account id in a never-applied
template invites someone to believe it is live. `terraform validate` does not read
tfvars, so this costs nothing.

### `infra/README.md` — corrections beyond the apply order

Rewriting the apply order surfaced three sections that had gone stale:

- A **"Migrating an already-applied environment"** section describing how to move ECR
  *into* `infra/shared` — the exact opposite of what now happens. Removed.
- A pre-deploy step to **sync 4,562 documents to S3**. C4 established that **staging
  starts empty** — dev documents are development artifacts with no place in an
  environment holding borrower NPI. Replaced with an explicit "do not sync" note.
- A **destroy-and-rebuild** section describing the dev template's disposable flags.
  Staging inverts all of them (`rds_deletion_protection = true`,
  `rds_skip_final_snapshot = false`, `secret_recovery_window_days = 30`,
  `ecr_force_delete = false`). Rewritten so the refusals read as intended rather than
  as obstacles.

The pre-handover security checklist is unchanged, as instructed.

### SSO configuration untouched

`~/.aws/config` was not modified and the three separate SSO sessions are not
questioned anywhere in the docs. The apply order simply notes that the staging
profiles use the `mbai` session, so the right `aws sso login` is obvious.

---

## Revised monthly cost

Removing the dedicated ECR KMS key saves **~$1/month**. Removing the DynamoDB lock
table saves a negligible amount (`PAY_PER_REQUEST`, a handful of requests per plan) —
its value was never cost.

| Item | C4 | C4b |
|---|---|---|
| Environment CMK | $1.00 | $1.00 |
| **Dedicated ECR CMK** | **$1.00** | **— removed** |
| DynamoDB lock table | ~$0.00 | — removed |
| Everything else | ≈ $165 | ≈ $165 |
| **Total** | **≈ $167** | **≈ $166** |

Against the $300 budget. The saving is not the point — one fewer key to protect from
deletion, and one fewer service in the critical path of every plan, are.

---

## What to check on the first apply

1. **⚠️ `use_lockfile` is accepted by v1.15.8.** First thing on the initial
   `terraform init`. Fallback fully specified above.
2. **The account guard asserts `058190633983`** in both bootstrap and staging — a
   `precondition`, so a wrong-account apply is a hard plan failure.
3. **`Environment` cost-allocation tag activates.** Until it does, the budget cannot
   match anything. It can take up to 24 hours to begin reporting after activation.
4. Everything still outstanding from C4: the RDS CA bundle for `PGSSLROOTCERT`, the
   frontend rebuild with `NEXT_PUBLIC_API_URL`, populating all four secrets, applying
   the Redis AUTH token out of band, and Bedrock **model access** in the staging
   account — which is a separate switch from quota and fails at invoke time looking
   like an IAM problem.
