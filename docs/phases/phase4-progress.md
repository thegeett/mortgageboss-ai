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
| 4 | LP-817 Template library (5 templates, versioned) | AWAITING_REVIEW | see Log | | ADR-401: version pinned by content hash, so wording cannot change without a bump. "The plain template" is defined as this module, not a sixth file. `render_document_block` refuses any type the borrower does not hold. **No "Done when" clause in the build plan**, like LP-802 |
| 5 | LP-822 Tone / style profile | PENDING | | | needs Priya's real emails; ship the mechanism with a neutral default profile and fill it in later |
| 6 | LP-809 Draft accumulation | PENDING | | | |
| 7 | LP-810 AI drafting engine + compliance scanner | PENDING | | | flag off by default |
| 8 | LP-811 Send, threading, `request_needs_item()` | PENDING | | | the ticket that finally stamps `requested_at` |

## M2 — Mail arrives and is safe

| # | Ticket | Status | Build SHA | Review SHA | Notes |
|---|---|---|---|---|---|
| 9 | INFRA-1 Inbound DNS + SES + S3 + SQS | PENDING | | | **HUMAN_GATED on apply.** Start the Terraform on day one — prod delegation has registrar lead time |
| 10 | INFRA-2 GuardDuty malware scanning | PENDING | | | HUMAN_GATED on apply |
| 11 | INFRA-3 Outbound identity + `bounces.` subdomain | PENDING | | | HUMAN_GATED. **SES production sandbox exit has AWS lead time — request it early** |
| 12 | LP-803 Ingest skeleton + dev `.eml` injector (§H1) | PENDING | | | add `tasks/inbound.py` to `_TASK_MODULES` |
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
| 2026-09-06 | LP-817 | 228b4c19 |  |  | awaiting review. ADR-401 (version pinned by content hash). No "Done when" clause in the plan |
| 2026-09-06 | LP-800 | 6d71cb9d |  |  | awaiting review. ADR-400. 166 types carry a party, 28 carry full instructions; Priya's pass outstanding and not blocking |
| 2026-09-06 | LP-801 | 392b1469 |  |  | awaiting review. ADR-399: predicate over the consolidated rule id, no migration — the plan's preferred column would be True on exactly one row per file |
```

## Blocked / escalations

Anything a session could not resolve. One line each, with the ticket it belongs to.

_(none yet)_
