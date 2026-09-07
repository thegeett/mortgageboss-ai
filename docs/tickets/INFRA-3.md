# INFRA-3 — Outbound sending identity and the bounce path

- **Ticket:** INFRA-3 · Phase 4, M2, ticket 11 of 27
- **Status:** **HUMAN_GATED.** Terraform written and validated; **not applied, `plan` not run, SES
  sandbox exit not requested.**
- **Date:** 2026-09-07
- **Scope:** `infra/modules/outbound_mail/` (new), `infra/envs/staging/{main,variables}.tf`,
  `terraform.tfvars`
- **No application code.**

**Nothing in this ticket touched AWS.** No apply, no plan, no DNS change, and **no production access
request** — that last is explicitly a human action under protocol rule 2.8, and it is the one with
AWS-side lead time.

---

## Three subdomains, three jobs, and they must not overlap

| Domain | Job | Records |
|---|---|---|
| `inbox.<parent>` | receives borrower mail | MX to SES receipt. **No SPF, no DKIM.** (INFRA-1) |
| `mail.<parent>` | sends | SES identity, DKIM CNAMEs, DMARC. The `From:` domain. |
| `bounces.<parent>` | envelope sender / Return-Path | one MX to SES feedback, SPF |

The separation is not tidiness. AWS states the constraints directly: a MAIL FROM domain *"shouldn't
be a subdomain that you also use to send email from"* and *"shouldn't be a subdomain that you use to
receive email"*. An outbound identity overlapping an inbound MX is the documented cause of a mail
loop.

**Why `mail.` and `bounces.` are siblings rather than nested.** For SPF to satisfy DMARC the `From:`
domain must align with the MAIL FROM domain, and under **relaxed** alignment two subdomains of one
organisational domain align. The DMARC record therefore carries no `aspf` or `adkim` tag — their
absence *is* relaxed alignment, and AWS is explicit that `aspf=s` would break this exact
configuration: *"In order to achieve SPF alignment with SES, the domain's DMARC policy must not
specify a strict SPF policy (aspf=s)."*

DKIM aligns strictly on its own, because SES signs as the identity, which is the `From:` domain.
Either passing satisfies DMARC; both passing is why both are built.

Pages read 2026-09-07 with headings verified: *Using a custom MAIL FROM domain*, *Complying with
DMARC authentication protocol in Amazon SES*, *Creating and verifying identities in Amazon SES*.

---

## The finding: Terraform cannot express the DKIM record correctly

This is the thing I would have got wrong from memory, and it is worse than a wrong constant.

The SES guide says each Easy DKIM CNAME's value is *"the DKIM token followed by a hosted zone domain
(for example, `token.dkim.amazonses.com` or `token.a31d.dkim.us-west-2.amazonses.com`)"* and that
**"the hosted zone portion varies by AWS Region and cell"**. The authoritative value is
`SigningHostedZone` in `GetEmailIdentity`'s `DkimAttributes`.

**No provider resource exposes it.** Checked against the provider's own schema (aws 5.100.0):
`aws_ses_domain_dkim` returns only `dkim_tokens`; `aws_sesv2_email_identity.dkim_signing_attributes`
returns only `tokens`. Neither carries the hosted zone.

So the suffix is a **module variable** defaulting to the common form, with the override procedure in
its description. Hardcoding it would be right in most cells and silently wrong in the rest — and the
symptom would be DKIM never verifying, which reads as "DNS has not propagated yet" for the 72 hours
SES spends trying.

---

## `behavior_on_mx_failure = "RejectMessage"`

The alternative, `UseDefaultValue`, silently reverts the envelope sender to an `amazonses.com`
subdomain. Mail still goes out, SPF still passes, and the bounce path this ticket builds is simply
not used — with nothing anywhere saying so. Bounces then land where LP-819 cannot read them, which is
the failure that ticket exists to prevent.

Refusing to send is louder and cheaper than sending into a path nobody is watching.

---

## Escalation: LP-819 cannot ingest the `bounces.` subdomain as mail

The plan's LP-819 says *"Ingest the `bounces.` subdomain"*. **That is not possible as written**, and
the reason is a hard AWS constraint rather than a preference:

- A custom MAIL FROM domain requires an MX pointing at `feedback-smtp.<region>.amazonses.com`.
- AWS: *"you must publish exactly one MX record to the DNS server of your MAIL FROM domain. If the
  MAIL FROM domain has multiple MX records, the custom MAIL FROM setup with Amazon SES will fail."*

So `bounces.` cannot also carry an MX to SES receipt, and bounces never arrive as mail we can read.
They arrive as **SES events**.

This module therefore builds the real bounce path: an SES **configuration set** with an SNS event
destination for `reject`, `bounce`, `complaint`, `delivery` and `renderingFailure`. LP-819 reads that
topic. Without it, a sending identity publishes bounces nowhere, and "no bounces" and "bounces going
nowhere" are indistinguishable.

**Recorded as an escalation** rather than silently reinterpreted: LP-819's text needs correcting, and
whoever writes it should know the shape changed before they start.

No open or click tracking on the configuration set. Both require SES to rewrite links in the body —
which for a borrower document request means rewriting a secure upload link — and neither has been
asked for.

---

## Deliberately not done

- **No apply, no `plan`, no sandbox exit request.** Rule 2.8. The current process is *"Request
  production access (Moving out of the Amazon SES sandbox)"*; it is a console/support request with
  AWS-side lead time and it is a person's to file.
- **`dmarc_report_address` is empty**, and `outbound_mail_enabled` is `false`. The address names a
  real mailbox somebody must read; choosing one for them would produce a report nobody receives.
  Both are set together or not at all.
- **No production environment.** As with INFRA-1: `envs/dev` is a never-applied template and
  production does not exist as an environment.
- **No `p=quarantine` or `p=reject`.** AWS's own rollout guidance starts at monitoring mode and
  tightens on evidence. Doing it early is how legitimate mail stops being delivered.
- **No sending in the app.** LP-811a records a send without transmitting; LP-816 transmits.

---

## For the reviewer

The three standing reviewer checks:

- **Tenancy** — no application code, no `company_id`.
- **Message content in logs** — nothing logs here. Relevant downstream: the SNS events carry
  recipient addresses, so LP-819's consumer is subject to the standing rule even though this module
  is not.
- **AI in the decision path** — none.

The judgement calls worth a second opinion:

1. **Building the configuration set and SNS topic at all.** It is the thing that makes LP-819
   possible, and it has no reader today — the pattern I have declined twice and built twice. Here the
   alternative is not "LP-819 builds it": LP-819 is application code and the plan gives it no
   Terraform. If you think it belongs in LP-819 anyway, that ticket needs an infra half.
2. **`RejectMessage` over `UseDefaultValue`.** It means a misconfigured MX stops outbound mail
   entirely rather than degrading it. On a system that emails borrowers about their loan, I think
   loud is right; the opposite reading is defensible.
3. **The DKIM hosted-zone variable.** A default that is right in most cells and wrong in some is
   still a default. The alternative is no default, which forces a value nobody can know before the
   identity exists — a chicken-and-egg that would make the first apply impossible.

---

## Review (second session, protocol §3)

Two findings. The escalation against the plan is **correct and under-supported** — there is a
stronger citation for it than the one given — and the DKIM catch is right but leaves more uncertainty
on the table than it needs to.

### The escalation: LP-819 cannot ingest `bounces.*`, and the reason is stronger than quoted

Checked at the source, as asked. The builder quotes the one-MX rule, which the page states twice:

> "To successfully set up a custom MAIL FROM domain with Amazon SES, you must publish exactly one MX
> record to the DNS server of your MAIL FROM domain. If the MAIL FROM domain has multiple MX records,
> the custom MAIL FROM setup with Amazon SES will fail."

That is accurate. But the same page settles it more directly in its requirements list, and this is
the sentence LP-819's author should be shown:

> "The MAIL FROM domain **shouldn't be a subdomain that you use to receive email**."

So it is not merely that a second MX breaks the setup — AWS says outright not to use the MAIL FROM
subdomain for receiving. The escalation stands, and the configuration-set-plus-SNS path this module
builds is the real one. Recorded with both quotations so nobody re-opens it on the weaker of the two.

**One operational consequence nobody has written down yet, and it belongs in the runbook.** The
states table shows `Pending`, `TemporaryFailure` and `Failed` all "use custom MAIL FROM fallback
setting", and `behavior_on_mx_failure = "RejectMessage"` makes that fallback *reject*. SES spends up
to **72 hours** trying to detect the MX. So if the identity is configured before its MX resolves,
every outbound message is rejected for as long as that takes. The apply order is therefore not
cosmetic: publish DNS first, confirm detection, then send. Added to the escalation rather than left
for whoever meets it.

### A — Enabling outbound mail without a report address publishes a malformed DMARC record

`main.tf` interpolates the address straight in:

```
records = ["v=DMARC1; p=none; rua=mailto:${var.dmarc_report_address}"]
```

and `infra/envs/staging/terraform.tfvars` carries `dmarc_report_address = ""`. The module variable
has no default — correctly — but the **root** supplies one, so the module's "Required" is a comment
rather than a constraint. Flip `outbound_mail_enabled` without also setting the address and the
published record is `v=DMARC1; p=none; rua=mailto:` with nothing after the colon.

That is malformed, and it is the exact configuration the variable's own description warns about: a
`p=none` policy that neither enforces nor informs. The description argues the case and then ships
the thing it argues against, guarded only by a flag someone is going to flip.

Now fail-closed, using Terraform 1.9's cross-variable validation (the module requires `>= 1.9`):
empty is allowed while the flag is off, and refused at plan time when it is on. Proved in an
isolated config with no providers — flag off + empty passes, flag on + empty fails with the message,
flag on + address passes. The first case is what keeps today's staging plan clean.

### B — The DKIM suffix is knowable for this deployment, not merely overridable

The finding is right and it is the kind that would have cost a silent 72 hours: the CNAME target is
not always `dkim.amazonses.com`, and no provider resource exposes the correct value. Making it a
variable is the right shape.

But the authoritative source is not only `GetEmailIdentity` — the SES guide's own note points at a
**published table**: "DKIM domains" in the AWS General Reference. It is region-level, it lists
eleven regions with their own `dkim.<region>.amazonses.com`, and it ends "All other regions:
`dkim.amazonses.com`". **us-east-1 is not among the eleven**, so this deployment's default is
correct — verified rather than probably right, which is a different claim to make to whoever applies
this.

Worth noting for accuracy: the module's description says the zone "varies by AWS Region and cell"
and cites `token.a31d.dkim.us-west-2.amazonses.com`. The published table has no cell component, and
us-west-2 is itself not one of the eleven — it uses the default. The caution was correct; the
worked example illustrating it is not a form that table produces. Description rewritten around the
table, with `SigningHostedZone` kept as the read-back fallback.

### The builder's three, ruled on

1. **The configuration set and SNS topic with no reader — keep them, and the rule holds.** An unused
   constant is inert; a second spelling of a fact can drift. This is a resource with no consumer,
   which is the inert kind. The argument is stronger here than in the earlier cases: LP-819 is
   application code and the plan gives it no Terraform, so "a later ticket will build it" is false —
   nobody would, and the first symptom would be bounces going nowhere.
2. **`behavior_on_mx_failure = "RejectMessage"` — right.** The alternative silently reverts the
   envelope sender to `amazonses.com`: mail goes out, SPF still passes, and the bounce path is
   simply unused with nothing saying so. On a system that emails borrowers about their loan, a loud
   refusal beats a quiet loss of the feedback channel. The cost is real and is now written into the
   runbook note above rather than discovered during a 72-hour window.
3. **No `aspf` / `adkim` — correct, and correctly flagged as easy to "fix" wrongly.** Their absence
   is relaxed alignment, which is what lets `From: @mail.<parent>` align with
   `MAIL FROM: @bounces.<parent>`. Someone hardening the record later would break SPF alignment
   while believing they were tightening it. The comment naming that is the right defence.

### Done when, and the standing checks

Same disposition as INFRA-1 and INFRA-2: the acceptance criteria are post-apply observations no
session may make under §2.8, so REVIEWED with them carried forward. `outbound_mail_enabled` is
false, so an apply is a no-op until a person turns it on — and now cannot be turned on without a
DMARC report address.

Still the human's: `terraform plan`, apply, DNS delegation for `mail.` and `bounces.`, and the
production sandbox exit request, which has AWS-side lead time and is not something a session may
file.
