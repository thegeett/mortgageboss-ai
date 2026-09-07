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

---

## Review (second session, protocol §3)

One finding, in the detail-type list — which is the ticket's whole design decision and the one place
a mistake is silent. The IAM work is right, and both narrowings are not merely safe but
guide-endorsed; I read the source rather than agreeing with the reasoning.

### A — The plan-health types were matched exactly, and exactly is the fragile way to match them

Two problems, both found on the guide's own page rather than reasoned about.

**The guide contradicts itself on case.** Its normative list gives
`"GuardDuty Malware Protection Resource Status Warning"`. Its sample event for that same case prints:

```
"detail-type": "GuardDuty Malware Protection Resource Status warning",
```

— lowercase. (Its Error sample prints the word inside placeholder braces, so the samples are
templated loosely.) EventBridge matches `detail-type` exactly and case-sensitively. If the wire
format follows the sample rather than the list, an exact match never fires, the plan degrades, and
nothing is delivered to say so. That is the same fail-open shape as INFRA-1's hand-built ARN, and it
is the shape this ticket's four-type design exists to close.

**And `Resource Status Active` was omitted — the one that carries the argument.** The design's stated
purpose is that silence must not be ambiguous. But a plan that goes to WARNING and recovers emits
`Active`, so an operator would see the warning and never learn it cleared; and `Active` is the
positive confirmation that scanning ever started, which is exactly the "nothing was ever scanned"
case the health events were added for.

Both are fixed by one change: the two object-level types stay exact, and the resource-status family
is matched by `{ prefix = "GuardDuty Malware Protection Resource Status" }`. The prefix is spelled
identically in the list and in every sample, so it is correct under either reading of the casing, it
picks up `Active`, and it cannot miss a fourth status AWS adds later. Verified by rendering the
pattern and matching it against every detail-type the page documents — all six forms, including the
lowercase sample, now match; before the change, two did not.

### A note rather than a change — the rule is not scoped to this bucket

`source` + `detail-type` matches every GuardDuty malware-protection event in the account and region.
With one protection plan the rule cannot match anything else, so this is a limitation and not a
defect. Worth recording because the fix is not obvious: both shapes DO carry a bucket name, but at
different paths — `detail.s3ObjectDetails.bucketName` on the object events and
`detail.s3BucketDetails.bucketName` on the status ones — so scoping needs a two-branch pattern. That
complexity earns its place when a second plan appears, not before. Written into the module.

### The builder's three, ruled on

1. **Four detail-types in one rule — the design is right, the list was wrong.** Health and results
   in one queue is correct for the stated reason: a broken plan scans nothing and says nothing, so
   without health events "no threats found" and "nothing was ever scanned" arrive identically as no
   message. Splitting them would buy per-rule bucket scoping, which is worth nothing while there is
   one plan. The consumer switching on four shapes — five now — is the cheaper cost.
2. **Living in `inbound_mail` rather than its own module — right, and there is a stronger argument
   than the one given.** `aws_s3_bucket_notification` is **authoritative for the entire bucket**: it
   replaces the whole notification configuration, not a part of it. A separate module declaring it
   would silently fight any other notification config on the same bucket, and the module that owns
   the bucket would not own the setting that decides whether its objects are ever scanned. Keeping
   it here makes that conflict impossible rather than merely unlikely.
3. **Both narrowings — verified, and the first is what the guide asks for.** On the prefix scope,
   the IAM prerequisite page says it outright: *"When using an object prefix, add an `s3:prefix`
   condition on the targeted prefixes only. This prevents GuardDuty from accessing all the S3
   objects in your bucket."* Narrowing is the documented practice, not a departure from the
   template. (The guide suggests a condition where this narrows the resource ARN; the effect is the
   same and the ARN form is the stronger of the two.)
   On the KMS asymmetry, checked at the source: the environment key's policy carries
   `Sid = "EnableIAMUserPermissions"` with `Principal = {AWS = "…:root"}` and `Action = "kms:*"`,
   which is the statement that delegates key access to IAM within the account. An IAM role there
   needs no key-policy entry. SES is a service principal and is not covered by that delegation,
   which is why INFRA-1 needed its own statement. The two tickets do look symmetrical and are not,
   and the builder has the reason exactly right.

### A prediction I checked and dropped

I expected the narrowed `AllowMalwareScan` to break the validation object: it sits at the bucket
root, outside `inbound/`, and `INSUFFICIENT_TEST_OBJECT_PERMISSIONS` is a documented WARNING reason.
Reading the template settles it — `AllowPutValidationObject` grants **only** `s3:PutObject` on that
key, and nothing in the policy reads it back. AWS's own narrowing advice puts the object outside the
scanned prefix too, so the behaviour is expected. No finding; recorded because a plausible one that
turns out to be wrong is worth as much to the next reader as a real one.

### On the lock file

`infra/modules/inbound_mail/.terraform.lock.hcl` was **mine**, committed in `7656cefc`. I ran
`terraform init -backend=false` on the module to validate the check block I was adding, and
`git add -A` swept the generated file in. Only root configurations track a lock file here —
`bootstrap`, `envs/dev`, `envs/staging` — which is right, since a module is never initialised on its
own outside a check like ours. The builder was right to remove it and right to say so rather than
slip it into a diff. This pass was validated from a scratch copy so nothing was generated in the
repo at all.

### Done when, and the standing checks

Same disposition as INFRA-1 and for the same reason: the acceptance criterion is a post-apply
observation no session may make under §2.8, so the ticket is REVIEWED with the criterion carried
forward as the human's. `malware_scan_enabled` is false, so applying changes nothing until both that
flag and INFRA-1's are turned on.

Standing checks do not bite on infrastructure with no application code, with one exception worth
stating: nothing here logs, and the scan-results queue carries object keys and bucket names but no
message content — the `.eml` body never leaves S3.
