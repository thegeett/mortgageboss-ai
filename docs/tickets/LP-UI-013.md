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
