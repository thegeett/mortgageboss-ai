# INFRA-1 — Inbound mail DNS and SES

- **Ticket:** INFRA-1 · Phase 4, M2, ticket 9 of 27
- **Status:** **HUMAN_GATED.** Terraform written and validated; **not applied, and `plan` not run** —
  see below.
- **Date:** 2026-09-07
- **Plan:** [`phase4-build-plan.md`](../phases/phase4-build-plan.md) INFRA-1 section
- **Scope:** `infra/modules/inbound_mail/` (new), `infra/modules/secrets/`,
  `infra/envs/staging/{main,variables}.tf`, `terraform.tfvars`
- **No application code.**

**Nothing in this ticket touched AWS.** No apply, no DNS change, no SES sandbox request. Those are a
person's actions, per protocol rule 2.8.

---

## The plan that has not been run

The protocol says to run `terraform plan` and commit its output. **I could not.** There are no AWS
credentials in this session, and the S3 state backend is contacted even under `-backend=false`:

```
Error: No valid credential sources found
Error: failed to refresh cached credentials, no EC2 IMDS role found
```

So the root module was validated from a copy with `backend.tf` removed — identical in every other
respect, modules directory copied whole. Output in [`infra-1/validate.txt`](infra-1/validate.txt).

**What the plan should say, and the one line worth reading.** `inbound_mail_enabled` defaults to
`false`, so the module has `count = 0` and the same flag gates the KMS grant. A plan against staging
should therefore report **no changes at all**. If it reports any, the thing to look at first is
`module.secrets.aws_kms_key_policy.this` — the key policy was refactored from a list literal to
`concat([...existing...], [])`, which should render byte-identical JSON when the list is empty. That
is the single claim in this ticket that validation cannot check and a plan can.

To run it: `aws login` (or export a profile), then `terraform -chdir=infra/envs/staging init && terraform plan`.

---

## What was built

`infra/modules/inbound_mail/` — SES domain identity and its verification TXT, the MX record, an S3
bucket (SSE-KMS, versioned, public access blocked, TLS-only, lifecycle to Glacier IR then expiry),
an SNS topic, an SQS queue with a DLQ, and the receipt rule with an `s3_action`.

Instantiated in staging behind `inbound_mail_enabled`, which is **false**.

### Off by default, and not for tidiness

Turning it on **publishes an MX record**. From that moment the domain accepts mail from anyone, and
there is no application path to route it — LP-803 (ingest) and LP-805 (routing) are both later in
M2. The plan puts this Terraform on day one for production's *registrar* lead time, not because
staging should start receiving before it can process.

That is also the escalation already recorded against M1: the send path can advertise an inbox that
receives nothing. This ticket does not resolve it; it declines to make it worse.

### The permission conditions are not what my memory would have written

SES's write is authorised on `AWS:SourceAccount` **and** `AWS:SourceArn`, where the source ARN names
**this receipt rule** — not `aws:Referer`, which appears in most older examples and in a great deal
of published Terraform. Read from the SES developer guide's *"Giving permissions to Amazon SES for
email receiving"* page on 2026-09-07, heading verified on the page.

The same page settles a second thing I would have got wrong: **the key policy must grant
`kms:Decrypt` as well as `kms:GenerateDataKey*`**, specifically because the destination bucket has
server-side encryption enabled. Without it the write fails with an opaque `AccessDenied` *after* SES
has already accepted the message — so the sender sees success and the mail is gone.

That grant lives on the existing environment CMK (`modules/secrets`), added behind
`ses_receipt_rule_arns`, which is empty unless inbound mail is enabled. The ARN is constructed in the
root module from the same pieces the child builds it from, rather than read back from
`module.inbound_mail` — taking it from there would be a dependency cycle, because the module needs
the key.

### The rule set is a variable, and activation is not created

**Only one receipt rule set is active per account per region.** Applying a second
`aws_ses_active_receipt_rule_set` does not add to the first — it *replaces* it, silently, and
inbound mail stops with no error raised anywhere.

So the rule set name is a variable (anything else in this account adds a **rule to this set**), and
`aws_ses_active_receipt_rule_set` is **deliberately not created**. Activation is a one-time human
step taken with the account's other SES usage in view.

### The domain sends nothing

No SPF, no DKIM, no A record, no MAIL FROM on `inbox.`. An inbound MX overlapping an authenticated
sending domain is the documented cause of an infinite mail loop — a bounce to a bouncing address,
forever, against a borrower's mailbox. Outbound identity is INFRA-3's, on its own subdomains.

### Retention, and the ordering problem it creates

Glacier IR at 90 days, expiry at 5 years (the protocol's fixed decision, matching the Closing
Disclosure floor).

**That lifecycle rule *is* the purge job**, and `phase4.md` §6 says the legal-hold flag ships
*before* it. The flag is LP-821's, in M5. Written as a variable with the retention stated rather than
omitted, and flagged here rather than silently created — but the ordering conflict is real and
belongs to a person, not to me. It is now an escalation.

---

## Deliberately not done

- **No apply, no `terraform plan`, no DNS change, no SES sandbox request.** Rule 2.8.
- **No `aws_ses_active_receipt_rule_set`.** See above — account-wide and single-valued.
- **No production environment.** `infra/envs/dev` is a never-applied reference template and
  production does not exist as an environment yet. The plan's production path (reuse `modules/dns`
  with `enable_tls = false`, two-phase around the registrar) is recorded and unbuilt.
- **No GuardDuty.** INFRA-2.
- **No `settings.inbound_bucket` / `inbound_queue_url` wiring.** LP-802 created those settings;
  nothing sets them until this is applied and the outputs exist. The module exports them under the
  names LP-802 expects.

---

## For the reviewer

The three standing reviewer checks:

- **Tenancy** — no application code. The bucket is single-tenant infrastructure; `company_id` is
  derived from the resolved loan file in LP-805, which does not exist yet.
- **Message content in logs** — nothing logs. Worth noting for the apply: the raw `.eml` in this
  bucket is the most sensitive object the system will hold, which is why the bucket is SSE-KMS with
  the environment CMK rather than SSE-S3 — a separate audit trail and a revocation lever.
- **AI in the decision path** — none.

The judgement calls worth a second opinion, in the order I would attack them:

1. **`inbound_mail_enabled = false`.** The plan's "Done when" is *"`dig MX inbox.staging…` answers,
   and a message sent by hand appears as an object in the bucket."* **That cannot be met with the
   flag off**, and it cannot be met by me at all, because meeting it requires an apply. I chose not
   to meet an acceptance criterion rather than publish an MX for a domain with no consumer. If you
   read the flag as ducking the ticket rather than sequencing it, say so.
2. **The `concat` refactor of the KMS key policy** is the one edit that touches an applied resource.
   I believe it renders identically when the list is empty; only a plan proves it, and I could not
   run one.
3. **`GLACIER_IR` rather than `GLACIER`.** Instant Retrieval costs more to store and nothing to
   read. A stored message is read once on arrival and then almost never — but "almost never" includes
   a legal hold, where a multi-hour restore on every object is its own problem.
