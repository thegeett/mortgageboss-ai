# `envs/staging` — the deployed environment

**This is the first and only environment that gets applied.** `../dev` is a
reference template that is never applied: local development runs against Docker
Compose and calls Bedrock from the laptop, so it needs no AWS infrastructure.

Built by C4 on the modules C2 and C3 validated against `../dev`. Every difference
between the two is a **value**, not code — no module was edited to make staging
work, which was the acceptance test for §6b.

## ⚠️ Applying this takes TWO runs

ACM validates by DNS, and the zone's nameservers must be live at the registrar
before validation can succeed — but they do not exist until the zone is created.
`enable_tls` and `enable_cognito` in `terraform.tfvars` are the phase gate, and
**they move together** — Cognito cannot attach to an HTTP listener, so
`terraform_data.auth_guard` fails the plan on `cognito = true, tls = false`.

```
enable_tls     = false
enable_cognito = false   →  apply  →  outputs four nameservers
                                        ↓
                         MANUAL: add four NS records at Namecheap,
                                 host "staging", then verify:
                                 dig +short NS staging.mortgageboss.ai
                                        ↓
enable_tls     = true
enable_cognito = true    →  apply  →  certificate, HTTPS listener, redirect, Cognito
```

Running phase 2 early is not destructive — ACM sits in `PENDING_VALIDATION` until
the 45-minute timeout and the apply fails. Re-run once `dig` returns four `awsdns`
nameservers.

Do **not** use `-target` to work around the ordering. Full walkthrough in
[`../../README.md`](../../README.md) and
[`docs/tickets/C4-staging-dns-tls-result.md`](../../../docs/tickets/C4-staging-dns-tls-result.md).

## What differs from the `dev` template

| Setting | dev (template) | staging | Why |
|---|---|---|---|
| `enable_nat_gateway` | `true` | **`false`** | No egress to the public internet at all. |
| `enable_vpc_endpoints` | `false` | **`true`** | ⬆ — and confined to **one AZ** for cost. |
| `rds_deletion_protection` | `false` | **`true`** | Holds real borrower NPI. |
| `rds_skip_final_snapshot` | `true` | **`false`** | A destroy must leave a recovery point. |
| `secret_recovery_window_days` | `0` | **`30`** | Not a destroy-and-rebuild environment. |
| `kms_create_alias` | `false` | **`true`** | Long-lived, so readability beats rebuild friction (ADR-365). |
| `redis_auth_enabled` | `false` | **`true`** | Makes `REDIS_URL` a credential. |
| `enable_execute_command` | `true` | **`false`** | A shell into borrower NPI (ADR-372). |
| `enable_cognito` / `enable_tls` | n/a | **`true` in phase 2** | Must not be openly reachable. Both `false` in phase 1 — see the phase gate above. |
| `documents bucket` | hand-made, SSE-S3 | **Terraform, SSE-KMS** | Real files; CMK gives audit + revocation. |
| `budget_limit_usd` | `150` | **`300`** | dev's would fire immediately here. |
| `vpc_cidr` | `10.20.0.0/16` | **`10.30.0.0/16`** | Identical ranges cannot be peered. |

## ⚠️ Starts empty

No document sync from dev, no database seed. Dev documents are development
artifacts and have no place in an environment holding borrower NPI. The schema
comes from the migration task run against an empty RDS instance.

## `terraform.tfvars.example`

Kept from C2, when this directory held only that file as proof the modules were
portable. `terraform.tfvars` is now the real thing and is what applies — the
example is historical and can be deleted once nobody needs the comparison.
