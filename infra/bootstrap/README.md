# Bootstrap — apply once, then leave alone

Creates the one thing Terraform's S3 backend needs but cannot create for itself:

- **S3 bucket `mbai-tfstate-058190633983`** — versioned, SSE-KMS, public access
  fully blocked. Holds the state for `../envs/staging`.

**In the staging account (`058190633983`).** There is no second account to
bootstrap: `../envs/dev` is a reference template that is never applied, and
production will bootstrap its own when it exists. That is why this stays a single
directory with a single local state.

## No DynamoDB lock table

State locking uses **S3 conditional writes** (`use_lockfile = true` in the
backend), supported by the S3 backend since Terraform 1.10 and which deprecated
`dynamodb_table` in 1.11. One fewer resource, and no second service in the critical
path of every plan.

Nothing was ever applied under the old design, so there is no table to migrate away
from.

⚠️ `use_lockfile` has **not** been verified against the pinned Terraform (v1.15.8) —
confirming it requires `terraform init`, which was out of scope when this was
written. **It is the first thing to check on the initial init.** If it is rejected,
the fallback is `dynamodb_table` plus restoring an `aws_dynamodb_table` resource
here; see the C4b result doc.

## Which KMS key encrypts the bucket

The **AWS-managed `aws/s3` key**, not a customer-managed one — `sse_algorithm =
"aws:kms"` with no `kms_master_key_id`.

Deliberate: bootstrap runs *before* any environment exists, so the environment CMK
(created by `modules/secrets`) is not available to it. A CMK created here would be a
second chicken-and-egg — the key protecting state would itself need state — and
costs $1/month for no added control. The threat model for the state bucket is
"someone without S3 access reads it", which the managed key already covers.

## Why this directory is different

It uses **local state**. Every other directory uses the S3 backend this creates,
which is exactly why this one cannot.

## Apply

```bash
aws sso login --sso-session mbai        # the session the staging profiles use
cd infra/bootstrap
terraform init                          # no backend — local state
AWS_PROFILE=mbai-staging-admin terraform apply
```

Then, and only then, `../envs/staging` can `terraform init` and pick up the backend.

## Is `terraform.tfstate` committed?

**No — and `.gitignore` does not whitelist it.**

It contains no passwords or key material (a bucket has none), so committing it would
be *safe*. But it would become a liability the moment a secret-bearing resource is
added here, and it is a merge-conflict surface for a file Terraform rewrites on
every apply. The bucket is trivially re-importable if the local state is lost:

```bash
terraform import aws_s3_bucket.state mbai-tfstate-058190633983
```

If you do decide to commit it, check it for secrets first and use
`git add -f infra/bootstrap/terraform.tfstate` — the ignore rule is deliberately not
an exception, so the choice stays explicit.

## Destroying

**Don't.** The bucket carries `lifecycle { prevent_destroy = true }`. Destroying it
orphans every resource in the environment — Terraform would lose all knowledge of
what it created, and each resource would then need finding and deleting by hand.

If you genuinely need to tear the account down, destroy `../envs/staging` **first**,
confirm it is empty, then remove the `prevent_destroy` block and destroy this last.

## Account guard

`terraform_data.account_guard` fails the plan if the resolved credentials do not
match `var.aws_account_id`. A `precondition`, not a `check` block — a `check` only
produces a warning, and applying to the wrong account must be a hard stop.
