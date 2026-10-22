# `envs/staging` — the deployed environment

**This is the first and only environment that gets applied.** `../dev` is a
reference template that is never applied: local development runs against Docker
Compose and calls Bedrock from the laptop, so it needs no AWS infrastructure.

Built by C4 on the modules C2 and C3 validated against `../dev`. Every difference
between the two is a **value**, not code — no module was edited to make staging
work, which was the acceptance test for §6b.

## Applying this takes TWO runs

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

## Starts empty

No document sync from dev, no database seed. Dev documents are development
artifacts and have no place in an environment holding borrower NPI. The schema
comes from the migration task run against an empty RDS instance.

## `terraform.tfvars.example`

Kept from C2, when this directory held only that file as proof the modules were
portable. `terraform.tfvars` is now the real thing and is what applies — the
example is historical and can be deleted once nobody needs the comparison.

## SES production access

Requested 2026-10-19 with `aws sesv2 put-account-details` (CLI, not the console
wizard), after `mail.staging.mortgageboss.ai` verified (identity, DKIM and MAIL FROM
`bounces.mail.staging.mortgageboss.ai` all `SUCCESS`).

| | |
|---|---|
| Date requested | 2026-10-19 |
| Case ID | `179246520300535` |
| Status | `GRANTED` 2026-10-19, `ProductionAccessEnabled = true` (observed at 23:00 local, under 15 min after the request) |
| Mail type | `TRANSACTIONAL` |
| Website | https://mortgageboss.ai |
| Contact | contact@mortgageboss.ai |

Use-case text as submitted:

> MortgageBoss is a B2B tool for mortgage loan processors. It sends transactional
> email on behalf of a processor to a borrower on a specific loan file: document
> requests, receipt confirmations, and up to two reminders per outstanding document.
> Mail goes only to borrowers and loan participants already on the file; we never
> send to purchased or marketing lists and send no promotional content. Expected
> volume at pilot is under 2,000 emails per month. Each customer sends from its own
> verified subdomain with DKIM and DMARC. Bounces and complaints come back through an
> SES configuration set to SNS and SQS; our application stores them, suppresses
> bounced addresses and shows bounces to the processor. CloudWatch alarms alert us at
> 5% bounce and 0.1% complaint rates. Recipients can reply to stop reminders, which
> pauses automation on the file.

Several of those statements describe the planned feature, not what is deployed today:
the SES transport, the SQS events queue, bounce suppression and the CloudWatch alarms
are not built yet (`docs/email-communication/loan-email.md` §14). They must exist
before real borrower mail is sent.

Production access is per account and region; repeat this request in any new account (e.g. a future production account).

## Receiving switched on

- **Date:** 2026-10-21. `inbound_mail_enabled` and `inbound_malware_scan_enabled` applied, and the
  receipt rule set activated at 00:20:50 US Eastern (LP-989).
- **Rule set:** `mbai-inbound` (rule `mbai-staging-inbound`). It is the only rule set in the account.
- **Activated by:** SSO user `GeetaIdev` (`AdministratorAccess`), from CloudTrail `SetActiveReceiptRuleSet`.
- **Kill switch,** which stops all receiving in the account with no infra change. Run it with no
  rule-set name:

  ```bash
  aws ses set-active-receipt-rule-set --region us-east-1
  ```

- **Test result:** a real email to `test@mail.staging.mortgageboss.ai` landed in
  `mbai-staging-mail/inbound/`, KMS-encrypted and tagged `NO_THREATS_FOUND`. Its notice reached the
  inbound queue with the right recipient and every verdict `PASS`. **One gap:** GuardDuty's scan-result
  events never reach the `mbai-staging-scan-results` queue, because EventBridge cannot use the KMS key.
  See `docs/tickets/LP-989.md`.
- **2026-10-21 (US Eastern):** scan results now delivered (LP-990).
