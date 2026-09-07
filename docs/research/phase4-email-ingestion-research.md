# Phase 4 external research — inbound email, mailbox access, and compliance

- **Date:** 2026-09-06. Facts marked ⚠ are inferred or from secondary sources.
- **Companion:** `docs/phases/phase4.md` — the architecture and ticket plan that acts on this.
- Labels: **[LAW]** binding legal requirement · **[CONTRACT]** binding via GSE/investor contract ·
  **[PRACTICE]** industry norm · **[REC]** recommendation. Not legal advice.

---

## 1. Inbound provider comparison

| | **SES inbound** | **SendGrid Parse** | **Postmark** | **Mailgun Routes** | **CloudMailin** |
|---|---|---|---|---|---|
| MX target | `inbound-smtp.<region>.amazonaws.com` | `mx.sendgrid.net` | `inbound.postmarkapp.com` | `mxa/mxb.mailgun.org` | CloudMailin MX |
| Max message | **40 MB → S3**; 150 KB → SNS | 30 MB | 35 MB attachments | ⚠ ~25 MB parse; `store()` above | ⚠ verify |
| Delivery model | **Store-then-notify, into your S3** | Direct webhook POST | Direct webhook POST | Webhook, or `store()`+notify | Webhook, or direct-to-your-S3 |
| Raw MIME | Always — the S3 object *is* raw | Opt-in toggle (**use it**) | Parsed JSON only | Both | Raw format option |
| Retry | SMTP-level + Lambda/SQS; you own durability from S3 forward | 72 h, then **silent drop, no bounce, no alert** | 10 tries / ~6 h; `403` stops | 6 tries / 8 h; `406` stops | ⚠ |
| Signature | n/a — no webhook (IAM/S3) | ECDSA headers and/or OAuth | **HTTP Basic in the URL only** | HMAC-SHA256(ts+token) | ⚠ HMAC |
| Auth verdicts | spf / dkim / **dmarc** / dmarcPolicy / spam / virus | `SPF`, `dkim` map, SpamAssassin — **no dmarc** | SpamAssassin headers | raw headers | raw headers |
| Provider retains message | **No — your bucket, your CMK** | Yes (transient) | ≤1 MB, **attachments not retained at all** | **3 days** via `store()` | 30 d metadata; body → your bucket |
| BAA / regulated data | **Yes (AWS BAA; SES is HIPAA-eligible)** | **No — explicitly refused** | **No — explicitly refused** | Yes (published BAA), but "you are responsible for encrypting" | ⚠ none found |
| Price | $0.10/1k received + $0.09/1k 256 KB chunks | bundled | bundled | bundled | 10k/mo free, then tiered |

**Conclusion: SES.** NPI custody (the message never leaves our account), the 40 MB store-then-notify
model matching mortgage document sizes, durability inverted in our favour (the object is in S3 before
our code runs), and no new public attack surface. SendGrid and Postmark are disqualified for
regulated data by their own published positions. Fallback ranking if SES is rejected:
CloudMailin → Mailgun → *neither SendGrid nor Postmark*.

**SES gotchas:** headers in the notification are truncated at 10 KB (`headersTruncated`) — always
re-parse from the S3 object. Use `Event` (async) Lambda invocation, not `RequestResponse` (30 s hard
timeout). Inbound is **not supported in either GovCloud region**.

---

## 2. Per-record addressing

**Opaque token, not plus-addressing.** `loanfiles+LF12345@` leaks the record id and is trivially
enumerable — `LF12344` is one keystroke away, and anyone can post documents (or a prompt-injection
payload) into another borrower's file. Some MTAs and webforms also mangle `+`. Plus-addressing is
acceptable only as a cosmetic alias layered on a token.

Token rules: ≥128 bits from a CSPRNG (the repo currently uses `secrets.token_urlsafe(12)` ≈ 96 bits —
adequate, but 16 is free); case-insensitive lookup; a routing prefix (`lf-`); **never derived from
the record id**; scoped to `(company_id, loan_file_id)`; deactivated on file close, with expired
tokens behaving *identically* to unknown ones.

**Catch-all hazards:** an enumeration oracle (unknown bounces, known accepts) — return identical
responses and rate-limit by source IP; and dictionary spam — which is why the inbound subdomain must
have no other function.

**How the incumbents do it.** Zendesk uses a three-tier fallback: `References`/`In-Reply-To` against
stored message-ids → a bracketed **encoded** ticket id in the body (deliberately *not* the sequential
number) → an encoded id in the address. Linear and Jira Service Management use a per-team/per-project
address with header threading. Front, Help Scout and Intercom use inbox-level addresses plus
forwarding. **The pattern is: coarse address + header-based threading, with the per-record address as
a fallback.** Zendesk is the reference implementation of doing both — which is the ladder in
`phase4.md` §2.2.

**Keep bounces separate.** `From`/`Reply-To` = the per-file token address; envelope `Return-Path` =
a separate `bounces.` subdomain. Folding them means DSNs and out-of-office replies pour into the loan
file. With a managed provider you consume the structured bounce event rather than hand-rolling VERP.

---

## 3. Inbound sender authentication

| | Validates | Answers |
|---|---|---|
| SPF (RFC 7208) | envelope `MAIL FROM` domain vs connecting IP | "is this IP authorised for the **bounce** domain?" — not the visible From |
| DKIM (RFC 6376) | signature over headers + body | "did *some* domain sign this?" A valid signature from `evil.com` on a message claiming `From: chase.com` is a **pass** |
| **DMARC (RFC 7489)** | **alignment** of a passing SPF or DKIM domain with the **`From:` header domain** | **the only one that answers the question you care about** |
| ARC (RFC 8617) | signed chain of prior auth results across forwarders | "did this pass *before* a forwarder broke SPF and DKIM?" |

**SES verdicts:** `spfVerdict`, `dkimVerdict`, `dmarcVerdict`, `spamVerdict`, `virusVerdict` ∈
`PASS | FAIL | GRAY | PROCESSING_FAILED`; `dmarcPolicy` present **only on DMARC failure**. Two traps:
**`GRAY` is not `PASS`** (a `dkimVerdict: GRAY` most often means signed-by-a-non-matching-domain —
the spoofing case), and **SES does not enforce the DMARC policy** — `FAIL` + `p=reject` still lands in
your bucket. SES publishes **no ARC verdict**.

**Never trust an `Authentication-Results` header from the MIME body.** RFC 8601's security section is
explicit: a conforming MTA must delete instances claiming to originate inside its own trust boundary,
and consumers "SHOULD NOT interpret this header field unless specifically configured to do so." A
message can arrive carrying a forged `dmarc=pass`. Take verdicts from the provider's structured
object; strip inbound `Authentication-Results` / `ARC-*` before storing.

**Why display-name or From matching is insufficient:** display names are unauthenticated free text
(`From: "Jane Borrower" <attacker@gmail.com>` is a legitimately DMARC-passing gmail message, and this
is the dominant BEC vector); homoglyph and lookalike domains pass DMARC *for the attacker's own
domain* — DMARC proves the domain is real, not that it is the right one. You need a per-file expected-
participant allowlist plus IDN normalisation and a Levenshtein check against known participant
domains.

**Thread hijacking is the top threat.** A compromised realtor or title mailbox replies into a genuine
thread with real quoted history and altered wire instructions — every signal is green. Defenses:
verify the `References` chain against message-ids *you generated*; flag first-contact addresses and
recently-registered domains; flag behavioural deltas (same display name/different address, changed
DKIM signing domain); bound token lifetime; and **never let email change money** without out-of-band
verbal verification.

---

## 4. Attachment safety

Ordered gates: size/structure → sandboxed recursive MIME parse → per-part magic-byte sniff → AV →
format-specific inspection → **normalise/rasterize** → OCR + extraction reads *only* the derived
artifact. Everything before normalisation runs with **no network egress and no credentials** beyond
one object.

- **GuardDuty Malware Protection for S3** — scans on `PutObject`, publishes to EventBridge. Quotas:
  100 GB object, 100,000 extracted files, depth 100, 25 buckets/account/region; free tier 1,000
  requests + 1 GB/month/region. **The tag is applied after the scan — wait for the event.** ClamAV is
  weak against novel malware; its real value is its structural limits (`MaxRecursion`, `MaxFiles`) as
  a zip-bomb guard. **Do not send borrower documents to VirusTotal** — public submissions are shared
  with the security community, which is a GLBA disclosure. Hash-only lookups are safe.
- **Sniff, don't trust.** `puremagic` (no native dep) or `python-magic`. Reject on mismatch between
  sniffed / declared / extension; never "correct" it. Allowlist only. Normalise filenames — strip
  CR/LF (the 2026 nested-RFC822 campaign used CRLF-injected filenames precisely to produce parser
  disagreement), strip path separators, NFC-normalise, cap length, store under a generated key.
- **PDF risks:** `/JS`, `/JavaScript`, `/OpenAction`, `/AA` auto-execute; `/EmbeddedFile`, `/Launch`,
  `/URI`, `/SubmitForm` exfiltrate or launch; `/XFA` is a legacy parser surface. **Encrypted PDFs are
  common in this domain** (banks email password-protected statements) and are **unscannable by AV** —
  never pass one through as clean. PDF bombs: cap object count, pages (~500), decompressed stream
  size, wall-clock, and memory.
- **Rasterize.** `pikepdf` (QPDF) to strip, then `pypdfium2`/`pdf2image` to render pages to images and
  feed *images* to OCR. Destroys 100% of active content **and the invisible-text prompt-injection
  vector** in one step, at the cost of the text layer, which OCR regenerates anyway.
- **Reject archives in V1.** Fifield's single-layer construction reaches ~4.5 PB from 28 MB, so depth
  limits alone are insufficient; `py7zr` shipped a decompression-bomb DoS as CVE-2026-55195 — your
  archive library is not doing this for you. Quarantine and ask for individual files.
- **Prompt injection:** no prompt-level defense is reliable as of 2026; the mitigations are
  architectural — the extraction model gets no tools and no DB access, business decisions stay in
  deterministic code, extraction is cross-checked against stated/MISMO data, and no condition is ever
  auto-cleared from an emailed document. Flag near-invisible text (< 4pt, foreground ≈ background,
  off-page, zero-opacity) as an injection signal.

---

## 5. Idempotency, threading, auto-replies

**Idempotency key**, in preference order: provider message id (SES `messageId` = the S3 object key) →
normalised RFC 5322 `Message-ID` → `sha256(raw MIME)`. Materialise as `UNIQUE (company_id,
ingest_key)` with `ON CONFLICT DO NOTHING`, and **return 200 on a duplicate** — a non-2xx drives the
provider into its retry schedule forever. ⚠ `Message-ID` is not reliably unique in practice (Exchange
rewrites it, some MTAs omit it) — never make it the sole key.

**Threading:** generate and **store** a `Message-ID` for every outbound message; resolve inbound by
matching the *whole* `References` array (clients truncate the middle differently), then the recipient
token, then normalised-subject + overlapping participants + a 30-day window as a last resort —
preferring a new thread over a wrong merge.

**Auto-reply suppression** (RFC 3834 and practice): do not reply when `Auto-Submitted` is present with
any value other than `no`; `X-Auto-Response-Suppress` contains `DR`/`AutoReply`/`OOF`/`All`;
`Precedence: bulk|list|auto_reply|junk`; `List-Id`/`List-Unsubscribe` present; `Feedback-ID` present;
**`Return-Path` empty (`<>`)** — a bounce by definition; `X-Autoreply`/`X-Loop`; or `From` matches
`mailer-daemon@`/`postmaster@`/`no-reply@`. On our own automated mail set `Auto-Submitted:
auto-replied`, `X-Auto-Response-Suppress: All`, `Precedence: auto_reply`, and an `X-Loop` token. **Add
a header-independent rate limit** — 1 per address per 5 min, 3/day. Header detection will fail
eventually; the rate limit is what stops a two-system loop overnight.

**DSNs** (`multipart/report; report-type=delivery-status`, RFC 3464): route to the bounce subdomain;
if one reaches a loan-file address, detect it and file it as a delivery event, **never** as a borrower
document. Classify on the RFC 3463 status class (`5.x.x` hard, `4.x.x` soft). Never auto-reply to one.

---

## 6. MIME parsing gotchas and Python libraries (status verified Sept 2026)

**The gotchas that matter here:** `Content-Disposition` is a hint, not a rule — a phone-camera paystub
often arrives `inline`, so filter on *has a filename* or *is not text/plain|html* rather than on
disposition. **Borrowers forward**, so the real PDF is frequently nested inside a `message/rfc822`
part — recurse, cap depth at 3–5, and preserve provenance. Outlook-on-RTF encapsulates *all*
attachments into `winmail.dat` (`application/ms-tnef`) — still common on small-brokerage Exchange;
without handling it, borrowers report "I sent it and you didn't get it." Always
`part.get_payload(decode=True)`. Filenames arrive as RFC 2231 (`filename*=UTF-8''…`, with `filename*0*`
continuations) **or** RFC 2047 (`filename="=?UTF-8?B?…?="`) — `get_filename()` handles the first, so
run `decode_header` on the result if it still looks encoded.

| Need | Use | Status |
|---|---|---|
| Core MIME | **`email` stdlib, `policy=email.policy.default`, `BytesParser`** | the foundation; modern `EmailMessage` API; never compat32 |
| Security-oriented parsing | `mail-parser` (SpamScope) | **active — v4.6.4, 2026-08-21**; exposes RFC-compliance *defects* as a maliciousness signal |
| Reply/quote stripping | `mail-parser-reply` | active, **multi-language** (matters — Spanish-speaking borrowers) |
| | ~~`talon`~~ | **abandoned — last release April 2016.** Do not adopt |
| | ~~`flanker`~~ | **abandoned.** Do not adopt |
| Type sniffing | `puremagic` / `python-magic` | active |
| PDF sanitise / rasterize | `pikepdf` / `pypdfium2` | active |
| TNEF | `tnefparse` (or `pytnef`) | ⚠ low activity — verify |
| HTML→text | `selectolax` or bs4+lxml | active; strip `<script>`, `<style>`, **and comments** (a favourite injection hiding place) |
| DMARC alignment | `publicsuffix2` / `tldextract` | needed to compute organizational-domain alignment yourself |

---

## 7. Outbound deliverability (2026)

All senders, enforced since Feb 2024 (Google/Yahoo) and May 2025 (Microsoft consumer), now as
permanent `550` rejections rather than soft filtering: SPF **or** DKIM; valid FCrDNS/PTR; TLS;
complaint rate < 0.30% (target < 0.10%); RFC 5322-conformant. Bulk (5,000+/day to one consumer
domain): SPF **and** DKIM, a published DMARC record, `From:` alignment with the SPF or DKIM domain,
and RFC 8058 one-click unsubscribe.

**One-click unsubscribe does not belong on transactional mail** — Google scopes the requirement to
"marketing and subscribed messages," and an unsubscribe link on "your appraisal is scheduled" is
actively harmful. But be able to defend the classification, and note that `List-Unsubscribe` is
itself an auto-reply suppression signal to other systems.

**Subdomain separation from day one** (see `phase4.md` §2.1). Start DMARC at `p=none` with `rua=`,
read aggregate reports for 4–6 weeks, ratchet to `quarantine` then `reject`. **Shared IP at V1** — a
cold dedicated IP is worse than a good shared pool below ~100k messages/month. Publish MTA-STS and
TLS-RPT; enrol in Google Postmaster Tools, Yahoo CFL and Microsoft SNDS.

---

## 8. Using the processor's own mailbox

### 8.1 Decision matrix

| Option | Time | Google/MS review | Cost | Multi-tenant | Send-as | Key risk |
|---|---|---|---|---|---|---|
| **A. Admin routing/transport rule → our ingest address** | **1–3 days** | **none** | ~$0 | yes | no | forwarded mail fails SPF; no backfill; no read/label state |
| **B. Customer-owned OAuth client, "Internal" consent** | ~1 week | ⚠ see below | $0 | no — repeats per customer | yes | customer must own a GCP project; per-tenant toil |
| C. Our OAuth client, unverified production, admin-allowlisted | ~1 week | none yet | $0 | **≤100 users lifetime on that project, unresettable** | yes | burns the project — use a throwaway |
| D. Aggregator on *their* verified app (Nylas / Unipile) | 3–10 days | **none — shifts to vendor** | $15–49/mo + ~$2/account | yes | yes | a new subprocessor holding mortgage NPI; **their** brand on the consent screen |
| E. Aggregator, BYO OAuth (Aurinko, EmailEngine) | 1–3 weeks | **yes — CASA still ours** | $1/acct; EmailEngine $1,450/yr self-hosted | yes | yes | EmailEngine never stores bodies, but adds a Node+Redis service |
| F. Our own client, fully verified + CASA | **6–12 weeks** | yes | $500–4,500 lab + eng | yes | yes | **annual** re-assessment forever |
| **H. Microsoft Graph, single customer** | **~1 week** | admin consent only (free) | $0 | yes | yes | **no CASA equivalent exists on the Microsoft side** |
| I. Gmail over IMAP/XOAUTH2 | ~1 week | **yes — needs `mail.google.com`, restricted** | $0 | yes | via SMTP | same CASA cost as the API, fewer features. Never correct for a new app |

### 8.2 Google specifics

**Restricted** scopes (verification **and** CASA): `mail.google.com`, `gmail.readonly`,
`gmail.modify`, `gmail.compose`, `gmail.metadata`, `gmail.settings.*`.
**Sensitive** (verification only, **no** security assessment): **`gmail.send`**.
→ *Splitting inbound (forwarding) from outbound (`gmail.send`) is the cheapest full-duplex
configuration and deserves its own ADR.*

**CASA in 2026:** Tiers 1–3 replaced by Assurance Levels — AL1 "Developer Tested, Lab Reviewed"
(≈ $500–$1,800, 1–3 weeks) and AL2 "Lab Tested" (≈ $4,500, 2–4 weeks), Google assigning the level by
data sensitivity and user count. **Re-assessment every 12 months** from the previous Letter of
Validation. The App Defense Alliance now sits under the Linux Foundation. The **CASA Accelerator**
maps existing SOC 2 / ISO 27001 / PCI evidence across. ⚠ The widely-cited $15k–$75k figure traces to
a Nylas post last updated in **2021**, before CASA existed in this form — the lab fee is small; the
**remediation engineering (2–6 weeks of senior time) is the real cost**.

⚠ **Unresolved and load-bearing:** Google's restricted-scope-verification page lists "the app is used
only by people in your Google Workspace or Cloud Identity organization" among the scenarios where
verification isn't required — but the *same page* states that "every app that requests access to
Google users' restricted data and has the ability to access data from or through a third-party server
must go through a security assessment." **Do not plan GA on the Internal-consent exemption dodging
CASA without written confirmation from Google.**

**Domain-wide delegation** does bypass the user consent screen (a super admin authorises the client id
against an explicit scope list) — but it grants access to *all* users' data when you need one mailbox,
and any security-conscious admin will push back. Marketplace listing **adds** review, it does not
remove any.

**Push:** `users.watch` + Pub/Sub, granting Publisher to `gmail-api-push@system.gserviceaccount.com`.
**Must be re-called at least every 7 days; Google recommends daily** — a Celery beat task, not a cron
you forget. The notification carries only `{emailAddress, historyId}`; you must call
`users.history.list`. Max one event/second/user, and "notifications might be delayed or dropped" — a
reconciliation poll is mandatory. `historyId` is "typically valid for at least a week, in rare
circumstances only a few hours"; **too-old → HTTP 404 → full resync**. Build that path on day one.
Attachments come back **base64url in JSON** (~33% inflation). Gmail Enterprise Plus moved to 50 MB
send / 70 MB receive in Feb 2026 — a 70 MB message is a ~93 MB JSON response.

**Limited Use policy** — directly constrains this product: **human review of restricted-scope data is
prohibited** without documented explicit consent for specific messages (a processor QA-ing model
output against a source document is exactly that); no generalized model training; a 2026 addition
requires protection "against prompt injection techniques"; and transfer restrictions bar use for
**creditworthiness determination**. Get this to the domain expert and into `decisions.md` before any
Gmail code.

### 8.3 Microsoft specifics

Delegated `Mail.ReadWrite` + `Mail.Send` needs **no admin consent** and is the least alarming ask.
App-only grants access to **every mailbox in the tenant** by default — scope it with **RBAC for
Applications** (`New-ManagementScope` → `New-ServicePrincipal` → `New-ManagementRoleAssignment
-CustomResourceScope`), and note three traps: permissions are a **union**, so an unscoped Entra grant
makes the RBAC scope do nothing; cache propagation is 30 min–2 h (`Test-ServicePrincipalAuthorization`
bypasses it); legacy Application Access Policies ignore nested group members.

Change notifications: max lifetime **7 days** (1 day with `includeResourceData`); **set
`lifecycleNotificationUrl`** or you will silently lose mail (`reauthorizationRequired`,
`subscriptionRemoved`, **`missed`**); echo `validationToken` on creation; check `clientState`. Always
pair with `messages/delta`; an expired delta token gives **410 Gone / resyncRequired** — the same
failure shape as Gmail's 404, so build one abstraction over both. Attachments download as **raw bytes**
via `/$value` — strictly better than Gmail. Throttling: 10,000 requests/10 min and **4 concurrent
requests** per app+mailbox (the one that bites — enforce a semaphore); not raisable via support.

**EWS: do not build on it.** Disabling begins **October 2026**, fully disabled **April 2027**. SMTP
AUTH Basic is now scheduled for end of December 2026 (Microsoft's third delay).

### 8.4 Forwarding mechanics

**Gmail user-level** forwarding requires the target address to confirm a mailed code (since 2010).
**Workspace admin-level** routing has no per-user verification, preserves the original `From`,
supports "forward (include original recipient)" and `X-Gm-Original-To`, and allows content/attachment
conditions. Changes can take up to 24 hours.

**M365: automatic external forwarding is blocked by default** for tenants created after 2021 —
`AutoForwardingMode: Automatic - System-controlled` now means *off*. Blocked: **inbox rules** and
**mailbox SMTP forwarding** (`550 5.7.520 … AS(7555)`). **Not affected: transport/mail-flow rules and
alternate recipients.** So on M365, ask for a mail flow rule, never an inbox rule.

**What breaks:** SPF always fails on forward (the connecting IP is the forwarder's). SRS rewrites the
envelope sender so SPF passes — Gmail applies it automatically, Exchange Online since Aug 2023 — but
**SRS does not fix DMARC alignment**. DKIM usually survives *if* the forwarder doesn't touch the
message; it breaks on subject prefixes, appended disclaimers, link rewriting (Safe Links, Proofpoint),
and AV attachment rewriting. Since DKIM aligns on `From:`, **surviving DKIM is what keeps DMARC
passing across a forward.** ARC lets the forwarder attest the pre-forward verdict; Gmail trusts
sealers by reputation, M365 requires explicit `Set-ArcConfig`.

**Ingestion rule:** do not evaluate the forwarded message's own SPF as evidence about the original
sender. Instead: parse the `Authentication-Results` added by the original recipient's hop → walk
`ARC-Authentication-Results` trusting only allowlisted sealers → independently verify any surviving
`DKIM-Signature` for alignment with `From:` → use `Received` headers to reconstruct the path. Treat
`X-Forwarded-For` / `X-Gm-Original-To` as routing metadata, never as authentication.

**Forward selectively, not everything.** Blanket forwarding means receiving the processor's personal
mail, which is indefensible in a GLBA vendor review; a dedicated alias routed at the domain level is
selective by construction.

### 8.5 Token lifecycle (for whenever Route C lands)

Envelope-encrypt refresh tokens: a per-record DEK wrapped by a per-`company_id` KEK in KMS. Never log
them; **never put one in a Celery task argument** — it lands in Redis in plaintext. **Refresh races
are the #1 production bug**: two workers refreshing one connection looks identical to a stolen-token
replay and providers with rotation revoke on it — one in-flight refresh per connection behind a
distributed lock, persist before doing anything else.

Google revokes on: Testing publishing status (7 days), user revocation, **a password change when
Gmail scopes were requested**, 6 months unused, >100 refresh tokens per account per client id (oldest
silently invalidated), admin scope restriction. Microsoft: 90-day max inactive window
(non-configurable since Jan 2021); with Continuous Access Evaluation, near-real-time revocation on
password change or account disablement. **Admin revocation is invisible to you** and produces the same
`invalid_grant`/`403` as a transient outage.

Health monitoring: distinguish transient (429/5xx → backoff) from terminal (`invalid_grant`, `403`,
`subscriptionRemoved` → `needs_reauthorization`); renew watch/subscription **daily**; and **alert on
`last_success_at` staleness independently of errors** — the worst failure is silent: the watch quietly
expired, no error was ever raised, and mail stopped arriving three days ago. A processor will not
notice a subtle badge; use a persistent banner on the file list, because a broken mailbox means missed
conditions and a blown closing date.

---

## 9. Compliance

### 9.1 What changed, 2024–2026

| Change | Date | Why it matters |
|---|---|---|
| FTC Safeguards breach reporting to FTC live | 2024-05-13 | 30 days, 500+ consumers, **filings may be made public** |
| CFPB withdrew 67 guidance docs incl. Circulars **2022-04 (data security)** and **2023-03 (AI adverse action)** | 2025-05-12 | those Bureau theories are gone; **the underlying statutes are untouched**, and state AGs are live |
| NYDFS Part 500 final phase — MFA for *every* individual | 2025-11-01 | flows down contractually from NY-licensed clients |
| **Freddie Mac AI governance** (Bulletin 2025-16, Guide §1302.8) | eff. **2026-03-03** | first GSE mandate governing AI — **including vendor AI** |
| **Fannie Mae AI governance** (LL-2026-04) | eff. **2026-08-06** | sellers/servicers must govern *vendor* AI "no less protective" than their own |
| Colorado SB 24-205 enjoined, repealed, replaced by SB 26-189 (ADMT) | eff. **2027-01-01** | lending is an in-scope "consequential decision" |
| EU AI Act Annex III high-risk delayed | to **2027-12-02** | US-only product: monitoring only |

### 9.2 GLBA Safeguards Rule (16 CFR 314)

**[LAW]** §314.4(c)(3) requires encryption of customer information **in transit over external
networks**. Public-internet SMTP is an external network. Sending an SSN, bank statement, W-2 or
paystub as a plain attachment is therefore a Safeguards problem absent "effective alternative
compensating controls **reviewed and approved in writing by your Qualified Individual**." Opportunistic
STARTTLS is not one on its own — it is negotiated, downgradable, protects nothing at rest in either
mailbox, and yields no evidence. Enforced TLS with MTA-STS + TLS-RPT to known counterparty domains is
arguable **for lender/settlement counterparties, never for consumers**.

**Breach notification §314.4(j):** unauthorised acquisition of *unencrypted* customer information
(encrypted counts as unencrypted if the keys were also taken) affecting **500+ consumers**, reported
to the FTC **within 30 days**. In addition to — not instead of — 50 states' statutes, **Fannie's
36-hour** and **Freddie's 48-hour** contractual clocks, NYDFS 72 hours, and customer contracts.

**Enforcement template: FTC v. Ascension Data & Analytics (2020/21)** — a mortgage analytics firm's
OCR vendor left scanned mortgage documents (names, DOBs, SSNs, loan and account numbers) in plain text
on an unsecured cloud server. Charges: failing to vet the vendor, failing to contractually require
safeguards, failing to risk-assess. Order: comprehensive program, **biennial independent third-party
assessments**, annual executive certification, FTC notice within 10 days. Closest analog to a
document-processing SaaS in the whole docket.

### 9.3 GSE requirements **[CONTRACT]**

**Fannie** (Selling Guide A3-4-01 + Information Security Supplement): encryption in transit and at
rest; DLP/transmission controls; MFA at least for privileged accounts; unique IDs, annual access
certification, least privilege; logs protected from modification; **incident notice ≤ 36 hours**; and
the sentence that drives every security questionnaire — *"The Company is responsible for its vendors'
compliance … to the same extent as if such failure were committed by the Company."*

**Freddie** (Guide Ch. 1302): formal encryption policy; encryption during transmission of any
sensitive data; written policy governing information exchange; MFA for admins; **incident notice ≤ 48
hours** (privacy events affecting ≤10 borrowers may be quarterly); written agreements with all related
third parties.

Neither categorically bans emailing Confidential Information — but both require encryption in
transmission and DLP, which functionally forecloses plaintext attachments.

**[PRACTICE]** Secure exchange, in order of how mortgage shops actually do it: (1) borrower portal
upload — dominant and safest; (2) **secure-link-instead-of-attachment** — the right default for our
outbound; (3) encrypted-email gateways (Zix/OpenText, Virtru, Microsoft Purview Message Encryption,
whose revocation/expiration works only for external portal recipients); (4) password-protected
ZIP/PDF — widely used, weakly defensible, don't build on it. **ALTA Best Practices Pillar 3 (v4, eff.
2023-05-23)** is the settlement-side analog your title counterparties are certified against.

### 9.4 CAN-SPAM, TCPA, UDAAP, Reg B

Processing email is **transactional**, so CAN-SPAM's commercial-message requirements largely do not
attach — but classify per template and store the classification, keep promotional content out of
processing templates, and treat digest/nudge emails as a grey zone. TCPA applies to SMS reminders, not
email; the landscape is unsettled (5th Cir. rejected the FCC's prior-express-written-consent rule for
telemarketing in Feb 2026) — do not relax controls.

**The Reg B risk is precise and is the reason for the pre-send scanner.** §1002.9 requires notification
within 30 days of action taken on a completed application, with the action, creditor name/address, the
ECOA notice, the agency contact, and **specific principal reasons** — "generic references to internal
standards" are insufficient. §1002.9(c)'s incompleteness notice must specify the information needed,
designate a reasonable response period, and state that failure to respond ends consideration. **A
model asked to "follow up on missing documents" can easily produce something that functions as a
denial without the required content, or as an incompleteness notice without §1002.9(c)'s elements —
starting a clock nobody logged.** Make the incompleteness notice a first-class templated object with
enforced elements and a tracked deadline, not free text.

Also **TRID**: §1026.2(a)(3) defines "application" as six items — name, income, SSN to pull credit,
property address, estimated value, loan amount. Once received, the creditor has **three business days**
to deliver the Loan Estimate. **Extraction from an inbound email can complete that set and start a
statutory clock with no human in the loop.** Detect and alert on six-item completion.

**Why "AI drafts, human sends" is the mitigating design:** it preserves a named human sender of record
(what every examiner, E&O carrier and lender compliance officer asks for); it defeats the "no one
reviewed this" narrative; the model-draft/human-edit diff is auditable evidence of meaningful review;
it satisfies the GSE mandates' proportionality by classifying the feature as low-risk assistive; and
it keeps the product out of ADMT scope under Colorado SB 26-189, California's ADMT rules, and the EU
AI Act — all of which key on systems that *make or substantially replace* human judgment. **Enforce it
in code**: no send path without an authenticated `reviewed_by_user_id` + `draft_id`, and refuse to
build bulk send pre-pilot.

### 9.5 Retention **[LAW]**

| Regime | Cite | Period |
|---|---|---|
| ECOA / Reg B, consumer credit | 12 CFR 1002.12(b) | **25 months** after notice of action taken; **beyond** that on notice of investigation (1002.12(b)(7)) |
| TILA / Reg Z, general | 1026.25(a) | 2 years |
| **TILA — Closing Disclosure** | **1026.25(c)(1)** | **5 years after consummation** |
| TILA — ATR/QM | 1026.25(c)(3) | 3 years after consummation |
| RESPA / Reg X servicing | 1024.38(c)(1) | 1 year post-discharge/transfer; servicing file compilable in **5 business days**, incl. **notes reflecting communications with the borrower** |
| Reg N / MAP | 1014.5 | 24 months from last dissemination |
| **FTC Safeguards disposal duty** | **314.4(c)(6)** | **dispose within 2 years of last use** absent a documented business or legal need |

Practical floor: **5 years from consummation**, **25 months** for denied/withdrawn — with the
Safeguards disposal duty pulling the other way. "Keep everything forever" is now a finding.
**Ship the legal-hold flag before the purge job** (FRCP 37(e): the severest sanctions require intent
to deprive, and auto-purging a file after a demand letter arrives is exactly that fact pattern).

### 9.6 Model-provider handling

**Bedrock:** model providers have no access to prompts, completions or logs. Retention modes are
`none` / `default` / `inherit` — **new accounts default to `inherit`, not `none`.** Abuse detection can
retain inputs/outputs up to 30 days, and for certain models retains **all** traffic; which models fall
in which bucket changes over time, so verify against the live docs on every model upgrade.
**Cross-region inference stores retained data in the destination region** — pin or disable it. Enforce
`none` with an SCP denying `bedrock:PutAccountDataRetention` unless the mode is `none` (extend to the
project-level APIs); SCPs don't cover the Organizations management account, so use IAM there. Use VPC
endpoints/PrivateLink, KMS CMKs, TLS 1.2+.

**Disable Bedrock model-invocation logging, or treat its destination as an NPI store** with a CMK,
access control, retention schedule and disposal — it will contain full borrower documents in prompt
text. This is the most commonly missed NPI store in AI mortgage builds and the highest-probability
source of a Safeguards finding in this product.

**Anthropic direct API:** no training on commercial inputs/outputs by default; commercial inputs and
outputs auto-deleted within 30 days, **except** trust-and-safety-flagged content (up to 2 years) and
classification scores (up to 7 years). **Zero Data Retention agreements are available** to commercial
organizations via Sales.

**GLBA has no "BAA" concept.** The mechanism is **Reg P §1016.13** — a contract prohibiting the third
party from disclosing or using the information other than to carry out the purposes disclosed — plus
Safeguards §314.4(f) (select capable providers, contractually require safeguards, periodically
assess). Name the subprocessor in your own customer DPA; your lender clients need it for their
Fannie/Freddie fourth-party obligations.

**Data minimisation is the highest-leverage AI control available.** Redact or tokenise SSNs, full
account numbers and DOB before the prompt wherever the task doesn't need them. Classification does not
need an SSN. Drafting a document-request email does not need a bank statement's contents.

### 9.7 Minimum control set for this feature

**P0 — do not run a pilot with borrower data without these:** WISP with a named Qualified Individual;
a written risk assessment **naming the email ingestion channel and the AI pipeline**; encryption in
transit and at rest incl. backups, logs **and AI prompt/response stores**; MFA for every human;
**no NPI in outbound attachments, enforced in code**; **human-in-the-loop send gate** with
`reviewed_by_user_id`, no bulk send; **deterministic pre-send scanner** (rates/APRs, approval-denial
language, payment amounts, wire/routing/account numbers, Reg Z triggering terms); **Bedrock ZDR
configured and enforced**, regions pinned, invocation logging off or governed; **tenant isolation at
ingest** — unroutable mail quarantined, never cross-tenant visible; **scoped mailbox access**;
**append-only communication log** capturing the model draft / human edit / sent diff; a written
incident response plan meeting the **shortest** applicable clock (36 h); DPAs with §1016.13
use-restriction clauses for every subprocessor; SPF+DKIM+DMARC `p=reject` outbound and stored inbound
verdicts; and untrusted-input handling for ingested documents with **no auto-clearing of conditions
from extraction alone**.

**P1 — before GA / first enterprise client:** documented retention schedule + automated disposal;
**legal-hold flag shipped before the purge job**; the per-feature **AI System Disclosure**; a written
AI governance policy with a named owner and annual review; templated Reg B §1002.9(c) incompleteness
notice; **TRID six-item detection**; per-template CAN-SPAM classification; E-SIGN consent captured per
borrower with required disclosures on a consent-gated path; annual pen test; quarterly access reviews;
vendor register with annual reassessment incl. AI subprocessors; the Qualified Individual's annual
report; security training; and a **per-loan-file evidentiary export** (communications + documents +
audit trail + hashes) — needed for client exams, and an excellent sales asset.

**The three things most worth worrying about:** (1) the AI prompt/response store is an unmanaged NPI
store in nearly every build of this kind; (2) the 2026 GSE AI mandates make you a diligence blocker or
the easy choice depending on whether you can hand a lender the disclosure; (3) **email ingestion
silently starts legal clocks** — TRID's three days and Reg B's thirty — through a pipe no human reads
first.

---

## Sources

**Inbound providers** — [SES email receiving](https://docs.aws.amazon.com/ses/latest/dg/receiving-email.html) ·
[SES receiving concepts (40 MB / 150 KB, actions)](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-concepts.html) ·
[SES notification contents (verdicts)](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-notifications-contents.html) ·
[SES Lambda action](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-action-lambda.html) ·
[SES pricing](https://aws.amazon.com/ses/pricing/) ·
[SES HIPAA eligibility](https://aws.amazon.com/about-aws/whats-new/2019/07/amazon-ses-achieves-hipaa-eligibility) ·
[SendGrid Inbound Parse setup](https://www.twilio.com/docs/sendgrid/for-developers/parsing-email/setting-up-the-inbound-parse-webhook) ·
[Securing Parse webhooks](https://www.twilio.com/docs/sendgrid/for-developers/parsing-email/securing-your-parse-webhooks) ·
[SendGrid retry logic](https://support.sendgrid.com/hc/en-us/articles/46513815674395-Understanding-Inbound-Parse-Webhook-Retry-Logic) ·
[SendGrid HIPAA position](https://www.twilio.com/docs/sendgrid/ui/account-and-settings/hipaa-compliant) ·
[Postmark inbound webhook](https://postmarkapp.com/developer/webhooks/inbound-webhook) ·
[Postmark size limits](https://postmarkapp.com/support/article/1056-what-are-the-attachment-and-email-size-limits) ·
[Postmark HIPAA position](https://postmarkapp.com/support/article/1041-is-postmark-hipaa-compliant) ·
[Mailgun receive/forward/store](https://mailgun-docs.redoc.ly/docs/mailgun/user-manual/receive-forward-store/) ·
[Mailgun webhook security](https://documentation.mailgun.com/docs/mailgun/user-manual/webhooks/securing-webhooks) ·
[Mailgun HIPAA BAA](https://www.mailgun.com/legal/hipaa-baa/) ·
[CloudMailin inbound](https://www.cloudmailin.com/inbound) ·
[CloudMailin S3 attachment storage](https://docs.cloudmailin.com/receiving_email/store-email-attachments-in-s3-azure-google-storage/) ·
[Cloudflare Email Service limits](https://developers.cloudflare.com/email-service/platform/limits/)

**Addressing / threading** — [Zendesk email threading](https://support.zendesk.com/hc/en-us/articles/8396827889946-How-are-incoming-emails-threaded-to-tickets) ·
[Linear email intake](https://linear.app/integrations/create-issues-via-email) ·
[JSM email requests](https://support.atlassian.com/jira-service-management-cloud/docs/receive-requests-from-an-email-address/) ·
[VERP spec (djb)](https://cr.yp.to/proto/verp.txt)

**Authentication / abuse** — [RFC 8601 Authentication-Results](https://www.rfc-editor.org/rfc/rfc8601) ·
[RFC 3834 automatic responses](https://datatracker.ietf.org/doc/html/rfc3834) ·
[Detecting automated mail](https://www.arp242.net/autoreply.html) ·
[RFC 3464 DSN parsing](https://smtpedia.com/dsn-parsing-guide/) ·
[Display-name spoofing](https://www.doppel.com/blog/display-name-spoofing-reply-and-lookalikes) ·
[Email thread hijacking](https://abnormal.ai/learning/email-thread-hijacking) ·
[Reply-chain attacks](https://threatcop.com/blog/reply-chain-attacks/) ·
[Webhook idempotency](https://www.svix.com/resources/webhook-university/reliability/idempotency-and-deduplication/)

**Attachment safety** — [GuardDuty Malware Protection for S3](https://docs.aws.amazon.com/guardduty/latest/ug/gdu-malware-protection-s3.html) ·
[GuardDuty S3 quotas](https://docs.aws.amazon.com/guardduty/latest/ug/malware-protection-s3-quotas-guardduty.html) ·
[Nested RFC822 CRLF filename obfuscation](https://ironscales.com/threat-intelligence/nested-rfc822-attachment-crlf-filename-obfuscation) ·
[Zip bomb primer](https://www.bamsoftware.com/hacks/zipbomb/) ·
[py7zr decompression bomb GHSA-gjrg-mpp7-g774](https://github.com/advisories/GHSA-gjrg-mpp7-g774) ·
[jSPDF object injection](https://github.com/absholi7ly/jsPDF-Object-Injection) ·
[Prompt injection in PDFs](https://www.promptinjectionprevention.com/kb/prompt-injection-in-pdfs-and-documents.php) ·
[Indirect prompt injection defenses, 2026](https://zylos.ai/research/2026-04-12-indirect-prompt-injection-defenses-agents-untrusted-content/) ·
[mail-parser (PyPI)](https://pypi.org/project/mail-parser/) ·
[mail-parser-reply](https://github.com/alfonsrv/mail-parser-reply) ·
[puremagic](https://github.com/cdgriffith/puremagic)

**Outbound deliverability** — [Google sender guidelines](https://support.google.com/mail/answer/81126) ·
[RFC 8058 one-click unsubscribe](https://www.rfc-editor.org/rfc/rfc8058) ·
[2026 bulk sender guide](https://redsift.com/guides/bulk-email-sender-requirements)

**Mailbox APIs** — [Gmail API scopes](https://developers.google.com/gmail/api/auth/scopes) ·
[Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification) ·
[OAuth verification FAQ](https://support.google.com/cloud/answer/13463817) ·
[Workspace user data & developer policy (Limited Use)](https://developers.google.com/workspace/workspace-api-user-data-developer-policy) ·
[Gmail push notifications](https://developers.google.com/workspace/gmail/api/guides/push) ·
[users.history.list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list) ·
[Gmail API quotas](https://developers.google.com/workspace/gmail/api/reference/quota) ·
[Gmail 50/70 MB limits, Feb 2026](https://workspaceupdates.googleblog.com/2026/02/ending-larger-attachments-in-gmail-new-50MB-limit-for-Enterprise-Plus.html) ·
[Google CASA 2026 assurance levels & costs](https://deepstrike.io/blog/google-casa-security-assessment-2025) ·
[Domain-wide delegation](https://knowledge.workspace.google.com/admin/apps/control-api-access-with-domain-wide-delegation) ·
[Authorize unverified third-party apps](https://knowledge.workspace.google.com/admin/apps/authorize-unverified-third-party-apps) ·
[Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference) ·
[Limit application permissions to specific mailboxes](https://learn.microsoft.com/en-us/graph/auth-limit-mailbox-access) ·
[Graph change notifications](https://learn.microsoft.com/en-us/graph/change-notifications-overview) ·
[message: delta](https://learn.microsoft.com/en-us/graph/api/message-delta?view=graph-rest-1.0) ·
[Outlook large attachments](https://learn.microsoft.com/en-us/graph/outlook-large-attachments) ·
[Graph throttling limits](https://learn.microsoft.com/en-us/graph/throttling-limits) ·
[EWS deprecation in Exchange Online](https://learn.microsoft.com/en-us/exchange/clients-and-mobile-in-exchange-online/deprecation-of-ews-exchange-online) ·
[SMTP AUTH basic retirement update, Jan 2026](https://techcommunity.microsoft.com/blog/exchange/updated-exchange-online-smtp-auth-basic-authentication-deprecation-timeline/4489835) ·
[IMAP/POP/SMTP OAuth on M365](https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth) ·
[Transition from less secure apps to OAuth](https://knowledge.workspace.google.com/admin/sync/transition-from-less-secure-apps-to-oauth) ·
[Workspace redirect/forward messages](https://knowledge.workspace.google.com/admin/gmail/advanced/redirect-or-forward-gmail-messages-to-another-user) ·
[M365 control external email forwarding](https://learn.microsoft.com/en-us/defender-office-365/outbound-spam-policies-external-email-forwarding)

**Compliance** — 16 CFR 314 (FTC Safeguards Rule) · 12 CFR 1002 (Reg B) · 12 CFR 1024 (Reg X) ·
12 CFR 1026 (Reg Z) · 12 CFR 1014 (Reg N/MAP) · 15 U.S.C. 7001 (E-SIGN) · 23 NYCRR 500 (NYDFS) ·
FTC v. Ascension Data & Analytics (2020/21) · Fannie Mae Selling Guide A3-4-01 + Information Security
Supplement · Fannie Mae Lender Letter LL-2026-04 · Freddie Mac Bulletin 2025-16 / Guide §1302.8 ·
CFPB guidance withdrawal 90 FR 20084 (2025-05-12) · ALTA Best Practices v4 Pillar 3 ·
NIST AI RMF 1.0 + NIST AI 600-1 · Colorado SB 26-189 · Texas HB 149 (TRAIGA) ·
AWS Bedrock data-retention and abuse-detection docs · Anthropic commercial data-retention and ZDR docs
