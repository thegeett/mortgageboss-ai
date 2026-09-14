# Phase 4.5 — Condition Management: build plan

**Status:** draft for review · 2026-09-14
**Ticket block:** **LP-900 … LP-923**. Phase 4 ran LP-800 … LP-859; LP-860 … LP-899 are left
unallocated as headroom for Phase 4 follow-ups, so a Phase 4.5 number never collides with a
communication fix.
**Inputs:** `docs/research/` — the condition research (lifecycle, processor actions, a ~110-type
taxonomy, tooling landscape, practitioner practice) · the twelve screen mockups · `phase4.md`,
`phase4-build-plan.md`.

---

## 0. How the work is sliced

Four rules decide what is one ticket and what is two.

1. **Each milestone leaves the product usable.** M1 alone replaces the spreadsheet a processor keeps
   beside the lender portal. Nothing in a later milestone is required to make an earlier one worth
   opening.
2. **A ticket is a vertical slice with a "Done when" clause**, and the clause names behaviour, not
   files. Four Phase 4 tickets shipped without one and the close-out had to re-derive it.
3. **Data-authoring is its own ticket.** The condition library and the playbooks are rows reviewed by
   the domain expert, not literals inside a service. Two tickets here (LP-901, LP-921) produce no
   endpoint at all.
4. **AI is never on the critical path of a milestone's value.** LP-903 lets a processor type a whole
   sheet in by hand; LP-906 only makes that faster. If the parser is wrong on a lender's format, the
   feature still works.

**What is deliberately NOT in Phase 4.5** — portal integration or scraping (no public API exists at
either lender), auto-send of any kind, auto-clearing, a borrower portal, the full 110-type library
(40 ships, the rest follow demand), cross-file learned ranking (M5, gated on data), and condition
prediction before submission (a spike of its own).

---

## 1. Milestones

| # | Milestone | Tickets | What it buys | Rough size |
|---|---|---|---|---|
| **M0** | Decisions | LP-900 | The three calls every later ticket assumes | 1 day |
| **M1** | Capture | LP-901 … LP-904 | A file holds conditions; entered by hand; dates drive clocks | ~1 week |
| **M2** | Intake | LP-905 … LP-907 | The sheet reads itself; round 2 diffs against round 1 | ~1 week |
| **M3** | Work | LP-908 … LP-914 | The board, the plan, one borrower ask, third parties | ~1.5 weeks |
| **M4** | Guard | LP-915 … LP-919 | Nothing bounces, nothing expires, nothing is missed across files | ~1 week |
| **M5** | Learn | LP-920 … LP-923 | Metrics, playbooks, then ranking and prediction | after pilot data |

Two workstreams run in parallel from M1: backend owns LP-902/905/906/908/912/915-918, frontend owns
LP-903/909/910/911/914 against the contracts those tickets publish. The critical path is
**LP-902 → LP-908 → LP-912 → LP-915 → LP-917**.

---

## 2. M0 — the decisions (LP-900)

**LP-900 · Three ADRs before any migration.** No code.

1. **A condition is its own entity, not a `needs_item`.** A condition has a lender, a round, a
   verdict and a verbatim text that a need does not; a need has an arrival lifecycle a condition does
   not. Conditions *create* needs (`NeedsItemOrigin.CONDITION` has been reserved since LP-68).
2. **Only the lender clears.** Our side has a prep track; the lender's verdict is mirrored. "Waived"
   is recorded, never chosen by us; the processor's equivalent is *waiver requested*.
3. **Raw condition text is NPI.** It quotes balances, account fragments and employer names. Stored
   with the encrypted column types, excluded from the `readonly.*` staging views, and covered by the
   existing legal-hold flag.

**Done when** the three ADRs are in `decisions.md` and LP-902's migration references them.

---

## 3. M1 — Capture

### LP-901 · Condition library v1 (data, domain-expert reviewed) — M
Forty canonical types drawn from the taxonomy, as effective-dated rows: `id`, category, default
`prior_to`, default responsible party, guideline citation + **authority tier** (agency / overlay /
unknown, the LP-501 shape), the document types that satisfy it, and a one-paragraph playbook. An
unmapped fallback type exists and is not an error state.
**Done when** every row resolves to a `documents/catalog.py` type or is explicitly action-only, a
sync test pins that, and the domain expert has signed off the top twenty.

### LP-902 · Data model and migrations — M
`conditions`, `condition_events` (append-only), `uw_rounds`, `condition_actions`,
`condition_documents` (m2m), plus a cutoff/turn-time config on `lenders`. Company scoping, soft
delete, encrypted raw text, and the identity key (`canonical_type_id` + `subject_key`) that lets
round 2 match round 1.
**Done when** tenancy isolation and event-immutability tests pass. No API.

### LP-903 · Manual conditions, and the tab stops being a placeholder — M
Create / edit / list / delete, with prior-to, owner, category, note. Replaces `TabPlaceholder` with
the list view (screen 4 without bulk actions).
**Done when** a processor can type a real UWM sheet in by hand, see it on the tab, and it survives a
reload. This is the first ticket that is useful on its own.

### LP-904 · The dates that drive everything — S
`contract_closing_date`, `scheduled_signing_date`, `projected_note_date`,
`projected_disbursement_date`, each with source and history, on the file header and context rail.
**Done when** changing one writes history, emits an activity entry, and publishes the recompute hook
LP-918 will consume.

---

## 4. M2 — Intake

### LP-905 · Getting the sheet in — M
Three doors: upload, paste, and forward to the file's inbox address. The attachment enters as
`CORRESPONDENCE` (Phase 4 built that disposition for this), pages are rasterized and OCR'd by the
existing `page_render` / `page_ocr` services, and a `uw_round` record is created. No AI.
**Done when** a PDF emailed to `lf-…@in.…` produces a round with page text and a timeline entry, and
the raster path is the only path (it is also what neutralises an active PDF).

### LP-906 · Reading it (AI) and the parse-review screen — L
Per condition: verbatim text, summary, entities (amount, date, account last four, borrower),
canonical type, prior-to, owner, confidence. Screen 2: low-confidence rows surfaced, unmapped rows
importable anyway, every field overridable.
**Done when**, on ten real sheets from both lenders, every line becomes a condition, the verbatim
text is exact, and no line is silently dropped. Accuracy of the *derived* fields is measured and
reported, not gated — an override is one click.
**Blocked by** real sheets from the domain expert. This is the only hard external dependency in the
plan.

### LP-907 · Round two, compared with round one — M
Diff the new sheet against the open set: cleared, not cleared (carrying the underwriter's comment),
still open, new, reworded → superseded with history inherited. Per-condition manual verdict for what
only appeared in the portal.
**Done when** importing round 2 of a real file produces the right five buckets and writes one event
per change, and nothing on the board moves until the diff is applied.

---

## 5. M3 — Work

### LP-908 · The state machine — M
Internal track `NEW → TRIAGED → IN_PROGRESS → EVIDENCE_IN → READY → IN_PACKAGE → SUBMITTED` with side
states `NEEDS_CLARIFICATION`, `CHALLENGED`, `ALREADY_SATISFIED`, `BLOCKED`, `EXPIRED`, `WATCH_ONLY`;
lender track `OPEN → PENDING_REVIEW → CLEARED | NOT_CLEARED | WAIVED | SUPERSEDED`. Guards: no READY
without linked evidence or an in-file pointer; no CLEARED without a recorded verdict; every backward
move carries a reason.
**Done when** an illegal transition is refused with a typed error the UI can render, and every legal
one appends an event.

### LP-909 · The board — M (frontend)
Six columns, swimlanes by waiting-on / prior-to / none, drag with optimistic update and rollback on
refusal, filters, counts, cutoff countdown, "submit package" entry point.
**Done when** a drag persists through the API, a refused drag snaps back with the reason, and the
board is keyboard-operable.

### LP-910 · List view and bulk actions — S (frontend)
Same rows, dense, sortable, multi-select → one borrower ask, one bulk verdict, one package.

### LP-911 · Condition detail — M (frontend)
Verbatim above derived, entities, rule basis with authority tier, evidence with expiry, action plan,
event history, ask/challenge entry points.
**Done when** the underwriter's exact words are always reachable in one click from any card.

### LP-912 · Conditions become needs — M
Create or attach a `NeedsItem` with `origin=CONDITION`; detect already-satisfied against documents in
the file; dedupe against existing needs. Arrival through `apply_document_to_needs` under the existing
per-file lock moves the condition to `EVIDENCE_IN`.
**Done when** a borrower upload moves its condition without a human touch, and a condition satisfied
by a document already in the file can be marked with a page pointer instead of an ask.

### LP-913 · Actions that are not document requests — M
`condition_actions` for the verbal VOE, the AUS re-run, a processor certification, a challenge, a
third-party order — each with performer, counterparty, due date and outcome. Third-party actions feed
LP-820's accumulating per-party draft.
**Done when** a title ask created from a condition appears on that party's existing draft rather than
starting a second email, and a logged VVOE call records where the phone number came from.

### LP-914 · One borrower ask, from many conditions — M
Every open borrower condition in one draft through the Phase 4 drafting engine and style profile,
with the predictable prior-to-funding items included early, an upload link per condition, and
reminders keyed on `requested_at`.
**Done when** five conditions produce one draft, each returned file lands on the condition it
answers, and the pre-send scanner runs on it unchanged.

---

## 6. M4 — Guard

### LP-915 · The check that stops a bounce — M
Per document linked to a condition: page completeness, identifiers, signature and date, age measured
at the **projected note or disbursement date**, and whether it answers the literal ask (compared
against the condition's entities).
**Done when** a statement missing page 3 of 6 cannot reach READY, and the reason is the sentence the
processor would have written.

### LP-916 · Creep radar — M
After each condition document is extracted, re-run verification and link any new finding to the
condition that brought the document in; propose the pre-emptive explanation.
**Done when** a new large deposit on an uploaded statement produces a linked finding and a suggested
action *before* the package is submitted.

### LP-917 · Package and submit — M
Per-condition upload kit (file naming, note to paste), completeness gate, lender cutoff countdown,
"mark submitted" opening a round and stamping every condition in it, downloadable bundle.
**Done when** marking a package submitted creates the `uw_round`, stamps the conditions, and the
board shows the turn-time clock the lender will actually use.

### LP-918 · Clocks — L
`expires_at` per piece of evidence from the program rule (Fannie four months to the note date, FHA
120 days to disbursement, VVOE ten business days, appraisal update after four months), recomputed
whenever a date on the file changes; a daily pass that warns and reopens; the "if closing slipped"
simulator.
**Done when** moving the projected note date reopens what lapses, and every expiry shows its
arithmetic and the rule behind it.

### LP-919 · Attention and the Today queue — M
The condition line `services/attention.py` has a TODO for ("2 lender conditions past due"), plus the
cross-file queue split into *what you owe* and *what you are waiting on*, including the quiet state.
**Done when** the dashboard line is derived from real conditions in one aggregate query per section.

---

## 7. M5 — Learn (after the pilot has files)

- **LP-920 · Outcome capture and file health** — counts, not a score: conditions at first approval,
  rounds, first-upload clear rate, re-requests, days approval→CTC; "preventable" suggested from the
  submission snapshot and confirmed by the processor.
- **LP-921 · Playbooks** (data-authoring round two) surfaced on the condition detail.
- **LP-922 · Learned suggestions**, gated on a minimum number of resolved conditions per
  (lender, canonical type) — below it, the playbook shows instead.
- **LP-923 · Pre-submission prediction** — the differentiator, and a spike before it is a ticket.

---

## 8. Dependencies, risks and open calls

| Item | Why it matters | Owner |
|---|---|---|
| **Real condition sheets (5–10, both lenders)** | LP-906 cannot be measured without them; every "typical wording" in the library is otherwise a guess | Domain expert — **blocking M2** |
| **Which orders the lender already does** (title, HOI, payoff, condo docs, VOE, case number) | Decides the default `performer` on half the library's action types | Domain expert — needed by LP-901 |
| **Does the LO see or approve borrower asks?** | Changes LP-914's send path | Product call |
| **Processor certifications: accepted by UWM / Sun West, and for what?** | Decides whether A4 actions are real | Domain expert |
| **Shadow mode** | Running alongside her current process on 3–5 files is how trust is earned; needs a per-file flag and nothing else | LP-903 |
| **Library drift** | Agency rules moved four times in 2026 alone; the library is effective-dated from day one rather than retrofitted | LP-901 |
| **Lock contention** | A sheet import and an inbound document can land together; both take the per-file needs lock | LP-902 / LP-912 |

---

## 9. Definition of done for the phase

A processor takes a real UWM file from conditional approval to clear-to-close inside the product:
the sheet arrives by email and parses, the board shows who she is waiting on, one email covers every
borrower item, third parties are asked from the file's own address book, nothing reaches the package
that would bounce, the clocks warn her before anything expires, round two diffs itself, and the file
health screen tells her which of the conditions she could have prevented — with no list kept
anywhere else.
