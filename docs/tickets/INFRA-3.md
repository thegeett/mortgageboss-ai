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
