# Loan Email — living document

Everything about email in MortgageBoss lives here. Add new sections at the bottom; keep the decisions table current.

Started 2026-10-17. Last updated 2026-10-21.

---

## 1. What it is

Each loan file gets its own email address on the customer's domain. MortgageBoss sends from it, receives replies to it, sends reminders by itself. The processor is CC'd on every email we send, and any reply that comes only to the file address is forwarded to her. We never read her mailbox.

`lf-y36e@mb-mail.abcmortgage.com` — display name "Priya Thaker, ABC Mortgage"

**Scope rule:** anything sent *to a file address* is routed to that file — whoever sends it: a reply to a thread we started, a borrower emailing the file address directly, the LO, the lender, or the processor forwarding something from her inbox. Email sent anywhere else (the processor's own address) is not on the file unless she forwards it. The routing key is the address, not who started the conversation.

**No subdomain, no email.** A tenant without an active subdomain gets no file addresses: drafts only, copied into the processor's own mail client ("Copy & open mail app"). This is the existing copy-and-send behaviour.

**Product promise, stated precisely:** MortgageBoss is the authoritative record of every email it sent and every email delivered to a file address. It cannot guarantee capture of mail the processor sends from her own mail client — if she replies (not reply-all) to a thread from Outlook, the file address is not on that reply and the file will not see it. CC and forwarding give her visibility; they do not make her client's outbox part of the record. This goes in the customer agreement and the onboarding guide ("reply-all keeps it on the file").

**Why not mirror Gmail/Outlook (what LendFlowPro does):** full-inbox OAuth is Gmail-only, needs Google's CASA audit, and gives a third-party app read/write/delete on the processor's whole mailbox — exactly what wire-fraud training and GLBA vendor reviews say not to allow. The subdomain approach is provider-neutral, sees only mail sent to file addresses, and is a one-line pitch: **"We never touch your inbox."**

## 2. Rules

1. Templates send automatically. AI-written text is always a draft a processor approves (v1). See §11 for how AI replies graduate to automatic.
2. Every inbound message is shown on the file. Nothing is acted on silently.
3. Attachments go through the existing document intake, same as a manual upload.
4. Customer's root domain is never touched. One NS record delegates a subdomain to us.
5. Pre-send check on every outbound — template, human or AI: no rates, APRs, approval/denial wording, account or routing numbers. Blocks with a reason; override needs a note.
6. The AI never has a tool that sends, changes document status, or reads another file. It returns a structured suggestion; code decides.
7. Inbound routing uses the SES envelope recipients (`receipt.recipients`), never the To/Cc headers.
8. Only the worker sends mail. The API queues a send; it never calls SES itself.

## 3. Decisions

| Topic | Decision | Date |
|---|---|---|
| Address format | `lf-<display_id lowercase>@<tenant subdomain>`, e.g. `lf-y36e@mb-mail.abcmortgage.com`. Replaces the 128-bit `inbox_token` address. `get_inbox_address()`, the resolver and its `lower()` index move to `display_id`; ADR-397 amended. Old token addresses keep resolving for existing files during a grace period. The authenticated-sender gate, not address secrecy, is the defence | 10-19 |
| No active subdomain | No file address at all. Drafts only (copy into own mail client). No inbound | 10-19 |
| SES region | us-east-1 — staging and dev are both there and it supports receiving. Nothing cross-region | 10-19 |
| Pilot environment | No production account yet. **Staging is the pilot environment.** Its data is treated as production: backups on, no destroy/reset, access limited, test tenants separate from the pilot company. Moving to a production account later recreates tenant zones with new nameservers, so each customer updates their NS record once; nameservers are stored per tenant to make that a scripted list | 10-19 |
| Dev | Local only, no AWS mail. Outbound via an SMTP transport to MailHog (`localhost:8025`). Inbound via a script that feeds a `.eml` and a fake SES notification into the same ingest code. Tenant domain via a fake provider that marks it active immediately. Selected by `MAIL_TRANSPORT=ses|smtp`, `DOMAIN_PROVIDER=route53|fake`. `infra/envs/dev` gets no mail modules | 10-19 |
| Staging test tenant | A separately registered domain on a non-Route 53 DNS provider, as its own company in staging. Registered early so it has some age before sending. Kept after the pilot as the permanent onboarding regression test. Test mail only to own inboxes and SES simulator addresses | 10-19 |
| Platform domain | `imboxstaging.mortgageboss.ai` and the global `imbox` inbox domain are **dropped**. `mail.staging.mortgageboss.ai` both sends and receives ("tenant zero"), the same shape as every customer subdomain. Production later: `mail.mortgageboss.ai` | 10-20 |
| Mail bucket | One bucket for raw mail in both directions, renamed from `mbai-staging-inbound-mail` to **`mbai-staging-mail`** (free now: never applied). Folders `inbound/` (SES writes, object named by SES message ID) and `outbound/` (worker writes `<communication_id>.eml` before calling SES). Flat — no tenant or loan folders, because inbound mail is stored before routing; Postgres holds the link. See §4a | 10-20 |
| Email-sourced documents | Stay on the normal documents path. Source recorded in `Document.upload_source = BORROWER_INBOX` (exists) and traceable through `InboundAttachment.document_id` (exists). Added: S3 object metadata `source=email`, `inbound-message-id=<id>`; a visible "Email · from … · date" label on the document linking to the message. Source is never encoded in the S3 path | 10-20 |
| SES production access | Requested by hand (CLI), not Terraform — it is a reviewed request, once per account. **Granted 2026-10-19 in staging, case 179246520300535.** Recorded in `infra/envs/staging/README.md`. Repeat in any new account | 10-19 |
| DMARC reports | `rua=mailto:contact@mortgageboss.ai` for our domains. Must be on mortgageboss.ai (same organisation) — a Gmail address would be ignored. Customer subdomains also report to us, authorised by one wildcard record `*._report._dmarc.mortgageboss.ai TXT "v=DMARC1"` in the **apex** zone; customers may add their own address as a second `rua`. Policy starts at `p=none`; tighten to `quarantine` after a few weeks of clean reports | 10-19 |
| Bounce (MAIL FROM) domain | Must be a **subdomain of the sending identity**. Staging: `bounces.mail.staging.mortgageboss.ai`. Tenants: `bounce.mb-mail.<customer>`. Enforced by a validation in `outbound_mail` so `plan` fails before SES does | 10-19 |
| Account suppression list | SES account-level suppression on for `BOUNCE` and `COMPLAINT` — SES refuses to resend to hard-bounced or complaining addresses before our own suppression code exists. AWS sends no notice when an address is added; a later send to it still succeeds at the API and comes back as a Bounce event (`OnAccountSuppressionList`). Step 2 surfaces both and blocks known-bad addresses before calling SES | 10-20 |
| Alarm thresholds | Bounce rate > **2.5%**, complaint rate > **0.05%**. AWS puts the account under review at 5% / 0.1%, so alarming there is too late | 10-20 |
| Sending runs in the worker | `send_draft` queues a Celery task; the worker calls SES. The API role cannot send. Matches the `queued → sending → sent` outbox states | 10-20 |
| Route 53 reachability | A private endpoint exists for the Route 53 API (`com.amazonaws.route53`, private DNS `route53.amazonaws.com`). No NAT gateway, Lambda or admin script needed. Added in step 3, when the api first creates zones: the network module must pass through list entries that already start with `com.amazonaws.` (it otherwise prefixes the region, and the Route 53 name has none) | 10-20 |
| Route B (`FORWARDED_ALIAS`) | Superseded — processors forward to the file address instead. Model and enum stay; connection UI hidden; delete later once unreferenced | 10-20 |
| Tenant vs shared infra | Terraform modules are the shared layer (bucket, queues, rule set, config set, events topic, endpoints, IAM, alarms). Per-tenant Route 53 zone, SES identity and DNS records are created at runtime by a boto3 service in the API | 10-19 |
| Routing key | The loan is identified from `receipt.recipients` in the SES notification — the addresses SES actually delivered to. To/Cc/Bcc headers are stored as metadata only. A message delivered to several file addresses attaches to each only if all are in the same tenant; otherwise it goes to quarantine | 10-19 |
| Receipt rule | One shared receipt rule with no recipient condition, matching all mail to any verified identity with MX at SES. Routing happens in code. No per-tenant rules | 10-19 |
| Rule set activation | Manual, once per account: `set-active-receipt-rule-set`. Only one rule set can be active per account and switching silently disables the previous one, so Terraform never does it. It doubles as the master switch for receiving | 10-20 |
| Inbound encryption | SES receipt action gets **no KMS key** (that mode is client-side encryption, which the worker cannot read). The bucket's default encryption is SSE-KMS with the shared CMK; the key policy allows SES for the rule ARN. Worker reads with plain `get_object` | 10-19 |
| Send states | Outbox: `queued → sending → sent → delivered / bounced / complained`. `sending` is written before the SES call; the SES MessageId is stored the moment it returns. On restart, rows stuck in `sending` are never retried blindly — they are reconciled against SES events or flagged for a human | 10-19 |
| Received ≠ satisfied | An arriving document **pauses** the reminder and moves the requirement to `received`. Only validation (rule engine or processor) moves it to `satisfied`; a failed validation re-requests with the reason and the reminder clock restarts | 10-19 |
| Sender trust levels | *Recognized* (address matches a file contact) → *Authenticated* (DMARC pass on that sender) → *Authorized* (allowed to do the thing) → *Trusted document* (passed malware/intake checks). Auto-attach needs recognized + authenticated; sensitive outbound needs authorized | 10-19 |
| Offboarding | Export + delete-on-request exist before the first customer can leave; legal hold + retention schedule follow | 10-19 |
| Retention | Keep everything in v1. The mail bucket's lifecycle moves both `inbound/` and `outbound/` to Glacier Instant Retrieval after 90 days and **never expires anything** (changed in LP-981 review from a 5-year expiry: S3 lifecycle can't see a legal hold in the database, so an expiry could delete held mail). Expiry comes back only with legal hold (S3 Object Lock, or a purge job that checks the hold). Written into the customer agreement | 10-21 |
| Scope | Everything addressed to a file address lands on that file, from any sender. Email sent to the processor's own address is on the file only if she forwards it | 10-18 |
| Subdomain | Default `mb-mail`, customer can change, collision-checked. Root domain never used | 10-17 |
| DNS | Zone is created first so the four nameserver names can be shown; the customer adds one NS record; verify; self-test; active. Fallback: manual records (MX, 3 DKIM CNAME, DMARC, bounce MX/SPF) for providers that can't do NS | 10-17 |
| Reply-To | Always the file address | 10-17 |
| CC | Processor's real address on **every** send, reminders included. Per-processor toggle later if reminder volume becomes noise | 10-17 |
| Inbound to processor | Reply-all → she is already in CC, nothing to do. Message arrives at the file address without her in To/Cc → we **forward the full email** to her, attachments included. Forward is from the file address, display name "<sender> via <company>", subject unchanged, Reply-To = sender + file address (best effort; tested on Outlook desktop, Outlook web, Gmail). Skip if she was in To/Cc; never forward her own forwards; marker header, never re-forwarded; above a size cap send a link instead of attachments. Unread badge on the file | 10-17 |
| Auto-responders | Out-of-office / vacation / delivery-failure messages are stored but never answered. Detected by `Auto-Submitted`, `X-Autoreply`, `Precedence: bulk/auto_reply` and the usual subject patterns. About mail-server auto-responders, not AI replies | 10-18 |
| AI replies | Tiered — see §11 | 10-18 |
| Copy & open mail app | Shown only while the tenant has no active domain | 10-18 |
| Unknown senders | Message shown on the file; attachments held as "needs review" until the processor accepts | 10-17 |
| Secure upload link | In every document request; attachments remain the fallback | 10-17 |
| Sequencing | AWS resources first, then business logic | 10-17 |
| Ticket numbering | Continues the existing series: LP-981 onward | 10-19 |
| Not in v1 | Reading the processor's inbox (OAuth), automatic AI replies, automatic DNS tools (Entri / Domain Connect), lender portal integration, SES tenant management (revisit at ~10 tenants) | 10-17 |

## 4. Environments and addresses

| Environment | Who | Example address | What happens |
|---|---|---|---|
| Dev (laptop) | Fake tenant | `lf-y36e@mb-mail.localhost` | Sent mail appears in MailHog; replies simulated by script. `.localhost` cannot receive real mail by design |
| Staging | Our domain ("tenant zero") | `lf-a7k2@mail.staging.mortgageboss.ai` | Real SES; tests receiving before any customer exists |
| Staging | Test tenant | `lf-q8m3@mb-mail.<test domain>` | Real SES; tests full onboarding incl. NS at a third-party DNS provider |
| Staging | Pilot customer | `lf-y36e@mb-mail.abcmortgage.com` | Real SES, real borrowers |
| Production (later) | Our domain | `lf-a7k2@mail.mortgageboss.ai` | Self-tests |
| Production (later) | Every customer | `lf-y36e@mb-mail.<customer>` | Same address as in staging; NS record updated once at migration |

What a borrower sees (staging and production):

```
From:     Priya Thaker, ABC Mortgage <lf-y36e@mb-mail.abcmortgage.com>
To:       john.smith@gmail.com
Cc:       priya@abcmortgage.com
Reply-To: lf-y36e@mb-mail.abcmortgage.com
```

Not visible to borrowers: the bounce address (`…@bounces.mail.staging.mortgageboss.ai`, `…@bounce.mb-mail.<customer>`) and DMARC reports (`contact@mortgageboss.ai`).

### 4a. Storage layout

**Raw mail — `mbai-staging-mail`** (production later: `mbai-prod-mail`)

```
mbai-staging-mail/
├── inbound/
│   └── <ses-message-id>              ← written by SES, one object per received email, no extension
└── outbound/
    └── <communication_id>.eml        ← written by the worker before calling SES: exactly what was sent
```

- Flat: inbound mail is stored before we know its tenant or loan, so the path can't contain them. Postgres links each object to its company and loan (`InboundMessage.raw_storage_path`, and the outbound equivalent on `Communication`).
- Object names are always server-chosen (SES message ID or our UUID), never anything a sender wrote.
- Bucket-default SSE-KMS with the shared CMK; versioning on; lifecycle moves both folders to Glacier Instant Retrieval after 90 days; nothing expires (see Retention in §3).
- GuardDuty tags each `inbound/` object with `GuardDutyMalwareScanStatus`.
- Tenant export and delete (FR-30) work from the Postgres rows, not from folder listing.

**Accepted attachments — `mbai-staging-documents-058190633983`** (existing)

```
mbai-staging-documents-058190633983/
└── <company_id>/
    └── <loan_file_id>/
        └── <document_id>.<ext>       ← same path as any other upload
```

- `Document.upload_source = BORROWER_INBOX` for emailed attachments (`UPLOAD_LINK` for the secure link, `USER_UPLOAD` for manual, `MISMO_IMPORT` for imports).
- `InboundAttachment.document_id` links back to the attachment, and from there to the email, sender and authentication result.
- S3 object metadata on email-sourced documents: `source=email`, `inbound-message-id=<id>`.
- In the app: "Email · from john.smith@gmail.com · Oct 20" on the document, linking to the message.

An emailed attachment therefore exists twice: inside the raw email (evidence of what was received) and as a document (what the app works with). Intentional.

**Dev:** no S3. Raw inbound already goes to local storage at `inbound-raw/<message_id>.eml`; outbound copies use `outbound-raw/<communication_id>.eml`.

## 5. Status

| Item | State |
|---|---|
| Step 0 — decisions | **Done** 2026-10-19 (§3) |
| Outbound SES identity `mail.staging.mortgageboss.ai` (DKIM, MAIL FROM `bounces.mail.staging…`, DMARC, config set, events SNS topic) | **Applied** to staging. Branch `infra/ses-outbound-staging`, commit 20f5e472, not yet merged. `plan` clean |
| SES production access, staging | **Granted** 2026-10-19, case 179246520300535 |
| LP-981 — inbound module → shared plumbing, `mbai-staging-mail` | ✅ **Done** 2026-10-20 (code) on `infra/lp-981-mail-bucket`; applied 2026-10-21 in LP-989. Ticket file `docs/tickets/LP-981.md` |
| Step 1 — LP-982–989 | ✅ **Done** 2026-10-21. Receiving activated in staging (rule set `mbai-inbound`, 2026-10-21 00:20 ET). One real email proven end to end, except scan-result events (→ LP-990). Details in §15 and `docs/tickets/LP-98*.md` |
| LP-990 — scan-result delivery fix | ✅ **Done** 2026-10-21. Scan results now reach their queue; failures go to the DLQ and alarm |
| Steps 2–6 | Not started |

**Until LP-989 and step 2 are done:** the staging account can deliver real mail to anyone (production access is account-wide). Send test mail only to own inboxes or `success@ / bounce@ / complaint@simulator.amazonses.com`. No real borrower addresses.

## 6. AWS resources (target state)

| Resource | Use | Where | State |
|---|---|---|---|
| SES production access | Leave the sandbox | Manual | Done |
| SES identity `mail.staging…` + DKIM + MAIL FROM + DMARC | Our sending/receiving domain | `modules/outbound_mail` | Done |
| SES configuration set + events SNS topic | Delivery / bounce / complaint events | `modules/outbound_mail` | Done |
| MX on `mail.staging…` → `inbound-smtp.us-east-1.amazonaws.com` | Receive on our domain | `modules/outbound_mail` (`receive_enabled`) | ✅ Done (LP-982) |
| SQS events queue + DLQ | Events to the worker | `modules/outbound_mail` | ✅ Done (LP-983) |
| Account suppression (BOUNCE, COMPLAINT) | Stop resending to bad addresses | env `main.tf` | ✅ Done (LP-984) |
| S3 mail bucket `mbai-staging-mail` (`inbound/`, `outbound/`; SSE-KMS default, versioned, Glacier IR after 90 days, no expiry) | Raw mail both directions, permanent record | `modules/inbound_mail` | ✅ Done (LP-981, applied LP-989) |
| KMS key policy for SES | Let SES write to the SSE-KMS bucket | `modules/secrets` via `ses_receipt_rule_arns` | ✅ Done (LP-989) |
| Receipt rule set + one rule (no recipients, no KMS on action, spam/virus scan, TLS required) | Accept mail for every verified identity | `modules/inbound_mail` | ✅ Done (LP-981, applied LP-989) |
| SNS inbound topic → SQS inbound + DLQ | "Message arrived" with `receipt.recipients` | `modules/inbound_mail` | ✅ Done (LP-989) |
| GuardDuty malware scan + scan-results SQS + DLQ | Scan every stored inbound message | `modules/inbound_mail` | ✅ Done. Scan, object tag and scan-result queue all work (LP-989, LP-990) |
| Active rule set | Master switch for receiving | Manual | ✅ Active since 2026-10-21 (LP-989) |
| VPC endpoints: `sqs`, `email` (SES API) | Reach SQS/SES with no NAT | `interface_endpoint_services` | ✅ Done (LP-985; proven from inside the VPC in LP-989) |
| VPC endpoint `com.amazonaws.route53` | Tenant onboarding from the api task | `interface_endpoint_services` + one-line network-module change | Step 3 (exists; deferred until used) |
| IAM worker / api | Least privilege per role | `modules/compute/iam.tf` | ✅ Done (LP-986) |
| Ops alerts SNS topic + 5 alarms | Bounce, complaint, 3 DLQs | env + `outbound_mail` + `inbound_mail` | ✅ Done (LP-987; scan-rule failure alarm added in LP-990 — 6 alarms) |
| Task env vars | Wire the app | `modules/compute` / env `main.tf` | ✅ Done (LP-988) |
| Wildcard `*._report._dmarc.mortgageboss.ai` | Accept tenant DMARC reports | Apex zone (not staging) | Step 3 |
| Per-tenant Route 53 zone + SES identity | Customer subdomains | Runtime, boto3 | Step 3 |

Not needed: Lambda, WorkMail, dedicated IPs, SES Mail Manager, Entri, per-tenant receipt rules, per-tenant KMS keys, SNS or KMS VPC endpoints (the worker never calls SNS; S3 calls KMS on the worker's behalf).

Shared reputation: all tenants send through one SES account; one tenant's bounces can get the whole account paused. Account suppression and early alarms are the v1 mitigation; SES tenant management (per-tenant reputation and pause) at ~10 tenants.

## 7. Questions for the pilot customer

1. Who manages your DNS? (15-minute call, or a ticket to an agency?)
2. Microsoft 365 or Google Workspace? (Which clients to test reply behaviour on first; whether a mailbox connector is cheap later.)
3. Do your lender portals accept a per-file contact email? (Optional free win: lender notices land on the file without forwarding.)
4. After how many days do you normally chase a borrower?
5. One-week count with a processor: loan emails she started vs. ones that arrived unprompted.
6. We may ask you to update the NS record once when we move to our production environment — OK?
7. Do any of your lenders, title or escrow companies send from old mail systems? The receiving rule only accepts mail sent over an encrypted (TLS) connection; Gmail, Microsoft 365 and nearly all modern providers do this, but a very old server would get a bounce. Decide before go-live whether to keep TLS required.

## 8. Sample emails

**First document request** — From "Priya Thaker, ABC Mortgage" `<lf-y36e@mb-mail.abcmortgage.com>`, CC `priya@abcmortgage.com`, Reply-To file address. Introduces Priya, numbered list of documents, two ways to send (secure upload link, 14 days; or reply with attachments), "please reply to this email rather than starting a new one", signature with phone, footer: file reference + don't email SSNs/account numbers.

**Reminder** — `Re:` on the original thread, processor CC'd. "Still waiting on: …", "We've received: … thank you", upload link, "if you've already sent it or need more time, just reply", footer: "automated reminder from ABC Mortgage's loan file system; replies go straight to Priya."

**Forward of a plain reply** — From "John Smith via ABC Mortgage" `<lf-y36e@…>`, To `priya@abcmortgage.com`, subject unchanged, original body and attachments, Reply-To = John + file address, one-line header: "Reply from John Smith on LF-Y36E — reply normally, or open the file."

None contain rates, amounts, approval language or account numbers — they pass the pre-send check by construction.

## 9. What already exists in the repo (checked 2026-10-19)

| Area | Exists | Where |
|---|---|---|
| Inbound infra | S3 (KMS, versioning, lifecycle), SNS → SQS + DLQ, receipt rule set + rule, GuardDuty scan | `infra/modules/inbound_mail`, `inbound_mail_enabled=false` |
| Outbound infra | SES identity, DKIM, MAIL FROM, DMARC, config set, events SNS | `infra/modules/outbound_mail` — **applied** |
| Inbound ingest | SQS poll, SES notification parsing, dedupe; local raw path `inbound-raw/<id>.eml` | `backend/app/tasks/inbound.py`, `services/inbound_ingest.py` |
| Routing, MIME, participants, triage | Accept creates a `Document` with `upload_source=BORROWER_INBOX` | `services/inbound_routing.py`, `inbound_mime.py`, `inbound_participants.py`, `inbound_triage.py` |
| Models | `InboundMessage`, `InboundAttachment` (with `document_id`), `LoanFileParticipant`, `EmailThread`, `MailboxConnection`, `Communication` (template key/version, `in_reply_to_message_id`, `upload_link_url`), `Document.upload_source` | `backend/app/models/` |
| Send path | `send_draft` with suppression, rate limit, approver; `MailTransport` registry; `transmit()` inside `send_draft`. **No transport registered** | `services/email_send.py`, `services/mail_transport.py` |
| Settings | `inbound_bucket`, `inbound_queue_url`, `inbox_domain` (to be removed) | `core/config.py` |
| Local mail | MailHog in docker-compose; SMTP settings in `.env.example` | `docker-compose.yml` |
| Documents bucket | `mbai-staging-documents-058190633983`, path `<company_id>/<file_id>/<document_id>.<ext>` | `modules/documents`, `storage/base.py` |

Found while grooming step 1 (2026-10-20): the receipt rule set `kms_key_arn` on its S3 action (client-side encryption the worker can't read) and limited recipients to one domain; the platform inbox needed a separate zone and registrar step; no mail IAM, no alarms or alert topic existed; only ECR/logs/Secrets Manager/Bedrock endpoints existed; `send_draft` sent from inside the API request; no location was defined for copies of sent mail.

## 10. Implementation plan

**0. Decide** — done (§3).

**1. AWS shared layer (Terraform)** — tickets in §15
- ✅ Request SES production access — granted 2026-10-19, case 179246520300535.
- ✅ Apply `outbound_mail` for `mail.staging.mortgageboss.ai` — identity, DKIM, MAIL FROM `bounces.mail.staging…`, DMARC, configuration set, events SNS topic (commit 20f5e472).
- ✅ `inbound_mail`: one receipt rule with no recipient condition; no KMS key on the S3 action; bucket-default SSE-KMS; key policy allows SES; drop the platform inbox domain; bucket renamed `mbai-staging-mail` with `inbound/` and `outbound/` — LP-981 (code done, not committed).
- ✅ MX on `mail.staging.mortgageboss.ai` so it receives as well as sends — LP-982.
- ✅ SQS events queue + DLQ subscribed to the events topic; KMS grant so SNS can deliver to encrypted queues — LP-983.
- ✅ SES account suppression list (BOUNCE, COMPLAINT) — LP-984.
- ✅ VPC endpoints for SQS and the SES API (`email`); Route 53 has a private endpoint too, added in step 3 — LP-985.
- ✅ IAM for the worker and api roles (email permissions in use now; tenant-onboarding permissions in step 3) — LP-986.
- ✅ Ops alerts topic and CloudWatch alarms (bounce > 2.5%, complaint > 0.05%, DLQ depth) — LP-987.
- ✅ Task environment variables: `INBOUND_BUCKET`, `INBOUND_QUEUE_URL` (read today), `EVENTS_QUEUE_URL`, `SES_CONFIGURATION_SET`, `MAIL_TRANSPORT` (read from step 2) — LP-988.
- ✅ Apply with flags on, activate the rule set, confirm the alert subscription, and test: mail to `test@mail.staging.mortgageboss.ai` → S3 object readable with plain `get_object` → inbound queue message with `receipt.recipients` → GuardDuty verdict — LP-989 (all passed except scan-result events).
- ✅ Let EventBridge deliver scan results to the encrypted queue; dead-letter and alarm on failure — LP-990.

**2. Send**
- `SesTransport(MailTransport)` (`sesv2 send_email`, config set), registered for `TOKEN_ADDRESS`; `SmtpTransport` for dev.
- `send_draft` queues a Celery task; the worker sends. Outbox `queued → sending → sent`; MessageId persisted on return; stuck `sending` never blind-retried.
- Worker writes the exact MIME to `outbound/<communication_id>.eml` before calling SES; path stored on `Communication`.
- Pre-send content check next to the suppression check.
- CC processor, Reply-To file address, threading headers in `build_outbound`.
- Events consumer updating `Communication.status`; bounces on the thread.
- Suppressed addresses are never silent. A send to an address on SES's account suppression list is **accepted by the API** (MessageId returned) and only reported afterwards as a Bounce event with `bounceSubType = OnAccountSuppressionList`. The events consumer marks that email "Not delivered: this address bounced or complained before" on the thread, so the processor can ask for another address.
- Our own suppression table is fed from Bounce (permanent) and Complaint events, and the existing suppression check in `send_draft` refuses those addresses **before** calling SES, with the same clear message. SES's account list stays as the backstop.
- `get_inbox_address()` → `lf-<display_id>@<tenant active domain>` or none; resolver and index on `display_id`; grace period for token addresses; ADR-397 amendment; remove `PRODUCTION_INBOX_DOMAIN` guard and `inbox_domain` setting.
- Frontend: Send primary; "Copy & open" only without an active domain.
- Test: Send → simulator recipient → delivered event lands; `.eml` present in `outbound/`; kill worker between SES return and commit → no duplicate.

**3. Tenant domain**
- Route 53 VPC endpoint: network module passes through entries starting with `com.amazonaws.` unchanged; add `"com.amazonaws.route53"` to `interface_endpoint_services` (~$7.30/month).
- IAM (moved from LP-986): api gets Route 53 zone/record create and change, SES identity create/get/put-mail-from/delete, `ses:GetAccount`; worker gets read-only `route53:ListResourceRecordSets` and `ses:GetEmailIdentity` for the daily health check.
- `company_mail_domain` model (subdomain, zone_id, nameservers, identity, status).
- `services/tenant_mail_domain.py` (boto3, `DOMAIN_PROVIDER=route53|fake`): create zone → show NS → verify → SES identity + DKIM + MAIL FROM `bounce.<subdomain>` → MX, DKIM, DMARC → check `ProductionAccessEnabled` → self-test → active.
- Wildcard DMARC report authorisation in the apex zone.
- Daily health task: records missing → degraded, stop sending, alert tenant admin + ops.
- Settings page: subdomain pick, NS record, Check now, status, manual-records fallback.
- Hide the `FORWARDED_ALIAS` connection UI.
- Test: test-tenant domain goes subdomain pick → NS record → active with no console work.

**4. Receive completions**
- **Mail-bucket reader (bug found in LP-986 grooming):** the app's storage backend points only at the documents bucket, but `_attachment_bytes()` reads the raw message through it. SES stores raw mail in `mbai-staging-mail`, so accepting an attachment would fail with "not found". Add a small reader for the mail bucket and use it wherever raw mail is read.
- Confirm `inbound_routing` uses `receipt.recipients`; same-tenant multi-recipient rule, else quarantine.
- Auto-attach only on DMARC pass + known contact; everything else held.
- Accepted attachments: S3 metadata `source=email`, `inbound-message-id`; "Email · from … · date" label on the document linking to the message.
- Forward-to-processor step.
- Auto-responders stored, never answered.
- Unhide `InboundMessagesPanel`; verified badge; unread indicator.
- Test: reply with two PDFs, reply-all, BCC, fresh mail, cross-tenant pair, forged From.

**5. Reminders + upload link**
- Requirement states `requested → received → validating → satisfied | rejected`.
- Celery beat reminder task; max 2; snooze; pause; stop-word.
- Signed upload-link route; included in the request template.

**6. Hardening + pilot**
- Isolation, spoofed sender, injection, forwarding loop, crash recovery tests.
- Reply-behaviour test on Outlook desktop, Outlook web, Gmail; onboarding note.
- Offboarding export + delete.
- "Sending paused" banner; retention wording in the customer agreement.
- Pilot customer questions (§7); onboard their domain.

Demo after step 2. ~5–6 weeks solo for the functional pilot.

## 11. AI replies — tiered path to automation

| Tier | What | Who sends | When |
|---|---|---|---|
| 1 | Reminders, "we received your X", upload-link resend | Template, automatic | v1 |
| 2 | Routine borrower question → AI drafts from a tenant-approved known-answers list | AI drafts; processor taps **Send** (one click, from the forwarded email or the app) | v1.5 |
| 3 | Same as tier 2, sent automatically on a high-confidence match that passes the content check | AI, automatic | After tier 2 shows ≥ 95% of drafts sent unchanged over 4–6 weeks, per tenant; tenant admin turns it on |
| 4 | Status, timelines, lender decisions, rates, amounts, eligibility | Human only | Never automatic |

Every AI draft, sent or edited, is logged with its edit diff — the evidence for the tier-3 gate. Pausing a file pauses tier 3 on that file. Tier-3 replies carry the automated footer.

## 12. Alerts

| Signal | Detected by | Told | How |
|---|---|---|---|
| Account bounce rate > 2.5% | CloudWatch on `Reputation.BounceRate` | Ops | `ops-alerts` SNS → contact@ |
| Account complaint rate > 0.05% | CloudWatch on `Reputation.ComplaintRate` | Ops | Same |
| Inbound, events or scan-results DLQ depth > 0 | CloudWatch on SQS | Ops | Same |
| Scan-result rule can't deliver (`FailedInvocations` > 0) | CloudWatch on `AWS/Events` | Ops | Same (LP-990) |
| Outbox rows stuck in `sending` | Worker check, startup + hourly | Ops | Same; flagged in admin UI |
| Tenant DNS degraded | Daily worker check | Tenant admin + ops | Email + in-app banner |
| Per-tenant bounce spike | Outbox query, weekly in v1 | Ops | Ops decides whether to pause the tenant |
| Sending paused | Tenant state | Every processor in the tenant | In-app banner |

## 13. Email injection — risks and mitigations

**Prompt injection:** the AI has no tool that sends, mutates state or reads other files (rule 6) — the control that matters. PDFs rasterized before extraction. Content passed as labelled untrusted data. Outbound content check on every send including AI drafts. Red-team test in step 6, repeated after any prompt change.

**Sender spoofing:** SPF/DKIM/DMARC verdicts stored and shown as a badge. Known-contact matching and processor-forward detection use the authenticated sender. A forged processor forward failing DMARC is treated as unknown. Unknown-sender attachments never enter intake without a click. Routing uses envelope recipients, so a forged `To:` cannot steer a message onto another loan.

## 14. Requirements

### Functional
- FR-1 One email subdomain per tenant on their own domain (default `mb-mail`, editable, collision-checked). Root domain never modified.
- FR-2 Route 53 zone created when the subdomain is chosen; onboarding shows one NS record with four nameservers; "Check now"; manual-records fallback.
- FR-3 On NS verification: DNS records + SES identity (`verified`); send+receive self-test and production-access check (`active`). Status visible: pending / verified / active / degraded.
- FR-4 Every loan file's address is `lf-<display_id lowercase>@<tenant active subdomain>`; no address without an active subdomain.
- FR-5 Destination loan from `receipt.recipients`, never To/Cc. Multi-file delivery attaches to each only within one tenant; otherwise quarantined.
- FR-6 Mail to a non-existent file address goes to an admin "unassigned" list.
- FR-7 Each message stores sender, envelope recipients, To/Cc/Bcc as metadata, subject, body, headers, SPF/DKIM/DMARC, Message-ID, raw S3 key, received time; verified/unverified badge.
- FR-8 Attachments from a recognized and authenticated contact enter intake after malware scan; others held with accept/ignore.
- FR-9 Editable known-contacts list per file, seeded from file data.
- FR-10 Authenticated processor forwards attributed to the original sender, marked "forwarded by".
- FR-11 Auto-responder messages stored, never answered.
- FR-12 Forward to processor when she was not in To/Cc: loop-safe, size-capped, best-effort replyable, tested on three clients.
- FR-13 Unread indicator on new inbound.
- FR-14 One-action Send from the file address; "Copy & open mail app" only without an active domain.
- FR-15 Reply on any thread message stays in the thread.
- FR-16 Every outbound: From file address with processor display name, Reply-To file address, CC processor.
- FR-17 Every document request includes a signed, scoped, 14-day upload link.
- FR-18 Deterministic content check on every outbound; blocked sends show the reason; override needs a note and is logged.
- FR-19 Outbound status `queued → sending → sent → delivered / bounced / complained`; bounces shown on thread and file.
- FR-20 Every outbound records template id + version, policy version, recipient authorization, delivery status.
- FR-21 Requirement states `requested → received → validating → satisfied | rejected`; reminders key off state.
- FR-22 `requested_at` recorded on send.
- FR-23 Daily reminder after N business days (default 3), same thread, lists received items; max 2, then a processor task.
- FR-24 Arrival → `received`, reminder paused; pass → `satisfied`; fail → `rejected`, re-request, clock restarts; snooze.
- FR-25 Pause automation per file; stop/unsubscribe pauses and flags.
- FR-26 Reminder footer states it is automated.
- FR-27 Activity log entries for every send and receive.
- FR-28 Raw message retained in S3 for every send (`outbound/`) and receive (`inbound/`) and linked from its row.
- FR-29 Banner when the tenant's domain is degraded or sending paused.
- FR-30 Tenant export and delete-on-request.
- FR-31 A document that arrived by email shows its source ("Email · from … · date") and links to the message; the S3 object carries `source=email` and `inbound-message-id` metadata.

### Non-functional
- NFR-1 A file address resolves to exactly one tenant and file; automated cross-tenant test incl. multi-recipient.
- NFR-2 Raw mail encrypted by bucket-default SSE-KMS; no KMS key on the SES action; read path tested first. TLS in transit; receipt rule requires TLS.
- NFR-3 The API role cannot send; the worker role cannot modify DNS.
- NFR-4 Executables/archives rejected; size cap; malware scan before intake; PDFs rasterized.
- NFR-5 Email content never treated as instructions; AI has no send/mutate tools.
- NFR-6 No NPI in subject lines.
- NFR-7 Layered sender trust; display name alone grants nothing.
- NFR-8 Inbound idempotent (Message-ID + raw hash).
- NFR-9 Failed messages go to a DLQ (events queue after 3 attempts; inbound queue after 5, since parsing and DB writes see more transient errors), alerted; never block other messages.
- NFR-10 Crash-safe sends; verified by kill-between-send-and-commit test.
- NFR-11 Broken tenant DNS stops that tenant's sending within one daily check; others unaffected.
- NFR-12 Events reconciled to the outbox within minutes.
- NFR-13 Inbound visible on the file within 2 minutes.
- NFR-14 Processor send leaves SES within 30 seconds.
- NFR-15 Inbound up to 40 MB accepted; processing and forwarding enforce their own caps.
- NFR-16 No AI-composed text sent without approval in v1.
- NFR-17 Append-only audit of every send and receive.
- NFR-18 Nothing deleted in v1 except on offboarding request; keep-everything stated in the agreement.
- NFR-19 Reputation alarms at 2.5% bounce and 0.05% complaint.
- NFR-20 Tenant onboarding needs no console work.
- NFR-21 Alarms route to the ops alerts topic.
- NFR-22 Per-tenant cost measured after the first pilot month.
- NFR-23 The processor sees every message delivered to her files in her own inbox.
- NFR-24 Borrowers need no account: reply, or use the upload link.
- NFR-25 Customer DNS setup is one record on a 15-minute call.
- NFR-26 S3 object names are server-chosen (SES message ID or our UUID); no sender-supplied text in any key.

## 15. Step 1 tickets — AWS shared layer

Order: LP-981 → 982 → 983 → 984 → 985 (stop if Route 53 needs NAT) → 986 → 987 → 988 → 989 → 990 (fix found in 989). Every apply shows a plan summary first; terraform output is never piped in a way that hides its exit code.

### Outcome of step 1

**In one line:** the AWS plumbing for email is finished and proven, but nothing changes for a processor yet. No button in the app sends or receives email until step 2.

**What will be true after LP-981–989**

*Receiving works, up to the queue*
- Email to any address at `mail.staging.mortgageboss.ai` is accepted by SES.
- It is stored in `mbai-staging-mail/inbound/`, encrypted and readable by the worker.
- GuardDuty scans it for malware and tags the result on the object.
- A "message arrived" notice lands in the inbound queue, naming the exact address it was delivered to.

*Sending is ready, with feedback*
- SES can send from `mail.staging.mortgageboss.ai`, signed and authenticated (DKIM, MAIL FROM, DMARC).
- Delivered, bounced and complaint events land in their own queue.
- SES refuses to send again to addresses that bounced or complained (account suppression list).
- The `outbound/` folder exists for copies of sent mail.

*Safety and monitoring*
- An email reaches contact@ if the bounce rate passes 2.5%, the complaint rate passes 0.05%, or any message fails processing three times.
- The worker can send and write `outbound/` but cannot change DNS; the api can set up DNS but cannot send or write the mail bucket; only SES writes `inbound/`.
- The app containers reach SQS and SES from inside the private network and have the bucket name, queue URLs and transport settings they need.

*One open question answered*
- Whether tenant onboarding can reach Route 53 without a NAT gateway (LP-985).

**What will not be true yet**

| Not yet | Comes in |
|---|---|
| A Send button that actually sends; copies saved in `outbound/` | Step 2 |
| `lf-<display_id>@…` addresses on loan files | Step 2 |
| Customer domains (`mb-mail.abcmortgage.com`) | Step 3 |
| The app reading the inbound queue and showing mail on a loan file (code exists, not connected) | Step 4 |
| Forwarding replies to the processor; email-source label on documents | Step 4 |
| Reminders and upload links | Step 5 |

**How we will know it is done**
- Send an email from your own mailbox to `test@mail.staging.mortgageboss.ai`. Within a minute: the object is in `mbai-staging-mail/inbound/`, the inbound queue has a notice naming that address, and GuardDuty reports it clean.
- Send to `success@` and `bounce@simulator.amazonses.com`: Delivery and Bounce events appear in the events queue.
- Force a test alarm: the alert email arrives at contact@.
- `terraform plan` on staging shows no changes.

**Why first**
Everything after this is app code. AWS risks (permissions, encryption, network reach, DNS) are found and fixed now, on infrastructure, rather than halfway through building the Send button.

### Outcome of each later step

| Step | Outcome a person can see |
|---|---|
| 2 — Send | A processor clicks Send; the borrower receives it from `lf-…@mail.staging.mortgageboss.ai` with the processor CC'd; delivered/bounced shows on the thread. **First demo.** |
| 3 — Tenant domain | A customer admin picks `mb-mail`, adds one NS record, clicks Check now, and their files get `lf-…@mb-mail.<their domain>` addresses |
| 4 — Receive | A borrower replies with documents; the email shows on the loan file, attachments become documents labelled "Email · from …", and the processor gets a copy in her inbox |
| 5 — Reminders | Requested documents are chased automatically on day 3 and again later; chasing stops when the right document arrives |
| 6 — Hardening + pilot | The pilot customer's processors use it on real loans |

### LP-981 — Inbound module becomes shared plumbing; one mail bucket — ✅ Done (applied 2026-10-21 in LP-989)
- Remove `recipients` from `aws_ses_receipt_rule.store` (accept every verified identity).
- Remove `kms_key_arn` from its `s3_action` (bucket default SSE-KMS already applies).
- Remove the module's own SES domain identity, verification TXT and MX; remove `mail_domain` and `route53_zone_id` inputs.
- Delete `module "inbox_dns"`; remove the `inbox_domain` variable, tfvars entry and `INBOX_DOMAIN` task env var.
- **Rename the bucket** `${name_prefix}-inbound-mail` → `${name_prefix}-mail` (free: never applied).
- **Add `outbound/`**: lifecycle rule (same Glacier + 5-yr expiry + noncurrent handling) applied to both `inbound/` and `outbound/`; bucket policy unchanged for SES (still `inbound/*` only). *(Changed in review: transition only, no expiry — see Retention in §3.)*
- Keep the rule ARN name (`${name_prefix}-inbound`) so the KMS key-policy grant still matches.
- Outputs: bucket name, inbound queue URL, scan-results queue URL, rule set name.
- **Done when:** `plan` with `inbound_mail_enabled=true` creates bucket `mbai-staging-mail`, no zone, no SES identity; the S3 action has no KMS key; lifecycle covers both folders. Nothing applied yet.
- **Result:** as above. Preview plan 23 add, 1 change (KMS key policy), 0 destroy. Lifecycle is one rule per folder (not bucket-wide) so the GuardDuty validation object at the bucket root never expires. `inbox_domain` / `INBOX_DOMAIN` kept in staging and dev because the app reads it; removed in step 2. Found the missing SNS key grant → LP-983. Details: `docs/tickets/LP-981.md`.

### LP-982 — Receive on `mail.staging.mortgageboss.ai` — ✅ Done
- `outbound_mail`: new `receive_enabled` flag adding `MX 10 inbound-smtp.<region>.amazonaws.com` on `send_domain`.
- Staging: `receive_enabled = var.inbound_mail_enabled`, so MX only exists when the receiving stack does.
- **Done when:** plan shows one MX on `mail.staging…`; bounce MX on `bounces.mail.staging…` unchanged.
- **Result:** MX `10 inbound-smtp.us-east-1.amazonaws.com`, TTL 600, confirmed with `dig` after LP-989. Details: `docs/tickets/LP-982.md`.

### LP-983 — Delivery events queue + KMS grants for SNS — ✅ Done
- `outbound_mail`: SQS `events` queue + DLQ (maxReceiveCount 3), SNS subscription with raw delivery, queue policy allowing the topic. Output the queue URL.
- **Shared key policy (found in LP-981):** the inbound topic and queues are encrypted with the shared CMK, but the key policy has no statement for `sns.amazonaws.com`. Without it SNS cannot deliver to an encrypted SQS queue and messages vanish silently. Add one statement granting `sns.amazonaws.com` `kms:GenerateDataKey*` and `kms:Decrypt`, conditioned on the inbound and events topic ARNs.
- Check whether the events SNS topic is KMS-encrypted; if so, confirm SES (configuration-set event publishing) is allowed to use the key, and add a grant conditioned on the configuration set if not.
- **Done when:** a send to `success@simulator.amazonses.com` and `bounce@simulator.amazonses.com` puts Delivery and Bounce events in the queue; the inbound path is proven in LP-989.
- **Result:** events queue and DLQ (max 3 receives), raw delivery, queue policy; SNS key grant names both the inbound and events topics. A send to `success@simulator` put a Delivery event in the queue (re-checked in LP-989). **Missed:** the grant covered SNS but not EventBridge, which also writes to an encrypted queue (scan results) → LP-990. Details: `docs/tickets/LP-983.md`.

### LP-984 — Account suppression list — ✅ Done
- `aws_sesv2_account_suppression_attributes` with `BOUNCE`, `COMPLAINT`, at env level (account-wide singleton).
- **Done when:** `aws sesv2 get-account` shows both reasons.
- **Result:** applied without `count` and with `prevent_destroy`, so a later destroy can't silently clear the account setting. Details: `docs/tickets/LP-984.md`.

### LP-985 — VPC endpoints — ✅ Done
- Check real names: `aws ec2 describe-vpc-endpoint-services --region us-east-1` for SES API, SQS, Route 53.
- Add `sqs` and the SES API endpoint to `interface_endpoint_services`.
- Route 53: add the endpoint if it exists; if not, **stop** and record a decision (NAT gateway ~$32/month, or onboarding outside the VPC) before step 3.
- **Found:** SES API endpoint is `email` (not `email-smtp`). Route 53 has a private endpoint (`com.amazonaws.route53`) but the module can't build its name yet → deferred to step 3. ECS Exec is off and no tasks were running → in-task reachability test moves to LP-989. Cost ≈ $14.60/month for the two endpoints.
- **Done when:** worker reaches SQS and SES from inside the VPC; Route 53 answer written in §3.
- **Result:** `sqs` and `email` endpoints applied. Proven in LP-989 from a one-off worker task: SQS `OK`, SES `REACHED:AccessDenied` (path works, permission not granted), S3 mail bucket `OK`. Details: `docs/tickets/LP-985.md`.

### LP-986 — IAM — ✅ Done
- **Worker:** `s3:GetObject` on `mbai-staging-mail/inbound/*`; `s3:PutObject` on `mbai-staging-mail/outbound/*`; consume the inbound, scan-results and events queues (Receive, Delete, ChangeVisibility, GetQueueAttributes, GetQueueUrl); `ses:SendEmail`/`SendRawEmail` on `identity/*` and the configuration set; `kms:Decrypt` + `kms:GenerateDataKey` on the shared CMK. Stays read-only on the documents bucket.
- **Api:** `s3:GetObject` on `mbai-staging-mail/inbound/*` and `kms:Decrypt` — accepting an attachment runs in the api (`api/inbound.py` → `accept_attachment`) and reads the raw message. **No send, no write to the mail bucket, no queue access.**
- Statements for the inbound stack render only when receiving is on, so they appear in LP-989.
- **Moved to step 3:** Route 53 zone/record permissions, SES identity create/get/delete, `ses:GetAccount` (api), and the worker's read-only DNS health-check permissions — added with the code that uses them and the Route 53 endpoint.
- **Done when:** IAM policy simulator — worker can send and read the events queue; api can do neither; worker still cannot write documents.
- **Result:** in LP-989 the simulator matched all 8 checks: worker reads `inbound/`, writes `outbound/`, can't write `inbound/`, consumes the inbound queue; api reads `inbound/`, can't write `outbound/`, can't send, can't read the queue. Details: `docs/tickets/LP-986.md`.

### LP-987 — Ops alerts and alarms — ✅ Done
- `ops-alerts` SNS topic, email subscription to `contact@mortgageboss.ai`.
- Alarms: `AWS/SES Reputation.BounceRate` > 0.025; `Reputation.ComplaintRate` > 0.0005; `ApproximateNumberOfMessagesVisible` > 0 on inbound DLQ, events DLQ, scan-results DLQ.
- **Done when:** `aws cloudwatch set-alarm-state` on one alarm delivers an email.
- **Result:** 5 alarms (`ses-bounce-rate`, `ses-complaint-rate`, `outbound-mail-events-dlq-not-empty`, `inbound-mail-dlq-not-empty`, `scan-results-dlq-not-empty`) behind an `alarms_enabled` flag; ops-alerts subscription confirmed at contact@. The alarm → email path was proven for real in LP-989 (a test message hit the events DLQ). Details: `docs/tickets/LP-987.md`.

### LP-988 — Task environment wiring — ✅ Done
- Api and worker containers (shared env map; frontend gets none):
  - `INBOUND_BUCKET` = `mbai-staging-mail` and `INBOUND_QUEUE_URL`. The app already reads both; set only when receiving is on, so they appear in LP-989.
  - `EVENTS_QUEUE_URL`, `SES_CONFIGURATION_SET`, `MAIL_TRANSPORT=ses`. Read from step 2; harmless now because settings ignore unknown variables (`extra="ignore"`).
- Not set: `INBOUND_KMS_KEY_ARN` (must not trigger any client-side decryption; bucket-default SSE-KMS since LP-981), `DOMAIN_PROVIDER` (step 3), `MAIL_BUCKET` (renamed from `INBOUND_BUCKET` in step 2 together with the code).
- Setting `INBOUND_QUEUE_URL` is safe: `inbound.poll_queue` is not on the beat schedule, so LP-989's test message stays in the queue to inspect.
- **Done when:** new api and worker task-definition revisions carry the variables, and running services reach steady state.
- **Result:** api, worker **and migrate** task definitions (they share one env) carry the variables; worker `:106` has `INBOUND_BUCKET=mbai-staging-mail` and `INBOUND_QUEUE_URL`, no `INBOUND_KMS_KEY_ARN`. Found: only `INBOUND_QUEUE_URL` is read today. `INBOUND_BUCKET` is not read (ingest uses the bucket named in each notification), and nothing reads `MAIL_TRANSPORT`, `EVENTS_QUEUE_URL` or `SES_CONFIGURATION_SET` yet — step 2 wires them. Details: `docs/tickets/LP-988.md`.

### LP-989 — Apply and prove — ✅ Done (one gap → LP-990)
1. `inbound_malware_scan_enabled = true` → plan → apply.
2. `inbound_mail_enabled = true` → plan → apply.
3. Manual: `aws ses describe-active-receipt-rule-set` (expect none), then `aws ses set-active-receipt-rule-set --rule-set-name mbai-inbound`.
4. Manual: confirm the SNS subscription email at contact@.
5. Test: from your own mailbox, email `test@mail.staging.mortgageboss.ai` → object under `mbai-staging-mail/inbound/` readable with plain `get_object` → message in the inbound queue with `receipt.recipients = ["test@mail.staging.mortgageboss.ai"]` → GuardDuty verdict in scan-results.
6. Network reachability from inside the VPC (deferred from LP-985): run a one-off ECS task with the worker image (no ECS Exec needed) that calls `sqs.list_queues` and `sesv2.get_account` with a 5-second connect timeout and prints OK / AccessDenied / timeout. OK or AccessDenied = path works; timeout = missing endpoint or security group.
7. Record activation date and test results in `infra/envs/staging/README.md`.
- **Done when:** step 5 passes end to end.
- **Result:** applied (both flags in one apply: the scan lives inside the inbound module, so it can't go first alone) and rule set `mbai-inbound` activated 2026-10-21 00:20 ET; no other rule set was active. Test email (530 KB, one PDF) passed: stored in `inbound/`, readable with plain `get_object`, `aws:kms` with our key, GuardDuty tag `NO_THREATS_FOUND`, queue notice with the right `receipt.recipients`, spam/virus/SPF/DKIM/DMARC all PASS, IAM simulator 8/8, in-VPC reachability OK, simulator Delivery event, alarms and subscription OK, DLQs empty after cleanup. **Failed:** scan-result events never reached `mbai-staging-scan-results` (EventBridge `FailedInvocations = 1`) → LP-990. Lessons: one-off tasks need `uv run python` (plain `python` lacks the app's packages); receive test messages with `--max-number-of-messages 1` and a non-zero visibility timeout — a batch with visibility 0 used up the events queue's 3 receives in one call and set off its DLQ alarm. Details: `docs/tickets/LP-989.md`.

### LP-990 — Deliver scan results (found in LP-989) — ✅ Done
- **Problem:** GuardDuty scans each message and tags it, but the EventBridge rule `mbai-staging-inbound-scan-results` can't put the result in `mbai-staging-scan-results`. That queue is encrypted with the shared key, and the key policy doesn't allow `events.amazonaws.com`. The event is dropped and nothing alarms. GuardDuty's plan-health events use the same rule, so they're lost too.
- Key policy: add `events.amazonaws.com` with `kms:GenerateDataKey*` and `kms:Decrypt`, conditioned on `aws:SourceArn` = the rule's ARN (built by name, the same pattern as the SNS grant, so there's no module cycle).
- Rule target: dead-letter to the existing `mbai-staging-scan-results-dlq` (already alarmed); its queue policy allows the rule to send.
- One alarm on the rule's `FailedInvocations` > 0, to ops-alerts.
- **Done when:** one test email puts a verdict message in the scan-results queue; `FailedInvocations` stays 0.
- **Result:** applied 2026-10-21 (2 added, 2 changed, 0 destroyed). Key statement `AllowEventBridgeDeliveryToEncryptedQueues` uses `StringEquals` on source account and rule ARN, like the SNS one. Test email: scan-results queue got `GuardDuty Malware Protection Object Scan Result` for the right object, `NO_THREATS_FOUND`; `FailedInvocations` 0 (was 1); DLQs 0; all six alarms OK. **Lesson:** every AWS service that writes to a queue or bucket encrypted with our key needs its own key-policy grant (SES, SNS, EventBridge so far); the failure is on AWS's side, so our code never sees an error. Details: `docs/tickets/LP-990.md`.

### App-side follow-ups created by step 1 (scheduled in steps 2–4)
- Move `send_draft`'s `transmit()` into a worker task (rule 8).
- Worker writes `outbound/<communication_id>.eml` before calling SES; column on `Communication` for its path.
- Rename setting `inbound_bucket` → `mail_bucket` and env `INBOUND_BUCKET` → `MAIL_BUCKET` together; add readers for `EVENTS_QUEUE_URL`, `SES_CONFIGURATION_SET`, `MAIL_TRANSPORT`.
- Put `inbound.poll_queue` on the beat schedule (step 4, once the mail-bucket reader exists).
- Remove `inbox_domain` variable, tfvars value and `INBOX_DOMAIN` task env var in **staging and dev** together, once addresses come from the tenant subdomain.
- Address on `display_id`; remove `inbox_domain`, `PRODUCTION_INBOX_DOMAIN` and its guard; ADR-397 amendment.
- `.env.example`: `INBOX_DOMAIN=imbox.localhost` → dev fake tenant domain.
- Email-sourced documents: S3 metadata + source label (FR-31).
- Hide `FORWARDED_ALIAS` connection UI; mark Route B docs/ADRs superseded by this doc.

## 16. Diagrams

- **Loan Email Architecture** — three straight flows (in, out, domain setup); for customer conversations.
- **Loan Email AWS Detail** — every AWS resource, VPC, numbered flows, resource change table; for implementation.

PNG exports sent in chat 2026-10-19. Both still show the dropped platform inbox, the old bucket name and alarm thresholds of 5% / 0.1%; regenerate after step 1.

## 17. After v1, in order

Legal hold + retention schedule → AI reply tier 2 → M365 mailbox connector (if the customer is on M365) → AI reply tier 3 once gated → SES tenant management (per-tenant reputation and pause) → Domain Connect for GoDaddy-type DNS → production AWS account (repeat production access; re-delegate tenant NS).

## 18. Log

- 2026-10-21 — LP-990 ✅: EventBridge key grant, DLQ on the scan rule, `scan-results-rule-failed` alarm. Scan results now reach their queue. All AWS work for step 1 closed.
- 2026-10-21 — Step 1 done. LP-982–989 ✅. Receiving activated in staging; one real email proven end to end. Gap found: EventBridge can't write scan results to the encrypted queue (no key grant) → LP-990. Retention corrected to match the infra: Glacier IR after 90 days, no expiry, until legal hold exists. Pilot question 7 added (TLS-required receiving).
- 2026-10-20 — LP-988 scoped: existing setting names kept (`INBOUND_BUCKET`), step-2 values set early, `DOMAIN_PROVIDER` deferred to step 3, `INBOUND_KMS_KEY_ARN` not set. Poller stays unscheduled until step 4.
- 2026-10-20 — LP-986 scoped to permissions in use: api reads raw mail for accept; tenant-onboarding and health-check permissions moved to step 3. Step 4: mail-bucket reader needed (raw mail read through the documents-bucket backend).
- 2026-10-20 — LP-985: SQS and SES API (`email`) endpoints. Route 53 private endpoint exists; added in step 3 with a one-line module change — no NAT decision needed. In-task reachability test moved to LP-989 (one-off ECS task).
- 2026-10-20 — Step 2: suppression made visible — `OnAccountSuppressionList` bounces shown on the thread; own suppression table fed from bounce/complaint events and checked before sending.
- 2026-10-20 — Plan changes from LP-981: SNS key-policy grant added to LP-983; INBOX_DOMAIN removal moved to step 2 (staging + dev). Rule: tickets stay in this doc after they're built; they're marked ✅ Done with a short result, and full details live in `docs/tickets/LP-*.md`.
- 2026-10-20 — §15 gained "Outcome of step 1" (what will and won't be true, how we'll know, why first) and a one-line outcome per later step.
- 2026-10-20 — Storage layout (§4a): mail bucket renamed `mbai-staging-mail` with `inbound/` and `outbound/`; copies of sent mail kept. Email-sourced documents: existing `upload_source = BORROWER_INBOX` and attachment link kept; S3 metadata and visible source label added (FR-31). LP-981, LP-986, LP-988 updated.
- 2026-10-20 — Environments table gained the borrower-view header block. This file (`loan-email.md`) is the single copy; `claude/loan-email.md` retired.
- 2026-10-20 — Step 1 groomed into LP-981–989. Platform inbox `imboxstaging` dropped; `mail.staging.mortgageboss.ai` sends and receives. Account suppression list added. Alarm thresholds lowered to 2.5% / 0.05%. Sending moves to the worker. Route B superseded. Doc restructured: environments table (§4), status (§5), tickets (§15).
- 2026-10-19 — Step 0 decided: `display_id` address; us-east-1; no subdomain → draft mode; staging is the pilot environment; dev local with MailHog; separate test-tenant domain. Outbound SES applied to staging; bounce domain fixed to `bounces.mail.staging…` after SES rejected the sibling name (validation added). Production access granted, case 179246520300535. DMARC reports to contact@mortgageboss.ai.
- 2026-10-19 — Repo checked; plan rewritten as a delta on the parked LP-800 work. Second external review applied (envelope-recipient routing, one receipt rule, bucket-default SSE-KMS, crash-safe sends, received ≠ satisfied, trust levels, zone-first DNS, offboarding before GA, precise product promise).
- 2026-10-18 — Injection mitigations, AI reply tiers, alert routing, requirements added. Scope corrected: routing key is the address.
- 2026-10-17 — Approach chosen: customer subdomain + per-file address + SES; CC processor on every send; plain replies forwarded in full. LendFlowPro reviewed.
