# Phase 4.5 staging trial — gaps and bugs (2026-09-30)

A processor walked one file (**LF-DH8V**, staging) through Stage 3: import a condition sheet, read it,
confirm the plan, draft emails, mark them sent, and try to clear a condition. The loop works end to end.
This file records every gap and bug found, with the evidence, the root cause in code, a proposed fix and
what "done" means. It is a brief for building tickets; it is not itself a ticket.

**Read first:** `CLAUDE.md` (conventions, ticket files, ADRs, CI), `docs/phases/phase4.5-stage3-plan.md`
(the Stage 3 spec), `docs/querying-staging.md` (read-only SQL against staging).

## Context

- Staging runs commit `0f482eeb` (checked with `./scripts/deploy staging status`).
- LF-DH8V has 6 conditions from one sheet: `0006` credit report invoice, `0007` final inspection invoice,
  `1228` final inspection, `1582` third-party processing invoice, `1947` title: final seller CD, `6378`
  title: loan number on checks. The sheet is a **UWM** letter (its mortgagee clause reads "United
  Wholesale Mortgage ISAOA…"). It is a test PDF whose borrower (GURUNG) is not the file's borrower; that
  mismatch is expected and is not one of the bugs below.
- Round 1 was imported 2026-09-26, before LP-919 (reading) existed. Round 2 (same PDF) was imported
  2026-09-30 to trigger the reading; plan confirmed; both drafts (Title/attorney, Lender) marked sent.
- Staging state, measured 2026-09-30 with `./scripts/deploy staging query`:

  | code | canonical_type_id | owner_hint (source) | prep_status | waiting_on |
  |---|---|---|---|---|
  | 0006 | — | processor (code_map) | waiting | processor |
  | 0007 | — | processor (code_map) | to_do | — |
  | 1228 | — | unknown (code_map) | with_underwriter | — |
  | 1582 | — | processor (code_map) | to_do | — |
  | 1947 | — | title (code_map) | waiting | title |
  | 6378 | — | title (prefix) | waiting | title |

  `0006`'s waiting-on-processor and `1228`'s with_underwriter were set by hand (condition_prep_moved
  events with an actor, after the email's own move).

## Summary

| # | Item | Kind | Priority |
|---|---|---|---|
| 1 | File with no lender → no library types → every condition read as a generic item | Root-cause gap | High |
| 2 | Generic items print a placeholder ("what the lender's words describe") into emails | Bug | High |
| 3 | The email TO the lender uses the third-party template ("the lender needs the following") | Bug | High |
| 4 | Nothing on screen while conditions are being read; the plan does not appear by itself | Gap | Medium |
| 5 | No way to read conditions that missed the reading (imported before a release, or reading failed) | Gap | Medium |
| 6 | An arriving invoice links by type only — a processing invoice satisfies the credit invoice | Bug | Medium |
| 7 | No manual link / unlink / upload of a document on a condition item (the spec asked for it) | Gap | Medium |
| 8 | "I'll do it" tasks have no actions (no upload, no "ask someone for it") | Gap | Medium |
| 9 | Condition drawer and row: unclear what to do next; clearing is buried | UX | Medium |
| 10 | Small: "Waiting on Processor" offered; 0007 does not show it waits on 1228 | Small | Low |
| 11 | Optional: warn when the sheet's borrower / loan number does not match the file | Optional | Low |
| 12 | Read-only staging views are stale (reading and plan columns missing) | Tooling | Low |
| 13 | To verify: 1228's reading summary drops "possibly a Change of Circumstance" | Observation | — |

Suggested order: **1 → 2 → 3**, then 4 + 5 together, then 6, 7 + 8 together, 9, the rest.

---

## 1. File with no lender → no library types → every condition is generic

**What the processor sees.** The plan reads every condition as a loose item. Emails say nothing useful
(item 2), no document is ever found "already in the file", nothing waits on anything (item 10b), and
the lender email has no address.

**Evidence.** LF-DH8V has no lender (`loan_files.lender_id` null; `condition_rounds.lender_id` null).
All six conditions have `canonical_type_id` null (table above). UWM's code list would have typed every
one: `backend/app/conditions/lender_codes/uwm.yaml` maps `0006`→IV-01, `1228`→PA-03, `1582`→IV-02,
`1947`→TI-03, `6378`→TI-04, `0007`→IV-03.

**Root cause.**
- A condition's library type is set **only at import, only from the lender's code map**:
  `_apply_code_defaults` in `backend/app/services/condition_import.py:507`.
- The round's lender is a snapshot of the file's lender at round creation:
  `backend/app/services/condition_rounds.py:203` and `:322`. Setting the file's lender later does not
  type existing conditions.
- The reading never picks a type: by design "the AI proposes items only for a condition no library type
  covers" (`backend/app/services/condition_reading.py`, module docstring, order of authority). With no
  type, every item is `_generic_item` (`condition_reading.py:190`): `documents: []`, no checks, the
  placeholder acceptable text.
- Consequences, each traced: generic items have `documents: []`, so `_find_document`
  (`condition_plan.py:215`) and arrival linking (`condition_evidence.py:509`) can never match anything;
  `waits_on_type` needs both conditions typed (`condition_plan.py:531`); `_lender_address`
  (`condition_drafts.py:678`) needs `loan_file.lender_id`.
- The lender CAN be set by hand today: Overview → loan editor (`frontend/components/file/overview/loan-editor.tsx`).
  Nothing tells the processor that conditions depend on it.

**Proposed fix.**
1. At sheet import, if the file has no lender, **detect the lender from the sheet** (header / mortgagee
   clause, matched against `lenders` by name or `canonical_lender_key`) and **ask** the processor to
   confirm it ("This looks like a United Wholesale Mortgage sheet — set it as this file's lender?").
   Never set it silently.
2. When a file's lender is set or changed, **re-apply the code map** to that file's conditions whose
   `canonical_type_id` is null (and the round's `lender_id`), then re-read the ones that are still
   unplanned. Conditions already read and planned are left alone, matching "conditions already read are
   left alone" in `read_round`.
3. Show a warning on the Conditions tab while the file has no lender: "No lender on this file — conditions
   can't be matched to the library. Set the lender."

**Done when.** On a file with no lender, importing a UWM sheet offers UWM; accepting it gives all six
LF-DH8V codes their UWM types; setting the lender after import types the untyped conditions and the plan
updates. Tests: lender detected and offered; nothing set without confirmation; late lender assignment
types only untyped conditions and never re-types a read/confirmed one.

**Open question.** Should an AI-suggested library type (processor confirms) cover sheets from lenders
with no code map at all? That would change the "library beats the AI" order and needs an ADR.

---

## 2. Generic items print a placeholder into emails

**What the processor sees.** The Title email reads:
"1. **Final Seller Closing Disclosure** — what the lender's words describe. 2. **Lender loan number on
checks** — what the lender's words describe." The title company is never told what to do (for `6378`,
to put loan number 1226474352 on every check).

**Root cause.** `_generic_item` sets `acceptable: "What the lender's words describe"`
(`backend/app/services/condition_reading.py:194`). `_plain_line` (`backend/app/services/condition_drafts.py:284`)
renders every item without a library `email` template as "**{name}** — {acceptable}." So an internal
placeholder reaches an outside party.

**Proposed fix.** For a generic item (no library type, or a library item with no `email`), the email
line uses the **lender's own words** for that condition (`condition.verbatim_text`, trimmed), or the
reading's summary when the verbatim text is unusable. Never emit the placeholder in any outbound text.
Keep the existing privacy rule: last four only, and the existing test that bodies carry no nine-digit run.

**Done when.** A test renders a party email from generic items and asserts the lender's words are there
and the placeholder string is not. A guard test fails if the placeholder string reaches any rendered
email body (borrower, party, lender, question).

---

## 3. The email to the lender uses the third-party template

**What the processor sees.** "Email to the lender · round 2", sent TO the lender, says: "For GURUNG ·
Lender loan 1226474352 …, **the lender needs the following**: 1. Final inspection — …". Subject: "…
items for closing". It asks the lender for something the lender itself required.

**Root cause.** Every non-borrower recipient, including `DraftRecipient.LENDER` (LP-942), goes through
`render_party` (`backend/app/services/condition_drafts.py:497`, dispatched in the `else` branch at
`:1077`).

**Proposed fix.** A `render_lender` for `DraftRecipient.LENDER`. It **asks the lender to act**: "Please
order the final inspection (1004D) for loan 1226474352" for appraiser items routed through the lender
(`APPRAISAL_VIA_LENDER`, `condition_plan.py:1096`), and "Please provide …" for the lender's own items.
Subject names the request ("1226474352 — final inspection request"), not "items for closing".

**Done when.** Tests: a lender draft never contains "the lender needs"; an appraiser item routed to the
lender renders as an order request; the borrower and party templates are unchanged (snapshot).

---

## 4. Nothing on screen while conditions are being read

**What the processor sees.** After **Import**, no spinner and no message. The plan only appears after a
refresh or navigation.

**Root cause.**
- `RoundPlanPanel` returns null while `data.planned === 0` (`frontend/components/file/conditions/round-plan-panel.tsx:55`).
- `useRoundPlan` has no `refetchInterval` (`frontend/lib/api/conditions.ts:602`). The polling that exists
  (`isWorthPolling`, `conditions.ts:129`) is for parsing the PDF, which finished before Import.
- The server exposes no reading state. `RoundPlanPublic` (`backend/app/schemas/condition.py:1009`) has
  `planned` and `ready_at`; `condition_rounds.reading_run` is written only when the reading ends. "Being
  read", "never queued" (LF-DH8V round 1) and "failed" all look the same.

**Proposed fix.** Expose a reading state on the round or the plan payload: `queued | reading | done |
failed`, plus the count of unread conditions. The panel shows "Reading 6 conditions…" and polls until
`done` / `failed`. On `failed`, show what failed and a **Read again** button (item 5).

**Done when.** After Import the panel shows the reading state without a refresh and turns into the plan by
itself; a failed reading shows its failure and a retry. Frontend tests for each state; a backend test
that the state is right for queued, done and failed rounds.

---

## 5. No way to read conditions that missed the reading

**What the processor sees.** On LF-DH8V round 1, every condition said "Not read yet. The app reads each
condition shortly after the sheet is imported." It never would be. The only workaround was re-uploading
the same PDF as a second round.

**Root cause.** The reading is enqueued in exactly one place, at import
(`_enqueue_reading`, `backend/app/api/conditions.py:217`, called at `:980`). The task's own docstring
says that when retries are exhausted "the conditions stay `unread` … and the next import on the file
reads them" (`backend/app/tasks/conditions.py:580`). `read_round` already reads every unread condition
on the file (`condition_reading.py:511`), and `build_plan` plans the whole file.

**Proposed fix.** `POST /condition-rounds/{round_id}/read`: enqueues `read_condition_round` for the
file's newest imported round; refuses (409, with a sentence) when nothing is unread or a reading is
already running. A **Read conditions** button wherever unread conditions show "Not read yet", and as the
retry in item 4. Whether production needs a one-off backfill depends on whether any round was imported
before LP-919 shipped there; check before deploying.

**Done when.** An imported round with unread conditions can be read from the UI; a second click while
reading is refused; reading twice never re-reads a read or confirmed condition. Tenant-scoped like every
other round route.

---

## 6. An arriving invoice links by type only

**What goes wrong.** IV-01 (credit report invoice) and IV-02 (third-party processing invoice) both ask
for `service_invoice`. At plan time the match also requires a library word in the document's name
(`match_words: ["credit"]` / `["processing"]`). When a document **arrives later**, linking checks only
the type, so the processing invoice is linked to the credit-invoice item too and can mark it done.

**Root cause.** `_find_document` applies `match_words` (`backend/app/services/condition_plan.py:215`).
`_takes` does not (`backend/app/services/condition_evidence.py:509`). The library item is reachable from
the item: `condition.canonical_type_id` → library type → item by `item.key` (as `condition_plan.py:1265`
does).

**Proposed fix.** Apply the same match words in `_takes`. One helper used by both paths, so they cannot
drift again.

**Done when.** Tests, both directions: a processing invoice does NOT satisfy the credit-invoice item; a
credit invoice DOES (so the test is not green because nothing links). IV-03 (inspection
invoice, `match_words: ["inspection", "appraisal"]`) also takes `service_invoice`, so all three invoice
types cross-link today; test each pair. Note: `document_name` is AI-written prose, so word matching is a weak
signal; item 7's manual link is the processor's correction.

---

## 7. No manual link / unlink / upload on a condition item

**What the processor sees.** No way to say "this document answers this item", to remove a wrong
automatic link, or to upload straight from the condition. Choosing **Already in the file** by hand only
changes the label and the plan's count; it links nothing.

**Root cause.** The Stage 3 spec defines "Already in the file | Links the document and page"
(`docs/phases/phase4.5-stage3-plan.md`, LP-921's option table). Built: automatic linking only.
`ConditionItem` has `document_id` and `document_page`, but `ConditionItemUpdate`
(`backend/app/schemas/condition.py:972`) accepts only option, name, performers, due date and status.

**Proposed fix.** On an item:
- **Link**: choose a document of this file (and optionally a page; more than one document per condition
  is allowed, as in Encompass's eFolder). Marks the item done and records who linked it.
- **Change / unlink**: replace or remove a link, automatic or manual.
- **Upload here**: upload from the item; the document goes through normal processing and is linked to
  this item on arrival rather than by matching.
- **The processor's choice wins**: arrival linking (`condition_evidence.py`) never overrides or re-adds a
  link she made or removed. Same principle the owner field already follows (`OwnerHintSource`, manual
  outranks inference).
- **Checks still run and stay visible**: linking a credit report to an invoice item is allowed, but the
  item shows "linked document is a credit report; this item asks for an invoice". Only a recorded lender
  verdict makes a condition Cleared (unchanged).
- Each action writes a condition event (history), tenant-scoped, refuses another file's document (404).

**Done when.** Link, change, unlink and upload-here all work from the drawer; a later automatic match
does not undo a manual unlink; a mismatched manual link shows its warning; events appear in History.

---

## 8. "I'll do it" tasks have no actions

**What the processor sees.** `0006` says "Your task · credit report invoice" with nothing to act on.
Even "I'll do it" work means getting a document from someone.

**Root cause.** Drafts exist only for ask options (`_ASKS`, `condition_plan.py:77`) and only for
recipients in `_RECIPIENT` (`condition_plan.py:1080`). The processor has no recipient, and there is no
credit-vendor recipient.

**Proposed fix.** On an "I'll do it" item: **Upload** (item 7) and **Ask someone for it**, which turns the
item into an ask with a chosen recipient (LO, or other party) and adds it to that recipient's open draft.

**Open questions for the domain expert (answer before building a credit-vendor recipient):**
1. With UWM, when credit is pulled **in EASE** (UWM pays upfront and recoups it on the CD — HousingWire,
   2024-03-13), is there still an invoice to provide, and where does it come from?
2. When the broker's own vendor pulled it, does the processor download the invoice from the vendor
   portal, or get it from the LO?
3. Do lenders accept a billing page inside the credit report PDF as the invoice?

Background: the credit report fee is a zero-tolerance fee under TRID, which is why the lender wants the
actual invoice.

---

## 9. Condition drawer and row: unclear what to do next

**What the processor sees.** "When I click on a condition the drawer is so confusing. Not sure what we
need to do to clear it." The list row has no action; the Lender column ("Open") is not clickable.

**Current drawer order** (`frontend/components/file/conditions/condition-detail-sheet.tsx`): Lender's
words → Evidence → Reading box ("Not read yet" when unread) → Our status → Owner → Lender (holds
**Record lender's answer**) → Underwriter notes → Rounds → History. The only action that ends the job is
the fourth block. The component comment at `condition-detail-sheet.tsx:174` ("NO ACTION BUTTONS FOR
STAGE 3 WORK") predates Stage 3 shipping and is stale.

**Proposed fix.**
- A **"Next:" line** at the top of the drawer, from the same logic as the Next step column
  (`frontend/lib/conditions/next-step.ts`): "Next: get the credit report invoice — Upload / Ask someone".
- The two tracks shown as one sequence: our work (get → check → send to lender) then the lender's answer
  (Record lender's answer).
- **Record lender's answer** reachable from the row (e.g. clicking the Lender status), not only via a
  checkbox + bulk bar.
- Status, rounds and history below, as reference.

Design work: mock the drawer for three cases (an ask waiting on Title, an "I'll do it" task, a condition
sent to the lender) before building. Follow the colour/radius rules in `CLAUDE.md`.

---

## 10. Small items

**a. "Waiting on Processor" is offered.** Waiting on yourself is not a state. The waiting-on choices
include `processor` (`condition-detail-sheet.tsx:65`, `conditions-bulk-bar.tsx:41`). Remove it from the
**waiting-on** pickers only; it remains valid as an owner/performer (`confirm-reading-dialog.tsx:34`,
`conditions-filter-row.tsx:60` are performer/owner lists, check each before changing).

**b. 0007 does not show it waits on 1228.** The library has the link (IV-03 `waits_on_type: PA-03`), and
the UI renders "Waits on …" (`reading-box.tsx:210`, `round-plan-panel.tsx:293`). It was not set because
neither condition had a type (`condition_plan.py:531`). Fixed by item 1; add a test once types exist.

---

## 11. Optional: sheet / file mismatch warning

The import accepted a sheet whose borrower (GURUNG, read by `condition_drafts.py:208` from the title line)
is not the file's borrower. A **warning, not a block** at import ("This sheet says GURUNG, this file is
Patel — continue?") would catch a wrong PDF uploaded to a real file while still allowing test PDFs. Same
for the lender loan number when the file has one.

---

## 12. Read-only staging views are stale

`CLAUDE.md` says to answer staging questions by querying. During this trial these were missing from the
`readonly.*` views: `conditions.reading_status`, `reading_source`, `reading_confidence`;
`condition_rounds.plan_ready_at`, `plan_confirmed_at`, `reading_run`. `condition_items` and
`condition_drafts` are excluded whole (by design, LP-922), so item-level questions (links, waits_on) cannot
be answered on staging. The conditions views were last defined in the LP-915 migration
(`backend/alembic/versions/20260927_1200_a7c31e6d94b2_lp915_round_comparison.py`).

**Proposed fix.** A migration adding the non-NPI columns above, and a readonly view of `condition_items`
with only non-NPI columns (ids, key, option, status, performer, document_id, waits_on_condition_id,
draft_id; NOT name, acceptable or specifics). Extend `backend/tests/test_readonly_query.py`. Document in
`docs/querying-staging.md`.

---

## 13. To verify: 1228's reading drops a clause

The lender's text: "Final inspection is required (and possibly a Change of Circumstance) to confirm…".
The reading's summary: "Final inspection required to confirm construction completion per plans and specs".
A change of circumstance means the LO/lender may have to re-disclose; dropping it hides work. Verify on
the item (the reading confidence was 0.75, the lowest of the six) and decide whether the reading prompt
must keep conditional clauses. Not a confirmed bug yet.

---

## Working rules for whoever builds this

- One ticket file per item in `docs/tickets/LP-XXX.md` (next free number after LP-948); ADRs in
  `decisions.md` where a principle changes (item 1's open question, item 7's "manual wins").
- CI must stay green: ruff, mypy, pytest; biome, tsc, vitest (`CI=true TZ=UTC pnpm test`), build.
- One pytest at a time on the shared test DB.
- Every new test needs a positive control: a "does not link" test is paired with a "does link" test.
- Do not commit or push without the owner's approval.
