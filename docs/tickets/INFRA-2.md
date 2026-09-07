# INFRA-2 — GuardDuty malware scanning

- **Ticket:** INFRA-2 · Phase 4, M2, ticket 10 of 27
- **Status:** **HUMAN_GATED.** Terraform written and validated; **not applied, `plan` not run.**
- **Date:** 2026-09-07
- **Plan:** [`phase4-build-plan.md`](../phases/phase4-build-plan.md) INFRA-2 section
- **Scope:** `infra/modules/inbound_mail/malware_scan.tf` (new) + that module's variables and
  outputs, `infra/envs/staging/{main,variables}.tf`, `terraform.tfvars`
- **No application code.**

**Nothing in this ticket touched AWS.** No apply, no plan, no console action.

---

## What was built

GuardDuty Malware Protection for S3 over the inbound bucket: the IAM role GuardDuty assumes, the
protection plan scoped to the `inbound/` prefix with post-scan tagging enabled, EventBridge
notifications on the bucket, and an EventBridge rule delivering scan results to a dedicated SQS
queue with a DLQ.

Behind `inbound_malware_scan_enabled`, which is **false**, and which is **separate from**
`inbound_mail_enabled` on purpose — see below.

### Silence is the dangerous state

The plan's "Watch for" is about the tag arriving *after* the scan. The deeper version of the same
problem is that **a broken protection plan scans nothing and says nothing**: "no threats found" and
"nothing was ever scanned" both arrive as no message at all.

So the EventBridge rule matches four detail-types, not one:

| Detail-type | Why it is on the rule |
|---|---|
| `GuardDuty Malware Protection Object Scan Result` | the result itself |
| `GuardDuty Malware Protection Post Scan Action Failed` | the tag will not arrive; a consumer waiting for it would wait forever |
| `GuardDuty Malware Protection Resource Status Warning` | the plan is degraded |
| `GuardDuty Malware Protection Resource Status Error` | the plan is scanning nothing |

All four strings are verbatim from the GuardDuty user guide's *"Monitoring S3 object scans with
Amazon EventBridge"* page, read 2026-09-07 with the heading verified on the page. **A typo in one of
them does not fail at apply.** The rule simply never matches, and the pipeline waits forever for an
event being published to nobody — the same fail-open shape the reviewer corrected me on in INFRA-1,
where I had claimed a wrong ARN would fail closed.

### The two flags are separate, and the order matters

`inbound_malware_scan_enabled` is independent of `inbound_mail_enabled` so **the scan can be applied
and observed first**. GuardDuty writes a validation object and publishes a resource-status event, so
the plan proves itself healthy before any borrower mail exists to be scanned.

Turning mail on first would be the wrong order for exactly the reason above: the failure is silent,
and the first evidence would be an unscanned attachment reaching extraction.

Both are listed explicitly in `terraform.tfvars` rather than left to defaults, so turning mail on
without deciding about scanning is not something that can happen by omission.

### The resource schema came from the provider, not the registry

`registry.terraform.io`'s page is JavaScript-rendered and returned no content. The argument shape
was read from `terraform providers schema -json` against the installed provider (aws 5.100.0) —
which is not merely a substitute source but a better one: it is what the provider will actually
accept, rather than what a page says it accepts.

That is how `actions` was found to be an **attribute** of type
`list(object({ tagging = list(object({ status = string })) }))` rather than a nested block. Written
from memory it would have been a block, and the failure would have been at the human's plan.

### Two narrowings against the AWS template

- **`AllowMalwareScan` is scoped to the prefix**, not the whole bucket. AWS's template grants
  `bucket/*`. The bucket holds nothing else today, but the grant outlives that assumption and a read
  grant over borrower mail is worth narrowing while it is free.
- **No KMS key-policy change.** The environment CMK already allows the account root `kms:*`, so an
  IAM grant in the same account suffices. That is *not* true of SES in INFRA-1, which is a service
  principal rather than an IAM identity and therefore needed its own statement on the key. The
  difference is worth stating because the two tickets look symmetrical and are not.

---

## Deliberately not done

- **No apply, no `terraform plan`.** Same blocker as INFRA-1: no AWS credentials in this session,
  and the S3 backend is contacted even under `-backend=false`. Recorded in
  [`infra-2/validate.txt`](infra-2/validate.txt).
- **No GuardDuty detector.** Malware Protection for S3 can run independently, and enabling the full
  GuardDuty service is a cost and scope decision for the account, not for this ticket. The
  consequence is stated and real: without a detector, a `THREATS_FOUND` result produces **no
  GuardDuty finding** — the EventBridge event is the only notification, and this rule is what makes
  it reach anything.
- **No consumer.** Nothing polls the scan-results queue; LP-804 owns attachment safety. The queue
  and its outputs exist so that ticket has somewhere to attach.
- **No quarantine bucket.** "Objects with no result inside N minutes go to quarantine" is an
  application decision about an object that is already stored; it needs no second bucket, and
  inventing one now would be infrastructure ahead of the rule that uses it.

### One housekeeping fix

`infra/modules/inbound_mail/.terraform.lock.hcl` was committed during INFRA-1's review. No other
module in this repo tracks one — only root configurations do (`bootstrap`, `envs/dev`,
`envs/staging`), which is correct, because a module is never initialised on its own outside a check
like this one. Removed.

---

## For the reviewer

The three standing reviewer checks:

- **Tenancy** — no application code, no `company_id`.
- **Message content in logs** — nothing logs. Worth noting for whoever consumes the queue: the scan
  result carries `objectKey`, which for this bucket is an SES-generated message id and not borrower
  content, but it identifies one borrower's message and should be treated as such.
- **AI in the decision path** — none.

The judgement calls worth a second opinion:

1. **Putting this in `inbound_mail` rather than its own module.** Every resource is scoped to that
   bucket, that prefix and that key, and the EventBridge notification setting is a property of the
   bucket itself — a separate module would leave the bucket's owner not owning its own notification
   configuration. It has its own flag, so it is still its own apply. If you would rather see it
   split, now is the cheap moment.
2. **Matching four detail-types on one rule and one queue.** The consumer must switch on
   `detail-type` regardless. The alternative is separate rules and queues for health versus results,
   which is more machinery for a consumer that does not exist yet.
3. **`object_prefixes = ["inbound/"]`.** It excludes the validation object at the bucket root from
   scanning, which is correct — but it also means anything ever written outside that prefix is
   unscanned, silently. Today nothing is.
