# Phase 4.5 — Condition Management: build plan

**Status:** draft for review · v3 · 2026-09-23
**Ticket block:** **LP-903 … LP-929** · **ADRs:** **ADR-403 … ADR-407**
**What changed from v2:** the work is regrouped into the three stages the product owner set —
**(1) get conditions in, (2) see them, (3) work them** — plus a short decisions step before
Stage 1 and a fourth "guard" stage after Stage 3. The design content from v2 (what the real sheets
taught us, the paste rules, rules-first reading, what we keep from the header) is unchanged and is
carried in §7.

---

## 0. The plan on one page

| Stage | What it delivers | Tickets | Rough size |
|---|---|---|---|
| **0 · Decisions** | Five ADRs, so the migrations are written once | LP-903 | 1 day |
| **1 · Get conditions in** | Upload the PDF, forward the email, or paste text → every condition saved with its exact wording, code, bucket and round; the rest of the letter kept | LP-904 … LP-910 | ~1.5 weeks |
| **2 · See them** | List and board per file; rounds shown; round 2 compared with round 1; condition detail | LP-911 … LP-917 | ~1 week |
| **3 · Work them** | Each condition's action items worked out; the app offers the right next step and carries it through the lifecycle to "cleared" | LP-918 … LP-925 | ~2 weeks |
| **4 · Guard** *(added)* | Expiry clocks, the cross-file Today queue, file health, learning | LP-926 … LP-929 | ~1 week, then ongoing |

**The acceptance test for every stage is the same real file:** UWM loan …4352, round 1 printed
08/28 (11 conditions) and round 2 printed 09/10 (6 conditions) — replayed as synthetic look-alikes,
never the real PDFs (ADR-405).

| Stage | Done when, on loan …4352 |
|---|---|
| 1 | Both sheets come in (one as a PDF, one as a paste) and all 17 condition rows are saved with exact wording, codes and buckets; the header and expiry dates are kept for the PDF round |
| 2 | The list and board show round 2; the comparison proposes 7086, 6132, 6637, 6178 and 0132 as *probably cleared* and she confirms them; rate and verified-asset changes are shown |
| 3 | 6637 splits into three items across two people, 6178 is recognised as not applying if closing is on or after 09/30, one borrower email covers every borrower item, and 0007 waits on 1228 |
| 4 | The lock expiring on the first allowed closing day is flagged; Today lists the file; file health names the preventable conditions |

---

## 1. Principles (unchanged)

1. **Each stage is usable on its own.** Stage 1 alone replaces retyping conditions; Stage 2 alone
   replaces the spreadsheet beside the portal.
2. **Every ticket has a "Done when" that names behaviour.**
3. **Data-authoring is its own ticket** — the condition library and lender code maps are reviewed rows.
4. **AI is never on the critical path of a stage's value.** Known formats are read by rules; AI
   adds understanding on top.
5. **Nothing is required up front.** Ask one question when it's needed, then remember it.
6. **Only the lender clears.** The app prepares and records; it never decides a condition is cleared.

---

## 2. Stage 0 — Decisions (LP-903)

Five ADRs in `decisions.md`, no code.

| ADR | Decision |
|---|---|
| **403** | A condition is its own entity. A condition is the lender's demand; a need is our ask for a document; an action is work that isn't a document. Conditions create needs (`NeedsItemOrigin.CONDITION`), never the reverse. |
| **404** | Only the lender clears. Two status tracks — our preparation, the lender's answer. A verdict records who said so and where. **Nothing closes a condition except a recorded verdict or a confirmed full-sheet comparison; a partial source never does.** |
| **405** | Condition text and sheet headers are NPI: storage encryption + TLS (16 CFR 314.4(c)(3)), dropped from the `readonly.*` staging views, identifiers kept as last four, legal hold and the two-year disposal clock apply. Decide `communications.body` the same way. Real borrower PDFs never enter the repo. |
| **406** | A condition never becomes a finding; a finding raised by a condition's document links back to it. |
| **407** | Lender condition codes are lender-scoped — always (lender, code), never a global table. AUS message codes are the only cross-lender codes. |

**Done when** all five are Accepted and LP-904's migration cites them.

---

## 3. Stage 1 — Get conditions in

**Goal:** a condition sheet, however it arrives, becomes saved conditions with the lender's exact
wording — without retyping, and without AI for the formats we know.

### LP-904 · Data model and migrations — M
- `condition_rounds`: file, lender, round number, **source** (PDF / email / pasted / typed),
  **completeness** (full / partial), **date printed**, raw-text reference, **header snapshot** (loan
  figures, contacts, dates), **lender expiry dates**, linked document.
- `conditions`: file, lender, first and latest round, **lender code**, **lender category**,
  **bucket** (Master / PTD / Compliance PTD / Underwriter to obtain / PTF / Trailing / Champions'
  "Prior to Docs – X"), **verbatim text**, **underwriter notes** (dated), identity key
  (lender, code, subject), info-only flag, two status fields (ADR-404).
- `condition_events` (append-only), `lender_condition_codes` (lender, code → canonical type,
  times seen).
- Lender fields for later: mortgagee clause, cutoff, who-handles-what.
- Company scoping, soft delete, encryption per ADR-405.

**Done when** tenancy and event-immutability tests pass. Actions and needs links come in Stage 3.

### LP-905 · Upload and forward — M
- **Upload** a PDF on the Conditions tab.
- **Forward** the lender's email to the file's inbox address: the attachment enters as
  `CORRESPONDENCE` (built in Phase 4 for this) and is offered as a condition sheet in triage.
- Text layer read first (both real formats are HTML-to-PDF text); `page_render` / `page_ocr` only
  when there is no text layer. Pages rasterized before any AI sees them.

**Done when** a PDF uploaded or forwarded produces a draft round with its page text and a timeline
entry, and nothing is saved as conditions until the processor confirms (LP-909).

### LP-906 · Reading known layouts with rules — L
- **UWM reader:** header (Senior UW, UW II, UW team, AE, closer), ~30 loan facts, buckets, rows
  (4-digit code · category · text), expiry table, mortgagee clause.
- **Champions reader:** header blocks with contacts and expiry dates, "Prior to Docs / Prior to
  Funding – Category" sections, rows (number · text).
- **Generic reader** for unknown formats: finds line breaks and numbering; hands the rest to LP-908.
- Handles the known hazards: page-break duplication, soft hyphens in headings, wrapped lines,
  leading-zero codes, one code repeated on a sheet, `Date Printed` as the round marker.

**Done when** all five real sheets (as synthetic look-alikes) read with exact wording and every row
accounted for.

### LP-907 · Paste — M
- A paste box with one question: **"Is this the full list, or just some?"**
- Headings and codes in the paste are split by the same rules; otherwise LP-908 splits it.
- Round date defaults to today and can be changed; source shows as **pasted**.
- A PDF uploaded later for a pasted round **merges into that round** instead of starting a new one.

**Done when** a partial paste can never remove a condition, and a later PDF fills in the pasted
round's header, contacts and expiry dates.

### LP-908 · AI for structure only — M
Used only when rules can't split the text (unknown format, unstructured paste): returns the list of
conditions with **verbatim text**, any code and bucket it can see, and a confidence. **It does not
interpret** — understanding is Stage 3 (LP-919).

**Done when** an unstructured paste of the …4352 round-2 conditions splits into the right six
conditions with exact wording.

### LP-909 · Review and import — M
The review screen: every parsed row beside its source, low-confidence rows first, every field
editable, one button to import. Importing creates the round and its conditions and writes events.

**Done when** the processor can fix a row and import, and nothing is saved before she does.

### LP-910 · Lender code map v1 — S (data)
Seed UWM and Champions codes from the real sheets (UWM `7086`, `1582`, `0006`, `0007`, `6378`,
`1947`, `1228`, `6132`, `6637`, `6178`, `0132`, `6174`, `1812`, `6457`, `0973`, `1760`, `0571`,
`0562` …; Champions `71`, `268`, `209`, `284`, `286` …). New codes seen on import are added as
"unmapped" for review.

**Done when** every seeded code resolves to a canonical type, and a new code on import is recorded
rather than dropped.

**Stage 1 exit:** both …4352 sheets are in — one uploaded, one pasted — with 17 rows saved exactly.

---

## 4. Stage 2 — See them

**Goal:** one place to see every condition on a file, by round, and what changed between rounds.

### LP-911 · Conditions API — M
List and filter by round, bucket, code, category, status, owner; round summaries (source,
completeness, counts); condition detail with its events.

### LP-912 · Status model and moves — M
- Our track: **To do → Waiting → Review → Ready → With underwriter**; the lender's track:
  **Open / Pending review / Cleared / Not cleared / Waived / Superseded**.
- Side flags: needs clarification, challenged, blocked, lender is doing it, information only.
- Moves write events; backward moves need a reason; **Cleared needs a recorded verdict**.
- Manual verdict entry (the portal has no feed).

**Done when** an illegal move is refused with a reason the UI can show, and every move is an event.

### LP-913 · List view — M
Replaces the placeholder tab. Dense and sortable by bucket and code — the way portals show them — with
the round selector, source label per round ("Round 2 · pasted · just some"), and bulk verdict entry.

### LP-914 · Board view — M
Six columns, rows by who we're waiting on (in Stage 2 the owner comes from the bucket, the `TC:` /
`(PA)` prefixes and the code map; Stage 3 refines it), drag with refusal messages, information-only
lines kept off the board.

### LP-915 · Rounds and comparison — L
- A round strip on the tab: each round's date, source, completeness and counts.
- **Comparing a new full round with the last:** missing → *probably cleared* (she confirms); a new
  dated underwriter note → *came back*; changed wording → *reworded* (history carried); new code →
  *new*; unchanged → *still open*.
- Header comparison: rate, ratios, verified income and assets, expiry dates; lender's verified assets
  against the file's.
- A partial paste only adds and updates.

**Done when** the …4352 pair produces exactly the five probably-cleared conditions and the six still
open, and shows the rate and verified-asset changes.

### LP-916 · Condition detail — M
The lender's words first, then code, bucket, category, underwriter notes with dates, round history,
events. Read-only reading in Stage 2; the plan and actions arrive in Stage 3.

### LP-917 · Dates on the file — S
Contract closing, scheduled signing, projected note and funding dates, with source and history; the
lender's dates from the latest round (must not close before, lock expiry, expiry table) shown on the
round card and the file rail.

**Stage 2 exit:** she opens the file and sees round 2 on the board, confirms what cleared, and never
re-reads the sheet by hand.

---

## 5. Stage 3 — Work them

**Goal:** for each condition, the app knows what it asks, who has to act and what the next step is —
and offers that step, then moves the condition along its lifecycle as things happen.

### LP-918 · Condition library v1 with action templates — M (data, domain expert)
Forty canonical types, each with: what it usually asks (items), default owner, satisfying document
types, **default actions**, guideline basis (agency or overlay), effective dates, a short playbook.

**Done when** the domain expert has signed off the top twenty and every mapped lender code resolves.

### LP-919 · AI understanding of each condition — L
One call per round, with the condition text and a short file summary (borrowers, accounts by bank
and last four, employers, earnest money, closing date, parties) — **never the loan snapshot**. Per
condition it returns:
- the **items** asked for (a compound condition becomes several)
- **who acts** for each item — borrower, title, insurance agent, HOA, employer, you, LO, or the
  lender itself
- specifics — amounts, accounts, dates, names
- information-only or real request
- what any **underwriter note** means ("not in upload" → came back)
- a plain-English one-liner and a confidence

Guardrails: a known (lender, code) wins over the AI's type; numbers are checked by code; low
confidence asks her to confirm; the lender's wording is always shown beside the reading.

**Done when**, on …4352: 6637 → three items across borrower and title; 0132 → three items across
LO, borrower and attorney; 7086's shortfall is computed by code; 1760 and 6174 are "lender is doing
it"; 6178 is flagged as not applying if closing is on or after 09/30.

### LP-920 · Action plan — M
- `condition_actions`: type, performer (you / borrower / LO / lender / third party), counterparty,
  due date, status, outcome.
- **Needs from conditions:** one need per requested document item (`origin=CONDITION`), deduped
  against existing needs.
- **Already in the file:** a matching document is offered as "point to it" instead of an ask.
- **Links between conditions:** e.g. 0007 (inspection invoice) waits on 1228 (inspection).

**Done when** importing …4352 round 1 produces the needs and actions above without a human creating
any of them, and she can edit any of them.

### LP-921 · Next-step options on every condition — M
Each card and the detail panel offer the options that fit that condition's items:

| Option | What it does |
|---|---|
| Ask the borrower | Adds the item to the borrower email (LP-922) |
| Ask a third party | Adds it to that party's email — title, insurance, HOA, employer |
| I'll do it | Upload the invoice, log the verbal VOE call, write a processor note |
| Already in the file | Point to the document and page; goes straight to Ready |
| Ask the underwriter | Drafts a question to the right person on the lender team |
| Challenge | Drafts a push-back with the guideline behind it |
| Lender is doing it | Watch only; no ask |
| Information only | Takes it off the board |

**Done when** every condition on …4352 has at least one sensible option and choosing it moves the
card.

### LP-922 · Asking people — M
- **One borrower email** for every open borrower item, predictable funding items included early.
- **One email per third party**, accumulating (Phase 4 `party_requests`); the lender's mortgagee
  clause filled into the insurance email; contacts from the letter.
- Missing contact → asked once, then remembered. Reminders from the send date. Nothing sends itself.

**Done when** round 1 of …4352 produces three drafts — borrower, attorney/title, LO — and sending
them moves the right cards to Waiting.

### LP-923 · Evidence arrives, and is checked — L
- A returned document links to its item and moves the card to **Review** on its own.
- The check: pages, account last four, dates inside the **lender's** expiry date, and whether it
  answers what was asked.
- Verification re-runs on the new document; any new finding is linked to the condition, with a
  drafted explanation request.

**Done when** a statement missing a page cannot reach Ready, and a new deposit on an uploaded
statement is flagged before submission.

### LP-924 · Package and submit — M
One file per condition named with its code, a one-line note per condition (AI draft, numbers
code-checked), a warning when prior-to-docs items are still open, the lender's cutoff countdown, and
"mark submitted" opening the next round.

### LP-925 · Lender settings — S
Mortgagee clause, upload cutoff, who handles what, and the code map (review unmapped codes). Entered
once per lender, used on every file.

**Stage 3 exit:** on …4352 she goes from round 1 to "all prior-to-docs cleared" inside the app, with
every ask drafted for her and nothing marked cleared that the lender didn't clear.

---

## 6. Stage 4 — Guard *(added)*

These don't change what a condition is; they make the whole thing trustworthy day to day.

- **LP-926 · Clocks** — the lender's expiry dates first, calculated ones only where the lender gave
  none (labelled); recompute when a date on the file moves; "if closing slipped" view; the lock
  expiring on the first allowed closing day flagged.
- **LP-927 · Today** — what needs her across files, rounds waiting for her to confirm, rounds that came
  from a paste; the dashboard attention line `services/attention.py` reserves.
- **LP-928 · File health** — conditions, preventable (from the submission snapshot's findings, read
  by code), rounds, came back, asked twice.
- **LP-929 · Learning** — outcome capture per (lender, code); suggestions shown once there is enough
  history; prediction before submission as a spike.

---

## 7. Design notes carried from v2

### 7.1 What the real sheets taught us
Four UWM letters (incl. the …4352 pair) and one Champions certificate, all real text.
- UWM: header with lender team and ~30 loan facts; buckets; rows of **code · category · text**;
  expiry table; mortgagee clause. Champions: header blocks; "Prior to Docs / Funding – Category"
  sections; rows of **number · text**.
- **Cleared conditions just disappear** — only comparing rounds tells what cleared.
- **"Not cleared" is a dated note in the text** (`**8/28 Not in Upload`).
- **Who acts is in the wording** (`TC:`, `(PA)`, "Underwriter To Obtain And Clear",
  "Account Manager to order").
- **One condition can ask for several things**; **some lines are information only**; `Master` can
  carry a restructure with a deadline.
- **The lender publishes the expiry dates**, and the header changes between rounds too.

### 7.2 Codes are not a standard
Lender codes are each lender's own template IDs (short funds is `7086` at UWM and `268` at
Champions). Line numbers mean nothing across files. Only Fannie DU message IDs and Freddie LPA codes
are shared across lenders, and lenders usually rewrite them.

### 7.3 Paste rules
Full list → compare, propose *probably cleared*, she confirms. Just some → add and update only.
Every round shows its source. Starting with a paste loses nothing: loan figures and dates are already
on the file, the mortgagee clause is a lender setting, contacts are asked when needed, expiry dates
are calculated until the letter arrives.

### 7.4 Reading: rules first, AI second
Rules give exact wording for known formats. AI splits unknown formats (Stage 1) and understands
conditions (Stage 3). A known code beats an AI guess; numbers are checked by code; AI never clears.

### 7.5 The rest of the letter
Must keep: dates and expiry table, lender team, mortgagee clause, loan figures (cross-check and
round-to-round changes). Nice: MI detail, compensation, EMD, seller concessions. Ignore: boilerplate.

### 7.6 The loan snapshot
Never sent to an AI call for conditions. Read by code in three places only: "preventable" (the
submission-time run's findings), new findings after a condition document arrives (the normal
verification run), and optionally to build the per-round file summary when the file hasn't changed
since the last run.

---

## 8. Open items

| Item | Needed by | Owner |
|---|---|---|
| A **Sun West** sheet (and more round pairs) | LP-906 for Sun West; LP-915 hardening | Domain expert |
| Which orders UWM / Champions do themselves beyond `(PA)` and "Account Manager to order" | LP-918 defaults | Domain expert |
| Processor certifications accepted? | LP-921 "I'll do it" options | Domain expert |
| Does the LO see or approve borrower emails? | LP-922 | Product |
| Which branch owns Phase 4.5 (`phase4-with-ui` or `raspberrypi-work`) | Before LP-904 | Product |
| Shadow mode: run each stage alongside her current process on 3–5 files | End of each stage | Product + domain expert |
