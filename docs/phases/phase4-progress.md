# Phase 4 progress — the state file

**Both sessions read this first and write it last.** It is the only thing that survives a session
ending, so if it is stale the loop is broken.

Statuses: `PENDING` → `IN_PROGRESS` → `AWAITING_REVIEW` → `REVIEWED`. Also `BLOCKED` (with a reason)
and `HUMAN_GATED` (Terraform written and planned; waiting on a person to apply).

Protocol: [`phase4-execution-protocol.md`](phase4-execution-protocol.md) ·
Plan: [`phase4-build-plan.md`](phase4-build-plan.md) · Design: [`phase4.md`](phase4.md)

**Branch:** `phase4-with-ui` — not `phase4`. Corrected 2026-09-06, after both LP-802 and LP-801 were
reported against `bedrock_integration_with_rules_staging` for a whole session. Verify with
`git rev-parse --abbrev-ref HEAD` rather than trusting this line or a session-start snapshot; the
tree's branch has changed under a running session at least once. One branch for the whole phase; one
commit per ticket plus one per review pass.

**Nothing is stranded, and the reflog alone would suggest otherwise.** The branch reflog says
`Created from origin/mbai-ui-improvemet-merge^0`, which reads as "cut off the UI branch, away from
bedrock". It is not: that branch had already merged bedrock at `1ca4e0f4`, so `phase4-with-ui`
contains the bedrock staging branch in full — `git log --oneline bedrock_integration_with_rules_staging
^HEAD` is empty, and the fork point is bedrock's own tip `076307f2`. The LP-640..643 work and its
migrations are here alongside the UI merge's. No commit needs moving.

Because the branch descends from the UI merge, it carries that merge's schema: `alembic heads` is
`a7c93e12f4b8`, and staging's current revision `d7e3a9b41f02` is its direct parent. A deploy from here
applies one migration.

**This worktree is shared.** `/Users/geetthaker/Geet/project/loan-processing/mbai-bedrock` has had at
least three sessions committing into it. The protocol's concurrency rule guards the branch and the
ticket; the resource actually shared is the TREE, so a checkout by one session moves files under
another mid-review with nothing on screen to say so. A worktree per session is the fix, and it is the
user's call.

---

## M1 — The email is right (no infrastructure)

| # | Ticket | Status | Build SHA | Review SHA | Notes |
|---|---|---|---|---|---|
| 1 | LP-802 ADRs, settings, `inbox_domain`, token widening | REVIEWED | see Log | see Log | ADR-094 amended by ADR-397 — the address contains the token, so exposure is a narrowing not a technicality. Review found `inbox_domain` set by nothing; now wired in both task definitions. LP-802 has no "Done when" clause in the build plan |
| 2 | LP-801 Requestable-finding filter + `docs_requested` shape + activity type | REVIEWED | see Log | see Log | Review found the bulk dedupe never matched untyped or aliased labels — two clicks made two needs items for one ask, measured. Marker unified for new writes only; pre-LP-801 rows keep a bare `True`, read them with `requested_needs_item_id` |
| 3 | LP-800 Borrower instruction catalog | REVIEWED | see Log | see Log | Priya's review still outstanding by design — 3 of 4 "Done when" clauses met, not sent back per the do-not-block note. Review found a misspelled instruction key drops in silence (guarded now) and the Form 1007/1025 pair split from `appraisal` across two parties |
| 4 | LP-817 Template library (5 templates, versioned) | REVIEWED | see Log | see Log | LP-810's "plain template" fallback lives here. No "Done when" clause (2nd after LP-802). Review rewrote three borrower-facing sentences: an automatic-filing promise LP-806's `auto_accept_inbound=false` does not keep, a claim about the borrower's own application, and a security notice offering a route out of an unasked request. ESCALATION: M1 can send an email advertising an inbox that receives nothing until M3 |
| 5 | LP-822 Tone / style profile | REVIEWED | see Log | see Log | needs Priya's real emails; ships with a neutral default. No "Done when" clause (3rd). Review: the model was invisible to alembic's target_metadata, so `--autogenerate` would have proposed DROPPING style_profiles — three more pre-existing models were in the same state and are now exported and guarded. The new readonly view had nothing that ever executed it |
| 6 | LP-809 Draft accumulation | REVIEWED | see Log | see Log | No "Done when" clause (4th). Review: a `$` in a need title ("Proof of $10,000 gift deposit") made the stored body raise on send-time substitution — `finalise_draft_body` is now the only supported way to resolve one. template_key/template_version endorsed as §6's evidence requirement, which no later M1 ticket could host. NOTE FOR LP-818: reply drafts pass through `uq_communications_open_draft` ungoverned, since NULL template keys do not collide |
| 7 | LP-810 AI drafting engine + compliance scanner | REVIEWED | see Log | see Log | flag off by default. No "Done when" clause (5th). Review: the v2 bump silently DROPPED a v1 sentence (the test only checked framing ⊆ v1); `closing costs` was refused under §1026.24(d)(1)'s citation but is not one of its four terms; the catalog's borrower-facing prose was scanned by nothing. NOTE FOR LP-814: `is_follow_up` has no writer — a reminder path that forgets to set it will silently serve initial-request prose from the shared cache entry |
| 8 | LP-811a Send, threading, `request_needs_item()` (backend) | REVIEWED | see Log | see Log | the ticket that finally stamps `requested_at`. Split from LP-811b (frontend) per §2.1. No "Done when" clause (6th). Review: the rate limit counted ALL tenants' sends and told one company that another had emailed their borrower — now scoped to the company; the existing test had pinned that behaviour rather than missed it. GAP FOR LP-821: `send_draft` overwrites `draft.body`, so for anything sent before LP-821 the composed version is gone, not merely unstored, and cannot be backfilled |
| 8b | LP-811b Send panel (frontend) | REVIEWED | see Log | see Log | last M1 ticket. Review: "Open in mail client" carried the COMPOSED body while Copy and Mark-as-sent used the processor's edit — the borrower would receive one version and the record store the other. Fixed, and the length gate now re-measures the edit. FOR LP-812: no layout seam, deliberately; the panel is a self-contained component to place. FOR A LATER TICKET: no borrower-email lookup — offer the file's borrowers as a choice rather than pre-filling one |

## M2 — Mail arrives and is safe

| # | Ticket | Status | Build SHA | Review SHA | Notes |
|---|---|---|---|---|---|
| 9 | INFRA-1 Inbound DNS + SES + S3 + SQS | REVIEWED (HUMAN_GATED) | 662b9400 | | Module written and validated; **`terraform plan` NOT run — no AWS credentials in the session**, and the S3 backend is contacted even under `-backend=false`. `inbound_mail_enabled = false`, so an apply is a no-op until a person turns it on. `aws_ses_active_receipt_rule_set` deliberately not created (account-wide switch). Two permission details corrected from AWS docs: SourceArn not `aws:Referer`, and `kms:Decrypt` alongside `GenerateDataKey*` Review: the hand-built receipt-rule ARN had nothing comparing it to the rule — a typo applies cleanly and loses mail after SES accepts it, so a `check` block now compares them. The §6 purge conflict was the 30-day NONCURRENT rule, not the 5-year one: on a versioned bucket a delete destroyed the only version in a month, and legal hold is LP-821 in M5 — noncurrent now follows the same retention. Both SES permission details verified against the source. STILL HUMAN: plan, apply, DNS delegation, rule-set activation, SES sandbox. The reviewer had AWS credentials but `terraform init` was refused by its permission layer and not worked around. |
| 10 | INFRA-2 GuardDuty malware scanning | REVIEWED (HUMAN_GATED) | c297a3df | | Written and validated; plan NOT run (same credentials blocker). Own flag, separate from `inbound_mail_enabled`, so the scan is applied and proven healthy BEFORE mail arrives. Rule matches four detail-types, not one — a degraded plan and a clean scan both look like silence. Resource schema read from the provider, not the registry page Review: the plan-health detail-types were matched EXACTLY — but the guide's own sample prints `Resource Status warning` in lowercase while its normative list capitalises it, and EventBridge matches case-sensitively, so a degraded plan could have emitted an event this rule never saw. `Resource Status Active` was also omitted, which is the recovery signal and the proof scanning ever started. Both fixed by prefix-matching that family. Both narrowings verified at the source — prefix scoping is what the IAM page asks for, and the KMS asymmetry is right. Rule is not bucket-scoped: recorded, not fixed, since both event shapes carry the bucket name at different paths. STILL HUMAN: plan, apply, both flags. |
| 11 | INFRA-3 Outbound identity + `bounces.` subdomain | REVIEWED (HUMAN_GATED) | 4c71c20b | | Written and validated; plan NOT run, **sandbox exit NOT requested** (human, and the one with AWS lead time). DKIM CNAME suffix is a VARIABLE — SES says the signing hosted zone varies by region and cell and no provider resource exposes it. DMARC p=none with relaxed alignment (no `aspf=s`, which would break it). `RejectMessage` on MX failure. **See escalation: LP-819 cannot ingest `bounces.` as mail** Review: the `bounces.*` escalation is CORRECT, and has a stronger citation than the one quoted — AWS says outright the MAIL FROM domain "shouldn't be a subdomain that you use to receive email". Two fixes: enabling the flag with an empty `dmarc_report_address` published `rua=mailto:` with nothing after it, now refused at plan time; and the DKIM suffix is settled from the published per-region table — us-east-1 uses the default, verified not assumed. RUNBOOK: with RejectMessage SES rejects ALL outbound mail for up to 72h while detecting the MX, so publish DNS before enabling. STILL HUMAN: plan, apply, DNS for `mail.`/`bounces.`, sandbox exit. |
| 12 | LP-803 Ingest skeleton + dev `.eml` injector (§H1) | AWAITING_REVIEW | see Log | | Migration d1a8f37c0e59. **`company_id` is NULLABLE**, against the plan's "company-owned" — the standing tenancy rule forbids ingest deriving it, so LP-805 fills it. Dedup index is `NULLS NOT DISTINCT`, without which the "same message twice" criterion fails in the state every message starts in. Poller written but NOT scheduled |
| 13 | LP-804 MIME parsing + attachment safety + fixture corpus (§H2) | PENDING | | | |
| 14 | LP-819 Bounces, DSNs, delivery failure | PENDING | | | must land before LP-814 |

## M3 + M4 — One release, not two

| # | Ticket | Status | Build SHA | Review SHA | Notes |
|---|---|---|---|---|---|
| 15 | LP-805 Routing ladder + participants + token resolver | PENDING | | | **write the cross-tenant test first** |
| 16 | LP-806 Triage API + accept + `correspondence` disposition | PENDING | | | |
| 17 | LP-807 Triage queue UI + seed data (§H3) | PENDING | | | |
| 18 | LP-813 Underwriter contact + per-file assignment | PENDING | | | moved earlier — LP-805 needs them as participants |
| 19 | LP-815 Secure link + borrower nudge auto-reply | PENDING | | | needs INFRA-3 |
| 20 | LP-808 Route B forwarding + guided connection flow | PENDING | | | ships **with** M3, not after it |

## M5 — The loop closes

| # | Ticket | Status | Build SHA | Review SHA | Notes |
|---|---|---|---|---|---|
| 21 | LP-812 Communication timeline | PENDING | | | reconcile `inbound_messages` vs `communications` first |
| 22 | LP-818 Reply, compose, mark important, unread | PENDING | | | schema change, not a button |
| 23 | LP-814 Reminder suggestions | PENDING | | | blocked until LP-811 and LP-819 are REVIEWED |
| 24 | LP-820 Non-borrower request paths | PENDING | | | |
| 25 | LP-821 Evidence record + legal hold + AI disclosure | PENDING | | | legal hold must precede any purge job going live |
| 26 | LP-816 Send from the app | PENDING | | | interface only — no provider implementation, per §5 |

---

## Log

Append one line per completed cycle. Newest last.

```
| date | ticket | build SHA | review SHA | findings fixed | note |
|------|--------|-----------|------------|----------------|------|
| 2026-09-06 | LP-802 | bcf00b0a | b57b085f | 5 | first Phase 4 ticket; ADR-094 amended. Fixed: inbox_domain unset in every env, a false import rationale, a tautological address test, two token-length assertions the widening could not fail |
| 2026-09-06 | LP-801 | 392b1469 | d3325a9b | 3 | duplicate borrower request from an untyped label; the marker's other shape and its reader |
| 2026-09-06 | LP-800 | 6d71cb9d | 9d1cad77 | 2 | silent drop of a mistyped instruction key; the appraiser-prepared family split across two parties |
| 2026-09-06 | LP-817 | 228b4c19 | 7fd7f924 | 3 | three sentences a borrower reads; templates are the one path LP-810's scanner never sees |
| 2026-09-06 | LP-822 | bb203058 | 626547b2 | 4 | unregistered models autogenerate would drop (4 total, 3 pre-existing); an untested readonly view; a duplicate index; a comment contradicting the migration |
| 2026-09-07 | LP-809 | c3d34471 | e238e6c7 | 1 | a dollar amount in a need title broke the send-time substitution; one predicted finding disproved by measuring it |
| 2026-09-07 | LP-810 | ab89cddd | f721148e | 3 | a sentence lost in the first real version bump; a house rule citing a regulation that does not require it; catalog prose past every guard |
| 2026-09-07 | LP-811a | 748ace96 | d222da0f | 1 | a cross-tenant rate limit that leaked one company's contact with a borrower to another, asserted as correct by the existing test |
| 2026-09-07 | LP-811b | 710ed72b | b55b6110 | 1 | the mail-client link sent the composed body while the record stored the edit — M1 complete |
| 2026-09-07 | INFRA-1 | 662b9400 | 7656cefc | 2 | HUMAN_GATED. Review found the ARN-consequence backwards (fail-open, not closed) and that `noncurrent_version_expiration` was the real §6 conflict — a deleted message destroyed in 30 days, not 5 years |
| 2026-09-07 | INFRA-2 | c297a3df | 48244319 | 1 | exact-matched event types the guide spells two ways, and a missing health event; one predicted finding checked and dropped. Plan still not run — human |
| 2026-09-07 | LP-803 | 4024f921 |  |  | awaiting review. Migration d1a8f37c0e59; nullable company_id against the plan; NULLS NOT DISTINCT dedup; §H1 injector |
| 2026-09-07 | INFRA-3 | 4c71c20b | 9cd54199 | 2 | a malformed DMARC record one flag-flip away, now fail-closed; the DKIM suffix sourced from the published table; the bounces escalation verified and strengthened |
| 2026-09-07 | LP-811b | 710ed72b |  |  | awaiting review. Frontend only. The navigation question answered itself — the Communication tab placeholder has existed since LP-33. **M1 complete pending this review** |
| 2026-09-07 | LP-811a | 748ace96 |  |  | awaiting review. Split from LP-811; LP-811b (frontend) is row 8b. First write to `requested_at` in the system's life |
| 2026-09-06 | LP-809 | c3d34471 |  |  | awaiting review. Migration b8d5e0a17c42; two provenance columns the plan did not ask for; LP-818 will need the draft uniqueness index revisited |
| 2026-09-07 | LP-800a | f3f0e06c | 228ddc61 | 1 | sourcing pass, user-directed. Fannie Mae citations inline; no assignment wrong; found the party recorded twice with the wrong copy winning; review found one stale section number |
| 2026-09-07 | LP-810 | ab89cddd |  |  | awaiting review. Migration c9f1a4b73e08; template v2; Reg Z §1026.24 read 2026-09-07 |
| 2026-09-06 | LP-822 | bb203058 |  |  | awaiting review. Mechanism + neutral default; migration e4a1c7d90b3f. No "Done when" clause in the plan (3rd) |
| 2026-09-06 | LP-817 | 228b4c19 |  |  | awaiting review. ADR-401 (version pinned by content hash). No "Done when" clause in the plan |
| 2026-09-06 | LP-800 | 6d71cb9d |  |  | awaiting review. ADR-400. 166 types carry a party, 28 carry full instructions; Priya's pass outstanding and not blocking |
| 2026-09-06 | LP-801 | 392b1469 |  |  | awaiting review. ADR-399: predicate over the consolidated rule id, no migration — the plan's preferred column would be True on exactly one row per file |
```

## Blocked / escalations

Anything a session could not resolve. One line each, with the ticket it belongs to.

| Item | What it is, and what it needs |
|---|---|
| **LP-817 / M1 sequencing** | M1 can send an email advertising an inbox that receives nothing until M3. LP-811 (send) is inside M1; LP-803 (ingest) and LP-805 (routing) are inside M2, and nothing sequences them. Raised by the LP-817 review. **Needs a person to decide** before M1 ships: hold the send behind M2, drop the address line from the initial-request template until M3 (it would need a version bump, ADR-401), or ship knowing a borrower can email documents into a void. |
| **LP-800 / LP-817 domain review** | NARROWED 2026-09-07. The assignments the Fannie Mae Selling Guide governs are now sourced and cited inline (B4-1.1-03, B3-4.2-01, B3-3.1-02, B3-3.1-04, B3-4.3-04, B3-4.3-09), with tests named after the rules; none was wrong. What remains for Priya is the unsourced majority — disclosures, identity, LOEs, inspections — plus the five templates' wording, which no source settles. Still not blocking, but it should reach her before Phase 4 mails a real borrower. |
| **LP-820 / the party vocabulary has no depository or servicer** | Surfaced by the sourcing pass. `verification_of_deposit`, `verification_of_assets`, `verification_of_mortgage` and `verification_of_rent` are forms sent OUT to a bank, servicer or landlord — the same shape as `voe`, which can name its third party because `EMPLOYER` exists. Recorded as PROCESSOR, which is right about "not a borrower ask" and wrong about "no outbound request at all". LP-820 needs a party for each or it will read them as having nowhere to go. |
| **INFRA-1 / the purge job ships before the legal hold** | INFRA-1's S3 lifecycle expiry IS the purge job `phase4.md` §6 says must not precede the legal-hold flag — and that flag is LP-821, in M5. Written with retention as a stated variable and flagged rather than silently created. **A person must decide**: hold the lifecycle rule until LP-821, or accept a window in which nothing can suppress expiry. |
| **LP-819 / bounces cannot be ingested as mail** | LP-819's text says "ingest the `bounces.` subdomain". Not possible: a custom MAIL FROM domain must carry **exactly one** MX, pointing at SES's feedback endpoint, so bounces never arrive as mail we can read — they arrive as SES events. INFRA-3 therefore builds an SES configuration set with an SNS destination for reject/bounce/complaint/delivery, and LP-819 reads that topic. **The plan's wording needs correcting** before somebody writes LP-819 against the wrong shape. |
| **INFRA-3 / DMARC reports need a real mailbox** | `dmarc_report_address` is empty and `outbound_mail_enabled` is false. `rua=` names an address somebody has to actually read; choosing one would create a report nobody receives. A person sets both together. **Now enforced rather than trusted (review):** `outbound_mail_enabled = true` with an empty address fails at plan time, so the two can no longer be turned on apart. The decision — which mailbox — is still a person's. |
| **INFRA-1 / `terraform plan` needs credentials** | The protocol wants the plan output committed. This session has no AWS credentials and the S3 state backend is reached even under `-backend=false`. The config is validated offline (`docs/tickets/infra-1/validate.txt`); the plan is outstanding and needs either a person to run it or `aws login` in this session. |
| **LP-810 / no prompt-version in the audit record** | `phase4.md` §6 wants "model + prompt version" stored beside a sent message. The drafting prompt is a file with no version discipline of its own, and LP-810 has no send path to store one against. Not built rather than half-built; LP-811 is where it lands or is dropped on purpose. |
| **Build plan: four tickets with no "Done when"** | LP-802, LP-817, LP-822 and LP-809. Both were judged against the section prose, by different sessions reaching the same call. The plan should carry the clause rather than each reviewer re-deriving it. |
