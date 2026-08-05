# `infra/shared` — account-scoped resources

One state, applied once per **account**, holding what outlives and spans every
environment:

| Resource | Why it is here and not in an environment |
|---|---|
| ECR repositories | Shared by design — environments are distinguished by image *tag*, so the exact bytes tested in dev are what get promoted. A shared resource cannot be owned by a throwaway environment's state. |
| The registry KMS key | Encrypts the image layers. If it lived in an environment, that environment's `destroy` would schedule deletion of the key protecting every other environment's images. |
| `Environment` cost allocation tag | An account (payer) setting. Every environment's budget `cost_filter` matches `user:Environment$<name>` and matches **nothing** until this is activated. |

## Why the registry is not per-environment

It was, briefly, and that was the bug. `envs/dev` is documented as
destroy-and-rebuild and ran with `ecr_force_delete = true`, while both dev and the
staging example declared the identical repository names. In one account that means:

1. Staging's apply fails with `RepositoryAlreadyExistsException` — or, forced
   through, two states manage one resource.
2. Dev's routine destroy deletes the shared repositories and **every** image.
3. The repositories were encrypted with dev's CMK, so that destroy also scheduled
   deletion of the key protecting staging's image layers.

## Apply

```bash
cd infra/shared
terraform init
terraform plan -out=shared.tfplan
terraform apply shared.tfplan
```

Run it **after** `bootstrap/` (which creates the state bucket) and **before** any
environment. It carries the same account guard the environments do: a `precondition`
on `terraform_data.account_guard`, so applying against the wrong credentials is a
hard error rather than a warning.

## Image retention

Two tiers, because the count is now global across environments:

- **Protected** (`ecr_protected_tag_prefixes`, default `staging-` / `prod-` /
  `release-`) — matched by a higher-priority rule, so promoted images never enter
  the ordinary count and keep `ecr_keep_last_protected_images` of history.
- **Ordinary** (`ecr_keep_last_images`) — everything else, mostly CI builds.

Without the protected tier a busy dev pipeline reaches the ceiling in days and
evicts the *oldest* image in the registry, which is exactly the long-lived tag
another environment is running. The failure is deferred and confusing: that
environment cannot launch a replacement task or scale out, failing with
`CannotPullContainerError` long after the push that caused it.

**Tag your promoted images with one of these prefixes.** A promotion tagged
`v1.4.2` rather than `release-v1.4.2` gets no protection.

## Destroying this state

Don't, as a routine operation — it holds every environment's images.

`kms_create_alias` exists because of ADR-365: `terraform destroy` **orphans** a KMS
alias, so a later re-apply fails with `AlreadyExistsException`. The environments set
it false precisely because they are rebuilt often. Here it defaults to **true** —
this state is long-lived and the alias is worth having — but it is a knob, so a
rebuild after an accidental destroy is not blocked on console surgery.

## `registry_kms_key_arn` — migration only

Leave it `null`. It exists for one situation: adopting repositories that an
environment already created under **its** CMK.

ECR has no API to re-encrypt a repository, so the provider marks
`encryption_configuration` `ForceNew`. Importing such repositories while this module
demands a newly created key plans a **destroy of every repository** — and with
`ecr_force_delete = false` that destroy then fails on repositories holding images,
leaving the apply half-done. Setting this variable to the original key's ARN adopts
them in place with no replacement.

While it is set, the images remain protected by an environment's key, so that
environment's `destroy` still makes them unpullable. `terraform output
registry_key_is_owned_here` reports `false` for exactly as long as that is true. The
full recipe is in [`../README.md`](../README.md) under "Migrating an already-applied
dev environment".
