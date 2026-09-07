# Phase 4 build plan — what to build, in what order, and how

- **Companion:** [`phase4.md`](phase4.md) is the design (architecture, data model, decisions).
  This document is the execution plan. Ticket scope lives here; the *why* lives there.
- **Figures:** [`phase4-mail-flows.md`](phase4-mail-flows.md) — the eight flows this plan builds.
- **Series:** LP-800 … LP-816. Last Phase 3 ticket was LP-647.
- **Date:** 2026-09-07. **Revised 2026-09-07** after a coverage audit against the source
  specification (`V1_Build_Plan_v3_rule_engine.docx`, Phase 4.1–4.5 and the Phase 4 testing
  checklist). The audit found eight uncovered requirements; §C.5 holds the tickets that close them
  and §B now sequences them. Nothing below is aspirational — every gap named was verified against
  both the spec text and the repo.

---

## §A — Four tracks, because they do not block each other

The single biggest scheduling mistake available here is treating Phase 4 as one sequence. It is
four, and three of them can start on day one.

| Track | What it is | Blocked by | Who |
|---|---|---|---|
| **1. Data** | The borrower instruction catalog (LP-800) and the requestable-finding filter (LP-801) | nothing | engineer + **Priya** |
| **2. Infra** | Delegated zone, MX, SES receipt rule, S3 bucket, SQS, IAM | nothing | engineer (Terraform) |
| **3. Backend** | Ingest, routing, triage, drafting, send | LP-802 for settings; track 2 for anything that receives real mail | engineer |
| **4. Frontend** | Triage queue, draft composer, timeline | its backend endpoint | engineer |

**Start track 2 on day one even though nothing uses it for weeks.** Production
`inbox.mortgageboss.ai` needs a delegated zone whose NS records a human enters at the registrar and
then waits on — the same two-phase gate `infra/envs/staging` already went through. That wait is
calendar time you cannot compress later. Staging has no such wait (see §C, INFRA-1).

**Track 1 has a dependency that is not code: Priya's time.** And it is already owed —
`documents/catalog.py` says in its own docstring that the taxonomy is *"an INDUSTRY-STANDARD STARTER
… not validated against the resident domain expert's (Priya's) real library … expect it to refine
with Priya."* LP-800 should be **the same session**: validate the type list and capture the borrower
instructions in one pass, rather than booking her twice.

---

## §B — Five milestones, each one demonstrable

Stop after any of these and the product is better than it was. That is the ordering constraint.

### M1 — The email is right (≈ 18–20 days, **zero infrastructure**)

`LP-800 · LP-801 · LP-802 · LP-817 · LP-822 · LP-809 · LP-810 · LP-811`

> Priya clicks "Request docs" on four findings. She gets one email that asks the borrower only for
> what the borrower can actually produce, tells them exactly how to get each document, and does not
> contain a rate or the word "approved". She copies it, sends it from Outlook, and every need on the
> file moves to REQUESTED with a timestamp.

**This is the whole outbound half and it needs no DNS, no SES, no S3, no mailbox.** It is the highest
value per unit of risk in Phase 4. Build it first, and be willing to ship only this.

### M2 — Mail arrives and is safe (≈ 14–16 days)

`INFRA-1 · INFRA-2 · INFRA-3 · LP-803 · LP-804 · LP-819`

> Forward an email with a PDF to `lf-<token>@inbox.staging.mortgageboss.ai`. Within seconds there is
> a row in `inbound_messages` with the SPF/DKIM/DMARC/virus verdicts, the raw `.eml` in S3 under a
> CMK, and a rasterized, sanitised derivative of the attachment. Nothing is attached to a loan file
> yet — deliberately.

### M3 — Mail lands on a file (≈ 15 days)

`LP-805 · LP-806 · LP-807 · LP-813 · LP-815`

> The borrower replies with three PDFs. Priya opens the Communication tab, sees a card with the
> sender, a green auth badge, thumbnails and a suggested document type, clicks **Accept**, and the
> documents enter the existing classify → extract → needs pipeline. The needs flip to Received.

**End of M3 the feature is real — but M3's demo is not yet representative, and that matters.**
The borrower only replies *to the file address* if she told them to send there, or if the app sent
the request (LP-816, M5). On M1's copy-and-paste path she sends from Outlook, the borrower replies
to **her**, and that is Route B. So ladder rungs 1 and 2 are unreachable until either LP-808 or
LP-816 lands, and rung 3 — the `[LF-xxxxxxxx]` footer tag — is doing the work, from inside a body
that Gmail and Outlook mobile routinely trim when quoting.

Two honest consequences: **M3 must ship with explicit "send your documents to this address"
instructions** in the request email (LP-817's initial-request template), and **M4 is not optional
polish** — it is what makes inbound work for a processor who sends from her own client. Treat M3+M4
as one release, not two.

### M4 — She keeps her own address (≈ 4–5 days)

`LP-808`

> An admin adds one routing rule at Herco. Mail sent to `processing@herco.com` now also appears in
> the triage queue, correctly attributed, with trust evaluated from the original hop.

### M5 — The loop closes (≈ 16 days)

`LP-812 · LP-818 · LP-814 · LP-820 · LP-821 · LP-816`

> Timeline, reminders, underwriter contact, secure links, and send-from-app.

**Total ≈ 68–74 working days ≈ 14–15 weeks at full time.** The unified build plan budgets 2–3 weeks
for Phase 4; that estimate predates the attachment safety pipeline, the instruction catalog and
Route B, none of which are optional. Say so now rather than at week four.

---

## §C — Ticket by ticket

Conventions throughout: every ticket writes `docs/tickets/LP-XXX.md`; architectural decisions become
ADRs in `decisions.md`; CI (ruff / mypy strict / pytest, biome / tsc / build) stays green. Migrations
are named `YYYYMMDD_HHMM_<rev>_<slug>.py` to match the 75 already in `backend/alembic/versions`.

---

### INFRA-1 — Inbound mail DNS and SES

**Track** infra · **~2 days + registrar wait for prod** · **No app code**

**Build**

- `infra/modules/inbound_mail/` — new module: SES domain identity + verification TXT, the MX record,
  the receipt rule set and rule, the S3 bucket (SSE-KMS, no public access, lifecycle to Glacier then
  expiry per the retention decision), the SNS topic or Lambda notification, the SQS queue and its DLQ,
  and the IAM policy letting SES write to the bucket.
- `infra/envs/staging/main.tf` — instantiate it. **Staging needs no registrar step**: the
  `staging.mortgageboss.ai` zone already exists and is authoritative for everything under it, so
  `inbox.staging.mortgageboss.ai` is one `aws_route53_record` of type MX inside it.
- Production reuses `infra/modules/dns` with **`enable_tls = false`** — an inbound-only mail domain
  serves no HTTPS and needs no ACM certificate, so the phase gate that exists for the certificate is
  irrelevant. Phase 1 creates the zone and outputs nameservers; a human enters them at the registrar;
  phase 2 applies the rest.

**Watch for**

- Only **one receipt rule set is active** per account per region. If anything else ever uses SES
  receipt in this account, it is a rule *in the same set*, not a second set.
- SES inbound is not available in every region and in neither GovCloud region. `us-east-1` is fine.
- The `inbox.` subdomain gets **no SPF, no DKIM, no A record** — an inbound MX overlapping an
  authenticated sending domain is the documented cause of an infinite mail loop.

**Done when** `dig MX inbox.staging.mortgageboss.ai` answers, and a message sent by hand to any
address at that domain appears as an object in the bucket.

---

### INFRA-2 — Malware scanning

**Track** infra · **~1 day**

Enable **GuardDuty Malware Protection for S3** on the inbound bucket; route scan results to
EventBridge. Free tier is 1,000 requests + 1 GB/month/region, which covers the pilot outright.

**Watch for** the tag being written **after** the scan — the pipeline must wait for the EventBridge
result event, never read the object on `PutObject` and hope. Objects with no result inside N minutes
go to quarantine, not to extraction.

---

### LP-800 — Borrower instruction catalog

**Track** data · **~3–4 days, most of it Priya's** · **No migration**

**Build**

- Extend `backend/app/documents/catalog.py`. **Keep it as code, not a table** — ADR-053/ADR-167
  already decided that tier and category are app-layer knowledge precisely so a type can be added in
  a one-line edit with no migration, and the same reasoning applies here.
- Add a second mapping alongside `CATALOG`, keyed by the same slugs:

  ```python
  @dataclass(frozen=True)
  class BorrowerGuidance:
      responsible_party: ResponsibleParty     # borrower | processor | lender | title
                                              # | employer | cpa | agent | insurer
      borrower_label: str | None = None       # "Bank statements — 2 most recent months"
      how_to_obtain: str | None = None        # where to get it, in the borrower's words
      completeness_rule: str | None = None    # what "all pages" means for THIS type
      common_rejects: tuple[str, ...] = ()    # screenshots, partial pages, summaries
      template_url: str | None = None         # gift letters, LOEs, 4506-C

  GUIDANCE: dict[str, BorrowerGuidance] = {...}
  ```
- `get_guidance(document_type)` returning a safe default (party `processor`, no instructions) for an
  unknown slug — the catalog's existing never-raise discipline.
- A test asserting **every** `CATALOG` key has a `GUIDANCE` entry with at least a
  `responsible_party`, mirroring the existing test that keeps the catalog and the classification
  prompt in sync.

**Scope the authoring by tier or it will not get done.** Roughly 25 types are ever asked of a
borrower — pay stubs, W-2s, bank statements, tax returns, IDs, insurance declarations, gift letters,
LOEs, divorce decrees, lease agreements, EMD proof. Those get full entries. Everything else gets
`responsible_party` only.

**Done when** the mapping is complete for party, the 25 borrower-facing types have full entries,
Priya has reviewed them, and the sync test passes.

---

### LP-801 — Requestable-finding filter

**Track** backend · **~2 days** · **Migration: possibly one**

**Build**

- A `requestable` predicate over findings, excluding the consolidated `unidentified_document` case.
  The flag lives on `RuleEvaluation` in-run (`verification/rule_engine/result.py:145`) and is
  **not a persisted column** — so either read it from the run path or persist the cause on the
  finding. Persisting is the smaller long-term cost; decide in the ticket and write the ADR.
- Phrase ID-2 / ID-3 / ID-4 from `requested_documents` as "one more source", never as a named document.
- **Normalise `details.docs_requested`.** The per-finding path writes
  `{by, at, needs_item_id}`; the bulk path writes a bare `True`
  (`services/finding_resolution.py:540`), so the bulk path loses the finding → needs-item link the
  draft needs. One shape, both paths.
- **Fix the activity type.** The bulk path logs `ActivityType.FINDING_RESOLVED` for an action its own
  docstring says does not resolve the finding; the per-finding path correctly logs
  `NEEDS_ITEM_CREATED`. The Phase 4.3 timeline is built on this log, so a request currently reads
  there as a resolution.

**Done when** a file with an unidentified document produces zero borrower-facing requests from it,
and both request paths write the same `docs_requested` shape and the same activity type.

---

### LP-802 — ADRs, settings, and the domain constant

**Track** backend · **~1 day** · **No migration**

**Build**

- ADRs: *ingestion source is pluggable*; *SES over SendGrid*; *the inbox address is exposed, the token
  is not*; *outbound never carries an NPI attachment*.
- `INBOX_DOMAIN` moves from `models/loan_file.py:59` to `core/config.py` as `inbox_domain`. It must
  differ per environment — `inbox.staging.mortgageboss.ai` vs `inbox.mortgageboss.ai` — and the
  constant's own comment already anticipates this.
- Widen `INBOX_TOKEN_BYTES` from 12 to 16 (96 → 128 bits) in `services/loan_file_ids.py:29`. Free
  now, a migration later.
- New settings: `inbound_bucket`, `inbound_queue_url`, `inbound_kms_key_arn`. The six existing
  `smtp_*` settings (`core/config.py:263-268`) stay pointed at MailHog for local development.
- **ADR-094 changes here.** It asserts `inbox_token` never appears in a response and
  `tests/integration/test_contracts_leaks.py` enforces it. Expose `get_inbox_address()`; never the
  raw token.

---

### LP-803 — Ingest skeleton

**Track** backend · **~3 days** · **Migration: yes**

**Build**

- `backend/app/models/inbound_message.py` — company-owned; `loan_file_id` nullable until routed;
  `UNIQUE (company_id, ingest_key)` where `ingest_key = COALESCE(ses_message_id,
  normalized_message_id, sha256(raw))`; `auth_verdicts` and `references` as `jsonb`;
  `routing_state`, `routing_signal`, `routing_confidence`; `raw_storage_path`; **`is_dsn`** and
  **`is_auto_reply`** — both are in `phase4.md` §4 and were dropped from an earlier draft of this
  ticket. Without `is_dsn` you cannot implement the empty-`Return-Path` suppression rule, and a
  bounce files itself as a borrower document.
- `backend/app/tasks/inbound.py` — `inbound.ingest_message`. **Add the module to `_TASK_MODULES` in
  `tasks/celery_app.py:19`.** Its own comment warns that a module left out never imports, the task
  is unregistered, and enqueued messages are dropped silently.
- `backend/app/services/inbound_ingest.py` — pull from S3, dedup with `INSERT … ON CONFLICT DO
  NOTHING`, store verdicts, stop.
- An SQS consumer. Prefer a Celery broker transport or a small poller task on beat over inventing a
  second daemon.

**Watch for** returning **200 on a duplicate**. A non-2xx drives a provider into its retry schedule
forever. And take verdicts from the SES `receipt` object only — never from an `Authentication-Results`
header in the message body, which an attacker can forge.

**Done when** the same message delivered twice produces exactly one row, and a message with
`dmarcVerdict: GRAY` is stored as GRAY rather than coerced to PASS.

---

### LP-804 — MIME parsing and attachment safety

**Track** backend · **~4–5 days** · **Migration: yes**

**Build**

- `backend/app/models/inbound_attachment.py` — filename original and normalised, sniffed type, size,
  sha256, scan verdict, safety state, `derived_storage_path`, disposition, nullable `document_id`.
- `backend/app/services/inbound_mime.py` — stdlib `email` with `policy=default` and `BytesParser`;
  **recurse into `message/rfc822`** (borrowers forward, and the real PDF is often nested), depth
  capped at 5; TNEF / `winmail.dat`; RFC 2231 filenames with an RFC 2047 fallback.
- `backend/app/services/attachment_safety.py` — magic-byte sniff against an allowlist
  (**add `tiff` and `heic`**; `storage/base.py` already permits the extensions while
  `services/documents.py` rejects the content types, and borrowers email HEIC from iPhones
  constantly); reject archives outright in V1; `pikepdf` strips `/JS`, `/OpenAction`, `/AA`,
  `/EmbeddedFile`, `/Launch`, `/XFA`; detect but never crack encrypted PDFs; rasterize every page.
- New dependencies: `pikepdf`, `pypdfium2`, `puremagic`, `mail-parser`. Not `talon` (dead since
  2016), not `flanker` (abandoned).

**Watch for** filtering attachments on `Content-Disposition`. It is a hint and frequently absent — a
phone photo of a paystub arrives `inline`. Filter on *has a filename* or *is not text*.

**Done when** a forwarded message with a nested PDF yields the PDF; a `.pdf` that sniffs as ZIP is
quarantined; and the extraction path reads only the rasterized derivative.

---

### LP-805 — Routing and participants

**Track** backend · **~3 days** · **Migration: yes**

**Build**

- `backend/app/models/loan_file_participant.py` and `email_thread.py`.
- `backend/app/services/inbound_routing.py` — the six-rung ladder. Rung 2 must match the **whole**
  `References` array against stored message-ids, not just the last entry; clients truncate the middle
  differently.
- **The token resolver, written once and deliberately.** It inverts the tenancy invariant: it starts
  from an address, not an authenticated user, and derives `company_id` **from** the loan file it
  resolves. Nothing else in the codebase may do this. Case-insensitive lookup; unknown and expired
  tokens behave identically; rate-limit probing by source IP.
- Seed participants from `borrowers.email`, `loan_files.loan_officer_email`, `lenders.contact_email`
  — all of which exist today.
- Emit `Communication(direction=INBOUND, status=RECEIVED)` and the `COMMUNICATION_RECEIVED` activity.
  Both the model and the enum value already exist and have never been used.

**Done when** a token address routes with confidence `certain`, an unknown sender on a known file
routes `medium`, and an unroutable message lands in the company queue and is invisible to every
other company. **Write the cross-tenant test first.**

---

### LP-806 — Triage API and accept-into-file

**Track** backend · **~3 days** · **Migration: small**

**Build**

- `backend/app/api/inbound.py` — list the queue, accept, reassign, reject.
- Accept calls the existing `create_document(upload_source=UploadSource.BORROWER_INBOX,
  uploaded_by_user_id=None)` and sets **`Document.possible_duplicate`** when a current document of
  that type is already on the file. That column, its schema field and its frontend type all exist and
  nothing has ever written `True` to it; its docstring names this exact case.
- Per-file `auto_accept_inbound` flag, default **false**.
- **A `correspondence` disposition alongside `accepted`.** Not every accepted attachment is a
  borrower document: a lender's conditional-approval PDF satisfies no need and would be classified
  against a 166-type *borrower* taxonomy. `correspondence` attaches the file to the thread and the
  timeline without entering classify → extract → needs. Phase 4.5 depends on this existing.

**Done when** accepting produces a document indistinguishable from a manual upload except for its
`upload_source`, and the needs update runs under the existing per-file Redis lock.

---

### LP-807 — Triage queue UI

**Track** frontend · **~4 days**

Replace the `TabPlaceholder` at
`frontend/app/(protected)/loan-files/[id]/communication/page.tsx`. Cards carry sender, auth badge,
subject, attachment thumbnails, and the suggested file / type / need; one click accepts. A separate
company-level view holds the unrouted queue. TanStack Query for server state, design tokens only.

---

### LP-808 — Route B and the connection flow

**Track** backend + frontend · **~4 days** · **Migration: yes**

**Build**

- `backend/app/models/mailbox_connection.py` — company-owned; `kind`, `address`, structured `status`
  (`connected | degraded | needs_reauthorization | revoked`), cursor fields for the later API route,
  `last_success_at`, `consecutive_failures`. Build it now even though forwarding needs almost none of
  it, so Route C slots in without a schema change.
- Original-hop trust evaluation: parse the `Authentication-Results` added by the sender's first
  recipient, walk `ARC-Authentication-Results` trusting only allowlisted sealers, and independently
  verify any surviving `DKIM-Signature` for alignment with `From:`. **Never** evaluate the forwarded
  message's own SPF — it always fails, by protocol.
- The guided connection UI: mint `co-{token}@`, provider-specific steps, an **"email these steps to
  my admin"** button, and `not_verified → awaiting_first_message → verified` flipping automatically
  on first arrival.
- Staleness alerting on `last_success_at`, surfaced as a persistent banner. The worst failure here is
  silent — the rule was removed, nothing errored, and documents stopped arriving.

---

### LP-809 — Draft accumulation

**Track** backend · **~2 days** · **Migration: yes**

`Communication(direction=OUTBOUND, status=DRAFT)` plus a `communication_needs_items` join. Wire
`request_documents_in_bulk` to add to the open draft. Regenerate on add and remove.

---

### LP-810 — The drafting engine

**Track** backend · **~3 days** · **Migration: yes** (the prose cache)

**Build**, following `ai/finding_prose.py` and LP-634 layer for layer:

- `app/models/email_draft_prose.py` — pure cache keyed on `sha256(facts)`, no FK, truncatable.
- `app/ai/email_draft.py` — facts dataclass → system prompt → `complete()` → guards.
- `app/services/email_draft.py` — gather, cache lookup, compose, store.
- Prompts in `app/ai/prompts/communication/` — the directory exists and is empty, reserved.
- `settings.anthropic_model_reasoning`, `temperature=0.0`, feature flag **off** by default.
- Import `leaked_identifiers_in`, `unsupported_numbers_in` and the `_RULE_ID` regex from
  `ai/finding_prose.py` rather than re-deriving them.
- **The compliance scanner in `rejection_reason()`** — deterministic, not a prompt instruction:
  numeric rates and APRs, Reg Z triggering terms, approved/denied/commitment language, dollar payment
  amounts, wire/routing/account numbers, named settlement-service recommendations. One corrective
  retry, then the plain template.
- **The model quotes `GUIDANCE`; it never invents an instruction.** Enforce it the way
  `unsupported_numbers_in` enforces numbers.

**Watch for the fact bundle.** A consolidated email is batched by construction, which is the opposite
of the prose passes' hard-won "per item, not one batched call". Scope the bundle to the requested
needs plus borrower name and file basics — **nothing else**. bug-008's lesson applies with full
force: include the document list and every upload silently rewords the draft under her cursor.

---

### LP-811 — Send, threading, and the REQUESTED transition

**Track** backend + frontend · **~2 days** · **Migration: no**

- Copy & send, plus "open in mail client" **disabled above a length threshold** — `mailto:` is
  truncated around 2 000 characters in several clients and would send half an email.
- `Reply-To` set to the file address; an opaque `[LF-xxxxxxxx]` footer tag; an offer to Bcc the file
  address so the sent copy is captured.
- **Calls `request_needs_item()`** — the function exists at `services/needs_items.py:76` and has
  **zero callers**, so `requested_at` is NULL on every row that has ever existed. This is the ticket
  that starts the reminder clock.
- The send endpoint requires `reviewed_by_user_id` and `draft_id`. **No bulk send.** Store the model
  draft, the human edit and the sent version separately.
- Auto-reply suppression headers on anything automated, plus a header-independent rate limit of one
  per address per five minutes and three per day.

---

### LP-812 … LP-816 — M5

| Ticket | Scope | Days |
|---|---|---|
| **LP-812** Timeline | Merge communications and activity log **without double-counting** — LP-805 writes both an `inbound_message` and a `Communication` for the same message, and no ticket reconciled them; decide which is the timeline's row and how it reaches the attachment manifest. Filter pills (all / sent / received / drafts / activity, per spec 4.3); inbox address displayed for forwarding instructions. **Depends on LP-811**, which §D's graph was missing. | 5 |
| **LP-818** Reply, compose, and read state | Reply to an inbound message — `In-Reply-To` set to the **inbound** `message_id`, which is the only thing that keeps a borrower's next message on rungs 1–2; compose a message with no needs behind it; mark important; unread state and a badge. All four are spec 4.3 bullets and none exists. See §C.5 for why this is a schema change, not a button. | 5 |
| **LP-814** Reminders | Celery beat over `requested_at`: pending > 3d, no reply > 5d, file untouched > 7d. Suggestion cards with snooze. **Blocked on LP-811.** Suggests only, never sends | 2 |
| **LP-820** Non-borrower requests | LP-800 sorts needs to eight parties; only the borrower has a send path, so title / employer / CPA / underwriter needs sit at PENDING forever, never get `requested_at`, and are invisible to LP-814. Per-party draft variants and their own clock. | 3 |
| **LP-821** Evidence record + legal hold | `phase4.md` §6's full field set — template + version, body as sent, attachment manifest with hashes, which guardrail fired, model + prompt version, inbound auth verdicts — **append-only, not soft-deletable**. Plus the per-file legal-hold flag, which §6 says ships *before* the purge job — and INFRA-1 builds the purge job on day one. Plus the one-page AI System Disclosure for LP-810. | 4 |
| **LP-816** Send from app | Transmit as her via a mailbox connection (`gmail.send`, *sensitive* scope only; or Graph `Mail.Send` delegated). Same gate, same guards; captures the sent copy natively | 3 |

---

## §C.5 — Tickets added by the coverage review

Each of these closes a requirement stated in the source specification or in `phase4.md` §6 that the
first draft of this plan did not cover. They are not scope creep; they are the audit's findings.

### INFRA-3 — Outbound sending identity and the bounce path

**~2 days.** INFRA-1 builds SES *receipt* only, and correctly gives `inbox.` no SPF, no DKIM and no
A record. But **nothing in the plan could send anything**, while LP-815 auto-replies to every inbound
message and LP-816 sends as her. Build the other two subdomains `phase4.md` §2.1 specifies:
`mail.mortgageboss.ai` for transactional outbound (SPF + DKIM + DMARC, `From:` alignment, SES
sending identity, and the **production sandbox exit request**, which has AWS-side lead time) and
`bounces.mortgageboss.ai` for envelope Return-Path. Start DMARC at `p=none` with `rua=`.

### LP-817 — Template library

**~3 days.** Spec 4.1 names five: *initial documentation request, reminder / follow-up, status
update, condition response request, custom*. None exists, and the omission has a sharp edge:
**LP-810's compliance scanner falls back to "the plain template" and no ticket defines it.** Since
the drafting flag ships off by default, the plain template is not the fallback — it is the default
path for every draft until the flag flips. Ship M1 without this and M1 renders nothing.

Templates are versioned, because `phase4.md` §6 requires the audit record to capture *template +
version*. The initial-request template carries the **"send your documents to this address"** line
that M3's routing depends on.

### LP-818 — Reply, compose, and read state

**~5 days.** Spec 4.3: *"Per-item actions: view full thread, reply, mark important."* None exists —
and reply is blocked by the data model, not by a missing button. LP-809 creates a draft **plus a
`communication_needs_items` join**; LP-811's send endpoint requires a `draft_id`. A reply to *"is
page 4 really needed?"* has no needs behind it, so it cannot become a draft, so it cannot be sent.

So: a needs-less draft kind, threading that sets `In-Reply-To` to the **inbound** `message_id`
(LP-805 writes `email_threads` and `references[]` and nothing has ever read them), `mark_important`,
unread state and a badge. Without the badge the queue is pull-only and an evening reply sits unseen
until she happens to open the tab.

### LP-819 — Bounces, DSNs and delivery failure

**~3 days.** The plan had zero occurrences of bounce, DSN or Return-Path. Consequences, all real:
a typo'd borrower address bounces and nobody sees it; **LP-814 keeps counting "no reply > 5 days"
against a dead mailbox and escalates forever**; and `Communication.error_detail` — a column that
already exists on the model — never gets a writer. Ingest the `bounces.` subdomain, classify on the
RFC 3463 status class (`5.x.x` hard → suppress the address and tell her; `4.x.x` soft → retry then
alert), set `is_dsn` / `is_auto_reply`, and **never** file a DSN as a borrower document.

### LP-820 — Non-borrower request paths

**~3 days.** See the M5 table. LP-800 sorts correctly to eight parties and only one can be written to.

### LP-821 — Evidence record and legal hold

**~4 days.** See the M5 table. The legal-hold flag is the urgent half: `phase4.md` §6 says ship it
*before* the purge job, and INFRA-1 builds the S3 lifecycle expiry — which **is** the purge job — on
day one of the critical path.

### LP-822 — Tone and style profile

**~2 days.** Spec 4.1: *"Tone matches sister's voice (informed by Phase 0 template review)."* This
is not merely absent — it **conflicts with LP-810's central design decision**, which scopes the fact
bundle to "the requested needs plus borrower name and file basics — nothing else", on bug-008's
lesson that a wide bundle reworded every draft on any change.

Resolve it by separating the two caches: a **style profile keyed on `user_id`**, holding her
signature block, greeting and closing conventions and two or three exemplars, cached independently
of the per-draft fact bundle so editing it invalidates style but not content. **Its input is a Phase
0 deliverable that is still outstanding** — the spec's own collection list asks for *"examples of her
current borrower-request emails (templates and actual sends)"*. Ask Priya for them in the same
session as LP-800.

Ship without this and the drafter writes in generic assistant voice, Priya rewrites every email, and
an AI drafter whose output is always rewritten is slower than a template — which is the spec's own
testing checklist item *"drafted emails sound like her voice"* failing.

---

## §D — Critical path

```
day 1  ├─ INFRA-1 ──► (prod: registrar wait) ──► INFRA-2 ──► INFRA-3 ──► (SES sandbox exit)
       ├─ LP-800 + LP-822 inputs (Priya, one session) ──┐
       └─ LP-802 ──┬─► LP-801 ─► LP-817 ─┬─► LP-809 ─► LP-810 ─► LP-811 ──────► [M1]
                   │                     └─► LP-822 ──┘                │
                   └─► LP-803 ─► LP-804 ─► LP-819 ──► [M2]             │
                                    └─► LP-805 ─► LP-806 ─► LP-807 ─► LP-813 ─► LP-815 ─► [M3]
                                                              └─► LP-808 ──────────────► [M4]
       LP-811 ─► LP-814      LP-807 + LP-811 ─► LP-812 ─► LP-818      LP-810 ─► LP-820, LP-821
```

**Four real serialisations, not two:**

1. **LP-800 gates LP-810** — a drafter with no instruction catalog writes the wrong email.
2. **LP-817 gates LP-810** — the "plain template" the compliance scanner falls back to has to exist,
   and with the drafting flag off it is the *only* path.
3. **LP-811 gates LP-814** — a reminder with no clock has nothing to fire on.
4. **INFRA-3 gates LP-815 and LP-816** — and the SES production sandbox exit has AWS-side lead time,
   so it belongs on the day-one infra track with the registrar delegation, not in M5.

Everything else has slack. LP-812 also gained an edge from LP-811 that the first graph was missing —
compose needs the send machinery.

---

## §E — Decide before M1 starts

1. **Which mail provider is the pilot customer on?** Microsoft 365 makes Route C a ~1-week Graph
   build with no CASA; Google makes it 6–12 weeks and a recurring assessment. It does not change M1
   or M2, and it changes everything about M5's LP-816.
2. **Is `Communication.body` encrypted at rest?** Inbound borrower bodies will otherwise sit in
   cleartext in Postgres. Note that `EncryptedString` is non-deterministic, so routing and dedup
   columns must stay plaintext regardless.
3. **How long is an inbound `.eml` kept**, and does the loan-file record or the raw message govern?
   This sets the S3 lifecycle rule in INFRA-1, so it is needed on day one.
4. **Is a loan-file token ever valid across `company_id`** — a broker and a processor on one file?
   The answer changes the resolver in LP-805.
5. **Are borrowers told the address is not a secure channel?** Copy decision, needed for LP-815.

---

## §F — Risks, and what each one actually costs

| Risk | Cost if it lands | Mitigation |
|---|---|---|
| Priya's catalog review slips | LP-810 slips with it; M1 stalls at 80% | Book the session in week 1. Ship party-only entries first and add instructions incrementally — the drafter degrades to the document label, it does not break |
| Production DNS delegation drags at the registrar | Production inbound slips; staging is unaffected | Start INFRA-1 day one; staging needs no registrar step at all |
| Attachment safety turns into a project | M2 doubles | Reject archives outright; rasterize rather than deep-inspect. Both were chosen for this reason |
| The drafter's fact bundle is too wide | Every upload silently reworded the draft under her cursor | Scope the bundle in LP-810 and assert on it in a test, not in review |
| Cross-tenant leak through the token resolver | Existential | Write the cross-tenant test before the resolver; the resolver is the only code allowed to derive `company_id` from an address |
| Nobody can reply to a borrower | She replies from Outlook, the thread leaves our records, and her next inbound message falls off rungs 1–2 | LP-818, and treat M3+M4 as one release |
| A bounce is invisible | The reminder engine nags forever against a dead address | LP-819, before LP-814 ships |
| The nightly shutdown pages someone daily | Alert fatigue, then a real alert ignored | H4 — gate the alarms on the shutdown schedule |
| The AI drafts something that reads as a Reg B notice | Regulatory, and it starts a clock nobody logged | The scanner is deterministic and blocks the draft — never a prompt instruction |

---

## §H — The operational track nobody tickets and everybody needs

None of this is in the spec. All of it decides whether the tickets above are buildable.

### H1 — Local development without AWS

A developer cannot run SES on a laptop, and the ingest path is where the fiddly bugs are. Build a
**dev-only raw-message injector** — a `dev.py`-style endpoint or a management command that takes an
`.eml` off disk and enqueues it exactly as the SQS consumer would. Everything downstream of
`inbound.ingest_message` is then testable offline. MailHog is already in `docker-compose.yml` for the
outbound side. **This is part of LP-803, not a follow-up** — without it LP-804 and LP-805 are written
blind and debugged in staging.

### H2 — The `.eml` fixture corpus

The parser gets exercised by shapes, not volume. Commit fixtures for: a plain reply with a PDF; a
**forwarded** message with the PDF nested in `message/rfc822`; an Outlook RTF message with a
`winmail.dat`; an encrypted PDF; a HEIC from an iPhone; an RFC 2231 filename and an RFC 2047 one; a
DSN; an out-of-office auto-reply; a `dmarc=GRAY` message; and one message that arrives twice. Each is
a named test, and together they are the acceptance criteria for LP-804 and LP-819.

### H3 — Seed data, so the frontend is not blocked

LP-807 (4 days) and LP-812 (5 days) both sit behind backend tickets. Seed a handful of
`inbound_messages` with attachments, verdicts and routing states — routed, unrouted, quarantined —
in the existing seed path, and the two frontend tickets can start in parallel with LP-805.

### H4 — Observability, and the one alarm that will lie to you

Structlog throughout, per the repo's convention — and **never log a message body or subject**;
metadata only. Metrics worth having: ingest lag (SES receipt time → row committed), routing
confidence distribution, triage queue depth and age, DLQ depth, and drafts rejected per guardrail.

**The trap is specific to this repo.** Staging scales to zero and stops RDS between 22:00 and 09:00
(LP-630). SES and S3 do not shut down, so mail still arrives all night and lands safely in the
bucket — but the SQS consumer is down, so the queue drains at 09:00. That means **ingest lag will
show an 11-hour spike every single night, by design**, and a naive alarm on queue depth or lag will
page someone daily. Set the SQS message retention well above the window (the 4-day default is fine),
and gate the alarms on the same schedule the shutdown uses. Say this in the runbook before anyone
wires a PagerDuty rule to it.

### H5 — Feature flags and how to stop it

LP-810 ships behind a flag by the prose-pass convention. **Ingestion needs one too**: a per-company
kill switch that stops routing and accepting while still capturing raw mail to S3. If the ladder
misroutes, the recovery must be "stop attaching, keep receiving", not "lose the mail".

### H6 — Cost

Rounding error, but the repo tracks cost deliberately (budget alarms, overnight shutdown) so it
should be stated rather than assumed. SES receipt is $0.10 per 1,000 messages plus $0.09 per 1,000
256 KB chunks; SES sending is $0.10 per 1,000 plus $0.12/GB of attachment data. GuardDuty S3 gives
1,000 requests and 1 GB free per month per region, which covers the pilot outright. At ~30 files a
month the whole feature is **well under $5/month**, dominated by S3 storage of the raw `.eml`
archive — which is a retention decision (§E item 3), not a throughput one.

---

## §G — Deliberately not in Phase 4

Borrower portal · auto-send · Gmail/Graph inbound (Route C) · SMS · condition parsing from
underwriter email (that is Phase 4.5) · historical mailbox backfill · read/unread and label sync ·
archive extraction · TRID six-item clock detection (flagged in `phase4.md` §6, but it belongs with
conditions, not communication).
