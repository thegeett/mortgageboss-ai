# Terraform state across accounts — what must change before staging is applied

**Read-only investigation.** Nothing was modified; no `terraform init/plan/apply/destroy`
was run; no AWS resource was created, changed, or deleted.

**DATA** = observed in the repository or returned by AWS.
**INFERENCE** = reasoned from that data, labelled as such.

---

## The headline

**DATA — the state bucket does not exist. Anywhere.**

```
$ aws s3 ls s3://mbai-tfstate-591554480818/ --recursive
An error occurred (NoSuchBucket) ... The specified bucket does not exist

$ aws s3api head-bucket --bucket mbai-tfstate-591554480818
An error occurred (404) ... Not Found
```

S3 bucket names are **globally unique**, and a bucket that exists in another account
returns `403`/`AccessDenied` rather than `NoSuchBucket`. The `NoSuchBucket` response
is therefore authoritative: no such bucket exists in any account.

Corroborated from the repository: `infra/bootstrap/` contains **no `terraform.tfstate`
on disk and none tracked in git** (only `main.tf`, `terraform.tfvars`, `README.md`,
`.terraform.lock.hcl`). `infra/bootstrap` uses local state, so an applied bootstrap
would have left a state file. It did not.

**⇒ `infra/bootstrap` has never been applied, and no Terraform state has ever been
written for any environment.**

This changes the shape of the problem entirely. **There is no state to migrate**, no
`terraform init -migrate-state`, no risk of orphaning resources. The cross-account
backend in `envs/staging/backend.tf` has never been used — it is a wrong value in a
file, not a wrong deployment. **This is a clean slate.**

---

## 1. `infra/bootstrap` — every file read

### Is the bucket name hardcoded, or built from a variable?

**DATA — neither. It is a plain variable, not a derivation.**

```hcl
variable "state_bucket_name" { type = string }   # main.tf:43
variable "lock_table_name"   { type = string }   # main.tf:48

resource "aws_s3_bucket"     "state" { bucket = var.state_bucket_name }   # :71
resource "aws_dynamodb_table" "locks" { name  = var.lock_table_name }     # :114
```

It is **not** `"mbai-tfstate-${var.aws_account_id}"` — the name is supplied whole.

**INFERENCE — this is better than the interpolated form for this purpose.** A derived
name would make the bucket name a function of the account, which reads tidily but
removes the ability to name a bucket anything else, and S3 names are a global
namespace where collisions are a real failure. Supplying it whole means bootstrapping
a second account is a **tfvars change with no code change**. The `${account_id}`
suffix convention is preserved by the *value*, not enforced by the code.

### Does bootstrap have an account guard, and would it block staging?

**DATA — yes, and yes.** `main.tf:59-68`:

```hcl
resource "terraform_data" "account_guard" {
  input = var.aws_account_id
  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.aws_account_id
      error_message = "Wrong AWS account: credentials resolve to ... Refusing to apply."
    }
  }
}
```

A `precondition`, not a `check` block — so it is a **hard plan failure**, not a
warning. Applying the current `terraform.tfvars` (`aws_account_id = "591554480818"`)
with staging credentials fails before creating anything.

**INFERENCE — this is protection, not an obstacle.** It is exactly what should stop a
mis-targeted bootstrap. Bootstrapping staging means supplying staging's account id in
tfvars, at which point the guard asserts the *intended* account.

### Local state, and is a `.tfstate` committed?

**DATA — local state by design** (`main.tf:19`: "Deliberately NO backend block").
**No `.tfstate` exists on disk and none is tracked in git.** The question of whether a
committed state file contains secrets is therefore **moot** — there is no file.

`infra/.gitignore` ignores `*.tfstate` and deliberately does not whitelist bootstrap's,
so committing it would require an explicit `git add -f`.

**INFERENCE — when bootstrap is applied, its local state will contain no secret
material.** The resources are an S3 bucket and a DynamoDB table; neither has a
credential attribute. That will remain true only while nothing secret-bearing is added
to this directory.

### `dynamodb_table` vs `use_lockfile`, and the pinned versions

**DATA:**

| Item | Value |
|---|---|
| Terraform | **v1.15.8** |
| AWS provider pin | **`~> 5.0`** (`main.tf:15`) — and in every module |
| All three backends | **`dynamodb_table = "mbai-tf-locks"`** |
| `use_lockfile` | **used nowhere** in `infra/` |

**⚠️ Correction worth making: the AWS provider version is not what governs this.**
The S3 backend is a **Terraform core** feature, not a provider resource — it is
initialised before providers load. The `~> 5.0` pin has no bearing on `dynamodb_table`
or `use_lockfile`.

**INFERENCE** (not verified, because verifying requires `terraform init`, which was
prohibited): `use_lockfile` (S3-native conditional-write locking) was introduced in
Terraform 1.10, and `dynamodb_table` was deprecated in 1.11. At v1.15.8 the current
configuration should still work but is expected to emit a deprecation warning on
`init`. Since **bootstrap has never been applied**, this is the ideal moment to adopt
`use_lockfile` and skip the DynamoDB table entirely — a table that does not exist yet
does not need migrating.

---

## 2. §6b grep over `infra/bootstrap/` — verbatim

This directory was never covered by the earlier greps, which targeted
`infra/modules/`.

```
$ grep -rniE '591554480818|058190633983|us-east-1|mbai-' infra/bootstrap/
infra/bootstrap/README.md:6:- **S3 bucket `mbai-tfstate-591554480818`** — versioned, SSE-KMS, public access
infra/bootstrap/README.md:8:- **DynamoDB table `mbai-tf-locks`** — hash key `LockID` (string),
infra/bootstrap/README.md:37:terraform import aws_s3_bucket.state mbai-tfstate-591554480818
infra/bootstrap/README.md:38:terraform import aws_dynamodb_table.locks mbai-tf-locks
infra/bootstrap/terraform.tfvars:5:aws_region        = "us-east-1"
infra/bootstrap/terraform.tfvars:6:aws_account_id    = "591554480818"
infra/bootstrap/terraform.tfvars:7:state_bucket_name = "mbai-tfstate-591554480818"
infra/bootstrap/terraform.tfvars:8:lock_table_name   = "mbai-tf-locks"
```

**Eight hits. Real HCL values: four — all in `terraform.tfvars`. Comments/prose: four —
all in `README.md`. Zero in any `.tf` file.**

**This is a PASS, not a violation.** The C2 ground rules say *"No hardcoded account
IDs, ARNs, or passwords in `.tf` files — variables and data sources"*, and
`terraform.tfvars` is the sanctioned home for exactly these values — the same
arrangement every `envs/*/terraform.tfvars` uses. `bootstrap/main.tf` is clean.

---

## 3. What must change to bootstrap staging

**The bucket name is NOT hardcoded, so there is no §6b violation to fix.** The
required changes are smaller than the framing assumed.

**⚠️ But there is a real obstacle the question did not anticipate: `infra/bootstrap`
uses LOCAL state and is a SINGLE directory.** Applying it twice with different
tfvars, in place, would have the second apply **overwrite the first's local state** —
Terraform would then believe the tooling account's bucket does not exist and try to
create it again. One directory holds one state.

Three ways out:

| Option | Change | Trade-off |
|---|---|---|
| **A. Workspaces** | `terraform workspace new staging`, one tfvars per account | No restructure; local state supports workspaces (`terraform.tfstate.d/staging/`). Workspace selection becomes an invisible, easy-to-forget prerequisite. |
| **B. Split directories** | `bootstrap/tooling/` + `bootstrap/staging/` | Explicit and unmissable — the directory *is* the account. Duplicates ~130 lines, or needs a shared module. |
| **C. Re-point the single tfvars** | Change the values to staging | Simplest, but see §D — the tooling account still needs a bucket for `infra/shared`. |

**INFERENCE — Option B is the better fit.** This repository has consistently preferred
making an environment boundary visible in the filesystem over encoding it in
invisible CLI state; that is precisely why `envs/dev` and `envs/staging` are separate
directories rather than workspaces, and why `infra/shared` was split into its own
state. A forgotten `terraform workspace select` on a **bootstrap** apply is the same
class of error the account guard exists to prevent — except the guard would catch it,
which is a point in Option A's favour. Either is defensible; Option C is not, because
of §D.

**No `.tf` change is required for bootstrap under any option** — only new tfvars,
plus (Option B) copying the directory.

---

## 4. Both `backend.tf` files, verbatim

**`infra/envs/dev/backend.tf`**

```hcl
terraform {
  backend "s3" {
    bucket         = "mbai-tfstate-591554480818"
    key            = "dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "mbai-tf-locks"
    encrypt        = true
  }
}
```

**`infra/envs/staging/backend.tf`**

```hcl
terraform {
  backend "s3" {
    bucket         = "mbai-tfstate-591554480818"
    key            = "staging/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "mbai-tf-locks"
    encrypt        = true
  }
}
```

**DATA — the only difference is `key`.** Bucket, region, lock table, and `encrypt` are
identical. Confirmed: staging's state would live in the **dev/tooling account**.

**There is a third**, and it is the one that is actually correct as written —
`infra/shared/backend.tf`, same bucket and table, `key = "shared/terraform.tfstate"`.
`infra/shared` genuinely targets account `591554480818`
(`shared/terraform.tfvars: aws_account_id = "591554480818"`), so its state belongs in
that account. **Do not "fix" this one.**

**INFERENCE — the staging comment is now misleading.** It reads *"Same bucket and lock
table as every other environment, with its own key — one state file per environment."*
That describes a single-account design and quietly justifies the cross-account
arrangement. It should say which account the bucket is in.

---

## 5–7. AWS observations

| # | Question | Result |
|---|---|---|
| 5 | `mbai-tfstate-591554480818` exists? | **DATA — NO. `NoSuchBucket` / `404`.** Not empty; absent. |
| 6 | `mbai-tf-locks` exists and is empty? | ⚠️ **BLOCKED** — `AccessDeniedException` on `dynamodb:DescribeTable` |
| 7 | State bucket in `058190633983`? | ⚠️ **BLOCKED** — no working credentials for that account |

**On #5 — "if empty, no `envs/dev` state was ever written."** It is not empty, it is
**non-existent**, which is a stronger version of the same conclusion: no state was
ever written for *any* environment, dev included.

**On #6 — INFERENCE:** the table almost certainly does not exist. It is created by the
same never-applied `infra/bootstrap` apply that would have created the bucket. The
check was blocked because the only working role is `BedrockDeveloper`, which has no
DynamoDB permission.

**On #7 — genuinely unknown.** Three of four profiles have expired SSO tokens:

```
mbai-dev            -> 591554480818   ✅ works (BedrockDeveloper)
mbai-dev-admin      -> Token has expired and refresh failed
mbai-staging        -> Token has expired and refresh failed
mbai-staging-admin  -> Token has expired and refresh failed
```

**⚠️ DATA — the profiles use THREE SEPARATE SSO SESSIONS**, so one login does not
authenticate the others:

```
[sso-session mbai-dev]        <- mbai-dev
[sso-session mbai-dev-admin]  <- mbai-dev-admin
[sso-session mbai]            <- mbai-staging AND mbai-staging-admin
```

To answer #7 yourself:

```bash
aws sso login --sso-session mbai
AWS_PROFILE=mbai-staging-admin aws s3api list-buckets \
  --query "Buckets[?contains(Name,'tfstate')].Name" --output text
```

---

## A. Commands to bootstrap staging with its own state bucket

Assumes **Option B** (split directories) from §3; with Option A, substitute
`terraform workspace new staging` for the directory change.

```bash
# ── 0. Log in. THREE separate SSO sessions — one login does not cover the others.
aws sso login --sso-session mbai-dev-admin      # tooling account 591…
aws sso login --sso-session mbai                # staging account 058…

# ── 1. Tooling account state bucket — needed for infra/shared (see §D).
cd infra/bootstrap                              # or bootstrap/tooling under Option B
AWS_PROFILE=mbai-dev-admin terraform init
AWS_PROFILE=mbai-dev-admin terraform apply      # guard asserts 591554480818

# ── 2. Staging account state bucket.
cd ../bootstrap/staging                         # Option B; or `terraform workspace new staging`
AWS_PROFILE=mbai-staging-admin terraform init
AWS_PROFILE=mbai-staging-admin terraform apply  # guard asserts 058190633983

# ── 3. Shared registry, in the TOOLING account, BEFORE staging.
#      Staging's task definitions reference these repositories by ARN, and the
#      cross-account pull grants live here.
cd ../../shared
AWS_PROFILE=mbai-dev-admin terraform init
AWS_PROFILE=mbai-dev-admin terraform plan -out=shared.tfplan
AWS_PROFILE=mbai-dev-admin terraform apply shared.tfplan

# ── 4. Staging, phase 1 (enable_tls = false, enable_cognito = false).
cd ../envs/staging
AWS_PROFILE=mbai-staging-admin terraform init   # picks up the NEW backend from B
AWS_PROFILE=mbai-staging-admin terraform plan -out=staging.tfplan
AWS_PROFILE=mbai-staging-admin terraform apply staging.tfplan
```

`terraform init` in step 4 is a **first** init, not a migration — there is no existing
state to move.

**Staging bootstrap tfvars** (new file):

```hcl
aws_region        = "us-east-1"
aws_account_id    = "058190633983"
state_bucket_name = "mbai-tfstate-058190633983"
lock_table_name   = "mbai-tf-locks"
```

---

## B. Exact new `infra/envs/staging/backend.tf`

```hcl
# State backend — created by ../../bootstrap APPLIED TO THE STAGING ACCOUNT.
#
# ⚠️ This bucket lives in 058190633983, the same account as the resources it
# describes. It is deliberately NOT the tooling account's bucket: state records
# every resource, and a workload account's state in another account means an
# identity there can read the whole shape of this one. `infra/shared` is the
# exception — it genuinely runs in the tooling account, so its state belongs there.
#
# A backend block cannot use variables or locals: Terraform evaluates it before the
# variable graph exists. This is the one place in the environment where literals are
# unavoidable.

terraform {
  backend "s3" {
    bucket       = "mbai-tfstate-058190633983"
    key          = "staging/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
```

**On `use_lockfile` vs `dynamodb_table`:** shown with `use_lockfile` because nothing
has been applied yet, so there is no table to migrate away from and no reason to adopt
a deprecated option in new configuration. **If you prefer to defer that decision**,
substitute `dynamodb_table = "mbai-tf-locks"` — the DynamoDB table is created by the
same bootstrap apply either way. **Do not set both**; Terraform treats that as a
conflict.

⚠️ **INFERENCE, not verified** — I could not run `terraform init` to confirm
`use_lockfile` is accepted at v1.15.8. Verify on the first init of step 4.

---

## C. Is a code change needed, or is it tfvars only?

**Neither purely. Precisely:**

| Change | Kind | Required? |
|---|---|---|
| `infra/bootstrap/*.tf` | Terraform code | **No change.** Fully parameterised. |
| Staging bootstrap tfvars | New tfvars | **Yes** — four values. |
| Two-state problem (§3) | New directory *or* a workspace | **Yes** — one directory cannot hold two accounts' state. |
| `infra/envs/staging/backend.tf` | Terraform config | **Yes** — bucket name. Cannot be a variable. |
| `infra/envs/dev/backend.tf` | Terraform config | See §D. |
| `infra/shared/backend.tf` | Terraform config | **No change — correct as written.** |
| `infra/modules/**` | Module code | **No change.** No account literal in any module. |

**⇒ No module code changes. One `backend.tf` value, one new tfvars, and a decision
about how bootstrap holds two states.**

---

## D. Is the tooling-account state bucket pointless?

**No — recommend KEEP (create it), but for a different reason than it was built for.**

The premise is right that `envs/dev` is never applied, so a `dev/terraform.tfstate`
key will never be written. But the bucket is not only dev's:

**DATA — `infra/shared` genuinely targets the tooling account** and needs state there:

```
infra/shared/terraform.tfvars:  aws_account_id = "591554480818"
infra/shared/backend.tf:        key = "shared/terraform.tfstate"
```

`infra/shared` holds the ECR repositories both accounts pull from, plus the KMS key
encrypting the image layers. It is applied, it is long-lived, and its state has to
live somewhere. Putting the tooling account's state in the *staging* account would
invert the very separation this exercise is about.

**⇒ Create `mbai-tfstate-591554480818` for `infra/shared`. It is not pointless; it was
just mis-scoped in its naming and documentation as "the dev bucket".**

**INFERENCE — worth doing at the same time:** since `envs/dev` will never be applied,
`infra/envs/dev/backend.tf` describes a state file that will never exist. Options, in
order of preference:

1. **Leave it and add a comment** saying dev is a reference template and this backend
   is never initialised. Cheapest, and matches how `envs/staging/README.md` already
   describes dev.
2. **Delete `envs/dev/backend.tf`.** `terraform validate` in that directory already
   runs with `-backend=false`, so nothing breaks, and it removes a file that implies a
   deployment that never happens.

Do **not** repoint it at staging — that would make an accidental `terraform apply` in
`envs/dev` write to staging's state.

---

## E. What else breaks applying these modules to a second account for the first time

### Already solved — verified, no action needed

**DATA — the cross-account ECR problem has been handled.** `envs/staging/main.tf`
assembles repository URLs and ARNs from `var.ecr_registry_account_id` rather than
using `data.aws_ecr_repository`, and the comment records why: a data source resolves
through *this* environment's provider, looked the repositories up in the workload
account, found nothing, and failed with `RepositoryNotFoundException`.

Both halves of the grant are implemented:

```
infra/shared/terraform.tfvars:27          ecr_pull_account_ids = ["058190633983"]
infra/modules/registry/main.tf:107        aws_ecr_repository_policy.cross_account_pull
infra/shared/main.tf:142                  Action = ["kms:Decrypt", "kms:DescribeKey"]
infra/envs/staging/terraform.tfvars:145   ecr_registry_account_id = "591554480818"
```

The KMS half is the one that would otherwise bite: without it the pull fails with an
authorization error naming **KMS, not ECR**, which sends you looking in the wrong
place.

**DATA — no provider aliases anywhere, and no account-id literal in any `.tf` outside
the three `backend.tf` files.** Every stack uses a single default provider, so
"which account" is decided entirely by the credentials in the environment. That is
the right design here; it also means **the profile is load-bearing on every command**
and a wrong `AWS_PROFILE` is caught only by the account guard.

### Not verified — check before applying

1. **⚠️ Bedrock model access is a per-account, per-region opt-in**, separate from
   quota. The ticket records the staging account's quotas as identical to dev
   (TPM 5,000,000 / RPM 10), which suggests it has been looked at — but quota and
   *model access* are different switches, and a model that is not enabled fails at
   invoke time with `AccessDeniedException`, which looks exactly like an IAM problem.
   Confirm in the staging account's Bedrock console, or:
   `aws bedrock list-foundation-models --by-provider anthropic`.
2. **The `us.` inference profile ARNs embed the account id** and are assembled in
   `envs/staging` from `var.aws_account_id` — correct by construction, but this is the
   first time they resolve to `058…`. C3 verified the profiles route to **three**
   regions (us-east-1, us-east-2, us-west-2); that finding is account-independent, but
   confirm the profiles exist in the staging account.
3. **New-account service quotas.** Fresh accounts carry lower defaults for VPCs,
   Elastic IPs, and ECS tasks. No NAT means no EIP is needed, which removes the most
   common one — but a brand-new account has not been exercised.
4. **`mbai-staging-documents-058190633983`** is a new S3 bucket in a global namespace;
   the name is unlikely to collide but is not guaranteed.
5. **Route 53 and ACM** are created in the staging account, which is correct — but the
   `staging.mortgageboss.ai` delegation is a manual step at Namecheap and cannot be
   verified until phase 1 has been applied.
6. **The budget alarm address** must actually receive mail in the new account.
7. **⚠️ Operational:** the three separate SSO sessions mean a `terraform apply` run
   with a stale token fails partway rather than at the start. Log in to both sessions
   before beginning, not between steps.

---

## Summary

1. **Nothing has ever been applied.** The state bucket does not exist, bootstrap has
   no state file. There is no migration to perform — this is a clean slate.
2. **Bootstrap is fully parameterised.** No hardcoded bucket name, no §6b violation.
   Bootstrapping a second account is tfvars, not code.
3. **The account guard already blocks the wrong-account apply**, and is a precondition
   (hard failure), not a warning.
4. **The real obstacle is that bootstrap is one directory with local state** and
   cannot hold two accounts' state as-is. Split the directory or use a workspace.
5. **The tooling-account bucket is still needed** — for `infra/shared`, not for
   `envs/dev`. Keep it; correct its documentation.
6. **Adopt `use_lockfile` now** rather than inheriting a deprecated `dynamodb_table`,
   since there is no existing table to migrate.
7. **The cross-account ECR problem is already solved**, including the KMS half that
   would otherwise produce a misleading error.
8. **Three AWS questions remain unanswered** — the lock table, any pre-existing
   staging bucket, and Bedrock model access — all blocked on expired SSO tokens.
   Commands are given above.
