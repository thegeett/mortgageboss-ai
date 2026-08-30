# LP-UI-013 — Pipeline: table and attention column

- **Ticket:** LP-UI-013 — the worklist, re-cut as a pipeline
- **Epic:** Ledger redesign → Epic C (Core screens)
- **Status:** Completed
- **Date:** 2026-08-30
- **Mockup:** Pipeline

## Summary

`StatsCards` is gone and an **Attention** column replaces it. The dashboard now
answers the question a processor opens it to ask — *which of these needs me, and
why* — instead of showing four numbers you cannot click.

Measured on the dashboard: **3 API requests** where there were 7. Rows at
**28px**. Every row carries an attention string, a left stripe encoding it
without colour alone, and a needs-progress bar.

## The decision the ticket asked for: server-side

The ticket says *"The attention string is derived, so decide where: an
`attention` field on `LoanFileSummary` is cleaner than five client-side queries.
Raise it on the ticket."*

**Server-side, and not marginally.** The string reads four domains — findings,
documents, staleness, needs. Deriving it in the browser means those queries *per
row*: forty files × four is not a dashboard, it is an outage. The new
`app/services/attention.py` does it in **four queries for a page of any size**,
one aggregate per domain, never one per file.

## What Changed

**Backend**

- `app/services/attention.py` (new) — `AttentionTone`, `FileAttention`,
  `attention_for_files()`. The tones are deliberately the frontend's four, not a
  fifth vocabulary invented for this screen.
- `LoanFileSummary.attention`, built by a new `list_item()` classmethod.
- `GET /loan-files` derives once for the page.

**Frontend**

- `components/dashboard/attention-cell.tsx` (new) — the cell, the stripe map and
  the needs bar.
- `file-table.tsx` — columns are now File, Borrower, Property, **Amount**,
  Stage, **Attention**, **Needs**, Lender, Touched.
- `lib/loan-files/attention.ts` (new) — `byAttention()`, the default sort.
- `components/dashboard/stats-cards.tsx` — **deleted**.

## Verification

**Requests, counted over CDP.** Before: 7 (`/loan-files` ×4 at `pageSize: 1`
for the stat cards, plus the real list, preferences and refresh). After: **3** —
`/loan-files`, `/users/me/preferences`, `/auth/refresh`.

**Attention strings on real data**, sorted with blocking first:

| file | attention | needs | stripe |
|---|---|---|---|
| LF-96SV | 10 findings block submission | 1 / 18 | `rgb(178,58,42)` destructive |
| LF-6T3N | 2 findings block submission | 7 / 26 | `rgb(178,58,42)` |
| LF-2BMX | Pay stub is 334 days old | 0 / 18 | `rgb(143,93,8)` warning |
| LF-HWKM | No documents yet | 0 / 3 | neutral |

**Rows are 28px**, nine of nine at a single height.

**CI.** Frontend biome, tsc, 583 tests, build. Backend ruff, mypy, and the
**full 5,932-test suite**: 5,930 pass, 2 fail — the two pre-existing
`test_model_selection_lp457` failures caused by this machine's `.env`, which the
LP-UI-010 review already identified as environmental.

## Two defects I introduced and caught

Both are worth recording because they fail *silently*, which is this epic's
recurring shape.

1. **The stripe class was assembled by interpolation and therefore never
   existed.** I wrote `` `[&>*:first-child]:${ATTENTION_STRIPE[tone]}` ``.
   Tailwind scans source text for *complete* class names, so a computed one is
   never emitted — the stripe rendered as the default border colour and nothing
   failed. This is LP-UI-002's undefined `danger` in a new costume. The map now
   holds full literal class strings.

2. **`TableRow` was colouring all four borders.** With the stripe class finally
   emitted, it *still* rendered `--border`: `[&>*]:border-border` sets
   `border-color` on every side, which beats a cell's `border-l-<colour>`. A row
   that draws one hairline should only colour that hairline — it is
   `[&>*]:border-b-border` now. This affects every table, not just this screen.

Measured after both fixes: `rgb(178,58,42)` on blocking rows, `rgb(143,93,8)` on
attention rows.

## Findings raised

1. **The sort is client-side, over one page.** `byAttention()` orders the rows
   the server returned. With more files than a page, a blocking file on page 2
   stays on page 2 — the dashboard's default order is only true within a page.
   Sorting server-side needs the derivation to be expressible in SQL, and it is
   not: it is assembled in Python from four sources, one of which (staleness) is
   computed per document rather than stored. Fixing it properly means either a
   materialised attention column maintained on write, or accepting that the sort
   is a page-local convenience. A real decision, not a detail.

2. **Two of the mockup's attention strings are not implemented, deliberately.**
   "2 lender conditions past due" needs underwriting conditions, which are Phase
   4.5. "Reserves fall short by 1.1 mo" and "Appraisal below contract price" are
   calculator-derived and would need a calculator run per file — the exact
   per-row cost this design exists to avoid. Both are absent rather than faked.

3. **Staleness cannot be a SQL aggregate.** `evaluate_staleness` is computed
   from document type windows and an extracted date. It is derived here over the
   documents already loaded for the failed-extraction check, so it costs no
   extra query — but it does mean the attention derivation loads every current
   document for the page. For a 20-file page that is fine; at `pageSize: 100`
   it is worth re-measuring.

## Assumptions and decisions

- **Decided** `LoanFileSummary.list_item()` rather than widening `from_model`.
  `LoanFileDetail` subclasses the summary, so widening would break its override
  *and* give the detail screen an `attention` field it always reports as null.
- **Decided** the attention field is optional. A version-skewed client renders
  "—" rather than claiming a file is calm.
- **Decided** the ordering of causes: blocking findings, then failed extraction,
  then staleness, then no-documents, then outstanding needs, then clear. Ordered
  by what stops the file moving, not by abstract severity.
- **Assumed** "Nothing outstanding" is the right calm state. The mockup says
  "Clear at Balanced", which names the aggression level — that is available per
  file but reads as verification jargon on a list, and the level is a *user*
  default that a reader of someone else's row would misread.

## Files

- backend: `app/services/attention.py` (new), `app/schemas/loan_file.py`,
  `app/api/loan_files.py`
- frontend: `components/dashboard/attention-cell.tsx` (new),
  `lib/loan-files/attention.ts` (new), `file-table.tsx` (+ test),
  `app/(protected)/dashboard/page.tsx`, `components/ui/table.tsx`,
  `lib/types/loan-file.ts`; `stats-cards.tsx` deleted

## Review pass — a dashboard that disagreed with the screen it links to

Reviewed on request from the session running the epic. Five defects. The
hand-off's own suspicion about the finding filter was right, and worse than it
feared.

### "N findings block submission" was not the app's definition of blocking

`app/services/finding_blocking.py` already owns what blocks submission:
resolution OPEN, severity red or yellow, and **confidence at or above the cutoff
in force**. The attention service invented its own pair —
`evaluation_outcome == OPEN and resolution_status == OPEN` — and that is wrong in
BOTH directions:

- **Overcounts.** It ignores confidence entirely, so it counts the
  low-confidence hunches the aggression dial exists to exclude. A file whose
  verification screen says it is clear reads on the dashboard as blocked.
- **Undercounts.** `evaluation_outcome` is set by the rule engine
  (`rule_findings.py:53` maps `Verdict.FIRED → (OPEN, RED)`). An AI cross-source
  finding carries a severity and **no** rule outcome, so a genuinely blocking
  file read as clear.

Now mirrors the canonical predicate. The cutoff is per file — its override, else
the user's default (LP-79) — so `attention_for_files` takes the `user`, resolves
each file's cutoff with `active_cutoff`, and compares in Python over one query's
worth of candidate findings. Still one query; the page-wide property the ticket
was built around is intact.

This is the failure the hand-off named as worse than either count being wrong
alone, and it is: a processor looking at two numbers for the same thing cannot
tell which to believe.

### The needs count disagreed with the needs screen for the same reason

`total - satisfied` put `received` in the waiting set. The file's own needs list
does not: `NEEDS_GROUP` in `frontend/lib/loan-files/needs.ts` maps `received` to
`in_review`, because the document ARRIVED and what is outstanding is the reading
of it. A file with 3 pending and 2 received said "Waiting on 5 documents" on the
dashboard and 3 on the file screen.

Aligned to `needs_action` = {pending, requested, rejected}. That leaves a state
the old arithmetic accidentally covered — all needs received, none verified —
which would now fall through to "Nothing outstanding" while a processor still has
reading to do. So `received` gets its own line, "N documents to review", rather
than being folded into either neighbour. The progress chip is unchanged:
satisfied stays {verified, waived}, which is what "done" means.

### A new file with a full needs list read as calm

`if not documents: "No documents yet"` sat above the needs check, so a file
opened this morning with eight needs and no documents returned NEUTRAL "No
documents yet" — the least useful sentence available, in the calmest tone, on
what is arguably the most actionable row on the page. The needs lines now come
first; "No documents yet" is the honest answer only when nothing is being waited
on.

### `_oldest_stale` loaded every extraction ever made

`selectinload(Document.extractions)` pulls all versions, for every current
document, for every file on the page — and `_oldest_stale` then discards all but
`is_current`. Prior versions are kept for audit and are unbounded in principle,
so this was page-size × version-count rows to answer a question about one of
them. Now `selectinload(Document.extractions.and_(Extraction.is_current))`, which
the partial unique index bounds to at most one per document.

### `attention.tone as Tone` would have gone on compiling

Raised in the hand-off, and correctly diagnosed as LP-UI-005's shape. A cast
compiles while `AttentionTone` happens to be a subset and keeps compiling the day
it stops being one — a fifth backend tone would reach `StatusToken`, miss
`GLYPH[tone]`, and render a row with no glyph at all. Replaced with an explicit
`Record<AttentionTone, Tone>`, which is a compile error on the day the enum grows.

### The tests

Both gaps the hand-off named, filled:

- `backend/tests/services/test_attention.py` — 17 tests across three groups: the
  blocking count AGREES with `finding_blocking`'s definition (cutoff respected,
  per-file override beats the user default, AI findings counted, green and
  resolved never block); the needs counts agree with `NEEDS_GROUP`; and the
  decision ladder, which is the real behaviour — what outranks what.
- `frontend/lib/loan-files/attention.test.ts` — `byAttention`'s ordering, the
  unknown-payload file sorting LAST rather than first, and that it does not
  reorder the query cache's array.
- The stripe is asserted **on the rendered row** in `file-table.test.tsx`, per
  LP-UI-011's lesson, including that the emitted class contains no `$` or `{` —
  which is what the interpolation defect looks like in the DOM.

### Confirmed, not changed

- **The `TableRow` border change is safe across every table.** `[&>*]:border-border`
  → `[&>*]:border-b-border` only matters to a cell that draws a non-bottom
  border. Checked: no `TableCell` or `TableHead` anywhere sets a bare
  `border-l/r/t`, and `TableHead` names its own `border-b border-border`. Every
  bare `border-t` in the tree is outside a table (page footers, calculator
  sections, dialogs) where the selector does not reach. The pipeline was not the
  only table that needed looking at, but it was the only one affected.
- **The colcount assertion moved 7 → 9 → 10.** Flagged in the hand-off as the
  "changed a test to match the code" move. It is fine, by the same test as
  LP-UI-011's: the load-bearing property — every cell carries `aria-colindex` and
  the count matches the header — still holds, and a column count that does not
  track the columns is not an assertion about anything.
- **Client-side `byAttention` over one page.** Left as raised. Sorting
  server-side needs the derivation to be sortable in SQL, and it is assembled in
  Python from three sources; the honest fix is a stored column, which is its own
  ticket.

### Verification

Backend: `ruff`, `ruff format`, `mypy` clean over 444 files; **5,947 pass** (from
5,930) with the two known `.env` failures. Frontend: `tsc` clean, `biome` clean
over 222 files, **595 tests** (from 583), build compiles. Every fix
mutation-checked:

| mutation | result |
| --- | --- |
| ignore the confidence cutoff | 1 test fails |
| filter on `evaluation_outcome` again | 4 tests fail |
| count `received` as waiting again | 1 test fails |
| restore the empty-documents ordering | 1 test fails |
| interpolate the stripe class | 1 test fails |
