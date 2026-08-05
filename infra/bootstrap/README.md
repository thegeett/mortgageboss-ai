# Bootstrap — apply once, then leave alone

This directory creates the two things Terraform's S3 backend needs but cannot
create for itself:

- **S3 bucket `mbai-tfstate-591554480818`** — versioned, SSE-KMS, public access
  fully blocked. Holds the state for every environment under `../envs/`.
- **DynamoDB table `mbai-tf-locks`** — hash key `LockID` (string),
  `PAY_PER_REQUEST`. Prevents two people applying at once.

## Why this directory is different

It uses **local state**. Every other directory uses the S3 backend that this one
creates, which is exactly why this one cannot.

## Apply order

```bash
cd infra/bootstrap
terraform init          # no backend — local state
terraform apply         # the user runs this, not Claude
```

Then, and only then, `../envs/dev` can `terraform init` and pick up the backend.

## Is `terraform.tfstate` committed?

**No — and the `.gitignore` does not whitelist it.**

The reasoning: this state contains no passwords or key material (the bucket and
table have none), so committing it would be *safe*. But it would also be a
liability the moment anyone adds a resource here that does have a secret, and it
creates a merge-conflict surface for a file Terraform rewrites on every apply.
The bucket and table are trivially re-importable if the local state is ever lost:

```bash
terraform import aws_s3_bucket.state mbai-tfstate-591554480818
terraform import aws_dynamodb_table.locks mbai-tf-locks
```

If you decide you do want it committed, check it for secrets first and then
`git add -f infra/bootstrap/terraform.tfstate` — the ignore rule is deliberately
not an exception so that the choice stays explicit.

## Destroying

**Don't.** Both resources carry `lifecycle { prevent_destroy = true }`. Destroying
the state bucket orphans every resource in every environment — Terraform would
lose all knowledge of what it created, and each resource would then need to be
found and deleted by hand in the console.

If you genuinely need to tear the whole account down, destroy `../envs/dev`
**first**, confirm it is empty, then remove the `prevent_destroy` blocks and
destroy this last.

## Account guard

`terraform_data.account_guard` fails the plan if the resolved credentials do not
match `var.aws_account_id`. It is a `precondition`, not a `check` block, because
a `check` only produces a warning — applying to the wrong account must be a hard
stop.
