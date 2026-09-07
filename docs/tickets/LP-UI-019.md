# LP-UI-019 — Documents: list, upload, freshness

- **Ticket:** LP-UI-019
- **Epic:** Ledger redesign → Epic C (Core screens)
- **Status:** Completed
- **Date:** 2026-08-30
- **Depends on:** LP-UI-007 (the dense table), LP-UI-009 (the context rail)
- **ADR:** none. No new architecture; this is presentation over data that already exists.

## Summary

Documents were cards. A card gives a verified W-2 and a pay stub with four fields
to check the same weight and the same height, and eighteen of them is a page you
scroll rather than a list you scan. They are now table rows grouped by category,
so the period and the status line up in columns and the outliers are the ones
that break the column.

Three things moved, and each move is the point of the ticket:

**Processing goes above the list.** A document that is classifying has no type, no
period and no size worth reading, and it changed every few seconds — so it held a
row that moved the nine settled documents underneath it. In-flight documents now
sit in a `ProcessingStrip` above the table and join the list when they settle.
That adds a row; it does not reorder the ones already there.

**Freshness and duplicates go to the context rail.** Both were per-row cues you
noticed one document at a time — a badge on a stale row, "1 other pay stub" under
two different names, which is the same fact told twice. In the rail each is one
answer for the whole file. On `LF-XKQ3` that reads: three documents past their
window, named with the backend's own reasons, and four types held twice.

**Coverage is the backend's judgement, labelled.** `package_qualification` checks
four criteria server-side in priority order — current, fresh, typed, extracted —
and reports the *first* one each document failed. The rail labels that reason. It
does not re-derive it, and the hint under it ("current, fresh, typed and
extracted") was checked against `app/documents/staleness.py` rather than copied
from the mockup.

## What changed

- `components/file/documents/processing-strip.tsx` (new).
- `components/file/documents/document-list.tsx` — cards to category-grouped
  tables. The export and every call site are unchanged.
- `components/layout/file-context-rail.tsx` — the one "Documents" block becomes
  Coverage, Freshness and Duplicates.
- `lib/loan-files/documents.ts` — `documentCoverage()` and
  `QUALIFICATION_REASON_LABEL`, beside the other document display logic rather
  than in a new file.
- `components/file/documents/document-dropzone.tsx` — see below.
- `app/(protected)/loan-files/[id]/documents/page.tsx` — renders the strip.

## Two fixes outside the brief

**The dropzone was 290px tall.** Stacked icon, label, hint and button at `py-10`,
so the first screen of the Documents tab was the invitation to add a document
rather than the documents. It is now a single row: seven documents are visible
where two were. Dropping still targets the whole area.

**`table-fixed`, and it was a real bug.** The shared `Table` has no fixed layout,
so percentage column widths are only hints. A `truncate` cell sets `nowrap`, and
under auto layout that *widens* its column rather than ellipsing — so the
brokerage statement's summary pushed the Assets table off screen and under the
context rail, with its own columns no longer aligned to the group above it.
Scoped to the two tables that declare percentage widths rather than to the shared
component: fixed layout needs every width declared and the pipeline grid does not
declare all ten.

That fix also lands in `reconciliation-ledger.tsx`, which is LP-UI-018's file. It
is the same latent bug — a long enough snippet would have done the same thing
there — and leaving a known layout bug in place because it belongs to a ticket
that has already shipped is not a reason.

## Tests

Five for the strip, three added to the list, seven for the rail — 653 frontend
tests pass, tsc and biome clean. No backend changes.

Eleven mutations verified to fail, read as counts rather than exit codes: in-flight
documents back in the table, the row ignoring the keyboard, coverage counting
superseded versions, a resolved staleness still chased, duplicates without the
type grouping, the strip rendering when nothing is in flight, the strip showing
settled documents, and the missing filename fallback.

**Three tests changed rather than added, each because a signal moved:**

- *"gently surfaces other current documents of the same type"* now asserts the row
  does **not** repeat that cue. The property moved to the rail's Duplicates block
  and is pinned there. Asserting where it is no longer, rather than deleting it,
  keeps the move visible.
- *"shows the Documents section only on the documents tab"* follows the rename to
  Coverage / Freshness / Duplicates. Same property, three names.
- The strip's filename-fallback test asserted `standard_name: null`. The type says
  `string`, so the real case is the **empty** name — tsc caught that the test was
  pinning a state that cannot occur.

## Verified against the running app

- `?doc=<id>` opens the right drawer (`Mortgage-Statement_FAY-SERVICING-LLC` on
  `LF-XKQ3`) — the deep link LP-114 added still works through the rewrite.
- Polling is untouched: it lives in `useLoanFileDocuments` and its four existing
  tests still pass, including the stuck-document backstop.
- Light and dark.

**The strip itself was verified by test, not by screenshot.** No seed file has a
document mid-flight, and uploading one to produce a screenshot would leave a stray
document on a seed file. Worth stating plainly rather than implying the whole
screen was seen working.

## Noted, not changed

- The mockup's Freshness and Duplicates blocks carry action buttons ("Request
  refreshed copies", "Review versions"). Neither action exists; a button that
  looks like it does something is worse than its absence, so they are left out.
- The mockup's document table has no line for a Tier 2 summary (LP-65). It is kept
  as a quiet second line — dropping a shipped signal to match a drawing is not a
  reason.
- The rail's Verification block reports `red_count` / `yellow_count` /
  `green_count`, which `lib/types/verification.ts` says are the **legacy sweep's**
  counts, while the Verification screen shows governed outcomes. One rail
  reporting two vocabularies is LP-UI-020's problem, and it is real today.

## Review pass — the strip promised rows the table would never show

Reviewed on request from the session running the epic. One defect, three
judgement calls confirmed, and the deferral upheld.

### "Processing — N of M" counted documents the table cannot hold

`DocumentList` shows `is_current && isTerminalStatus`. `documentCoverage`
counts `is_current`. The processing strip and the rail's "Still processing"
metric each filtered on `!isTerminalStatus` **alone**.

So a SUPERSEDED document mid-flight was counted as arriving and listed in the
strip — and could never appear in the table beneath it when it settled, because
it is not current. The strip is a promise that these rows are on their way to the
list; a row that is not makes the count irreconcilable with what the reader can
see.

The denominator had the same fault from the other end: `documents.length`
counted every version ever uploaded, so "3 of 18" described no set on the screen.

One definition now — `inFlightDocuments()` beside `documentCoverage()` in
`lib/loan-files/documents.ts` — used by both the strip and the rail. This is the
LP-UI-013 lesson: three readers of one list had two answers, and the two that
disagreed were the two that count things a processor reconciles by eye.

The rail's count had no test at all, so the mutation passed until one was added.

### The three changed tests, judged

All three are honest. Taking them in turn, because the hand-off asked:

- **The duplicate cue.** The strongest of the three. The property was not
  deleted, it moved, and it is asserted in BOTH places — absent from the row,
  present in the rail (`file-context-rail.test.tsx:192`). Asserting where a
  signal is no longer, with the positive pinned where it now is, is the right
  shape for a move.

  One correction applied: the "no longer repeats" assertion was a bare
  `toBeNull`, which passes just as well when the list renders nothing at all —
  the same shape as the hand-off's own mutation harness finding no tests. A
  positive control now sits beside it.

- **The rail tab rename.** Following a rename from one "Documents" block to
  Coverage / Freshness / Duplicates is not changing a test to match code; it is
  the test continuing to describe the thing it always described.

- **The strip's fallback.** `standard_name: null` against a type that says
  `string` was a test pinning a state that cannot occur, and `tsc` catching it is
  the type system doing its job. Correcting it to the empty name tests the case
  that can actually happen. Worth noting the general form: a test that only
  compiles because the fixture lies is not testing the code.

### Confirmed, not changed

- **`table-fixed` on the two tables rather than the primitive.** Right, and for
  the reason given: fixed layout requires every column width declared, and the
  pipeline grid declares only some. Putting it on the shared `Table` would fix
  two tables and silently reflow a third. Touching LP-UI-018's file to fix the
  identical latent bug there was also right — a bug found in one place and left
  in its twin is a bug you have decided to ship.
- **The two mockup items left alone.** "Request refreshed copies" and "Review
  versions" have no action behind them, and dropping the Tier 2 summary line to
  match a drawing would remove a shipped signal. Both correctly reasoned.
- **The strip is tested but never watched.** Declining to upload a stray
  document onto seed data to get a screenshot is the right call. Recording that
  it is the one part of the screen not seen working is what makes the gap
  honest rather than invisible.

### The deferral is upheld — with a condition

The rail's Verification block reports `red_count` / `yellow_count` /
`green_count`, which `lib/types/verification.ts:31` documents as the **legacy
sweep's** counts, while the Verification screen shows governed outcomes. One rail
reporting two vocabularies, live today.

Deferring is correct here, and the distinction from LP-UI-016's mobile-navigation
call is worth stating: that regression was introduced by the ticket under review
that night, so it was undone rather than scheduled. This one is pre-existing (it
shipped with LP-UI-009), this commit does not touch that block — checked, the
diff contains no change to it — and LP-UI-020 owns the Verification surface.

The condition: it is a processor seeing different numbers for the same file on
two screens, which is the disagreement class this epic has now produced five
times. LP-UI-020 should not close without it.

### Verification

`tsc` and `biome` clean over 233 files, **657 tests** (from 653), build compiles.
No backend changes. Both halves of the fix mutation-checked:

| mutation | result |
| --- | --- |
| strip drops the `is_current` check | 2 tests fail |
| rail counts processing without `is_current` | 1 test fails |
