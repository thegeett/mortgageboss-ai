# LP-UI-016 — File overview: identity strip

- **Ticket:** LP-UI-016 — one identity strip, tabs into the context column
- **Epic:** Ledger redesign → Epic C (Core screens)
- **Status:** Completed
- **Date:** 2026-08-30
- **Mockup:** Overview — top strip

## Summary

The file header is one strip: who, which file, what kind of loan, whose lender
and where it stands on the left; the loan amount and the property it is secured
on set right. Two things left it — the back link became a topbar breadcrumb, and
the tab strip moved into the shell's context column.

**This closes the duplication raised on LP-UI-008.** That ticket put the six file
sections in the context column and noted the file page still rendered the same
six as a tab strip directly beneath the header — "the kind of thing that reads as
an unfinished migration". It was LP-UI-013's to decide and this is where it lands.

## What Changed

- `components/file/file-header.tsx` — rewritten as the identity strip.
- `components/layout/breadcrumb.tsx` (new) — `Pipeline / <borrower> <LF-ID>` in
  the topbar, reading the file from the query the layout already cached.
- `components/layout/header.tsx` — renders the breadcrumb instead of a title.
- `app/(protected)/loan-files/[id]/layout.tsx` — the tab strip is gone.
- **Deleted:** `components/file/file-tabs.tsx`, `lib/loan-files/tabs.ts` and its
  test — orphaned once the strip went (see Decisions).

## Verification

Measured in the browser on a real file:

| | |
|---|---|
| breadcrumb | `Pipeline / Bharat Kapadiya  LF-96SV` |
| strip | name + `Draft` status token, then `LF-96SV` · `Conventional` · `Purchase` |
| right | `$357,050` over `860 Balfour Drive` |
| tab strip | **gone** (`nav[aria-label="File sections"]` absent) |
| context column | Overview, Documents, Verification, Communication, Conditions, Lender package |

**Skeleton height, which took four attempts to measure honestly.** The criterion
is that the skeleton and the loaded strip are the same height, and my first
measurement said 52 vs 54 — a real 2px jump, fixed by setting the shared
`min-h` to the loaded strip's actual height rather than a guessed one.

Confirming the fix was harder than making it, and the failures are worth
recording because each looked like a result:

1. Sampling at 1.1s caught a **different** `[aria-busy]` element — the tab's
   loading block, not the header's — and reported 168px.
2. Targeting the header's own live region returned `null`: on localhost the
   query resolves faster than the probe can sample.
3. `Network.setBlockedURLs` held the request but produced the **error** state,
   which is a different screen (869px).
4. 4s of emulated latency held the request but the shell's auth loader was still
   up, so the header had not rendered at all.

What worked was forcing `<FileHeader file={undefined} />` in the layout,
measuring, and reverting: **skeleton 54px, loaded 54.4px** — 0.4px apart, below
one device pixel.

**CI.** biome, tsc, 605 tests, build — green.

## Decisions

- **Deleted `lib/loan-files/tabs.ts` rather than leaving it.** It held the same
  six sections `fileSections()` in `lib/navigation.ts` now owns, and two
  producers of one list is the shape three reviews in this epic have flagged.
  The one that renders should be the one that decides. Its `phase` metadata had
  no consumer — the placeholder pages hard-code their own copy.
- **The breadcrumb reads the cached file query**, so it costs no request. Before
  the file resolves it shows the id from the URL, which is real and already on
  screen — a skeleton there would flicker a word into a bar and back for a query
  that usually resolves instantly.
- **Status renders through `StatusToken`**, not the old `StatusBadge` pill, so
  the strip carries colour + glyph + word like every other status in the app.
- **Assumed** the context column is the only file navigation now. On a narrow
  screen the column is hidden below `md`, which means the file's sections are
  currently unreachable there — raised below.

## Finding raised

**Below `md`, a file's sections have no navigation.** The tab strip used to be
the mobile affordance: it scrolled horizontally and was always present. The
context column that replaced it is `hidden … md:block`, and the header's mobile
menu only carries top-level destinations (Dashboard, Administration). So on a
phone you can open a file and cannot reach its Documents or Verification tabs.

Not fixed here because the fix is a design decision rather than a patch — a
drawer, a select, or a horizontal strip that returns only below `md` — and
LP-UI-037 ("Narrow-width pass") is the ticket that owns exactly this question.
Recording it now so that ticket starts from a known defect rather than
rediscovering it.

## Files

- new: `components/layout/breadcrumb.tsx`
- changed: `components/file/file-header.tsx`, `components/layout/header.tsx`,
  `app/(protected)/loan-files/[id]/layout.tsx`, `lib/navigation.ts`
- deleted: `components/file/file-tabs.tsx`, `lib/loan-files/tabs.ts`,
  `lib/loan-files/tabs.test.ts`
