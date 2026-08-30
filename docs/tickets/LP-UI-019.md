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
