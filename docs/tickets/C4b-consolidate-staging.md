# C4b — Consolidate into the staging account

**Branch:** `bedrock_integration`
**Depends on:** C4
**Blocks:** C5 (deploy)
**Target:** account **`058190633983`** (staging), `us-east-1`

---

## What this does and why

The current layout assumes two deployed accounts: a **tooling** account (`591554480818`)
holding ECR and Terraform state, and a **workload** account holding everything else. That
assumption is no longer true.

- `envs/dev` is **never applied** — dev is local Docker Compose plus Bedrock calls from the
  laptop. It creates no AWS infrastructure.
- Production, when it comes, will be a **separate account with its own registry**.

So `infra/shared` — a cross-account ECR registry with repository policies, a dedicated KMS key,
and cross-account grant plumbing — exists to serve **exactly one consumer**: staging. That is a
whole mechanism earning nothing.

Worse, it carries a genuinely nasty failure mode: a cross-account pull without the
`kms:Decrypt` grant fails with an authorization error naming **KMS, not ECR**, which sends you
looking in the wrong service entirely.

**This ticket collapses everything into the staging account** and adopts S3-native state
locking. Nothing has ever been applied — the state bucket does not exist and `infra/bootstrap`
has no state file — so this is a clean edit, not a migration.

## Accepted trade-off, stated deliberately

With one registry per account, promoting a staging-validated image to production later means
either a cross-account pull (re-introducing this complexity at that point, where it would
genuinely serve two accounts) or rebuilding in production (a different digest from the artifact
you validated).

That decision belongs to when production exists, with real information. It is **not** being
pre-solved here. Record it in the result doc so the trade-off is visible rather than forgotten.

## Acceptance criteria

1. `infra/shared` no longer exists; ECR is created by `envs/staging`.
2. `infra/bootstrap` targets the staging account only, with a single state.
3. All state locking uses `use_lockfile`; no DynamoDB lock table anywhere.
4. `envs/staging/backend.tf` points at a bucket in `058190633983`.
5. No cross-account ECR plumbing remains active.
6. `envs/dev` still validates. The §6b grep over `infra/modules/` stays empty.
7. Nothing applied.

---

## Tasks

### 1. Bootstrap — staging only, single state

`infra/bootstrap` stays **one directory**. The two-state problem that would have required
splitting it disappears once the tooling account has nothing to bootstrap.

- `terraform.tfvars`: `aws_account_id = "058190633983"`,
  `state_bucket_name = "mbai-tfstate-058190633983"`, region unchanged
- **Remove the DynamoDB lock table resource entirely** — `use_lockfile` makes it unnecessary,
  and it has never been created
- Remove the `lock_table_name` variable
- The account guard now asserts `058190633983`
- Update `bootstrap/README.md`: this bootstraps the staging account, is applied once, and holds
  local state

The bucket keeps versioning, SSE-KMS, and blocked public access. Note in the result doc which
KMS key it uses — bootstrap runs before the environment CMK exists, so it is almost certainly
`aws/s3`. Say so rather than leaving it implicit.

### 2. `use_lockfile` everywhere

Replace `dynamodb_table = "mbai-tf-locks"` with `use_lockfile = true` in every `backend.tf`.

⚠️ **Never set both** — Terraform treats that as a conflict.

`use_lockfile` uses S3 conditional writes for locking, introduced in Terraform 1.10;
`dynamodb_table` was deprecated in 1.11. The repo is on **v1.15.8**.

⚠️ This was **not verified** — confirming it requires `terraform init`, which is out of scope
here. Flag it in the result doc as the first thing to check on the initial init. If v1.15.8
rejects it, `dynamodb_table` is the fallback and the table must be restored to bootstrap.

### 3. Dissolve `infra/shared`

Move ECR into `envs/staging` using the existing `modules/registry`.

- Delete `infra/shared/` entirely. It has never been applied and has no state, so there is
  nothing to import or move.
- `envs/staging/main.tf` calls `module "registry"` with `mbai/api` and `mbai/frontend`
- **Use the environment CMK** for repository encryption — not a dedicated key. One fewer key,
  one fewer thing to protect from deletion.
- Wire the repository URLs directly from the module output into the compute module.

### 4. Remove the cross-account plumbing

Now unused. Remove or neutralise:

- `ecr_registry_account_id` in `envs/staging` — repository URLs come from the module output
- `ecr_pull_account_ids` and its tfvars value
- The KMS key policy statement granting `kms:Decrypt` / `kms:DescribeKey` to another account

**In `modules/registry`, make `aws_ecr_repository_policy.cross_account_pull` conditional**
rather than deleting it — `count = length(var.pull_account_ids) > 0 ? 1 : 0`, with the variable
defaulting to `[]`. Production may genuinely need it later, and a count-gated resource with an
empty default is inert. Deleting working code you will want again is worse than gating it.

⚠️ C4's result doc records that `envs/staging` deliberately assembles repository URLs from a
variable **because** `data.aws_ecr_repository` resolves through the environment's own provider
and failed with `RepositoryNotFoundException` against the other account. That constraint
**disappears** once the registry is in the same account — a module output is now the correct
source. Note this in the result doc so the earlier reasoning is not re-applied later.

### 5. `envs/staging/backend.tf`

```hcl
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

Keep C4's explanatory comment, corrected: the bucket now lives in the **same** account as the
resources it describes, and there is no tooling-account exception.

A backend block cannot use variables — Terraform evaluates it before the variable graph exists.
This is the one place a literal account id is unavoidable.

### 6. `envs/dev`

`envs/dev` is a **reference template, never applied**. Its `backend.tf` describes a state file
that will never exist and points at a bucket that will never be created.

**Delete `envs/dev/backend.tf`.** `terraform validate` there already runs with
`-backend=false`, so nothing breaks, and it removes a file implying a deployment that never
happens.

Add a prominent note at the top of `envs/dev/main.tf` and in `infra/README.md`: this directory
exists to prove the modules take different values and as a starting point for a future
environment. It is not deployed.

⚠️ **Do not** repoint it at staging. An accidental `apply` in `envs/dev` would then write to
staging's state.

### 7. Documentation

**`infra/README.md`** — rewrite the apply order. It is now:

```
1. infra/bootstrap        (staging account, local state, once)
2. infra/envs/staging     phase 1  — enable_tls = false
   MANUAL: delegate staging.mortgageboss.ai at Namecheap
3. infra/envs/staging     phase 2  — enable_tls = true
```

No tooling-account step, no `infra/shared` step. Keep the pre-handover security checklist.

**`docs/tickets/C4b-consolidate-staging-result.md`** — what this ticket is, acceptance criteria
with evidence, what was implemented, and every assumption and decision with reasoning. Include:

- The production-registry trade-off from above, stated explicitly
- Which KMS key the bootstrap bucket uses
- That `use_lockfile` is unverified at v1.15.8 and what to do if init rejects it
- Why the `data.aws_ecr_repository` constraint no longer applies
- The revised monthly cost — removing a dedicated ECR KMS key saves ~$1

**`decisions.md`** — append ADRs. Read for the current maximum (C4 reached ADR-372) and
continue. At minimum: single-account consolidation, and `use_lockfile` over DynamoDB.

⚠️ **Do not change SSO or profile configuration.** Three separate sessions is a deliberate
choice for now; leave `~/.aws/config` alone and do not recommend otherwise in the docs.

---

## Verify

```bash
cd infra
terraform fmt -recursive -check
cd envs/staging && terraform init -backend=false && terraform validate
cd ../dev && terraform validate
cd ../../bootstrap && terraform init -backend=false && terraform validate
grep -rniE '058190633983|591554480818|us-east-1|\bstaging\b|\bdev\b|mbai-' infra/modules/
grep -rn "dynamodb_table\|mbai-tf-locks" infra/
grep -rn "591554480818" infra/
```

- All validates pass
- The §6b grep is empty or comments only
- **No `dynamodb_table` or `mbai-tf-locks` anywhere**
- **No `591554480818` outside comments** — the tooling account is no longer referenced
- `infra/shared/` does not exist

**Do not run `plan` or `apply`.**

---

## Stop and report — do not work around

- `modules/registry` requiring changes beyond gating the cross-account policy.
- Anything in `envs/staging` that depended on `infra/shared` outputs and cannot be sourced
  locally.
- `envs/dev` failing to validate after the module changes.
- Any remaining reference to the tooling account that cannot be removed.

## Do not

- `git push`. Commit locally with a clear message.
- Run `terraform apply`, `destroy`, or `plan`.
- Modify `~/.aws/config` or any SSO configuration.
- Set both `use_lockfile` and `dynamodb_table`.
- Repoint `envs/dev`'s backend at staging.
- Delete `modules/registry`'s cross-account policy resource — gate it.
- Create an Alembic migration or touch `app/`.
