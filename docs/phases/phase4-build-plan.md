# Phase 4 build plan — what to build, in what order, and how

- **Companion:** [`phase4.md`](phase4.md) is the design (architecture, data model, decisions).
  This document is the execution plan. Ticket scope lives here; the *why* lives there.
- **Figures:** [`phase4-mail-flows.md`](phase4-mail-flows.md) — the eight flows this plan builds.
- **Series:** LP-800 … LP-816. Last Phase 3 ticket was LP-647.
- **Date:** 2026-09-07.

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

### M1 — The email is right (≈ 12–14 days, **zero infrastructure**)

`LP-800 · LP-801 · LP-802 · LP-809 · LP-810 · LP-811`

> Priya clicks "Request docs" on four findings. She gets one email that asks the borrower only for
> what the borrower can actually produce, tells them exactly how to get each document, and does not
> contain a rate or the word "approved". She copies it, sends it from Outlook, and every need on the
> file moves to REQUESTED with a timestamp.

**This is the whole outbound half and it needs no DNS, no SES, no S3, no mailbox.** It is the highest
value per unit of risk in Phase 4. Build it first, and be willing to ship only this.

### M2 — Mail arrives and is safe (≈ 10–12 days)

`INFRA-1 · INFRA-2 · LP-803 · LP-804`

> Forward an email with a PDF to `lf-<token>@inbox.staging.mortgageboss.ai`. Within seconds there is
> a row in `inbound_messages` with the SPF/DKIM/DMARC/virus verdicts, the raw `.eml` in S3 under a
> CMK, and a rasterized, sanitised derivative of the attachment. Nothing is attached to a loan file
> yet — deliberately.

### M3 — Mail lands on a file (≈ 10 days)

`LP-805 · LP-806 · LP-807`

> The borrower replies with three PDFs. Priya opens the Communication tab, sees a card with the
> sender, a green auth badge, thumbnails and a suggested document type, clicks **Accept**, and the
> documents enter the existing classify → extract → needs pipeline. The needs flip to Received.

**End of M3 the feature is real.** M4 and M5 make it fit her actual workflow.

### M4 — She keeps her own address (≈ 4–5 days)

`LP-808`

> An admin adds one routing rule at Herco. Mail sent to `processing@herco.com` now also appears in
> the triage queue, correctly attributed, with trust evaluated from the original hop.

### M5 — The loop closes (≈ 13 days)

`LP-812 · LP-813 · LP-814 · LP-815 · LP-816`

> Timeline, reminders, underwriter contact, secure links, and send-from-app.

**Total ≈ 50–55 working days ≈ 10–11 weeks at full time.** The unified build plan budgets 2–3 weeks
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
  `routing_state`, `routing_signal`, `routing_confidence`; `raw_storage_path`.
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
| **LP-812** Timeline | Merge communications and activity log; filter pills; compose with template selector; inbox address displayed for forwarding instructions | 3 |
| **LP-813** Underwriter contact | Lender write endpoints — **there is currently no create or update path for lenders at all** — and per-file underwriter assignment, which exists nowhere today | 2 |
| **LP-814** Reminders | Celery beat over `requested_at`: pending > 3d, no reply > 5d, file untouched > 7d. Suggestion cards with snooze. **Blocked on LP-811.** Suggests only, never sends | 2 |
| **LP-815** Secure link + nudge | Tokenised expiring upload link; auto-reply steering borrowers to it; outbound NPI attachments blocked in code | 3 |
| **LP-816** Send from app | Transmit as her via a mailbox connection (`gmail.send`, *sensitive* scope only; or Graph `Mail.Send` delegated). Same gate, same guards; captures the sent copy natively | 3 |

---

## §D — Critical path

```
day 1  ├─ INFRA-1 ──────────────► (prod: registrar wait) ──► INFRA-2
       ├─ LP-800 (Priya) ──┐
       └─ LP-802 ──┬───────┴─► LP-801 ─► LP-809 ─► LP-810 ─► LP-811 ─► [M1]
                   └─► LP-803 ─► LP-804 ─► LP-805 ─► LP-806 ─► LP-807 ─► [M3]
                                                        └─► LP-808 ─► [M4]
LP-811 ─► LP-814                     LP-807 ─► LP-812
```

**The two real serialisations:** LP-800 gates LP-810 (a drafter with no instruction catalog writes
the wrong email), and LP-811 gates LP-814 (a reminder with no clock has nothing to fire on).
Everything else has slack.

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
| The AI drafts something that reads as a Reg B notice | Regulatory, and it starts a clock nobody logged | The scanner is deterministic and blocks the draft — never a prompt instruction |

---

## §G — Deliberately not in Phase 4

Borrower portal · auto-send · Gmail/Graph inbound (Route C) · SMS · condition parsing from
underwriter email (that is Phase 4.5) · historical mailbox backfill · read/unread and label sync ·
archive extraction · TRID six-item clock detection (flagged in `phase4.md` §6, but it belongs with
conditions, not communication).
